"""Navegador multicolumnas de biblioteca musical estilo iTunes (Artista -> Álbum -> Tema)."""
from __future__ import annotations

from typing import Callable

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk, Pango

from ..audio.track import AudioTrack
from ..library.db import LibraryDB
from ..logger import get_logger
from .. import i18n
from .track_list import TrackListView

log = get_logger("ui.column_browser")


class ColumnBrowserView(Gtk.Box):
    """
    Componente visual de navegación de biblioteca estilo iTunes:
    Columna 1: Artista del álbum (mostrado como 'Artista')
    Columna 2: Álbum
    Columna 3: Temas (TrackListView con calidad Hi-Res y animación de onda)
    """

    def __init__(
        self,
        db: LibraryDB,
        on_track_activate: Callable[[AudioTrack], None],
        on_play_next_queue: Callable[[AudioTrack], None] | None = None,
        on_add_to_queue: Callable[[AudioTrack], None] | None = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.db = db
        self.on_track_activate = on_track_activate
        self.on_play_next_queue = on_play_next_queue
        self.on_add_to_queue = on_add_to_queue

        self.current_artist: str = "__ALL__"
        self.current_album: str = "__ALL__"
        self.search_query: str = ""

        self._artists_data: list[tuple[str, int]] = []
        self._albums_data: list[tuple[str, str, int]] = []

        self._updating_artists_ui = False
        self._updating_albums_ui = False

        self._build_ui()
        i18n.add_language_listener(lambda *_: self.refresh_i18n())

    def _build_ui(self):
        # 1. Paned vertical principal: parte superior (navegador de columnas) | parte inferior (tabla de temas)
        self.v_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.v_paned.set_resize_start_child(False)
        self.v_paned.set_resize_end_child(True)
        self.v_paned.set_shrink_start_child(False)
        self.v_paned.set_shrink_end_child(False)
        self.v_paned.set_position(210)  # Altura cómoda inicial para artistas y álbumes

        # 2. Paned horizontal para las dos columnas superiores (Artista | Álbum)
        self.h_browser_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.h_browser_paned.add_css_class("column-browser-pane")
        self.h_browser_paned.set_resize_start_child(True)
        self.h_browser_paned.set_resize_end_child(True)

        # Columna 1: Artista
        self.artist_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.artist_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.artist_header.add_css_class("column-header-box")

        self.artist_title_label = Gtk.Label(label=i18n.t("browser.col_artist"), xalign=0.0)
        self.artist_title_label.add_css_class("column-header-title")
        self.artist_title_label.set_hexpand(True)

        self.artist_count_label = Gtk.Label(label="", xalign=1.0)
        self.artist_count_label.add_css_class("column-header-count")

        self.artist_header.append(self.artist_title_label)
        self.artist_header.append(self.artist_count_label)
        self.artist_box.append(self.artist_header)

        self.artist_scrolled = Gtk.ScrolledWindow()
        self.artist_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.artist_scrolled.set_vexpand(True)

        self.artist_listbox = Gtk.ListBox()
        self.artist_listbox.add_css_class("column-list")
        self.artist_listbox.set_show_separators(False)
        self.artist_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.artist_listbox.connect("row-selected", self._on_artist_selected)
        self.artist_listbox.connect("row-activated", self._on_artist_activated)
        self.artist_scrolled.set_child(self.artist_listbox)
        self.artist_box.append(self.artist_scrolled)

        self.h_browser_paned.set_start_child(self.artist_box)

        # Columna 2: Álbum
        self.album_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.album_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.album_header.add_css_class("column-header-box")

        self.album_title_label = Gtk.Label(label=i18n.t("browser.col_album"), xalign=0.0)
        self.album_title_label.add_css_class("column-header-title")
        self.album_title_label.set_hexpand(True)

        self.album_count_label = Gtk.Label(label="", xalign=1.0)
        self.album_count_label.add_css_class("column-header-count")

        self.album_header.append(self.album_title_label)
        self.album_header.append(self.album_count_label)
        self.album_box.append(self.album_header)

        self.album_scrolled = Gtk.ScrolledWindow()
        self.album_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.album_scrolled.set_vexpand(True)

        self.album_listbox = Gtk.ListBox()
        self.album_listbox.add_css_class("column-list")
        self.album_listbox.set_show_separators(False)
        self.album_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.album_listbox.connect("row-selected", self._on_album_selected)
        self.album_listbox.connect("row-activated", self._on_album_activated)
        self.album_scrolled.set_child(self.album_listbox)
        self.album_box.append(self.album_scrolled)

        self.h_browser_paned.set_end_child(self.album_box)

        # Columna 3 / Vista Inferior: Tabla de pistas
        self.track_list = TrackListView(
            on_track_activate=self.on_track_activate,
            on_play_next_queue=self.on_play_next_queue,
            on_add_to_queue=self.on_add_to_queue,
        )

        self.v_paned.set_start_child(self.h_browser_paned)
        self.v_paned.set_end_child(self.track_list)

        self.append(self.v_paned)

    # -------------------------------------------------------------------------
    # Carga de datos y filtrado
    # -------------------------------------------------------------------------
    def load_initial_data(self):
        """Carga la colección completa desde la base de datos de manera instantánea."""
        self.current_artist = "__ALL__"
        self.current_album = "__ALL__"
        self.refresh_artists()
        self.refresh_albums()
        self.refresh_tracks()

    def refresh_artists(self):
        self._updating_artists_ui = True
        try:
            self._artists_data = self.db.get_artists(search_query=self.search_query)

            # Limpiar filas anteriores
            while True:
                row = self.artist_listbox.get_row_at_index(0)
                if row is None:
                    break
                self.artist_listbox.remove(row)

            # Fila especial: (Todos)
            total_tracks = sum(count for _, count in self._artists_data)
            all_text = i18n.t("browser.all_artists", count=len(self._artists_data))
            row_all = self._create_browser_row(all_text, total_tracks, is_all=True)
            self.artist_listbox.append(row_all)

            # Filas de artistas
            selected_row = row_all
            for idx, (artist_name, count) in enumerate(self._artists_data):
                row = self._create_browser_row(artist_name, count)
                self.artist_listbox.append(row)
                if self.current_artist == artist_name:
                    selected_row = row

            self.artist_count_label.set_text(f"{len(self._artists_data)}")
            self.artist_listbox.select_row(selected_row)
        finally:
            self._updating_artists_ui = False

    def refresh_albums(self):
        self._updating_albums_ui = True
        try:
            self._albums_data = self.db.get_albums(
                artist_filter=self.current_artist,
                search_query=self.search_query,
            )

            # Limpiar filas anteriores
            while True:
                row = self.album_listbox.get_row_at_index(0)
                if row is None:
                    break
                self.album_listbox.remove(row)

            # Fila especial: (Todos)
            total_tracks = sum(count for _, _, count in self._albums_data)
            all_text = i18n.t("browser.all_albums", count=len(self._albums_data))
            row_all = self._create_browser_row(all_text, total_tracks, is_all=True)
            self.album_listbox.append(row_all)

            # Filas de álbumes
            selected_row = row_all
            for album_name, year, count in self._albums_data:
                label_text = f"{album_name} ({year})" if year else album_name
                row = self._create_browser_row(label_text, count)
                self.album_listbox.append(row)
                if self.current_album == album_name:
                    selected_row = row

            self.album_count_label.set_text(f"{len(self._albums_data)}")
            self.album_listbox.select_row(selected_row)
        finally:
            self._updating_albums_ui = False

    def refresh_tracks(self):
        tracks = self.db.get_tracks(
            artist_filter=self.current_artist,
            album_filter=self.current_album,
            search_query=self.search_query,
        )
        self.track_list.add_tracks(tracks, clear=True)

    def _create_browser_row(self, title: str, count: int, is_all: bool = False) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("browser-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        lbl = Gtk.Label(label=title, xalign=0.0)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_hexpand(True)
        if is_all:
            lbl.add_css_class("heading")

        badge = Gtk.Label(label=str(count), xalign=1.0)
        badge.add_css_class("count-badge")

        box.append(lbl)
        box.append(badge)
        row.set_child(box)
        return row

    # -------------------------------------------------------------------------
    # Manejadores de eventos de selección
    # -------------------------------------------------------------------------
    def _on_artist_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        if self._updating_artists_ui or row is None:
            return

        idx = row.get_index()
        if idx <= 0 or idx > len(self._artists_data):
            self.current_artist = "__ALL__"
        else:
            self.current_artist = self._artists_data[idx - 1][0]

        log.debug("Artista seleccionado en navegador: %s", self.current_artist)
        self.current_album = "__ALL__"
        self.refresh_albums()
        self.refresh_tracks()

    def _on_album_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        if self._updating_albums_ui or row is None:
            return

        idx = row.get_index()
        if idx <= 0 or idx > len(self._albums_data):
            self.current_album = "__ALL__"
        else:
            self.current_album = self._albums_data[idx - 1][0]

        log.debug("Álbum seleccionado en navegador: %s", self.current_album)
        self.refresh_tracks()

    def _on_artist_activated(self, box: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        if row is None:
            return
        self._on_artist_selected(box, row)
        first_track = self.track_list.get_first_track()
        if first_track and self.on_track_activate:
            log.info("Doble clic en artista '%s': reproduciendo primera pista '%s'", self.current_artist, first_track.title)
            self.on_track_activate(first_track)

    def _on_album_activated(self, box: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        if row is None:
            return
        self._on_album_selected(box, row)
        first_track = self.track_list.get_first_track()
        if first_track and self.on_track_activate:
            log.info("Doble clic en álbum '%s': reproduciendo primera pista '%s'", self.current_album, first_track.title)
            self.on_track_activate(first_track)

    def select_album_and_play(self, album_name: str):
        """Selecciona un álbum específico y reproduce inmediatamente su primera canción."""
        if not album_name:
            return
        # 1. Buscar en la lista de álbumes actual
        for idx, (alb, _, _) in enumerate(self._albums_data):
            if alb.lower() == album_name.lower():
                row = self.album_listbox.get_row_at_index(idx + 1)
                if row:
                    self.album_listbox.select_row(row)
                    self._on_album_activated(self.album_listbox, row)
                    return

        # 2. Si no está en el filtro de artista actual, restablecer a Todos y buscar
        self.current_artist = "__ALL__"
        self.refresh_albums()
        for idx, (alb, _, _) in enumerate(self._albums_data):
            if alb.lower() == album_name.lower():
                row = self.album_listbox.get_row_at_index(idx + 1)
                if row:
                    self.album_listbox.select_row(row)
                    self._on_album_activated(self.album_listbox, row)
                    return

    # -------------------------------------------------------------------------
    # Búsqueda e Internacionalización
    # -------------------------------------------------------------------------
    def set_search_query(self, query: str):
        self.search_query = query.strip()
        self.refresh_artists()
        self.refresh_albums()
        self.refresh_tracks()

    def refresh_i18n(self):
        self.artist_title_label.set_text(i18n.t("browser.col_artist"))
        self.album_title_label.set_text(i18n.t("browser.col_album"))
        self.refresh_artists()
        self.refresh_albums()

    # -------------------------------------------------------------------------
    # Métodos delegados a TrackListView para compatibilidad con MainWindow
    # -------------------------------------------------------------------------
    def get_selected_or_first_track(self) -> AudioTrack | None:
        return self.track_list.get_selected_or_first_track()

    def get_next_track(self, shuffle: bool = False, repeat_mode: str = "none") -> AudioTrack | None:
        return self.track_list.get_next_track(shuffle=shuffle, repeat_mode=repeat_mode)

    def get_previous_track(self) -> AudioTrack | None:
        return self.track_list.get_previous_track()

    def set_current_playing_track(self, track: AudioTrack | None, is_paused: bool = False):
        self.track_list.set_current_playing_track(track, is_paused=is_paused)

    def update_playback_state(self, is_playing: bool, is_paused: bool = False):
        self.track_list.update_playback_state(is_playing=is_playing, is_paused=is_paused)
