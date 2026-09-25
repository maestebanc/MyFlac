"""Estilos CSS y personalización visual para MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..constants import APP_ID

EXTRA_CSS = """
/* Badges de calidad de audio */
.hires-badge {
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 0.76em;
    font-weight: 700;
    letter-spacing: 0.03em;
    background-color: alpha(#d97706, 0.22);
    color: #f59e0b;
    border: 1px solid alpha(#f59e0b, 0.35);
}

.hires-cd-badge {
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 0.76em;
    font-weight: 600;
    background-color: alpha(@window_fg_color, 0.08);
    color: alpha(@window_fg_color, 0.7);
    border: 1px solid alpha(@window_fg_color, 0.12);
}

.hires-dsd-badge {
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 0.76em;
    font-weight: 700;
    background-color: alpha(#8b5cf6, 0.22);
    color: #a78bfa;
    border: 1px solid alpha(#a78bfa, 0.35);
}

/* Ficha técnica audiófila en el inspector */
.audiophile-card {
    border-radius: 10px;
    background-color: alpha(@window_fg_color, 0.04);
    border: 1px solid alpha(@window_fg_color, 0.08);
    padding: 10px;
}

.audiophile-card-title {
    font-size: 0.74em;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    opacity: 0.65;
}

.audiophile-stat-val {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 0.88em;
}

/* Marco de carátula en alta definición */
.album-cover-frame {
    border-radius: 12px;
    border: 1px solid alpha(@window_fg_color, 0.12);
    box-shadow: 0 10px 24px alpha(black, 0.25), 0 3px 8px alpha(black, 0.12);
    background-color: alpha(@window_fg_color, 0.03);
}

.album-cover-placeholder {
    border-radius: 12px;
    border: 2px dashed alpha(@window_fg_color, 0.18);
    background-color: alpha(@window_fg_color, 0.02);
    padding: 24px;
}

/* Miniatura acotada de la barra inferior */
.mini-cover-frame {
    min-width: 48px;
    min-height: 48px;
    border-radius: 8px;
    border: 1px solid alpha(@window_fg_color, 0.12);
    box-shadow: 0 2px 8px alpha(black, 0.20);
    background-color: alpha(@window_fg_color, 0.04);
}

/* Barra inferior del reproductor con altura acotada */
.player-bar {
    min-height: 64px;
    background-color: alpha(@window_bg_color, 0.95);
    border-top: 1px solid alpha(@window_fg_color, 0.10);
    padding: 6px 16px;
}

.play-pause-btn {
    border-radius: 9999px;
    min-width: 42px;
    min-height: 42px;
    padding: 0;
}

.time-label {
    font-variant-numeric: tabular-nums;
    font-size: 0.82em;
    opacity: 0.75;
    min-width: 40px;
}

/* Tabla de canciones */
.track-table row {
    min-height: 38px;
}

.track-table columnviewcell {
    padding: 4px 8px;
}

.track-number-cell {
    font-variant-numeric: tabular-nums;
    opacity: 0.6;
}

.row-playing {
    font-weight: 600;
    color: @accent_color;
}

/* Botón selector de dispositivo en la barra */
.device-select-btn {
    font-size: 0.86em;
    padding: 4px 10px;
    border-radius: 8px;
}
"""


def load_extra_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(EXTRA_CSS)
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


_gnome_settings: Gio.Settings | None = None
_gnome_settings_connected: bool = False
_current_ui_scale_percent: int = 100


def _get_linux_system_font_scale() -> float:
    global _gnome_settings, _gnome_settings_connected
    if _gnome_settings is None:
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source and source.lookup("org.gnome.desktop.interface", True):
                _gnome_settings = Gio.Settings.new("org.gnome.desktop.interface")
        except Exception:
            _gnome_settings = None

    if _gnome_settings is not None:
        if not _gnome_settings_connected:
            try:
                _gnome_settings.connect("changed::text-scaling-factor", _on_system_text_scaling_changed)
                _gnome_settings_connected = True
            except Exception:
                pass
        try:
            factor = _gnome_settings.get_double("text-scaling-factor")
            if factor and factor > 0:
                return float(factor)
        except Exception:
            pass

    return 1.0


def _on_system_text_scaling_changed(_settings: Gio.Settings, _key: str) -> None:
    apply_ui_scale(_current_ui_scale_percent)


def apply_ui_scale(percent: int) -> None:
    global _current_ui_scale_percent
    _current_ui_scale_percent = percent
    settings = Gtk.Settings.get_default()
    if settings is None:
        return
    font_scale = _get_linux_system_font_scale()
    base_dpi = 96.0 * font_scale
    dpi_1024 = int(round(base_dpi * 1024 * (percent / 100.0)))
    settings.set_property("gtk-xft-dpi", dpi_1024)


def apply_theme(theme: str) -> None:
    style_manager = Adw.StyleManager.get_default()
    if style_manager is None:
        return
    if theme == "dark":
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    elif theme == "light":
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    else:
        style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)


def ensure_desktop_integration() -> None:
    """Instala o sincroniza el archivo .desktop y los iconos en ~/.local/share para integración con GNOME Shell / Wayland."""
    try:
        import shutil
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_icons = os.path.join(base_dir, "data", "icons", "hicolor")
        user_icons = os.path.expanduser("~/.local/share/icons/hicolor")
        user_apps = os.path.expanduser("~/.local/share/applications")

        os.makedirs(user_apps, exist_ok=True)
        os.makedirs(user_icons, exist_ok=True)

        if os.path.isdir(data_icons):
            for root, _, files in os.walk(data_icons):
                rel = os.path.relpath(root, data_icons)
                dest_dir = os.path.join(user_icons, rel)
                os.makedirs(dest_dir, exist_ok=True)
                for f in files:
                    src_f = os.path.join(root, f)
                    dest_f = os.path.join(dest_dir, f)
                    if not os.path.exists(dest_f) or os.path.getmtime(src_f) > os.path.getmtime(dest_f):
                        shutil.copy2(src_f, dest_f)

        desktop_src = os.path.join(base_dir, "data", f"{APP_ID}.desktop")
        desktop_dest = os.path.join(user_apps, f"{APP_ID}.desktop")
        if os.path.isfile(desktop_src):
            run_script = os.path.join(base_dir, "run.sh")
            with open(desktop_src, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace("Exec=myflac", f"Exec={run_script} %F")
            with open(desktop_dest, "w", encoding="utf-8") as f:
                f.write(content)
    except Exception:
        pass


def register_icon_theme() -> None:
    ensure_desktop_integration()
    display = Gdk.Display.get_default()
    if not display:
        return
    icon_theme = Gtk.IconTheme.get_for_display(display)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_icons = os.path.join(base_dir, "data", "icons")
    internal_icons = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icons")
    user_icons = os.path.expanduser("~/.local/share/icons")
    for d in (data_icons, internal_icons, user_icons):
        if os.path.isdir(d):
            icon_theme.add_search_path(d)
