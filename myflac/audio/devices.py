"""Detección y gestión de dispositivos de audio ALSA y PipeWire para MyFlac."""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
import ctypes


@dataclass
class AudioDevice:
    id: str  # 'hw:2,0', 'hw:CARD=Audio,DEV=0', o 'pipewire'
    name: str  # Nombre amigable ej. 'iFi (by AMR) HD USB Audio'
    card_index: int | None = None
    device_index: int | None = None
    subname: str = ""
    is_exclusive: bool = True
    is_usb_dac: bool = False
    supported_rates: list[int] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)

    @property
    def max_rate_khz(self) -> str:
        if self.supported_rates:
            max_r = max(self.supported_rates)
            return f"{max_r / 1000:g} kHz"
        return "Desconocido"

    @property
    def display_rates(self) -> str:
        if not self.supported_rates:
            return ""
        rates_khz = [f"{r/1000:g}" for r in sorted(self.supported_rates)]
        return f"{', '.join(rates_khz)} kHz"


def _read_alsa_cards() -> dict[int, dict[str, str]]:
    """Lee `/proc/asound/cards` para obtener nombres reales y descripción de tarjetas."""
    cards: dict[int, dict[str, str]] = {}
    cards_path = "/proc/asound/cards"
    if not os.path.exists(cards_path):
        return cards

    try:
        with open(cards_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Cada tarjeta ocupa 2 o 3 líneas separadas por bloque
        # Ej:
        #  2 [Audio          ]: USB-Audio - iFi (by AMR) HD USB Audio
        #                       iFi (by AMR) iFi (by AMR) HD USB Audio at usb-...
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r"^\s*(\d+)\s+\[([^\]]+)\]:\s*(.+)$", line)
            if m:
                card_idx = int(m.group(1))
                short_id = m.group(2).strip()
                rest = m.group(3).strip()
                # rest suele ser "USB-Audio - iFi (by AMR) HD USB Audio"
                if " - " in rest:
                    driver, name = rest.split(" - ", 1)
                else:
                    driver, name = rest, rest
                desc = ""
                if i + 1 < len(lines) and lines[i + 1].startswith(" "):
                    desc = lines[i + 1].strip()
                cards[card_idx] = {
                    "short": short_id,
                    "driver": driver.strip(),
                    "name": name.strip(),
                    "desc": desc,
                }
            i += 1
    except Exception:
        pass

    return cards


def _read_usb_stream_caps(card_idx: int, dev_idx: int = 0) -> tuple[list[int], list[str]]:
    """Extrae las frecuencias y formatos soportados desde `/proc/asound/cardX/streamY`."""
    stream_candidates = [
        f"/proc/asound/card{card_idx}/stream{dev_idx}",
        f"/proc/asound/card{card_idx}/stream0",
    ]
    rates_set: set[int] = set()
    formats_set: set[str] = set()

    for stream_path in stream_candidates:
        if not os.path.exists(stream_path):
            continue
        try:
            with open(stream_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for r_match in re.finditer(r"Rates:\s*([0-9, ]+)", content):
                for r_str in r_match.group(1).split(","):
                    r_str = r_str.strip()
                    if r_str.isdigit():
                        rates_set.add(int(r_str))
            for f_match in re.finditer(r"Format:\s*([A-Za-z0-9_]+)", content):
                formats_set.add(f_match.group(1).strip())
        except Exception:
            pass

    return sorted(rates_set), sorted(formats_set)


def get_available_devices() -> list[AudioDevice]:
    """Obtiene la lista completa de dispositivos de salida de audio."""
    devices: list[AudioDevice] = []

    # 1. Opción de audio compartida de sistema (PipeWire / Auto)
    devices.append(
        AudioDevice(
            id="pipewire",
            name="PipeWire / Sistema (Compartido)",
            card_index=None,
            device_index=None,
            subname="Salida compartida predeterminada del escritorio",
            is_exclusive=False,
            is_usb_dac=False,
            supported_rates=[],
            supported_formats=[],
        )
    )

    cards = _read_alsa_cards()

    # 2. Leer dispositivos PCM de reproducción en `/proc/asound/pcm`
    pcm_path = "/proc/asound/pcm"
    if os.path.exists(pcm_path):
        try:
            with open(pcm_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    # Ej: "02-00: USB Audio : USB Audio : playback 1 : capture 1"
                    parts = [p.strip() for p in line.split(":")]
                    if len(parts) >= 4 and "playback" in parts[3]:
                        card_dev = parts[0]
                        c_idx, d_idx = [int(x) for x in card_dev.split("-")]
                        card_info = cards.get(c_idx, {})
                        card_name = card_info.get("name") or card_info.get("short") or f"Card {c_idx}"
                        sub_name = parts[1]

                        # Filtrar cámaras web o dispositivos que solo son micrófonos con monitor
                        if "webcam" in card_name.lower() or "cam" in card_info.get("short", "").lower():
                            continue

                        is_usb = "usb" in card_info.get("driver", "").lower() or "usb" in card_name.lower()
                        rates, formats = _read_usb_stream_caps(c_idx, d_idx)

                        # Si no tenemos rates (ej. tarjeta interna Intel/AMD), inferir rangos típicos
                        if not rates:
                            rates = [44100, 48000, 96000, 192000]

                        # Formato amigable para el identificador
                        short_id = card_info.get("short")
                        hw_id = f"hw:CARD={short_id},DEV={d_idx}" if short_id else f"hw:{c_idx},{d_idx}"

                        devices.append(
                            AudioDevice(
                                id=hw_id,
                                name=card_name,
                                card_index=c_idx,
                                device_index=d_idx,
                                subname=sub_name,
                                is_exclusive=True,
                                is_usb_dac=is_usb,
                                supported_rates=rates,
                                supported_formats=formats,
                            )
                        )
        except Exception:
            pass

    # Ordenar: primero DACs USB audiófilos externos, luego el resto, dejando PipeWire disponible
    def sort_key(d: AudioDevice) -> tuple[int, int]:
        if d.is_usb_dac:
            return (0, -(max(d.supported_rates) if d.supported_rates else 0))
        if d.is_exclusive:
            return (1, 0)
        return (2, 0)

    devices.sort(key=sort_key)
    return devices


def find_device_by_id(device_id: str) -> AudioDevice | None:
    """Busca un dispositivo por su identificador (ej. 'hw:CARD=Audio,DEV=0' o 'hw:2,0')."""
    devices = get_available_devices()
    for dev in devices:
        if dev.id == device_id:
            return dev
    # Búsqueda flexible (por ej. si guardó 'hw:2,0' y ahora es 'hw:CARD=Audio,DEV=0')
    if device_id.startswith("hw:"):
        for dev in devices:
            if dev.card_index is not None and f"hw:{dev.card_index}" in device_id:
                return dev
    return None


def get_default_device(preferred_id: str | None = None) -> AudioDevice:
    """Retorna el dispositivo preferido o el mejor DAC Hi-Res disponible."""
    devices = get_available_devices()
    if not devices:
        return AudioDevice(
            id="pipewire",
            name="Audio predeterminado",
            is_exclusive=False,
        )

    if preferred_id and preferred_id != "auto":
        found = find_device_by_id(preferred_id)
        if found:
            return found

    # Buscar el primer DAC USB de alta resolución
    for dev in devices:
        if dev.is_usb_dac:
            return dev

    # Devolver el primer dispositivo exclusivo
    for dev in devices:
        if dev.is_exclusive:
            return dev

    return devices[0]
