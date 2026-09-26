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
    "header.fullscreen": {
        "es": "Pantalla completa (F11)",
        "en": "Fullscreen (F11)",
        "ca": "Pantalla completa (F11)",
    },
    "header.unfullscreen": {
        "es": "Salir de pantalla completa (F11)",
        "en": "Leave fullscreen (F11)",
        "ca": "Sortir de pantalla completa (F11)",
    },
    "header.mini_player": {
        "es": "Activar Mini-Reproductor",
        "en": "Activate Mini Player",
        "ca": "Activar Mini-Reproductor",
    },
    "header.super_player": {
        "es": "Super-Reproductor a Pantalla Completa (F11)",
        "en": "Fullscreen Super Player (F11)",
        "ca": "Super-Reproductor a Pantalla Completa (F11)",
    },
    "header.dock_main": {
        "es": "Volver a la ventana principal (Escape)",
        "en": "Return to main window (Escape)",
        "ca": "Tornar a la finestra principal (Escape)",
    },
    "lyrics.title": {
        "es": "Letra",
        "en": "Lyrics",
        "ca": "Lletra",
    },
    "lyrics.loading": {
        "es": "Buscando letra...",
        "en": "Searching lyrics...",
        "ca": "Cercant lletra...",
    },
    "lyrics.not_found": {
        "es": "Letra no disponible",
        "en": "Lyrics not available",
        "ca": "Lletra no disponible",
    },
    "lyrics.instrumental": {
        "es": "Pista Instrumental",
        "en": "Instrumental Track",
        "ca": "Pista Instrumental",
    },
    "lyrics.source_online": {
        "es": "Letra en línea",
        "en": "Online lyrics",
        "ca": "Lletra en línia",
    },
    "lyrics.source_synced": {
        "es": "Letra sincronizada",
        "en": "Synced lyrics",
        "ca": "Lletra sincronitzada",
    },
    "app.subtitle": {
        "es": "Biblioteca Audiófila",
        "en": "Audiophile Library",
        "ca": "Biblioteca Audiòfila",
    },
    "menu.shortcuts": {
        "es": "Atajos de teclado",
        "en": "Keyboard Shortcuts",
        "ca": "Dreceres de teclat",
    },
    "shortcuts.section_playback": {
        "es": "Reproducción",
        "en": "Playback",
        "ca": "Reproducció",
    },
    "shortcuts.section_views": {
        "es": "Vistas",
        "en": "Views",
        "ca": "Vistes",
    },
    "shortcuts.section_general": {
        "es": "General",
        "en": "General",
        "ca": "General",
    },
    "shortcuts.play_pause": {
        "es": "Reproducir / pausar",
        "en": "Play / pause",
        "ca": "Reprodueix / pausa",
    },
    "shortcuts.next": {
        "es": "Pista siguiente",
        "en": "Next track",
        "ca": "Pista següent",
    },
    "shortcuts.previous": {
        "es": "Pista anterior",
        "en": "Previous track",
        "ca": "Pista anterior",
    },
    "shortcuts.seek_forward": {
        "es": "Avanzar 10 segundos",
        "en": "Forward 10 seconds",
        "ca": "Avança 10 segons",
    },
    "shortcuts.seek_backward": {
        "es": "Retroceder 10 segundos",
        "en": "Back 10 seconds",
        "ca": "Retrocedeix 10 segons",
    },
    "shortcuts.volume_up": {
        "es": "Subir el volumen",
        "en": "Volume up",
        "ca": "Apuja el volum",
    },
    "shortcuts.volume_down": {
        "es": "Bajar el volumen",
        "en": "Volume down",
        "ca": "Abaixa el volum",
    },
    "shortcuts.mute": {
        "es": "Silenciar / restaurar volumen",
        "en": "Mute / restore volume",
        "ca": "Silencia / restaura el volum",
    },
    "shortcuts.shuffle": {
        "es": "Activar / desactivar aleatorio",
        "en": "Toggle shuffle",
        "ca": "Activa / desactiva l'aleatori",
    },
    "shortcuts.repeat": {
        "es": "Cambiar modo de repetición",
        "en": "Cycle repeat mode",
        "ca": "Canvia el mode de repetició",
    },
    "shortcuts.exclusive": {
        "es": "Activar / desactivar modo exclusivo Bit-Perfect",
        "en": "Toggle Bit-Perfect exclusive mode",
        "ca": "Activa / desactiva el mode exclusiu Bit-Perfect",
    },
    "shortcuts.view_main": {
        "es": "Ventana principal",
        "en": "Main window",
        "ca": "Finestra principal",
    },
    "shortcuts.view_mini": {
        "es": "Mini-reproductor",
        "en": "Mini player",
        "ca": "Mini-reproductor",
    },
    "shortcuts.view_super": {
        "es": "Super-reproductor a pantalla completa",
        "en": "Full-screen super player",
        "ca": "Super-reproductor a pantalla completa",
    },
    "shortcuts.back": {
        "es": "Salir del super-reproductor o mini-reproductor / cerrar la portada",
        "en": "Leave the super or mini player / close the cover",
        "ca": "Surt del super o mini-reproductor / tanca la portada",
    },
    "shortcuts.cover_mode": {
        "es": "Portada: osciloscopio / foto del artista",
        "en": "Cover: oscilloscope / artist photo",
        "ca": "Portada: oscil·loscopi / foto de l'artista",
    },
    "shortcuts.show_cover": {
        "es": "Ver la portada a gran tamaño",
        "en": "Show the cover art full size",
        "ca": "Mostra la portada a mida gran",
    },
    "shortcuts.search": {
        "es": "Buscar en la biblioteca",
        "en": "Search the library",
        "ca": "Cerca a la biblioteca",
    },
    "shortcuts.rescan": {
        "es": "Buscar temas nuevos",
        "en": "Scan for new tracks",
        "ca": "Cerca temes nous",
    },
    "shortcuts.preferences": {
        "es": "Preferencias",
        "en": "Preferences",
        "ca": "Preferències",
    },
    "shortcuts.help": {
        "es": "Atajos de teclado",
        "en": "Keyboard shortcuts",
        "ca": "Dreceres de teclat",
    },
    "shortcuts.quit": {
        "es": "Salir",
        "en": "Quit",
        "ca": "Surt",
    },
    "tabs.lyrics": {
        "es": 'Letra',
        "en": 'Lyrics',
        "ca": 'Lletra',
    },
    "tabs.track": {
        "es": 'Tema',
        "en": 'Track',
        "ca": 'Tema',
    },
    "tabs.album": {
        "es": 'Disco',
        "en": 'Album',
        "ca": 'Disc',
    },
    "tabs.artist": {
        "es": 'Artista',
        "en": 'Artist',
        "ca": 'Artista',
    },
    "info.loading": {
        "es": 'Buscando información…',
        "en": 'Looking up information…',
        "ca": 'Cercant informació…',
    },
    "info.no_track": {
        "es": 'No hay ninguna pista seleccionada',
        "en": 'No track selected',
        "ca": 'No hi ha cap pista seleccionada',
    },
    "info.empty": {
        "es": 'No hay información sobre esto en Wikipedia ni en Discogs',
        "en": 'Nothing about this on Wikipedia or Discogs',
        "ca": 'No hi ha informació sobre això a la Viquipèdia ni a Discogs',
    },
    "info.error": {
        "es": 'No se pudo obtener la información ({error}). Vuelve a esta pestaña para reintentarlo.',
        "en": 'The information could not be retrieved ({error}). Come back to this tab to retry.',
        "ca": "No s'ha pogut obtenir la informació ({error}). Torna a aquesta pestanya per reintentar-ho.",
    },
    "info.err_busy": {
        "es": 'Wikipedia y Discogs no responden ahora',
        "en": 'Wikipedia and Discogs are not responding right now',
        "ca": 'La Viquipèdia i Discogs no responen ara',
    },
    "info.sources": {
        "es": 'Fuentes',
        "en": 'Sources',
        "ca": 'Fonts',
    },
    "info.year": {
        "es": 'Año',
        "en": 'Year',
        "ca": 'Any',
    },
    "info.label": {
        "es": 'Sello',
        "en": 'Label',
        "ca": 'Segell',
    },
    "info.country": {
        "es": 'País',
        "en": 'Country',
        "ca": 'País',
    },
    "info.format": {
        "es": 'Formato',
        "en": 'Format',
        "ca": 'Format',
    },
    "info.genres": {
        "es": 'Géneros',
        "en": 'Genres',
        "ca": 'Gèneres',
    },
    "info.styles": {
        "es": 'Estilos',
        "en": 'Styles',
        "ca": 'Estils',
    },
    "info.credits": {
        "es": 'Créditos',
        "en": 'Credits',
        "ca": 'Crèdits',
    },
    "info.release_notes": {
        "es": 'Notas de la edición',
        "en": 'Release notes',
        "ca": "Notes de l'edició",
    },
    "info.album": {
        "es": 'Disco',
        "en": 'Album',
        "ca": 'Disc',
    },
    "info.position": {
        "es": 'Posición',
        "en": 'Position',
        "ca": 'Posició',
    },
    "info.duration": {
        "es": 'Duración',
        "en": 'Duration',
        "ca": 'Durada',
    },
    "info.real_name": {
        "es": 'Nombre real',
        "en": 'Real name',
        "ca": 'Nom real',
    },
    "info.members": {
        "es": 'Miembros',
        "en": 'Members',
        "ca": 'Membres',
    },
    "info.groups": {
        "es": 'Miembro de',
        "en": 'Member of',
        "ca": 'Membre de',
    },
    "info.aliases": {
        "es": 'Alias',
        "en": 'Aliases',
        "ca": 'Àlies',
    },
    "info.discogs_profile": {
        "es": 'Perfil en Discogs',
        "en": 'Discogs profile',
        "ca": 'Perfil a Discogs',
    },
    "info.translated": {
        "es": 'Traducción automática ({service})',
        "en": 'Machine translation ({service})',
        "ca": 'Traducció automàtica ({service})',
    },
    "tray.play": {
        "es": 'Reproducir',
        "en": 'Play',
        "ca": 'Reprodueix',
    },
    "tray.pause": {
        "es": 'Pausar',
        "en": 'Pause',
        "ca": 'Pausa',
    },
    "tray.previous": {
        "es": 'Anterior',
        "en": 'Previous',
        "ca": 'Anterior',
    },
    "tray.next": {
        "es": 'Siguiente',
        "en": 'Next',
        "ca": 'Següent',
    },
    "tray.show": {
        "es": 'Mostrar MyFlac',
        "en": 'Show MyFlac',
        "ca": 'Mostra MyFlac',
    },
    "tray.quit": {
        "es": 'Salir',
        "en": 'Quit',
        "ca": 'Surt',
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
        "es": "Portada con osciloscopio en tiempo real (clic para ver la foto del artista)",
        "en": "Cover with real-time oscilloscope (click to show the artist photo)",
        "ca": "Portada amb oscil·loscopi en temps real (clica per veure la foto de l'artista)",
    },
    "inspector.mode_artist": {
        "es": "Foto del artista (clic para volver a la portada con osciloscopio)",
        "en": "Artist photo (click to go back to the cover with oscilloscope)",
        "ca": "Foto de l'artista (clica per tornar a la portada amb oscil·loscopi)",
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
    "devices.exclusive_title": {
        "es": "Modo exclusivo Bit-Perfect",
        "en": "Bit-Perfect exclusive mode",
        "ca": "Mode exclusiu Bit-Perfect",
    },
    "devices.exclusive_subtitle": {
        "es": "Acceso directo al DAC (ALSA hw) sin mezclador, remuestreo ni volumen digital",
        "en": "Direct DAC access (ALSA hw) with no mixer, resampling or digital volume",
        "ca": "Accés directe al DAC (ALSA hw) sense mesclador, remostreig ni volum digital",
    },
    "devices.exclusive_unavailable": {
        "es": "No disponible para esta salida (no es un dispositivo ALSA)",
        "en": "Not available for this output (not an ALSA device)",
        "ca": "No disponible per a aquesta sortida (no és un dispositiu ALSA)",
    },
    "devices.exclusive_failed": {
        "es": "No se pudo usar el modo exclusivo ({reason}). Esta pista se reproduce por el mezclador.",
        "en": "Exclusive mode could not be used ({reason}). This track plays through the mixer.",
        "ca": "No s'ha pogut usar el mode exclusiu ({reason}). Aquesta pista es reprodueix pel mesclador.",
    },
    "devices.exclusive_busy": {
        "es": "el DAC está ocupado",
        "en": "the DAC is busy",
        "ca": "el DAC està ocupat",
    },
    "devices.exclusive_format_unsupported": {
        "es": "El DAC no admite {format} en modo exclusivo. Esta pista se reproduce por el mezclador.",
        "en": "The DAC does not support {format} in exclusive mode. This track plays through the mixer.",
        "ca": "El DAC no admet {format} en mode exclusiu. Aquesta pista es reprodueix pel mesclador.",
    },
    "player.cover_tooltip": {
        "es": "Ver la portada a gran tamaño",
        "en": "Show the cover art full size",
        "ca": "Mostra la portada a mida gran",
    },
    "player.volume_locked": {
        "es": "Volumen fijo a 0 dB en modo exclusivo (ajústalo en el DAC o amplificador)",
        "en": "Volume fixed at 0 dB in exclusive mode (adjust it on your DAC or amplifier)",
        "ca": "Volum fix a 0 dB en mode exclusiu (ajusta'l al DAC o l'amplificador)",
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
    "prefs.backdrop_group": {
        "es": "Fondo del artista",
        "en": "Artist backdrop",
        "ca": "Fons de l'artista",
    },
    "prefs.backdrop_desc": {
        "es": "Foto desenfocada del artista en reproducción detrás de la biblioteca",
        "en": "Blurred photo of the playing artist behind the library",
        "ca": "Foto desenfocada de l'artista en reproducció darrere de la biblioteca",
    },
    "prefs.backdrop_enabled": {
        "es": "Mostrar fondo del artista",
        "en": "Show artist backdrop",
        "ca": "Mostra el fons de l'artista",
    },
    "prefs.backdrop_intensity": {
        "es": "Intensidad de la foto",
        "en": "Photo intensity",
        "ca": "Intensitat de la foto",
    },
    "prefs.backdrop_intensity_desc": {
        "es": "Más alta, la foto se ve más; más baja, más legibilidad",
        "en": "Higher shows more of the photo; lower improves readability",
        "ca": "Més alta, la foto es veu més; més baixa, més llegibilitat",
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
