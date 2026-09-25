"""Sistema de internacionalización para MyFlac: Español, English y Català."""
from __future__ import annotations

from typing import Callable

from . import config as _config
from .config import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE_FALLBACK

LANGUAGE_NAMES = {
    "es": "Español",
    "en": "English",
    "ca": "Català",
}

_cfg = _config.load_config()
_current_language = _cfg.get("language") or DEFAULT_LANGUAGE_FALLBACK
if _current_language not in SUPPORTED_LANGUAGES:
    _current_language = DEFAULT_LANGUAGE_FALLBACK

_change_listeners: list[Callable[[str], None]] = []


def get_language() -> str:
    return _current_language


def set_language(lang: str) -> None:
    global _current_language
    if lang not in SUPPORTED_LANGUAGES:
        return
    if _current_language == lang:
        return
    _current_language = lang
    cfg = _config.load_config()
    cfg["language"] = lang
    _config.save_config(cfg)

    # Notificar a los listeners registrados
    for listener in _change_listeners:
        try:
            listener(lang)
        except Exception:
            pass


def add_language_listener(callback: Callable[[str], None]) -> None:
    if callback not in _change_listeners:
        _change_listeners.append(callback)


def remove_language_listener(callback: Callable[[str], None]) -> None:
    if callback in _change_listeners:
        _change_listeners.remove(callback)


def t(key: str, **kwargs) -> str:
    """Traduce `key` al idioma activo, con soporte de parámetros kwargs."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_current_language) or entry.get(DEFAULT_LANGUAGE_FALLBACK) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


STRINGS: dict[str, dict[str, str]] = {
    # --- Aplicación y Acerca de ---
    "app.name": {
        "es": "MyFlac",
        "en": "MyFlac",
        "ca": "MyFlac",
    },
    "app.comment": {
        "es": "Reproductor de música Hi-Res para GNOME",
        "en": "Hi-Res music player for GNOME",
        "ca": "Reproductor de música Hi-Res per a GNOME",
    },
    "about.title": {
        "es": "Acerca de MyFlac",
        "en": "About MyFlac",
        "ca": "Quant a MyFlac",
    },

    # --- Barra de cabecera ---
    "header.open_folder": {
        "es": "Abrir álbum o carpeta de música (Ctrl+O)",
        "en": "Open album or music folder (Ctrl+O)",
        "ca": "Obrir àlbum o carpeta de música (Ctrl+O)",
    },
    "header.open_files": {
        "es": "Añadir pistas individuales (Ctrl+Shift+O)",
        "en": "Add individual tracks (Ctrl+Shift+O)",
        "ca": "Afegir pistes individuals (Ctrl+Shift+O)",
    },
    "header.clear_playlist": {
        "es": "Vaciar lista de reproducción",
        "en": "Clear playlist",
        "ca": "Buidar llista de reproducció",
    },
    "header.search_placeholder": {
        "es": "Buscar en la lista...",
        "en": "Search playlist...",
        "ca": "Cercar a la llista...",
    },
    "menu.preferences": {
        "es": "Preferencias",
        "en": "Preferences",
        "ca": "Preferències",
    },
    "menu.devices": {
        "es": "Dispositivos de Audio",
        "en": "Audio Devices",
        "ca": "Dispositius d'Àudio",
    },
    "menu.view_log": {
        "es": "Ver Registro (Log)",
        "en": "View Log",
        "ca": "Veure Registre (Log)",
    },
    "menu.about": {
        "es": "Acerca de MyFlac",
        "en": "About MyFlac",
        "ca": "Quant a MyFlac",
    },

    # --- Columnas de tabla ---
    "col.num": {
        "es": "#",
        "en": "#",
        "ca": "#",
    },
    "col.title": {
        "es": "Título",
        "en": "Title",
        "ca": "Títol",
    },
    "col.artist": {
        "es": "Artista",
        "en": "Artist",
        "ca": "Artista",
    },
    "col.album": {
        "es": "Álbum",
        "en": "Album",
        "ca": "Àlbum",
    },
    "col.duration": {
        "es": "Duración",
        "en": "Duration",
        "ca": "Durada",
    },
    "col.quality": {
        "es": "Calidad",
        "en": "Quality",
        "ca": "Qualitat",
    },

    # --- Pie de lista ---
    "footer.no_tracks": {
        "es": "0 pistas",
        "en": "0 tracks",
        "ca": "0 pistes",
    },
    "footer.tracks_summary": {
        "es": "{count} pistas · {duration}",
        "en": "{count} tracks · {duration}",
        "ca": "{count} pistes · {duration}",
    },
    "footer.hires_album": {
        "es": "⭐ Álbum Hi-Res ({rates})",
        "en": "⭐ Hi-Res Album ({rates})",
        "ca": "⭐ Àlbum Hi-Res ({rates})",
    },
    "footer.hires_partial": {
        "es": "⭐ {hires} de {total} pistas en Hi-Res",
        "en": "⭐ {hires} of {total} tracks in Hi-Res",
        "ca": "⭐ {hires} de {total} pistes en Hi-Res",
    },
    "footer.standard_quality": {
        "es": "Calidad Estándar CD",
        "en": "Standard CD Quality",
        "ca": "Qualitat Estàndard CD",
    },

    # --- Panel Inspector ---
    "inspector.select_track": {
        "es": "Selecciona una pista",
        "en": "Select a track",
        "ca": "Selecciona una pista",
    },
    "inspector.no_playback": {
        "es": "Sin reproducción",
        "en": "No playback",
        "ca": "Sense reproducció",
    },
    "inspector.unknown_artist": {
        "es": "Artista desconocido",
        "en": "Unknown artist",
        "ca": "Artista desconegut",
    },
    "inspector.unknown_album": {
        "es": "Álbum desconocido",
        "en": "Unknown album",
        "ca": "Àlbum desconegut",
    },
    "inspector.card_title": {
        "es": "Ficha Técnica de Audio",
        "en": "Audio Specifications",
        "ca": "Fitxa Tècnica d'Àudio",
    },
    "inspector.format": {
        "es": "Formato",
        "en": "Format",
        "ca": "Format",
    },
    "inspector.sampling": {
        "es": "Muestreo",
        "en": "Sampling",
        "ca": "Mostreig",
    },
    "inspector.resolution": {
        "es": "Resolución",
        "en": "Resolution",
        "ca": "Resolució",
    },
    "inspector.channels": {
        "es": "Canales",
        "en": "Channels",
        "ca": "Canals",
    },
    "inspector.bitrate": {
        "es": "Tasa de bits",
        "en": "Bitrate",
        "ca": "Taxa de bits",
    },
    "inspector.size": {
        "es": "Tamaño",
        "en": "Size",
        "ca": "Mida",
    },
    "inspector.output_device": {
        "es": "Salida de audio",
        "en": "Audio output",
        "ca": "Sortida d'àudio",
    },
    "inspector.stereo": {
        "es": "Estéreo (2 canales)",
        "en": "Stereo (2 channels)",
        "ca": "Estèreo (2 canals)",
    },
    "inspector.channels_n": {
        "es": "{n} canales",
        "en": "{n} channels",
        "ca": "{n} canals",
    },
    "inspector.no_cover": {
        "es": "Sin carátula disponible",
        "en": "No cover art available",
        "ca": "Sense portada disponible",
    },

    "inspector.device": {
        "es": "Dispositivo",
        "en": "Device",
        "ca": "Dispositiu",
    },
    "inspector.mixer": {
        "es": "Mezclador",
        "en": "Mixer",
        "ca": "Mesclador",
    },
    "inspector.mixer_name": {
        "es": "Mezclador del Sistema",
        "en": "System Mixer",
        "ca": "Mesclador de Sistema",
    },
    "inspector.status": {
        "es": "Estado",
        "en": "Status",
        "ca": "Estat",
    },
    "inspector.status_playing": {
        "es": "Reproduciendo",
        "en": "Playing",
        "ca": "Reproduint",
    },
    "inspector.status_stopped": {
        "es": "Detenido",
        "en": "Stopped",
        "ca": "Detingut",
    },
    "inspector.status_paused": {
        "es": "En pausa",
        "en": "Paused",
        "ca": "En pausa",
    },

    # --- Barra de Transporte / Controles ---
    "player.prev": {
        "es": "Pista anterior",
        "en": "Previous track",
        "ca": "Pista anterior",
    },
    "player.play_pause": {
        "es": "Reproducir / Pausa (Espacio)",
        "en": "Play / Pause (Space)",
        "ca": "Reprodueix / Pausa (Espai)",
    },
    "player.next": {
        "es": "Siguiente pista",
        "en": "Next track",
        "ca": "Pista següent",
    },
    "player.shuffle": {
        "es": "Modo aleatorio",
        "en": "Shuffle mode",
        "ca": "Mode aleatori",
    },
    "player.repeat": {
        "es": "Repetir lista / pista",
        "en": "Repeat playlist / track",
        "ca": "Repetir llista / pista",
    },
    "player.volume": {
        "es": "Volumen",
        "en": "Volume",
        "ca": "Volum",
    },
    "player.active_device": {
        "es": "Dispositivo activo: {name}",
        "en": "Active device: {name}",
        "ca": "Dispositiu actiu: {name}",
    },

    # --- Selector de Dispositivos ---
    "devices.title": {
        "es": "Dispositivos de Salida de Audio",
        "en": "Audio Output Devices",
        "ca": "Dispositius de Sortida d'Àudio",
    },
    "devices.group_title": {
        "es": "Salidas del Mezclador del Sistema",
        "en": "System Mixer Audio Outputs",
        "ca": "Sortides del Mesclador de Sistema",
    },
    "devices.group_desc": {
        "es": "Selecciona a través de qué dispositivo reproducir la música",
        "en": "Select which device to play music through",
        "ca": "Selecciona a través de quin dispositiu reproduir la música",
    },
    "devices.group_usb": {
        "es": "DACs USB de Alta Calidad",
        "en": "High-Quality USB DACs",
        "ca": "DACs USB d'Alta Qualitat",
    },
    "devices.group_other": {
        "es": "Otras Salidas de Audio",
        "en": "Other Audio Outputs",
        "ca": "Altres Sortides d'Àudio",
    },
    "devices.default_name": {
        "es": "Predeterminado del Sistema",
        "en": "System Default",
        "ca": "Predeterminat del Sistema",
    },
    "devices.default_desc": {
        "es": "Salida predeterminada del escritorio",
        "en": "System default desktop output",
        "ca": "Sortida predeterminada de l'escriptori",
    },
    "devices.select_btn": {
        "es": "Seleccionar",
        "en": "Select",
        "ca": "Selecciona",
    },
    "devices.active_btn": {
        "es": "Activo",
        "en": "Active",
        "ca": "Actiu",
    },

    # --- Preferencias ---
    "prefs.title": {
        "es": "Preferencias",
        "en": "Preferences",
        "ca": "Preferències",
    },
    "prefs.general": {
        "es": "General",
        "en": "General",
        "ca": "General",
    },
    "prefs.language": {
        "es": "Idioma",
        "en": "Language",
        "ca": "Idioma",
    },
    "prefs.language_desc": {
        "es": "Idioma de la interfaz de usuario",
        "en": "User interface language",
        "ca": "Idioma de la interfície d'usuari",
    },
    "prefs.audio_group": {
        "es": "Dispositivo de Audio",
        "en": "Audio Device",
        "ca": "Dispositiu d'Àudio",
    },
    "prefs.audio_device": {
        "es": "Salida de audio predeterminada",
        "en": "Default audio output",
        "ca": "Sortida d'àudio predeterminada",
    },
    "prefs.ui_group": {
        "es": "Apariencia de la Interfaz",
        "en": "Interface Appearance",
        "ca": "Aparença de la Interfície",
    },
    "prefs.theme": {
        "es": "Tema",
        "en": "Theme",
        "ca": "Tema",
    },
    "prefs.theme_system": {
        "es": "Sistema",
        "en": "System",
        "ca": "Sistema",
    },
    "prefs.theme_light": {
        "es": "Claro",
        "en": "Light",
        "ca": "Clar",
    },
    "prefs.theme_dark": {
        "es": "Oscuro",
        "en": "Dark",
        "ca": "Fosc",
    },
    "prefs.scale": {
        "es": "Escala de la Interfaz (%)",
        "en": "Interface Scaling (%)",
        "ca": "Escala de la Interfície (%)",
    },
    "prefs.scale_desc": {
        "es": "Ajusta el tamaño visual de textos e iconos",
        "en": "Adjust visual size of text and icons",
        "ca": "Ajusta la mida visual de textos i icones",
    },

    # --- Diálogos de archivo ---
    "dialog.open_folder_title": {
        "es": "Seleccionar carpeta de música / álbum",
        "en": "Select music folder / album",
        "ca": "Selecciona carpeta de música / àlbum",
    },
    "dialog.open_files_title": {
        "es": "Seleccionar pistas de audio",
        "en": "Select audio tracks",
        "ca": "Selecciona pistes d'àudio",
    },
    "dialog.filter_audio": {
        "es": "Archivos de audio Hi-Res y FLAC",
        "en": "Hi-Res & FLAC Audio Files",
        "ca": "Fitxers d'àudio Hi-Res i FLAC",
    },
}
