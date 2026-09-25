"""Diálogo de preferencias de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..audio.devices import AudioDevice, get_available_devices
from ..config import save_config
from .. import i18n
from .style import apply_theme, apply_ui_scale

LANG_CODES = ["es", "en", "ca"]
LANG_LABELS = ["Español", "English", "Català"]


class PreferencesDialog(Adw.PreferencesWindow):
    def __init__(self, cfg: dict, on_config_changed: Callable[[dict], None] | None = None, parent=None):
        super().__init__()
        self.cfg = cfg
        self.on_config_changed = on_config_changed

        self.set_title(i18n.t("prefs.title"))
        self.set_default_size(560, 480)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self._available_devices = get_available_devices()
        self._build_ui()

        # Listener para actualizar el diálogo si cambia el idioma
        i18n.add_language_listener(self._on_language_changed)

    def _build_ui(self):
        self.page = Adw.PreferencesPage()
        self.page.set_title(i18n.t("prefs.general"))
        self.page.set_icon_name("preferences-system-symbolic")

        # ---------------------------------------------
        # Grupo: Idioma de la interfaz
        # ---------------------------------------------
        self.group_lang = Adw.PreferencesGroup(
            title=i18n.t("prefs.language"),
            description=i18n.t("prefs.language_desc")
        )

        self.lang_row = Adw.ComboRow()
        self.lang_row.set_title(i18n.t("prefs.language"))
        lang_model = Gtk.StringList.new(LANG_LABELS)
        self.lang_row.set_model(lang_model)

        curr_lang = i18n.get_language()
        if curr_lang in LANG_CODES:
            self.lang_row.set_selected(LANG_CODES.index(curr_lang))
        else:
            self.lang_row.set_selected(0)

        self.lang_row.connect("notify::selected", self._on_lang_changed)
        self.group_lang.add(self.lang_row)
        self.page.add(self.group_lang)

        # ---------------------------------------------
        # Grupo: Dispositivo de Salida de Audio
        # ---------------------------------------------
        self.group_audio = Adw.PreferencesGroup(
            title=i18n.t("prefs.audio_group"),
            description=i18n.t("devices.group_desc")
        )

        self.device_row = Adw.ComboRow()
        self.device_row.set_title(i18n.t("prefs.audio_device"))

        device_names = [d.name for d in self._available_devices]
        dev_model = Gtk.StringList.new(device_names)
        self.device_row.set_model(dev_model)

        curr_dev_id = self.cfg.get("audio_device_id", "default")
        selected_idx = 0
        for idx, dev in enumerate(self._available_devices):
            if dev.id == curr_dev_id or (curr_dev_id in dev.id and curr_dev_id != "default"):
                selected_idx = idx
                break
        self.device_row.set_selected(selected_idx)
        self.device_row.connect("notify::selected", self._on_device_changed)
        self.group_audio.add(self.device_row)
        self.page.add(self.group_audio)

        # ---------------------------------------------
        # Grupo: Apariencia e Interfaz
        # ---------------------------------------------
        self.group_ui = Adw.PreferencesGroup(title=i18n.t("prefs.ui_group"))

        # Tema visual
        self.theme_row = Adw.ComboRow()
        self.theme_row.set_title(i18n.t("prefs.theme"))
        self._update_theme_model()

        curr_theme = self.cfg.get("theme", "system")
        if curr_theme == "light":
            self.theme_row.set_selected(1)
        elif curr_theme == "dark":
            self.theme_row.set_selected(2)
        else:
            self.theme_row.set_selected(0)

        self.theme_row.connect("notify::selected", self._on_theme_changed)
        self.group_ui.add(self.theme_row)

        # Escala de interfaz (UI scale)
        self.scale_row = Adw.SpinRow.new_with_range(75, 150, 5)
        self.scale_row.set_title(i18n.t("prefs.scale"))
        self.scale_row.set_subtitle(i18n.t("prefs.scale_desc"))
        self.scale_row.set_value(float(self.cfg.get("ui_scale", 100)))
        self.scale_row.connect("notify::value", self._on_ui_scale_changed)
        self.group_ui.add(self.scale_row)

        self.page.add(self.group_ui)
        self.add(self.page)

    def _update_theme_model(self):
        theme_names = [
            i18n.t("prefs.theme_system"),
            i18n.t("prefs.theme_light"),
            i18n.t("prefs.theme_dark"),
        ]
        self.theme_row.set_model(Gtk.StringList.new(theme_names))

    def _on_language_changed(self, _lang: str):
        """Actualiza las etiquetas dinámicamente si el idioma cambia."""
        self.set_title(i18n.t("prefs.title"))
        self.page.set_title(i18n.t("prefs.general"))
        self.group_lang.set_title(i18n.t("prefs.language"))
        self.group_lang.set_description(i18n.t("prefs.language_desc"))
        self.lang_row.set_title(i18n.t("prefs.language"))

        self.group_audio.set_title(i18n.t("prefs.audio_group"))
        self.group_audio.set_description(i18n.t("devices.group_desc"))
        self.device_row.set_title(i18n.t("prefs.audio_device"))

        self.group_ui.set_title(i18n.t("prefs.ui_group"))
        self.theme_row.set_title(i18n.t("prefs.theme"))
        self.scale_row.set_title(i18n.t("prefs.scale"))
        self.scale_row.set_subtitle(i18n.t("prefs.scale_desc"))

        # Actualizar opciones de tema preservando la selección
        sel = self.theme_row.get_selected()
        self._update_theme_model()
        self.theme_row.set_selected(sel)

    def _on_lang_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        if 0 <= idx < len(LANG_CODES):
            lang_code = LANG_CODES[idx]
            self.cfg["language"] = lang_code
            save_config(self.cfg)
            i18n.set_language(lang_code)
            if self.on_config_changed:
                self.on_config_changed(self.cfg)

    def _on_device_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        if 0 <= idx < len(self._available_devices):
            dev = self._available_devices[idx]
            self.cfg["audio_device_id"] = dev.id
            save_config(self.cfg)
            if self.on_config_changed:
                self.on_config_changed(self.cfg)

    def _on_theme_changed(self, row: Adw.ComboRow, _param):
        idx = row.get_selected()
        theme = "system" if idx == 0 else ("light" if idx == 1 else "dark")
        self.cfg["theme"] = theme
        apply_theme(theme)
        save_config(self.cfg)
        if self.on_config_changed:
            self.on_config_changed(self.cfg)

    def _on_ui_scale_changed(self, row: Adw.SpinRow, _param):
        val = int(row.get_value())
        self.cfg["ui_scale"] = val
        apply_ui_scale(val)
        save_config(self.cfg)
        if self.on_config_changed:
            self.on_config_changed(self.cfg)
