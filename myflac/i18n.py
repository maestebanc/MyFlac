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
    "header.theme_to_light": {
        "es": "Cambiar a modo claro",
        "en": "Switch to light mode",
        "ca": "Canviar a mode clar",
    },
    "header.theme_to_dark": {
        "es": "Cambiar a modo oscuro",
        "en": "Switch to dark mode",
        "ca": "Canviar a mode fosc",
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
        "es": "Letra",
        "en": "Lyrics",
        "ca": "Lletra",
    },
    "tabs.track": {
        "es": "Tema",
        "en": "Track",
        "ca": "Tema",
    },
    "tabs.album": {
        "es": "Disco",
        "en": "Album",
        "ca": "Disc",
    },
    "tabs.artist": {
        "es": "Artista",
        "en": "Artist",
        "ca": "Artista",
    },
    "info.loading": {
        "es": "Buscando información…",
        "en": "Looking up information…",
        "ca": "Cercant informació…",
    },
    "info.no_track": {
        "es": "No hay ninguna pista seleccionada",
        "en": "No track selected",
        "ca": "No hi ha cap pista seleccionada",
    },
    "info.empty": {
        "es": "No hay información sobre esto en Wikipedia ni en Discogs",
        "en": "Nothing about this on Wikipedia or Discogs",
        "ca": "No hi ha informació sobre això a la Viquipèdia ni a Discogs",
    },
    "info.error": {
        "es": "No se pudo obtener la información ({error}). Vuelve a esta pestaña para reintentarlo.",
        "en": "The information could not be retrieved ({error}). Come back to this tab to retry.",
        "ca": "No s'ha pogut obtenir la informació ({error}). Torna a aquesta pestanya per reintentar-ho.",
    },
    "info.err_busy": {
        "es": "Wikipedia y Discogs no responden ahora",
        "en": "Wikipedia and Discogs are not responding right now",
        "ca": "La Viquipèdia i Discogs no responen ara",
    },
    "info.sources": {
        "es": "Fuentes",
        "en": "Sources",
        "ca": "Fonts",
    },
    "info.year": {
        "es": "Año",
        "en": "Year",
        "ca": "Any",
    },
    "info.label": {
        "es": "Sello",
        "en": "Label",
        "ca": "Segell",
    },
    "info.country": {
        "es": "País",
        "en": "Country",
        "ca": "País",
    },
    "info.format": {
        "es": "Formato",
        "en": "Format",
        "ca": "Format",
    },
    "info.genres": {
        "es": "Géneros",
        "en": "Genres",
        "ca": "Gèneres",
    },
    "info.styles": {
        "es": "Estilos",
        "en": "Styles",
        "ca": "Estils",
    },
    "info.credits": {
        "es": "Créditos",
        "en": "Credits",
        "ca": "Crèdits",
    },
    "info.release_notes": {
        "es": "Notas de la edición",
        "en": "Release notes",
        "ca": "Notes de l'edició",
    },
    "info.album": {
        "es": "Disco",
        "en": "Album",
        "ca": "Disc",
    },
    "info.position": {
        "es": "Posición",
        "en": "Position",
        "ca": "Posició",
    },
    "info.duration": {
        "es": "Duración",
        "en": "Duration",
        "ca": "Durada",
    },
    "info.real_name": {
        "es": "Nombre real",
        "en": "Real name",
        "ca": "Nom real",
    },
    "info.members": {
        "es": "Miembros",
        "en": "Members",
        "ca": "Membres",
    },
    "info.groups": {
        "es": "Miembro de",
        "en": "Member of",
        "ca": "Membre de",
    },
    "info.aliases": {
        "es": "Alias",
        "en": "Aliases",
        "ca": "Àlies",
    },
    "info.discogs_profile": {
        "es": "Perfil en Discogs",
        "en": "Discogs profile",
        "ca": "Perfil a Discogs",
    },
    "info.translated": {
        "es": "Traducción automática ({service})",
        "en": "Machine translation ({service})",
        "ca": "Traducció automàtica ({service})",
    },
    "tray.play": {
        "es": "Reproducir",
        "en": "Play",
        "ca": "Reprodueix",
    },
    "tray.pause": {
        "es": "Pausar",
        "en": "Pause",
        "ca": "Pausa",
    },
    "tray.previous": {
        "es": "Anterior",
        "en": "Previous",
        "ca": "Anterior",
    },
    "tray.next": {
        "es": "Siguiente",
        "en": "Next",
        "ca": "Següent",
    },
    "tray.show": {
        "es": "Mostrar MyFlac",
        "en": "Show MyFlac",
        "ca": "Mostra MyFlac",
    },
    "tray.super_player": {
        "es": "Super-Reproductor",
        "en": "Super Player",
        "ca": "Super-Reproductor",
    },
    "tray.mini_player": {
        "es": "Mini-Reproductor",
        "en": "Mini Player",
        "ca": "Mini-Reproductor",
    },
    "tray.quit": {
        "es": "Salir",
        "en": "Quit",
        "ca": "Surt",
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
    "menu.website": {
        "es": "Sitio web oficial",
        "en": "Official Website",
        "ca": "Lloc web oficial",
    },
    "menu.donate": {
        "es": "¡Dame argo! (Ko-fi)",
        "en": "Buy Me a Coffee (Ko-fi)",
        "ca": "Dona'm argo! (Ko-fi)",
    },
    "about.donate": {
        "es": "¡Dame argo! (Ko-fi)",
        "en": "Buy Me a Coffee (Ko-fi)",
        "ca": "Dona'm argo! (Ko-fi)",
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
        "es": "◆ Álbum Hi-Res ({rates})",
        "en": "◆ Hi-Res Album ({rates})",
        "ca": "◆ Àlbum Hi-Res ({rates})",
    },
    "footer.hires_partial": {
        "es": "◆ {hires} de {total} pistas en Hi-Res ({pct}%)",
        "en": "◆ {hires} of {total} tracks in Hi-Res ({pct}%)",
        "ca": "◆ {hires} de {total} pistes en Hi-Res ({pct}%)",
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
    "devices.bitperfect_enable": {
        "es": "Bit-Perfect",
        "en": "Bit-Perfect",
        "ca": "Bit-Perfect",
    },
    "devices.bitperfect_tooltip": {
        "es": "Salida directa ALSA por hardware (Bit-Perfect)",
        "en": "Direct hardware ALSA output (Bit-Perfect)",
        "ca": "Sortida directa ALSA per maquinari (Bit-Perfect)",
    },
    "devices.subtitle_default": {
        "es": "Mezclador general del sistema",
        "en": "System audio mixer",
        "ca": "Mesclador general del sistema",
    },
    "devices.type_usb": {
        "es": "DAC USB",
        "en": "USB DAC",
        "ca": "DAC USB",
    },
    "devices.type_hdmi": {
        "es": "Audio HDMI",
        "en": "HDMI Audio",
        "ca": "Àudio HDMI",
    },
    "devices.type_network": {
        "es": "AirPlay / Red",
        "en": "AirPlay / Network",
        "ca": "AirPlay / Xarxa",
    },
    "devices.type_integrated": {
        "es": "Audio integrado",
        "en": "Integrated audio",
        "ca": "Àudio integrat",
    },
    "devices.max_sample_rate": {
        "es": "Hasta {rate} kHz",
        "en": "Up to {rate} kHz",
        "ca": "Fins a {rate} kHz",
    },
    "player.bitperfect_tooltip": {
        "es": "Modo exclusivo directo por hardware (Bit-Perfect)",
        "en": "Direct hardware exclusive mode (Bit-Perfect)",
        "ca": "Mode exclusiu directe per maquinari (Bit-Perfect)",
    },
    "player.resampling_tooltip": {
        "es": "Remuestreado a {rate} (límite máximo del DAC)",
        "en": "Resampled to {rate} (DAC maximum limit)",
        "ca": "Remostrejat a {rate} (límit màxim del DAC)",
    },
    "player.depth_tooltip": {
        "es": "El DAC recibe {bits} bits: menos de los que tiene la pista",
        "en": "The DAC receives {bits} bits: fewer than the track has",
        "ca": "El DAC rep {bits} bits: menys dels que té la pista",
    },
    "devices.wireplumber_lost": {
        "es": "PipeWire no ha recuperado «{name}». Si no vuelve a aparecer, reinicia WirePlumber: systemctl --user restart wireplumber",
        "en": "PipeWire has not recovered “{name}”. If it does not come back, restart WirePlumber: systemctl --user restart wireplumber",
        "ca": "PipeWire no ha recuperat «{name}». Si no torna a aparèixer, reinicia WirePlumber: systemctl --user restart wireplumber",
    },
    "devices.unavailable": {
        "es": "No disponible ahora mismo",
        "en": "Not available right now",
        "ca": "No disponible ara mateix",
    },
    "devices.popover_title": {
        "es": "Salida de audio",
        "en": "Audio output",
        "ca": "Sortida d'àudio",
    },
    "devices.exclusive_subtitle_short": {
        "es": "Directo al DAC, sin mezclador ni volumen digital",
        "en": "Straight to the DAC, no mixer or digital volume",
        "ca": "Directe al DAC, sense mesclador ni volum digital",
    },
    "devices.exclusive_unavailable_short": {
        "es": "No disponible para esta salida",
        "en": "Not available for this output",
        "ca": "No disponible per a aquesta sortida",
    },
    "devices.status_mixer": {
        "es": "Mezclador del sistema",
        "en": "System mixer",
        "ca": "Mesclador del sistema",
    },
    "devices.status_network": {
        "es": "Red · UPnP/DLNA",
        "en": "Network · UPnP/DLNA",
        "ca": "Xarxa · UPnP/DLNA",
    },
    "devices.network_tooltip": {
        "es": "El dispositivo descarga y decodifica el audio directamente (sin pérdidas, hasta su máxima resolución).",
        "en": "The device fetches and decodes the audio itself (lossless, up to its maximum resolution).",
        "ca": "El dispositiu descarrega i descodifica l'àudio directament (sense pèrdues, fins a la seva màxima resolució).",
    },
    "devices.network_failed": {
        "es": "No se pudo reproducir en {name}: {reason}",
        "en": "Could not play on {name}: {reason}",
        "ca": "No s'ha pogut reproduir a {name}: {reason}",
    },
    "devices.network_not_found": {
        "es": "No se encuentra el dispositivo de red '{name}'. Comprueba que está encendido y en la misma red.",
        "en": "Network device '{name}' not found. Make sure it is on and on the same network.",
        "ca": "No es troba el dispositiu de xarxa '{name}'. Comprova que està encès i a la mateixa xarxa.",
    },
    "devices.dsd_native_rejected": {
        "es": "{dsd} no se puede enviar en nativo a este DAC: se convierte a PCM de alta resolución, sin salir del modo exclusivo.",
        "en": "{dsd} cannot be sent natively to this DAC: it is converted to high-resolution PCM, staying in exclusive mode.",
        "ca": "{dsd} no es pot enviar en natiu a aquest DAC: es converteix a PCM d'alta resolució, sense sortir del mode exclusiu.",
    },
    "devices.status_dsd_native": {
        "es": "DSD nativo · {dsd}",
        "en": "Native DSD · {dsd}",
        "ca": "DSD natiu · {dsd}",
    },
    "devices.status_dsd_pcm": {
        "es": "DSD → PCM · {rate}",
        "en": "DSD → PCM · {rate}",
        "ca": "DSD → PCM · {rate}",
    },
    "player.dsd_native_tooltip": {
        "es": "El flujo DSD llega al DAC tal cual, sin convertirlo a PCM ni empaquetarlo en DoP",
        "en": "The DSD stream reaches the DAC as is, without PCM conversion or DoP packing",
        "ca": "El flux DSD arriba al DAC tal qual, sense convertir-lo a PCM ni empaquetar-lo en DoP",
    },
    "player.dsd_pcm_tooltip": {
        "es": "Este DAC no admite DSD nativo: la pista se convierte a PCM",
        "en": "This DAC does not accept native DSD: the track is converted to PCM",
        "ca": "Aquest DAC no admet DSD natiu: la pista es converteix a PCM",
    },
    "devices.status_resampling": {
        "es": "Remuestreo a {rate}",
        "en": "Resampled to {rate}",
        "ca": "Remostreig a {rate}",
    },
    "devices.status_depth": {
        "es": "Reducido a {bits} bits",
        "en": "Reduced to {bits} bits",
        "ca": "Reduït a {bits} bits",
    },
    "player.cover_tooltip": {
        "es": "Ver la portada a gran tamaño",
        "en": "Show the cover art full size",
        "ca": "Mostra la portada a mida gran",
    },
    "player.volume_down": {
        "es": "Bajar volumen (1 %)",
        "en": "Volume down (1 %)",
        "ca": "Abaixar el volum (1 %)",
    },
    "player.volume_up": {
        "es": "Subir volumen (1 %)",
        "en": "Volume up (1 %)",
        "ca": "Apujar el volum (1 %)",
    },
    "player.volume_hardware": {
        "es": "Volumen del DAC (por hardware: la señal digital llega intacta)",
        "en": "DAC volume (hardware: the digital signal arrives untouched)",
        "ca": "Volum del DAC (per maquinari: el senyal digital arriba intacte)",
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
    "prefs.behavior_group": {
        "es": "Comportamiento",
        "en": "Behavior",
        "ca": "Comportament",
    },
    "prefs.close_to_tray": {
        "es": "Permanecer en la bandeja al cerrar",
        "en": "Keep in system tray on close",
        "ca": "Mantenir a la safata en tancar",
    },
    "prefs.close_to_tray_desc": {
        "es": "Mantener MyFlac reproduciendo en segundo plano al cerrar la ventana. Si se desactiva, cerrar la ventana saldrá de la aplicación completamente.",
        "en": "Keep MyFlac playing in the background when closing the window. If disabled, closing the window will exit completely.",
        "ca": "Mantenir MyFlac reproduint en segon pla en tancar la finestra. Si es desactiva, tancar la finestra sortirà de l'aplicació completament.",
    },
    "prefs.ui_group": {
        "es": "Interfaz",
        "en": "Interface",
        "ca": "Interfície",
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
    "prefs.appearance_page": {
        "es": "Apariencia",
        "en": "Appearance",
        "ca": "Aparença",
    },
    "prefs.tone": {
        "es": "Tono",
        "en": "Tone",
        "ca": "To",
    },
    "prefs.tone_dark_obsidian": {
        "es": "Obsidiana",
        "en": "Obsidian",
        "ca": "Obsidiana",
    },
    "prefs.tone_dark_midnight": {
        "es": "Medianoche",
        "en": "Midnight",
        "ca": "Mitjanit",
    },
    "prefs.tone_dark_espresso": {
        "es": "Espresso",
        "en": "Espresso",
        "ca": "Espresso",
    },
    "prefs.tone_dark_oled": {
        "es": "OLED (negro puro)",
        "en": "OLED (pure black)",
        "ca": "OLED (negre pur)",
    },
    "prefs.tone_dark_graphite": {
        "es": "Grafito",
        "en": "Graphite",
        "ca": "Grafit",
    },
    "prefs.tone_light_slate": {
        "es": "Pizarra suave",
        "en": "Soft slate",
        "ca": "Pissarra suau",
    },
    "prefs.tone_light_paper": {
        "es": "Papel cálido",
        "en": "Warm paper",
        "ca": "Paper càlid",
    },
    "prefs.tone_light_slate_mid": {
        "es": "Pizarra media",
        "en": "Medium slate",
        "ca": "Pissarra mitjana",
    },
    "prefs.tone_light_graphite": {
        "es": "Grafito claro",
        "en": "Light graphite",
        "ca": "Grafit clar",
    },
    "prefs.tone_light_sage": {
        "es": "Salvia",
        "en": "Sage",
        "ca": "Sàlvia",
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
    "prefs.oscilloscope_enabled": {
        "es": "Osciloscopio en tiempo real",
        "en": "Real-time oscilloscope",
        "ca": "Oscil·loscopi en temps real",
    },
    "prefs.oscilloscope_desc": {
        "es": "Muestra la animación de onda sobre la portada del disco; si se desactiva, se muestra solo la carátula limpia",
        "en": "Shows waveform animation over album cover; when disabled, shows clean cover art only",
        "ca": "Mostra l'animació d'ona sobre la portada del disc; si es desactiva, es mostra només la caràtula neta",
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
        "es": "Organiza tu colección local de música Hi-Res o explora directamente tus servicios de streaming favoritos.",
        "en": "Organize your local Hi-Res music collection or explore your favorite streaming services right away.",
        "ca": "Organitza la teva col·lecció local de música Hi-Res o explora directament els teus serveis de streaming preferits.",
    },
    "setup.choose_btn": {
        "es": "Seleccionar Carpeta de Música",
        "en": "Select Music Folder",
        "ca": "Seleccionar Carpeta de Música",
    },
    "setup.continue_tidal": {
        "es": "Continuar a TIDAL",
        "en": "Continue to TIDAL",
        "ca": "Continuar a TIDAL",
    },
    "setup.continue_qobuz": {
        "es": "Continuar a Qobuz",
        "en": "Continue to Qobuz",
        "ca": "Continuar a Qobuz",
    },
    "setup.skip_btn": {
        "es": "Omitir por ahora",
        "en": "Skip for now",
        "ca": "Ometre per ara",
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

    # --- Navegación y Vistas ---
    "nav.library": {
        "es": "Biblioteca",
        "en": "Library",
        "ca": "Biblioteca",
    },
    "nav.library_tooltip": {
        "es": "Colección de música local",
        "en": "Local music collection",
        "ca": "Col·lecció de música local",
    },
    "nav.qobuz": {
        "es": "Qobuz",
        "en": "Qobuz",
        "ca": "Qobuz",
    },
    "nav.qobuz_tooltip": {
        "es": "Catálogo Hi-Res de Qobuz con filtros por género",
        "en": "Qobuz Hi-Res catalog with genre filters",
        "ca": "Catàleg Hi-Res de Qobuz amb filtres per gènere",
    },

    # --- Explorador Qobuz ---
    "qobuz.badge_tooltip": {
        "es": "Catálogo Hi-Res y Bit-Perfect de Qobuz",
        "en": "Qobuz Hi-Res and Bit-Perfect catalog",
        "ca": "Catàleg Hi-Res i Bit-Perfect de Qobuz",
    },
    "qobuz.genre_label": {
        "es": "Género:",
        "en": "Genre:",
        "ca": "Gènere:",
    },
    "qobuz.show_label": {
        "es": "Mostrar:",
        "en": "Show:",
        "ca": "Mostrar:",
    },
    "qobuz.cat.recent": {
        "es": "Novedades",
        "en": "New Releases",
        "ca": "Novetats",
    },
    "qobuz.cat.most_streamed": {
        "es": "Más escuchados",
        "en": "Most Streamed",
        "ca": "Més escoltats",
    },
    "qobuz.cat.press_awards": {
        "es": "Premios de crítica",
        "en": "Press Awards",
        "ca": "Premis de crítica",
    },
    "qobuz.cat.ideal_discography": {
        "es": "Esenciales",
        "en": "Essential",
        "ca": "Essencials",
    },
    "qobuz.search_placeholder": {
        "es": "Buscar en Qobuz...",
        "en": "Search Qobuz...",
        "ca": "Cercar a Qobuz...",
    },
    "qobuz.no_albums_found": {
        "es": "No se encontraron álbumes para el filtro seleccionado.",
        "en": "No albums found for the selected filter.",
        "ca": "No s'han trobat àlbums per al filtre seleccionat.",
    },
    "qobuz.select_album_hint": {
        "es": "Selecciona un álbum para ver sus pistas.",
        "en": "Select an album to view its tracks.",
        "ca": "Selecciona un àlbum per veure les seves pistes.",
    },
    "qobuz.play_album": {
        "es": "Reproducir álbum",
        "en": "Play album",
        "ca": "Reproduir àlbum",
    },
    "qobuz.loading_tracks": {
        "es": "Obteniendo pistas de audio...",
        "en": "Loading audio tracks...",
        "ca": "Obtenint pistes d'àudio...",
    },
    "qobuz.play_track_tooltip": {
        "es": "Reproducir pista",
        "en": "Play track",
        "ca": "Reproduir pista",
    },
    "qobuz.queue_track_tooltip": {
        "es": "Añadir a la cola",
        "en": "Add to queue",
        "ca": "Afegir a la cua",
    },
    "qobuz.account.login_btn": {
        "es": "Iniciar sesión",
        "en": "Sign in",
        "ca": "Inicia la sessió",
    },
    "qobuz.account.login_tooltip": {
        "es": "Haz clic para conectar tu cuenta de Qobuz",
        "en": "Click to connect your Qobuz account",
        "ca": "Fes clic per connectar el teu compte de Qobuz",
    },
    "qobuz.account.connected_btn": {
        "es": "🟢 Qobuz ({name})",
        "en": "🟢 Qobuz ({name})",
        "ca": "🟢 Qobuz ({name})",
    },
    "qobuz.account.connected_tooltip": {
        "es": "Cuenta Qobuz activa: {plan}",
        "en": "Active Qobuz account: {plan}",
        "ca": "Compte Qobuz actiu: {plan}",
    },

    # --- Pantalla de Inicio de Sesión Requerido ---
    "qobuz.login_required_title": {
        "es": "Inicia sesión en Qobuz",
        "en": "Sign in to Qobuz",
        "ca": "Inicia la sessió a Qobuz",
    },
    "qobuz.login_required_desc": {
        "es": "Conecta tu cuenta de Qobuz para explorar el catálogo y reproducir música en streaming FLAC de alta resolución (hasta 24-Bit / 192 kHz).",
        "en": "Connect your Qobuz account to browse the catalog and stream high-resolution FLAC audio (up to 24-Bit / 192 kHz).",
        "ca": "Connecta el teu compte de Qobuz per explorar el catàleg i reproduir música en streaming FLAC d'alta resolució (fins a 24-Bit / 192 kHz).",
    },
    "qobuz.connect_btn": {
        "es": "Iniciar sesión en Qobuz",
        "en": "Sign in with Qobuz",
        "ca": "Inicia la sessió a Qobuz",
    },
    "qobuz.manual_token_btn": {
        "es": "Introducir token manualmente...",
        "en": "Enter token manually...",
        "ca": "Introduir testimoni manualment...",
    },
    "qobuz.manual_token_dialog_title": {
        "es": "Token de autenticación de Qobuz",
        "en": "Qobuz Auth Token",
        "ca": "Token d'autenticació de Qobuz",
    },

    # --- Diálogo de Cuenta Qobuz ---
    "qobuz.dialog.title": {
        "es": "Cuenta Qobuz Hi-Res",
        "en": "Qobuz Hi-Res Account",
        "ca": "Compte Qobuz Hi-Res",
    },
    "qobuz.dialog.status_group": {
        "es": "Estado del servicio",
        "en": "Service status",
        "ca": "Estat del servei",
    },
    "qobuz.dialog.subscription_type": {
        "es": "Tipo de suscripción",
        "en": "Subscription type",
        "ca": "Tipus de subscripció",
    },
    "qobuz.dialog.logout_btn": {
        "es": "Cerrar sesión de Qobuz",
        "en": "Log out from Qobuz",
        "ca": "Tancar sessió de Qobuz",
    },
    "qobuz.dialog.login_group": {
        "es": "Iniciar sesión en Qobuz",
        "en": "Log in to Qobuz",
        "ca": "Iniciar sessió a Qobuz",
    },
    "qobuz.dialog.login_description": {
        "es": "Introduce tu usuario o correo y contraseña de Qobuz para conectar tu cuenta directamente.",
        "en": "Enter your Qobuz username/email and password to connect your account directly.",
        "ca": "Introdueix el teu usuari o correu i contrasenya de Qobuz per connectar el teu compte directament.",
    },
    "qobuz.dialog.email_user_row": {
        "es": "Correo electrónico o usuario",
        "en": "Email or username",
        "ca": "Correu electrònic o usuari",
    },
    "qobuz.dialog.password_row": {
        "es": "Contraseña",
        "en": "Password",
        "ca": "Contrasenya",
    },
    "qobuz.dialog.login_btn": {
        "es": "Iniciar sesión",
        "en": "Log in",
        "ca": "Iniciar sessió",
    },
    "qobuz.dialog.web_sso_btn": {
        "es": "Iniciar sesión con Google, Apple o Web",
        "en": "Log in with Google, Apple or Web",
        "ca": "Iniciar sessió amb Google, Apple o Web",
    },
    "qobuz.dialog.web_window_title": {
        "es": "Acceso web a Qobuz",
        "en": "Qobuz Web Login",
        "ca": "Accés web a Qobuz",
    },
    "qobuz.dialog.advanced_token_row": {
        "es": "Opciones avanzadas (Token manual)",
        "en": "Advanced Options (Manual Token)",
        "ca": "Opcions avançades (Token manual)",
    },
    "qobuz.dialog.token_row": {
        "es": "User Auth Token",
        "en": "User Auth Token",
        "ca": "User Auth Token",
    },
    "qobuz.dialog.connect_token_btn": {
        "es": "Conectar con Token",
        "en": "Connect with Token",
        "ca": "Connectar amb Token",
    },
    "qobuz.dialog.logging_in": {
        "es": "Iniciando sesión en Qobuz...",
        "en": "Logging in to Qobuz...",
        "ca": "Iniciant sessió a Qobuz...",
    },
    "qobuz.dialog.prompt_creds": {
        "es": "Por favor, introduce tu usuario/correo y contraseña.",
        "en": "Please enter your username/email and password.",
        "ca": "Si us plau, introdueix el teu usuari/correu i contrasenya.",
    },
    "qobuz.dialog.invalid_creds": {
        "es": "Correo electrónico o contraseña incorrectos.",
        "en": "Invalid email or password.",
        "ca": "Correu electrònic o contrasenya incorrectes.",
    },
    "qobuz.dialog.login_success": {
        "es": "¡Sesión iniciada con éxito como {name}!",
        "en": "Successfully logged in as {name}!",
        "ca": "Sessió iniciada amb èxit com a {name}!",
    },
    "qobuz.dialog.security_check": {
        "es": "Completa la verificación de seguridad en pantalla...",
        "en": "Complete the security verification on screen...",
        "ca": "Completa la verificació de seguretat en pantalla...",
    },
    "qobuz.dialog.prompt_token": {
        "es": "Por favor, introduce el token de usuario.",
        "en": "Please enter user token.",
        "ca": "Si us plau, introdueix el token d'usuari.",
    },
    "qobuz.dialog.verifying": {
        "es": "Verificando token con Qobuz...",
        "en": "Verifying token with Qobuz...",
        "ca": "Verificant token amb Qobuz...",
    },
    "qobuz.err.network": {
        "es": "No se pudo conectar con Qobuz: {error}",
        "en": "Could not connect to Qobuz: {error}",
        "ca": "No s'ha pogut connectar amb Qobuz: {error}",
    },
    "qobuz.err.app_credentials": {
        "es": "Faltan las credenciales de aplicación de Qobuz (app_id y app_secret). Qobuz las concede a cada desarrollador; añádelas en {path}.",
        "en": "Qobuz application credentials (app_id and app_secret) are missing. Qobuz grants them to each developer; add them to {path}.",
        "ca": "Falten les credencials d'aplicació de Qobuz (app_id i app_secret). Qobuz les concedeix a cada desenvolupador; afegeix-les a {path}.",
    },
    "qobuz.err.session_expired": {
        "es": "Tu sesión de Qobuz ha caducado. Vuelve a iniciar sesión.",
        "en": "Your Qobuz session has expired. Please log in again.",
        "ca": "La teva sessió de Qobuz ha caducat. Torna a iniciar sessió.",
    },
    "qobuz.err.invalid_token": {
        "es": "Token no válido (HTTP {code}).",
        "en": "Invalid token (HTTP {code}).",
        "ca": "Token no vàlid (HTTP {code}).",
    },
    "qobuz.err.http": {
        "es": "Qobuz ha respondido con un error (HTTP {code}). {message}",
        "en": "Qobuz returned an error (HTTP {code}). {message}",
        "ca": "Qobuz ha respost amb un error (HTTP {code}). {message}",
    },
    "qobuz.err.stream_unavailable": {
        "es": "No se puede reproducir «{title}» desde Qobuz: {error}",
        "en": "Cannot play “{title}” from Qobuz: {error}",
        "ca": "No es pot reproduir «{title}» des de Qobuz: {error}",
    },
    "qobuz.sample_only": {
        "es": "Qobuz solo da un fragmento de 30 segundos de «{title}»: tu suscripción no incluye la escucha completa.",
        "en": "Qobuz only provides a 30-second preview of “{title}”: your subscription does not include full streaming.",
        "ca": "Qobuz només dona un fragment de 30 segons de «{title}»: la teva subscripció no inclou l'escolta completa.",
    },
    "qobuz.all_genres": {
        "es": "Todos los géneros",
        "en": "All genres",
        "ca": "Tots els gèneres",
    },
    "qobuz.no_tracks": {
        "es": "No se han podido cargar las pistas de este álbum.",
        "en": "Could not load this album's tracks.",
        "ca": "No s'han pogut carregar les pistes d'aquest àlbum.",
    },
    "qobuz.dialog.user_fallback": {
        "es": "Usuario conectado",
        "en": "Connected user",
        "ca": "Usuari connectat",
    },
    "qobuz.dialog.session_active": {
        "es": "Sesión activa",
        "en": "Active session",
        "ca": "Sessió activa",
    },
    "qobuz.dialog.subscription_unknown": {
        "es": "Suscripción de Qobuz",
        "en": "Qobuz subscription",
        "ca": "Subscripció de Qobuz",
    },
    "qobuz.dialog.web_subtitle": {
        "es": "Inicia sesión con tu cuenta de Qobuz, Google o Apple",
        "en": "Log in with your Qobuz, Google or Apple account",
        "ca": "Inicia sessió amb el teu compte de Qobuz, Google o Apple",
    },
    "qobuz.dialog.syncing": {
        "es": "Sesión detectada: conectando con MyFlac...",
        "en": "Session detected: connecting to MyFlac...",
        "ca": "Sessió detectada: connectant amb MyFlac...",
    },
    "qobuz.dialog.session_not_found": {
        "es": "No se ha encontrado la sesión. Prueba con correo y contraseña.",
        "en": "Session not found. Try email and password instead.",
        "ca": "No s'ha trobat la sessió. Prova amb correu i contrasenya.",
    },
    "qobuz.dialog.other_methods_btn": {
        "es": "Correo o token",
        "en": "Email or token",
        "ca": "Correu o token",
    },
    "devices.network_stream_failed": {
        "es": "no se pudo obtener la URL de streaming ({error})",
        "en": "could not get the streaming URL ({error})",
        "ca": "no s'ha pogut obtenir l'URL de streaming ({error})",
    },
    "devices.network_no_start": {
        "es": "el dispositivo no ha empezado a reproducir",
        "en": "the device did not start playing",
        "ca": "el dispositiu no ha començat a reproduir",
    },
    "devices.network_local_blocked": {
        "es": "el dispositivo no ha podido descargar el archivo de este equipo. Permite conexiones entrantes al puerto TCP {port} en el cortafuegos (Fedora: sudo firewall-cmd --permanent --add-port={port}/tcp && sudo firewall-cmd --reload)",
        "en": "the device could not download the file from this computer. Allow incoming connections to TCP port {port} in the firewall (Fedora: sudo firewall-cmd --permanent --add-port={port}/tcp && sudo firewall-cmd --reload)",
        "ca": "el dispositiu no ha pogut descarregar el fitxer d'aquest equip. Permet connexions entrants al port TCP {port} al tallafoc (Fedora: sudo firewall-cmd --permanent --add-port={port}/tcp && sudo firewall-cmd --reload)",
    },
    "qobuz.section.explore": {
        "es": "Explorar",
        "en": "Explore",
        "ca": "Explorar",
    },
    "qobuz.section.library": {
        "es": "Mi biblioteca",
        "en": "My library",
        "ca": "La meva biblioteca",
    },
    "qobuz.lib.albums": {
        "es": "Álbumes favoritos",
        "en": "Favorite albums",
        "ca": "Àlbums preferits",
    },
    "qobuz.lib.tracks": {
        "es": "Temas favoritos",
        "en": "Favorite tracks",
        "ca": "Temes preferits",
    },
    "qobuz.lib.artists": {
        "es": "Artistas favoritos",
        "en": "Favorite artists",
        "ca": "Artistes preferits",
    },
    "qobuz.lib.playlists": {
        "es": "Listas de reproducción",
        "en": "Playlists",
        "ca": "Llistes de reproducció",
    },
    "qobuz.playlist_tracks": {
        "es": "{n} temas",
        "en": "{n} tracks",
        "ca": "{n} temes",
    },
    "qobuz.artist_albums": {
        "es": "{n} álbumes",
        "en": "{n} albums",
        "ca": "{n} àlbums",
    },
    "qobuz.back_to": {
        "es": "Volver a {name}",
        "en": "Back to {name}",
        "ca": "Tornar a {name}",
    },
    "qobuz.library_empty": {
        "es": "No hay nada de este tipo en tu biblioteca de Qobuz.",
        "en": "There is nothing of this kind in your Qobuz library.",
        "ca": "No hi ha res d'aquest tipus a la teva biblioteca de Qobuz.",
    },
    "qobuz.play_playlist": {
        "es": "Reproducir lista",
        "en": "Play playlist",
        "ca": "Reproduir llista",
    },
    "qobuz.no_artist_albums": {
        "es": "No se han encontrado álbumes de este artista.",
        "en": "No albums found for this artist.",
        "ca": "No s'han trobat àlbums d'aquest artista.",
    },
    "qobuz.releases.album": {
        "es": "Álbumes",
        "en": "Albums",
        "ca": "Àlbums",
    },
    "qobuz.releases.epSingle": {
        "es": "EPs y singles",
        "en": "EPs & singles",
        "ca": "EPs i senzills",
    },
    "qobuz.releases.live": {
        "es": "Directos",
        "en": "Live",
        "ca": "Directes",
    },
    "qobuz.releases.compilation": {
        "es": "Recopilatorios",
        "en": "Compilations",
        "ca": "Recopilatoris",
    },
    "qobuz.releases.empty_album": {
        "es": "Este artista no tiene álbumes en Qobuz.",
        "en": "This artist has no albums on Qobuz.",
        "ca": "Aquest artista no té àlbums a Qobuz.",
    },
    "qobuz.releases.empty_epSingle": {
        "es": "Este artista no tiene EPs ni singles en Qobuz.",
        "en": "This artist has no EPs or singles on Qobuz.",
        "ca": "Aquest artista no té EPs ni senzills a Qobuz.",
    },
    "qobuz.releases.empty_live": {
        "es": "Este artista no tiene discos en directo en Qobuz.",
        "en": "This artist has no live albums on Qobuz.",
        "ca": "Aquest artista no té discos en directe a Qobuz.",
    },
    "qobuz.releases.empty_compilation": {
        "es": "Este artista no tiene recopilatorios en Qobuz.",
        "en": "This artist has no compilations on Qobuz.",
        "ca": "Aquest artista no té recopilatoris a Qobuz.",
    },
    "qobuz.fav.added": {
        "es": "«{name}» añadido a tu biblioteca de Qobuz",
        "en": "“{name}” added to your Qobuz library",
        "ca": "«{name}» afegit a la teva biblioteca de Qobuz",
    },
    "qobuz.fav.removed": {
        "es": "«{name}» quitado de tu biblioteca de Qobuz",
        "en": "“{name}” removed from your Qobuz library",
        "ca": "«{name}» tret de la teva biblioteca de Qobuz",
    },
    "qobuz.fav.add_tracks": {
        "es": "Añadir el tema a mi biblioteca",
        "en": "Add track to my library",
        "ca": "Afegir el tema a la meva biblioteca",
    },
    "qobuz.fav.add_albums": {
        "es": "Añadir el álbum a mi biblioteca",
        "en": "Add album to my library",
        "ca": "Afegir l'àlbum a la meva biblioteca",
    },
    "qobuz.fav.add_artists": {
        "es": "Añadir el artista a mi biblioteca",
        "en": "Add artist to my library",
        "ca": "Afegir l'artista a la meva biblioteca",
    },
    "qobuz.fav.remove_tracks": {
        "es": "Quitar el tema de mi biblioteca",
        "en": "Remove track from my library",
        "ca": "Treure el tema de la meva biblioteca",
    },
    "qobuz.fav.remove_albums": {
        "es": "Quitar el álbum de mi biblioteca",
        "en": "Remove album from my library",
        "ca": "Treure l'àlbum de la meva biblioteca",
    },
    "qobuz.fav.remove_artists": {
        "es": "Quitar el artista de mi biblioteca",
        "en": "Remove artist from my library",
        "ca": "Treure l'artista de la meva biblioteca",
    },
    "qobuz.fav.in_library": {
        "es": "En mi biblioteca",
        "en": "In my library",
        "ca": "A la meva biblioteca",
    },
    "qobuz.view_artist": {
        "es": "Ver artista",
        "en": "View artist",
        "ca": "Veure l'artista",
    },
    "qobuz.search.artists": {
        "es": "Artistas",
        "en": "Artists",
        "ca": "Artistes",
    },
    "qobuz.search.albums": {
        "es": "Álbumes",
        "en": "Albums",
        "ca": "Àlbums",
    },
    "qobuz.booklet.default_name": {
        "es": "Libreto digital",
        "en": "Digital booklet",
        "ca": "Llibret digital",
    },
    "qobuz.booklet.view": {
        "es": "Abrir el PDF en el visor de documentos",
        "en": "Open the PDF in the document viewer",
        "ca": "Obrir el PDF al visor de documents",
    },
    "qobuz.booklet.save": {
        "es": "Guardar el PDF…",
        "en": "Save the PDF…",
        "ca": "Desar el PDF…",
    },
    "qobuz.booklet.downloading": {
        "es": "Descargando el libreto…",
        "en": "Downloading the booklet…",
        "ca": "Descarregant el llibret…",
    },
    "qobuz.booklet.saved": {
        "es": "Libreto guardado en {path}",
        "en": "Booklet saved to {path}",
        "ca": "Llibret desat a {path}",
    },
    "qobuz.booklet.failed": {
        "es": "No se pudo descargar el libreto: {error}",
        "en": "Could not download the booklet: {error}",
        "ca": "No s'ha pogut descarregar el llibret: {error}",
    },
    "tidal.account.connected_btn": {
        "es": "🟢 TIDAL ({name})",
        "en": "🟢 TIDAL ({name})",
        "ca": "🟢 TIDAL ({name})",
    },
    "tidal.account.connected_tooltip": {
        "es": "Cuenta de TIDAL activa",
        "en": "Active TIDAL account",
        "ca": "Compte de TIDAL actiu",
    },
    "tidal.account.login_tooltip": {
        "es": "Haz clic para conectar tu cuenta de TIDAL",
        "en": "Click to connect your TIDAL account",
        "ca": "Fes clic per connectar el teu compte de TIDAL",
    },
    "tidal.badge_tooltip": {
        "es": "Catálogo de TIDAL (API oficial)",
        "en": "TIDAL catalog (official API)",
        "ca": "Catàleg de TIDAL (API oficial)",
    },
    "tidal.connect_btn": {
        "es": "Conectar con TIDAL",
        "en": "Connect to TIDAL",
        "ca": "Connectar amb TIDAL",
    },
    "tidal.login_required_title": {
        "es": "Conecta tu cuenta de TIDAL",
        "en": "Connect your TIDAL account",
        "ca": "Connecta el teu compte de TIDAL",
    },
    "tidal.login_required_desc": {
        "es": "Conecta tu cuenta de TIDAL para explorar tus mezclas, tu colección y el catálogo en FLAC (hasta Hi-Res).",
        "en": "Connect your TIDAL account to browse your mixes, your collection and the FLAC catalog (up to Hi-Res).",
        "ca": "Connecta el teu compte de TIDAL per explorar les teves mescles, la teva col·lecció i el catàleg en FLAC (fins a Hi-Res).",
    },
    "tidal.search_placeholder": {
        "es": "Buscar en TIDAL...",
        "en": "Search TIDAL...",
        "ca": "Cercar a TIDAL...",
    },
    "tidal.manual_token_btn": {
        "es": "Configurar la app de TIDAL...",
        "en": "Configure the TIDAL app...",
        "ca": "Configurar l'app de TIDAL...",
    },
    "tidal.fav.added": {
        "es": "«{name}» añadido a tu colección de TIDAL",
        "en": "“{name}” added to your TIDAL collection",
        "ca": "«{name}» afegit a la teva col·lecció de TIDAL",
    },
    "tidal.fav.removed": {
        "es": "«{name}» quitado de tu colección de TIDAL",
        "en": "“{name}” removed from your TIDAL collection",
        "ca": "«{name}» tret de la teva col·lecció de TIDAL",
    },
    "tidal.library_empty": {
        "es": "No hay nada de este tipo en tu colección de TIDAL.",
        "en": "There is nothing of this kind in your TIDAL collection.",
        "ca": "No hi ha res d'aquest tipus a la teva col·lecció de TIDAL.",
    },
    "tidal.releases.empty_album": {
        "es": "Este artista no tiene álbumes en TIDAL.",
        "en": "This artist has no albums on TIDAL.",
        "ca": "Aquest artista no té àlbums a TIDAL.",
    },
    "tidal.releases.empty_epSingle": {
        "es": "Este artista no tiene EPs ni singles en TIDAL.",
        "en": "This artist has no EPs or singles on TIDAL.",
        "ca": "Aquest artista no té EPs ni senzills a TIDAL.",
    },
    "tidal.err.stream_unavailable": {
        "es": "No se puede reproducir «{title}» desde TIDAL: {error}",
        "en": "Cannot play “{title}” from TIDAL: {error}",
        "ca": "No es pot reproduir «{title}» des de TIDAL: {error}",
    },
    "tidal.sample_only": {
        "es": "TIDAL solo da un fragmento de «{title}»: tu suscripción no incluye la escucha completa.",
        "en": "TIDAL only provides a preview of “{title}”: your subscription does not include full streaming.",
        "ca": "TIDAL només dona un fragment de «{title}»: la teva subscripció no inclou l'escolta completa.",
    },
    "tidal.cat.new_releases": {
        "es": "Novedades para ti",
        "en": "New releases for you",
        "ca": "Novetats per a tu",
    },
    "tidal.cat.discovery": {
        "es": "Descubrimiento",
        "en": "Discovery",
        "ca": "Descobriment",
    },
    "tidal.cat.daily": {
        "es": "Mezclas diarias",
        "en": "Daily mixes",
        "ca": "Mescles diàries",
    },
    "tidal.err.app_credentials": {
        "es": "No hay app de TIDAL configurada. Revisa {path}.",
        "en": "No TIDAL app configured. Check {path}.",
        "ca": "No hi ha cap app de TIDAL configurada. Revisa {path}.",
    },
    "tidal.err.redirect_uri": {
        "es": "La dirección de retorno ({uri}) tiene que ser local, con puerto, como http://localhost:8723/callback.",
        "en": "The redirect URI ({uri}) must be local with a port, like http://localhost:8723/callback.",
        "ca": "L'adreça de retorn ({uri}) ha de ser local, amb port, com http://localhost:8723/callback.",
    },
    "tidal.err.port_busy": {
        "es": "No se puede escuchar en el puerto {port} para recibir el inicio de sesión: {error}",
        "en": "Cannot listen on port {port} to receive the login: {error}",
        "ca": "No es pot escoltar al port {port} per rebre l'inici de sessió: {error}",
    },
    "tidal.err.login_timeout": {
        "es": "No ha llegado la respuesta de TIDAL. Vuelve a intentarlo.",
        "en": "No response from TIDAL. Please try again.",
        "ca": "No ha arribat la resposta de TIDAL. Torna-ho a provar.",
    },
    "tidal.err.login_failed": {
        "es": "TIDAL no ha permitido el inicio de sesión: {error}",
        "en": "TIDAL refused the login: {error}",
        "ca": "TIDAL no ha permès l'inici de sessió: {error}",
    },
    "tidal.err.session_expired": {
        "es": "Tu sesión de TIDAL ha caducado. Vuelve a conectar.",
        "en": "Your TIDAL session has expired. Please reconnect.",
        "ca": "La teva sessió de TIDAL ha caducat. Torna a connectar.",
    },
    "tidal.err.network": {
        "es": "No se pudo conectar con TIDAL: {error}",
        "en": "Could not connect to TIDAL: {error}",
        "ca": "No s'ha pogut connectar amb TIDAL: {error}",
    },
    "tidal.err.http": {
        "es": "TIDAL ha respondido con un error (HTTP {code}). {message}",
        "en": "TIDAL returned an error (HTTP {code}). {message}",
        "ca": "TIDAL ha respost amb un error (HTTP {code}). {message}",
    },
    "tidal.err.drm": {
        "es": "TIDAL entrega esta pista cifrada con DRM y MyFlac no puede reproducirla.",
        "en": "TIDAL delivers this track DRM-encrypted and MyFlac cannot play it.",
        "ca": "TIDAL lliura aquesta pista xifrada amb DRM i MyFlac no la pot reproduir.",
    },
    "tidal.dialog.title": {
        "es": "Conectar con TIDAL",
        "en": "Connect to TIDAL",
        "ca": "Connectar amb TIDAL",
    },
    "tidal.dialog.app_group": {
        "es": "Avanzado: usar mi propia app de TIDAL",
        "en": "Advanced: use my own TIDAL app",
        "ca": "Avançat: fer servir la meva pròpia app de TIDAL",
    },
    "tidal.dialog.app_help": {
        "es": "No hace falta: MyFlac ya trae la suya. Solo si tienes una app propia en developer.tidal.com (con {redirect} como Redirect URI).",
        "en": "Not needed: MyFlac has its own. Only if you have your own app at developer.tidal.com (with {redirect} as Redirect URI).",
        "ca": "No cal: MyFlac ja porta la seva. Només si tens una app pròpia a developer.tidal.com (amb {redirect} com a Redirect URI).",
    },
    "tidal.dialog.client_id": {
        "es": "Client ID",
        "en": "Client ID",
        "ca": "Client ID",
    },
    "tidal.dialog.client_secret": {
        "es": "Client Secret (opcional)",
        "en": "Client Secret (optional)",
        "ca": "Client Secret (opcional)",
    },
    "tidal.dialog.redirect_uri": {
        "es": "Dirección de retorno (Redirect URI)",
        "en": "Redirect URI",
        "ca": "Adreça de retorn (Redirect URI)",
    },
    "tidal.dialog.login_group": {
        "es": "Tu cuenta",
        "en": "Your account",
        "ca": "El teu compte",
    },
    "tidal.dialog.login_help": {
        "es": "Se abrirá la web de TIDAL en el navegador. Inicia sesión y acepta: MyFlac recibirá la sesión automáticamente.",
        "en": "The TIDAL website will open in your browser. Sign in and accept: MyFlac will receive the session automatically.",
        "ca": "S'obrirà la web de TIDAL al navegador. Inicia sessió i accepta: MyFlac rebrà la sessió automàticament.",
    },
    "tidal.dialog.login_btn": {
        "es": "Iniciar sesión en TIDAL",
        "en": "Sign in to TIDAL",
        "ca": "Inicia la sessió a TIDAL",
    },
    "tidal.dialog.prompt_client_id": {
        "es": "Introduce el Client ID de tu app de TIDAL.",
        "en": "Enter your TIDAL app's Client ID.",
        "ca": "Introdueix el Client ID de la teva app de TIDAL.",
    },
    "tidal.dialog.waiting_browser": {
        "es": "Esperando a que inicies sesión en el navegador…",
        "en": "Waiting for you to sign in in the browser…",
        "ca": "Esperant que iniciïs sessió al navegador…",
    },
    "tidal.dialog.browser_done": {
        "es": "Sesión de TIDAL conectada. Ya puedes cerrar esta pestaña y volver a MyFlac.",
        "en": "TIDAL session connected. You can close this tab and return to MyFlac.",
        "ca": "Sessió de TIDAL connectada. Ja pots tancar aquesta pestanya i tornar a MyFlac.",
    },
    "tidal.dialog.account_title": {
        "es": "Cuenta de TIDAL",
        "en": "TIDAL account",
        "ca": "Compte de TIDAL",
    },
    "tidal.dialog.country": {
        "es": "País",
        "en": "Country",
        "ca": "País",
    },
    "tidal.dialog.logout_btn": {
        "es": "Desconectar TIDAL",
        "en": "Disconnect TIDAL",
        "ca": "Desconnectar TIDAL",
    },
    "nav.tidal": {
        "es": "Tidal",
        "en": "Tidal",
        "ca": "Tidal",
    },
    "nav.tidal_tooltip": {
        "es": "Explorar y escuchar TIDAL",
        "en": "Browse and listen to TIDAL",
        "ca": "Explorar i escoltar TIDAL",
    },
    "tidal.sample_app_tier": {
        "es": "TIDAL solo da un fragmento de «{title}» porque la app de MyFlac está aún en el nivel de pruebas («Third party»). Tu suscripción no es el problema: hay que pedir a TIDAL el acceso de producción en developer.tidal.com.",
        "en": "TIDAL only provides a preview of “{title}” because the MyFlac app is still on the test tier (“Third party”). Your subscription is not the problem: production access must be requested from TIDAL at developer.tidal.com.",
        "ca": "TIDAL només dona un fragment de «{title}» perquè l'app de MyFlac encara és al nivell de proves («Third party»). La teva subscripció no és el problema: cal demanar a TIDAL l'accés de producció a developer.tidal.com.",
    },
    "tidal.sample_purchase": {
        "es": "TIDAL solo da un fragmento de «{title}»: esta pista hay que comprarla.",
        "en": "TIDAL only provides a preview of “{title}”: this track must be purchased.",
        "ca": "TIDAL només dona un fragment de «{title}»: aquesta pista s'ha de comprar.",
    },
    "prefs.streaming_group": {
        "es": "Servicios de streaming",
        "en": "Streaming services",
        "ca": "Serveis de streaming",
    },
    "prefs.qobuz_desc": {
        "es": "Explorar y escuchar Qobuz en Hi-Res. Si lo desactivas, desaparece de MyFlac.",
        "en": "Browse and listen to Qobuz in Hi-Res. If disabled, it disappears from MyFlac.",
        "ca": "Explorar i escoltar Qobuz en Hi-Res. Si el desactives, desapareix de MyFlac.",
    },
    "prefs.tidal_desc": {
        "es": "Explorar y escuchar TIDAL. Si lo desactivas, desaparece de MyFlac.",
        "en": "Browse and listen to TIDAL. If disabled, it disappears from MyFlac.",
        "ca": "Explorar i escoltar TIDAL. Si el desactives, desapareix de MyFlac.",
    },
    "prefs.tidal_coming_soon": {
        "es": "Próximamente",
        "en": "Coming soon",
        "ca": "Pròximament",
    },
    "qobuz.booklet.score": {
        "es": "Partitura",
        "en": "Score",
        "ca": "Partitura",
    },
    "qobuz.booklet.lyrics": {
        "es": "Letras",
        "en": "Lyrics",
        "ca": "Lletres",
    },
}
