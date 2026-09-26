"""
Portadas en alta resolución: busca en iTunes y Deezer la MISMA imagen que la portada incrustada
(normalmente 500 px) pero más grande. Solo se acepta si, reducidas a la misma escala, ambas imágenes
coinciden prácticamente píxel a píxel; si no, se sigue usando la portada incrustada.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable

from gi.repository import GLib
from PIL import Image

from .audio.track import AudioTrack
from .logger import get_logger

log = get_logger("hires_cover")

USER_AGENT = "MyFlac/0.1.0"
# No se busca nada si la portada incrustada ya es al menos así de grande
MIN_EMBEDDED_TO_SKIP = 1200
# La versión descargada debe ser al menos este factor mayor que la incrustada
MIN_UPSCALE_FACTOR = 1.5
ITUNES_SIZE = 2000
# Umbrales de "misma imagen", calibrados con 254 candidatas de la biblioteca:
# - la misma portada con otro escaneo, color o recorte leve da una correlación de 0.77-1.00;
# - otras maquetaciones o encuadres del mismo disco, 0.64-0.69; portadas de otros discos, <= 0.47.
# (Sin excepciones por diferencia de píxeles: en portadas casi blancas es mínima aunque cambie la
# maquetación, como en las reediciones de "Please" de Pet Shop Boys.)
MIN_CORRELATION = 0.75
# Tope al cambio del color medio: tolera otra corrección de color (hasta ~0.25 en portadas reales),
# no una edición recoloreada
MAX_MEAN_COLOR_DIFF = 0.30
# Formato: tolera escaneos algo recortados (p. ej. 500x466) frente a la portada digital cuadrada
MAX_ASPECT_DIFF = 0.10
NEGATIVE_CACHE_TTL = 30 * 24 * 3600
# Versión de los criterios: los "no encontrado" guardados con criterios anteriores se reintentan
MATCH_VERSION = 2


def _cache_dir() -> str:
    return os.path.join(GLib.get_user_cache_dir(), "myflac", "covers")


def _square(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((size, size), Image.Resampling.LANCZOS)


def image_similarity(a: Image.Image, b: Image.Image, size: int = 32) -> tuple[float, float]:
    """
    (correlación de luminancia, diferencia media de color 0-1) entre dos imágenes reducidas.
    La correlación tolera pequeños cambios de brillo o contraste entre ediciones de la misma imagen.
    """
    sa, sb = _square(a, size), _square(b, size)
    ga = list(sa.convert("L").tobytes())
    gb = list(sb.convert("L").tobytes())
    mean_a, mean_b = sum(ga) / len(ga), sum(gb) / len(gb)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(ga, gb))
    den = (sum((x - mean_a) ** 2 for x in ga) * sum((y - mean_b) ** 2 for y in gb)) ** 0.5
    correlation = num / den if den else (1.0 if ga == gb else 0.0)
    ca, cb = sa.tobytes(), sb.tobytes()
    color_diff = sum(abs(x - y) for x, y in zip(ca, cb)) / (len(ca) * 255)
    return correlation, color_diff


def mean_color_distance(a: Image.Image, b: Image.Image) -> float:
    """Distancia (0-1) entre los colores medios de dos imágenes."""
    ma = _square(a, 1).getpixel((0, 0))
    mb = _square(b, 1).getpixel((0, 0))
    return (sum((x - y) ** 2 for x, y in zip(ma, mb)) / 3) ** 0.5 / 255


def match_score(embedded: Image.Image, candidate: Image.Image) -> float | None:
    """Correlación con la portada incrustada si la candidata es la misma imagen; None si no lo es."""
    ea, ca = embedded.size, candidate.size
    if abs(ea[0] / ea[1] - ca[0] / ca[1]) > MAX_ASPECT_DIFF:
        return None
    if mean_color_distance(embedded, candidate) > MAX_MEAN_COLOR_DIFF:
        return None
    correlation, _pixel_diff = image_similarity(embedded, candidate)
    return correlation if correlation >= MIN_CORRELATION else None


def is_same_image(embedded: Image.Image, candidate: Image.Image) -> bool:
    return match_score(embedded, candidate) is not None


def _clean_album(album: str) -> str:
    """Quita coletillas de edición para una segunda búsqueda: '(2011 Remaster)', '[Deluxe]'..."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*", " ", album).strip()


class HiResCoverService:
    """Busca, verifica y cachea portadas en alta resolución, compartido por toda la aplicación."""

    _instance: HiResCoverService | None = None

    @classmethod
    def get_default(cls) -> HiResCoverService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._cache_dir = _cache_dir()
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
        except OSError as e:
            log.warning("No se pudo crear la caché de portadas %s: %s", self._cache_dir, e)
        self._pending: dict[str, list[Callable[[str | None], None]]] = {}

    # ------------------------------------------------------------------ API pública
    def cached_path(self, track: AudioTrack | None) -> str | None:
        """Ruta de la portada HD ya descargada para la pista, si existe."""
        key = self._key(track)
        if not key:
            return None
        path = os.path.join(self._cache_dir, f"{key}.jpg")
        return path if os.path.isfile(path) else None

    def prefetch(self, track: AudioTrack | None):
        """Descarga en segundo plano la portada HD de la pista (sin avisar a nadie)."""
        self.fetch(track, lambda _path: None)

    def fetch(self, track: AudioTrack | None, callback: Callable[[str | None], None]):
        """callback(ruta_hd o None) en el hilo principal. Una sola búsqueda por portada a la vez."""
        cover = track.get_cover_image_bytes() if track else None
        key = self._key(track, cover)
        if not key:
            GLib.idle_add(callback, None)
            return
        cached = os.path.join(self._cache_dir, f"{key}.jpg")
        if os.path.isfile(cached):
            GLib.idle_add(callback, cached)
            return
        if self._recent_not_found(key):
            GLib.idle_add(callback, None)
            return
        if key in self._pending:
            self._pending[key].append(callback)
            return
        self._pending[key] = [callback]

        artist, album, data = track.album_artist or track.artist, track.album, cover[0]

        def _worker():
            path = None
            try:
                path, definitive = self._find_and_save(artist, album, data, cached)
                if path is None and definitive:
                    self._write_not_found(key)
            except Exception as e:
                log.warning("Error buscando portada HD de %s — %s: %s", artist, album, e)
            GLib.idle_add(self._deliver, key, path)

        threading.Thread(target=_worker, name="hires-cover", daemon=True).start()

    # ------------------------------------------------------------------ internos
    def _key(self, track: AudioTrack | None, cover=None) -> str | None:
        if track is None or not track.album or not (track.artist or track.album_artist):
            return None
        cover = cover if cover is not None else track.get_cover_image_bytes()
        if not cover:
            return None
        # Clave por contenido de la portada: todas las pistas del álbum comparten resultado
        return hashlib.sha256(cover[0]).hexdigest()[:40]

    def _deliver(self, key: str, path: str | None) -> bool:
        for callback in self._pending.pop(key, []):
            try:
                callback(path)
            except Exception as e:
                log.exception("Error en callback de portada HD: %s", e)
        return False

    def _recent_not_found(self, key: str) -> bool:
        try:
            marker = os.path.join(self._cache_dir, f"{key}.none{MATCH_VERSION}")
            return time.time() - os.path.getmtime(marker) < NEGATIVE_CACHE_TTL
        except OSError:
            return False

    def _write_not_found(self, key: str):
        try:
            with open(os.path.join(self._cache_dir, f"{key}.none{MATCH_VERSION}"), "w", encoding="utf-8"):
                pass
        except OSError:
            pass

    def _get(self, url: str, raw: bool = False):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        return data if raw else json.loads(data.decode("utf-8"))

    def _candidates(self, artist: str, album: str) -> tuple[list[tuple[str, str, str]], bool]:
        """[(fuente, url_miniatura, url_grande)], y si ambas búsquedas respondieron."""
        found: list[tuple[str, str, str]] = []
        ok = True
        queries = [album]
        if _clean_album(album) and _clean_album(album) != album:
            queries.append(_clean_album(album))
        for query_album in queries:
            try:
                params = urllib.parse.urlencode({"term": f"{artist} {query_album}", "entity": "album", "limit": 10})
                for item in self._get(f"https://itunes.apple.com/search?{params}").get("results", []):
                    thumb = item.get("artworkUrl100")
                    if thumb and "100x100bb" in thumb:
                        found.append(("itunes", thumb, thumb.replace("100x100bb", f"{ITUNES_SIZE}x{ITUNES_SIZE}bb")))
            except Exception as e:
                ok = False
                log.debug("iTunes no respondió para %s — %s: %s", artist, query_album, e)
            try:
                params = urllib.parse.urlencode({"q": f'artist:"{artist}" album:"{query_album}"'})
                for item in self._get(f"https://api.deezer.com/search/album?{params}").get("data", [])[:10]:
                    if item.get("cover_medium") and item.get("cover_xl"):
                        found.append(("deezer", item["cover_medium"], item["cover_xl"]))
            except Exception as e:
                ok = False
                log.debug("Deezer no respondió para %s — %s: %s", artist, query_album, e)
            if found:
                break
        # Sin duplicados, y primero iTunes (ofrece más resolución)
        unique = list(dict.fromkeys(found))
        unique.sort(key=lambda c: c[0] != "itunes")
        return unique, ok

    def _find_and_save(self, artist: str, album: str, cover_bytes: bytes, target: str) -> tuple[str | None, bool]:
        embedded = Image.open(io.BytesIO(cover_bytes))
        embedded.load()
        if min(embedded.size) >= MIN_EMBEDDED_TO_SKIP:
            return None, True

        candidates, definitive = self._candidates(artist, album)

        # Puntuar todas las miniaturas (son pequeñas) y probar de la más parecida a la menos
        scored: list[tuple[float, str, str]] = []
        for source, thumb_url, big_url in candidates:
            try:
                thumb = Image.open(io.BytesIO(self._get(thumb_url, raw=True)))
                thumb.load()
            except Exception as e:
                definitive = False
                log.debug("No se pudo descargar la miniatura %s: %s", thumb_url, e)
                continue
            score = match_score(embedded, thumb)
            if score is not None:
                scored.append((score, source, big_url))
        # Con puntuaciones casi iguales, iTunes primero: ofrece más resolución
        scored.sort(key=lambda c: (round(c[0], 2), c[1] == "itunes"), reverse=True)

        for score, source, big_url in scored:
            try:
                big_bytes = self._get(big_url, raw=True)
                big = Image.open(io.BytesIO(big_bytes))
                big.load()
            except Exception as e:
                definitive = False
                log.debug("No se pudo descargar la candidata %s: %s", big_url, e)
                continue
            if min(big.size) < min(embedded.size) * MIN_UPSCALE_FACTOR:
                continue
            # Segunda comprobación con la imagen grande real (la miniatura podría no corresponder)
            if not is_same_image(embedded, big):
                log.debug("Candidata %s descartada al comprobar la imagen grande", big_url)
                continue
            tmp = f"{target}.tmp.{os.getpid()}.{threading.get_ident()}"
            with open(tmp, "wb") as f:
                f.write(big_bytes)
            os.replace(tmp, target)
            log.info(
                "Portada HD (%s, %dx%d, similitud %.2f) para %s — %s",
                source, big.size[0], big.size[1], score, artist, album,
            )
            return target, True

        log.info("Sin portada HD idéntica para %s — %s; se usa la incrustada", artist, album)
        return None, definitive
