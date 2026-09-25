"""Selector visual de dispositivos de audio ALSA y PipeWire para MyFlac."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from ..audio.devices import AudioDevice, get_available_devices


class DeviceSelectionDialog(Adw.Window):
    def __init__(self, current_device_id: str, on_device_selected: Callable[[AudioDevice], None], parent=None):
        super().__init__()
        self.set_title("Dispositivos de Salida de Audio")
        self.set_default_size(520, 420)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self.current_device_id = current_device_id
        self.on_device_selected = on_device_selected

        self._build_ui()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Adw.PreferencesPage()
        group_usb = Adw.PreferencesGroup(
            title="DACs USB de Alta Resolución (Modo Exclusivo Bit-Perfect)",
            description="Acceso directo por hardware ALSA bypassando el mezclador del sistema"
        )
        group_other = Adw.PreferencesGroup(
            title="Otras Salidas de Audio",
            description="Tarjetas internas, HDMI o salida compartida PipeWire"
        )

        devices = get_available_devices()
        has_usb = False

        for dev in devices:
            row = Adw.ActionRow()
            row.set_title(dev.name)

            # Subtítulo con especificaciones técnicas
            subtitle_parts = []
            if dev.is_exclusive:
                subtitle_parts.append(f"ALSA {dev.id}")
            if dev.supported_rates:
                subtitle_parts.append(f"Hasta {dev.max_rate_khz}")
            if dev.supported_formats:
                fmts = ", ".join(f for f in dev.supported_formats if "DSD" in f or "S" in f)[:35]
                subtitle_parts.append(fmts)
            
            row.set_subtitle(" · ".join(subtitle_parts) if subtitle_parts else dev.subname)

            # Icono
            if dev.is_usb_dac:
                icon_name = "audio-card-symbolic"
            elif dev.id == "pipewire":
                icon_name = "audio-volume-high-symbolic"
            else:
                icon_name = "audio-speakers-symbolic"
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))

            # Indicador de selección activa
            is_active = (dev.id == self.current_device_id) or (
                self.current_device_id.startswith("hw:") and dev.card_index is not None and f"hw:{dev.card_index}" in self.current_device_id
            )

            if is_active:
                check_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
                check_icon.add_css_class("accent")
                row.add_suffix(check_icon)

            # Botón activar
            btn = Gtk.Button(label="Seleccionar")
            btn.set_valign(Gtk.Align.CENTER)
            btn.add_css_class("flat")
            if is_active:
                btn.set_sensitive(False)
                btn.set_label("Activo")

            def make_handler(target_dev: AudioDevice):
                return lambda *_: self._select(target_dev)

            btn.connect("clicked", make_handler(dev))
            row.set_activatable_widget(btn)
            row.add_suffix(btn)

            if dev.is_usb_dac:
                group_usb.add(row)
                has_usb = True
            else:
                group_other.add(row)

        if has_usb:
            page.add(group_usb)
        page.add(group_other)

        scrolled.set_child(page)
        toolbar_view.set_content(scrolled)
        self.set_content(toolbar_view)

    def _select(self, dev: AudioDevice):
        self.on_device_selected(dev)
        self.close()
