"""Barra inferior de controles de reproducción para MyFlac."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..audio.engine import AudioEngine, PlaybackState
from ..audio.track import AudioTrack


class PlayerBar(Gtk.Box):
    def __init__(self, engine: AudioEngine, on_device_click: Callable[[], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("player-bar")
        self.engine = engine
        self.on_device_click = on_device_click

        self._is_seeking = False
        self._current_duration = 0.0

        # Callbacks
        self.on_previous_clicked: Callable[[], None] | None = None
        self.on_next_clicked: Callable[[], None] | None = None
        self.on_shuffle_toggled: Callable[[bool], None] | None = None
        self.on_repeat_clicked: Callable[[], None] | None = None
        self.on_bitperfect_toggled: Callable[[], None] | None = None

        self._build_ui()
        self._connect_engine()

    def _build_ui(self):
        # ==========================================
        # 1. IZQUIERDA: Mini carátula + Título / Artista
        # ==========================================
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left_box.set_size_request(260, -1)
        left_box.set_hexpand(False)

        # Marco con overflow oculto para miniatura perfectamente encajada
        self.cover_frame = Gtk.Box()
        self.cover_frame.add_css_class("album-cover-frame")
        self.cover_frame.set_size_request(44, 44)
        self.cover_frame.set_overflow(Gtk.Overflow.HIDDEN)

        self.cover_stack = Gtk.Stack()
        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_size_request(44, 44)
        self.cover_stack.add_named(self.cover_picture, "picture")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_size_request(44, 44)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon.set_pixel_size(24)
        placeholder.append(icon)
        self.cover_stack.add_named(placeholder, "placeholder")
        self.cover_stack.set_visible_child_name("placeholder")

        self.cover_frame.append(self.cover_stack)
        left_box.append(self.cover_frame)

        # Textos de pista
        track_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        track_info_box.set_valign(Gtk.Align.CENTER)

        self.title_label = Gtk.Label(label="Sin reproducción", xalign=0.0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.add_css_class("heading")
        self.title_label.set_max_width_chars(24)

        sub_info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.artist_label = Gtk.Label(label="", xalign=0.0)
        self.artist_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_label.add_css_class("dim-label")
        self.artist_label.set_max_width_chars(18)

        self.hires_badge_label = Gtk.Label(label="")
        self.hires_badge_label.set_visible(False)

        sub_info_box.append(self.artist_label)
        sub_info_box.append(self.hires_badge_label)

        track_info_box.append(self.title_label)
        track_info_box.append(sub_info_box)
        left_box.append(track_info_box)

        self.append(left_box)

        # ==========================================
        # 2. CENTRO: Botones de transporte y barra de tiempo
        # ==========================================
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        center_box.set_hexpand(True)
        center_box.set_halign(Gtk.Align.CENTER)
        center_box.set_size_request(480, -1)

        # Botones de control
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls_box.set_halign(Gtk.Align.CENTER)

        self.shuffle_btn = Gtk.ToggleButton()
        self.shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.shuffle_btn.set_tooltip_text("Modo aleatorio")
        self.shuffle_btn.add_css_class("flat")
        self.shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        controls_box.append(self.shuffle_btn)

        self.prev_btn = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.prev_btn.set_tooltip_text("Pista anterior")
        self.prev_btn.add_css_class("flat")
        self.prev_btn.connect("clicked", lambda *_: self.on_previous_clicked and self.on_previous_clicked())
        controls_box.append(self.prev_btn)

        self.play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.play_btn.set_tooltip_text("Reproducir / Pausa (Espacio)")
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.add_css_class("play-pause-btn")
        self.play_btn.connect("clicked", lambda *_: self.engine.toggle_play_pause())
        controls_box.append(self.play_btn)

        self.next_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.next_btn.set_tooltip_text("Siguiente pista")
        self.next_btn.add_css_class("flat")
        self.next_btn.connect("clicked", lambda *_: self.on_next_clicked and self.on_next_clicked())
        controls_box.append(self.next_btn)

        self.repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.repeat_btn.set_tooltip_text("Repetir lista / pista")
        self.repeat_btn.add_css_class("flat")
        self.repeat_btn.connect("clicked", lambda *_: self.on_repeat_clicked and self.on_repeat_clicked())
        controls_box.append(self.repeat_btn)

        center_box.append(controls_box)

        # Barra de progreso y tiempos
        seek_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seek_box.set_valign(Gtk.Align.CENTER)

        self.elapsed_label = Gtk.Label(label="0:00")
        self.elapsed_label.add_css_class("time-label")

        self.seek_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.seek_scale.set_hexpand(True)
        self.seek_scale.set_draw_value(False)
        self.seek_scale.connect("change-value", self._on_seek_change_value)

        self.duration_label = Gtk.Label(label="0:00")
        self.duration_label.add_css_class("time-label")

        seek_box.append(self.elapsed_label)
        seek_box.append(self.seek_scale)
        seek_box.append(self.duration_label)

        center_box.append(seek_box)
        self.append(center_box)

        # ==========================================
        # 3. DERECHA: Botón Interactivo Bit-Perfect + DAC + Volumen
        # ==========================================
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right_box.set_size_request(290, -1)
        right_box.set_halign(Gtk.Align.END)
        right_box.set_valign(Gtk.Align.CENTER)

        # Botón interactivo de transporte Bit-Perfect (clic para activar/desactivar)
        self.bitperfect_btn = Gtk.Button(label="⚡ BIT-PERFECT")
        self.bitperfect_btn.add_css_class("flat")
        self.bitperfect_btn.add_css_class("bitperfect-pill-btn")
        self.bitperfect_btn.add_css_class("bitperfect-pill-active")
        self.bitperfect_btn.set_tooltip_text("Haz clic para alternar entre Modo Exclusivo Bit-Perfect y Modo Compartido")
        self.bitperfect_btn.connect("clicked", lambda *_: self.on_bitperfect_toggled and self.on_bitperfect_toggled())
        right_box.append(self.bitperfect_btn)

        # Botón selector de dispositivo DAC
        self.device_btn = Gtk.Button()
        self.device_btn.add_css_class("flat")
        self.device_btn.add_css_class("device-select-btn")
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.device_icon = Gtk.Image.new_from_icon_name("audio-card-symbolic")
        self.device_label = Gtk.Label(label="DAC...")
        self.device_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.device_label.set_max_width_chars(14)
        device_box.append(self.device_icon)
        device_box.append(self.device_label)
        self.device_btn.set_child(device_box)
        self.device_btn.connect("clicked", lambda *_: self.on_device_click and self.on_device_click())
        right_box.append(self.device_btn)

        # Bloque de Volumen / Bypass
        self.vol_btn = Gtk.MenuButton()
        self.vol_btn.set_icon_name("audio-volume-high-symbolic")
        self.vol_btn.add_css_class("flat")

        # Popover de volumen
        vol_popover = Gtk.Popover()
        vol_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vol_content.set_margin_top(8)
        vol_content.set_margin_bottom(8)
        vol_content.set_margin_start(8)
        vol_content.set_margin_end(8)

        self.bypass_check = Gtk.CheckButton(label="Bypass Bit-Perfect (100% / 0 dB)")
        self.bypass_check.set_active(self.engine.volume_bypass)
        self.bypass_check.connect("toggled", self._on_bypass_toggle)
        vol_content.append(self.bypass_check)

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.vol_scale.set_value(self.engine.volume)
        self.vol_scale.set_size_request(140, -1)
        self.vol_scale.set_sensitive(not self.engine.volume_bypass)
        self.vol_scale.connect("value-changed", self._on_volume_changed)
        vol_content.append(self.vol_scale)

        vol_popover.set_child(vol_content)
        self.vol_btn.set_popover(vol_popover)
        right_box.append(self.vol_btn)

        self.append(right_box)

    def _connect_engine(self):
        self.engine.on_state_changed = self._on_state_changed
        self.engine.on_track_changed = self._on_track_changed
        self.engine.on_position_updated = self._on_position_updated
        self.engine.on_bitperfect_status = self._on_bitperfect_status

    def _on_state_changed(self, state: PlaybackState):
        if state == PlaybackState.PLAYING:
            self.play_btn.set_icon_name("media-playback-pause-symbolic")
        else:
            self.play_btn.set_icon_name("media-playback-start-symbolic")

    def _on_track_changed(self, track: AudioTrack):
        self.title_label.set_text(track.title)
        self.artist_label.set_text(track.artist or track.album or "")
        self._current_duration = track.duration
        self.duration_label.set_text(track.formatted_duration)
        self.seek_scale.set_range(0.0, max(1.0, track.duration))
        self.seek_scale.set_value(0.0)
        self.elapsed_label.set_text("0:00")

        # Actualizar badge Hi-Res
        self.hires_badge_label.set_text(track.badge_text)
        self.hires_badge_label.set_visible(True)
        self.hires_badge_label.remove_css_class("hires-badge")
        self.hires_badge_label.remove_css_class("hires-cd-badge")
        self.hires_badge_label.remove_css_class("hires-dsd-badge")

        if "DSD" in track.format_name.upper():
            self.hires_badge_label.add_css_class("hires-dsd-badge")
        elif track.is_hires:
            self.hires_badge_label.add_css_class("hires-badge")
        else:
            self.hires_badge_label.add_css_class("hires-cd-badge")

        # Mini carátula escalada
        cover_info = track.get_cover_image_bytes()
        if cover_info:
            try:
                data, _ = cover_info
                bytes_glib = GLib.Bytes.new(data)
                texture = Gdk.Texture.new_from_bytes(bytes_glib)
                self.cover_picture.set_paintable(texture)
                self.cover_stack.set_visible_child_name("picture")
            except Exception:
                self.cover_picture.set_paintable(None)
                self.cover_stack.set_visible_child_name("placeholder")
        else:
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")

    def _on_position_updated(self, pos: float, dur: float):
        if self._is_seeking:
            return
        self.seek_scale.set_value(pos)
        self.elapsed_label.set_text(self._format_sec(pos))
        if dur > 0 and self._current_duration <= 0:
            self._current_duration = dur
            self.seek_scale.set_range(0.0, dur)
            self.duration_label.set_text(self._format_sec(dur))

    def _on_seek_change_value(self, _scale, _scroll, value: float) -> bool:
        self.engine.seek(value)
        self.elapsed_label.set_text(self._format_sec(value))
        return False

    def _on_bitperfect_status(self, info: dict):
        is_bp = info.get("is_bitperfect", False)
        is_excl = info.get("is_exclusive", False)
        sink_rate = info.get("sink_rate")
        dev_name = info.get("device_name", "Desconocido")

        # Actualizar botón de dispositivo
        self.device_label.set_text(dev_name)
        self.device_btn.set_tooltip_text(f"Dispositivo activo: {dev_name} ({info.get('device_id')})")

        self.bitperfect_btn.remove_css_class("bitperfect-pill-active")
        self.bitperfect_btn.remove_css_class("bitperfect-pill-shared")
        self.bitperfect_btn.remove_css_class("bitperfect-pill-warn")

        if is_bp:
            rate_str = f"{sink_rate / 1000:g} kHz" if sink_rate else ""
            self.bitperfect_btn.set_label(f"⚡ BIT-PERFECT {rate_str}".strip())
            self.bitperfect_btn.add_css_class("bitperfect-pill-active")
            self.bitperfect_btn.set_tooltip_text(
                f"Modo Exclusivo ALSA Bit-Perfect [ACTIVO]\n"
                f"DAC: {dev_name}\n"
                f"Reloj DAC: {sink_rate} Hz\n"
                f"Formato: {info.get('sink_format')}\n\n"
                f"👉 Haz clic para desactivar (pasar a Modo Compartido)"
            )
        elif is_excl:
            self.bitperfect_btn.set_label("ALSA EXCLUSIVO")
            self.bitperfect_btn.add_css_class("bitperfect-pill-warn")
            self.bitperfect_btn.set_tooltip_text(
                f"Dispositivo exclusivo en {dev_name}, pero el volumen o formato no es bit-exact.\n"
                f"👉 Haz clic para desactivar"
            )
        else:
            self.bitperfect_btn.set_label("🔊 COMPARTIDO")
            self.bitperfect_btn.add_css_class("bitperfect-pill-shared")
            self.bitperfect_btn.set_tooltip_text(
                f"Salida de audio compartida (PipeWire/Sistema).\n"
                f"👉 Haz clic para activar el Modo Exclusivo Bit-Perfect ALSA"
            )

    def _on_shuffle_toggle(self, btn: Gtk.ToggleButton):
        if self.on_shuffle_toggled:
            self.on_shuffle_toggled(btn.get_active())

    def _on_bypass_toggle(self, btn: Gtk.CheckButton):
        active = btn.get_active()
        self.vol_scale.set_sensitive(not active)
        self.engine.set_volume_bypass(active)

    def _on_volume_changed(self, scale: Gtk.Scale):
        val = scale.get_value()
        self.engine.set_volume(val)
        if val == 0:
            self.vol_btn.set_icon_name("audio-volume-muted-symbolic")
        elif val < 0.35:
            self.vol_btn.set_icon_name("audio-volume-low-symbolic")
        elif val < 0.7:
            self.vol_btn.set_icon_name("audio-volume-medium-symbolic")
        else:
            self.vol_btn.set_icon_name("audio-volume-high-symbolic")

    def _format_sec(self, seconds: float) -> str:
        s = int(round(max(0.0, seconds)))
        m = s // 60
        sec = s % 60
        return f"{m}:{sec:02d}"
