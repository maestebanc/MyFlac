"""Panel lateral derecho: inspector de metadatos audiófilos, carátula HD y visualizadores en tiempo real."""
from __future__ import annotations

import os
from typing import Callable, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.engine import PlaybackState
from ..audio.track import AudioTrack
from ..config import load_config, save_config
from ..logger import get_logger
from ..artist_art import ArtistArtService
from ..music_info import KINDS, MusicInfoService
from ..lyrics import LyricsService, SyncedLyrics
from ..ui.visualizers import OscilloscopeWidget
from .lyrics_view import SyncedLyricsView
from .info_view import InfoView

# Pestañas de la tarjeta inferior del inspector: (nombre, clave de texto)
INFO_TABS = [("lyrics", "tabs.lyrics"), ("track", "tabs.track"), ("album", "tabs.album"), ("artist", "tabs.artist")]
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
        self.on_album_activate: Callable[[str], None] | None = None
        self.on_visualizer_mode_changed: Callable[[int], None] | None = None

        # Cargar modo visualizador persistente (0: Portada+Osciloscopio [por defecto], 1: Portada limpia)
        cfg = load_config()
        self.visualizer_mode: int = cfg.get("visualizer_mode", 0) % 2
        self._oscilloscope_enabled: bool = cfg.get("oscilloscope_enabled", True)

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
        # FILL: la tarjeta de letra ocupa el espacio que sobra bajo la ficha técnica
        content.set_valign(Gtk.Align.FILL)

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

        # Picture para la foto del artista (modo 1 del visualizador)
        self.artist_picture = Gtk.Picture()
        self.artist_picture.set_can_shrink(True)
        self.artist_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.artist_picture.set_hexpand(True)
        self.artist_picture.set_vexpand(False)
        self.cover_stack.add_named(self.artist_picture, "artist")
        self.cover_stack.set_visible_child_name("placeholder")
        self._cover_child = "placeholder"  # 'picture' o 'placeholder' según tenga carátula la pista
        self._artist_image_for: str | None = None  # artista cuya foto está cargada
        self._artist_requested: str | None = None

        self.art_overlay.set_child(self.cover_stack)

        # Osciloscopio en tiempo real superpuesto a la carátula
        self.scope_widget = OscilloscopeWidget()
        self.scope_widget.set_can_target(False)
        self.scope_widget.set_visible(False)
        self.art_overlay.add_overlay(self.scope_widget)

        self.frame_overlay.set_child(self.art_overlay)

        # Indicador de modo en la base de la carátula (cápsula con 2 puntos: Osciloscopio / Limpio)
        self.badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.badge_box.add_css_class("visualizer-pill")
        self.badge_box.set_halign(Gtk.Align.CENTER)
        self.badge_box.set_valign(Gtk.Align.END)
        self.badge_box.set_margin_bottom(8)
        self.badge_box.set_can_target(False)

        self.mode_dots = []
        for i in range(2):
            dot = Gtk.Box()
            dot.add_css_class("visualizer-dot")
            self.mode_dots.append(dot)
            self.badge_box.append(dot)

        self.frame_overlay.add_overlay(self.badge_box)

        # Gesto de clic sobre la carátula para alternar entre Osciloscopio y Portada limpia
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
        self.album_label.set_cursor_from_name("pointer")
        self.album_label.set_tooltip_text("Doble clic para reproducir este álbum")

        # Gesto de doble clic en álbum para reproducir desde la primera pista
        album_click = Gtk.GestureClick()
        album_click.connect("released", self._on_album_label_clicked)
        self.album_label.add_controller(album_click)

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

        # 4. Letra de la pista (sincronizada con la reproducción cuando es la pista que suena)
        content.append(self._build_lyrics_card())

        scrolled.set_child(content)
        self.append(scrolled)

    def _build_lyrics_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("audiophile-card")
        card.add_css_class("inspector-lyrics-card")
        card.set_vexpand(True)
        card.set_size_request(-1, 180)

        # Pestañas: letra y fichas del tema, el disco y el artista (Wikipedia y Discogs)
        self.info_tabs = Adw.ToggleGroup()
        self.info_tabs.add_css_class("inspector-info-tabs")
        self.info_tabs.set_homogeneous(True)
        self.info_tabs.set_hexpand(True)
        self._tab_toggles: dict[str, Adw.Toggle] = {}
        for name, key in INFO_TABS:
            toggle = Adw.Toggle(label=i18n.t(key), name=name)
            self._tab_toggles[name] = toggle
            self.info_tabs.add(toggle)
        card.append(self.info_tabs)

        # Estado de la letra ("Letra sincronizada"), solo en la pestaña de letra
        self.lyrics_status_label = Gtk.Label(label="", xalign=1.0)
        self.lyrics_status_label.add_css_class("dim-label")
        self.lyrics_status_label.add_css_class("caption")

        self.info_stack = Gtk.Stack()
        self.info_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.info_stack.set_vexpand(True)

        lyrics_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lyrics_page.append(self.lyrics_status_label)

        self.lyrics_stack = Gtk.Stack()
        self.lyrics_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.lyrics_stack.set_vexpand(True)

        self.lyrics_view = SyncedLyricsView("inspector-lyrics-text", width_chars=12, bottom_padding=140)
        self.lyrics_view.on_seek = self._on_lyrics_seek
        self.lyrics_view.position_provider = lambda: self._engine.position if self._engine else 0.0
        self.lyrics_stack.add_named(self.lyrics_view, "lyrics")

        self.lyrics_message = Gtk.Label(label="", xalign=0.5)
        self.lyrics_message.add_css_class("dim-label")
        self.lyrics_message.set_wrap(True)
        self.lyrics_message.set_valign(Gtk.Align.CENTER)
        self.lyrics_stack.add_named(self.lyrics_message, "message")
        self._show_lyrics_message("")

        lyrics_page.append(self.lyrics_stack)
        self.info_stack.add_named(lyrics_page, "lyrics")

        self.notes_views: dict[str, InfoView] = {}
        for kind in KINDS:
            view = InfoView()
            self.notes_views[kind] = view
            self.info_stack.add_named(view, kind)
        self._notes_loaded: dict[str, str] = {}  # pestaña -> ficha mostrada (para no repetir)

        card.append(self.info_stack)
        self._lyrics_track_key: str | None = None

        saved_tab = load_config().get("inspector_tab", "lyrics")
        self.info_tabs.set_active_name(saved_tab if saved_tab in self._tab_toggles else "lyrics")
        self.info_stack.set_visible_child_name(self.info_tabs.get_active_name())
        self.info_tabs.connect("notify::active-name", self._on_info_tab_changed)
        return card

    def _on_info_tab_changed(self, *_args):
        name = self.info_tabs.get_active_name()
        if not name:
            return
        self.info_stack.set_visible_child_name(name)
        try:
            cfg = load_config()
            cfg["inspector_tab"] = name
            save_config(cfg)
        except Exception as e:
            log.warning("No se pudo guardar la pestaña del inspector: %s", e)
        self._load_notes(name)

    def _load_notes(self, kind: str | None):
        """Carga la ficha de la pestaña visible; las demás se precargan al sonar la pista."""
        if kind not in KINDS:
            return
        view = self.notes_views[kind]
        track = self.current_track
        if track is None or not (track.artist or track.album_artist):
            self._notes_loaded.pop(kind, None)
            view.show_message(i18n.t("info.no_track"))
            return
        subject = MusicInfoService.subject_key(kind, track)
        if self._notes_loaded.get(kind) == subject:
            return
        self._notes_loaded[kind] = subject
        view.show_loading(i18n.t("info.loading"))
        MusicInfoService.get_default().fetch(
            kind, track, i18n.get_language(),
            # Si mientras tanto se mostró otra pista, el resultado ya no aplica
            lambda info, k=kind, sub=subject: self._on_info(k, info) if self._notes_loaded.get(k) == sub else None,
        )

    def _on_info(self, kind: str, info):
        view = self.notes_views[kind]
        if info.status == "ok":
            view.show_info(info)
            if info.temporary:
                # Incompleta por un fallo temporal: al volver a la pestaña se intentará completar
                self._notes_loaded.pop(kind, None)
            return
        if info.status == "empty":
            view.show_message(i18n.t("info.empty"))
            return
        self._notes_loaded.pop(kind, None)
        view.show_message(i18n.t("info.error", error=info.error))

    def _show_lyrics_message(self, text: str, status: str = ""):
        self.lyrics_message.set_text(text)
        self.lyrics_status_label.set_text(status)
        self.lyrics_stack.set_visible_child_name("message")

    def _is_playing_track(self) -> bool:
        playing = self._engine.current_track if self._engine else None
        return bool(self.current_track and playing and playing.filepath == self.current_track.filepath)

    def _load_lyrics(self, track: AudioTrack | None):
        if track is None:
            self._lyrics_track_key = None
            self.lyrics_view.clear()
            self._show_lyrics_message("")
            return
        key = LyricsService.track_key(track)
        if key == self._lyrics_track_key:
            return
        self._lyrics_track_key = key
        self.lyrics_view.clear()
        self._show_lyrics_message(i18n.t("lyrics.loading"))
        LyricsService.get_default().fetch_lyrics(
            track,
            # Si mientras tanto se mostró otra pista, el resultado ya no aplica
            lambda lyrics, status, synced, k=key: (
                self._on_lyrics_loaded(lyrics, status, synced) if self._lyrics_track_key == k else None
            ),
        )

    def _on_lyrics_loaded(self, lyrics: str | None, status: str, synced: SyncedLyrics | None):
        if status == "ready" and lyrics:
            # Sin sincronizar con otra pista: solo se sigue la letra de la que está sonando
            position = self._engine.position if self._engine and self._is_playing_track() else -1.0
            self.lyrics_view.set_content(lyrics, synced, position)
            self.lyrics_status_label.set_text(
                i18n.t("lyrics.source_synced") if synced else i18n.t("lyrics.source_online")
            )
            self.lyrics_stack.set_visible_child_name("lyrics")
        elif status == "instrumental":
            self._show_lyrics_message(i18n.t("lyrics.instrumental"))
        else:
            self._show_lyrics_message(i18n.t("lyrics.not_found"))

    def _on_position_updated(self, pos: float, _dur: float):
        if self._is_playing_track() and self.lyrics_view.get_mapped():
            self.lyrics_view.update_position(pos)

    def _on_lyrics_seek(self, position: float):
        if self._engine and self._is_playing_track():
            self._engine.seek(position)

    def _on_album_label_clicked(self, _gesture: Gtk.GestureClick, n_press: int, _x: float, _y: float):
        if n_press == 2 and self.on_album_activate and self.current_track:
            album_name = self.current_track.album
            if album_name:
                log.info("Doble clic en etiqueta de álbum del inspector: '%s'", album_name)
                self.on_album_activate(album_name)

    def cycle_visualizer_mode(self):
        """Alterna entre los 2 modos: Portada+Osciloscopio <-> Portada limpia."""
        self.visualizer_mode = (self.visualizer_mode + 1) % 2
        self._apply_visualizer_mode(self.visualizer_mode)
        try:
            cfg = load_config()
            cfg["visualizer_mode"] = self.visualizer_mode
            save_config(cfg)
        except Exception as e:
            log.warning("No se pudo guardar visualizer_mode en configuración: %s", e)
        if self.on_visualizer_mode_changed:
            self.on_visualizer_mode_changed(self.visualizer_mode)

    def set_oscilloscope_enabled(self, enabled: bool):
        """Activa o desactiva el osciloscopio externamente (desde Preferencias)."""
        self._oscilloscope_enabled = enabled
        self._apply_visualizer_mode(self.visualizer_mode)

    def set_visualizer_mode(self, mode: int):
        """Aplica un modo visualizador externamente (ej. sincronizado desde MiniPlayerWindow)."""
        mode = mode % 2
        if self.visualizer_mode != mode:
            self._apply_visualizer_mode(mode)

    def _apply_visualizer_mode(self, mode: int):
        self.visualizer_mode = mode

        # Actualizar estado de los puntos de la pastilla (2 puntos)
        for i, dot in enumerate(self.mode_dots):
            if i == mode:
                dot.add_css_class("active")
            else:
                dot.remove_css_class("active")

        # Configurar visibilidad y estado de cada modo
        is_scope = (mode == 0) and getattr(self, "_oscilloscope_enabled", True)
        if is_scope:
            # Modo 0 con osciloscopio habilitado: superpuesto (en pausa o parado, portada limpia)
            self.scope_widget.set_active(True)
            self.scope_widget.set_playing(self._is_playing)
            self.scope_widget.set_visible(self._is_playing)
        else:
            # Osciloscopio desactivado o Modo 1: oculto, portada limpia
            self.scope_widget.set_active(False)
            self.scope_widget.set_playing(False)
            self.scope_widget.set_visible(False)
        self._refresh_cover_view()

        self._update_mode_tooltip()

    def _set_cover_child(self, name: str):
        self._cover_child = name
        self._refresh_cover_view()

    def _refresh_cover_view(self):
        """Muestra la foto del artista en el modo 1 si está disponible; si no, la portada."""
        has_artist = self.artist_picture.get_paintable() is not None
        if self.visualizer_mode == 1 and has_artist:
            self.cover_stack.set_visible_child_name("artist")
        else:
            self.cover_stack.set_visible_child_name(self._cover_child)

    def _load_artist_image(self, artist: str | None):
        artist = (artist or "").strip()
        if artist == self._artist_requested:
            return
        self._artist_requested = artist
        if not artist:
            self._on_artist_image(None, "")
            return
        ArtistArtService.get_default().fetch_artist_image(
            # Si mientras tanto cambió la pista, el resultado ya no aplica
            artist, lambda path, a=artist: self._on_artist_image(path, a) if a == self._artist_requested else None
        )

    def _on_artist_image(self, path: str | None, artist: str):
        self._artist_image_for = artist if path else None
        if path:
            self.artist_picture.set_filename(path)
        else:
            self.artist_picture.set_paintable(None)
        self._refresh_cover_view()

    def _update_mode_tooltip(self):
        tooltips = [
            i18n.t("inspector.mode_scope"),
            i18n.t("inspector.mode_artist"),
        ]
        if 0 <= self.visualizer_mode < len(tooltips):
            self.cover_frame.set_tooltip_text(tooltips[self.visualizer_mode])

    def set_engine(self, engine: AudioEngine | None):
        """Conecta el motor de audio para recibir métricas de nivel y estado."""
        if self._engine:
            self._engine.remove_level_listener(self._on_audio_level)
            self._engine.remove_state_listener(self._on_playback_state_changed)
            self._engine.remove_position_listener(self._on_position_updated)
        self._engine = engine
        if self._engine:
            self._engine.add_level_listener(self._on_audio_level)
            self._engine.add_state_listener(self._on_playback_state_changed)
            self._engine.add_position_listener(self._on_position_updated)
            is_playing = (self._engine.state == PlaybackState.PLAYING)
            self._is_playing = is_playing
            is_scope = (self.visualizer_mode == 0) and getattr(self, "_oscilloscope_enabled", True)
            self.scope_widget.set_playing(is_playing and is_scope)
            self.scope_widget.set_visible(is_playing and is_scope)

    def _on_audio_level(self, rms: list[float], peak: list[float]):
        is_scope = (self.visualizer_mode == 0) and getattr(self, "_oscilloscope_enabled", True)
        if is_scope and self._is_playing:
            self.scope_widget.update_levels(rms, peak)

    def _on_playback_state_changed(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        self._is_playing = is_playing
        is_scope = (self.visualizer_mode == 0) and getattr(self, "_oscilloscope_enabled", True)
        self.scope_widget.set_playing(is_playing and is_scope)
        self.scope_widget.set_visible(is_playing and is_scope)

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
        for name, key in INFO_TABS:
            self._tab_toggles[name].set_label(i18n.t(key))
        self._notes_loaded.clear()
        self._lyrics_track_key = None  # recargar mensajes de estado en el nuevo idioma
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
            self._set_cover_child("placeholder")
            self._load_artist_image(None)
            self._load_lyrics(None)
            self._load_notes(self.info_tabs.get_active_name())
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
        self._load_lyrics(track)
        self._load_notes(self.info_tabs.get_active_name())

        # Carátula escalada con Gtk.Picture
        cover_info = track.cached_cover()
        if cover_info:
            try:
                data, _mime = cover_info
                bytes_glib = GLib.Bytes.new(data)
                texture = Gdk.Texture.new_from_bytes(bytes_glib)
                self.cover_picture.set_paintable(texture)
                self._set_cover_child("picture")
            except Exception as e:
                log.warning(f"Error cargando carátula de pista: {e}")
                self.cover_picture.set_paintable(None)
                self._set_cover_child("placeholder")
        else:
            self.cover_picture.set_paintable(None)
            self._set_cover_child("placeholder")
        self._load_artist_image(track.artist)

    def update_dac_status(self, info: dict):
        """Mantiene compatibilidad con llamadas de estado del reproductor."""
        self._last_output_info = info
