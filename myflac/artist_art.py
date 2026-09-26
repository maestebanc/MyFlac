"""Servicio asíncrono para obtención y almacenamiento en caché de fotografías de artistas (Deezer + Wikipedia)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Callable

from gi.repository import GLib

from .logger import get_logger

log = get_logger("artist_art")

USER_AGENT = "MyFlac/0.1.0"

# Tiempo que se recuerda que un artista no tiene foto pública antes de volver a preguntar
NEGATIVE_CACHE_TTL = 7 * 24 * 3600

# Palabras de la descripción corta de Wikipedia que identifican una página musical
_MUSIC_DESCRIPTION_RE = re.compile(
    r"\b(band|musician|singer|rapper|composer|songwriter|group|duo|trio|dj|producer|guitarist|"
    r"pianist|drummer|bassist|violinist|cellist|orchestra|ensemble|conductor|vocalist|music)",
    re.IGNORECASE,
)
_WIKIPEDIA_SUFFIXES = ("band", "musician", "singer", "rapper")


def _cache_dir() -> str:
    # GLib respeta XDG_CACHE_HOME, que en Flatpak apunta a ~/.var/app/<id>/cache (escribible)
    return os.path.join(GLib.get_user_cache_dir(), "myflac", "artists")


def _clean_artist_name(name: str) -> str:
    """Limpia el nombre del artista quitando menciones de colaboradores y texto entre paréntesis."""
    if not name:
        return ""
    # Quitar sufijos comunes de colaboración (ej. "feat. ...", "ft. ...", "vs. ...")
    clean = re.sub(r"\s+(feat\.?|ft\.?|vs\.?|with)\s+.*$", "", name, flags=re.IGNORECASE)
    # Si hay barra o coma (varios artistas), tomar el principal
    clean = re.split(r"[/,;&]", clean)[0]
    return clean.strip()


def _normalize_name(name: str) -> str:
    """Normaliza para comparar nombres: sin acentos, mayúsculas, artículo inicial ni puntuación."""
    decomposed = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    text = re.sub(r"^the\s+", "", text.strip())
    return re.sub(r"[^\w]+", "", text)


def _pick_deezer_picture(artist_name: str, results: list[dict]) -> str | None:
    """Elige la foto del resultado de Deezer cuyo nombre coincide, descartando la silueta genérica."""
    target = _normalize_name(artist_name)
    matches = [a for a in results if _normalize_name(a.get("name", "")) == target]
    # Entre homónimos, el más seguido suele ser el que se escucha
    for artist in sorted(matches, key=lambda a: a.get("nb_fan", 0), reverse=True):
        url = artist.get("picture_xl") or artist.get("picture_big") or artist.get("picture_medium")
        # Sin foto, Deezer devuelve una silueta genérica con el hash vacío: /images/artist//...
        if url and "/images/artist//" not in url:
            return url
    return None


def _pick_wikipedia_thumbnail(candidates: list[str], query: dict) -> str | None:
    """Elige la miniatura del primer título candidato que sea una página musical (no desambiguación)."""
    redirects = {r["from"]: r["to"] for r in query.get("redirects", [])}
    normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
    pages = {p.get("title"): p for p in query.get("pages", [])}

    for title in candidates:
        final = normalized.get(title, title)
        final = redirects.get(final, final)
        page = pages.get(final)
        if not page or page.get("missing") or "disambiguation" in page.get("pageprops", {}):
            continue
        if not _MUSIC_DESCRIPTION_RE.search(page.get("description", "")):
            continue
        thumb = page.get("thumbnail", {}).get("source")
        if thumb:
            return thumb
    return None


class ArtistArtService:
    """
    Servicio de obtención asíncrona de retratos de artistas para wallpapers en el Super-Reproductor:
    1. Verifica si la imagen (o la ausencia de imagen) ya está en la caché local.
    2. Consulta la API pública de Deezer (resolución 1000x1000 sin autenticación).
    3. Fallback a la API de Wikipedia (páginas musicales del artista).
    4. Descarga la imagen y la guarda en la caché.
    5. Notifica al hilo principal mediante GLib.idle_add(callback, image_path).
    """

    _instance: ArtistArtService | None = None

    @classmethod
    def get_default(cls) -> ArtistArtService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._cache_dir = _cache_dir()
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
        except OSError as e:
            log.warning("No se pudo crear la caché de artistas %s: %s", self._cache_dir, e)
        self._current_request_id = 0
        self._lock = threading.Lock()

    def _get_cache_key(self, artist: str) -> str:
        norm = artist.strip().lower()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def _is_current(self, req_id: int) -> bool:
        with self._lock:
            return req_id == self._current_request_id

    def fetch_artist_image(
        self,
        artist: str,
        callback: Callable[[str | None], None],
    ) -> int:
        """
        Inicia la búsqueda asíncrona de la imagen del artista.
        callback(image_path_or_none) se invocará en el hilo principal de GLib.
        Retorna el request_id actual para control de cancelaciones.
        """
        clean_name = _clean_artist_name(artist)
        if not clean_name:
            GLib.idle_add(callback, None)
            return 0

        with self._lock:
            self._current_request_id += 1
            req_id = self._current_request_id

        cache_key = self._get_cache_key(clean_name)
        cached_file = os.path.join(self._cache_dir, f"{cache_key}.jpg")
        not_found_marker = os.path.join(self._cache_dir, f"{cache_key}.none")

        # 1. Comprobar caché en disco (positiva y negativa)
        if os.path.isfile(cached_file) and os.path.getsize(cached_file) > 1024:
            log.debug("Foto de artista cargada desde caché para: %s (%s)", clean_name, cached_file)
            GLib.idle_add(self._deliver, req_id, callback, cached_file)
            return req_id
        if self._is_recent_not_found(not_found_marker):
            log.debug("Artista sin foto pública (caché negativa): %s", clean_name)
            GLib.idle_add(self._deliver, req_id, callback, None)
            return req_id

        # 2. Descarga asíncrona en hilo de trabajo
        def _worker():
            image_url, definitive = self._resolve_artist_url(clean_name)
            if not self._is_current(req_id):
                log.debug("Búsqueda de foto descartada para %s (req #%d superado)", clean_name, req_id)
                return

            if not image_url:
                log.info("No se encontró imagen pública para el artista: %s", clean_name)
                # Solo se recuerda si ambos servicios respondieron; un fallo de red se reintenta
                if definitive:
                    self._write_not_found(not_found_marker)
                GLib.idle_add(self._deliver, req_id, callback, None)
                return

            downloaded_path = self._download_image(image_url, cached_file)
            if downloaded_path:
                log.info("Foto descargada con éxito para %s (%s)", clean_name, downloaded_path)
            GLib.idle_add(self._deliver, req_id, callback, downloaded_path)

        t = threading.Thread(target=_worker, name=f"artist-art-{req_id}", daemon=True)
        t.start()
        return req_id

    def _deliver(self, req_id: int, callback: Callable[[str | None], None], path: str | None) -> bool:
        # Comprobado en el hilo principal: una petición superada nunca pisa el fondo del artista actual
        if self._is_current(req_id):
            callback(path)
        return False

    def _is_recent_not_found(self, marker: str) -> bool:
        try:
            return time.time() - os.path.getmtime(marker) < NEGATIVE_CACHE_TTL
        except OSError:
            return False

    def _write_not_found(self, marker: str):
        try:
            with open(marker, "w", encoding="utf-8"):
                pass
        except OSError as e:
            log.debug("No se pudo guardar la caché negativa %s: %s", marker, e)

    def _get_json(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _resolve_artist_url(self, artist_name: str) -> tuple[str | None, bool]:
        """
        Busca la URL de la imagen en Deezer y si falla en Wikipedia.
        Retorna (url, definitivo): definitivo es False si algún servicio falló por red.
        """
        definitive = True

        # 1. Deezer API
        try:
            query = urllib.parse.quote(artist_name)
            data = self._get_json(f"https://api.deezer.com/search/artist?q={query}")
            pic_url = _pick_deezer_picture(artist_name, data.get("data", []))
            if pic_url:
                return pic_url, True
        except Exception as e:
            definitive = False
            log.debug("Error consultando Deezer para %s: %s", artist_name, e)

        # 2. Fallback Wikipedia API: "X (band)", "X (musician)", ... y por último "X"
        try:
            candidates = [f"{artist_name} ({suffix})" for suffix in _WIKIPEDIA_SUFFIXES] + [artist_name]
            params = urllib.parse.urlencode({
                "action": "query",
                "titles": "|".join(candidates),
                "redirects": 1,
                "prop": "pageimages|pageprops|description",
                "ppprop": "disambiguation",
                "pithumbsize": 1200,
                "format": "json",
                "formatversion": 2,
            })
            data = self._get_json(f"https://en.wikipedia.org/w/api.php?{params}")
            thumb = _pick_wikipedia_thumbnail(candidates, data.get("query", {}))
            if thumb:
                return thumb, True
        except Exception as e:
            definitive = False
            log.debug("Error consultando Wikipedia para %s: %s", artist_name, e)

        return None, definitive

    def _download_image(self, url: str, target_file: str) -> str | None:
        """Descarga la imagen a un archivo temporal y luego lo mueve atómicamente a target_file."""
        tmp_file = f"{target_file}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as resp:
                with open(tmp_file, "wb") as f:
                    while chunk := resp.read(16384):
                        f.write(chunk)

            if os.path.getsize(tmp_file) > 1024:
                os.replace(tmp_file, target_file)
                return target_file
            os.remove(tmp_file)
            return None
        except Exception as e:
            log.warning("Fallo al descargar imagen desde %s: %s", url, e)
            try:
                os.remove(tmp_file)
            except OSError:
                pass
            return None
