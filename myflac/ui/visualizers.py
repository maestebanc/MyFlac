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
        if active:
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
        if self._active and is_playing:
            self._ensure_tick()

    def update_levels(self, rms: list[float], peak: list[float]):
        if not self._active:
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
        if not self._active or w <= 0 or h <= 0:
            return

        # 1. Tinte oscuro semitransparente con viñeta para contraste supremo sobre la carátula
        vig = cairo.RadialGradient(w / 2, h / 2, 20, w / 2, h / 2, max(w, h) * 0.72)
        vig.add_color_stop_rgba(0.0, 0.02, 0.03, 0.05, 0.50)
        vig.add_color_stop_rgba(1.0, 0.01, 0.02, 0.03, 0.82)
        cr.set_source(vig)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # 2. Retícula milimétrica estilo osciloscopio CRT audiófilo
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

        # 3. Puntos de la forma de onda
        pts = []
        amp_scale = self._amplitude * (h * 0.34)
        for x in range(w):
            nx = x / float(w)
            # Envolvente sinusoidal para fundir suavemente con los bordes
            env = math.sin(nx * math.pi)
            val = (
                math.sin(nx * 10.0 * math.pi + self._phase)
                + 0.45 * math.sin(nx * 22.0 * math.pi - self._phase * 1.4)
                + 0.22 * math.cos(nx * 34.0 * math.pi + self._phase * 2.2)
            )
            y = h / 2 + env * (amp_scale * val)
            pts.append((x, y))

        if not pts:
            return

        # Capa 1: Resplandor cian amplio (Wide Glow)
        cr.new_sub_path()
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(0.0, 0.90, 1.0, 0.20)
        cr.set_line_width(8.0)
        cr.move_to(pts[0][0], pts[0][1])
        for px, py in pts[1:]:
            cr.line_to(px, py)
        cr.stroke()

        # Capa 2: Resplandor medio (Medium Glow)
        cr.new_sub_path()
        cr.set_source_rgba(0.0, 0.95, 1.0, 0.60)
        cr.set_line_width(3.2)
        cr.move_to(pts[0][0], pts[0][1])
        for px, py in pts[1:]:
            cr.line_to(px, py)
        cr.stroke()

        # Capa 3: Núcleo brillante ultra nítido (Crisp Core)
        cr.new_sub_path()
        cr.set_source_rgba(0.92, 1.0, 1.0, 0.95)
        cr.set_line_width(1.2)
        cr.move_to(pts[0][0], pts[0][1])
        for px, py in pts[1:]:
            cr.line_to(px, py)
        cr.stroke()

        # 4. HUD audiófilo discreto en esquina superior izquierda
        cr.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(9)
        cr.set_source_rgba(0.0, 0.95, 1.0, 0.75)
        cr.move_to(14, 20)
        cr.show_text("OSC · 20Hz-48kHz · CH L+R")


class VUMeterWidget(Gtk.DrawingArea):
    """Vúmetro analógico vintage estéreo (doble aguja L/R, retroiluminación ámbar cálida)."""

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)

        self._active: bool = False
        self._is_playing: bool = False
        self._tick_id: int | None = None

        self.target_l: float = -20.0
        self.target_r: float = -20.0
        self.current_l: float = -20.0
        self.current_r: float = -20.0

        self.set_draw_func(self._draw)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._ensure_tick()
        else:
            self._stop_tick()
            self.current_l = -20.0
            self.current_r = -20.0
            self.target_l = -20.0
            self.target_r = -20.0
            self.queue_draw()

    def set_playing(self, is_playing: bool):
        self._is_playing = is_playing
        if not is_playing:
            self.target_l = -20.0
            self.target_r = -20.0
        if self._active:
            self._ensure_tick()

    def update_levels(self, rms: list[float], peak: list[float]):
        if not self._active:
            return
        r_l = rms[0] if len(rms) > 0 else -100.0
        r_r = rms[1] if len(rms) > 1 else r_l
        p_l = peak[0] if len(peak) > 0 else -100.0
        p_r = peak[1] if len(peak) > 1 else p_l

        # Calibración analógica audiófila: 0 VU = -16 dBFS
        # Mezcla ponderada de RMS (75%) y Peak (25%) para dinámica realista
        vu_l = 0.75 * r_l + 0.25 * p_l + 16.0
        vu_r = 0.75 * r_r + 0.25 * p_r + 16.0

        self.target_l = max(-20.0, min(3.0, vu_l))
        self.target_r = max(-20.0, min(3.0, vu_r))
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

        # Balística analógica IEC 60268-10:
        # Ataque rápido (subida enérgica) y decaimiento suave (resorte mecánico)
        for ch in ("l", "r"):
            tgt = getattr(self, f"target_{ch}")
            cur = getattr(self, f"current_{ch}")
            if tgt > cur:
                new_val = cur + (tgt - cur) * 0.35  # Ataque
            else:
                new_val = cur + (tgt - cur) * 0.12  # Decaimiento
            setattr(self, f"current_{ch}", new_val)

        self.queue_draw()

        # Si no se reproduce y las agujas ya reposan en -20 dB, detener tick (0% CPU)
        if (
            not self._is_playing
            and abs(self.current_l - (-20.0)) < 0.05
            and abs(self.current_r - (-20.0)) < 0.05
        ):
            self.current_l = -20.0
            self.current_r = -20.0
            self._tick_id = None
            return False

        return True

    def _draw(self, _area, cr: cairo.Context, w: int, h: int):
        if not self._active or w <= 0 or h <= 0:
            return

        # Escalar de forma proporcional respecto al lienzo de referencia 340x340
        scale = min(w / 340.0, h / 340.0)
        tx = (w - 340.0 * scale) / 2.0
        ty = (h - 340.0 * scale) / 2.0

        cr.save()
        cr.translate(tx, ty)
        cr.scale(scale, scale)

        # 1. Chasis oscuro cepillado (audiophile dark metal chassis)
        cr.set_source_rgb(0.08, 0.085, 0.095)
        cr.paint()

        # Borde exterior dorado vintage sutil
        cr.set_source_rgba(0.96, 0.62, 0.11, 0.30)
        cr.set_line_width(1.5)
        cr.rectangle(6, 6, 340 - 12, 340 - 12)
        cr.stroke()

        # 4 tornillos de precisión en las esquinas
        for sx, sy in [(16, 16), (324, 16), (16, 324), (324, 324)]:
            cr.set_source_rgba(0.20, 0.22, 0.25, 1.0)
            cr.arc(sx, sy, 4, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.40, 0.42, 0.45, 0.8)
            cr.set_line_width(0.8)
            cr.move_to(sx - 3, sy)
            cr.line_to(sx + 3, sy)
            cr.stroke()

        # Cabecera de marca
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(11)
        cr.set_source_rgba(0.96, 0.62, 0.11, 0.90)
        txt = "VINTAGE AUDIO VU METER"
        ext = cr.text_extents(txt)
        cr.move_to((340 - ext.width) / 2, 28)
        cr.show_text(txt)

        # Dibujar las dos ventanas apiladas (Izquierda arriba, Derecha abajo)
        self._draw_meter_window(cr, 38, "CHANNEL L (LEFT)", self.current_l)
        self._draw_meter_window(cr, 182, "CHANNEL R (RIGHT)", self.current_r)

        cr.restore()

    def _draw_meter_window(self, cr: cairo.Context, y_offset: int, ch_name: str, level_db: float):
        win_x, win_y = 20, y_offset
        win_w, win_h = 300, 132

        cr.save()
        cr.rectangle(win_x, win_y, win_w, win_h)
        cr.clip()

        # Fondo de la esfera: degradado ámbar cálido vintage
        pat = cairo.LinearGradient(win_x, win_y, win_x, win_y + win_h)
        pat.add_color_stop_rgba(0.0, 0.14, 0.13, 0.10, 1.0)
        pat.add_color_stop_rgba(0.4, 0.18, 0.15, 0.08, 1.0)
        pat.add_color_stop_rgba(1.0, 0.10, 0.09, 0.06, 1.0)
        cr.set_source(pat)
        cr.paint()

        # Resplandor de lámpara incandescente superior
        glow = cairo.RadialGradient(
            win_x + win_w / 2, win_y, 10, win_x + win_w / 2, win_y + 40, win_w * 0.6
        )
        glow.add_color_stop_rgba(0.0, 0.98, 0.72, 0.20, 0.35)
        glow.add_color_stop_rgba(1.0, 0.98, 0.72, 0.20, 0.0)
        cr.set_source(glow)
        cr.paint()

        # Geometría del arco
        pivot_x = win_x + win_w / 2
        pivot_y = win_y + win_h + 30
        radius = 125

        start_deg = 230.0
        zero_deg = 295.0
        end_deg = 310.0

        # Arco zona normal (-20 a 0 dB)
        cr.new_sub_path()
        cr.set_line_width(2.0)
        cr.set_source_rgba(0.95, 0.92, 0.85, 0.85)
        cr.arc(pivot_x, pivot_y, radius, math.radians(start_deg), math.radians(zero_deg))
        cr.stroke()

        # Arco zona roja de sobrecarga (0 a +3 dB)
        cr.new_sub_path()
        cr.set_line_width(2.0)
        cr.set_source_rgba(0.95, 0.25, 0.25, 0.95)
        cr.arc(pivot_x, pivot_y, radius, math.radians(zero_deg), math.radians(end_deg))
        cr.stroke()

        # Tics calibrados
        ticks = [
            (-20, 230, "-20"),
            (-10, 250, "-10"),
            (-7, 262, "-7"),
            (-5, 273, "-5"),
            (-3, 283, "-3"),
            (-1, 291, "-1"),
            (0, 295, "0"),
            (+1, 300, "+1"),
            (+2, 305, "+2"),
            (+3, 310, "+3"),
        ]
        for val, deg, lbl in ticks:
            rad = math.radians(deg)
            x1 = pivot_x + radius * math.cos(rad)
            y1 = pivot_y + radius * math.sin(rad)
            tlen = 7 if val in (-20, -10, -5, 0, +3) else 4
            x2 = pivot_x + (radius - tlen) * math.cos(rad)
            y2 = pivot_y + (radius - tlen) * math.sin(rad)

            cr.new_sub_path()
            if val >= 0:
                cr.set_source_rgba(0.95, 0.25, 0.25, 0.95)
            else:
                cr.set_source_rgba(0.95, 0.92, 0.85, 0.85)
            cr.set_line_width(1.2 if tlen == 7 else 0.8)
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

            if val in (-20, -10, -5, 0, +3):
                cr.set_font_size(8)
                tx = pivot_x + (radius - 15) * math.cos(rad)
                ty = pivot_y + (radius - 15) * math.sin(rad)
                ext = cr.text_extents(lbl)
                cr.move_to(tx - ext.width / 2, ty + ext.height / 2)
                cr.show_text(lbl)

        # Rótulo de canal
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(9)
        cr.set_source_rgba(0.96, 0.62, 0.11, 0.90)
        cr.move_to(win_x + 12, win_y + win_h - 12)
        cr.show_text(ch_name)

        # Indicador de unidades
        cr.set_font_size(8)
        cr.set_source_rgba(0.90, 0.90, 0.90, 0.60)
        vu_ext = cr.text_extents("VU · dB")
        cr.move_to(win_x + win_w - vu_ext.width - 12, win_y + win_h - 12)
        cr.show_text("VU · dB")

        # Cálculo angular de la aguja con interpolación no lineal calibrada
        clamped = max(-20.0, min(3.0, level_db))
        if clamped <= 0:
            angle_deg = start_deg + (clamped - (-20.0)) / 20.0 * (zero_deg - start_deg)
        else:
            angle_deg = zero_deg + (clamped / 3.0) * (end_deg - zero_deg)

        n_rad = math.radians(angle_deg)

        # Sombra de la aguja
        cr.new_sub_path()
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.35)
        cr.set_line_width(2.0)
        cr.move_to(pivot_x + 2, pivot_y + 2)
        cr.line_to(
            pivot_x + 2 + (radius - 2) * math.cos(n_rad),
            pivot_y + 2 + (radius - 2) * math.sin(n_rad),
        )
        cr.stroke()

        # Cuerpo de la aguja (dorado suave)
        cr.new_sub_path()
        cr.set_source_rgba(0.98, 0.78, 0.25, 0.95)
        cr.set_line_width(1.5)
        cr.move_to(pivot_x, pivot_y)
        cr.line_to(
            pivot_x + (radius - 12) * math.cos(n_rad),
            pivot_y + (radius - 12) * math.sin(n_rad),
        )
        cr.stroke()

        # Punta de la aguja en carmesí
        cr.new_sub_path()
        cr.set_source_rgba(0.95, 0.25, 0.25, 1.0)
        cr.set_line_width(1.5)
        cr.move_to(
            pivot_x + (radius - 12) * math.cos(n_rad),
            pivot_y + (radius - 12) * math.sin(n_rad),
        )
        cr.line_to(
            pivot_x + (radius - 2) * math.cos(n_rad),
            pivot_y + (radius - 2) * math.sin(n_rad),
        )
        cr.stroke()

        # Eje / buje central
        cr.new_sub_path()
        cr.set_source_rgba(0.12, 0.13, 0.15, 1.0)
        cr.arc(pivot_x, pivot_y, 14, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(0.96, 0.62, 0.11, 0.50)
        cr.set_line_width(1.0)
        cr.arc(pivot_x, pivot_y, 14, 0, 2 * math.pi)
        cr.stroke()

        cr.restore()

        # Marco biselado de la ventana
        cr.set_source_rgba(0.96, 0.62, 0.11, 0.35)
        cr.set_line_width(1.2)
        cr.rectangle(win_x, win_y, win_w, win_h)
        cr.stroke()
