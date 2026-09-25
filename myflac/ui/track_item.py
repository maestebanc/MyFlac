"""Envoltorio GObject de AudioTrack para Gio.ListStore y Gtk.ColumnView en MyFlac."""
from __future__ import annotations

import gi

gi.require_version("GObject", "2.0")
from gi.repository import GObject

from ..audio.track import AudioTrack


class FlacTrackItem(GObject.Object):
    __gtype_name__ = "MyFlacTrackItem"

    def __init__(self, track: AudioTrack):
        super().__init__()
        self.track = track
        self._is_playing: bool = False
        self._is_paused: bool = False

    @GObject.Property(type=str)
    def title(self) -> str:
        return self.track.title or self.track.filename

    @GObject.Property(type=str)
    def artist(self) -> str:
        return self.track.artist or self.track.album_artist or "Desconocido"

    @GObject.Property(type=str)
    def album(self) -> str:
        return self.track.album or "Álbum desconocido"

    @GObject.Property(type=str)
    def duration_str(self) -> str:
        return self.track.formatted_duration

    @GObject.Property(type=str)
    def track_number_str(self) -> str:
        if self.track.track_number is not None:
            return f"{self.track.track_number:02d}"
        return ""

    @GObject.Property(type=int)
    def track_order_key(self) -> int:
        disc = self.track.disc_number or 1
        num = self.track.track_number or 99999
        return disc * 100000 + num

    @GObject.Property(type=str)
    def badge_text(self) -> str:
        return self.track.badge_text

    @GObject.Property(type=bool, default=False)
    def is_hires(self) -> bool:
        return self.track.is_hires

    @GObject.Property(type=bool, default=False)
    def is_playing(self) -> bool:
        return self._is_playing

    @is_playing.setter
    def is_playing(self, val: bool):
        if self._is_playing != val:
            self._is_playing = val
            self.notify("is-playing")

    @GObject.Property(type=bool, default=False)
    def is_paused(self) -> bool:
        return self._is_paused

    @is_paused.setter
    def is_paused(self, val: bool):
        if self._is_paused != val:
            self._is_paused = val
            self.notify("is-paused")
