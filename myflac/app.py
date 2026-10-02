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
from .ui.shortcuts import register_app_shortcuts
from .ui.tray import TrayIcon
from .ui.preferences_dialog import PreferencesDialog
from .ui.style import apply_theme, apply_ui_scale, load_extra_css, register_icon_theme, set_dark_variant, set_light_variant

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
        quit_action.connect("activate", lambda *_: self._quit())
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

    quitting = False

    def can_run_in_background(self) -> bool:
        """Si hay icono en la barra superior y está activada la opción, cerrar la ventana no detiene la música."""
        cfg = getattr(self.window, "cfg", {}) if self.window else {}
        if not cfg.get("close_to_tray", True):
            return False
        tray = getattr(self, "tray", None)
        return bool(tray and tray.visible_in_panel)

    def _quit(self):
        """Cerrar la ventana principal hace el cierre ordenado (guardar configuración, liberar el DAC)."""
        if not self.window:
            self.quit()
            return
        self.quitting = True
        # Con un diálogo abierto (p. ej. los atajos), Libadwaita cerraría solo el diálogo
        dialog = self.window.get_visible_dialog()
        if dialog:
            dialog.force_close()
        self.window.close()

    def _on_activate(self, _app: Adw.Application) -> None:
        log.info("Evento activate de Adw.Application recibido")
        if self.window is None:
            register_icon_theme()
            Gtk.Window.set_default_icon_name(APP_ID)
            load_extra_css()
            cfg = config.load_config()
            log.info("Configuración cargada: %s", {k: v for k, v in cfg.items() if k != "last_directory"})
            apply_ui_scale(cfg.get("ui_scale", 100))
            set_light_variant(cfg.get("light_variant", "paper"))
            set_dark_variant(cfg.get("dark_variant", "obsidian"))
            apply_theme(cfg.get("theme", "system"))

            self.window = MainWindow(self, cfg)
            register_app_shortcuts(self, self.window.shortcut_handlers())
            self.window.present()

            # Icono en la barra superior: bandeja estándar (extensión AppIndicator en GNOME, KDE, XFCE...)
            self.tray = TrayIcon(self)
            GLib.idle_add(self.tray.start)
            log.info("Ventana principal MainWindow instanciada exitosamente")
        else:
            self.window.present()

    def _open_preferences(self):
        if not self.window:
            return
        log.info("Abriendo diálogo de preferencias")
        cfg = self.window.cfg
        self._last_prefs = {k: cfg.get(k) for k in
                            ("audio_device_id", "language", "oscilloscope_enabled", "backdrop_enabled", "backdrop_intensity")}
        dlg = PreferencesDialog(
            cfg=self.window.cfg,
            db=self.window.db,
            scanner=self.window.scanner,
            on_config_changed=self._on_preferences_changed,
            on_library_updated=self.window.on_library_updated,
            parent=self.window
        )
        dlg.present()

    def _on_preferences_changed(self, cfg: dict):
        """Aplica solo lo que ha cambiado: el diálogo avisa en cada paso de un deslizador."""
        if not self.window:
            return
        keys = ("audio_device_id", "language", "oscilloscope_enabled", "backdrop_enabled", "backdrop_intensity")
        current = {k: cfg.get(k) for k in keys}
        previous = getattr(self, "_last_prefs", {})
        changed = {k for k in keys if current[k] != previous.get(k)}
        self._last_prefs = current
        if not changed:
            return

        if changed - {"backdrop_intensity"}:
            log.info("Preferencias modificadas: %s", ", ".join(f"{k}={current[k]}" for k in sorted(changed)))

        if "audio_device_id" in changed:
            target_device = current["audio_device_id"] or "default"
            if target_device != self.window.engine.device_id:
                self.window._on_device_selected(target_device)
        if changed & {"audio_device_id", "language"}:
            self.window._update_output_status()

        if changed & {"backdrop_enabled", "backdrop_intensity"}:
            self.window.apply_backdrop_settings()

        if "oscilloscope_enabled" in changed:
            oscilloscope_enabled = current["oscilloscope_enabled"] if current["oscilloscope_enabled"] is not None else True
            self.window.engine.set_levels_enabled(oscilloscope_enabled)
            if self.window.inspector:
                self.window.inspector.set_oscilloscope_enabled(oscilloscope_enabled)
            if hasattr(self.window, "player_bar") and self.window.player_bar:
                is_scope = oscilloscope_enabled and (self.window.inspector.visualizer_mode == 0 if self.window.inspector else True)
                self.window.player_bar.set_bar_oscilloscope_enabled(is_scope)
            if self.window.mini_player:
                self.window.mini_player.set_oscilloscope_enabled(oscilloscope_enabled)

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
    from . import watchdog
    watchdog.install()
    log.info("Iniciando bucle de aplicación GTK4...")
    app = MyFlacApplication()
    ret = app.run(sys.argv)
    log.info("Aplicación finalizada con código de retorno: %s", ret)
    return ret


if __name__ == "__main__":
    sys.exit(main())
