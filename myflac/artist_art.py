"""Servicio asíncrono para obtención y almacenamiento en caché de fotografías de artistas (Deezer + Wikipedia)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from typing import Callable

from gi.repository import GLib

from .logger import get_logger

log = get_logger("artist_art")

CACHE_DIR = os.path.expanduser("~/.cache/myflac/artists")


def _clean_artist_name(name: str) -> str:
    """Limpia el nombre del artista quitando menciones de colaboradores y texto entre paréntesis."""
    if not name:
        return ""
    # Quitar sufijos comunes de colaboración (ej. "feat. ...", "ft. ...", "vs. ...")
    clean = re.sub(r"\s+(feat\.?|ft\.?|vs\.?|with)\s+.*$", "", name, flags=re.IGNORECASE)
    # Si hay barra o coma (varios artistas), tomar el principal
    clean = re.split(r"[/,;&]", clean)[0]
    return clean.strip()


class ArtistArtService:
    """
    Servicio de obtención asíncrona de retratos de artistas para wallpapers en el Super-Reproductor:
    1. Verifica si la imagen ya existe en la caché local (~/.cache/myflac/artists/).
    2. Consulta la API pública de Deezer (resolución 1000x1000 sin autenticación).
    3. Fallback a la API de Wikipedia (artículo del artista).
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
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._current_request_id = 0
        self._lock = threading.Lock()

    def _get_cache_key(self, artist: str) -> str:
        norm = artist.strip().lower()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

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
        cached_file = os.path.join(CACHE_DIR, f"{cache_key}.jpg")

        # 1. Comprobar caché en disco
        if os.path.isfile(cached_file) and os.path.getsize(cached_file) > 1024:
            log.debug("Foto de artista cargada desde caché para: %s (%s)", clean_name, cached_file)
            GLib.idle_add(callback, cached_file)
            return req_id

        # 2. Descarga asíncrona en hilo de trabajo
        def _worker():
            image_url = self._resolve_artist_url(clean_name)
            if not image_url:
                log.info("No se encontró imagen pública para el artista: %s", clean_name)
                GLib.idle_add(callback, None)
                return

            with self._lock:
                if req_id != self._current_request_id:
                    log.debug("Descarga de foto descartada para %s (req #%d superado)", clean_name, req_id)
                    return

            # Descargar archivo
            downloaded_path = self._download_image(image_url, cached_file)
            with self._lock:
                if req_id != self._current_request_id:
                    return

            if downloaded_path:
                log.info("Foto descargada con éxito para %s (%s)", clean_name, downloaded_path)
                GLib.idle_add(callback, downloaded_path)
            else:
                GLib.idle_add(callback, None)

        t = threading.Thread(target=_worker, name=f"artist-art-{req_id}", daemon=True)
        t.start()
        return req_id

    def _resolve_artist_url(self, artist_name: str) -> str | None:
        """Busca la URL de la imagen en Deezer y si falla en Wikipedia."""
        # 1. Deezer API
        try:
            query = urllib.parse.quote(artist_name)
            url = f"https://api.deezer.com/search/artist?q={query}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MyFlac/0.1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                artists = data.get("data", [])
                if artists:
                    first = artists[0]
                    # Preferir picture_xl (1000x1000) o picture_big (500x500)
                    pic_url = first.get("picture_xl") or first.get("picture_big") or first.get("picture_medium")
                    if pic_url:
                        return pic_url
        except Exception as e:
            log.debug("Error consultando Deezer para %s: %s", artist_name, e)

        # 2. Fallback Wikipedia API
        try:
            query = urllib.parse.quote(artist_name)
            wiki_url = (
                f"https://en.wikipedia.org/w/api.php?action=query&titles={query}"
                f"&prop=pageimages&format=json&pithumbsize=1200"
            )
            req = urllib.request.Request(
                wiki_url,
                headers={"User-Agent": "MyFlac/0.1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pages = data.get("query", {}).get("pages", {})
                for _pid, page in pages.items():
                    thumb = page.get("thumbnail", {}).get("source")
                    if thumb:
                        return thumb
        except Exception as e:
            log.debug("Error consultando Wikipedia para %s: %s", artist_name, e)

        return None

    def _download_image(self, url: str, target_file: str) -> str | None:
        """Descarga la imagen a un archivo temporal y luego lo mueve atómicamente a target_file."""
        tmp_file = f"{target_file}.tmp.{os.getpid()}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MyFlac/0.1.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                with open(tmp_file, "wb") as f:
                    while chunk := resp.read(16384):
                        f.write(chunk)

            if os.path.exists(tmp_file) and os.path.getsize(tmp_file) > 1024:
                os.replace(tmp_file, target_file)
                return target_file
            else:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
                return None
        except Exception as e:
            log.warning("Fallo al descargar imagen desde %s: %s", url, e)
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass
            return None
