"""Visor de letras sincronizadas estilo Roon, reutilizable (Super-Reproductor e inspector)."""
from __future__ import annotations

import bisect
import time
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Graphene, Gtk, Pango

from ..lyrics import SyncedLyrics

# Adelanto con el que se resalta cada línea: el ojo lee un instante antes de oír la voz
LEAD_SECONDS = 0.15
# Tras un scroll manual, el seguimiento automático de la letra se pausa este tiempo
MANUAL_SCROLL_PAUSE = 4.0
SCROLL_DURATION_MS = 450
# Un cambio de posición mayor que este entre dos actualizaciones se considera un salto (seek)
SEEK_THRESHOLD_SECONDS = 1.5
# Por encima de estas líneas de distancia, el scroll es inmediato en lugar de animado
MAX_ANIMATED_LINES = 3


class SyncedLyricsView(Gtk.ScrolledWindow):
    """
    Muestra una letra línea a línea. Con marcas de tiempo resalta la línea cantada, atenúa las
    anteriores y la mantiene centrada con scroll animado; el scroll manual pausa el seguimiento
    y un clic en una línea llama a on_seek con su tiempo. Sin marcas de tiempo, texto estático.
    """

    def __init__(self, line_css_class: str, width_chars: int = 45, bottom_padding: int = 320):
        super().__init__()
        self._line_css_class = line_css_class
        self._width_chars = width_chars
        self._bottom_padding = bottom_padding
        self.on_seek: Callable[[float], None] | None = None
        # Posición actual de la reproducción, para ponerse al día al mostrarse tras estar oculto
        self.position_provider: Callable[[], float] | None = None

        self._synced: SyncedLyrics | None = None
        self._times: list[float] = []
        self._labels: list[Gtk.Label] = []
        self._active_index = -1
        self._last_position: float | None = None
        self._manual_scroll_until = 0.0
        self._needs_recenter = False
        self._recenter_tick_id = 0

        self.add_css_class("lyrics-view")
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)
        self.set_hexpand(True)

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._box.set_margin_end(12)
        self.set_child(self._box)

        # La rueda o el touchpad pausan el seguimiento automático, como en Roon
        scroll_ctrl = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_ctrl.connect("scroll", self._on_manual_scroll)
        self.add_controller(scroll_ctrl)

        vadj = self.get_vadjustment()
        target = Adw.CallbackAnimationTarget.new(lambda value: vadj.set_value(value))
        self._animation = Adw.TimedAnimation.new(self, 0.0, 0.0, SCROLL_DURATION_MS, target)
        self._animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)

        # Mientras está oculto no tiene geometría: se recoloca al mostrarse o redimensionarse
        self.connect("map", lambda *_: self._on_map())
        vadj.connect("notify::page-size", lambda *_: self._request_recenter())

    @property
    def is_synced(self) -> bool:
        return bool(self._synced)

    def clear(self):
        self.set_content("", None)

    def set_content(self, plain: str, synced: SyncedLyrics | None, position: float = 0.0):
        """Crea una etiqueta por línea; con letra sincronizada cada línea sabe cuándo se canta."""
        child = self._box.get_first_child()
        while child:
            self._box.remove(child)
            child = self._box.get_first_child()

        self._synced = synced
        self._times = [t for t, _ in synced] if synced else []
        self._labels = []
        self._active_index = -1
        self._last_position = None
        self._manual_scroll_until = 0.0

        entries = synced if synced else [(None, line) for line in plain.splitlines()] if plain else []
        for start, text in entries:
            label = Gtk.Label(label=text or ("♪" if synced else " "))
            label.add_css_class(self._line_css_class)
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.set_width_chars(self._width_chars)
            label.set_max_width_chars(self._width_chars)
            label.set_xalign(0.0)
            label.set_justify(Gtk.Justification.LEFT)
            if synced:
                label.add_css_class("lyrics-line")
                label.add_css_class("lyrics-line-upcoming")
                # Clic en una línea: saltar a ese momento de la canción
                click = Gtk.GestureClick()
                click.connect("released", lambda *_a, t=start: self._on_line_clicked(t))
                label.add_controller(click)
                label.set_cursor_from_name("pointer")
            else:
                label.set_selectable(True)
            self._box.append(label)
            self._labels.append(label)

        # Espacio final para que las últimas líneas también puedan quedar centradas
        self._box.set_margin_bottom(self._bottom_padding if synced else 0)
        self._animation.pause()
        self.get_vadjustment().set_value(0.0)
        if synced:
            self.update_position(position)

    def update_position(self, position: float):
        """Resalta la línea que se está cantando y la mantiene centrada en el panel."""
        if not self._synced:
            return

        # Un salto de posición (seek desde cualquier control) siempre recoloca la letra,
        # aunque el usuario hubiera hecho scroll manual
        seeked = self._last_position is not None and abs(position - self._last_position) > SEEK_THRESHOLD_SECONDS
        self._last_position = position
        if seeked:
            self._manual_scroll_until = 0.0

        index = bisect.bisect_right(self._times, position + LEAD_SECONDS) - 1
        if index != self._active_index:
            jump = abs(index - self._active_index) > MAX_ANIMATED_LINES
            self._active_index = index
            self._apply_line_states()
            self._scroll_to_active(animate=not (jump or seeked))
        elif seeked or self._needs_recenter:
            self._scroll_to_active(animate=False)

    def _apply_line_states(self):
        for i, label in enumerate(self._labels):
            for css in ("lyrics-line-active", "lyrics-line-past", "lyrics-line-upcoming"):
                label.remove_css_class(css)
            if i == self._active_index:
                label.add_css_class("lyrics-line-active")
            elif i < self._active_index:
                label.add_css_class("lyrics-line-past")
            else:
                label.add_css_class("lyrics-line-upcoming")

    def _on_map(self):
        if self._synced and self.position_provider:
            self.update_position(self.position_provider())
        self._request_recenter()

    def _request_recenter(self):
        if not self._synced:
            return
        self._needs_recenter = True
        self._scroll_to_active(animate=False)
        if self._needs_recenter and not self._recenter_tick_id:
            # Sin geometría todavía (y en pausa no llegan posiciones): reintentar en los próximos frames
            self._recenter_tick_id = self.add_tick_callback(self._on_recenter_tick)

    def _on_recenter_tick(self, _widget, _clock) -> bool:
        self._scroll_to_active(animate=False)
        if self._needs_recenter and self._synced:
            return True
        self._recenter_tick_id = 0
        return False

    def _scroll_to_active(self, animate: bool = True):
        if time.monotonic() < self._manual_scroll_until or not self._labels:
            return
        label = self._labels[max(self._active_index, 0)]
        ok, point = label.compute_point(self._box, Graphene.Point())
        if not ok or not self.get_mapped() or label.get_height() <= 0:
            # Aún sin geometría: se hará en cuanto el panel se muestre
            self._needs_recenter = True
            return
        self._needs_recenter = False

        vadj = self.get_vadjustment()
        page = vadj.get_page_size()
        target = point.y + label.get_height() / 2 - page * 0.4
        target = max(vadj.get_lower(), min(target, vadj.get_upper() - page))

        self._animation.pause()
        if animate:
            self._animation.set_value_from(vadj.get_value())
            self._animation.set_value_to(target)
            self._animation.play()
        else:
            vadj.set_value(target)

    def _on_manual_scroll(self, *_args) -> bool:
        if self._synced:
            self._manual_scroll_until = time.monotonic() + MANUAL_SCROLL_PAUSE
            self._animation.pause()
        return False

    def _on_line_clicked(self, start: float):
        self._manual_scroll_until = 0.0
        if self.on_seek:
            self.on_seek(start)
