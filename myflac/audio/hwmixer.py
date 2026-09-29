"""
Volumen por hardware del DAC (mezclador ALSA de la tarjeta) para el modo exclusivo.

En exclusivo la señal digital llega intacta al DAC y el volumen de GStreamer queda fijo a 0 dB.
Si la tarjeta tiene control de volumen propio (p. ej. el Feature Unit de un DAC USB), se ajusta
ahí: la atenuación la hace el DAC y la muestra no se toca.

Se usa libasound directamente con ctypes (sin dependencias extra; también está en Flatpak).
La curva sigue a alsamixer (volume_mapping.c): lineal en rangos pequeños y logarítmica en dB
en el resto, para que el deslizador se comporte de forma natural al oído.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import math

from ..logger import get_logger

log = get_logger("audio.hwmixer")

_SND_MIXER_SCHN_FRONT_LEFT = 0
_SND_CTL_TLV_DB_GAIN_MUTE = -9999999
_MAX_LINEAR_DB_SCALE = 24  # dB: por debajo de este rango se usa escala lineal

# Controles preferidos, por orden; si no hay ninguno se usa el primero con volumen de reproducción
_PREFERRED = ("PCM", "Master", "Speaker", "Headphone", "Digital", "Line Out")
_EXCLUDED = ("mic", "capture", "boost", "input", "loopback")

_lib: ctypes.CDLL | None = None


def _alsa() -> ctypes.CDLL | None:
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("asound") or "libasound.so.2"
        try:
            lib = ctypes.CDLL(name)
        except OSError as e:
            log.warning("libasound no disponible: %s", e)
            return None
        c_long_p = ctypes.POINTER(ctypes.c_long)
        vp = ctypes.c_void_p
        lib.snd_mixer_open.argtypes = [ctypes.POINTER(vp), ctypes.c_int]
        lib.snd_mixer_attach.argtypes = [vp, ctypes.c_char_p]
        lib.snd_mixer_selem_register.argtypes = [vp, vp, vp]
        lib.snd_mixer_load.argtypes = [vp]
        lib.snd_mixer_close.argtypes = [vp]
        lib.snd_mixer_handle_events.argtypes = [vp]
        lib.snd_mixer_first_elem.argtypes = [vp]
        lib.snd_mixer_first_elem.restype = vp
        lib.snd_mixer_elem_next.argtypes = [vp]
        lib.snd_mixer_elem_next.restype = vp
        lib.snd_mixer_selem_get_name.argtypes = [vp]
        lib.snd_mixer_selem_get_name.restype = ctypes.c_char_p
        lib.snd_mixer_selem_get_index.argtypes = [vp]
        lib.snd_mixer_selem_is_active.argtypes = [vp]
        lib.snd_mixer_selem_has_playback_volume.argtypes = [vp]
        lib.snd_mixer_selem_get_playback_volume_range.argtypes = [vp, c_long_p, c_long_p]
        lib.snd_mixer_selem_get_playback_volume.argtypes = [vp, ctypes.c_int, c_long_p]
        lib.snd_mixer_selem_set_playback_volume_all.argtypes = [vp, ctypes.c_long]
        lib.snd_mixer_selem_get_playback_dB_range.argtypes = [vp, c_long_p, c_long_p]
        lib.snd_mixer_selem_get_playback_dB.argtypes = [vp, ctypes.c_int, c_long_p]
        lib.snd_mixer_selem_set_playback_dB_all.argtypes = [vp, ctypes.c_long, ctypes.c_int]
        _lib = lib
    return _lib


def normalized_from_db(value: int, min_db: int, max_db: int) -> float:
    """Posición 0..1 del deslizador para un valor en centésimas de dB (curva de alsamixer)."""
    normalized = 10 ** ((value - max_db) / 6000.0)
    if min_db != _SND_CTL_TLV_DB_GAIN_MUTE:
        min_norm = 10 ** ((min_db - max_db) / 6000.0)
        normalized = (normalized - min_norm) / (1 - min_norm)
    return max(0.0, min(1.0, normalized))


def db_from_normalized(volume: float, min_db: int, max_db: int) -> int:
    """Centésimas de dB para una posición 0..1 del deslizador (inversa de normalized_from_db)."""
    volume = max(0.0, min(1.0, volume))
    if min_db != _SND_CTL_TLV_DB_GAIN_MUTE:
        min_norm = 10 ** ((min_db - max_db) / 6000.0)
        volume = volume * (1 - min_norm) + min_norm
    if volume <= 0.0:
        return min_db
    return int(round(6000.0 * math.log10(volume))) + max_db


class HardwareMixer:
    """Control de volumen de reproducción de una tarjeta ALSA (hw:N)."""

    def __init__(self, handle, elem, name: str):
        self._handle = handle
        self._elem = elem
        self.name = name
        lib = _alsa()
        lo, hi = ctypes.c_long(), ctypes.c_long()
        lib.snd_mixer_selem_get_playback_volume_range(elem, ctypes.byref(lo), ctypes.byref(hi))
        self._min, self._max = lo.value, hi.value
        self._use_db = False
        # Valor que tenía el control al abrirlo (el de PipeWire): se restaura al devolver la tarjeta
        self._initial_raw = self._get_raw()
        self._modified = False
        if lib.snd_mixer_selem_get_playback_dB_range(elem, ctypes.byref(lo), ctypes.byref(hi)) == 0:
            self._min_db, self._max_db = lo.value, hi.value
            self._use_db = self._max_db - self._min_db > _MAX_LINEAR_DB_SCALE * 100

    @classmethod
    def open(cls, card: int) -> HardwareMixer | None:
        """Abre el mezclador de la tarjeta. None si no tiene control de volumen de reproducción."""
        lib = _alsa()
        if lib is None or card is None:
            return None
        handle = ctypes.c_void_p()
        if lib.snd_mixer_open(ctypes.byref(handle), 0) < 0:
            return None
        ok = (lib.snd_mixer_attach(handle, f"hw:{card}".encode()) >= 0
              and lib.snd_mixer_selem_register(handle, None, None) >= 0
              and lib.snd_mixer_load(handle) >= 0)
        if not ok:
            lib.snd_mixer_close(handle)
            return None

        candidates = []
        elem = lib.snd_mixer_first_elem(handle)
        while elem:
            if lib.snd_mixer_selem_is_active(elem) and lib.snd_mixer_selem_has_playback_volume(elem):
                name = (lib.snd_mixer_selem_get_name(elem) or b"").decode(errors="replace")
                index = lib.snd_mixer_selem_get_index(elem)
                if not any(word in name.lower() for word in _EXCLUDED):
                    candidates.append((name, index, elem))
            elem = lib.snd_mixer_elem_next(elem)
        if not candidates:
            lib.snd_mixer_close(handle)
            return None

        def rank(c):
            name, index, _ = c
            pref = next((i for i, p in enumerate(_PREFERRED) if name.strip().lower() == p.lower()), len(_PREFERRED))
            return (pref, index)

        name, index, elem = min(candidates, key=rank)
        mixer = cls(handle, elem, f"{name.strip()},{index}")
        log.info("Volumen por hardware en hw:%d: '%s' (%s)", card, mixer.name, "dB" if mixer._use_db else "lineal")
        return mixer

    def get_volume(self) -> float:
        lib = _alsa()
        lib.snd_mixer_handle_events(self._handle)  # Recoge cambios hechos por otros (alsamixer...)
        value = ctypes.c_long()
        if self._use_db:
            lib.snd_mixer_selem_get_playback_dB(self._elem, _SND_MIXER_SCHN_FRONT_LEFT, ctypes.byref(value))
            return normalized_from_db(value.value, self._min_db, self._max_db)
        lib.snd_mixer_selem_get_playback_volume(self._elem, _SND_MIXER_SCHN_FRONT_LEFT, ctypes.byref(value))
        if self._max <= self._min:
            return 1.0
        return (value.value - self._min) / (self._max - self._min)

    def set_volume(self, volume: float):
        lib = _alsa()
        self._modified = True
        volume = max(0.0, min(1.0, volume))
        if self._use_db:
            lib.snd_mixer_selem_set_playback_dB_all(self._elem, db_from_normalized(volume, self._min_db, self._max_db), 1)
        else:
            lib.snd_mixer_selem_set_playback_volume_all(
                self._elem, int(round(self._min + volume * (self._max - self._min))))

    def _get_raw(self) -> int:
        value = ctypes.c_long()
        _alsa().snd_mixer_selem_get_playback_volume(self._elem, _SND_MIXER_SCHN_FRONT_LEFT, ctypes.byref(value))
        return value.value

    def restore_initial(self):
        """Deja el control como estaba antes de que MyFlac lo tocara."""
        if self._modified:
            _alsa().snd_mixer_selem_set_playback_volume_all(self._elem, self._initial_raw)
            self._modified = False

    def close(self):
        if self._handle:
            _alsa().snd_mixer_close(self._handle)
            self._handle = None
