"""Gestión y detección de dispositivos de salida de audio a través del mezclador del sistema."""
from __future__ import annotations

import re
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from ..logger import get_logger
from .. import i18n

log = get_logger("audio.devices")

if not Gst.is_initialized():
    Gst.init(None)


@dataclass
class AudioDevice:
    id: str  # 'default' o node.name de PipeWire / PulseAudio (ej: 'alsa_output.usb-iFi...')
    name: str  # Nombre legible para el usuario
    description: str = ""
    is_usb: bool = False
    is_default: bool = False
    icon_name: str = "audio-speakers-symbolic"


def _clean_device_name(raw_name: str) -> str:
    """Limpia nombres técnicos para mostrarlos de forma elegante en la interfaz."""
    name = raw_name.strip()
    # Eliminar sufijos redundantes de perfil como "Estéreo analógico", "Estéreo digital (HDMI)", etc.
    name = re.sub(r"\s+Est[eé]reo\s+(anal[oó]gico|digital.*)$", "", name, flags=re.IGNORECASE)
    # Acortar prefijos técnicos largos
    name = re.sub(r"^Radeon High Definition Audio Controller", "HDMI", name)
    name = re.sub(r"^Ryzen HD Audio Controller", "Audio Integrado", name)
    return name.strip() or raw_name


import time

_cached_devices: list[AudioDevice] = []
_last_scan_time: float = 0.0
_CACHE_TTL = 3.0  # segundos


def get_available_devices(force_refresh: bool = False) -> list[AudioDevice]:
    """Obtiene la lista de dispositivos de salida a través del mezclador del sistema (PipeWire/Pulse)."""
    global _cached_devices, _last_scan_time
    now = time.time()
    if not force_refresh and _cached_devices and (now - _last_scan_time < _CACHE_TTL):
        # Actualizar textos del dispositivo por defecto según el idioma actual
        _cached_devices[0].name = i18n.t("devices.default_name")
        _cached_devices[0].description = i18n.t("devices.default_desc")
        return list(_cached_devices)

    devices: list[AudioDevice] = []

    # 1. Opción predeterminada del sistema
    devices.append(
        AudioDevice(
            id="default",
            name=i18n.t("devices.default_name"),
            description=i18n.t("devices.default_desc"),
            is_usb=False,
            is_default=True,
            icon_name="audio-card-symbolic",
        )
    )

    try:
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Audio/Sink", None)
        monitor.start()
        gst_devices = monitor.get_devices()

        for d in gst_devices:
            raw_display = d.get_display_name() or ""
            display_name = _clean_device_name(raw_display)
            props = d.get_properties()

            node_name = ""
            device_bus = ""
            is_sys_default = False

            if props:
                for i in range(props.n_fields()):
                    field_name = props.nth_field_name(i)
                    if field_name == "node.name":
                        node_name = str(props.get_value(field_name))
                    elif field_name == "device.bus":
                        device_bus = str(props.get_value(field_name))
                    elif field_name == "is-default":
                        is_sys_default = bool(props.get_value(field_name))

            if not node_name:
                continue

            # Determinar tipo de icono y si es USB
            is_usb = (device_bus == "usb") or ("usb" in node_name.lower()) or ("usb" in display_name.lower())
            if is_usb:
                icon = "audio-card-symbolic"
            elif "hdmi" in node_name.lower() or "hdmi" in display_name.lower():
                icon = "video-display-symbolic"
            elif "raop" in node_name.lower() or "network" in node_name.lower():
                icon = "network-wireless-symbolic"
            else:
                icon = "audio-speakers-symbolic"

            devices.append(
                AudioDevice(
                    id=node_name,
                    name=display_name,
                    description=raw_display,
                    is_usb=is_usb,
                    is_default=is_sys_default,
                    icon_name=icon,
                )
            )

        monitor.stop()
    except Exception as e:
        log.exception("Error al enumerar dispositivos de audio con Gst.DeviceMonitor: %s", e)

    # Ordenar: Predeterminado primero, luego USB/DACs externos, luego HDMI y altavoces de red
    def sort_key(dev: AudioDevice) -> tuple[int, str]:
        if dev.id == "default":
            return (0, "")
        if dev.is_usb:
            return (1, dev.name)
        return (2, dev.name)

    devices.sort(key=sort_key)
    _cached_devices = list(devices)
    _last_scan_time = time.time()
    log.info("Dispositivos de salida del mezclador disponibles: %d", len(devices))
    return devices


def find_device_by_id(device_id: str) -> AudioDevice | None:
    """Busca un dispositivo por su ID (node.name o 'default')."""
    if not device_id or device_id in ("default", "auto", "pipewire"):
        return get_available_devices()[0]
    for dev in get_available_devices():
        if dev.id == device_id or (device_id and device_id in dev.id):
            return dev
    return None


def get_default_device(preferred_id: str | None = None) -> AudioDevice:
    """Retorna el dispositivo configurado o la salida por defecto del sistema."""
    if preferred_id:
        found = find_device_by_id(preferred_id)
        if found:
            return found
    devices = get_available_devices()
    return devices[0]
