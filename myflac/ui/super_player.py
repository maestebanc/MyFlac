"""Super-Reproductor a pantalla completa: fondo ambiental, foto del artista, letras y volumen.

Se integra en MiniPlayerWindow como mixin; comparte ventana, motor y estado con el Mini-Reproductor.
"""
from __future__ import annotations

import io
import os
from PIL import Image

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..audio.track import AudioTrack
from ..logger import get_logger
from ..lyrics import SyncedLyrics
from .. import i18n
from .lyrics_view import SyncedLyricsView
from .visualizers import OscilloscopeWidget

log = get_logger("ui.super_player")



def _extract_ambient_palette(cover_bytes: bytes | None) -> tuple[str, str, str]:
    """
    Extrae dos colores atmosféricos y un color de resplandor para el marco de arte en < 2ms.
    Devuelve (rgba1, rgba2, glow_rgba).
    """
    if not cover_bytes:
        return (
            "rgba(30, 48, 80, 0.45)",
            "rgba(15, 22, 36, 0.70)",
            "rgba(56, 189, 248, 0.20)",
        )
    try:
        img = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
        img.thumbnail((32, 32), Image.Resampling.NEAREST)
        quant = img.quantize(colors=6)
        palette = quant.getpalette()[:18]
        colors = [
            (palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2])
            for i in range(len(palette) // 3)
        ]

        def vibrancy(rgb: tuple[int, int, int]) -> float:
            r, g, b = rgb
            max_c = max(r, g, b)
            min_c = min(r, g, b)
            sat = (max_c - min_c) / max(1, max_c)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            lum_factor = 1.0 - abs(lum - 128) / 128
            return sat * 1.6 + lum_factor

        colors.sort(key=vibrancy, reverse=True)
        c1 = colors[0] if colors else (30, 48, 80)
        c2 = colors[1] if len(colors) > 1 else (c1[0] // 2, c1[1] // 2, c1[2] // 2)

        # Si el color extraído es excesivamente oscuro, aportar piso de color audiófilo
        lum1 = 0.299 * c1[0] + 0.587 * c1[1] + 0.114 * c1[2]
        if lum1 < 35:
            c1 = (max(22, c1[0] + 16), max(36, c1[1] + 28), max(60, c1[2] + 48))

        rgba1 = f"rgba({c1[0]}, {c1[1]}, {c1[2]}, 0.45)"
        rgba2 = f"rgba({c2[0]}, {c2[1]}, {c2[2]}, 0.22)"
        glow = f"rgba({c1[0]}, {c1[1]}, {c1[2]}, 0.28)"
        return (rgba1, rgba2, glow)
    except Exception as e:
        log.warning("No se pudo extraer paleta atmosférica de carátula: %s", e)
        return (
            "rgba(30, 48, 80, 0.45)",
            "rgba(15, 22, 36, 0.70)",
            "rgba(56, 189, 248, 0.20)",
        )


class SuperPlayerMixin:
    """Construcción y lógica del modo Super-Reproductor de MiniPlayerWindow."""

    def _build_super_ui(self) -> Gtk.Widget:
        super_root_overlay = Gtk.Overlay()
        super_root_overlay.add_css_class("super-player-ambient-bg")
        super_root_overlay.set_hexpand(True)
        super_root_overlay.set_vexpand(True)

        # Capa de wallpaper del artista con foto HD y viñeta atenuada
        self.super_wallpaper_picture = Gtk.Picture()
        self.super_wallpaper_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.super_wallpaper_picture.set_can_shrink(True)
        self.super_wallpaper_picture.set_hexpand(True)
        self.super_wallpaper_picture.set_vexpand(True)
        self.super_wallpaper_picture.add_css_class("super-player-wallpaper-picture")
        self.super_wallpaper_picture.set_visible(False)

        super_wallpaper_scrim = Gtk.Box()
        super_wallpaper_scrim.set_hexpand(True)
        super_wallpaper_scrim.set_vexpand(True)
        super_wallpaper_scrim.add_css_class("super-player-wallpaper-scrim")

        super_bg_overlay = Gtk.Overlay()
        super_bg_overlay.set_hexpand(True)
        super_bg_overlay.set_vexpand(True)
        super_bg_overlay.set_child(self.super_wallpaper_picture)
        super_bg_overlay.add_overlay(super_wallpaper_scrim)

        super_root_overlay.set_child(super_bg_overlay)

        super_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=80)
        super_container.add_css_class("super-player-container")
        super_container.set_valign(Gtk.Align.CENTER)
        super_container.set_halign(Gtk.Align.CENTER)
        super_container.set_hexpand(True)
        super_container.set_vexpand(True)
        super_root_overlay.add_overlay(super_container)

        # Botón superior derecho de restauración como capa flotante independiente
        top_nav_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top_nav_bar.set_halign(Gtk.Align.END)
        top_nav_bar.set_valign(Gtk.Align.START)
        top_nav_bar.set_margin_top(28)
        top_nav_bar.set_margin_end(36)

        self.super_btn_restore = Gtk.Button.new_from_icon_name("view-restore-symbolic")
        self.super_btn_restore.add_css_class("super-player-btn-restore")
        self.super_btn_restore.add_css_class("flat")
        self.super_btn_restore.set_tooltip_text(i18n.t("header.unfullscreen"))
        self.super_btn_restore.connect("clicked", lambda *_: self._on_super_restore_clicked())
        top_nav_bar.append(self.super_btn_restore)
        super_root_overlay.add_overlay(top_nav_bar)

        # ---------------------------------------------------------------------
        # 2.1 Panel Izquierdo: Marco de Arte HD + Osciloscopio + Dock de Controles
        # ---------------------------------------------------------------------
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        left_box.set_valign(Gtk.Align.CENTER)
        left_box.set_halign(Gtk.Align.CENTER)

        # Marco de Carátula con bordes redondeados y sombra multicapa
        self.super_art_overlay = Gtk.Overlay()
        self.super_art_overlay.add_css_class("super-player-art-frame")
        self.super_art_overlay.set_size_request(620, 620)
        self.super_art_overlay.set_halign(Gtk.Align.CENTER)
        self.super_art_overlay.set_valign(Gtk.Align.CENTER)

        # Gesto de clic exclusivo sobre el marco de carátula para conmutar osciloscopio
        art_click = Gtk.GestureClick()
        art_click.connect("released", self._on_art_frame_clicked)
        self.super_art_overlay.add_controller(art_click)

        # Carátula en alta definición
        self.super_cover_stack = Gtk.Stack()
        self.super_cover_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.super_cover_stack.set_size_request(620, 620)

        self.super_cover_picture = Gtk.Picture()
        self.super_cover_picture.set_can_shrink(True)
        self.super_cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.super_cover_picture.set_size_request(620, 620)
        self.super_cover_stack.add_named(self.super_cover_picture, "picture")

        super_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        super_placeholder.set_valign(Gtk.Align.CENTER)
        super_placeholder.set_halign(Gtk.Align.CENTER)
        super_ph_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        super_ph_icon.set_pixel_size(160)
        super_ph_icon.set_opacity(0.35)
        super_placeholder.append(super_ph_icon)
        self.super_cover_stack.add_named(super_placeholder, "placeholder")
        self.super_artist_picture = self._make_artist_picture(620)
        self.super_cover_stack.add_named(self.super_artist_picture, "artist")
        self.super_cover_stack.set_visible_child_name("placeholder")

        self.super_art_overlay.set_child(self.super_cover_stack)

        # Osciloscopio en el super-reproductor a 60 FPS
        self.super_scope = OscilloscopeWidget()
        self.super_scope.set_size_request(620, 620)
        self.super_scope.set_active(True)
        self.super_scope.set_visible(False)
        self.super_art_overlay.add_overlay(self.super_scope)

        left_box.append(self.super_art_overlay)

        # Panel de Controles Flotante (Dock estilizado ubicado bajo la carátula)
        self.super_controls_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.super_controls_panel.add_css_class("super-player-controls-panel")
        self.super_controls_panel.set_size_request(620, -1)
        self.super_controls_panel.set_halign(Gtk.Align.CENTER)

        # Fila 1: Barra de tiempo Hi-Fi
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

        self.super_controls_panel.append(super_seek_box)

        # Fila 2: Botones de transporte principales y control de volumen
        super_transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        super_transport.set_halign(Gtk.Align.CENTER)
        super_transport.set_valign(Gtk.Align.CENTER)

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

        # Botón Play/Pause grande y resplandeciente
        self.super_btn_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.super_btn_play.add_css_class("flat")
        self.super_btn_play.add_css_class("super-player-play-btn")
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

        # Separador y control de volumen integrado
        vol_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        vol_sep.set_margin_start(10)
        vol_sep.set_margin_end(6)
        super_transport.append(vol_sep)

        self.super_vol_btn = Gtk.Button.new_from_icon_name("audio-volume-high-symbolic")
        self.super_vol_btn.add_css_class("flat")
        self.super_vol_btn.add_css_class("mini-player-aux-btn")
        self.super_vol_btn.set_tooltip_text(i18n.t("player.volume"))
        self.super_vol_btn.connect("clicked", self._on_super_vol_btn_clicked)
        super_transport.append(self.super_vol_btn)

        self.super_vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.02)
        self.super_vol_scale.add_css_class("super-player-vol-scale")
        self.super_vol_scale.set_draw_value(False)
        self.super_vol_scale.set_value(self.engine.volume)
        self.super_vol_scale.connect("value-changed", self._on_super_vol_scale_changed)
        super_transport.append(self.super_vol_scale)

        self.super_controls_panel.append(super_transport)
        left_box.append(self.super_controls_panel)

        super_container.append(left_box)

        # ---------------------------------------------------------------------
        # 2.2 Panel Derecho: Metadatos Editoriales y Letra Flotante
        # ---------------------------------------------------------------------
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right_box.set_valign(Gtk.Align.CENTER)
        right_box.set_size_request(820, 770)

        # Metadatos del tema en gran formato editorial
        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        meta_box.set_halign(Gtk.Align.FILL)

        # Insignia de Calidad Audiófila
        self.super_badge_label = Gtk.Label(label="")
        self.super_badge_label.add_css_class("super-player-hi-res-pill")
        self.super_badge_label.set_halign(Gtk.Align.START)
        meta_box.append(self.super_badge_label)

        # Título principal en negrita de gran tamaño
        self.super_title_label = Gtk.Label(label=i18n.t("inspector.no_playback"))
        self.super_title_label.add_css_class("super-player-title")
        self.super_title_label.set_halign(Gtk.Align.START)
        self.super_title_label.set_wrap(True)
        self.super_title_label.set_xalign(0.0)
        meta_box.append(self.super_title_label)

        # Artista destacado
        self.super_artist_label = Gtk.Label(label="")
        self.super_artist_label.add_css_class("super-player-artist")
        self.super_artist_label.set_halign(Gtk.Align.START)
        self.super_artist_label.set_xalign(0.0)
        meta_box.append(self.super_artist_label)

        # Álbum y fecha
        self.super_album_label = Gtk.Label(label="")
        self.super_album_label.add_css_class("super-player-album")
        self.super_album_label.set_halign(Gtk.Align.START)
        self.super_album_label.set_xalign(0.0)
        meta_box.append(self.super_album_label)

        right_box.append(meta_box)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4)
        sep.set_margin_bottom(8)
        right_box.append(sep)

        # Sección de Letras Flotantes (sin marcos toscos)
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

        right_box.append(lyrics_header_box)

        # Stack de estados de letra: 'loading', 'lyrics', 'instrumental', 'not_found'
        self.lyrics_stack = Gtk.Stack()
        self.lyrics_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.lyrics_stack.set_vexpand(True)
        self.lyrics_stack.set_hexpand(True)
        self.lyrics_stack.add_css_class("super-player-lyrics-glass-panel")

        # Estado 1: Cargando letra
        loading_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        self.lyrics_spinner = Gtk.Spinner()
        self.lyrics_spinner.set_size_request(28, 28)
        loading_box.append(self.lyrics_spinner)
        lbl_loading = Gtk.Label(label=i18n.t("lyrics.loading"))
        lbl_loading.add_css_class("dim-label")
        loading_box.append(lbl_loading)
        self.lyrics_stack.add_named(loading_box, "loading")

        # Estado 2: Letra encontrada; con marcas de tiempo sigue la canción resaltando la línea actual
        self.super_lyrics_view = SyncedLyricsView("super-player-lyrics-text", width_chars=45)
        self.super_lyrics_view.add_css_class("super-player-lyrics-scroll")
        self.super_lyrics_view.on_seek = self.engine.seek
        self.super_lyrics_view.position_provider = lambda: self.engine.position
        self.lyrics_stack.add_named(self.super_lyrics_view, "lyrics")

        # Estado 3: Pista Instrumental
        inst_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        inst_box.add_css_class("super-player-instrumental-badge")
        inst_box.set_valign(Gtk.Align.CENTER)
        inst_box.set_halign(Gtk.Align.CENTER)
        icon_inst = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon_inst.set_pixel_size(28)
        inst_box.append(icon_inst)
        lbl_inst = Gtk.Label(label=i18n.t("lyrics.instrumental"))
        inst_box.append(lbl_inst)
        self.lyrics_stack.add_named(inst_box, "instrumental")

        # Estado 4: Letra no disponible
        not_found_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
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
        right_box.append(self.lyrics_stack)

        super_container.append(right_box)
        return super_root_overlay

    def _on_super_restore_clicked(self):
        """
        Acción del único botón de restauración en el super-reproductor:
        - Si se abrió desde la ventana principal, vuelve a la ventana principal.
        - Si se abrió desde el mini-reproductor, vuelve al mini-reproductor compacto (500x500).
        """
        if self._launched_from == "main":
            self.restore_main_window()
        else:
            self.toggle_fullscreen()

    def _on_super_vol_scale_changed(self, scale: Gtk.Scale):
        val = scale.get_value()
        self.engine.set_volume(val)
        self._update_volume_icons(val)
        if hasattr(self.main_window, "player_bar") and hasattr(self.main_window.player_bar, "vol_scale"):
            self.main_window.player_bar.vol_scale.set_value(val)

    def _on_super_vol_btn_clicked(self, _btn: Gtk.Button):
        if self.engine.volume > 0.0:
            self._prev_vol = self.engine.volume
            self.super_vol_scale.set_value(0.0)
        else:
            restore_val = getattr(self, "_prev_vol", 0.8)
            self.super_vol_scale.set_value(restore_val)

    def _on_output_changed(self):
        """En modo exclusivo el volumen queda fijo a 0 dB y no se puede ajustar."""
        exclusive = self.engine.exclusive_active
        self.super_vol_btn.set_sensitive(not exclusive)
        self.super_vol_scale.set_sensitive(not exclusive)
        self.super_vol_btn.set_tooltip_text(
            i18n.t("player.volume_locked") if exclusive else i18n.t("player.volume")
        )

    def _update_volume_icons(self, val: float):
        if val <= 0.001:
            icon = "audio-volume-muted-symbolic"
        elif val < 0.33:
            icon = "audio-volume-low-symbolic"
        elif val < 0.66:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-high-symbolic"
        self.super_vol_btn.set_icon_name(icon)

    def _update_ambient_background(self, cover_bytes: bytes | None):
        """Actualiza el fondo radial de alta fidelidad y el halo del marco de arte."""
        rgba1, rgba2, glow = _extract_ambient_palette(cover_bytes)
        css = f"""
        .super-player-ambient-bg {{
            background: radial-gradient(
                circle at 26% 48%,
                {rgba1} 0%,
                {rgba2} 48%,
                #06070b 84%
            );
        }}
        .super-player-art-frame {{
            box-shadow:
                0 32px 80px -15px rgba(0, 0, 0, 0.88),
                0 0 70px -10px {glow},
                0 0 0 1px rgba(255, 255, 255, 0.12);
        }}
        """
        self._ambient_css_provider.load_from_string(css)

    def _load_artist_art_for_track(self, track: AudioTrack):
        artist_name = (track.artist or "").strip()
        if not artist_name:
            self._on_artist_image_loaded(None)
            return

        # Mismo artista que la pista anterior (con o sin foto): no repetir la búsqueda
        if self._last_artist_searched == artist_name:
            return
        self._last_artist_searched = artist_name

        self.artist_art_service.fetch_artist_image(
            artist_name,
            # Si mientras tanto cambió el artista, el resultado ya no aplica
            lambda path, artist=artist_name: (
                self._on_artist_image_loaded(path) if self._last_artist_searched == artist else None
            ),
        )

    def _on_artist_image_loaded(self, path: str | None):
        self._current_artist_image = path
        if path and os.path.isfile(path):
            self.super_wallpaper_picture.set_filename(path)
            self.super_wallpaper_picture.set_visible(True)
            # La misma foto para el modo "foto del artista" de la portada (mini y super)
            texture = self.super_wallpaper_picture.get_paintable()
            self.mini_artist_picture.set_paintable(texture)
            self.super_artist_picture.set_paintable(texture)
        else:
            self.super_wallpaper_picture.set_paintable(None)
            self.super_wallpaper_picture.set_visible(False)
            self.mini_artist_picture.set_paintable(None)
            self.super_artist_picture.set_paintable(None)
        self._refresh_player_cover_views()

    @staticmethod
    def _make_artist_picture(size: int) -> Gtk.Picture:
        picture = Gtk.Picture()
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.COVER)
        picture.set_size_request(size, size)
        return picture

    def _set_player_cover_child(self, name: str):
        """Guarda qué muestra la portada normal ('picture' o 'placeholder') y refresca las vistas."""
        self._player_cover_child = name
        self._refresh_player_cover_views()

    def _refresh_player_cover_views(self):
        """Modo 1: foto del artista si la hay; en otro caso, la portada (igual que en el inspector)."""
        if not hasattr(self, "super_artist_picture") or not hasattr(self, "mini_artist_picture"):
            return  # interfaz aún en construcción
        cover_child = getattr(self, "_player_cover_child", "placeholder")
        show_artist = self._oscilloscope_mode == 1 and self.super_artist_picture.get_paintable() is not None
        name = "artist" if show_artist else cover_child
        self.mini_cover_stack.set_visible_child_name(name)
        self.super_cover_stack.set_visible_child_name(name)

    def _load_lyrics_for_track(self, track: AudioTrack):
        track_id = self.lyrics_service.track_key(track)
        if self._last_lyrics_track_id == track_id:
            return
        self._last_lyrics_track_id = track_id

        self.lyrics_spinner.start()
        self.lyrics_stack.set_visible_child_name("loading")
        self.lyrics_status_label.set_text(i18n.t("lyrics.loading"))

        self.lyrics_service.fetch_lyrics(
            track,
            # Si mientras tanto cambió la pista, el resultado ya no aplica
            lambda lyrics, status, synced, key=track_id: (
                self._on_lyrics_loaded(lyrics, status, synced) if self._last_lyrics_track_id == key else None
            ),
        )

    def _on_lyrics_loaded(self, lyrics: str | None, status: str, synced: SyncedLyrics | None = None):
        self.lyrics_spinner.stop()
        if status == "ready" and lyrics:
            self.super_lyrics_view.set_content(lyrics, synced, self.engine.position)
            self.lyrics_stack.set_visible_child_name("lyrics")
            self.lyrics_status_label.set_text(
                i18n.t("lyrics.source_synced") if synced else i18n.t("lyrics.source_online")
            )
        elif status == "instrumental":
            self.lyrics_stack.set_visible_child_name("instrumental")
            self.lyrics_status_label.set_text(i18n.t("lyrics.instrumental"))
        else:
            self.lyrics_stack.set_visible_child_name("not_found")
            self.lyrics_status_label.set_text(i18n.t("lyrics.not_found"))
