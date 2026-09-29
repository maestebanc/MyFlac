"""Configuración persistente de MyFlac (dispositivos, idioma, temas y UI)."""
from __future__ import annotations

import json
import os
from typing import Any

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

SUPPORTED_LANGUAGES = ["es", "en", "ca"]
DEFAULT_LANGUAGE_FALLBACK = "es"


def _detect_system_language() -> str:
    """Detecta el idioma del sistema entre los soportados (es, en, ca)."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if not value:
            continue
        for part in value.split(":"):
            code = part.split(".")[0].split("_")[0].lower()
            if code in SUPPORTED_LANGUAGES:
                return code
    try:
        import locale
        loc = locale.getlocale()[0]
        if loc:
            code = loc.split("_")[0].lower()
            if code in SUPPORTED_LANGUAGES:
                return code
    except Exception:
        pass
    return DEFAULT_LANGUAGE_FALLBACK


DEFAULTS = {
    "language": "",             # Vacío para autodetectar
    "audio_device_id": "default",  # 'default' o nombre del sink de PipeWire/Pulse
    "exclusive_mode": False,    # Modo exclusivo bit-perfect (ALSA hw directo); desactivado por defecto
    "exclusive_devices": [],    # Lista de IDs de dispositivos con bit-perfect habilitado
    "software_volume": 1.0,
    "inspector_tab": "lyrics",  # Pestaña del inspector: lyrics, track, album, artist
    "browser_split_position": 430,  # Altura (px) de los paneles Artista/Álbum; se guarda al moverla
    "backdrop_enabled": False,  # Foto del artista desenfocada detrás de la biblioteca (opcional)
    "backdrop_intensity": 10,   # Visibilidad de esa foto en % (10-80)
    "ui_scale": 100,
    "theme": "system",          # "system", "light", "dark"
    "light_variant": "slate",   # Tono del tema claro: slate, paper, slate_mid, graphite, sage
    "dark_variant": "obsidian", # Tono del tema oscuro: obsidian, midnight, espresso, oled, graphite
    "window_width": 1280,
    "window_height": 880,
    "window_maximized": False,
    "last_directory": "",
    "repeat_mode": "none",      # "none", "all", "one"
    "shuffle": False,
    "library_folders": [],      # Lista de rutas absolutas de carpetas de biblioteca
    "visualizer_mode": 0,       # 0: Portada + Osciloscopio (por defecto), 1: Portada limpia
    "oscilloscope_enabled": True, # Activar/desactivar animación del osciloscopio sobre la portada
    "close_to_tray": True,      # True: permanecer en la bandeja del sistema al cerrar; False: salir completamente
    "last_artist": "__ALL__",   # Último artista seleccionado en el navegador
    "last_album": "__ALL__",    # Último álbum seleccionado en el navegador
    "last_track_path": "",      # Ruta del último archivo reproducido
    "last_position": 0.0,       # Última posición en segundos
}


# Ajustes de funciones retiradas (fichas con IA de Gemini, aviso al cerrar la ventana)
OBSOLETE_KEYS = ("gemini_api_key", "background_hint_shown")


def _config_path() -> str:
    config_dir = os.path.join(GLib.get_user_config_dir(), "myflac")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


def load_config() -> dict:
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Claves de funciones retiradas: no se conservan en el archivo
    obsolete = [k for k in OBSOLETE_KEYS if k in data]
    for k in obsolete:
        data.pop(k)

    is_first_run = "language" not in data or not data["language"]
    merged = dict(DEFAULTS)
    merged.update(data)

    if is_first_run or obsolete or merged["language"] not in SUPPORTED_LANGUAGES:
        merged["language"] = _detect_system_language()
        save_config(merged)

    return merged


def save_config(config: dict) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def is_device_exclusive_enabled(cfg: dict, dev_id_or_obj: Any) -> bool:
    """Comprueba si un dispositivo tiene habilitado el modo exclusivo bit-perfect."""
    if not dev_id_or_obj:
        return False
    dev_id = getattr(dev_id_or_obj, "id", str(dev_id_or_obj))
    if not dev_id or dev_id in ("default", "auto", "pipewire"):
        return False

    try:
        from .audio.devices import base_node_name
        base_id = base_node_name(dev_id)
    except Exception:
        base_id = dev_id

    exclusive_list = cfg.get("exclusive_devices", [])
    # Compatibilidad con configuraciones previas donde solo existía exclusive_mode global
    if not exclusive_list and cfg.get("exclusive_mode") and cfg.get("audio_device_id") == dev_id:
        return True

    card_id = getattr(dev_id_or_obj, "alsa_card_id", "")
    return any(
        d == dev_id or d == base_id or (card_id and d == card_id)
        for d in exclusive_list
    )


def set_device_exclusive_enabled(cfg: dict, dev_id_or_obj: Any, enabled: bool):
    """Guarda la preferencia de modo exclusivo para un dispositivo concreto."""
    dev_id = getattr(dev_id_or_obj, "id", str(dev_id_or_obj))
    if not dev_id or dev_id in ("default", "auto", "pipewire"):
        return
    try:
        from .audio.devices import base_node_name
        base_id = base_node_name(dev_id)
    except Exception:
        base_id = dev_id

    current_list = list(cfg.get("exclusive_devices", []))
    card_id = getattr(dev_id_or_obj, "alsa_card_id", "")

    # Eliminar referencias previas
    current_list = [
        d for d in current_list
        if d != dev_id and d != base_id and (not card_id or d != card_id)
    ]
    if enabled:
        current_list.append(base_id)
    cfg["exclusive_devices"] = current_list
