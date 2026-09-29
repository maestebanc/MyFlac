"""
Diagnóstico de cuelgues: si el bucle principal de GTK deja de responder, deja en el log dónde está
cada hilo, para poder analizarlo aunque luego haya que cerrar la aplicación a la fuerza.

- Un temporizador de GLib marca el pulso del hilo principal cada 250 ms.
- Un hilo vigilante comprueba el pulso; si pasan más de STALL_S sin él, escribe la pila de todos los
  hilos (el principal primero) y la memoria en uso. Al recuperarse, anota cuánto duró el bloqueo.
- faulthandler escribe en el log las pilas si el proceso muere por una señal (SIGSEGV, SIGABRT...),
  y `kill -USR1 <pid>` las vuelca a demanda.
- La memoria se anota cuando cruza nuevos umbrales (500 MB, 750 MB, 1 GB...).
"""
from __future__ import annotations

import faulthandler
import signal
import sys
import threading
import time
import traceback

from gi.repository import GLib

from .logger import get_log_path, get_logger

log = get_logger("watchdog")

STALL_S = 3.0
_BEAT_MS = 250
_MEMORY_STEP_MB = 250
_MEMORY_FIRST_MB = 500

_fault_file = None


def _rss_mb() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            return int(f.read().split()[1]) * 4096 // 2**20
    except (OSError, ValueError, IndexError):
        return -1


def _format_threads(main_ident: int) -> str:
    frames = sys._current_frames()
    names = {t.ident: t.name for t in threading.enumerate()}
    order = sorted(frames, key=lambda ident: ident != main_ident)
    parts = []
    for ident in order:
        label = "PRINCIPAL" if ident == main_ident else names.get(ident, "?")
        stack = "".join(traceback.format_stack(frames[ident]))
        parts.append(f"--- Hilo {label} ({ident}) ---\n{stack}")
    return "\n".join(parts)


class MainLoopWatchdog:
    def __init__(self):
        self._main_ident = threading.main_thread().ident
        self._last_beat = time.monotonic()
        self._stalled_since: float | None = None
        self._next_memory_mark = _MEMORY_FIRST_MB
        GLib.timeout_add(_BEAT_MS, self._beat)
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def _beat(self) -> bool:
        self._last_beat = time.monotonic()
        return True

    def _watch(self):
        while True:
            time.sleep(1.0)
            now = time.monotonic()
            silent = now - self._last_beat
            if silent > STALL_S and self._stalled_since is None:
                self._stalled_since = self._last_beat
                log.error("La interfaz no responde desde hace %.1f s (memoria: %d MB). Pilas de los hilos:\n%s",
                          silent, _rss_mb(), _format_threads(self._main_ident))
            elif silent <= STALL_S and self._stalled_since is not None:
                log.warning("La interfaz vuelve a responder tras %.1f s bloqueada",
                            self._last_beat - self._stalled_since)
                self._stalled_since = None

            rss = _rss_mb()
            if rss >= self._next_memory_mark:
                log.warning("Memoria en uso: %d MB", rss)
                while self._next_memory_mark <= rss:
                    self._next_memory_mark += _MEMORY_STEP_MB


def install():
    """Activa faulthandler sobre el archivo de log y el vigilante del bucle principal."""
    global _fault_file
    try:
        _fault_file = open(get_log_path(), "a", encoding="utf-8")  # Se mantiene abierto: faulthandler escribe en su fd
        faulthandler.enable(file=_fault_file, all_threads=True)
        faulthandler.register(signal.SIGUSR1, file=_fault_file, all_threads=True)
    except (OSError, ValueError, AttributeError) as e:
        log.warning("No se pudo activar faulthandler: %s", e)
    MainLoopWatchdog()
