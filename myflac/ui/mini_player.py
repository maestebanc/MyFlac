"""Ventana de Mini-Reproductor y Super-Reproductor a pantalla completa con osciloscopio y letras online."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack
from ..config import load_config, save_config
from ..logger import get_logger
from ..lyrics import LyricsService
from ..artist_art import ArtistArtService
from .. import i18n
from .super_player import SuperPlayerMixin
from .visualizers import OscilloscopeWidget

if TYPE_CHECKING:
    from .main_window import MainWindow

log = get_logger("ui.mini_player")


class MiniPlayerWindow(SuperPlayerMixin, Adw.Window):
    """
    Ventana flotante y expansible para MyFlac:
    1. Modo Mini-Reproductor (estrictamente 500x500 px): Carátula HD centrada con osciloscopio
       superpuesto, controles HUD auto-ocultables y arrastre por WindowHandle.
    2. Modo Super-Reproductor (Pantalla Completa):
       - Fondo atmosférico dinámico derivado de la carátula.
       - Panel izquierdo: Marco de arte de gran tamaño con osciloscopio de 60 FPS y
         dock flotante de controles auto-ocultable.
       - Panel derecho: Tipografía editorial grande (Hi-Res badge, título, artista, álbum)
         y letras online (LRCLIB) flotantes con scroll suave.
       - Botón superior derecho único de restauración.
    """

    def __init__(self, main_window: MainWindow, engine: AudioEngine):
        super().__init__()
        self.main_window = main_window
        self.engine = engine
        self.lyrics_service = LyricsService()
        self.artist_art_service = ArtistArtService.get_default()
        self._current_artist_image: str | None = None
        self._last_artist_searched: str | None = None

        self._launched_from = "mini"  # 'mini' o 'main'
        self._is_seeking = False
        self._current_duration = 0.0
        self._current_position = 0.0

        # Cargar modo visualizador persistente (0: Portada+Osciloscopio, 1: Portada limpia)
        cfg = load_config()
        if hasattr(main_window, "inspector") and hasattr(main_window.inspector, "visualizer_mode"):
            self._oscilloscope_mode = main_window.inspector.visualizer_mode % 2
        else:
            self._oscilloscope_mode = cfg.get("visualizer_mode", 0) % 2

        self._hud_timeout_id: int | None = None
        self._mouse_inside = False

        self._press_x = 0.0
        self._press_y = 0.0
        self._last_lyrics_track_id: str | None = None

        # Proveedor de CSS dinámico para el fondo atmosférico del Super-Reproductor
        self._ambient_css_provider = Gtk.CssProvider()
        disp = Gdk.Display.get_default()
        if disp:
            Gtk.StyleContext.add_provider_for_display(
                disp, self._ambient_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 20
            )

        self.set_title("MyFlac - Mini Reproductor")
        self.set_default_size(500, 500)
        self.set_size_request(500, 500)
        self.set_resizable(False)
        self.add_css_class("mini-player-window")

        app = main_window.get_application()
        if app:
            self.set_application(app)

        self.connect("notify::fullscreened", self._on_fullscreen_changed)

        self._build_ui()
        self._connect_engine()
        self._setup_controllers()
        self.set_visualizer_mode(self._oscilloscope_mode, save=False)

        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        # Stack no homogéneo para que la vista Super no fuerce a la vista Mini a expandirse
        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.set_hhomogeneous(False)
        self.main_stack.set_vhomogeneous(False)

        # 1. Página Modo Mini-Reproductor (500x500 px)
        mini_page = self._build_mini_ui()
        self.main_stack.add_named(mini_page, "mini")

        # 2. Página Modo Super-Reproductor a Pantalla Completa (Canvas Hi-Fi)
        super_page = self._build_super_ui()
        self.main_stack.add_named(super_page, "super")

        self.main_stack.set_visible_child_name("mini")

        # WindowHandle para permitir arrastrar la ventana en modo mini
        self.handle = Gtk.WindowHandle()
        self.handle.set_child(self.main_stack)
        self.set_content(self.handle)

    # =========================================================================
    # 1. CONSTRUCCIÓN MODO MINI-REPRODUCTOR (500x500 px)
    # =========================================================================
    def _build_mini_ui(self) -> Gtk.Widget:
        root_overlay = Gtk.Overlay()
        root_overlay.set_size_request(500, 500)
        root_overlay.set_hexpand(False)
        root_overlay.set_vexpand(False)

        # 1.1 Base: Carátula en alta resolución
        self.mini_cover_stack = Gtk.Stack()
        self.mini_cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.mini_cover_stack.set_size_request(500, 500)

        self.mini_cover_picture = Gtk.Picture()
        self.mini_cover_picture.set_can_shrink(True)
        self.mini_cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.mini_cover_picture.set_size_request(500, 500)
        self.mini_cover_stack.add_named(self.mini_cover_picture, "picture")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        ph_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        ph_icon.set_pixel_size(96)
        ph_icon.set_opacity(0.35)
        placeholder.append(ph_icon)
        self.mini_cover_stack.add_named(placeholder, "placeholder")
        self.mini_cover_stack.set_visible_child_name("placeholder")

        root_overlay.set_child(self.mini_cover_stack)

        # 1.2 Capa de Osciloscopio Superpuesto
        self.mini_scope = OscilloscopeWidget()
        self.mini_scope.set_size_request(500, 500)
        self.mini_scope.set_active(True)
        self.mini_scope.set_visible(False)
        root_overlay.add_overlay(self.mini_scope)

        # 1.3 Capa HUD centrada con auto-ocultación
        self.mini_hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.mini_hud_box.add_css_class("mini-player-hud")
        self.mini_hud_box.set_size_request(500, 500)

        # Barra Superior: Pantalla Completa y Regreso (Flecha Abajo)
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_bar.set_valign(Gtk.Align.START)
        top_bar.set_halign(Gtk.Align.FILL)
        top_bar.set_margin_top(12)
        top_bar.set_margin_start(14)
        top_bar.set_margin_end(14)

        top_spacer = Gtk.Box()
        top_spacer.set_hexpand(True)
        top_bar.append(top_spacer)

        self.mini_btn_fullscreen = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic")
        self.mini_btn_fullscreen.add_css_class("mini-player-btn-circle")
        self.mini_btn_fullscreen.add_css_class("flat")
        self.mini_btn_fullscreen.set_tooltip_text(i18n.t("header.super_player"))
        self.mini_btn_fullscreen.connect("clicked", lambda *_: self.toggle_fullscreen())
        top_bar.append(self.mini_btn_fullscreen)

        self.mini_btn_dock = Gtk.Button.new_from_icon_name("go-down-symbolic")
        self.mini_btn_dock.add_css_class("mini-player-btn-circle")
        self.mini_btn_dock.add_css_class("flat")
        self.mini_btn_dock.set_tooltip_text(i18n.t("header.dock_main"))
        self.mini_btn_dock.connect("clicked", lambda *_: self.restore_main_window())
        top_bar.append(self.mini_btn_dock)

        self.mini_hud_box.append(top_bar)

        mid_spacer = Gtk.Box()
        mid_spacer.set_vexpand(True)
        self.mini_hud_box.append(mid_spacer)

        # Contenedor de Controles Centrados estilo Apple Music
        controls_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        controls_card.set_halign(Gtk.Align.CENTER)
        controls_card.set_valign(Gtk.Align.END)
        controls_card.set_size_request(440, -1)
        controls_card.set_margin_start(16)
        controls_card.set_margin_end(16)
        controls_card.set_margin_bottom(24)

        self.mini_title_label = Gtk.Label(label=i18n.t("inspector.no_playback"))
        self.mini_title_label.add_css_class("mini-player-title")
        self.mini_title_label.set_halign(Gtk.Align.CENTER)
        self.mini_title_label.set_justify(Gtk.Justification.CENTER)
        self.mini_title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.mini_title_label.set_max_width_chars(32)
        controls_card.append(self.mini_title_label)

        self.mini_sub_label = Gtk.Label(label="")
        self.mini_sub_label.add_css_class("mini-player-sub")
        self.mini_sub_label.set_halign(Gtk.Align.CENTER)
        self.mini_sub_label.set_justify(Gtk.Justification.CENTER)
        self.mini_sub_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.mini_sub_label.set_max_width_chars(36)
        controls_card.append(self.mini_sub_label)

        # Barra de tiempo
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        seek_box.set_valign(Gtk.Align.CENTER)
        seek_box.set_margin_top(4)

        self.mini_pos_label = Gtk.Label(label="0:00")
        self.mini_pos_label.add_css_class("mini-player-time")
        self.mini_pos_label.set_xalign(1.0)
        seek_box.append(self.mini_pos_label)

        self.mini_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.mini_scale.set_hexpand(True)
        self.mini_scale.set_draw_value(False)
        self.mini_scale.add_css_class("mini-player-scale")
        self.mini_scale.connect("change-value", self._on_scale_change_value)
        seek_box.append(self.mini_scale)

        self.mini_dur_label = Gtk.Label(label="-0:00")
        self.mini_dur_label.add_css_class("mini-player-time")
        self.mini_dur_label.set_xalign(0.0)
        seek_box.append(self.mini_dur_label)

        controls_card.append(seek_box)

        # Botones de transporte
        transport_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        transport_box.set_halign(Gtk.Align.CENTER)
        transport_box.set_valign(Gtk.Align.CENTER)
        transport_box.set_margin_top(6)

        self.mini_shuffle_btn = Gtk.ToggleButton()
        self.mini_shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.mini_shuffle_btn.add_css_class("flat")
        self.mini_shuffle_btn.add_css_class("mini-player-aux-btn")
        self.mini_shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.mini_shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        transport_box.append(self.mini_shuffle_btn)

        self.mini_btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.mini_btn_prev.add_css_class("flat")
        self.mini_btn_prev.add_css_class("mini-player-skip-btn")
        self.mini_btn_prev.set_tooltip_text(i18n.t("player.prev"))
        self.mini_btn_prev.connect("clicked", lambda *_: self.main_window._play_previous())
        transport_box.append(self.mini_btn_prev)

        self.mini_btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.mini_btn_play.add_css_class("flat")
        self.mini_btn_play.add_css_class("mini-player-play-btn")
        self.mini_btn_play.set_tooltip_text(i18n.t("player.play_pause"))
        self.mini_btn_play.connect("clicked", lambda *_: self.main_window._toggle_play_pause())
        transport_box.append(self.mini_btn_play)

        self.mini_btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.mini_btn_next.add_css_class("flat")
        self.mini_btn_next.add_css_class("mini-player-skip-btn")
        self.mini_btn_next.set_tooltip_text(i18n.t("player.next"))
        self.mini_btn_next.connect("clicked", lambda *_: self.main_window._play_next())
        transport_box.append(self.mini_btn_next)

        self.mini_repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.mini_repeat_btn.add_css_class("flat")
        self.mini_repeat_btn.add_css_class("mini-player-aux-btn")
        self.mini_repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
        self.mini_repeat_btn.connect("clicked", lambda *_: self.main_window._toggle_repeat())
        transport_box.append(self.mini_repeat_btn)

        controls_card.append(transport_box)
        self.mini_hud_box.append(controls_card)

        root_overlay.add_overlay(self.mini_hud_box)
        return root_overlay


    # =========================================================================
    # 3. CONTROLADORES DE EVENTOS Y GESTOS
    # =========================================================================
    def _setup_controllers(self):
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("enter", self._on_pointer_enter)
        motion_ctrl.connect("motion", self._on_pointer_motion)
        motion_ctrl.connect("leave", self._on_pointer_leave)
        self.add_controller(motion_ctrl)

        # Clic para modo mini
        mini_click = Gtk.GestureClick()
        mini_click.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        mini_click.connect("pressed", self._on_click_pressed)
        mini_click.connect("released", self._on_click_released)
        self.add_controller(mini_click)

    def _on_click_pressed(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float):
        self._press_x = x
        self._press_y = y

    def _on_click_released(self, _gesture: Gtk.GestureClick, _n_press: int, x: float, y: float):
        dx = x - self._press_x
        dy = y - self._press_y
        dist_sq = dx * dx + dy * dy

        # Solo procesar en modo mini (en modo super se usa el gesto dedicado en la carátula)
        if dist_sq < 36 and not self.is_fullscreen():
            is_hud_visible = self.mini_hud_box.has_css_class("visible")
            if is_hud_visible and (y < 60 or y > 330):
                return
            self.toggle_oscilloscope_mode()

    def _on_art_frame_clicked(self, _gesture: Gtk.GestureClick, _n_press: int, _x: float, _y: float):
        """Conmuta el osciloscopio al hacer clic directamente en la carátula en modo super."""
        self.toggle_oscilloscope_mode()

    def set_visualizer_mode(self, mode: int, save: bool = True):
        """Establece el modo del osciloscopio (0: activo, 1: limpio) y sincroniza con todos los reproductores."""
        self._oscilloscope_mode = mode % 2
        is_active = (self._oscilloscope_mode == 0)
        is_playing = (self.engine.state == PlaybackState.PLAYING)

        self.mini_scope.set_active(is_active)
        self.mini_scope.set_playing(is_playing)
        self.mini_scope.set_visible(is_active and is_playing)

        self.super_scope.set_active(is_active)
        self.super_scope.set_playing(is_playing)
        self.super_scope.set_visible(is_active and is_playing)

        # Sincronizar con el panel inspector de la ventana principal
        if hasattr(self.main_window, "inspector") and self.main_window.inspector:
            self.main_window.inspector.set_visualizer_mode(self._oscilloscope_mode)

        # Persistir en la configuración
        if save:
            try:
                cfg = load_config()
                cfg["visualizer_mode"] = self._oscilloscope_mode
                save_config(cfg)
                if hasattr(self.main_window, "cfg"):
                    self.main_window.cfg["visualizer_mode"] = self._oscilloscope_mode
            except Exception as e:
                log.warning("No se pudo guardar visualizer_mode desde MiniPlayer: %s", e)

    def toggle_oscilloscope_mode(self):
        """Conmuta entre Modo 0 (Osciloscopio superpuesto) y Modo 1 (Portada limpia) y persiste."""
        new_mode = 1 if self._oscilloscope_mode == 0 else 0
        log.info(
            "Conmutando visualizador: %s",
            "Osciloscopio activo" if new_mode == 0 else "Portada Limpia HD",
        )
        self.set_visualizer_mode(new_mode, save=True)


    def toggle_fullscreen(self):
        """Alterna entre el Mini-Reproductor (500x500) y el Super-Reproductor a Pantalla Completa."""
        is_currently_super = (self.main_stack.get_visible_child_name() == "super") or self.is_fullscreen()
        if is_currently_super:
            self.unfullscreen()
            self._apply_player_mode(is_super=False)
        else:
            self.fullscreen()
            self._apply_player_mode(is_super=True)

    def _apply_player_mode(self, is_super: bool):
        is_playing = (self.engine.state == PlaybackState.PLAYING)
        scope_on = (self._oscilloscope_mode == 0) and is_playing

        if is_super:
            self.set_resizable(True)
            self.set_size_request(-1, -1)
            self.main_stack.set_visible_child_name("super")
            self.add_css_class("super-player-window")
            self.remove_css_class("mini-player-window")
            self.set_title(f"MyFlac - {i18n.t('header.super_player')}")

            # Calcular tamaño de carátula según la altura de la pantalla (máx 640px)
            h = self.get_height()
            if h <= 0:
                h = 1080
            art_size = max(440, min(640, h - 240))
            self.super_art_overlay.set_size_request(art_size, art_size)
            self.super_cover_stack.set_size_request(art_size, art_size)
            self.super_cover_picture.set_size_request(art_size, art_size)
            self.super_scope.set_size_request(art_size, art_size)
            self.super_controls_panel.set_size_request(art_size, -1)

            self.super_scope.set_active(self._oscilloscope_mode == 0)
            self.super_scope.set_playing(is_playing)
            self.super_scope.set_visible(scope_on)

            if self.engine.current_track:
                self._load_lyrics_for_track(self.engine.current_track)
        else:
            self.main_stack.set_visible_child_name("mini")
            self.set_resizable(False)
            self.set_size_request(500, 500)
            self.set_default_size(500, 500)
            self.add_css_class("mini-player-window")
            self.remove_css_class("super-player-window")
            self.set_title("MyFlac - Mini Reproductor")

            self.mini_scope.set_active(self._oscilloscope_mode == 0)
            self.mini_scope.set_playing(is_playing)
            self.mini_scope.set_visible(scope_on)

    def _on_fullscreen_changed(self, *_):
        """Actualiza la apariencia y el tamaño del panel de arte según la pantalla."""
        self._apply_player_mode(self.is_fullscreen())

    # -------------------------------------------------------------------------
    # Auto-ocultación del HUD y Controles (Hover)
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
        self.reset_hud_timeout(0.6)

    def show_hud(self):
        """Muestra los controles suavemente."""
        if not self.mini_hud_box.has_css_class("visible"):
            self.mini_hud_box.add_css_class("visible")
        if not self.super_controls_panel.has_css_class("visible"):
            self.super_controls_panel.add_css_class("visible")
        self.super_btn_restore.set_opacity(1.0)

    def hide_hud(self):
        """Oculta los controles para una experiencia inmersiva."""
        if self._is_seeking:
            return
        if self.mini_hud_box.has_css_class("visible"):
            self.mini_hud_box.remove_css_class("visible")
        if self.super_controls_panel.has_css_class("visible"):
            self.super_controls_panel.remove_css_class("visible")
        # Mantener el botón de restauración sutilmente visible para orientación
        self.super_btn_restore.set_opacity(0.25)

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
        """Muestra el mini-reproductor compacto estrictamente en 500x500 px."""
        self._launched_from = "mini"
        if hasattr(self.main_window, "inspector") and self.main_window.inspector:
            self.set_visualizer_mode(self.main_window.inspector.visualizer_mode, save=False)
        if self.is_fullscreen():
            self.unfullscreen()
        self.set_resizable(False)
        self.set_size_request(500, 500)
        self.set_default_size(500, 500)
        self._apply_player_mode(is_super=False)
        self.present()
        self.show_hud()
        self.reset_hud_timeout(2.5)

    def present_super_player(self):
        """Muestra directamente el Super-Reproductor a pantalla completa."""
        self._launched_from = "main"
        if hasattr(self.main_window, "inspector") and self.main_window.inspector:
            self.set_visualizer_mode(self.main_window.inspector.visualizer_mode, save=False)
        self._apply_player_mode(is_super=True)
        self.fullscreen()
        self.present()
        self.show_hud()
        self.reset_hud_timeout(3.0)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_F11:
            if self.is_fullscreen():
                self._on_super_restore_clicked()
            else:
                self.present_super_player()
            return True
        elif keyval == Gdk.KEY_Escape:
            if self.is_fullscreen():
                self._on_super_restore_clicked()
            else:
                self.restore_main_window()
            return True
        elif keyval == Gdk.KEY_space:
            self.main_window._toggle_play_pause()
            return True
        return False

    def _on_shuffle_toggle(self, btn: Gtk.ToggleButton):
        active = btn.get_active()
        self.mini_shuffle_btn.set_active(active)
        self.super_shuffle_btn.set_active(active)
        if hasattr(self.main_window, "player_bar") and hasattr(self.main_window.player_bar, "shuffle_btn"):
            if self.main_window.player_bar.shuffle_btn.get_active() != active:
                self.main_window.player_bar.shuffle_btn.set_active(active)


    def _connect_engine(self):
        self.engine.add_state_listener(self._on_playback_state_changed)
        self.engine.add_track_listener(self._on_track_changed)
        self.engine.add_position_listener(self._on_position_updated)
        self.engine.add_level_listener(self._on_level_updated)
        self.engine.add_output_listener(self._on_output_changed)
        self._on_output_changed()

        if self.engine.current_track:
            self.set_track(self.engine.current_track)
        self._update_play_button(self.engine.state)

        pos = self.engine.position
        if self._current_duration > 0.0:
            self.mini_scale.set_value(pos)
            self.super_scale.set_value(pos)
            pos_str = self._format_sec(pos)
            dur_str = self._format_remaining_sec(pos, self._current_duration)
            self.mini_pos_label.set_text(pos_str)
            self.super_pos_label.set_text(pos_str)
            self.mini_dur_label.set_text(dur_str)
            self.super_dur_label.set_text(dur_str)

    def set_track(self, track: AudioTrack | None):
        if not track:
            self.mini_title_label.set_text(i18n.t("inspector.no_playback"))
            self.mini_sub_label.set_text("")
            self.mini_cover_stack.set_visible_child_name("placeholder")

            self.super_title_label.set_text(i18n.t("inspector.no_playback"))
            self.super_artist_label.set_text("")
            self.super_album_label.set_text("")
            self.super_badge_label.set_text("")
            self.super_cover_stack.set_visible_child_name("placeholder")
            self.lyrics_stack.set_visible_child_name("not_found")
            self._update_ambient_background(None)
            self._on_artist_image_loaded(None)
            self._last_artist_searched = None
            return

        title = track.title or os.path.basename(track.filepath)
        artist = track.artist or ""
        album = track.album or ""
        sub_text = f"{artist} — {album}" if (artist and album) else (artist or album)

        # Actualizar etiquetas modo mini
        self.mini_title_label.set_text(title)
        self.mini_sub_label.set_text(sub_text)

        # Actualizar etiquetas modo super
        self.super_title_label.set_text(title)
        self.super_artist_label.set_text(artist)
        meta_sub = album
        if track.date:
            meta_sub = f"{album} ({track.date})" if album else f"({track.date})"
        self.super_album_label.set_text(meta_sub)

        # Ficha técnica de calidad audiófila
        rate_khz = track.sample_rate / 1000.0 if track.sample_rate else 44.1
        depth_str = f"{track.bits_per_sample} bits" if track.bits_per_sample > 1 else "1 bit (DSD)"
        badge_text = f"{track.format_name} • {rate_khz:g} kHz • {depth_str} • {track.formatted_bitrate}"
        self.super_badge_label.set_text(badge_text)

        self._current_duration = track.duration or 0.0
        self.mini_scale.set_range(0.0, max(1.0, self._current_duration))
        self.super_scale.set_range(0.0, max(1.0, self._current_duration))

        # Cargar carátula HD en ambas vistas y actualizar paleta ambiental
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            data, _mime = cover_info
            gbytes = GLib.Bytes.new(data)
            texture = Gdk.Texture.new_from_bytes(gbytes)
            self.mini_cover_picture.set_paintable(texture)
            self.mini_cover_stack.set_visible_child_name("picture")
            self.super_cover_picture.set_paintable(texture)
            self.super_cover_stack.set_visible_child_name("picture")
            self._update_ambient_background(data)
        else:
            self.mini_cover_picture.set_paintable(None)
            self.mini_cover_stack.set_visible_child_name("placeholder")
            self.super_cover_picture.set_paintable(None)
            self.super_cover_stack.set_visible_child_name("placeholder")
            self._update_ambient_background(None)

        # Cargar letra
        self._load_lyrics_for_track(track)

        # Cargar fotografía del artista para el fondo del Super-Reproductor
        self._load_artist_art_for_track(track)


    def _on_track_changed(self, track: AudioTrack):
        GLib.idle_add(self.set_track, track)

    def _on_playback_state_changed(self, state: PlaybackState):
        GLib.idle_add(self._update_play_button, state)
        is_playing = (state == PlaybackState.PLAYING)
        scope_on = is_playing and (self._oscilloscope_mode == 0)

        GLib.idle_add(self.mini_scope.set_playing, is_playing)
        GLib.idle_add(self.mini_scope.set_visible, scope_on)

        GLib.idle_add(self.super_scope.set_playing, is_playing)
        GLib.idle_add(self.super_scope.set_visible, scope_on)

    def _update_play_button(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        icon = "media-playback-pause-symbolic" if is_playing else "media-playback-start-symbolic"
        self.mini_btn_play.set_icon_name(icon)
        self.super_btn_play.set_icon_name(icon)

    def _on_level_updated(self, rms: list[float], peak: list[float]):
        if not self.get_visible() or self._oscilloscope_mode != 0:
            return
        if self.is_fullscreen():
            self.super_scope.update_levels(rms, peak)
        else:
            self.mini_scope.update_levels(rms, peak)

    def _on_position_updated(self, pos: float, dur: float):
        if not self.get_visible():
            return
        self._current_position = pos
        if not self._is_seeking and self._current_duration > 0.0:
            self.mini_scale.set_value(pos)
            self.super_scale.set_value(pos)
            pos_str = self._format_sec(pos)
            dur_str = self._format_remaining_sec(pos, self._current_duration)
            self.mini_pos_label.set_text(pos_str)
            self.super_pos_label.set_text(pos_str)
            self.mini_dur_label.set_text(dur_str)
            self.super_dur_label.set_text(dur_str)

    def _on_scale_change_value(self, _scale, _scroll_type, value: float) -> bool:
        self._is_seeking = True
        self.engine.seek(value)
        pos_str = self._format_sec(value)
        dur_str = self._format_remaining_sec(value, self._current_duration)
        self.mini_pos_label.set_text(pos_str)
        self.super_pos_label.set_text(pos_str)
        self.mini_dur_label.set_text(dur_str)
        self.super_dur_label.set_text(dur_str)
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
        """Cierra el mini/super-reproductor y vuelve a mostrar la ventana principal."""
        log.info("Restaurando ventana principal desde Reproductor")
        self.lyrics_service.cancel_current()
        if self._hud_timeout_id is not None:
            GLib.source_remove(self._hud_timeout_id)
            self._hud_timeout_id = None
        if self.is_fullscreen():
            self.unfullscreen()
        self._apply_player_mode(is_super=False)
        if hasattr(self.main_window, "inspector") and self.main_window.inspector:
            self.main_window.inspector.set_visualizer_mode(self._oscilloscope_mode)
        self.hide()
        self.main_window.set_visible(True)
        self.main_window.present()

    def destroy_window(self):
        """Desconecta listeners del motor y destruye la ventana."""
        self.lyrics_service.cancel_current()
        if self._hud_timeout_id is not None:
            GLib.source_remove(self._hud_timeout_id)
            self._hud_timeout_id = None
        self.mini_scope.set_active(False)
        self.super_scope.set_active(False)
        try:
            self.engine.remove_state_listener(self._on_playback_state_changed)
            self.engine.remove_track_listener(self._on_track_changed)
            self.engine.remove_position_listener(self._on_position_updated)
            self.engine.remove_level_listener(self._on_level_updated)
            self.engine.remove_output_listener(self._on_output_changed)
        except Exception:
            pass
        self.destroy()

    def _on_close_request(self, _window) -> bool:
        self.restore_main_window()
        return True
