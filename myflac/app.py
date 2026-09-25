"""Punto de entrada de la aplicación MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from . import config
from .constants import APP_ID
from .ui.about_dialog import build_about_dialog
from .ui.main_window import MainWindow
from .ui.preferences_dialog import PreferencesDialog
from .ui.style import apply_theme, apply_ui_scale, load_extra_css, register_icon_theme


class MyFlacApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        # Desactivar propiedad heredada de GTK3 para evitar avisos por consola en entornos Omarchy/GNOME
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", False)
        self.window: MainWindow | None = None
        self.connect("activate", self._on_activate)

        self._setup_actions()

    def _setup_actions(self):
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", lambda *_: self._open_preferences())
        self.add_action(prefs_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_: self._open_about())
        self.add_action(about_action)

    def _on_activate(self, _app: Adw.Application) -> None:
        if self.window is None:
            register_icon_theme()
            Gtk.Window.set_default_icon_name("audio-player-symbolic")
            load_extra_css()
            cfg = config.load_config()
            apply_ui_scale(cfg.get("ui_scale", 100))
            apply_theme(cfg.get("theme", "system"))

            self.window = MainWindow(self, cfg)

        self.window.present()

    def _open_preferences(self):
        if not self.window:
            return
        dlg = PreferencesDialog(
            cfg=self.window.cfg,
            on_config_changed=self._on_preferences_changed,
            parent=self.window
        )
        dlg.present()

    def _on_preferences_changed(self, cfg: dict):
        if self.window:
            self.window.engine.set_bitperfect_mode(cfg.get("bitperfect_mode", True))
            self.window.engine.set_volume_bypass(cfg.get("volume_bypass", True))

    def _open_about(self):
        if not self.window:
            return
        dlg = build_about_dialog()
        dlg.present(self.window)


def main():
    app = MyFlacApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
