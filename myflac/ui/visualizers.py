import math
import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk


class OscilloscopeWidget(Gtk.DrawingArea):
    """Visualizador de osciloscopio CRT audiófilo superpuesto a la carátula."""

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)

        self._active: bool = False
        self._is_playing: bool = False
        self._tick_id: int | None = None

        self._phase: float = 0.0
        self._amplitude: float = 0.0
        self._target_amplitude: float = 0.0
        self._linear_level: float = 0.0
        self._peak_factor: float = 0.0

        self.set_draw_func(self._draw)

    def set_active(self, active: bool):
        self._active = active
        if active and self._is_playing:
            self._ensure_tick()
        else:
            self._stop_tick()
            self._amplitude = 0.0
            self._target_amplitude = 0.0
            self.queue_draw()

    def set_playing(self, is_playing: bool):
        self._is_playing = is_playing
        if not is_playing:
            self._target_amplitude = 0.0
            self._amplitude = 0.0
            self._stop_tick()
        elif self._active:
            self._ensure_tick()
        self.queue_draw()

    def update_levels(self, rms: list[float], peak: list[float]):
        if not self._active or not self._is_playing:
            return
        r_l = rms[0] if len(rms) > 0 else -100.0
        r_r = rms[1] if len(rms) > 1 else r_l
        p_l = peak[0] if len(peak) > 0 else -100.0
        p_r = peak[1] if len(peak) > 1 else p_l

        avg_rms = (r_l + r_r) / 2.0
        avg_peak = (p_l + p_r) / 2.0

        # Normalizar de dBFS (-60 a 0 dB) a rango [0.0, 1.0]
        self._linear_level = 10.0 ** (max(-60.0, min(0.0, avg_rms)) / 20.0)
        self._peak_factor = 10.0 ** (max(-60.0, min(0.0, avg_peak)) / 20.0)

        # Amplitud objetivo dinámica con impacto de transitorios
        self._target_amplitude = min(1.0, max(0.0, self._linear_level * 0.7 + self._peak_factor * 0.3))
        self._ensure_tick()

    def _ensure_tick(self):
        if self._tick_id is None and self._active:
            self._tick_id = self.add_tick_callback(self._on_tick)

    def _stop_tick(self):
        if self._tick_id is not None:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = None

    def _on_tick(self, _widget, _frame_clock) -> bool:
        if not self._active:
            self._tick_id = None
            return False

        # Suavizado de amplitud
        self._amplitude += (self._target_amplitude - self._amplitude) * 0.25

        # Progresión de fase según energía musical
        self._phase += 0.08 + 0.12 * self._amplitude

        self.queue_draw()

        # Si no se reproduce y la amplitud ya se ha extinguido, pausar el tick para 0% CPU
        if not self._is_playing and self._amplitude < 0.005 and self._target_amplitude == 0.0:
            self._amplitude = 0.0
            self._tick_id = None
            return False

        return True

    def _draw(self, _area, cr: cairo.Context, w: int, h: int):
        if not self._active or not self._is_playing or w <= 0 or h <= 0:
            return

        # 1. Fondo adaptativo: nunca tapa la carátula
        if h <= 100 and w > 120:
            # Franja inferior compacta (mini-reproductor y super-reproductor):
            # Degradado vertical que nace completamente transparente arriba para fundirse con la carátula
            grad = cairo.LinearGradient(0, 0, 0, h)
            grad.add_color_stop_rgba(0.0, 0.02, 0.03, 0.05, 0.0)
            grad.add_color_stop_rgba(0.4, 0.02, 0.03, 0.05, 0.22)
            grad.add_color_stop_rgba(1.0, 0.01, 0.02, 0.03, 0.55)
            cr.set_source(grad)
            cr.rectangle(0, 0, w, h)
            cr.fill()
        elif w <= 120 and h <= 120:
            # Mini-portada de la barra del reproductor (pequeña): velo suave para no oscurecer la carátula
            vig = cairo.RadialGradient(w / 2, h / 2, 5, w / 2, h / 2, max(w, h) * 0.72)
            vig.add_color_stop_rgba(0.0, 0.02, 0.03, 0.05, 0.18)
            vig.add_color_stop_rgba(1.0, 0.01, 0.02, 0.03, 0.42)
            cr.set_source(vig)
            cr.rectangle(0, 0, w, h)
            cr.fill()
        else:
            # Modo completo grande
            vig = cairo.RadialGradient(w / 2, h / 2, 20, w / 2, h / 2, max(w, h) * 0.72)
            vig.add_color_stop_rgba(0.0, 0.02, 0.03, 0.05, 0.50)
            vig.add_color_stop_rgba(1.0, 0.01, 0.02, 0.03, 0.82)
            cr.set_source(vig)
            cr.rectangle(0, 0, w, h)
            cr.fill()

        # 2. Retícula / eje central adaptativo
        if h > 100:
            cr.set_source_rgba(0.0, 0.85, 1.0, 0.08)
            cr.set_line_width(0.75)
            step = max(24, int(min(w, h) / 10))
            for x in range(step, w, step):
                cr.move_to(x, 0)
                cr.line_to(x, h)
            for y in range(step, h, step):
                cr.move_to(0, y)
                cr.line_to(w, y)
            cr.stroke()

            # Eje central con mayor presencia
            cr.set_source_rgba(0.0, 0.85, 1.0, 0.20)
            cr.set_line_width(1.0)
            cr.move_to(w / 2, 0)
            cr.line_to(w / 2, h)
            cr.move_to(0, h / 2)
            cr.line_to(w, h / 2)
            cr.stroke()
        else:
            # Línea base central sutil y limpia en formato compacto
            cr.set_source_rgba(0.0, 0.85, 1.0, 0.14)
            cr.set_line_width(0.75)
            cr.move_to(0, h / 2)
            cr.line_to(w, h / 2)
            cr.stroke()

        # 3. Puntos de la forma de onda optimizados (paso adaptativo ~350 puntos máx)
        step_x = max(1, w // 350)
        pts = []
        amp_scale = self._amplitude * (h * 0.35)
        for x in range(0, w + step_x, step_x):
            cx = min(x, w)
            nx = cx / float(w)
            # Envolvente sinusoidal para fundir suavemente con los bordes
            env = math.sin(nx * math.pi)
            val = (
                math.sin(nx * 10.0 * math.pi + self._phase)
                + 0.45 * math.sin(nx * 22.0 * math.pi - self._phase * 1.4)
                + 0.22 * math.cos(nx * 34.0 * math.pi + self._phase * 2.2)
            )
            y = h / 2 + env * (amp_scale * val)
            pts.append((cx, y))

        if not pts:
            return

        # Anchos de trazo escalados según el alto disponible
        glow_w = 3.5 if h <= 80 else (5.0 if h <= 120 else 7.5)
        mid_w = 1.6 if h <= 80 else (2.2 if h <= 120 else 3.0)
        core_w = 0.8 if h <= 80 else (1.0 if h <= 120 else 1.2)

        # Trazado multicapa ultra-rápido usando stroke_preserve
        cr.new_sub_path()
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(pts[0][0], pts[0][1])
        for px, py in pts[1:]:
            cr.line_to(px, py)

        # Capa 1: Resplandor cian amplio (Wide Glow)
        cr.set_source_rgba(0.0, 0.90, 1.0, 0.20)
        cr.set_line_width(glow_w)
        cr.stroke_preserve()

        # Capa 2: Resplandor medio (Medium Glow)
        cr.set_source_rgba(0.0, 0.95, 1.0, 0.60)
        cr.set_line_width(mid_w)
        cr.stroke_preserve()

        # Capa 3: Núcleo brillante ultra nítido (Crisp Core)
        cr.set_source_rgba(0.92, 1.0, 1.0, 0.95)
        cr.set_line_width(core_w)
        cr.stroke()

        # 4. HUD audiófilo solo si hay suficiente espacio
        if w >= 260 and h >= 160:
            cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(9)
            cr.set_source_rgba(0.0, 0.95, 1.0, 0.75)
            cr.move_to(14, 20)
            cr.show_text("OSC · 20Hz-48kHz · CH L+R")

