"""Ventana de Mini-Reproductor y Super-Reproductor a pantalla completa con osciloscopio y letras online."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack
from ..logger import get_logger
from ..lyrics import LyricsService
from .. import i18n
from .visualizers import OscilloscopeWidget

if TYPE_CHECKING:
    from .main_window import MainWindow

log = get_logger("ui.mini_player")


class MiniPlayerWindow(Adw.Window):
    """
    Ventana flotante y expansible para MyFlac:
    1. Modo Mini-Reproductor (500x500 px): Carátula HD centrada con osciloscopio superpuesto,
       controles HUD auto-ocultables y arrastre por WindowHandle.
    2. Modo Super-Reproductor (Pantalla Completa):
       - Panel izquierdo: Carátula de gran tamaño (~800x800 px) con osciloscopio optimizado a 60 FPS
         y controles ampliados auto-ocultables.
       - Panel derecho: Metadatos en gran formato y visor de letras descargadas automáticamente
         de Internet con scroll fluido.
    """

    def __init__(self, main_window: MainWindow, engine: AudioEngine):
        super().__init__()
        self.main_window = main_window
        self.engine = engine
        self.lyrics_service = LyricsService()

        self.set_title("MyFlac - Mini Reproductor")
        self.set_default_size(500, 500)
        self.set_resizable(True)
        self.add_css_class("mini-player-window")

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
        self._last_lyrics_track_id: str | None = None

        self.connect("notify::fullscreened", self._on_fullscreen_changed)

        self._build_ui()
        self._connect_engine()
        self._setup_controllers()

        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # 1. Página Modo Mini-Reproductor (500x500 px)
        mini_page = self._build_mini_ui()
        self.main_stack.add_named(mini_page, "mini")

        # 2. Página Modo Super-Reproductor a Pantalla Completa (2 columnas)
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
        root_overlay.set_hexpand(True)
        root_overlay.set_vexpand(True)

        # 1.1 Base: Carátula en alta resolución
        self.mini_cover_stack = Gtk.Stack()
        self.mini_cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.mini_cover_stack.set_hexpand(True)
        self.mini_cover_stack.set_vexpand(True)

        self.mini_cover_picture = Gtk.Picture()
        self.mini_cover_picture.set_can_shrink(True)
        self.mini_cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.mini_cover_picture.set_hexpand(True)
        self.mini_cover_picture.set_vexpand(True)
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
        self.mini_scope.set_hexpand(True)
        self.mini_scope.set_vexpand(True)
        self.mini_scope.set_active(True)
        self.mini_scope.set_visible(False)
        root_overlay.add_overlay(self.mini_scope)

        # 1.3 Capa HUD Apple Music centrada con auto-ocultación
        self.mini_hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.mini_hud_box.add_css_class("mini-player-hud")
        self.mini_hud_box.set_hexpand(True)
        self.mini_hud_box.set_vexpand(True)

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
    # 2. CONSTRUCCIÓN MODO SUPER-REPRODUCTOR A PANTALLA COMPLETA
    # =========================================================================
    def _build_super_ui(self) -> Gtk.Widget:
        super_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=44)
        super_container.add_css_class("super-player-container")
        super_container.set_hexpand(True)
        super_container.set_vexpand(True)

        # ---------------------------------------------------------------------
        # 2.1 Panel Izquierdo: Carátula HD + Osciloscopio + Controles Ampliados
        # ---------------------------------------------------------------------
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_box.set_valign(Gtk.Align.CENTER)
        left_box.set_halign(Gtk.Align.CENTER)

        self.super_art_overlay = Gtk.Overlay()
        self.super_art_overlay.add_css_class("super-player-art-card")
        self.super_art_overlay.set_size_request(760, 760)

        # Carátula en alta definición
        self.super_cover_stack = Gtk.Stack()
        self.super_cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.super_cover_stack.set_hexpand(True)
        self.super_cover_stack.set_vexpand(True)

        self.super_cover_picture = Gtk.Picture()
        self.super_cover_picture.set_can_shrink(True)
        self.super_cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.super_cover_picture.set_hexpand(True)
        self.super_cover_picture.set_vexpand(True)
        self.super_cover_stack.add_named(self.super_cover_picture, "picture")

        super_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        super_placeholder.set_valign(Gtk.Align.CENTER)
        super_placeholder.set_halign(Gtk.Align.CENTER)
        super_ph_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        super_ph_icon.set_pixel_size(160)
        super_ph_icon.set_opacity(0.35)
        super_placeholder.append(super_ph_icon)
        self.super_cover_stack.add_named(super_placeholder, "placeholder")
        self.super_cover_stack.set_visible_child_name("placeholder")

        self.super_art_overlay.set_child(self.super_cover_stack)

        # Osciloscopio en el super-reproductor
        self.super_scope = OscilloscopeWidget()
        self.super_scope.set_hexpand(True)
        self.super_scope.set_vexpand(True)
        self.super_scope.set_active(True)
        self.super_scope.set_visible(False)
        self.super_art_overlay.add_overlay(self.super_scope)

        # Controles HUD superpuestos sobre la carátula izquierda (Auto-Hide)
        self.super_hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.super_hud_box.add_css_class("mini-player-hud")
        self.super_hud_box.set_hexpand(True)
        self.super_hud_box.set_vexpand(True)

        super_mid_spacer = Gtk.Box()
        super_mid_spacer.set_vexpand(True)
        self.super_hud_box.append(super_mid_spacer)

        super_controls_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        super_controls_card.set_halign(Gtk.Align.CENTER)
        super_controls_card.set_valign(Gtk.Align.END)
        super_controls_card.set_size_request(540, -1)
        super_controls_card.set_margin_bottom(28)

        # Barra de tiempo amplia
        super_seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        super_seek_box.set_valign(Gtk.Align.CENTER)

        self.super_pos_label = Gtk.Label(label="0:00")
        self.super_pos_label.add_css_class("mini-player-time")
        self.super_pos_label.set_xalign(1.0)
        super_seek_box.append(self.super_pos_label)

        self.super_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.super_scale.set_hexpand(True)
        self.super_scale.set_draw_value(False)
        self.super_scale.add_css_class("mini-player-scale")
        self.super_scale.connect("change-value", self._on_scale_change_value)
        super_seek_box.append(self.super_scale)

        self.super_dur_label = Gtk.Label(label="-0:00")
        self.super_dur_label.add_css_class("mini-player-time")
        self.super_dur_label.set_xalign(0.0)
        super_seek_box.append(self.super_dur_label)

        super_controls_card.append(super_seek_box)

        # Botones de transporte ampliados
        super_transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        super_transport.set_halign(Gtk.Align.CENTER)
        super_transport.set_valign(Gtk.Align.CENTER)
        super_transport.set_margin_top(8)

        self.super_shuffle_btn = Gtk.ToggleButton()
        self.super_shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.super_shuffle_btn.add_css_class("flat")
        self.super_shuffle_btn.add_css_class("mini-player-aux-btn")
        self.super_shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.super_shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        super_transport.append(self.super_shuffle_btn)

        self.super_btn_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.super_btn_prev.add_css_class("flat")
        self.super_btn_prev.add_css_class("mini-player-skip-btn")
        self.super_btn_prev.set_tooltip_text(i18n.t("player.prev"))
        self.super_btn_prev.connect("clicked", lambda *_: self.main_window._play_previous())
        super_transport.append(self.super_btn_prev)

        self.super_btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.super_btn_play.add_css_class("flat")
        self.super_btn_play.add_css_class("mini-player-play-btn")
        self.super_btn_play.set_size_request(60, 60)
        self.super_btn_play.set_tooltip_text(i18n.t("player.play_pause"))
        self.super_btn_play.connect("clicked", lambda *_: self.main_window._toggle_play_pause())
        super_transport.append(self.super_btn_play)

        self.super_btn_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.super_btn_next.add_css_class("flat")
        self.super_btn_next.add_css_class("mini-player-skip-btn")
        self.super_btn_next.set_tooltip_text(i18n.t("player.next"))
        self.super_btn_next.connect("clicked", lambda *_: self.main_window._play_next())
        super_transport.append(self.super_btn_next)

        self.super_repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.super_repeat_btn.add_css_class("flat")
        self.super_repeat_btn.add_css_class("mini-player-aux-btn")
        self.super_repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
        self.super_repeat_btn.connect("clicked", lambda *_: self.main_window._toggle_repeat())
        super_transport.append(self.super_repeat_btn)

        super_controls_card.append(super_transport)
        self.super_hud_box.append(super_controls_card)

        self.super_art_overlay.add_overlay(self.super_hud_box)
        left_box.append(self.super_art_overlay)
        super_container.append(left_box)

        # ---------------------------------------------------------------------
        # 2.2 Panel Derecho: Metadatos en gran formato y Letra online
        # ---------------------------------------------------------------------
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_box.set_hexpand(True)
        right_box.set_vexpand(True)

        # Fila superior de navegación del super-reproductor
        top_nav_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top_nav_bar.set_halign(Gtk.Align.FILL)

        nav_spacer = Gtk.Box()
        nav_spacer.set_hexpand(True)
        top_nav_bar.append(nav_spacer)

        self.super_btn_unfullscreen = Gtk.Button.new_from_icon_name("view-restore-symbolic")
        self.super_btn_unfullscreen.add_css_class("mini-player-btn-circle")
        self.super_btn_unfullscreen.add_css_class("flat")
        self.super_btn_unfullscreen.set_tooltip_text(i18n.t("header.unfullscreen"))
        self.super_btn_unfullscreen.connect("clicked", lambda *_: self.toggle_fullscreen())
        top_nav_bar.append(self.super_btn_unfullscreen)

        self.super_btn_dock = Gtk.Button.new_from_icon_name("go-down-symbolic")
        self.super_btn_dock.add_css_class("mini-player-btn-circle")
        self.super_btn_dock.add_css_class("flat")
        self.super_btn_dock.set_tooltip_text(i18n.t("header.dock_main"))
        self.super_btn_dock.connect("clicked", lambda *_: self.restore_main_window())
        top_nav_bar.append(self.super_btn_dock)

        right_box.append(top_nav_bar)

        # Metadatos del tema
        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        meta_box.set_halign(Gtk.Align.FILL)

        self.super_title_label = Gtk.Label(label=i18n.t("inspector.no_playback"))
        self.super_title_label.add_css_class("super-player-title")
        self.super_title_label.set_halign(Gtk.Align.START)
        self.super_title_label.set_wrap(True)
        self.super_title_label.set_xalign(0.0)
        meta_box.append(self.super_title_label)

        self.super_artist_label = Gtk.Label(label="")
        self.super_artist_label.add_css_class("super-player-artist")
        self.super_artist_label.set_halign(Gtk.Align.START)
        self.super_artist_label.set_xalign(0.0)
        meta_box.append(self.super_artist_label)

        self.super_album_label = Gtk.Label(label="")
        self.super_album_label.add_css_class("super-player-album")
        self.super_album_label.set_halign(Gtk.Align.START)
        self.super_album_label.set_xalign(0.0)
        meta_box.append(self.super_album_label)

        self.super_badge_label = Gtk.Label(label="")
        self.super_badge_label.add_css_class("super-player-badge")
        self.super_badge_label.set_halign(Gtk.Align.START)
        self.super_badge_label.set_margin_top(4)
        meta_box.append(self.super_badge_label)

        right_box.append(meta_box)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(4)
        right_box.append(sep)

        # Sección de Letras con Scroll
        lyrics_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lyrics_container.add_css_class("super-player-lyrics-section")
        lyrics_container.set_vexpand(True)
        lyrics_container.set_hexpand(True)

        lyrics_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl_lyr_title = Gtk.Label(label=i18n.t("lyrics.title"))
        lbl_lyr_title.add_css_class("super-player-lyrics-header")
        lyrics_header_box.append(lbl_lyr_title)

        lyr_spacer = Gtk.Box()
        lyr_spacer.set_hexpand(True)
        lyrics_header_box.append(lyr_spacer)

        self.lyrics_status_label = Gtk.Label(label="")
        self.lyrics_status_label.add_css_class("dim-label")
        lyrics_header_box.append(self.lyrics_status_label)

        lyrics_container.append(lyrics_header_box)

        # Stack de estados de letra: 'loading', 'lyrics', 'instrumental', 'not_found'
        self.lyrics_stack = Gtk.Stack()
        self.lyrics_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.lyrics_stack.set_vexpand(True)
        self.lyrics_stack.set_hexpand(True)

        # Estado 1: Cargando letra
        loading_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        self.lyrics_spinner = Gtk.Spinner()
        self.lyrics_spinner.set_size_request(24, 24)
        loading_box.append(self.lyrics_spinner)
        lbl_loading = Gtk.Label(label=i18n.t("lyrics.loading"))
        lbl_loading.add_css_class("dim-label")
        loading_box.append(lbl_loading)
        self.lyrics_stack.add_named(loading_box, "loading")

        # Estado 2: Letra encontrada con scroll
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.super_lyrics_label = Gtk.Label(label="")
        self.super_lyrics_label.add_css_class("super-player-lyrics-text")
        self.super_lyrics_label.set_wrap(True)
        self.super_lyrics_label.set_xalign(0.0)
        self.super_lyrics_label.set_yalign(0.0)
        self.super_lyrics_label.set_justify(Gtk.Justification.LEFT)
        self.super_lyrics_label.set_selectable(True)
        self.super_lyrics_label.set_margin_end(16)
        scrolled.set_child(self.super_lyrics_label)
        self.lyrics_stack.add_named(scrolled, "lyrics")

        # Estado 3: Pista Instrumental
        inst_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        inst_box.add_css_class("super-player-instrumental-badge")
        inst_box.set_valign(Gtk.Align.CENTER)
        inst_box.set_halign(Gtk.Align.CENTER)
        icon_inst = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon_inst.set_pixel_size(24)
        inst_box.append(icon_inst)
        lbl_inst = Gtk.Label(label=i18n.t("lyrics.instrumental"))
        inst_box.append(lbl_inst)
        self.lyrics_stack.add_named(inst_box, "instrumental")

        # Estado 4: Letra no disponible
        not_found_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        not_found_box.set_valign(Gtk.Align.CENTER)
        not_found_box.set_halign(Gtk.Align.CENTER)
        icon_nf = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
        icon_nf.set_pixel_size(48)
        icon_nf.set_opacity(0.35)
        not_found_box.append(icon_nf)
        lbl_nf = Gtk.Label(label=i18n.t("lyrics.not_found"))
        lbl_nf.add_css_class("dim-label")
        not_found_box.append(lbl_nf)
        self.lyrics_stack.add_named(not_found_box, "not_found")

        self.lyrics_stack.set_visible_child_name("not_found")
        lyrics_container.append(self.lyrics_stack)

        right_box.append(lyrics_container)
        super_container.append(right_box)

        return super_container

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

        if dist_sq < 36:
            # En modo mini, evitar clics en la barra superior o controles
            if not self.is_fullscreen():
                is_hud_visible = self.mini_hud_box.has_css_class("visible")
                if is_hud_visible and (y < 60 or y > 330):
                    return
            else:
                # En modo super, sólo alternar osciloscopio si el clic fue en la mitad izquierda
                w = self.get_width() or 1920
                if x > (w * 0.50):
                    return
            self.toggle_oscilloscope_mode()

    def toggle_oscilloscope_mode(self):
        """Conmuta entre Modo 0 (Osciloscopio superpuesto) y Modo 1 (Portada limpia)."""
        self._oscilloscope_mode = 1 if self._oscilloscope_mode == 0 else 0
        is_active = (self._oscilloscope_mode == 0)
        is_playing = (self.engine.state == PlaybackState.PLAYING)
        log.info(
            "Conmutando visualizador: %s",
            "Osciloscopio activo" if is_active else "Portada Limpia HD",
        )
        self.mini_scope.set_active(is_active)
        self.mini_scope.set_playing(is_playing)
        self.mini_scope.set_visible(is_active and is_playing)

        self.super_scope.set_active(is_active)
        self.super_scope.set_playing(is_playing)
        self.super_scope.set_visible(is_active and is_playing)

    def toggle_fullscreen(self):
        """Alterna entre el Mini-Reproductor y el Super-Reproductor a Pantalla Completa."""
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
            self.main_stack.set_visible_child_name("super")
            self.add_css_class("super-player-window")
            self.remove_css_class("mini-player-window")
            self.set_title(f"MyFlac - {i18n.t('header.super_player')}")

            # Calcular tamaño del cuadrado de carátula en función de la altura disponible
            h = self.get_height()
            if h <= 0:
                h = 1080
            art_size = max(480, min(860, h - 120))
            self.super_art_overlay.set_size_request(art_size, art_size)
            self.super_cover_stack.set_size_request(art_size, art_size)
            self.super_cover_picture.set_size_request(art_size, art_size)
            self.super_scope.set_size_request(art_size, art_size)

            self.super_scope.set_active(self._oscilloscope_mode == 0)
            self.super_scope.set_playing(is_playing)
            self.super_scope.set_visible(scope_on)

            if self.engine.current_track:
                self._load_lyrics_for_track(self.engine.current_track)
        else:
            self.main_stack.set_visible_child_name("mini")
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
    # Auto-ocultación del HUD (Hover)
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
        """Muestra los controles HUD suavemente."""
        if not self.mini_hud_box.has_css_class("visible"):
            self.mini_hud_box.add_css_class("visible")
        if not self.super_hud_box.has_css_class("visible"):
            self.super_hud_box.add_css_class("visible")

    def hide_hud(self):
        """Oculta los controles HUD para dejar la portada pura."""
        if self._is_seeking:
            return
        if self.mini_hud_box.has_css_class("visible"):
            self.mini_hud_box.remove_css_class("visible")
        if self.super_hud_box.has_css_class("visible"):
            self.super_hud_box.remove_css_class("visible")

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
        """Muestra el mini-reproductor compacto (500x500)."""
        if self.is_fullscreen():
            self.unfullscreen()
        self.set_default_size(500, 500)
        self.present()
        self._apply_player_mode(is_super=False)
        self.show_hud()
        self.reset_hud_timeout(2.5)

    def present_super_player(self):
        """Muestra directamente el Super-Reproductor a pantalla completa."""
        self.fullscreen()
        self.present()
        self._apply_player_mode(is_super=True)
        self.show_hud()
        self.reset_hud_timeout(3.0)

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

        # Ficha técnica de calidad de audio
        rate_khz = track.sample_rate / 1000.0 if track.sample_rate else 44.1
        depth_str = f"{track.bits_per_sample} bits" if track.bits_per_sample > 1 else "1 bit (DSD)"
        badge_text = f"{track.format_name} • {rate_khz:g} kHz • {depth_str} • {track.formatted_bitrate}"
        self.super_badge_label.set_text(badge_text)

        self._current_duration = track.duration or 0.0
        self.mini_scale.set_range(0.0, max(1.0, self._current_duration))
        self.super_scale.set_range(0.0, max(1.0, self._current_duration))

        # Cargar carátula HD en ambas vistas
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            data, _mime = cover_info
            gbytes = GLib.Bytes.new(data)
            texture = Gdk.Texture.new_from_bytes(gbytes)
            self.mini_cover_picture.set_paintable(texture)
            self.mini_cover_stack.set_visible_child_name("picture")
            self.super_cover_picture.set_paintable(texture)
            self.super_cover_stack.set_visible_child_name("picture")
        else:
            self.mini_cover_picture.set_paintable(None)
            self.mini_cover_stack.set_visible_child_name("placeholder")
            self.super_cover_picture.set_paintable(None)
            self.super_cover_stack.set_visible_child_name("placeholder")

        # Cargar letra si estamos en pantalla completa o cuando se pase a ella
        self._load_lyrics_for_track(track)

    def _load_lyrics_for_track(self, track: AudioTrack):
        track_id = f"{track.artist}___{track.title}"
        if self._last_lyrics_track_id == track_id:
            return
        self._last_lyrics_track_id = track_id

        self.lyrics_spinner.start()
        self.lyrics_stack.set_visible_child_name("loading")
        self.lyrics_status_label.set_text(i18n.t("lyrics.loading"))

        self.lyrics_service.fetch_lyrics(track, self._on_lyrics_loaded)

    def _on_lyrics_loaded(self, lyrics: str | None, status: str):
        self.lyrics_spinner.stop()
        if status == "ready" and lyrics:
            self.super_lyrics_label.set_text(lyrics)
            self.lyrics_stack.set_visible_child_name("lyrics")
            self.lyrics_status_label.set_text(i18n.t("lyrics.source_online"))
        elif status == "instrumental":
            self.lyrics_stack.set_visible_child_name("instrumental")
            self.lyrics_status_label.set_text(i18n.t("lyrics.instrumental"))
        else:
            self.lyrics_stack.set_visible_child_name("not_found")
            self.lyrics_status_label.set_text(i18n.t("lyrics.not_found"))

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
        self.mini_scope.set_active(False)
        self.super_scope.set_active(False)
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
        except Exception:
            pass
        self.destroy()

    def _on_close_request(self, _window) -> bool:
        self.restore_main_window()
        return True
