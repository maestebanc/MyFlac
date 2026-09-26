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

/* Marco de carátula en alta definición e interactivo para alternar modos */
.album-cover-frame {
    border-radius: 12px;
    border: 1px solid alpha(@window_fg_color, 0.12);
    box-shadow: 0 10px 24px alpha(black, 0.25), 0 3px 8px alpha(black, 0.12);
    background-color: alpha(@window_fg_color, 0.03);
    transition: box-shadow 200ms ease;
}

.album-cover-frame:hover {
    box-shadow: 0 14px 32px alpha(black, 0.35), 0 4px 12px alpha(black, 0.20);
}

/* Indicador de modo del visualizador en la carátula */
.visualizer-pill {
    background-color: alpha(black, 0.55);
    border-radius: 9999px;
    padding: 3px 8px;
    margin-bottom: 8px;
    box-shadow: 0 2px 6px alpha(black, 0.40);
    border: 1px solid alpha(white, 0.15);
}

.visualizer-dot {
    min-width: 6px;
    min-height: 6px;
    border-radius: 9999px;
    background-color: alpha(white, 0.35);
    margin: 2px 2px;
}

.visualizer-dot.active {
    min-width: 16px;
    background-color: #3584e4;
    box-shadow: 0 0 6px alpha(#3584e4, 0.6);
}

.album-cover-placeholder {
    border-radius: 12px;
    border: 2px dashed alpha(@window_fg_color, 0.18);
    background-color: alpha(@window_fg_color, 0.02);
    padding: 24px;
}

/* Miniatura de la barra inferior: adaptada al alto del minireproductor */
.mini-cover-frame {
    border-radius: 8px;
    border: 1px solid alpha(@window_fg_color, 0.12);
    box-shadow: 0 2px 8px alpha(black, 0.20);
    background-color: alpha(@window_fg_color, 0.04);
}

/* Barra inferior del reproductor: relleno ceñido para apurar toda la altura */
.player-bar {
    min-height: 64px;
    background-color: alpha(@window_bg_color, 0.95);
    border-top: 1px solid alpha(@window_fg_color, 0.10);
    padding: 4px 16px 4px 6px;
}

/* Barra de progreso de escaneo: delgada línea azul (#3584e4) no obstructiva */
.scan-progress-line {
    min-height: 2px;
    padding: 0;
    margin: 0;
    border: none;
    background-color: transparent;
}

.scan-progress-line > trough {
    min-height: 2px;
    border: none;
    border-radius: 0;
    background-color: alpha(@window_fg_color, 0.04);
}

.scan-progress-line > trough > progress {
    min-height: 2px;
    border: none;
    border-radius: 0;
    background-color: #3584e4;
    box-shadow: 0 0 4px alpha(#3584e4, 0.4);
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
.track-table {
    background-color: transparent;
}

.track-table header button {
    padding: 5px 8px;
    font-weight: 700;
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: alpha(@window_fg_color, 0.65);
    background-color: alpha(@window_fg_color, 0.035);
    border-bottom: 1px solid alpha(@window_fg_color, 0.08);
    box-shadow: none;
}

.track-table row {
    min-height: 28px;
    border-bottom: 1px solid alpha(@window_fg_color, 0.025);
}

.track-table row:nth-child(even) {
    background-color: alpha(@window_fg_color, 0.012);
}

.track-table row:hover {
    background-color: alpha(@window_fg_color, 0.045);
}

.track-table row:selected {
    background-color: alpha(#f59e0b, 0.16);
}

.track-table columnviewcell {
    padding: 2px 8px;
    font-size: 0.92em;
}

.track-number-cell {
    font-variant-numeric: tabular-nums;
    opacity: 0.6;
    font-size: 0.88em;
}

.row-playing-num {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    color: #f59e0b;
    opacity: 1.0;
}

.row-playing {
    font-weight: 700;
    color: #f59e0b;
}

/* Selector de dispositivo de audio enriquecido (Píldora audiófila) */
.audiophile-device-pill {
    border-radius: 10px;
    background-color: alpha(@window_fg_color, 0.05);
    border: 1px solid alpha(@window_fg_color, 0.12);
    padding: 3px 10px 3px 6px;
    transition: all 150ms ease;
}

.audiophile-device-pill:hover {
    background-color: alpha(@window_fg_color, 0.09);
    border-color: alpha(#f59e0b, 0.40);
    box-shadow: 0 2px 8px alpha(black, 0.20);
}

.device-icon-bubble {
    border-radius: 9999px;
    background-color: alpha(#f59e0b, 0.14);
    padding: 5px;
}

.device-icon-bubble image {
    color: #f59e0b;
}

.device-name-label {
    font-weight: 600;
    font-size: 0.84em;
}

.device-sub-label {
    font-size: 0.70em;
    opacity: 0.70;
    letter-spacing: 0.04em;
}

.device-led-active {
    color: #2ec27e;
    font-size: 0.75em;
}

/* Navegador Multicolumnas estilo iTunes */
.column-browser-pane {
    background-color: alpha(@window_bg_color, 0.4);
    border-bottom: 1px solid alpha(@window_fg_color, 0.10);
}

.column-header-box {
    padding: 5px 12px;
    background-color: alpha(@window_fg_color, 0.04);
    border-bottom: 1px solid alpha(@window_fg_color, 0.09);
}

.column-header-title {
    font-weight: 700;
    font-size: 0.78em;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: alpha(@window_fg_color, 0.75);
}

.column-header-count {
    font-size: 0.76em;
    color: #f59e0b;
    opacity: 0.85;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.column-list {
    background-color: transparent;
}

.column-list row {
    padding: 3px 10px;
    min-height: 26px;
    border-bottom: 1px solid alpha(@window_fg_color, 0.025);
    transition: background-color 100ms ease;
    font-size: 0.92em;
}

.column-list row:nth-child(even) {
    background-color: alpha(@window_fg_color, 0.012);
}

.column-list row:hover {
    background-color: alpha(@window_fg_color, 0.045);
}

.column-list row:selected {
    background-color: alpha(#f59e0b, 0.18);
    color: #f59e0b;
    font-weight: 600;
}

.column-list row:selected label {
    color: #f59e0b;
}

.count-badge {
    font-size: 0.74em;
    font-variant-numeric: tabular-nums;
    color: alpha(@window_fg_color, 0.5);
    padding: 0px 6px;
    border-radius: 8px;
    background-color: alpha(@window_fg_color, 0.05);
    border: 1px solid alpha(@window_fg_color, 0.06);
    min-height: 18px;
}

.column-list row:selected .count-badge {
    background-color: alpha(#f59e0b, 0.25);
    color: #f59e0b;
    border-color: alpha(#f59e0b, 0.35);
}

/* Divisores de paneles (Paned separators) */
paned > separator {
    background-color: alpha(@window_fg_color, 0.10);
    min-width: 1px;
    min-height: 1px;
    transition: background-color 150ms ease;
}

paned > separator:hover {
    background-color: alpha(#f59e0b, 0.5);
}

/* Panel inspector con borde izquierdo divisorio */
.inspector-panel {
    border-left: 1px solid alpha(@window_fg_color, 0.10);
    background-color: alpha(@window_fg_color, 0.012);
}

/* Menú contextual de pista */
.context-menu-box {
    min-width: 220px;
}

.context-menu-item {
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 0.88em;
}

.context-menu-item:hover {
    background-color: alpha(@window_fg_color, 0.08);
}

/* Botón y Popover de Cola de reproducción (A continuación) */
.queue-btn {
    border-radius: 9999px;
    padding: 6px;
}

.queue-btn.accent {
    color: #3584e4;
    background-color: alpha(#3584e4, 0.15);
}

.queue-popover-box {
    min-width: 320px;
}

.queue-row {
    padding: 6px 8px;
    border-radius: 6px;
    transition: background-color 150ms ease;
}

.queue-row:hover {
    background-color: alpha(@window_fg_color, 0.06);
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
