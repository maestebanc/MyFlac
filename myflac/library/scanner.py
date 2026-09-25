"""Escáner no bloqueante y ultrarrápido para la biblioteca de MyFlac."""
from __future__ import annotations

import os
import threading
from typing import Callable

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

from ..audio.track import AudioTrack, load_track
from ..constants import SUPPORTED_EXTENSIONS
from ..logger import get_logger
from .db import LibraryDB

log = get_logger("library.scanner")


class LibraryScanner:
    """Escáner multihilo optimizado para colecciones de audio Hi-Res."""

    def __init__(self, db: LibraryDB):
        self.db = db
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_scanning = False

    @property
    def is_scanning(self) -> bool:
        return self._is_scanning

    def stop(self) -> None:
        """Solicita la detención inmediata del escáner en curso."""
        self._stop_event.set()

    def start_scan(
        self,
        folders: list[str],
        quick: bool = True,
        on_progress: Callable[[int, int], None] | None = None,
        on_finished: Callable[[dict], None] | None = None,
    ) -> bool:
        """
        Inicia un escaneo en segundo plano.
        Si quick=True, compara mtime y tamaño contra la base de datos y salta archivos intactos.
        """
        if self._is_scanning:
            log.warning("Ya hay un escaneo de biblioteca en curso")
            return False

        valid_folders = [f for f in folders if os.path.isdir(f)]
        if not valid_folders:
            log.info("No se encontraron carpetas válidas para escanear")
            if on_finished:
                GLib.idle_add(on_finished, {"added_or_updated": 0, "deleted": 0, "stats": self.db.get_stats()})
            return False

        self._stop_event.clear()
        self._is_scanning = True

        def _worker():
            try:
                result = self._run_scan(valid_folders, quick=quick, on_progress=on_progress)
                log.info(
                    "Escaneo finalizado: %d añadidos/actualizados, %d eliminados",
                    result["added_or_updated"],
                    result["deleted"],
                )
            except Exception as e:
                log.exception("Error inesperado durante el escaneo de la biblioteca: %s", e)
                result = {"added_or_updated": 0, "deleted": 0, "error": str(e)}
            finally:
                self._is_scanning = False
                result["stats"] = self.db.get_stats()
                if on_finished and not self._stop_event.is_set():
                    GLib.idle_add(on_finished, result)

        self._thread = threading.Thread(target=_worker, name="MyFlacScannerThread", daemon=True)
        self._thread.start()
        return True

    def _run_scan(
        self,
        folders: list[str],
        quick: bool,
        on_progress: Callable[[int, int], None] | None,
    ) -> dict:
        log.info("Iniciando escaneo de biblioteca (quick=%s) en: %s", quick, folders)

        # 1. Obtener caché de archivos existentes en la base de datos
        cache = self.db.get_file_cache() if quick else {}
        log.debug("Caché de base de datos cargada con %d archivos", len(cache))

        seen_paths: set[str] = set()
        files_to_parse: list[tuple[str, str]] = []  # (filepath, root_folder)

        # 2. Recorrer árbol de carpetas con os.scandir (mucho más rápido que os.walk)
        for root_folder in folders:
            if self._stop_event.is_set():
                break

            stack = [root_folder]
            while stack:
                if self._stop_event.is_set():
                    break
                current_dir = stack.pop()
                try:
                    with os.scandir(current_dir) as it:
                        for entry in it:
                            if self._stop_event.is_set():
                                break
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(entry.path)
                                elif entry.is_file(follow_symlinks=False):
                                    name_lower = entry.name.lower()
                                    if any(name_lower.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
                                        p = entry.path
                                        seen_paths.add(p)
                                        stat = entry.stat()
                                        mtime = stat.st_mtime
                                        size = stat.st_size

                                        # Comprobación de caché
                                        if quick and p in cache:
                                            cached_mtime, cached_size = cache[p]
                                            if abs(cached_mtime - mtime) < 0.001 and cached_size == size:
                                                # Archivo idéntico: no hace falta parsear metadatos
                                                continue

                                        files_to_parse.append((p, root_folder))
                                        if on_progress and len(seen_paths) % 150 == 0:
                                            GLib.idle_add(on_progress, 0, 0)
                            except OSError:
                                continue
                except (OSError, PermissionError) as e:
                    log.warning("No se pudo leer el directorio %s: %s", current_dir, e)
                    continue

        if self._stop_event.is_set():
            return {"added_or_updated": 0, "deleted": 0, "cancelled": True}

        # 3. Detectar y purgar pistas eliminadas del disco
        deleted_paths = [
            p for p in cache
            if any(p.startswith(f) for f in folders) and p not in seen_paths
        ]
        deleted_count = 0
        if deleted_paths:
            deleted_count = self.db.delete_tracks_by_paths(deleted_paths)

        # 4. Parsear metadatos e insertar en lotes de 50
        total_to_parse = len(files_to_parse)
        log.info("Archivos a procesar: %d de %d encontrados", total_to_parse, len(seen_paths))

        batch: list[AudioTrack] = []
        batch_folder = ""
        processed = 0

        for filepath, root_folder in files_to_parse:
            if self._stop_event.is_set():
                break

            track = load_track(filepath)
            if track:
                batch.append(track)
                batch_folder = root_folder

            processed += 1

            if len(batch) >= 50:
                self.db.upsert_tracks(batch, folder_path=batch_folder)
                batch.clear()
                if on_progress:
                    GLib.idle_add(on_progress, processed, total_to_parse)

        # Insertar remanente
        if batch and not self._stop_event.is_set():
            self.db.upsert_tracks(batch, folder_path=batch_folder)
            batch.clear()
            if on_progress:
                GLib.idle_add(on_progress, processed, total_to_parse)

        return {
            "added_or_updated": processed,
            "deleted": deleted_count,
            "total_seen": len(seen_paths),
        }
