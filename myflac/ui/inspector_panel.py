"""Panel lateral derecho: inspector de metadatos audiófilos, carátula HD y visualizadores en tiempo real."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.engine import PlaybackState
from ..audio.track import AudioTrack
from ..config import load_config, save_config
from ..logger import get_logger
from ..ui.visualizers import OscilloscopeWidget, VUMeterWidget
from .. import i18n

if TYPE_CHECKING:
    from ..audio.engine import AudioEngine

log = get_logger(__name__)


class InspectorPanel(Gtk.Box):
    def __init__(self, engine: AudioEngine | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("inspector-panel")
        self.set_size_request(280, -1)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(10)
        self.set_margin_end(10)

        self._engine: AudioEngine | None = None
        self._is_playing: bool = False
        self.current_track: AudioTrack | None = None
        self._last_output_info: dict = {}

        # Cargar modo visualizador persistente (0: Portada, 1: Portada+Osciloscopio, 2: Vúmetro)
        cfg = load_config()
        self.visualizer_mode: int = cfg.get("visualizer_mode", 0)

        self._build_ui()
        self._apply_visualizer_mode(self.visualizer_mode)

        if engine:
            self.set_engine(engine)

        # Registrar listener para cambios dinámicos de idioma
        i18n.add_language_listener(self._on_language_changed)

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_hexpand(True)
        content.set_valign(Gtk.Align.START)

        # 1. Carátula del álbum / Visualizador interactivo 1:1
        self.aspect_frame = Gtk.AspectFrame(xalign=0.5, yalign=0.0, ratio=1.0, obey_child=False)
        self.aspect_frame.set_hexpand(True)
        self.aspect_frame.set_vexpand(False)

        self.cover_frame = Gtk.Box()
        self.cover_frame.add_css_class("album-cover-frame")
        self.cover_frame.set_hexpand(True)
        self.cover_frame.set_vexpand(False)
        self.cover_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.cover_frame.set_cursor_from_name("pointer")

        # Superposición principal del marco para contener stack y badge de estado
        self.frame_overlay = Gtk.Overlay()
        self.frame_overlay.set_hexpand(True)
        self.frame_overlay.set_vexpand(False)

        # Stack de capas principales (art_layer vs vu_layer) con crossfade suave
        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.set_transition_duration(250)
        self.main_stack.set_hexpand(True)
        self.main_stack.set_vexpand(False)

        # Capa de arte (con soporte para osciloscopio superpuesto)
        self.art_overlay = Gtk.Overlay()
        self.art_overlay.set_hexpand(True)
        self.art_overlay.set_vexpand(False)

        # Sub-stack para alternar entre imagen real del álbum y placeholder estético
        self.cover_stack = Gtk.Stack()
        self.cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.cover_stack.set_hexpand(True)
        self.cover_stack.set_vexpand(False)

        # Picture para la carátula real del álbum
        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_hexpand(True)
        self.cover_picture.set_vexpand(False)
        self.cover_stack.add_named(self.cover_picture, "picture")

        # Picture para el placeholder estético MyFlac
        self.placeholder_picture = Gtk.Picture()
        self.placeholder_picture.set_can_shrink(True)
        self.placeholder_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.placeholder_picture.set_hexpand(True)
        self.placeholder_picture.set_vexpand(False)
        self._load_placeholder_image()
        self.cover_stack.add_named(self.placeholder_picture, "placeholder")
        self.cover_stack.set_visible_child_name("placeholder")

        self.art_overlay.set_child(self.cover_stack)

        # Osciloscopio en tiempo real superpuesto a la carátula
        self.scope_widget = OscilloscopeWidget()
        self.scope_widget.set_can_target(False)
        self.scope_widget.set_visible(False)
        self.art_overlay.add_overlay(self.scope_widget)

        self.main_stack.add_named(self.art_overlay, "art_layer")

        # Vúmetro analógico vintage (doble aguja L/R, retroiluminado ámbar)
        self.vu_widget = VUMeterWidget()
        self.vu_widget.set_can_target(False)
        self.main_stack.add_named(self.vu_widget, "vu_layer")

        self.frame_overlay.set_child(self.main_stack)

        # Indicador de modo elegante en la base de la carátula (cápsula con 3 puntos)
        self.badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.badge_box.add_css_class("visualizer-pill")
        self.badge_box.set_halign(Gtk.Align.CENTER)
        self.badge_box.set_valign(Gtk.Align.END)
        self.badge_box.set_margin_bottom(8)
        self.badge_box.set_can_target(False)

        self.mode_dots = []
        for i in range(3):
            dot = Gtk.Box()
            dot.add_css_class("visualizer-dot")
            self.mode_dots.append(dot)
            self.badge_box.append(dot)

        self.frame_overlay.add_overlay(self.badge_box)

        # Gesto de clic sobre la carátula para ciclar modos interactivamente
        click_gesture = Gtk.GestureClick()
        click_gesture.connect("released", lambda *_: self.cycle_visualizer_mode())
        self.cover_frame.add_controller(click_gesture)

        self.cover_frame.append(self.frame_overlay)
        self.aspect_frame.set_child(self.cover_frame)
        content.append(self.aspect_frame)

        # 2. Resumen de la obra (Título, Artista, Álbum)
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_halign(Gtk.Align.CENTER)
        info_box.set_margin_top(2)

        self.title_label = Gtk.Label(label=i18n.t("inspector.select_track"), xalign=0.5)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.add_css_class("heading")
        self.title_label.set_max_width_chars(25)

        self.artist_label = Gtk.Label(label="", xalign=0.5)
        self.artist_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_label.add_css_class("dim-label")
        self.artist_label.set_max_width_chars(25)

        self.album_label = Gtk.Label(label="", xalign=0.5)
        self.album_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.album_label.add_css_class("dim-label")
        self.album_label.set_max_width_chars(25)

        info_box.append(self.title_label)
        info_box.append(self.artist_label)
        info_box.append(self.album_label)
        content.append(info_box)

        # 3. Ficha Técnica de Audio
        self.audiophile_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.audiophile_card.add_css_class("audiophile-card")

        self.card_title = Gtk.Label(label=i18n.t("inspector.card_title"), xalign=0.0)
        self.card_title.add_css_class("audiophile-card-title")
        self.audiophile_card.append(self.card_title)

        # Rejilla de especificaciones
        self.grid = Gtk.Grid()
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(8)

        def add_spec_row(row_idx: int, label_key: str) -> tuple[Gtk.Label, Gtk.Label]:
            lbl_name = Gtk.Label(label=i18n.t(label_key), xalign=0.0)
            lbl_name.add_css_class("dim-label")
            lbl_val = Gtk.Label(label="—", xalign=1.0)
            lbl_val.add_css_class("audiophile-stat-val")
            lbl_val.set_hexpand(True)
            self.grid.attach(lbl_name, 0, row_idx, 1, 1)
            self.grid.attach(lbl_val, 1, row_idx, 1, 1)
            return lbl_name, lbl_val

        self.lbl_format, self.val_format = add_spec_row(0, "inspector.format")
        self.lbl_rate, self.val_rate = add_spec_row(1, "inspector.sampling")
        self.lbl_depth, self.val_depth = add_spec_row(2, "inspector.resolution")
        self.lbl_channels, self.val_channels = add_spec_row(3, "inspector.channels")
        self.lbl_bitrate, self.val_bitrate = add_spec_row(4, "inspector.bitrate")
        self.lbl_size, self.val_size = add_spec_row(5, "inspector.size")

        self.audiophile_card.append(self.grid)
        content.append(self.audiophile_card)

        # Spacer vertical para evitar que los elementos se estiren cuando la ventana se maximiza
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        content.append(spacer)

        scrolled.set_child(content)
        self.append(scrolled)

    def cycle_visualizer_mode(self):
        """Alterna cíclicamente entre los 3 modos: Portada -> Portada+Osciloscopio -> Vúmetro."""
        self.visualizer_mode = (self.visualizer_mode + 1) % 3
        self._apply_visualizer_mode(self.visualizer_mode)
        try:
            cfg = load_config()
            cfg["visualizer_mode"] = self.visualizer_mode
            save_config(cfg)
        except Exception as e:
            log.warning("No se pudo guardar visualizer_mode en configuración: %s", e)

    def _apply_visualizer_mode(self, mode: int):
        self.visualizer_mode = mode

        # Actualizar estado de los puntos de la pastilla
        for i, dot in enumerate(self.mode_dots):
            if i == mode:
                dot.add_css_class("active")
            else:
                dot.remove_css_class("active")

        # Configurar visibilidad y estado de cada modo
        if mode == 0:
            # Modo 0: Portada limpia HD
            self.main_stack.set_visible_child_name("art_layer")
            self.scope_widget.set_visible(False)
            self.scope_widget.set_active(False)
            self.vu_widget.set_active(False)
        elif mode == 1:
            # Modo 1: Portada + Osciloscopio en tiempo real superpuesto
            self.main_stack.set_visible_child_name("art_layer")
            self.scope_widget.set_visible(True)
            self.scope_widget.set_active(True)
            self.scope_widget.set_playing(self._is_playing)
            self.vu_widget.set_active(False)
        elif mode == 2:
            # Modo 2: Vúmetro analógico vintage
            self.main_stack.set_visible_child_name("vu_layer")
            self.scope_widget.set_visible(False)
            self.scope_widget.set_active(False)
            self.vu_widget.set_active(True)
            self.vu_widget.set_playing(self._is_playing)

        self._update_mode_tooltip()

    def _update_mode_tooltip(self):
        tooltips = [
            i18n.t("inspector.mode_cover"),
            i18n.t("inspector.mode_scope"),
            i18n.t("inspector.mode_vu"),
        ]
        if 0 <= self.visualizer_mode < len(tooltips):
            self.cover_frame.set_tooltip_text(tooltips[self.visualizer_mode])

    def set_engine(self, engine: AudioEngine | None):
        """Conecta el motor de audio para recibir métricas de nivel y estado."""
        if self._engine:
            self._engine.remove_level_listener(self._on_audio_level)
            self._engine.remove_state_listener(self._on_playback_state_changed)
        self._engine = engine
        if self._engine:
            self._engine.add_level_listener(self._on_audio_level)
            self._engine.add_state_listener(self._on_playback_state_changed)
            is_playing = (self._engine.state == PlaybackState.PLAYING)
            self._is_playing = is_playing
            self.scope_widget.set_playing(is_playing)
            self.vu_widget.set_playing(is_playing)

    def _on_audio_level(self, rms: list[float], peak: list[float]):
        if self.visualizer_mode == 1:
            self.scope_widget.update_levels(rms, peak)
        elif self.visualizer_mode == 2:
            self.vu_widget.update_levels(rms, peak)

    def _on_playback_state_changed(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        self._is_playing = is_playing
        self.scope_widget.set_playing(is_playing)
        self.vu_widget.set_playing(is_playing)

    def _load_placeholder_image(self):
        """Carga el diseño estético de carátula MyFlac cuando no hay carátula activa."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(base_dir, "data", "placeholder-aesthetic.png"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "placeholder-aesthetic.png"),
            os.path.join(base_dir, "data", "placeholder-aesthetic.svg"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                file_obj = Gio.File.new_for_path(p)
                self.placeholder_picture.set_file(file_obj)
                break

    def _on_language_changed(self, _lang: str):
        """Actualiza todas las etiquetas estáticas al cambiar de idioma."""
        self.card_title.set_text(i18n.t("inspector.card_title"))
        self.lbl_format.set_text(i18n.t("inspector.format"))
        self.lbl_rate.set_text(i18n.t("inspector.sampling"))
        self.lbl_depth.set_text(i18n.t("inspector.resolution"))
        self.lbl_channels.set_text(i18n.t("inspector.channels"))
        self.lbl_bitrate.set_text(i18n.t("inspector.bitrate"))
        self.lbl_size.set_text(i18n.t("inspector.size"))
        self._update_mode_tooltip()

        if not self.current_track:
            self.title_label.set_text(i18n.t("inspector.select_track"))
        else:
            self.set_track(self.current_track)

    def set_track(self, track: AudioTrack | None):
        """Actualiza la vista con los metadatos de la pista."""
        self.current_track = track
        if not track:
            self.title_label.set_text(i18n.t("inspector.no_playback"))
            self.artist_label.set_text("")
            self.album_label.set_text("")
            self.val_format.set_text("—")
            self.val_rate.set_text("—")
            self.val_depth.set_text("—")
            self.val_channels.set_text("—")
            self.val_bitrate.set_text("—")
            self.val_size.set_text("—")
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")
            return

        self.title_label.set_text(track.title)
        self.artist_label.set_text(track.artist or i18n.t("inspector.unknown_artist"))
        meta_sub = track.album or i18n.t("inspector.unknown_album")
        if track.date:
            meta_sub += f" ({track.date})"
        self.album_label.set_text(meta_sub)

        # Ficha técnica de la fuente
        self.val_format.set_text(track.format_name)
        self.val_rate.set_text(f"{track.sample_rate / 1000:g} kHz")
        self.val_depth.set_text(f"{track.bits_per_sample} bits" if track.bits_per_sample > 1 else "1 bit (DSD)")
        channels_str = i18n.t("inspector.stereo") if track.channels == 2 else i18n.t("inspector.channels_n", n=track.channels)
        self.val_channels.set_text(channels_str)
        self.val_bitrate.set_text(track.formatted_bitrate)
        self.val_size.set_text(track.formatted_file_size)

        # Carátula escalada con Gtk.Picture
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            try:
                data, _mime = cover_info
                bytes_glib = GLib.Bytes.new(data)
                texture = Gdk.Texture.new_from_bytes(bytes_glib)
                self.cover_picture.set_paintable(texture)
                self.cover_stack.set_visible_child_name("picture")
            except Exception as e:
                log.warning(f"Error cargando carátula de pista: {e}")
                self.cover_picture.set_paintable(None)
                self.cover_stack.set_visible_child_name("placeholder")
        else:
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")

    def update_dac_status(self, info: dict):
        """Mantiene compatibilidad con llamadas de estado del reproductor."""
        self._last_output_info = info
