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
        "es": "Buscar artista, álbum o canción...",
        "en": "Search artist, album or track...",
        "ca": "Cercar artista, àlbum o cançó...",
    },
    "header.search_tooltip": {
        "es": "Buscar en la biblioteca (Ctrl+F)",
        "en": "Search library (Ctrl+F)",
        "ca": "Cercar a la biblioteca (Ctrl+F)",
    },
    "app.subtitle": {
        "es": "Biblioteca Audiófila",
        "en": "Audiophile Library",
        "ca": "Biblioteca Audiòfila",
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
        "es": "★ {hires} de {total} pistas en Hi-Res ({pct}%)",
        "en": "★ {hires} of {total} tracks in Hi-Res ({pct}%)",
        "ca": "★ {hires} de {total} pistes en Hi-Res ({pct}%)",
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
    "inspector.mode_cover": {
        "es": "Modo Carátula (Clic para alternar a osciloscopio o vúmetro)",
        "en": "Cover Art Mode (Click to toggle oscilloscope or VU meter)",
        "ca": "Mode Portada (Clica per alternar a oscil·loscopi o vúmetre)",
    },
    "inspector.mode_scope": {
        "es": "Modo Osciloscopio en tiempo real (Clic para alternar a vúmetro)",
        "en": "Real-time Oscilloscope Mode (Click to toggle VU meter)",
        "ca": "Mode Oscil·loscopi en temps real (Clica per alternar a vúmetre)",
    },
    "inspector.mode_vu": {
        "es": "Modo Vúmetro Analógico Vintage (Clic para alternar a carátula)",
        "en": "Vintage Analog VU Meter Mode (Click to toggle cover art)",
        "ca": "Mode Vúmetre Analògic Vintage (Clica per alternar a portada)",
    },

    # --- Menú contextual de pista ---
    "context.play_now": {
        "es": "Reproducir ahora",
        "en": "Play Now",
        "ca": "Reprodueix ara",
    },
    "context.play_next": {
        "es": "Reproducir a continuación",
        "en": "Play Next",
        "ca": "Reprodueix a continuació",
    },
    "context.add_queue": {
        "es": "Añadir a la cola",
        "en": "Add to Queue",
        "ca": "Afegeix a la cua",
    },
    "context.show_in_files": {
        "es": "Mostrar en el gestor de archivos",
        "en": "Show in File Manager",
        "ca": "Mostra al gestor de fitxers",
    },

    # --- Cola de reproducción ("A continuación") ---
    "queue.title": {
        "es": "A continuación",
        "en": "Up Next",
        "ca": "A continuació",
    },
    "queue.clear": {
        "es": "Vaciar cola",
        "en": "Clear Queue",
        "ca": "Buidar cua",
    },
    "queue.empty": {
        "es": "Cola de reproducción vacía",
        "en": "Playback Queue Empty",
        "ca": "Cua de reproducció buida",
    },
    "queue.empty_hint": {
        "es": "Haz clic derecho en cualquier canción y selecciona 'Añadir a la cola'",
        "en": "Right-click any track and select 'Add to Queue'",
        "ca": "Fes clic dret a qualsevol cançó i selecciona 'Afegeix a la cua'",
    },
    "queue.tooltip": {
        "es": "Cola de reproducción",
        "en": "Play Queue",
        "ca": "Cua de reproducció",
    },
    "queue.tooltip_count": {
        "es": "Cola de reproducción ({n} en cola)",
        "en": "Play Queue ({n} queued)",
        "ca": "Cua de reproducció ({n} a la cua)",
    },
    "queue.tracks_count": {
        "es": "{n} temas",
        "en": "{n} tracks",
        "ca": "{n} temes",
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
    "dialog.cancel": {
        "es": "Cancelar",
        "en": "Cancel",
        "ca": "Cancel·lar",
    },
    "dialog.confirm": {
        "es": "Confirmar",
        "en": "Confirm",
        "ca": "Confirmar",
    },

    # --- Navegador Multicolumnas estilo iTunes ---
    "browser.col_artist": {
        "es": "Artista",
        "en": "Artist",
        "ca": "Artista",
    },
    "browser.col_album": {
        "es": "Álbum",
        "en": "Album",
        "ca": "Àlbum",
    },
    "browser.all_artists": {
        "es": "Todos ({count} artistas)",
        "en": "All ({count} artists)",
        "ca": "Tots ({count} artistes)",
    },
    "browser.all_albums": {
        "es": "Todos ({count} álbumes)",
        "en": "All ({count} albums)",
        "ca": "Tots ({count} àlbums)",
    },
    "browser.unknown_artist": {
        "es": "Artista desconocido",
        "en": "Unknown artist",
        "ca": "Artista desconegut",
    },
    "browser.no_album": {
        "es": "Sin Álbum",
        "en": "No Album",
        "ca": "Sense Àlbum",
    },

    # --- Configuración inicial de biblioteca ---
    "setup.welcome_title": {
        "es": "Bienvenido a MyFlac",
        "en": "Welcome to MyFlac",
        "ca": "Benvingut a MyFlac",
    },
    "setup.welcome_subtitle": {
        "es": "Para comenzar a reproducir tu música Hi-Res, selecciona la carpeta donde guardas tus álbumes y archivos de audio.",
        "en": "To start playing your Hi-Res music, select the folder where you keep your albums and audio files.",
        "ca": "Per començar a reproduir la teva música Hi-Res, selecciona la carpeta on guardes els teus àlbums i fitxers d'àudio.",
    },
    "setup.choose_btn": {
        "es": "Seleccionar Carpeta de Música",
        "en": "Select Music Folder",
        "ca": "Seleccionar Carpeta de Música",
    },
    "setup.choose_title": {
        "es": "Elige la carpeta principal de tu biblioteca",
        "en": "Choose your primary music library folder",
        "ca": "Tria la carpeta principal de la teva biblioteca",
    },
    "setup.scanning": {
        "es": "Indexando biblioteca...",
        "en": "Indexing library...",
        "ca": "Indexant biblioteca...",
    },

    # --- Preferencias: Biblioteca ---
    "prefs.library_page": {
        "es": "Biblioteca",
        "en": "Library",
        "ca": "Biblioteca",
    },
    "prefs.library_folders_group": {
        "es": "Carpetas de la Biblioteca",
        "en": "Library Folders",
        "ca": "Carpetes de la Biblioteca",
    },
    "prefs.library_folders_desc": {
        "es": "Carpetas y subcarpetas que MyFlac escanea para organizar tu colección",
        "en": "Folders and subfolders that MyFlac scans to organize your collection",
        "ca": "Carpetes i subcarpetes que MyFlac escaneja per organitzar la teva col·lecció",
    },
    "prefs.add_folder": {
        "es": "Añadir carpeta a la biblioteca...",
        "en": "Add folder to library...",
        "ca": "Afegir carpeta a la biblioteca...",
    },
    "prefs.remove_folder": {
        "es": "Quitar carpeta",
        "en": "Remove folder",
        "ca": "Treure carpeta",
    },
    "prefs.maintenance_group": {
        "es": "Mantenimiento y Escaneo",
        "en": "Maintenance & Scanning",
        "ca": "Manteniment i Escaneig",
    },
    "prefs.scan_new": {
        "es": "Buscar temas nuevos",
        "en": "Scan for new tracks",
        "ca": "Cercar temes nous",
    },
    "prefs.scan_new_desc": {
        "es": "Escanea rápidamente las carpetas en busca de archivos nuevos o modificados",
        "en": "Quickly scans folders for new or modified files",
        "ca": "Escaneja ràpidament les carpetes a la cerca de fitxers nous o modificats",
    },
    "prefs.scan_btn": {
        "es": "Buscar ahora",
        "en": "Scan now",
        "ca": "Cercar ara",
    },
    "prefs.reset_db": {
        "es": "Restablecer base de datos a cero",
        "en": "Reset database to zero",
        "ca": "Restablir base de dades a zero",
    },
    "prefs.reset_db_desc": {
        "es": "Elimina todos los datos indexados y vuelve a escanear desde cero",
        "en": "Clears all indexed data and rescans from scratch",
        "ca": "Elimina totes les dades indexades i torna a escanejar des de zero",
    },
    "prefs.reset_btn": {
        "es": "Restablecer",
        "en": "Reset",
        "ca": "Restablir",
    },
    "prefs.reset_confirm_title": {
        "es": "¿Restablecer la base de datos a cero?",
        "en": "Reset database to zero?",
        "ca": "Restablir la base de dades a zero?",
    },
    "prefs.reset_confirm_msg": {
        "es": "Se eliminarán todos los temas indexados en la base de datos y se iniciará un nuevo escaneo completo de las carpetas de la biblioteca. ¿Deseas continuar?",
        "en": "All indexed tracks will be deleted and a fresh full scan of library folders will begin. Do you wish to proceed?",
        "ca": "S'eliminaran tots els temes indexats a la base de dades i s'iniciarà un nou escaneig complet de les carpetes de la biblioteca. Vols continuar?",
    },
    "header.scan_library": {
        "es": "Actualizar biblioteca",
        "en": "Update library",
        "ca": "Actualitzar biblioteca",
    },
    "header.library_status_scanning": {
        "es": "Escaneando...",
        "en": "Scanning...",
        "ca": "Escanejant...",
    },
    "header.library_status_done": {
        "es": "Biblioteca al día",
        "en": "Library up to date",
        "ca": "Biblioteca al dia",
    },
}
