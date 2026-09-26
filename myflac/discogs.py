"""
Cliente mínimo de la API pública de Discogs (sin cuenta): búsqueda de discos y artistas, ediciones,
créditos y perfiles. Sin autenticación Discogs permite 25 peticiones por minuto y no devuelve imágenes.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

from .logger import get_logger

log = get_logger("discogs")

API = "https://api.discogs.com"
USER_AGENT = "MyFlac/0.1.0 +https://github.com/maestebanc/MyFlac"
# 25 peticiones/minuto sin cuenta: una cada 2,4 s como mínimo
MIN_INTERVAL = 2.4
_lock = threading.Lock()
_last_request = [0.0]


class DiscogsRateLimited(Exception):
    """Discogs pidió esperar: no se guarda nada en caché y se reintenta más tarde."""


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    text = re.sub(r"\s*\(\d+\)$", "", text.strip())  # Discogs distingue homónimos con "(2)"
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def discogs_to_markup(text: str) -> str:
    """Convierte el marcado de Discogs ([a=Nombre], [l=Sello], [b]...[/b], [url=...]...[/url]) a Pango."""
    if not text:
        return ""
    markup = GLib.markup_escape_text(text.replace("\r\n", "\n").strip())
    markup = re.sub(r"\[url=([^\]]+)\](.*?)\[/url\]",
                    lambda m: f'<a href="{m.group(1)}">{m.group(2)}</a>', markup, flags=re.S)
    markup = re.sub(r"\[b\](.*?)\[/b\]", r"<b>\1</b>", markup, flags=re.S)
    markup = re.sub(r"\[i\](.*?)\[/i\]", r"<i>\1</i>", markup, flags=re.S)
    # Referencias con nombre: [a=Artista], [l=Sello], [m=...], [r=...]
    markup = re.sub(r"\[[almr]=([^\]]+)\]", lambda m: re.sub(r"\s*\(\d+\)$", "", m.group(1)), markup)
    # Referencias solo por número ([a123456]): no se puede mostrar el nombre sin otra petición
    markup = re.sub(r"\[[almr]\d+\]", "", markup)
    markup = re.sub(r"\[/?[a-z]+\]", "", markup)  # cualquier otra etiqueta que quede
    return re.sub(r"\n{3,}", "\n\n", markup).strip()


def clean_name(name: str) -> str:
    """'Sean Carey (3)' -> 'Sean Carey'."""
    return re.sub(r"\s*\(\d+\)$", "", name or "").strip()


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise DiscogsRateLimited() from e
            raise
        finally:
            _last_request[0] = time.monotonic()


def find_master(artist: str, album: str) -> dict | None:
    """Disco (master) de Discogs con su edición principal: {'master': ..., 'release': ...}."""
    wanted_artist, wanted_album = normalize(artist), normalize(album)
    for kind in ("master", "release"):
        results = _get("/database/search", {"artist": artist, "release_title": album, "type": kind, "per_page": 10})
        for result in results.get("results", []):
            # El título de un resultado es "Artista - Disco"
            found_artist, _, found_album = (result.get("title") or "").partition(" - ")
            if normalize(found_album) != wanted_album or wanted_artist[:10] not in normalize(found_artist):
                continue
            if kind == "master":
                master = _get(f"/masters/{result['id']}")
                release = _get(f"/releases/{master['main_release']}") if master.get("main_release") else {}
                return {"master": master, "release": release}
            release = _get(f"/releases/{result['id']}")
            return {"master": {}, "release": release}
    return None


def find_artist(name: str) -> dict | None:
    """Ficha de artista de Discogs cuyo nombre coincide exactamente."""
    wanted = normalize(name)
    results = _get("/database/search", {"q": name, "type": "artist", "per_page": 10})
    for result in results.get("results", []):
        if normalize(result.get("title", "")) == wanted:
            return _get(f"/artists/{result['id']}")
    return None


def track_credits(release: dict, title: str) -> tuple[dict | None, list[tuple[str, str]]]:
    """(pista de la edición, [(rol, nombres)]) para el tema: créditos propios y los del disco que lo incluyen."""
    wanted = normalize(re.sub(r"\s*[\(\[].*$", "", title))
    track = next((t for t in release.get("tracklist", [])
                  if t.get("type_", "track") == "track" and normalize(re.sub(r"\s*[\(\[].*$", "", t.get("title", ""))) == wanted),
                 None)
    if track is None:
        return None, []
    position = track.get("position", "")
    credits = list(track.get("extraartists", []))
    for credit in release.get("extraartists", []):
        if _credit_applies(credit.get("tracks", ""), position):
            credits.append(credit)
    return track, group_credits(credits)


def _credit_applies(tracks: str, position: str) -> bool:
    """¿Un crédito del disco con "tracks": "A1 to B2, C3" se refiere a esta posición?"""
    if not tracks.strip() or not position:
        return False
    for part in tracks.split(","):
        part = part.strip()
        if " to " in part:
            start, _, end = part.partition(" to ")
            if _position_key(start) <= _position_key(position) <= _position_key(end):
                return True
        elif part == position:
            return True
    return False


def _position_key(position: str) -> tuple:
    match = re.match(r"([A-Za-z]*)[\-\.]?(\d*)", position.strip())
    side, number = (match.group(1), match.group(2)) if match else ("", "")
    return (side.upper(), int(number) if number else 0)


def group_credits(credits: list[dict]) -> list[tuple[str, str]]:
    """[(rol, "Nombre, Nombre")] agrupados por rol en orden de aparición y sin duplicados."""
    grouped: dict[str, list[str]] = {}
    for credit in credits:
        role = (credit.get("role") or "").strip()
        # El nombre real del artista, no la variante con la que aparece en esa edición ("BMoen")
        name = clean_name(credit.get("name") or credit.get("anv", ""))
        if role and name and name not in grouped.setdefault(role, []):
            grouped[role].append(name)
    return [(role, ", ".join(names)) for role, names in grouped.items()]
