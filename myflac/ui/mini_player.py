"""Ventana de Mini-Reproductor flotante centrada en carátula 500x500 con controles integrados estilo Apple Music y osciloscopio."""
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
from .visualizers import OscilloscopeWidget

if TYPE_CHECKING:
    from .main_window import MainWindow

log = get_logger("ui.mini_player")


class MiniPlayerWindow(Adw.Window):
    """
    Ventana compacta independiente de 500x500 px inspirada en Apple Music.
    Muestra la carátula en alta definición con osciloscopio superpuesto por defecto.
    Un clic conmuta entre osciloscopio y carátula limpia.
    Los controles se centran elegantemente y se auto-ocultan cuando el cursor no está encima.
    La ventana es arrastrable por el escritorio mediante WindowHandle.
    """

    def __init__(self, main_window: MainWindow, engine: AudioEngine):
        super().__init__()
        self.main_window = main_window
        self.engine = engine

        self.set_title("MyFlac - Mini Reproductor")
        self.set_default_size(500, 500)
        self.set_resizable(True)
        self.add_css_class("mini-player-window")

        # Vincular aplicación
        app = main_window.get_application()
        if app:
            self.set_application(app)

        self._is_seeking = False
        self._current_duration = 0.0
        self._current_position = 0.0
        self._oscilloscope_mode = 0  # 0: Portada + Osciloscopio (por defecto), 1: Portada limpia
        self._hud_timeout_id: int | None = None
        self._mouse_inside = False

        self._press_x = 0.0
        self._press_y = 0.0

        self.connect("notify::fullscreened", self._on_fullscreen_changed)

        self._build_ui()
        self._connect_engine()
        self._setup_controllers()

        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        root_overlay = Gtk.Overlay()
        root_overlay.set_size_request(500, 500)
        root_overlay.set_hexpand(True)
        root_overlay.set_vexpand(True)

        # ---------------------------------------------------------------------
        # 1. Base: Carátula en alta resolución 500x500
        # ---------------------------------------------------------------------
        self.cover_stack = Gtk.Stack()
        self.cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.cover_stack.set_hexpand(True)
        self.cover_stack.set_vexpand(True)

        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_hexpand(True)
        self.cover_picture.set_vexpand(True)
        self.cover_stack.add_named(self.cover_picture, "picture")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_hexpand(True)
        placeholder.set_vexpand(True)
        ph_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        ph_icon.set_pixel_size(96)
        ph_icon.set_opacity(0.35)
        placeholder.append(ph_icon)
        self.cover_stack.add_named(placeholder, "placeholder")
        self.cover_stack.set_visible_child_name("placeholder")

        root_overlay.set_child(self.cover_stack)

        # ---------------------------------------------------------------------
        # 2. Capa de Osciloscopio Superpuesto (Modo 0 activo por defecto, sólo si reproduce)
        # ---------------------------------------------------------------------
        self.scope = OscilloscopeWidget()
        self.scope.set_hexpand(True)
        self.scope.set_vexpand(True)
        self.scope.set_active(True)
        self.scope.set_visible(False)
        root_overlay.add_overlay(self.scope)

        # ---------------------------------------------------------------------
        # 3. Capa HUD Apple Music centrada con auto-ocultación (Hover)
        # ---------------------------------------------------------------------
        self.hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.hud_box.add_css_class("mini-player-hud")
        self.hud_box.set_hexpand(True)
        self.hud_box.set_vexpand(True)

        # 3.1 Barra Superior Flotante: Pantalla Completa y Cerrar/Restaurar
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_bar.set_valign(Gtk.Align.START)
        top_bar.set_halign(Gtk.Align.FILL)
        top_bar.set_margin_top(12)
        top_bar.set_margin_start(14)
        top_bar.set_margin_end(14)

        top_spacer = Gtk.Box()
        top_spacer.set_hexpand(True)
        top_bar.append(top_spacer)

        self.btn_fullscreen = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic")
        self.btn_fullscreen.add_css_class("mini-player-btn-circle")
        self.btn_fullscreen.add_css_class("flat")
        self.btn_fullscreen.set_tooltip_text(i18n.t("header.fullscreen"))
        self.btn_fullscreen.connect("clicked", lambda *_: self.toggle_fullscreen())
        top_bar.append(self.btn_fullscreen)

        self.btn_close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        self.btn_close.add_css_class("mini-player-btn-circle")
        self.btn_close.add_css_class("flat")
        self.btn_close.set_tooltip_text("Volver a la ventana principal (Escape)")
        self.btn_close.connect("clicked", lambda *_: self.restore_main_window())
        top_bar.append(self.btn_close)

        self.hud_box.append(top_bar)

        # Espaciador central para empujar los controles hacia la mitad-inferior centrada
        mid_spacer = Gtk.Box()
        mid_spacer.set_vexpand(True)
        self.hud_box.append(mid_spacer)

        # 3.2 Contenedor de Controles Centrados estilo Apple Music
        controls_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        controls_card.set_halign(Gtk.Align.CENTER)
        controls_card.set_valign(Gtk.Align.END)
        controls_card.set_size_request(440, -1)
        controls_card.set_margin_start(16)
        controls_card.set_margin_end(16)
        controls_card.set_margin_bottom(24)

        # Título centrado prominente
        self.title_label = Gtk.Label(label=i18n.t("inspector.no_playback"))
        self.title_label.add_css_class("mini-player-title")
        self.title_label.set_halign(Gtk.Align.CENTER)
        self.title_label.set_justify(Gtk.Justification.CENTER)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(32)
        controls_card.append(self.title_label)

        # Artista — Álbum centrado
        self.sub_label = Gtk.Label(label="")
        self.sub_label.add_css_class("mini-player-sub")
        self.sub_label.set_halign(Gtk.Align.CENTER)
        self.sub_label.set_justify(Gtk.Justification.CENTER)
        self.sub_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub_label.set_max_width_chars(36)
        controls_card.append(self.sub_label)

        # Barra de tiempo interactiva: [ 2:33  ======-----  -1:54 ]
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        seek_box.set_valign(Gtk.Align.CENTER)
        seek_box.set_margin_top(4)

        self.pos_label = Gtk.Label(label="0:00")
        self.pos_label.add_css_class("mini-player-time")
        self.pos_label.set_xalign(1.0)
        seek_box.append(self.pos_label)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.add_css_class("mini-player-scale")
        self.scale.connect("change-value", self._on_scale_change_value)
        seek_box.append(self.scale)

        self.dur_label = Gtk.Label(label="-0:00")
        self.dur_label.add_css_class("mini-player-time")
        self.dur_label.set_xalign(0.0)
        seek_box.append(self.dur_label)

        controls_card.append(seek_box)

        # Fila de botones de transporte centrados
        transport_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        transport_box.set_halign(Gtk.Align.CENTER)
        transport_box.set_valign(Gtk.Align.CENTER)
        transport_box.set_margin_top(6)

        # Botón Aleatorio
        self.shuffle_btn = Gtk.ToggleButton()
        self.shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.shuffle_btn.add_css_class("flat")
        self.shuffle_btn.add_css_class("mini-player-aux-btn")
        self.shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        transport_box.append(self.shuffle_btn)

        # Pista Anterior
        self.btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.btn_prev.add_css_class("flat")
        self.btn_prev.add_css_class("mini-player-skip-btn")
        self.btn_prev.set_tooltip_text(i18n.t("player.prev"))
        self.btn_prev.connect("clicked", lambda *_: self.main_window._play_previous())
        transport_box.append(self.btn_prev)

        # Play / Pausa Prominente Circular
        self.btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.btn_play.add_css_class("flat")
        self.btn_play.add_css_class("mini-player-play-btn")
        self.btn_play.set_tooltip_text(i18n.t("player.play_pause"))
        self.btn_play.connect("clicked", lambda *_: self.main_window._toggle_play_pause())
        transport_box.append(self.btn_play)

        # Pista Siguiente
        self.btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.btn_next.add_css_class("flat")
        self.btn_next.add_css_class("mini-player-skip-btn")
        self.btn_next.set_tooltip_text(i18n.t("player.next"))
        self.btn_next.connect("clicked", lambda *_: self.main_window._play_next())
        transport_box.append(self.btn_next)

        # Repetición
        self.repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.repeat_btn.add_css_class("flat")
        self.repeat_btn.add_css_class("mini-player-aux-btn")
        self.repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
        self.repeat_btn.connect("clicked", lambda *_: self.main_window._toggle_repeat())
        transport_box.append(self.repeat_btn)

        controls_card.append(transport_box)
        self.hud_box.append(controls_card)

        root_overlay.add_overlay(self.hud_box)

        # Envolver en WindowHandle para permitir arrastrar la ventana pulsando sobre el fondo
        self.handle = Gtk.WindowHandle()
        self.handle.set_child(root_overlay)
        self.set_content(self.handle)

    def _setup_controllers(self):
        # 1. Teclado: Escape vuelve a la ventana principal, Espacio pausa/reproduce
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # 2. Movimiento de ratón (Hover) para auto-ocultar/mostrar HUD
        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("enter", self._on_pointer_enter)
        motion_ctrl.connect("motion", self._on_pointer_motion)
        motion_ctrl.connect("leave", self._on_pointer_leave)
        self.add_controller(motion_ctrl)

        # 3. Clic para conmutar entre Osciloscopio y Portada Limpia sin romper el drag-and-drop
        click_gesture = Gtk.GestureClick()
        click_gesture.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        click_gesture.connect("pressed", self._on_click_pressed)
        click_gesture.connect("released", self._on_click_released)
        self.add_controller(click_gesture)

    def _on_click_pressed(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float):
        self._press_x = x
        self._press_y = y

    def _on_click_released(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float):
        dx = x - self._press_x
        dy = y - self._press_y
        dist_sq = dx * dx + dy * dy

        # Solo considerar clic si el cursor casi no se desplazó (no fue un arrastre de ventana)
        if dist_sq < 36:
            is_hud_visible = self.hud_box.has_css_class("visible")
            if is_hud_visible:
                h = self.get_height() or 500
                # Evitar conmutar si se hace clic en la barra superior o en los controles inferiores
                if y < 60 or y > (h - 170):
                    return
            self.toggle_oscilloscope_mode()

    def toggle_oscilloscope_mode(self):
        """Conmuta entre Modo 0 (Osciloscopio superpuesto) y Modo 1 (Portada limpia)."""
        self._oscilloscope_mode = 1 if self._oscilloscope_mode == 0 else 0
        is_active = (self._oscilloscope_mode == 0)
        is_playing = (self.engine.state == PlaybackState.PLAYING)
        log.info(
            "Conmutando visualizador en mini-reproductor: %s",
            "Osciloscopio activo" if is_active else "Portada Limpia HD",
        )
        self.scope.set_active(is_active)
        self.scope.set_playing(is_playing)
        self.scope.set_visible(is_active and is_playing)

    def toggle_fullscreen(self):
        """Alterna el modo de pantalla completa."""
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_fullscreen_changed(self, *_):
        """Actualiza la apariencia y controles según el estado de pantalla completa."""
        is_fs = self.is_fullscreen()
        if is_fs:
            self.btn_fullscreen.set_icon_name("view-restore-symbolic")
            self.btn_fullscreen.set_tooltip_text(i18n.t("header.unfullscreen"))
            self.add_css_class("fullscreen-mode")
            self.set_title(f"MyFlac - {i18n.t('header.fullscreen')}")
        else:
            self.btn_fullscreen.set_icon_name("view-fullscreen-symbolic")
            self.btn_fullscreen.set_tooltip_text(i18n.t("header.fullscreen"))
            self.remove_css_class("fullscreen-mode")
            self.set_title("MyFlac - Mini Reproductor")

    # -------------------------------------------------------------------------
    # Auto-ocultación por Hover del HUD
    # -------------------------------------------------------------------------
    def _on_pointer_enter(self, _ctrl: Gtk.EventControllerMotion, _x: float, _y: float):
        self._mouse_inside = True
        self.show_hud()
        self.reset_hud_timeout(3.0)

    def _on_pointer_motion(self, _ctrl: Gtk.EventControllerMotion, _x: float, _y: float):
        self._mouse_inside = True
        self.show_hud()
        self.reset_hud_timeout(3.0)

    def _on_pointer_leave(self, _ctrl: Gtk.EventControllerMotion):
        self._mouse_inside = False
        # Ocultar rápidamente tras salir el cursor si no estamos manipulando la barra
        self.reset_hud_timeout(0.6)

    def show_hud(self):
        """Muestra los controles HUD suavemente."""
        if not self.hud_box.has_css_class("visible"):
            self.hud_box.add_css_class("visible")

    def hide_hud(self):
        """Oculta los controles HUD para dejar la portada pura."""
        if self._is_seeking:
            return
        if self.hud_box.has_css_class("visible"):
            self.hud_box.remove_css_class("visible")

    def reset_hud_timeout(self, seconds: float = 3.0):
        if self._hud_timeout_id is not None:
            GLib.source_remove(self._hud_timeout_id)
            self._hud_timeout_id = None

        def _timeout_cb():
            self._hud_timeout_id = None
            if not self._is_seeking:
                self.hide_hud()
            return False

        self._hud_timeout_id = GLib.timeout_add(int(seconds * 1000), _timeout_cb)

    def present_mini_player(self):
        """Muestra el mini-reproductor y da un pulso inicial al HUD para luego auto-ocultarlo."""
        self.present()
        is_playing = (self.engine.state == PlaybackState.PLAYING)
        is_scope_mode = (self._oscilloscope_mode == 0)
        self.scope.set_active(is_scope_mode)
        self.scope.set_playing(is_playing)
        self.scope.set_visible(is_scope_mode and is_playing)

        # Mostrar HUD brevemente y auto-ocultar a los 2.5s
        self.show_hud()
        self.reset_hud_timeout(2.5)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        elif keyval == Gdk.KEY_Escape:
            if self.is_fullscreen():
                self.unfullscreen()
            else:
                self.restore_main_window()
            return True
        elif keyval == Gdk.KEY_space:
            self.main_window._toggle_play_pause()
            return True
        return False

    def _on_shuffle_toggle(self, btn: Gtk.ToggleButton):
        active = btn.get_active()
        if active:
            btn.add_css_class("active")
        else:
            btn.remove_css_class("active")
        if hasattr(self.main_window, "player_bar") and hasattr(self.main_window.player_bar, "shuffle_btn"):
            if self.main_window.player_bar.shuffle_btn.get_active() != active:
                self.main_window.player_bar.shuffle_btn.set_active(active)

    def _connect_engine(self):
        self.engine.add_state_listener(self._on_playback_state_changed)
        self.engine.add_track_listener(self._on_track_changed)
        self.engine.add_position_listener(self._on_position_updated)
        self.engine.add_level_listener(self._on_level_updated)

        if self.engine.current_track:
            self.set_track(self.engine.current_track)
        self._update_play_button(self.engine.state)

        # Sincronizar posición actual inmediatamente
        pos = self.engine.position
        if self._current_duration > 0.0:
            self.scale.set_value(pos)
            self.pos_label.set_text(self._format_sec(pos))
            self.dur_label.set_text(self._format_remaining_sec(pos, self._current_duration))

    def set_track(self, track: AudioTrack | None):
        if not track:
            self.title_label.set_text(i18n.t("inspector.no_playback"))
            self.sub_label.set_text("")
            self.cover_stack.set_visible_child_name("placeholder")
            return

        self.title_label.set_text(track.title or os.path.basename(track.filepath))
        sub_text = track.artist or ""
        if track.album:
            sub_text = f"{sub_text} — {track.album}" if sub_text else track.album
        self.sub_label.set_text(sub_text)

        self._current_duration = track.duration or 0.0
        self.scale.set_range(0.0, max(1.0, self._current_duration))
        self.dur_label.set_text(self._format_remaining_sec(self._current_position, self._current_duration))

        # Cargar carátula HD
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            data, mime = cover_info
            gbytes = GLib.Bytes.new(data)
            texture = Gdk.Texture.new_from_bytes(gbytes)
            self.cover_picture.set_paintable(texture)
            self.cover_stack.set_visible_child_name("picture")
        else:
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")

    def _on_track_changed(self, track: AudioTrack):
        GLib.idle_add(self.set_track, track)

    def _on_playback_state_changed(self, state: PlaybackState):
        GLib.idle_add(self._update_play_button, state)
        is_playing = (state == PlaybackState.PLAYING)
        GLib.idle_add(self.scope.set_playing, is_playing)
        GLib.idle_add(self.scope.set_visible, is_playing and (self._oscilloscope_mode == 0))

    def _update_play_button(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        icon = "media-playback-pause-symbolic" if is_playing else "media-playback-start-symbolic"
        self.btn_play.set_icon_name(icon)

    def _on_level_updated(self, rms: list[float], peak: list[float]):
        if self.get_visible() and self._oscilloscope_mode == 0:
            self.scope.update_levels(rms, peak)

    def _on_position_updated(self, pos: float, dur: float):
        if not self.get_visible():
            return
        self._current_position = pos
        if not self._is_seeking and self._current_duration > 0.0:
            self.scale.set_value(pos)
            self.pos_label.set_text(self._format_sec(pos))
            self.dur_label.set_text(self._format_remaining_sec(pos, self._current_duration))

    def _on_scale_change_value(self, _scale, _scroll_type, value: float) -> bool:
        self._is_seeking = True
        self.engine.seek(value)
        self.pos_label.set_text(self._format_sec(value))
        self.dur_label.set_text(self._format_remaining_sec(value, self._current_duration))
        # Reanudar actualizaciones tras medio segundo
        GLib.timeout_add(300, self._finish_seeking)
        return False

    def _finish_seeking(self) -> bool:
        self._is_seeking = False
        return False

    def _format_sec(self, sec: float) -> str:
        s = int(max(0.0, sec))
        m = s // 60
        r = s % 60
        return f"{m}:{r:02d}"

    def _format_remaining_sec(self, pos: float, dur: float) -> str:
        if dur <= 0:
            return "-0:00"
        rem = max(0.0, dur - pos)
        return f"-{self._format_sec(rem)}"

    def restore_main_window(self):
        """Cierra el mini-reproductor y vuelve a mostrar la ventana principal."""
        log.info("Restaurando ventana principal desde Mini-Reproductor")
        if self._hud_timeout_id is not None:
            GLib.source_remove(self._hud_timeout_id)
            self._hud_timeout_id = None
        if self.is_fullscreen():
            self.unfullscreen()
        self.scope.set_active(False)
        self.hide()
        self.main_window.set_visible(True)
        self.main_window.present()

    def destroy_window(self):
        """Desconecta listeners del motor y destruye la ventana."""
        if self._hud_timeout_id is not None:
            GLib.source_remove(self._hud_timeout_id)
            self._hud_timeout_id = None
        self.scope.set_active(False)
        try:
            self.engine.remove_state_listener(self._on_playback_state_changed)
            self.engine.remove_track_listener(self._on_track_changed)
            self.engine.remove_position_listener(self._on_position_updated)
            self.engine.remove_level_listener(self._on_level_updated)
        except Exception:
            pass
        self.destroy()

    def _on_close_request(self, _window) -> bool:
        self.restore_main_window()
        return True
