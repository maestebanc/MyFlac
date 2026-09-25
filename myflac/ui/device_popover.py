"""Selector visual de dispositivos de salida de audio para MyFlac."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..audio.devices import AudioDevice, get_available_devices
from .. import i18n


class DeviceSelectionDialog(Adw.Window):
    def __init__(self, current_device_id: str, on_device_selected: Callable[[AudioDevice], None], parent=None):
        super().__init__()
        self.set_title(i18n.t("devices.title"))
        self.set_default_size(520, 440)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self.current_device_id = current_device_id or "default"
        self.on_device_selected = on_device_selected

        self._build_ui()

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Adw.PreferencesPage()

        devices = get_available_devices()
        usb_devices = [d for d in devices if d.is_usb]
        other_devices = [d for d in devices if not d.is_usb]

        if usb_devices:
            group_usb = Adw.PreferencesGroup(
                title=i18n.t("devices.group_usb"),
                description=i18n.t("devices.group_desc"),
            )
            for dev in usb_devices:
                group_usb.add(self._create_device_row(dev))
            page.add(group_usb)

        group_other = Adw.PreferencesGroup(
            title=i18n.t("devices.group_other") if usb_devices else i18n.t("devices.group_title"),
            description=i18n.t("devices.group_desc"),
        )
        for dev in other_devices:
            group_other.add(self._create_device_row(dev))
        page.add(group_other)

        scrolled.set_child(page)
        toolbar_view.set_content(scrolled)
        self.set_content(toolbar_view)

    def _create_device_row(self, dev: AudioDevice) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_title(dev.name)

        if dev.description and dev.description != dev.name:
            row.set_subtitle(dev.description)

        row.add_prefix(Gtk.Image.new_from_icon_name(dev.icon_name))

        is_active = (dev.id == self.current_device_id) or (
            self.current_device_id in ("default", "") and dev.id == "default"
        ) or (self.current_device_id in dev.id and dev.id != "default")

        if is_active:
            check_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check_icon.add_css_class("accent")
            row.add_suffix(check_icon)

        btn = Gtk.Button(label=i18n.t("devices.active_btn") if is_active else i18n.t("devices.select_btn"))
        btn.set_valign(Gtk.Align.CENTER)
        btn.add_css_class("flat")
        if is_active:
            btn.set_sensitive(False)

        def make_handler(target_dev: AudioDevice):
            return lambda *_: self._select(target_dev)

        btn.connect("clicked", make_handler(dev))
        row.set_activatable_widget(btn)
        row.add_suffix(btn)

        return row

    def _select(self, dev: AudioDevice):
        self.on_device_selected(dev)
        self.close()
