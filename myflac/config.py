"""Configuración persistente de MyFlac (dispositivos, idioma, temas y UI)."""
from __future__ import annotations

import json
import os

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
    "software_volume": 1.0,
    "ui_scale": 100,
    "theme": "system",          # "system", "light", "dark"
    "window_width": 1280,
    "window_height": 880,
    "window_maximized": False,
    "last_directory": "",
    "repeat_mode": "none",      # "none", "all", "one"
    "shuffle": False,
    "library_folders": [],      # Lista de rutas absolutas de carpetas de biblioteca
    "visualizer_mode": 0,       # 0: Portada, 1: Portada + Osciloscopio, 2: Vúmetro analógico
    "last_track_path": "",      # Ruta del último archivo reproducido
    "last_position": 0.0,       # Última posición en segundos
}


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

    is_first_run = "language" not in data or not data["language"]
    merged = dict(DEFAULTS)
    merged.update(data)

    if is_first_run or merged["language"] not in SUPPORTED_LANGUAGES:
        merged["language"] = _detect_system_language()
        save_config(merged)

    return merged


def save_config(config: dict) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
