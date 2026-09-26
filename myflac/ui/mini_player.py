"""Ventana de Mini-Reproductor flotante centrada en carátula 500x500 con controles integrados."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack
from ..logger import get_logger
from .. import i18n

if TYPE_CHECKING:
    from .main_window import MainWindow

log = get_logger("ui.mini_player")


class MiniPlayerWindow(Gtk.Window):
    """
    Ventana compacta independiente de 500x500 px.
    Muestra la carátula en alta definición a pantalla completa de la ventana
    con controles audiófilos esenciales en un panel translúcido inferior y un botón
    de retorno a la ventana principal.
    """

    def __init__(self, main_window: MainWindow, engine: AudioEngine):
        super().__init__()
        self.main_window = main_window
        self.engine = engine

        self.set_title("MyFlac - Mini Reproductor")
        self.set_default_size(500, 500)
        self.set_resizable(False)
        self.add_css_class("mini-player-window")

        # Vincular aplicación
        app = main_window.get_application()
        if app:
            self.set_application(app)

        self._is_seeking = False
        self._current_duration = 0.0
        self._pos_timer_id: int | None = None

        self._build_ui()
        self._connect_engine()
        self._setup_key_controller()

        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        root_overlay = Gtk.Overlay()
        root_overlay.set_size_request(500, 500)

        # 1. Base: Carátula en alta resolución 500x500
        self.cover_stack = Gtk.Stack()
        self.cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.cover_stack.set_size_request(500, 500)

        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_size_request(500, 500)
        self.cover_stack.add_named(self.cover_picture, "picture")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        ph_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        ph_icon.set_pixel_size(96)
        ph_icon.set_opacity(0.35)
        placeholder.append(ph_icon)
        self.cover_stack.add_named(placeholder, "placeholder")
        self.cover_stack.set_visible_child_name("placeholder")

        root_overlay.set_child(self.cover_stack)

        # 2. Capa Superior: Botón de retorno a la ventana principal
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_bar.set_valign(Gtk.Align.START)
        top_bar.set_halign(Gtk.Align.FILL)
        top_bar.set_margin_top(12)
        top_bar.set_margin_start(12)
        top_bar.set_margin_end(12)

        self.btn_back = Gtk.Button()
        self.btn_back.set_icon_name("view-restore-symbolic")
        self.btn_back.add_css_class("mini-player-btn")
        self.btn_back.add_css_class("flat")
        self.btn_back.set_tooltip_text("Volver a la ventana principal (Escape)")
        self.btn_back.connect("clicked", lambda *_: self.restore_main_window())
        top_bar.append(self.btn_back)

        title_spacer = Gtk.Box()
        title_spacer.set_hexpand(True)
        top_bar.append(title_spacer)

        root_overlay.add_overlay(top_bar)

        # 3. Capa Inferior: Tarjeta de controles translúcida estilo Glassmorphism
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom_box.add_css_class("mini-player-overlay-card")
        bottom_box.set_valign(Gtk.Align.END)
        bottom_box.set_halign(Gtk.Align.FILL)
        bottom_box.set_margin_start(12)
        bottom_box.set_margin_end(12)
        bottom_box.set_margin_bottom(12)

        # Metadatos de la pista
        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.title_label = Gtk.Label(label=i18n.t("inspector.no_playback"), xalign=0.0)
        self.title_label.add_css_class("mini-player-title")
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(32)

        self.sub_label = Gtk.Label(label="", xalign=0.0)
        self.sub_label.add_css_class("mini-player-sub")
        self.sub_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub_label.set_max_width_chars(36)

        meta_box.append(self.title_label)
        meta_box.append(self.sub_label)
        bottom_box.append(meta_box)

        # Barra de progreso de tiempo
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("caption")
        self.pos_label.add_css_class("dim-label")

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.add_css_class("mini-player-scale")
        self.scale.connect("change-value", self._on_scale_change_value)

        self.dur_label = Gtk.Label(label="0:00")
        self.dur_label.add_css_class("caption")
        self.dur_label.add_css_class("dim-label")

        time_box.append(self.pos_label)
        time_box.append(self.scale)
        time_box.append(self.dur_label)
        bottom_box.append(time_box)

        # Controles de transporte
        ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        ctrl_box.set_halign(Gtk.Align.CENTER)
        ctrl_box.set_valign(Gtk.Align.CENTER)

        self.btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.btn_prev.add_css_class("flat")
        self.btn_prev.add_css_class("circular")
        self.btn_prev.connect("clicked", lambda *_: self.main_window._play_previous())

        self.btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.btn_play.add_css_class("suggested-action")
        self.btn_play.add_css_class("circular")
        self.btn_play.add_css_class("play-pause-btn")
        self.btn_play.connect("clicked", lambda *_: self.main_window._toggle_play_pause())

        self.btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.btn_next.add_css_class("flat")
        self.btn_next.add_css_class("circular")
        self.btn_next.connect("clicked", lambda *_: self.main_window._play_next())

        ctrl_box.append(self.btn_prev)
        ctrl_box.append(self.btn_play)
        ctrl_box.append(self.btn_next)
        bottom_box.append(ctrl_box)

        root_overlay.add_overlay(bottom_box)
        self.set_child(root_overlay)

    def _setup_key_controller(self):
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.restore_main_window()
            return True
        elif keyval == Gdk.KEY_space:
            self.main_window._toggle_play_pause()
            return True
        return False

    def _connect_engine(self):
        self.engine.add_state_listener(self._on_playback_state_changed)
        self.engine.add_track_listener(self._on_track_changed)
        if self.engine.current_track:
            self.set_track(self.engine.current_track)
        self._update_play_button(self.engine.state)

    def set_track(self, track: AudioTrack | None):
        if not track:
            self.title_label.set_text(i18n.t("inspector.no_playback"))
            self.sub_label.set_text("")
            self.cover_stack.set_visible_child_name("placeholder")
            return

        self.title_label.set_text(track.title or os.path.basename(track.filepath))
        sub_text = track.artist or ""
        if track.album:
            sub_text += f" · {track.album}"
        self.sub_label.set_text(sub_text)

        self._current_duration = track.duration or 0.0
        self.dur_label.set_text(self._format_sec(self._current_duration))
        self.scale.set_range(0.0, max(1.0, self._current_duration))

        # Cargar carátula HD
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            data, mime = cover_info
            gbytes = GLib.Bytes.new(data)
            texture = Gdk.Texture.new_from_bytes(gbytes)
            self.cover_picture.set_paintable(texture)
            self.cover_stack.set_visible_child_name("picture")
        else:
            self.cover_stack.set_visible_child_name("placeholder")

    def _on_track_changed(self, track: AudioTrack):
        GLib.idle_add(self.set_track, track)

    def _on_playback_state_changed(self, state: PlaybackState):
        GLib.idle_add(self._update_play_button, state)

    def _update_play_button(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        icon = "media-playback-pause-symbolic" if is_playing else "media-playback-start-symbolic"
        self.btn_play.set_icon_name(icon)

        if is_playing:
            self._ensure_pos_timer()
        else:
            self._stop_pos_timer()

    def _ensure_pos_timer(self):
        if self._pos_timer_id is None:
            self._pos_timer_id = GLib.timeout_add(250, self._update_position)

    def _stop_pos_timer(self):
        if self._pos_timer_id is not None:
            GLib.source_remove(self._pos_timer_id)
            self._pos_timer_id = None

    def _update_position(self) -> bool:
        if not self.get_visible():
            return False
        if not self._is_seeking and self._current_duration > 0.0:
            pos = self.engine.position
            self.scale.set_value(pos)
            self.pos_label.set_text(self._format_sec(pos))
        return True

    def _on_scale_change_value(self, _scale, _scroll_type, value: float) -> bool:
        self.engine.seek(value)
        self.pos_label.set_text(self._format_sec(value))
        return False

    def _format_sec(self, sec: float) -> str:
        s = int(sec)
        m = s // 60
        r = s % 60
        return f"{m}:{r:02d}"

    def restore_main_window(self):
        """Cierra el mini-reproductor y vuelve a mostrar la ventana principal."""
        log.info("Restaurando ventana principal desde Mini-Reproductor")
        self._stop_pos_timer()
        self.hide()
        self.main_window.set_visible(True)
        self.main_window.present()

    def _on_close_request(self, _window) -> bool:
        self.restore_main_window()
        return True
