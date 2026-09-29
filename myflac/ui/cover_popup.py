"""Portada a gran tamaño superpuesta a la ventana principal; un clic (o Escape) la cierra."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from ..audio.track import AudioTrack
from ..hires_cover import HiResCoverService
from ..logger import get_logger

log = get_logger("ui.cover_popup")

FADE_MS = 220
# Margen alrededor de la portada para que se vea el velo y se entienda que es una capa
MARGIN = 48


class CoverPopup(Gtk.Revealer):
    """Capa para un Gtk.Overlay: velo oscuro con la portada centrada lo más grande posible."""

    def __init__(self):
        super().__init__()
        self.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.set_transition_duration(FADE_MS)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        # Oculta no debe interceptar clics de la ventana que cubre
        self.set_visible(False)
        self.connect("notify::child-revealed", self._on_child_revealed)

        scrim = Gtk.Box()
        scrim.add_css_class("cover-popup-scrim")
        scrim.set_focusable(True)

        frame = Gtk.AspectFrame(xalign=0.5, yalign=0.5, ratio=1.0, obey_child=False)
        frame.set_hexpand(True)
        frame.set_vexpand(True)
        for side in ("top", "bottom", "start", "end"):
            getattr(frame, f"set_margin_{side}")(MARGIN)

        self._picture = Gtk.Picture()
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._picture.set_can_shrink(True)
        self._picture.add_css_class("cover-popup-art")
        self._picture.set_overflow(Gtk.Overflow.HIDDEN)
        frame.set_child(self._picture)
        scrim.append(frame)
        self.set_child(scrim)
        self._scrim = scrim

        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.close())
        scrim.add_controller(click)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        scrim.add_controller(keys)

        self.set_cursor_from_name("pointer")
        self._track: AudioTrack | None = None

    @property
    def is_open(self) -> bool:
        return self.get_reveal_child()

    def open_for_track(self, track: AudioTrack | None) -> bool:
        """
        Muestra la portada de la pista a tamaño completo. Devuelve False si no tiene portada.
        Usa la versión HD idéntica si ya está descargada; si no, la incrustada y la cambia por la HD
        en cuanto llegue (si existe).
        """
        cover = track.cached_cover() if track else None
        if not cover:
            return False
        hires = HiResCoverService.get_default()
        try:
            cached = hires.cached_path(track)
            if cached:
                texture = Gdk.Texture.new_from_filename(cached)
            else:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(cover[0]))
        except GLib.Error as e:
            log.warning("No se pudo cargar la portada para el popup: %s", e.message)
            return False
        self._track = track
        if not cached:
            hires.fetch(track, lambda path, t=track: self._on_hires_ready(path, t))
        self._picture.set_paintable(texture)
        self.set_visible(True)
        self.set_reveal_child(True)
        self._scrim.grab_focus()
        return True

    def _on_hires_ready(self, path: str | None, track: AudioTrack):
        if path and self.is_open and track is self._track:
            try:
                self._picture.set_paintable(Gdk.Texture.new_from_filename(path))
            except GLib.Error as e:
                log.warning("No se pudo cargar la portada HD %s: %s", path, e.message)

    def close(self):
        self.set_reveal_child(False)

    def _on_child_revealed(self, *_args):
        if not self.get_child_revealed() and not self.get_reveal_child():
            self.set_visible(False)
            self._picture.set_paintable(None)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False
