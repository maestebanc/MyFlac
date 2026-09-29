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
    alsa_card: int | None = None  # Índice de tarjeta ALSA (para reservarla frente a PipeWire)
    alsa_card_id: str = ""  # Identificador estable de la tarjeta (ej. 'Audio')
    alsa_device: int | None = None
    max_sample_rate: int | None = None
    dsd_native: bool = False  # La tarjeta acepta DSD nativo en ALSA (DSD_U32_BE...), sin DoP

    @property
    def hw_path(self) -> str | None:
        """Ruta ALSA directa (hw) para el modo exclusivo, o None si no es una salida ALSA."""
        if not self.alsa_card_id or self.alsa_device is None:
            return None
        return f"hw:CARD={self.alsa_card_id},DEV={self.alsa_device}"


_card_rate_cache: dict[tuple[int, str], tuple[int | None, bool]] = {}


def parse_stream_dsd_native(text: str) -> bool:
    """True si la sección Playback de stream0 ofrece algún formato DSD nativo de ALSA."""
    in_playback = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.endswith(":") and " " not in stripped:
            in_playback = stripped == "Playback:"
        elif in_playback and stripped.startswith("Format:") and "DSD_" in stripped:
            return True
    return False


def parse_stream_max_rate(text: str) -> int | None:
    """Frecuencia máxima de la sección Playback de un /proc/asound/cardN/stream0 (tarjetas USB)."""
    max_rate: int | None = None
    in_playback = False
    for line in text.splitlines():
        stripped = line.strip()
        # Las secciones ("Playback:", "Capture:") son las únicas líneas que terminan en ':'
        if stripped.endswith(":") and " " not in stripped:
            in_playback = stripped == "Playback:"
            continue
        if in_playback and stripped.startswith("Rates:"):
            rates = [int(r) for r in re.findall(r"\d+", stripped)]
            if rates:
                max_rate = max(max_rate or 0, max(rates))
    return max_rate


def read_card_max_rate(card: int | None, card_id: str = "") -> int | None:
    """
    Frecuencia máxima de reproducción de una tarjeta USB según /proc/asound/cardN/stream0.
    No abre el dispositivo (abrirlo mientras PipeWire lo tiene daría "busy" y bloquearía la UI).
    Las tarjetas no USB no publican este fichero: se devuelve None.
    """
    if card is None:
        return None
    return _read_stream_info(card, card_id)[0]


def read_card_dsd_native(card: int | None, card_id: str = "") -> bool:
    """True si la tarjeta USB admite DSD nativo según /proc/asound/cardN/stream0."""
    if card is None:
        return False
    return _read_stream_info(card, card_id)[1]


def _read_stream_info(card: int, card_id: str) -> tuple[int | None, bool]:
    key = (card, card_id)
    if key not in _card_rate_cache:
        try:
            with open(f"/proc/asound/card{card}/stream0", encoding="utf-8") as f:
                text = f.read()
            _card_rate_cache[key] = (parse_stream_max_rate(text), parse_stream_dsd_native(text))
        except OSError:
            _card_rate_cache[key] = (None, False)
    return _card_rate_cache[key]


def _clean_device_name(raw_name: str) -> str:
    """Limpia nombres técnicos para mostrarlos de forma elegante en la interfaz."""
    name = raw_name.strip()
    # Eliminar sufijos redundantes de perfil como "Estéreo analógico", "Estéreo digital (HDMI)", etc.
    name = re.sub(r"\s+Est[eé]reo\s+(anal[oó]gico|digital.*)$", "", name, flags=re.IGNORECASE)
    # Acortar prefijos técnicos largos
    name = re.sub(r"^Radeon High Definition Audio Controller", "HDMI", name)
    name = re.sub(r"^Ryzen HD Audio Controller", "Audio Integrado", name)
    return name.strip() or raw_name


def _parse_alsa_fields(fields: dict[str, str]) -> dict:
    """Convierte las propiedades alsa.* de PipeWire en los campos ALSA de AudioDevice."""
    try:
        return {
            "alsa_card": int(fields["alsa.card"]),
            "alsa_card_id": fields["alsa.id"],
            "alsa_device": int(fields["alsa.device"]),
        }
    except (KeyError, ValueError):
        return {}


import time

_cached_devices: list[AudioDevice] = []
_last_scan_time: float = 0.0
_last_logged_count = -1
_CACHE_TTL = 3.0  # segundos

# Monitor único y siempre activo. Crear y detener un Gst.DeviceMonitor en cada consulta hacía
# que el hilo del proveedor de PipeWire procesara eventos de nodos (p. ej. al recuperar la tarjeta
# tras el modo exclusivo) mientras monitor.stop() liberaba su núcleo: SIGSEGV en libgstpipewire.
_monitor: Gst.DeviceMonitor | None = None


def _get_monitor() -> Gst.DeviceMonitor | None:
    global _monitor
    if _monitor is None:
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Audio/Sink", None)
        if not monitor.start():
            log.warning("No se pudo iniciar Gst.DeviceMonitor para salidas de audio")
            return None
        _monitor = monitor
    return _monitor


def get_available_devices(force_refresh: bool = False) -> list[AudioDevice]:
    """Obtiene la lista de dispositivos de salida a través del mezclador del sistema (PipeWire/Pulse)."""
    global _cached_devices, _last_scan_time, _last_logged_count
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
        monitor = _get_monitor()
        gst_devices = monitor.get_devices() if monitor else []

        for d in gst_devices:
            raw_display = d.get_display_name() or ""
            display_name = _clean_device_name(raw_display)
            props = d.get_properties()

            node_name = ""
            device_bus = ""
            is_sys_default = False
            alsa_fields: dict[str, str] = {}

            if props:
                for i in range(props.n_fields()):
                    field_name = props.nth_field_name(i)
                    if field_name == "node.name":
                        node_name = str(props.get_value(field_name))
                    elif field_name == "device.bus":
                        device_bus = str(props.get_value(field_name))
                    elif field_name == "is-default":
                        is_sys_default = bool(props.get_value(field_name))
                    elif field_name in ("alsa.card", "alsa.id", "alsa.device"):
                        alsa_fields[field_name] = str(props.get_value(field_name))

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

            dev = AudioDevice(
                id=node_name,
                name=display_name,
                description=raw_display,
                is_usb=is_usb,
                is_default=is_sys_default,
                icon_name=icon,
                **_parse_alsa_fields(alsa_fields),
            )
            dev.max_sample_rate = read_card_max_rate(dev.alsa_card, dev.alsa_card_id)
            dev.dsd_native = read_card_dsd_native(dev.alsa_card, dev.alsa_card_id)
            devices.append(dev)
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
    if len(devices) != _last_logged_count:
        _last_logged_count = len(devices)
        log.info("Dispositivos de salida del mezclador disponibles: %d", len(devices))
    return devices


def base_node_name(node_name: str) -> str:
    """Quita el sufijo '.N' que WirePlumber añade al recrear un nodo ALSA (p.ej. tras el modo exclusivo)."""
    if node_name.startswith("alsa_"):
        return re.sub(r"\.\d+$", "", node_name)
    return node_name


def make_default_device() -> AudioDevice:
    """Crea el objeto AudioDevice estándar para la salida por defecto del sistema."""
    return AudioDevice(
        id="default",
        name=i18n.t("devices.default_name"),
        description=i18n.t("devices.default_desc"),
        is_usb=False,
        is_default=True,
        icon_name="audio-card-symbolic",
    )


def find_device_by_id(device_id: str) -> AudioDevice | None:
    """Busca un dispositivo por su ID (node.name o 'default')."""
    if not device_id or device_id in ("default", "auto", "pipewire"):
        if _cached_devices:
            return _cached_devices[0]
        return make_default_device()
    base_id = base_node_name(device_id)
    for dev in get_available_devices():
        if dev.id == device_id or base_node_name(dev.id) == base_id or device_id in dev.id:
            return dev
    return None


def resolve_hardware_device(device_id: str) -> AudioDevice | None:
    """Devuelve el dispositivo ALSA real tras un id, o None si no es una salida hardware ALSA concreta."""
    if not device_id or device_id in ("default", "auto", "pipewire"):
        return None
    for force_refresh in (False, True):
        devices = get_available_devices(force_refresh=force_refresh)
        base_id = base_node_name(device_id)
        dev = next((d for d in devices if base_node_name(d.id) == base_id or device_id in d.id), None)
        if dev and dev.hw_path:
            return dev
    return None


def find_published_device(device_id: str) -> AudioDevice | None:
    """Devuelve la salida si PipeWire la está publicando ahora mismo (sin esperar)."""
    base_id = base_node_name(device_id)
    for dev in get_available_devices(force_refresh=True):
        if dev.id != "default" and base_node_name(dev.id) == base_id:
            return dev
    return None


def get_default_device(preferred_id: str | None = None) -> AudioDevice:
    """Retorna el dispositivo configurado o la salida por defecto del sistema."""
    if preferred_id and preferred_id not in ("default", "auto", "pipewire"):
        found = find_device_by_id(preferred_id)
        if found:
            return found
    if _cached_devices:
        return _cached_devices[0]
    return make_default_device()
