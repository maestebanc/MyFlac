import logging
import os
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from ..audio.devices import (
    AudioDevice,
    base_node_name,
    find_device_by_id,
    get_available_devices,
    get_default_device,
)
from ..audio.engine import AudioEngine, PlaybackState
from .output_status import format_device_subtitle, output_status, volume_tooltip
from ..audio.track import AudioTrack
from .. import i18n

log = logging.getLogger(__name__)


class AdaptiveCoverFrame(Gtk.AspectFrame):
    """AspectFrame adaptativo 1:1 que ajusta su tamaño al alto de la barra

    sin imponer altura vertical propia al contenedor padre.
    """
    def __init__(self, **kwargs):
        super().__init__(ratio=1.0, obey_child=False, **kwargs)

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.VERTICAL:
            return (0, 0, -1, -1)
        else:
            if for_size > 0:
                return (for_size, for_size, -1, -1)
            return (0, 0, -1, -1)


_OUTPUT_SELECTOR_WIDTH = 236
_OUTPUT_POPOVER_WIDTH = 340


class PlayerBar(Gtk.Box):
    def __init__(self, engine: AudioEngine, on_device_click: Callable[[], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("player-bar")
        self.set_size_request(-1, 64)
        self.engine = engine
        self.on_device_click = on_device_click

        self._is_seeking = False
        self._current_duration = 0.0

        # Callbacks
        self.on_play_pause_clicked: Callable[[], None] | None = None
        self.on_previous_clicked: Callable[[], None] | None = None
        self.on_next_clicked: Callable[[], None] | None = None
        self.on_shuffle_toggled: Callable[[bool], None] | None = None
        self.on_repeat_clicked: Callable[[], None] | None = None
        self.on_queue_track_clicked: Callable[[int], None] | None = None
        self.on_queue_track_removed: Callable[[int], None] | None = None
        self.on_clear_queue_clicked: Callable[[], None] | None = None
        self.on_device_selected: Callable[[AudioDevice], None] | None = None
        self.on_device_exclusive_toggled: Callable[[AudioDevice, bool], None] | None = None
        self.is_device_exclusive_enabled_cb: Callable[[AudioDevice], bool] | None = None
        self.on_exclusive_toggled: Callable[[bool], None] | None = None
        self.on_cover_clicked: Callable[[], None] | None = None

        self._queue: list[AudioTrack] = []

        self._build_ui()
        self._connect_engine()
        self.update_active_device()
        i18n.add_language_listener(lambda *_: self.refresh_i18n())

    def _build_ui(self):
        # ==========================================
        # 1. IZQUIERDA: Mini carátula adaptativa + Título / Artista
        # ==========================================
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left_box.set_size_request(300, -1)
        left_box.set_hexpand(False)
        left_box.set_vexpand(True)
        left_box.set_valign(Gtk.Align.FILL)

        # Marco adaptativo que apura toda la altura del minireproductor (1:1)
        self.aspect_frame = AdaptiveCoverFrame(xalign=0.0, yalign=0.5)
        self.aspect_frame.set_vexpand(True)
        self.aspect_frame.set_valign(Gtk.Align.FILL)
        self.aspect_frame.set_hexpand(False)

        self.cover_frame = Gtk.Box()
        self.cover_frame.add_css_class("mini-cover-frame")
        self.cover_frame.set_vexpand(True)
        self.cover_frame.set_valign(Gtk.Align.FILL)
        self.cover_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.cover_frame.set_cursor_from_name("pointer")
        self.cover_frame.set_tooltip_text(i18n.t("player.cover_tooltip"))

        # Clic en la miniportada para verla a gran tamaño sobre la ventana principal
        cover_gesture = Gtk.GestureClick()
        cover_gesture.connect("released", lambda *_: self.on_cover_clicked and self.on_cover_clicked())
        self.cover_frame.add_controller(cover_gesture)

        self.cover_stack = Gtk.Stack()
        self.cover_stack.set_vexpand(True)
        self.cover_stack.set_valign(Gtk.Align.FILL)

        self.cover_picture = Gtk.Picture()
        self.cover_picture.set_can_shrink(True)
        self.cover_picture.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_picture.set_size_request(0, 0)
        self.cover_stack.add_named(self.cover_picture, "picture")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_vexpand(True)
        placeholder.set_valign(Gtk.Align.FILL)
        placeholder.set_halign(Gtk.Align.FILL)
        icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        icon.set_pixel_size(28)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_vexpand(True)
        placeholder.append(icon)
        self.cover_stack.add_named(placeholder, "placeholder")
        self.cover_stack.set_visible_child_name("placeholder")

        self.cover_frame.append(self.cover_stack)
        self.aspect_frame.set_child(self.cover_frame)
        left_box.append(self.aspect_frame)

        # Textos de pista
        track_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        track_info_box.set_valign(Gtk.Align.CENTER)

        self.title_label = Gtk.Label(label=i18n.t("inspector.no_playback"), xalign=0.0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.add_css_class("heading")
        self.title_label.set_max_width_chars(24)

        sub_info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.artist_label = Gtk.Label(label="", xalign=0.0)
        self.artist_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.artist_label.add_css_class("dim-label")
        self.artist_label.set_max_width_chars(20)

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
        self.shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.shuffle_btn.add_css_class("flat")
        self.shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        controls_box.append(self.shuffle_btn)

        self.prev_btn = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.prev_btn.set_tooltip_text(i18n.t("player.prev"))
        self.prev_btn.add_css_class("flat")
        self.prev_btn.connect("clicked", lambda *_: self.on_previous_clicked and self.on_previous_clicked())
        controls_box.append(self.prev_btn)

        self.play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.play_btn.set_tooltip_text(i18n.t("player.play_pause"))
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.add_css_class("play-pause-btn")
        self.play_btn.connect("clicked", lambda *_: self._handle_play_click())
        controls_box.append(self.play_btn)

        self.next_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.next_btn.set_tooltip_text(i18n.t("player.next"))
        self.next_btn.add_css_class("flat")
        self.next_btn.connect("clicked", lambda *_: self.on_next_clicked and self.on_next_clicked())
        controls_box.append(self.next_btn)

        self.repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
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
        # 3. DERECHA: Selector de Dispositivo Enriquecido + Volumen
        # ==========================================
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right_box.set_size_request(320, -1)
        right_box.set_halign(Gtk.Align.END)
        right_box.set_valign(Gtk.Align.CENTER)

        # Selector de salida: ancho fijo para que ni el botón ni el desplegable se muevan
        # según la longitud del nombre del dispositivo o el estado bit-perfect
        self.device_btn = Gtk.Button()
        self.device_btn.add_css_class("flat")
        self.device_btn.add_css_class("output-selector")
        self.device_btn.set_size_request(_OUTPUT_SELECTOR_WIDTH, -1)
        self.device_btn.set_hexpand(False)

        btn_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_content.set_valign(Gtk.Align.CENTER)

        self.device_icon = Gtk.Image.new_from_icon_name("audio-card-symbolic")
        self.device_icon.set_pixel_size(16)
        self.device_icon.add_css_class("output-icon")
        btn_content.append(self.device_icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        self.device_label = Gtk.Label(label="", xalign=0.0)
        self.device_label.add_css_class("output-name")
        self.device_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.device_label.set_max_width_chars(1)  # El ancho lo fija el botón, no el texto
        self.device_label.set_hexpand(True)
        text_box.append(self.device_label)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.output_dot = Gtk.Box()
        self.output_dot.add_css_class("output-dot")
        self.output_dot.set_valign(Gtk.Align.CENTER)
        status_box.append(self.output_dot)
        self.output_status_label = Gtk.Label(label="", xalign=0.0)
        self.output_status_label.add_css_class("output-status")
        self.output_status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.output_status_label.set_max_width_chars(1)
        self.output_status_label.set_hexpand(True)
        status_box.append(self.output_status_label)
        text_box.append(status_box)

        btn_content.append(text_box)

        self.device_chevron = Gtk.Image.new_from_icon_name("pan-up-symbolic")
        self.device_chevron.set_pixel_size(12)
        self.device_chevron.add_css_class("output-chevron")
        self.device_chevron.set_valign(Gtk.Align.CENTER)
        btn_content.append(self.device_chevron)

        self.device_btn.set_child(btn_content)

        # Popover desplegable hacia arriba para seleccionar dispositivo de audio
        self.device_popover = Gtk.Popover()
        self.device_popover.add_css_class("output-popover")
        self.device_popover.set_parent(self.device_btn)
        self.device_popover.set_position(Gtk.PositionType.TOP)
        self.device_popover.set_has_arrow(False)
        self.device_popover.set_autohide(True)
        self.device_btn.connect("clicked", self._toggle_device_popover)
        right_box.append(self.device_btn)

        # Botón de Cola de reproducción ("A continuación")
        self.queue_btn = Gtk.Button()
        self.queue_btn.add_css_class("flat")
        self.queue_btn.add_css_class("queue-btn")
        self.queue_btn.set_icon_name("view-list-bullet-symbolic")
        self.queue_btn.set_tooltip_text(i18n.t("queue.tooltip"))
        self.queue_btn.connect("clicked", self._toggle_queue_popover)
        right_box.append(self.queue_btn)

        # Popover de cola de reproducción
        self.queue_popover = Gtk.Popover()
        self.queue_popover.set_parent(self.queue_btn)
        self.queue_popover.set_has_arrow(True)
        self.queue_popover.set_position(Gtk.PositionType.TOP)

        # Bloque de Volumen deslizante
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.vol_btn = Gtk.MenuButton()
        self.vol_btn.set_icon_name("audio-volume-high-symbolic")
        self.vol_btn.add_css_class("flat")
        self.vol_btn.set_tooltip_text(i18n.t("player.volume"))

        vol_popover = Gtk.Popover()
        vol_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vol_content.set_margin_top(8)
        vol_content.set_margin_bottom(8)
        vol_content.set_margin_start(8)
        vol_content.set_margin_end(8)

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.vol_scale.set_value(self.engine.volume)
        self.vol_scale.set_size_request(140, -1)
        self.vol_scale.connect("value-changed", self._on_volume_changed)
        vol_content.append(self.vol_scale)

        vol_popover.set_child(vol_content)
        self.vol_btn.set_popover(vol_popover)
        right_box.append(self.vol_btn)

        self.append(right_box)

    def _connect_engine(self):
        self.engine.add_state_listener(self._on_state_changed)
        self.engine.on_track_changed = self._on_track_changed
        self.engine.on_position_updated = self._on_position_updated
        self.engine.add_output_listener(self.update_active_device)

    def _handle_play_click(self):
        if self.on_play_pause_clicked:
            self.on_play_pause_clicked()
        else:
            self.engine.toggle_play_pause()

    def update_active_device(self):
        """Actualiza nombre, icono y estado de transporte del selector de salida."""
        dev_id = self.engine.device_id
        found = self.engine.hw_device or find_device_by_id(dev_id)
        missing = found is None and dev_id not in ("default", "")
        dev = found or get_default_device(dev_id)
        if found is not None and dev_id not in ("default", ""):
            self._last_device_name = dev.name

        if missing:
            # La salida elegida no está publicada: el audio va a la predeterminada del sistema
            name = getattr(self, "_last_device_name", "") or dev_id
            self.device_label.set_text(name)
            self.device_icon.set_from_icon_name("dialog-warning-symbolic")
            status, level, tooltip = (i18n.t("devices.unavailable"), "warn",
                                      i18n.t("devices.wireplumber_lost", name=name))
            self.output_status_label.set_text(status)
            for cls in ("ok", "warn"):
                self.output_dot.remove_css_class(cls)
            self.output_dot.add_css_class(level)
            self.device_btn.set_tooltip_text(tooltip)
        else:
            self.device_label.set_text(dev.name)
            self.device_icon.set_from_icon_name(dev.icon_name or "audio-card-symbolic")
            self._update_output_status_line(dev)

        # En exclusivo la señal va a 0 dB: el volumen solo se ajusta si el DAC tiene control propio
        self.vol_btn.set_sensitive(self.engine.volume_adjustable)
        self.vol_btn.set_tooltip_text(volume_tooltip(self.engine))
        if self.engine.volume_adjustable:
            vol = self.engine.volume
            if abs(self.vol_scale.get_value() - vol) > 0.001:
                self.vol_scale.set_value(vol)  # Emite value-changed: actualiza el icono
            else:
                self._update_vol_icon(vol)
        else:
            self.vol_btn.set_icon_name("audio-volume-high-symbolic")

    def _update_output_status_line(self, dev: AudioDevice):
        status, level, tooltip = output_status(self.engine)
        self.output_status_label.set_text(status)
        for cls in ("ok", "warn"):
            self.output_dot.remove_css_class(cls)
        if level:
            self.output_dot.add_css_class(level)
        self.device_btn.set_tooltip_text(f"{i18n.t('player.active_device', name=dev.name)}\n{tooltip}")

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

        # Mini carátula adaptativa: textura HD nítida ajustada al marco 1:1
        cover_info = track.cached_cover()
        if cover_info:
            try:
                data, _ = cover_info
                bytes_glib = GLib.Bytes.new(data)
                texture = Gdk.Texture.new_from_bytes(bytes_glib)
                self.cover_picture.set_paintable(texture)
                self.cover_stack.set_visible_child_name("picture")
            except Exception as e:
                log.warning("Error cargando miniatura en player_bar: %s", e)
                self.cover_picture.set_paintable(None)
                self.cover_stack.set_visible_child_name("placeholder")
        else:
            self.cover_picture.set_paintable(None)
            self.cover_stack.set_visible_child_name("placeholder")

    def set_track(self, track: AudioTrack | None):
        """Permite asignar una pista activa para visualización antes de reproducir."""
        if track:
            self._on_track_changed(track)

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

    def _on_shuffle_toggle(self, btn: Gtk.ToggleButton):
        if self.on_shuffle_toggled:
            self.on_shuffle_toggled(btn.get_active())

    def _on_volume_changed(self, scale: Gtk.Scale):
        val = scale.get_value()
        self.engine.set_volume(val)
        self._update_vol_icon(val)

    def _update_vol_icon(self, val: float):
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

    def _toggle_device_popover(self, *_):
        self._rebuild_device_popover()
        self.device_popover.popup()

    def _rebuild_device_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_size_request(_OUTPUT_POPOVER_WIDTH - 24, -1)

        lbl_title = Gtk.Label(label=i18n.t("devices.popover_title"), xalign=0.0)
        lbl_title.add_css_class("output-popover-title")
        lbl_title.set_margin_start(4)
        box.append(lbl_title)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(320)

        list_box = Gtk.ListBox()
        list_box.add_css_class("boxed-list")
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)

        devices = get_available_devices()
        current_id = self.engine.device_id if self.engine else "default"
        # Mientras la tarjeta está reservada en exclusiva, PipeWire no la lista
        hw_dev = self.engine.hw_device
        if hw_dev and current_id not in ("default", "") and not any(
            base_node_name(d.id) == base_node_name(hw_dev.id) for d in devices
        ):
            devices = devices + [hw_dev]

        # La salida elegida no está publicada (p. ej. WirePlumber no ha recuperado la tarjeta):
        # se muestra atenuada en lugar de desaparecer sin explicación
        missing_current = current_id not in ("default", "") and not any(
            d.id != "default" and base_node_name(d.id) == base_node_name(current_id) for d in devices
        )

        current_dev: AudioDevice | None = None
        for dev in devices:
            if current_id in ("default", ""):
                is_active = dev.id == "default"
            else:
                is_active = dev.id != "default" and base_node_name(dev.id) == base_node_name(current_id)
            if is_active:
                current_dev = dev

            row = Adw.ActionRow()
            row.set_title(dev.name)
            row.set_title_lines(1)
            row.set_subtitle(format_device_subtitle(dev))
            row.set_subtitle_lines(1)
            row.set_tooltip_text(dev.description or dev.name)

            icon = Gtk.Image.new_from_icon_name(dev.icon_name or "audio-card-symbolic")
            icon.set_pixel_size(16)
            icon.add_css_class("output-row-icon")
            row.add_prefix(icon)

            check_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check_icon.set_pixel_size(16)
            check_icon.add_css_class("accent")
            check_icon.set_opacity(1.0 if is_active else 0.0)
            row.add_suffix(check_icon)

            row.set_activatable(True)
            row.connect("activated", lambda _row, d=dev: self._select_device_from_popover(d))
            list_box.append(row)

        if missing_current:
            row = Adw.ActionRow()
            row.set_title(self.device_label.get_text() or current_id)
            row.set_title_lines(1)
            row.set_subtitle(i18n.t("devices.unavailable"))
            row.set_subtitle_lines(1)
            icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            icon.set_pixel_size(16)
            icon.add_css_class("output-row-icon")
            row.add_prefix(icon)
            row.set_sensitive(False)
            list_box.append(row)

        scrolled.set_child(list_box)
        box.append(scrolled)

        # Un único interruptor para la salida activa (la preferencia se guarda por dispositivo)
        bp_list = Gtk.ListBox()
        bp_list.add_css_class("boxed-list")
        bp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        bp_row = Adw.SwitchRow()
        bp_row.set_title(i18n.t("devices.exclusive_title"))
        bp_row.set_subtitle_lines(2)
        can_exclusive = current_dev is not None and current_dev.id != "default" and current_dev.hw_path is not None
        if can_exclusive:
            bp_row.set_subtitle(i18n.t("devices.exclusive_subtitle_short"))
            if self.is_device_exclusive_enabled_cb:
                bp_row.set_active(self.is_device_exclusive_enabled_cb(current_dev))
            else:
                bp_row.set_active(self.engine.exclusive)

            def _on_bp_toggled(row, _pspec, target_dev=current_dev):
                if self.on_device_exclusive_toggled:
                    self.on_device_exclusive_toggled(target_dev, row.get_active())

            bp_row.connect("notify::active", _on_bp_toggled)
        else:
            bp_row.set_subtitle(i18n.t("devices.exclusive_unavailable_short"))
            bp_row.set_sensitive(False)
        bp_list.append(bp_row)
        box.append(bp_list)

        # Ancho fijo: set_size_request solo fija el mínimo; el Clamp impide que un nombre o
        # subtítulo largo ensanche el desplegable (los textos se recortan con elipsis)
        clamp = Adw.Clamp(maximum_size=_OUTPUT_POPOVER_WIDTH, tightening_threshold=_OUTPUT_POPOVER_WIDTH)
        clamp.set_child(box)
        self.device_popover.set_child(clamp)

    def _select_device_from_popover(self, dev: AudioDevice):
        if self.on_device_selected:
            self.on_device_selected(dev)
        elif self.on_device_click:
            self.on_device_click()
        self.device_popover.popdown()

    def _toggle_queue_popover(self, *_):
        self._rebuild_queue_popover()
        self.queue_popover.popup()

    def _rebuild_queue_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("queue-popover-box")
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        # Cabecera
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl_title = Gtk.Label(label=i18n.t("queue.title"), xalign=0.0)
        lbl_title.add_css_class("heading")
        lbl_title.set_hexpand(True)
        header.append(lbl_title)

        if self._queue:
            badge_cnt = Gtk.Label(label=i18n.t("queue.tracks_count", n=len(self._queue)))
            badge_cnt.add_css_class("dim-label")
            badge_cnt.add_css_class("caption")
            header.append(badge_cnt)

            btn_clear = Gtk.Button(label=i18n.t("queue.clear"))
            btn_clear.add_css_class("flat")

            def on_clear_click(*_):
                if self.on_clear_queue_clicked:
                    self.on_clear_queue_clicked()
                self.queue_popover.popdown()

            btn_clear.connect("clicked", on_clear_click)
            header.append(btn_clear)

        box.append(header)

        # Contenido de la lista o mensaje vacío
        if not self._queue:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_margin_top(20)
            empty_box.set_margin_bottom(20)

            icon = Gtk.Image.new_from_icon_name("view-list-bullet-symbolic")
            icon.set_pixel_size(32)
            icon.set_opacity(0.35)
            lbl_empty = Gtk.Label(label=i18n.t("queue.empty"))
            lbl_empty.add_css_class("heading")
            lbl_empty.set_opacity(0.8)
            lbl_hint = Gtk.Label(label=i18n.t("queue.empty_hint"))
            lbl_hint.add_css_class("caption")
            lbl_hint.add_css_class("dim-label")
            lbl_hint.set_wrap(True)
            lbl_hint.set_max_width_chars(26)
            lbl_hint.set_justify(Gtk.Justification.CENTER)

            empty_box.append(icon)
            empty_box.append(lbl_empty)
            empty_box.append(lbl_hint)
            box.append(empty_box)
        else:
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_vexpand(True)
            scrolled.set_min_content_height(140)
            scrolled.set_max_content_height(260)

            list_box = Gtk.ListBox()
            list_box.add_css_class("boxed-list")
            list_box.set_selection_mode(Gtk.SelectionMode.NONE)

            for idx, track in enumerate(self._queue):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                row.add_css_class("queue-row")

                num_lbl = Gtk.Label(label=str(idx + 1), xalign=0.5)
                num_lbl.add_css_class("dim-label")
                num_lbl.set_size_request(20, -1)
                row.append(num_lbl)

                info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                info_box.set_hexpand(True)
                title = Gtk.Label(label=track.title or os.path.basename(track.filepath), xalign=0.0)
                title.set_ellipsize(Pango.EllipsizeMode.END)
                title.set_max_width_chars(20)
                sub = Gtk.Label(label=track.artist or "", xalign=0.0)
                sub.add_css_class("dim-label")
                sub.add_css_class("caption")
                sub.set_ellipsize(Pango.EllipsizeMode.END)
                sub.set_max_width_chars(20)
                info_box.append(title)
                info_box.append(sub)
                row.append(info_box)

                dur_lbl = Gtk.Label(label=self._format_sec(track.duration), xalign=1.0)
                dur_lbl.add_css_class("dim-label")
                dur_lbl.add_css_class("time-label")
                row.append(dur_lbl)

                btn_remove = Gtk.Button()
                btn_remove.set_icon_name("window-close-symbolic")
                btn_remove.add_css_class("flat")
                btn_remove.add_css_class("circular")
                btn_remove.set_valign(Gtk.Align.CENTER)

                def make_remove_cb(i):
                    def cb(*_):
                        if self.on_queue_track_removed:
                            self.on_queue_track_removed(i)
                    return cb

                btn_remove.connect("clicked", make_remove_cb(idx))
                row.append(btn_remove)

                list_box.append(row)

            scrolled.set_child(list_box)
            box.append(scrolled)

        self.queue_popover.set_child(box)

    def update_queue(self, queue: list[AudioTrack]):
        """Actualiza la lista interna de la cola y el estado visual del botón."""
        self._queue = list(queue)
        if self._queue:
            self.queue_btn.add_css_class("accent")
            self.queue_btn.set_tooltip_text(i18n.t("queue.tooltip_count", n=len(self._queue)))
        else:
            self.queue_btn.remove_css_class("accent")
            self.queue_btn.set_tooltip_text(i18n.t("queue.tooltip"))

        if self.queue_popover.get_visible():
            self._rebuild_queue_popover()

    def refresh_i18n(self):
        """Actualiza tooltips y textos traducidos."""
        self.cover_frame.set_tooltip_text(i18n.t("player.cover_tooltip"))
        self.shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.prev_btn.set_tooltip_text(i18n.t("player.prev"))
        self.play_btn.set_tooltip_text(i18n.t("player.play_pause"))
        self.next_btn.set_tooltip_text(i18n.t("player.next"))
        self.repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
        self.vol_btn.set_tooltip_text(i18n.t("player.volume"))
        self.update_active_device()
        self.update_queue(self._queue)
        if not self.engine.current_track:
            self.title_label.set_text(i18n.t("inspector.no_playback"))
