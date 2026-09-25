"""Punto de entrada de la aplicación MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import config
from .constants import APP_ID, APP_NAME
from .logger import get_log_path, get_logger, setup_logging
from .ui.about_dialog import build_about_dialog
from .ui.main_window import MainWindow
from .ui.preferences_dialog import PreferencesDialog
from .ui.style import apply_theme, apply_ui_scale, load_extra_css, register_icon_theme

log = get_logger("app")


class MyFlacApplication(Adw.Application):
    def __init__(self):
        if not GLib.get_prgname():
            GLib.set_prgname(APP_ID)
        if not GLib.get_application_name():
            GLib.set_application_name(APP_NAME)
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

        log_action = Gio.SimpleAction.new("open_log", None)
        log_action.connect("activate", lambda *_: self._open_log_file())
        self.add_action(log_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", lambda *_: self._open_about())
        self.add_action(about_action)

    def _on_activate(self, _app: Adw.Application) -> None:
        log.info("Evento activate de Adw.Application recibido")
        if self.window is None:
            register_icon_theme()
            Gtk.Window.set_default_icon_name(APP_ID)
            load_extra_css()
            cfg = config.load_config()
            log.info("Configuración cargada: %s", {k: v for k, v in cfg.items() if k != "last_directory"})
            apply_ui_scale(cfg.get("ui_scale", 100))
            apply_theme(cfg.get("theme", "system"))

            self.window = MainWindow(self, cfg)
            log.info("Ventana principal MainWindow instanciada exitosamente")

        self.window.present()

    def _open_preferences(self):
        if not self.window:
            return
        log.info("Abriendo diálogo de preferencias")
        dlg = PreferencesDialog(
            cfg=self.window.cfg,
            on_config_changed=self._on_preferences_changed,
            parent=self.window
        )
        dlg.present()

    def _on_preferences_changed(self, cfg: dict):
        if self.window:
            log.info(
                "Preferencias modificadas: audio_device_id=%s, language=%s, theme=%s",
                cfg.get("audio_device_id"),
                cfg.get("language"),
                cfg.get("theme")
            )
            target_device = cfg.get("audio_device_id", "default")
            self.window.engine.set_device(target_device)
            self.window._update_output_status()

    def _open_log_file(self):
        log_path = get_log_path()
        log.info("Solicitada apertura del archivo de registro: %s", log_path)
        if os.path.exists(log_path):
            launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(log_path))
            launcher.launch(self.window, None, None)

    def _open_about(self):
        if not self.window:
            return
        log.info("Abriendo diálogo Acerca de MyFlac")
        dlg = build_about_dialog()
        dlg.present(self.window)


def main():
    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_NAME)
    setup_logging(debug=True)
    log.info("Iniciando bucle de aplicación GTK4...")
    app = MyFlacApplication()
    ret = app.run(sys.argv)
    log.info("Aplicación finalizada con código de retorno: %s", ret)
    return ret


if __name__ == "__main__":
    sys.exit(main())
