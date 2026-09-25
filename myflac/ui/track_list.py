"""Vista de lista de pistas en Gtk.ColumnView con soporte Hi-Res y Drag & Drop."""
from __future__ import annotations

import os
import random
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.track import AudioTrack, load_track
from ..constants import SUPPORTED_EXTENSIONS
from .track_item import FlacTrackItem


class TrackListView(Gtk.Box):
    def __init__(self, on_track_activate: Callable[[AudioTrack], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.on_track_activate = on_track_activate

        self.list_store = Gio.ListStore.new(FlacTrackItem)
        self.current_playing_index: int | None = None
        self._search_query: str = ""

        # Modelo de filtrado para búsqueda en vivo
        self.filter = Gtk.CustomFilter.new(self._filter_func)
        self.filter_model = Gtk.FilterListModel.new(self.list_store, self.filter)

        # Selección
        self.selection_model = Gtk.SingleSelection.new(self.filter_model)
        self.selection_model.set_autoselect(False)

        self._build_ui()
        self._setup_dnd()

    def _build_ui(self):
        # Contenedor con scroll
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # ColumnView
        self.column_view = Gtk.ColumnView(model=self.selection_model)
        self.column_view.add_css_class("track-table")
        self.column_view.connect("activate", self._on_row_activated)

        # Configurar columnas
        self._setup_columns()

        scrolled.set_child(self.column_view)
        self.append(scrolled)

        # Pie de lista (resumen de canciones, duración y calidad)
        self.footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.footer_box.set_margin_top(6)
        self.footer_box.set_margin_bottom(6)
        self.footer_box.set_margin_start(12)
        self.footer_box.set_margin_end(12)

        self.footer_info_label = Gtk.Label(label="0 pistas", xalign=0.0)
        self.footer_info_label.add_css_class("dim-label")
        self.footer_info_label.set_hexpand(True)

        self.footer_hires_summary = Gtk.Label(label="", xalign=1.0)
        self.footer_hires_summary.add_css_class("dim-label")

        self.footer_box.append(self.footer_info_label)
        self.footer_box.append(self.footer_hires_summary)
        self.append(self.footer_box)

    def _setup_columns(self):
        # 1. Columna de estado (reproduciendo)
        col_status = Gtk.ColumnViewColumn(title="")
        col_status.set_fixed_width(32)
        status_factory = Gtk.SignalListItemFactory()
        status_factory.connect("setup", self._col_status_setup)
        status_factory.connect("bind", self._col_status_bind)
        col_status.set_factory(status_factory)
        self.column_view.append_column(col_status)

        # 2. Columna # (número de pista)
        col_num = Gtk.ColumnViewColumn(title="#")
        col_num.set_fixed_width(44)
        col_num.set_resizable(False)
        num_factory = Gtk.SignalListItemFactory()
        num_factory.connect("setup", lambda _, item: item.set_child(Gtk.Label(xalign=0.5)))
        num_factory.connect("bind", self._col_num_bind)
        col_num.set_factory(num_factory)
        self.column_view.append_column(col_num)

        # 3. Columna Título
        col_title = Gtk.ColumnViewColumn(title="Título")
        col_title.set_expand(True)
        col_title.set_resizable(True)
        title_factory = Gtk.SignalListItemFactory()
        title_factory.connect("setup", lambda _, item: item.set_child(Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)))
        title_factory.connect("bind", self._col_title_bind)
        col_title.set_factory(title_factory)
        self.column_view.append_column(col_title)

        # 4. Columna Artista
        col_artist = Gtk.ColumnViewColumn(title="Artista")
        col_artist.set_fixed_width(180)
        col_artist.set_resizable(True)
        artist_factory = Gtk.SignalListItemFactory()
        artist_factory.connect("setup", lambda _, item: item.set_child(Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)))
        artist_factory.connect("bind", lambda _, item: item.get_child().set_text(item.get_item().artist))
        col_artist.set_factory(artist_factory)
        self.column_view.append_column(col_artist)

        # 5. Columna Álbum
        col_album = Gtk.ColumnViewColumn(title="Álbum")
        col_album.set_fixed_width(200)
        col_album.set_resizable(True)
        album_factory = Gtk.SignalListItemFactory()
        album_factory.connect("setup", lambda _, item: item.set_child(Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)))
        album_factory.connect("bind", lambda _, item: item.get_child().set_text(item.get_item().album))
        col_album.set_factory(album_factory)
        self.column_view.append_column(col_album)

        # 6. Columna Duración
        col_dur = Gtk.ColumnViewColumn(title="Duración")
        col_dur.set_fixed_width(70)
        dur_factory = Gtk.SignalListItemFactory()
        dur_factory.connect("setup", lambda _, item: item.set_child(Gtk.Label(xalign=1.0)))
        dur_factory.connect("bind", lambda _, item: item.get_child().set_text(item.get_item().duration_str))
        col_dur.set_factory(dur_factory)
        self.column_view.append_column(col_dur)

        # 7. Columna Calidad Hi-Res
        col_quality = Gtk.ColumnViewColumn(title="Calidad")
        col_quality.set_fixed_width(90)
        quality_factory = Gtk.SignalListItemFactory()
        quality_factory.connect("setup", self._col_quality_setup)
        quality_factory.connect("bind", self._col_quality_bind)
        col_quality.set_factory(quality_factory)
        self.column_view.append_column(col_quality)

    def _col_status_setup(self, _factory, list_item: Gtk.ListItem):
        img = Gtk.Image()
        img.set_pixel_size(14)
        list_item.set_child(img)

    def _col_status_bind(self, _factory, list_item: Gtk.ListItem):
        img = list_item.get_child()
        item = list_item.get_item()
        if item.is_playing:
            img.set_from_icon_name("media-playback-start-symbolic")
            img.add_css_class("accent")
        else:
            img.clear()

    def _col_num_bind(self, _factory, list_item: Gtk.ListItem):
        lbl = list_item.get_child()
        item = list_item.get_item()
        lbl.set_text(item.track_number_str)
        lbl.add_css_class("track-number-cell")

    def _col_title_bind(self, _factory, list_item: Gtk.ListItem):
        lbl = list_item.get_child()
        item = list_item.get_item()
        lbl.set_text(item.title)
        if item.is_playing:
            lbl.add_css_class("row-playing")
        else:
            lbl.remove_css_class("row-playing")

    def _col_quality_setup(self, _factory, list_item: Gtk.ListItem):
        badge = Gtk.Label(xalign=0.5)
        list_item.set_child(badge)

    def _col_quality_bind(self, _factory, list_item: Gtk.ListItem):
        badge = list_item.get_child()
        item = list_item.get_item()
        badge.set_text(item.badge_text)

        badge.remove_css_class("hires-badge")
        badge.remove_css_class("hires-cd-badge")
        badge.remove_css_class("hires-dsd-badge")

        if "DSD" in item.track.format_name.upper():
            badge.add_css_class("hires-dsd-badge")
        elif item.is_hires:
            badge.add_css_class("hires-badge")
        else:
            badge.add_css_class("hires-cd-badge")

    def _on_row_activated(self, _view: Gtk.ColumnView, position: int):
        item = self.filter_model.get_item(position)
        if item:
            self.set_current_playing_track(item.track)
            self.on_track_activate(item.track)

    def _filter_func(self, item: FlacTrackItem) -> bool:
        if not self._search_query:
            return True
        q = self._search_query.lower()
        return (
            q in item.title.lower()
            or q in item.artist.lower()
            or q in item.album.lower()
        )

    def set_search_query(self, query: str):
        self._search_query = query.strip()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def add_tracks(self, tracks: list[AudioTrack], clear: bool = False):
        """Añade pistas al listado."""
        if clear:
            self.list_store.remove_all()
            self.current_playing_index = None

        new_items = [FlacTrackItem(t) for t in tracks]
        for item in new_items:
            self.list_store.append(item)

        self._update_footer()

    def set_current_playing_track(self, track: AudioTrack | None):
        """Actualiza el indicador visual de pista en reproducción."""
        target_idx = None
        for i in range(self.list_store.get_n_items()):
            item = self.list_store.get_item(i)
            if track and item.track.filepath == track.filepath:
                item.is_playing = True
                target_idx = i
            else:
                item.is_playing = False
        self.current_playing_index = target_idx

    def get_track_at_index(self, index: int) -> AudioTrack | None:
        if 0 <= index < self.list_store.get_n_items():
            return self.list_store.get_item(index).track
        return None

    def get_next_track(self, shuffle: bool = False, repeat_mode: str = "none") -> AudioTrack | None:
        n = self.list_store.get_n_items()
        if n == 0:
            return None

        if repeat_mode == "one" and self.current_playing_index is not None:
            return self.get_track_at_index(self.current_playing_index)

        if shuffle:
            idx = random.randint(0, n - 1)
            return self.get_track_at_index(idx)

        curr = self.current_playing_index if self.current_playing_index is not None else -1
        next_idx = curr + 1
        if next_idx >= n:
            if repeat_mode == "all":
                next_idx = 0
            else:
                return None
        return self.get_track_at_index(next_idx)

    def get_previous_track(self) -> AudioTrack | None:
        n = self.list_store.get_n_items()
        if n == 0:
            return None
        curr = self.current_playing_index if self.current_playing_index is not None else 0
        prev_idx = max(0, curr - 1)
        return self.get_track_at_index(prev_idx)

    def _update_footer(self):
        n = self.list_store.get_n_items()
        if n == 0:
            self.footer_info_label.set_text("0 pistas")
            self.footer_hires_summary.set_text("")
            return

        total_sec = sum(self.list_store.get_item(i).track.duration for i in range(n))
        hrs = int(total_sec // 3600)
        mins = int((total_sec % 3600) // 60)
        dur_str = f"{hrs} h {mins} min" if hrs > 0 else f"{mins} min"

        # Contar pistas Hi-Res
        hires_count = sum(1 for i in range(n) if self.list_store.get_item(i).is_hires)
        self.footer_info_label.set_text(f"{n} pistas · {dur_str}")

        if hires_count == n:
            sample_rates = {self.list_store.get_item(i).track.sample_rate for i in range(n)}
            rates_str = ", ".join(f"{r/1000:g} kHz" for r in sorted(sample_rates))
            self.footer_hires_summary.set_text(f"⭐ Álbum Hi-Res ({rates_str})")
        elif hires_count > 0:
            self.footer_hires_summary.set_text(f"⭐ {hires_count} de {n} pistas en Hi-Res")
        else:
            self.footer_hires_summary.set_text("Calidad Estándar CD")

    def _setup_dnd(self):
        actions = Gdk.DragAction.COPY | Gdk.DragAction.MOVE
        target = Gtk.DropTarget.new(Gdk.FileList, actions)
        target.connect("drop", self._on_drop_files)
        self.add_controller(target)

    def _on_drop_files(self, _target, file_list: Gdk.FileList, _x: float, _y: float) -> bool:
        paths = [f.get_path() for f in file_list.get_files() if f.get_path()]
        loaded = []
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in sorted(files):
                        if file.lower().endswith(SUPPORTED_EXTENSIONS):
                            full_p = os.path.join(root, file)
                            t = load_track(full_p)
                            if t:
                                loaded.append(t)
            elif os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
                t = load_track(path)
                if t:
                    loaded.append(t)

        if loaded:
            # Ordenar por disco y número de pista
            loaded.sort(key=lambda x: ((x.disc_number or 1) * 100000 + (x.track_number or 99999), x.filename))
            self.add_tracks(loaded, clear=False)
            return True
        return False
