"""Diálogo de preferencias de MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..audio.devices import find_device_by_id, get_default_device
from ..config import save_config
from .style import apply_theme, apply_ui_scale


class PreferencesDialog(Adw.PreferencesWindow):
    def __init__(self, cfg: dict, on_config_changed: Callable[[dict], None] | None = None, parent=None):
        super().__init__()
        self.set_title("Preferencias")
        self.set_default_size(560, 480)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self.cfg = cfg
        self.on_config_changed = on_config_changed

        self._build_ui()

    def _build_ui(self):
        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("preferences-system-symbolic")

        # ---------------------------------------------
        # Grupo: Motor de Audio Bit-Perfect
        # ---------------------------------------------
        group_audio = Adw.PreferencesGroup(
            title="Motor de Audio Hi-Res",
            description="Configuración de transporte bit-exacto por hardware ALSA"
        )

        # Modo exclusivo switch
        self.switch_bp = Adw.SwitchRow()
        self.switch_bp.set_title("Modo Exclusivo Bit-Perfect")
        self.switch_bp.set_subtitle("Bypassa el mezclador del sistema y fija el reloj nativo en el DAC")
        self.switch_bp.set_active(self.cfg.get("bitperfect_mode", True))
        self.switch_bp.connect("notify::active", self._on_bp_toggled)
        group_audio.add(self.switch_bp)

        # Bypass de volumen switch
        self.switch_vol = Adw.SwitchRow()
        self.switch_vol.set_title("Bypass de Volumen Digital (0 dB)")
        self.switch_vol.set_subtitle("Mantiene la ganancia digital unitaria para evitar pérdidas de bits")
        self.switch_vol.set_active(self.cfg.get("volume_bypass", True))
        self.switch_vol.connect("notify::active", self._on_vol_bypass_toggled)
        group_audio.add(self.switch_vol)

        page.add(group_audio)

        # ---------------------------------------------
        # Grupo: Apariencia e Interfaz
        # ---------------------------------------------
        group_ui = Adw.PreferencesGroup(title="Apariencia de la Interfaz")

        # Tema visual
        self.theme_row = Adw.ComboRow()
        self.theme_row.set_title("Tema")
        theme_model = Gtk.StringList.new(["Sistema", "Claro", "Oscuro"])
        self.theme_row.set_model(theme_model)

        curr_theme = self.cfg.get("theme", "system")
        if curr_theme == "light":
            self.theme_row.set_selected(1)
        elif curr_theme == "dark":
            self.theme_row.set_selected(2)
        else:
            self.theme_row.set_selected(0)

        self.theme_row.connect("notify::selected", self._on_theme_changed)
        group_ui.add(self.theme_row)

        # Escala de interfaz (UI scale)
        self.scale_row = Adw.SpinRow.new_with_range(75, 150, 5)
        self.scale_row.set_title("Escala de la Interfaz (%)")
        self.scale_row.set_subtitle("Ajusta el tamaño visual de textos e iconos")
        self.scale_row.set_value(float(self.cfg.get("ui_scale", 100)))
        self.scale_row.connect("notify::value", self._on_ui_scale_changed)
        group_ui.add(self.scale_row)

        page.add(group_ui)
        self.add(page)

    def _on_bp_toggled(self, row: Adw.SwitchRow, _param):
        val = row.get_active()
        self.cfg["bitperfect_mode"] = val
        save_config(self.cfg)
        if self.on_config_changed:
            self.on_config_changed(self.cfg)

    def _on_vol_bypass_toggled(self, row: Adw.SwitchRow, _param):
        val = row.get_active()
        self.cfg["volume_bypass"] = val
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
