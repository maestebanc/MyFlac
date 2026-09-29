"""Estilos CSS y personalización visual para MyFlac (GTK4 / Libadwaita)."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..constants import APP_ID

_CSS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "css")


def _load_css(provider: Gtk.CssProvider, name: str) -> None:
    """Carga una hoja de estilos de myflac/resources/css (base.css, light.css o dark.css)."""
    provider.load_from_path(os.path.join(_CSS_DIR, name))


# Tonos de cada tema. light.css y dark.css están escritos con los colores de "slate" y "obsidian"
# (SOURCE_*); los demás tonos los sustituyen al cargar la hoja. "backdrop" no aparece en
# el CSS: es la base de la capa que oscurece o aclara la foto del artista tras la biblioteca.
LIGHT_VARIANTS: dict[str, dict[str, str]] = {
    "paper": {"window": "#e6e0d6", "view": "#efeae1", "fg": "#2b2620"},      # Papel cálido
    "slate": {"window": "#ebeef3", "view": "#f7f9fb", "fg": "#242731"},      # Pizarra suave
    "slate_mid": {"window": "#d8dce3", "view": "#e2e6ec", "fg": "#1f232b"},  # Pizarra media
    "graphite": {"window": "#d6d6d3", "view": "#e1e1de", "fg": "#1e1e1e"},   # Grafito claro
    "sage": {"window": "#dde3dc", "view": "#e7ece6", "fg": "#222822"},       # Salvia
}
DARK_VARIANTS: dict[str, dict[str, str]] = {
    "obsidian": {  # Obsidiana: carbón con un leve tinte azul
        "window": "#111215", "view": "#16181d", "card": "#191c23", "popover": "#181a20",
        "dialog": "#14161b", "bar": "#0f1013", "fg": "#f1f5f9", "backdrop": "#0c0d11",
    },
    "midnight": {  # Medianoche: azul marino profundo
        "window": "#0e1320", "view": "#121928", "card": "#172031", "popover": "#151d2d",
        "dialog": "#101726", "bar": "#0b101b", "fg": "#e6ecf5", "backdrop": "#090d17",
    },
    "espresso": {  # Espresso: negro café, cálido
        "window": "#15110d", "view": "#1b1612", "card": "#221c17", "popover": "#1f1914",
        "dialog": "#18130f", "bar": "#110e0b", "fg": "#f3ece2", "backdrop": "#0f0c09",
    },
    "oled": {  # OLED: negro puro
        "window": "#000000", "view": "#050505", "card": "#0e0e0e", "popover": "#0b0b0b",
        "dialog": "#070707", "bar": "#010101", "fg": "#ececec", "backdrop": "#020202",
    },
    "graphite": {  # Grafito: gris oscuro suave, menos contraste
        "window": "#242424", "view": "#2a2a2a", "card": "#313131", "popover": "#2e2e2e",
        "dialog": "#272727", "bar": "#1f1f1f", "fg": "#f0f0f0", "backdrop": "#1b1b1b",
    },
}
SOURCE_LIGHT_VARIANT = "slate"
SOURCE_DARK_VARIANT = "obsidian"
# Tonos que se usan si el usuario no ha elegido otro
DEFAULT_LIGHT_VARIANT = "paper"
DEFAULT_DARK_VARIANT = "obsidian"
_variants = {"light": DEFAULT_LIGHT_VARIANT, "dark": DEFAULT_DARK_VARIANT}
_palette_listeners: list = []


def variants_for(mode: str) -> dict[str, dict[str, str]]:
    return DARK_VARIANTS if mode == "dark" else LIGHT_VARIANTS


def current_variant(mode: str) -> str:
    return _variants[mode]


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def light_base_rgb() -> tuple[int, int, int]:
    """Fondo del tema claro activo, en RGB (base de la capa sobre la foto del artista)."""
    return _hex_rgb(LIGHT_VARIANTS[_variants["light"]]["window"])


def dark_base_rgb() -> tuple[int, int, int]:
    """Base oscura de la capa sobre la foto del artista para el tono oscuro activo."""
    return _hex_rgb(DARK_VARIANTS[_variants["dark"]]["backdrop"])


def add_palette_listener(callback) -> None:
    """Avisa cuando cambia el tono de alguno de los temas."""
    _palette_listeners.append(callback)


def set_theme_variant(mode: str, name: str) -> None:
    """Cambia el tono del tema claro u oscuro al instante (si ese tema está activo, se recarga)."""
    global _light_theme_provider, _dark_theme_provider
    variants = variants_for(mode)
    default = DEFAULT_DARK_VARIANT if mode == "dark" else DEFAULT_LIGHT_VARIANT
    name = name if name in variants else default
    if name == _variants[mode]:
        return
    _variants[mode] = name
    display = Gdk.Display.get_default()
    provider = _dark_theme_provider if mode == "dark" else _light_theme_provider
    if provider is not None and display is not None:
        Gtk.StyleContext.remove_provider_for_display(display, provider)
        if mode == "dark":
            _dark_theme_provider = None
        else:
            _light_theme_provider = None
        _update_theme_palette()
    for callback in list(_palette_listeners):
        try:
            callback()
        except Exception:
            pass


def set_light_variant(name: str) -> None:
    set_theme_variant("light", name)


def set_dark_variant(name: str) -> None:
    set_theme_variant("dark", name)


def theme_css(mode: str, variant: str) -> str:
    """Hoja del tema claro u oscuro con los colores del tono indicado."""
    variants = variants_for(mode)
    default = variants[SOURCE_DARK_VARIANT if mode == "dark" else SOURCE_LIGHT_VARIANT]
    with open(os.path.join(_CSS_DIR, "dark.css" if mode == "dark" else "light.css"), encoding="utf-8") as f:
        css = f.read()
    for role, new in variants[variant].items():
        if role != "backdrop":
            css = css.replace(default[role], new)
    return css


def light_css(variant: str) -> str:
    return theme_css("light", variant)


_light_theme_provider: Gtk.CssProvider | None = None
_dark_theme_provider: Gtk.CssProvider | None = None
_style_manager_connected: bool = False


def _update_theme_palette() -> None:
    """Aplica el proveedor de tema claro (Slate Soft) u oscuro (Obsidian Dark) según el modo activo."""
    global _light_theme_provider, _dark_theme_provider
    style_manager = Adw.StyleManager.get_default()
    display = Gdk.Display.get_default()
    if style_manager is None or display is None:
        return

    if style_manager.get_dark():
        if _light_theme_provider is not None:
            try:
                Gtk.StyleContext.remove_provider_for_display(display, _light_theme_provider)
            except Exception:
                pass
            _light_theme_provider = None

        if _dark_theme_provider is None:
            _dark_theme_provider = Gtk.CssProvider()
            _dark_theme_provider.load_from_string(theme_css("dark", _variants["dark"]))
            Gtk.StyleContext.add_provider_for_display(
                display, _dark_theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
    else:
        if _dark_theme_provider is not None:
            try:
                Gtk.StyleContext.remove_provider_for_display(display, _dark_theme_provider)
            except Exception:
                pass
            _dark_theme_provider = None

        if _light_theme_provider is None:
            _light_theme_provider = Gtk.CssProvider()
            _light_theme_provider.load_from_string(theme_css("light", _variants["light"]))
            Gtk.StyleContext.add_provider_for_display(
                display, _light_theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )


def load_extra_css() -> None:
    global _style_manager_connected
    provider = Gtk.CssProvider()
    _load_css(provider, "base.css")
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    style_manager = Adw.StyleManager.get_default()
    if style_manager and not _style_manager_connected:
        style_manager.connect("notify::dark", lambda *_: _update_theme_palette())
        _style_manager_connected = True
    _update_theme_palette()


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
    _update_theme_palette()


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
