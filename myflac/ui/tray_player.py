"""Ventanita de reproducción que abre el icono de la barra superior (portada, progreso, controles, salir)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from ..audio.engine import PlaybackState
from ..logger import get_logger
from .. import i18n

if TYPE_CHECKING:
    from ..app import MyFlacApplication

log = get_logger("ui.tray_player")

COVER_SIZE = 300


def _fmt(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class TrayPlayerWindow(Adw.Window):
    """Se cierra sola al perder el foco (como un menú) o con Escape."""

    def __init__(self, app: MyFlacApplication):
        super().__init__()
        self.app = app
        self.engine = app.window.engine
        self._seeking = False
        self._was_active = False

        self.set_application(app)
        self.set_title("MyFlac")
        self.set_resizable(False)
        self.set_default_size(COVER_SIZE + 40, -1)
        self.set_hide_on_close(True)
        self.add_css_class("tray-player")
        self._build_ui()

        self.engine.add_track_listener(self._on_track)
        self.engine.add_state_listener(self._on_state)
        self.engine.add_position_listener(self._on_position)
        self.connect("notify::is-active", self._on_active_changed)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # ------------------------------------------------------------------ interfaz
    def _build_ui(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.add_css_class("flat")
        toolbar.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("start", "end"):
            getattr(box, f"set_margin_{side}")(20)
        box.set_margin_bottom(18)

        self.cover = Gtk.Picture()
        self.cover.set_content_fit(Gtk.ContentFit.COVER)
        self.cover.set_size_request(COVER_SIZE, COVER_SIZE)
        self.cover.set_can_shrink(True)
        self.cover.set_overflow(Gtk.Overflow.HIDDEN)
        self.cover.add_css_class("tray-player-cover")
        box.append(self.cover)

        self.title = Gtk.Label(xalign=0.5)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.add_css_class("title-4")
        box.append(self.title)
        self.subtitle = Gtk.Label(xalign=0.5)
        self.subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        self.subtitle.add_css_class("dim-label")
        box.append(self.subtitle)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self._on_seek)
        box.append(self.scale)
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.elapsed = Gtk.Label(xalign=0.0)
        self.elapsed.add_css_class("caption")
        self.elapsed.add_css_class("dim-label")
        self.elapsed.set_hexpand(True)
        self.remaining = Gtk.Label(xalign=1.0)
        self.remaining.add_css_class("caption")
        self.remaining.add_css_class("dim-label")
        times.append(self.elapsed)
        times.append(self.remaining)
        box.append(times)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        controls.set_halign(Gtk.Align.CENTER)
        prev_btn = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        prev_btn.add_css_class("circular")
        prev_btn.add_css_class("flat")
        prev_btn.set_tooltip_text(i18n.t("tray.previous"))
        prev_btn.connect("clicked", lambda *_: self.app.window._play_previous())
        self.play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.play_btn.add_css_class("circular")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.add_css_class("tray-player-play")
        self.play_btn.connect("clicked", lambda *_: self.app.window._toggle_play_pause())
        next_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        next_btn.add_css_class("circular")
        next_btn.add_css_class("flat")
        next_btn.set_tooltip_text(i18n.t("tray.next"))
        next_btn.connect("clicked", lambda *_: self.app.window._play_next())
        for button in (prev_btn, self.play_btn, next_btn):
            controls.append(button)
        box.append(controls)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_homogeneous(True)
        actions.set_margin_top(4)
        show_btn = Gtk.Button(label=i18n.t("tray.show"))
        show_btn.connect("clicked", lambda *_: self._show_main())
        quit_btn = Gtk.Button(label=i18n.t("tray.quit"))
        quit_btn.add_css_class("destructive-action")
        quit_btn.connect("clicked", lambda *_: self.app.activate_action("quit"))
        actions.append(show_btn)
        actions.append(quit_btn)
        box.append(actions)

        toolbar.set_content(box)
        self.set_content(toolbar)
        self._on_track(self.engine.current_track)
        self._on_state(self.engine.state)

    # ------------------------------------------------------------------ comportamiento
    def toggle(self):
        if self.get_visible():
            self.set_visible(False)
            return
        self._was_active = False
        self._on_track(self.engine.current_track)
        self._on_position(self.engine.position, self.engine.get_duration())
        self.present()

    def shutdown(self):
        self.engine.remove_track_listener(self._on_track)
        self.engine.remove_state_listener(self._on_state)
        self.engine.remove_position_listener(self._on_position)
        self.destroy()

    def _show_main(self):
        self.set_visible(False)
        self.app.window.show_main_view()

    def _on_active_changed(self, *_args):
        # Como un menú: se oculta al pasar a otra ventana (una vez que llegó a estar activa)
        if self.is_active():
            self._was_active = True
        elif self._was_active and self.get_visible():
            self.set_visible(False)

    def _on_key(self, _ctrl, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        if keyval == Gdk.KEY_space:
            self.app.window._toggle_play_pause()
            return True
        return False

    def _on_track(self, track):
        if track is None:
            self.title.set_text(i18n.t("inspector.no_playback"))
            self.subtitle.set_text("")
            self.cover.set_paintable(None)
            return
        self.title.set_text(track.title)
        self.subtitle.set_text(" — ".join(x for x in (track.artist, track.album) if x))
        cover = track.get_cover_image_bytes()
        try:
            self.cover.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(cover[0])) if cover else None)
        except GLib.Error:
            self.cover.set_paintable(None)
        duration = track.duration or 0.0
        self.scale.set_range(0, max(1.0, duration))

    def _on_state(self, state):
        playing = state == PlaybackState.PLAYING
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
        self.play_btn.set_tooltip_text(i18n.t("tray.pause") if playing else i18n.t("tray.play"))

    def _on_position(self, position: float, duration: float):
        if self._seeking or not self.get_visible():
            return
        self.scale.set_value(position)
        self.elapsed.set_text(_fmt(position))
        self.remaining.set_text(f"-{_fmt(max(0.0, duration - position))}" if duration else "")

    def _on_seek(self, _scale, _scroll, value: float) -> bool:
        self._seeking = True
        self.engine.seek(value)
        self.elapsed.set_text(_fmt(value))
        GLib.timeout_add(300, self._end_seek)
        return False

    def _end_seek(self) -> bool:
        self._seeking = False
        return False
