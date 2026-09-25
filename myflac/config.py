"""Configuración persistente de MyFlac."""
from __future__ import annotations

import json
import os

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

DEFAULTS = {
    "audio_device_id": "auto",  # 'auto', 'hw:X,Y', 'pipewire'
    "bitperfect_mode": True,    # Exclusivo ALSA sin resampling
    "volume_bypass": True,      # Salida al 100% (0 dB) bit-exact
    "software_volume": 1.0,
    "buffer_time_ms": 200,      # Buffer ALSA seguro
    "ui_scale": 100,
    "theme": "system",          # "system", "light", "dark"
    "window_width": 1280,
    "window_height": 820,
    "window_maximized": False,
    "last_directory": "",
    "repeat_mode": "none",      # "none", "all", "one"
    "shuffle": False,
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

    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_config(config: dict) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
