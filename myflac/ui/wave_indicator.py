"""Widget de animación de onda de audio para la fila en reproducción en MyFlac."""
from __future__ import annotations

import math
import cairo

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk


class PlayingWaveIndicator(Gtk.DrawingArea):
    """Indicador animado tipo onda de audio puesto con buen gusto."""

    def __init__(self):
        super().__init__()
        self.set_content_width(26)
        self.set_content_height(18)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        self.set_draw_func(self._on_draw)

        self._is_playing: bool = False
        self._is_paused: bool = False
        self._tick_id: int | None = None
        self._phase: float = 0.0
        self._last_time: float = 0.0

        self.connect("unmap", lambda *_: self._stop_animation())
        self.connect("map", lambda *_: self._on_map())

    def _on_map(self):
        if self._is_playing and not self._is_paused:
            self._start_animation()

    def set_state(self, is_playing: bool, is_paused: bool):
        """Actualiza el estado de reproducción y animación del indicador."""
        changed = (self._is_playing != is_playing or self._is_paused != is_paused)
        self._is_playing = is_playing
        self._is_paused = is_paused

        if is_playing and not is_paused:
            if self.get_mapped():
                self._start_animation()
        else:
            self._stop_animation()

        if changed:
            self.queue_draw()

    def _start_animation(self):
        if self._tick_id is None:
            self._last_time = GLib.get_monotonic_time() / 1_000_000.0
            self._tick_id = self.add_tick_callback(self._on_tick)

    def _stop_animation(self):
        if self._tick_id is not None:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = None

    def _on_tick(self, _widget, _frame_clock):
        now = GLib.get_monotonic_time() / 1_000_000.0
        dt = now - self._last_time
        self._last_time = now
        if dt > 0.1:
            dt = 0.016
        self._phase += dt * 4.8
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _on_draw(self, _area, cr: cairo.Context, width: int, height: int):
        if not self._is_playing:
            return

        wave_w = 20.0
        start_x = (width - wave_w) / 2.0
        mid_y = height / 2.0

        cr.set_line_width(2.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

        # Color ámbar dorado cálido audiófilo de MyFlac (#f59e0b)
        cr.set_source_rgba(0.96, 0.62, 0.07, 0.98)

        steps = 30
        cr.new_path()
        t = self._phase if not self._is_paused else 0.0
        amp_factor = 1.0 if not self._is_paused else 0.25

        for s in range(steps + 1):
            norm = s / steps
            x = start_x + norm * wave_w
            env = math.sin(norm * math.pi) ** 1.1
            # Combinación de armónicos musicales para una onda orgánica y fluida
            w1 = math.sin(norm * 3.5 * math.pi - t)
            w2 = 0.3 * math.sin(norm * 7.0 * math.pi + t * 1.5)
            y = mid_y + (w1 + w2) * (5.5 * amp_factor) * env
            if s == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()
