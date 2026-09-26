"""Atajos de teclado de MyFlac: registro, manejo y ventana de ayuda (una sola fuente de verdad)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from ..logger import get_logger
from .. import i18n

if TYPE_CHECKING:
    from ..app import MyFlacApplication
    from .main_window import MainWindow

log = get_logger("ui.shortcuts")

SEEK_STEP_SECONDS = 10.0
VOLUME_STEP = 0.05

# Atajos registrados como acciones de la aplicación: funcionan en cualquier ventana de MyFlac
# (principal, mini y super). (acción, aceleradores, texto de ayuda)
APP_SHORTCUTS: list[tuple[str, list[str], str]] = [
    ("view-main", ["<Control>1"], "shortcuts.view_main"),
    ("view-mini", ["<Control>2"], "shortcuts.view_mini"),
    ("view-super", ["<Control>3"], "shortcuts.view_super"),
    ("toggle-cover-mode", ["<Control>i"], "shortcuts.cover_mode"),
    ("show-cover", ["<Control>p"], "shortcuts.show_cover"),
    ("shuffle", ["<Control>s"], "shortcuts.shuffle"),
    ("repeat", ["<Control>t"], "shortcuts.repeat"),
    ("mute", ["<Control>m"], "shortcuts.mute"),
    ("exclusive", ["<Control>e"], "shortcuts.exclusive"),
    ("preferences", ["<Control>comma"], "shortcuts.preferences"),
    ("shortcuts", ["<Control>question", "F1"], "shortcuts.help"),
    ("quit", ["<Control>q"], "shortcuts.quit"),
]

# Secciones de la ventana de ayuda: (título, [(acelerador mostrado, texto)])
HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("shortcuts.section_playback", [
        ("space", "shortcuts.play_pause"),
        ("<Control>Right", "shortcuts.next"),
        ("<Control>Left", "shortcuts.previous"),
        ("<Shift>Right", "shortcuts.seek_forward"),
        ("<Shift>Left", "shortcuts.seek_backward"),
        ("<Control>Up", "shortcuts.volume_up"),
        ("<Control>Down", "shortcuts.volume_down"),
        ("<Control>m", "shortcuts.mute"),
        ("<Control>s", "shortcuts.shuffle"),
        ("<Control>t", "shortcuts.repeat"),
        ("<Control>e", "shortcuts.exclusive"),
    ]),
    ("shortcuts.section_views", [
        ("<Control>1", "shortcuts.view_main"),
        ("<Control>2", "shortcuts.view_mini"),
        ("<Control>3 F11", "shortcuts.view_super"),
        ("Escape", "shortcuts.back"),
        ("<Control>i", "shortcuts.cover_mode"),
        ("<Control>p", "shortcuts.show_cover"),
    ]),
    ("shortcuts.section_general", [
        ("<Control>f", "shortcuts.search"),
        ("<Control>r", "shortcuts.rescan"),
        ("<Control>comma", "shortcuts.preferences"),
        ("<Control>question F1", "shortcuts.help"),
        ("<Control>q", "shortcuts.quit"),
    ]),
]


def register_app_shortcuts(app: MyFlacApplication, handlers: dict[str, Callable[[], None]]):
    """Crea las acciones app.* (salvo las que ya existan) y les asigna sus aceleradores."""
    for name, accels, _title in APP_SHORTCUTS:
        if app.lookup_action(name) is None:
            handler = handlers.get(name)
            if handler is None:
                log.warning("Atajo sin manejador: %s", name)
                continue
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, h=handler: h())
            app.add_action(action)
        app.set_accels_for_action(f"app.{name}", accels)


def build_shortcuts_dialog() -> Adw.ShortcutsDialog:
    """Ventana de ayuda con todos los atajos, en el idioma actual."""
    dialog = Adw.ShortcutsDialog()
    for section_key, items in HELP_SECTIONS:
        section = Adw.ShortcutsSection.new(i18n.t(section_key))
        for accel, title_key in items:
            section.add(Adw.ShortcutsItem.new(i18n.t(title_key), accel))
        dialog.add(section)
    return dialog


def _focus_is_editable(window: Gtk.Window) -> bool:
    focus = window.get_focus()
    return isinstance(focus, Gtk.Editable)


def handle_playback_key(main_window: MainWindow, key_window: Gtk.Window, keyval: int, state) -> bool:
    """
    Atajos de reproducción con flechas y Espacio. No se registran como aceleradores globales para no
    robar a los campos de texto sus teclas de edición (Ctrl+← mueve por palabras, Shift+→ selecciona).
    """
    if _focus_is_editable(key_window):
        return False
    ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
    shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
    alt = bool(state & Gdk.ModifierType.ALT_MASK)
    if alt:
        return False

    if keyval == Gdk.KEY_space and not ctrl and not shift:
        main_window._toggle_play_pause()
    elif keyval == Gdk.KEY_Right and ctrl and not shift:
        main_window._play_next()
    elif keyval == Gdk.KEY_Left and ctrl and not shift:
        main_window._play_previous()
    elif keyval == Gdk.KEY_Right and shift and not ctrl:
        main_window.seek_relative(SEEK_STEP_SECONDS)
    elif keyval == Gdk.KEY_Left and shift and not ctrl:
        main_window.seek_relative(-SEEK_STEP_SECONDS)
    elif keyval == Gdk.KEY_Up and ctrl and not shift:
        main_window.change_volume(VOLUME_STEP)
    elif keyval == Gdk.KEY_Down and ctrl and not shift:
        main_window.change_volume(-VOLUME_STEP)
    else:
        return False
    return True
