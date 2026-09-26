"""Servicio de obtención y almacenamiento en caché de letras de canciones (LRCLIB + fallback local)."""
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

from .audio.track import AudioTrack
from .logger import get_logger

log = get_logger("lyrics")

CACHE_DIR = os.path.expanduser("~/.cache/myflac/lyrics")


class LyricsService:
    """
    Servicio de letras en segundo plano:
    1. Verifica si la pista ya tiene letra embebida en sus metadatos (USLT / Vorbis).
    2. Consulta la caché local en disco (~/.cache/myflac/lyrics/).
    3. Consulta la API pública de LRCLIB (gratuita, sin clave de API).
    4. Fallback secundario a Lyrics.ovh.
    5. Guarda el resultado en caché y notifica mediante callback en el hilo principal de GLib.
    """

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._current_request_id = 0
        self._lock = threading.Lock()

    def fetch_lyrics(
        self,
        track: AudioTrack,
        callback: Callable[[str | None, str], None],
    ) -> int:
        """
        Inicia la búsqueda asíncrona de la letra para la pista especificada.
        callback(texto_letra, estado) donde estado puede ser:
        - 'ready': Letra encontrada y lista para mostrar.
        - 'instrumental': Pista identificada como instrumental.
        - 'not_found': No se encontró letra.
        - 'error': Error de red o consulta.
        Retorna el request_id actual para control de cancelaciones.
        """
        with self._lock:
            self._current_request_id += 1
            req_id = self._current_request_id

        # 1. Comprobar letras embebidas en el archivo de audio
        embedded = self._get_embedded_lyrics(track)
        if embedded:
            log.info("Letra encontrada embebida en metadatos para: %s - %s", track.artist, track.title)
            GLib.idle_add(callback, embedded, "ready")
            return req_id

        # 2. Comprobar caché en disco
        cache_key = self._get_cache_key(track.artist, track.title)
        cached_data = self._read_cache(cache_key)
        if cached_data is not None:
            log.info("Letra cargada desde caché local para: %s - %s", track.artist, track.title)
            if cached_data.get("instrumental"):
                GLib.idle_add(callback, None, "instrumental")
            elif cached_data.get("lyrics"):
                GLib.idle_add(callback, cached_data["lyrics"], "ready")
            else:
                GLib.idle_add(callback, None, "not_found")
            return req_id

        # 3. Consulta asíncrona en hilo secundario
        def _worker():
            lyrics, status = self._fetch_online(track)
            with self._lock:
                if req_id != self._current_request_id:
                    # La petición fue reemplazada por otra pista mientras descargaba
                    log.debug("Petición de letra #%d descartada por cambio de pista", req_id)
                    return

            # Guardar en caché
            self._write_cache(
                cache_key,
                {
                    "artist": track.artist,
                    "title": track.title,
                    "lyrics": lyrics,
                    "instrumental": (status == "instrumental"),
                    "status": status,
                },
            )

            # Notificar al hilo de interfaz de usuario
            GLib.idle_add(callback, lyrics, status)

        t = threading.Thread(target=_worker, name=f"lyrics-{req_id}", daemon=True)
        t.start()
        return req_id

    def cancel_current(self):
        """Invalida cualquier petición pendiente activa."""
        with self._lock:
            self._current_request_id += 1

    def _get_cache_key(self, artist: str | None, title: str | None) -> str:
        raw = f"{artist or ''}___{title or ''}".lower().strip()
        cleaned = re.sub(r"\s+", " ", raw)
        return hashlib.md5(cleaned.encode("utf-8")).hexdigest()

    def _read_cache(self, cache_key: str) -> dict | None:
        path = os.path.join(CACHE_DIR, f"{cache_key}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Error leyendo caché de letra %s: %e", cache_key, e)
            return None

    def _write_cache(self, cache_key: str, data: dict):
        path = os.path.join(CACHE_DIR, f"{cache_key}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Error escribiendo caché de letra %s: %e", cache_key, e)

    def _get_embedded_lyrics(self, track: AudioTrack) -> str | None:
        """Intenta extraer letras guardadas dentro del propio archivo de audio."""
        try:
            import mutagen
            mf = mutagen.File(track.filepath)
            if mf is None:
                return None

            # ID3 (MP3)
            if hasattr(mf, "tags") and mf.tags:
                for k in mf.tags.keys():
                    if k.startswith("USLT") or k.startswith("SYLT"):
                        frame = mf.tags[k]
                        if hasattr(frame, "text") and frame.text:
                            return str(frame.text).strip()

            # Vorbis / FLAC / OGG / OPUS
            for key in ("lyrics", "unsyncedlyrics", "unsynced_lyrics", "lyric"):
                val = mf.get(key)
                if val and len(val) > 0:
                    return str(val[0]).strip()
        except Exception as e:
            log.debug("Error comprobando letras embebidas: %s", e)
        return None

    def _fetch_online(self, track: AudioTrack) -> tuple[str | None, str]:
        """Consulta LRCLIB y proveedores alternativos."""
        title = track.title or ""
        artist = track.artist or ""

        # Limpiar sufijos típicos como "(Remastered)", "[Official Video]", "- Live", etc.
        clean_title = re.sub(r"\(.*?(remaster|live|official|deluxe|version|mono|stereo).*?\)", "", title, flags=re.I)
        clean_title = re.sub(r"\[.*?(remaster|live|official|deluxe|version|mono|stereo).*?\]", "", clean_title, flags=re.I)
        clean_title = clean_title.strip() or title

        # 1. Probar LRCLIB get exacto
        log.info("Consultando LRCLIB para: '%s' - '%s'", artist, clean_title)
        lyrics, status = self._query_lrclib_get(artist, clean_title, track.duration)
        if status in ("ready", "instrumental"):
            return lyrics, status

        # 2. Probar LRCLIB search si el get exacto no dio resultado
        lyrics, status = self._query_lrclib_search(artist, clean_title)
        if status in ("ready", "instrumental"):
            return lyrics, status

        # 3. Fallback a Lyrics.ovh
        lyrics = self._query_lyrics_ovh(artist, clean_title)
        if lyrics:
            return lyrics, "ready"

        return None, "not_found"

    def _query_lrclib_get(self, artist: str, title: str, duration: float | None) -> tuple[str | None, str]:
        try:
            params = {"artist_name": artist, "track_name": title}
            if duration and duration > 0:
                params["duration"] = str(int(duration))
            url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": "MyFlac/0.1.0 (https://github.com)"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("instrumental"):
                        return None, "instrumental"
                    lyrics = data.get("plainLyrics")
                    if not lyrics and data.get("syncedLyrics"):
                        # Extraer texto de líneas sincronizadas tipo [01:23.45] texto
                        lyrics = self._strip_lrc_timestamps(data["syncedLyrics"])
                    if lyrics and lyrics.strip():
                        return lyrics.strip(), "ready"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.debug("LRCLIB get 404 para '%s' - '%s'", artist, title)
            else:
                log.warning("LRCLIB HTTP error %s para '%s' - '%s'", e.code, artist, title)
        except Exception as e:
            log.debug("LRCLIB get error: %s", e)
        return None, "not_found"

    def _query_lrclib_search(self, artist: str, title: str) -> tuple[str | None, str]:
        try:
            query = f"{artist} {title}".strip()
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "MyFlac/0.1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    results = json.loads(resp.read().decode("utf-8"))
                    if isinstance(results, list) and len(results) > 0:
                        first = results[0]
                        if first.get("instrumental"):
                            return None, "instrumental"
                        lyrics = first.get("plainLyrics")
                        if not lyrics and first.get("syncedLyrics"):
                            lyrics = self._strip_lrc_timestamps(first["syncedLyrics"])
                        if lyrics and lyrics.strip():
                            return lyrics.strip(), "ready"
        except Exception as e:
            log.debug("LRCLIB search error: %s", e)
        return None, "not_found"

    def _query_lyrics_ovh(self, artist: str, title: str) -> str | None:
        try:
            url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(title)}"
            req = urllib.request.Request(url, headers={"User-Agent": "MyFlac/0.1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    lyrics = data.get("lyrics")
                    if lyrics and lyrics.strip():
                        return lyrics.strip()
        except Exception as e:
            log.debug("Lyrics.ovh error: %s", e)
        return None

    def _strip_lrc_timestamps(self, synced_text: str) -> str:
        """Elimina las marcas de tiempo [mm:ss.xx] para producir texto plano legible."""
        lines = []
        for line in synced_text.splitlines():
            cleaned = re.sub(r"\[\d+:\d+(?:\.\d+)?\]", "", line).strip()
            lines.append(cleaned)
        return "\n".join(lines).strip()
