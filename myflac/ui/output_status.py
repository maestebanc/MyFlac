"""Textos del selector de salida (sin GTK, para poder probarlos sin interfaz)."""
from __future__ import annotations

import re

from .. import i18n
from ..audio.devices import AudioDevice


def format_device_subtitle(dev: AudioDevice) -> str:
    """Subtítulo conciso del dispositivo en el selector de salida."""
    if dev.id == "default":
        return i18n.t("devices.subtitle_default")

    dev_id_lower = dev.id.lower()
    icon_name = (dev.icon_name or "").lower()
    if dev.is_usb or "usb" in dev_id_lower:
        type_label = i18n.t("devices.type_usb")
    elif "hdmi" in dev_id_lower or "video-display" in icon_name:
        m = re.search(r"\[(.*?)\]", dev.description or "")
        type_label = f"HDMI ({m.group(1).strip()})" if m else i18n.t("devices.type_hdmi")
    elif "raop" in dev_id_lower or "network" in icon_name or "airplay" in dev_id_lower:
        type_label = i18n.t("devices.type_network")
    else:
        type_label = i18n.t("devices.type_integrated")

    parts = [type_label]
    if dev.max_sample_rate:
        parts.append(i18n.t("devices.max_sample_rate", rate=f"{dev.max_sample_rate / 1000:g}"))
    return " · ".join(parts)


def output_status(engine) -> tuple[str, str, str]:
    """Texto de estado del transporte, nivel del indicador ('ok', 'warn' o '') y tooltip."""
    if getattr(engine, "remote_active", False):
        return i18n.t("devices.status_network"), "ok", i18n.t("devices.network_tooltip")
    if not engine.exclusive_active:
        return i18n.t("devices.status_mixer"), "", i18n.t("devices.subtitle_default")
    if getattr(engine, "output_dsd", False):
        dsd = f"DSD{engine.output_sample_rate // 44100}" if engine.output_sample_rate else "DSD"
        return i18n.t("devices.status_dsd_native", dsd=dsd), "ok", i18n.t("player.dsd_native_tooltip")
    rate = f"{engine.output_sample_rate / 1000:g} kHz" if engine.output_sample_rate else ""
    if getattr(engine, "dsd_to_pcm", False):
        return (i18n.t("devices.status_dsd_pcm", rate=rate), "warn", i18n.t("player.dsd_pcm_tooltip"))
    if engine.resampling_active:
        return (i18n.t("devices.status_resampling", rate=rate), "warn",
                i18n.t("player.resampling_tooltip", rate=rate))
    if engine.depth_reduced:
        bits = engine.output_bit_depth
        return (i18n.t("devices.status_depth", bits=bits), "warn",
                i18n.t("player.depth_tooltip", bits=bits))
    status = f"Bit-perfect · {rate}" if rate else "Bit-perfect"
    return status, "ok", i18n.t("player.bitperfect_tooltip")


def volume_tooltip(engine) -> str:
    """Explica qué controla el volumen según la salida."""
    if not engine.exclusive_active:
        return i18n.t("player.volume")
    if engine.volume_adjustable:
        return i18n.t("player.volume_hardware")
    return i18n.t("player.volume_locked")
