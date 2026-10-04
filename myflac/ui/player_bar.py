import logging
import os
from .visualizers import OscilloscopeWidget
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from ..audio import upnp
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

# Paso de los botones − / + del volumen (1 %)
VOLUME_STEP = 0.01
# Paso por cada «clic» de la rueda del ratón sobre el altavoz (2 %)
VOLUME_SCROLL_STEP = 0.02


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
        self.set_size_request(-1, 74)
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

        # Overlay para superponer el osciloscopio a la mini-portada
        self._cover_overlay = Gtk.Overlay()
        self._cover_overlay.set_vexpand(True)
        self._cover_overlay.set_valign(Gtk.Align.FILL)
        self._cover_overlay.set_child(self.cover_stack)

        # Scope sobre la mini-portada (toda la superficie, pequeño por diseño)
        self.bar_scope = OscilloscopeWidget()
        self.bar_scope.set_can_target(False)
        self.bar_scope.set_active(True)
        self.bar_scope.set_visible(False)
        self._cover_overlay.add_overlay(self.bar_scope)

        self._bar_scope_enabled: bool = True

        self.cover_frame.append(self._cover_overlay)
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
        self.center_clamp = Adw.Clamp()
        self.center_clamp.set_hexpand(True)
        self.center_clamp.set_maximum_size(720)
        self.center_clamp.set_tightening_threshold(540)

        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        center_box.set_hexpand(True)
        center_box.set_valign(Gtk.Align.CENTER)

        # Botones de control con relieve táctil audiófilo
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls_box.set_halign(Gtk.Align.CENTER)
        controls_box.set_valign(Gtk.Align.CENTER)
        controls_box.set_margin_top(4)
        controls_box.add_css_class("hifi-controls-dock")

        self.shuffle_btn = Gtk.ToggleButton()
        self.shuffle_btn.set_icon_name("media-playlist-shuffle-symbolic")
        self.shuffle_btn.set_tooltip_text(i18n.t("player.shuffle"))
        self.shuffle_btn.set_valign(Gtk.Align.CENTER)
        self.shuffle_btn.add_css_class("hifi-btn")
        self.shuffle_btn.add_css_class("hifi-btn-sub")
        self.shuffle_btn.connect("toggled", self._on_shuffle_toggle)
        controls_box.append(self.shuffle_btn)

        self.prev_btn = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.prev_btn.set_tooltip_text(i18n.t("player.prev"))
        self.prev_btn.set_valign(Gtk.Align.CENTER)
        self.prev_btn.add_css_class("hifi-btn")
        self.prev_btn.add_css_class("hifi-btn-step")
        self.prev_btn.connect("clicked", lambda *_: self.on_previous_clicked and self.on_previous_clicked())
        controls_box.append(self.prev_btn)

        self.play_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.play_btn.set_tooltip_text(i18n.t("player.play_pause"))
        self.play_btn.set_valign(Gtk.Align.CENTER)
        self.play_btn.add_css_class("hifi-btn")
        self.play_btn.add_css_class("hifi-btn-play")
        self.play_btn.add_css_class("play-pause-btn")
        self.play_btn.connect("clicked", lambda *_: self._handle_play_click())
        controls_box.append(self.play_btn)

        self.next_btn = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.next_btn.set_tooltip_text(i18n.t("player.next"))
        self.next_btn.set_valign(Gtk.Align.CENTER)
        self.next_btn.add_css_class("hifi-btn")
        self.next_btn.add_css_class("hifi-btn-step")
        self.next_btn.connect("clicked", lambda *_: self.on_next_clicked and self.on_next_clicked())
        controls_box.append(self.next_btn)

        self.repeat_btn = Gtk.Button.new_from_icon_name("media-playlist-repeat-symbolic")
        self.repeat_btn.set_tooltip_text(i18n.t("player.repeat"))
        self.repeat_btn.set_valign(Gtk.Align.CENTER)
        self.repeat_btn.add_css_class("hifi-btn")
        self.repeat_btn.add_css_class("hifi-btn-sub")
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
        self.center_clamp.set_child(center_box)
        self.append(self.center_clamp)

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

        # Volumen: icono con el nivel en %, y en el desplegable − / deslizador / + para ajustes finos
        self.vol_btn = Gtk.MenuButton()
        self.vol_btn.add_css_class("flat")
        self.vol_btn.add_css_class("volume-btn")
        self.vol_btn.set_tooltip_text(i18n.t("player.volume"))
        vol_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.vol_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        vol_btn_box.append(self.vol_icon)
        self.vol_btn_label = Gtk.Label(label="")
        self.vol_btn_label.add_css_class("numeric")
        self.vol_btn_label.add_css_class("caption")
        # Ancho fijo para «100 %» y alineado a la derecha: el botón no se mueve al cambiar de cifra
        self.vol_btn_label.set_width_chars(5)
        self.vol_btn_label.set_max_width_chars(5)
        self.vol_btn_label.set_xalign(1.0)
        vol_btn_box.append(self.vol_btn_label)
        self.vol_btn.set_child(vol_btn_box)

        # Rueda del ratón sobre el altavoz: sube/baja sin abrir el desplegable
        vol_scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        vol_scroll.connect("scroll", self._on_volume_scroll)
        self.vol_btn.add_controller(vol_scroll)
        self._scroll_accum = 0.0

        vol_popover = Gtk.Popover()
        vol_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vol_content.set_margin_top(10)
        vol_content.set_margin_bottom(10)
        vol_content.set_margin_start(10)
        vol_content.set_margin_end(10)

        self.vol_value_label = Gtk.Label(label="")
        self.vol_value_label.add_css_class("title-2")
        self.vol_value_label.add_css_class("numeric")
        self.vol_value_label.set_width_chars(5)
        vol_content.append(self.vol_value_label)

        vol_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.vol_down_btn = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        self.vol_down_btn.add_css_class("circular")
        self.vol_down_btn.add_css_class("flat")
        self.vol_down_btn.set_valign(Gtk.Align.CENTER)
        self.vol_down_btn.set_tooltip_text(i18n.t("player.volume_down"))
        self.vol_down_btn.connect("clicked", lambda *_: self._step_volume(-VOLUME_STEP))
        vol_row.append(self.vol_down_btn)

        self.vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, VOLUME_STEP)
        self.vol_scale.set_increments(VOLUME_STEP, 0.05)
        self.vol_scale.set_round_digits(2)
        self.vol_scale.set_value(self.engine.volume)
        self.vol_scale.set_size_request(170, -1)
        self.vol_scale.set_hexpand(True)
        self.vol_scale.connect("value-changed", self._on_volume_changed)
        vol_row.append(self.vol_scale)

        self.vol_up_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.vol_up_btn.add_css_class("circular")
        self.vol_up_btn.add_css_class("flat")
        self.vol_up_btn.set_valign(Gtk.Align.CENTER)
        self.vol_up_btn.set_tooltip_text(i18n.t("player.volume_up"))
        self.vol_up_btn.connect("clicked", lambda *_: self._step_volume(VOLUME_STEP))
        vol_row.append(self.vol_up_btn)
        vol_content.append(vol_row)

        vol_popover.set_child(vol_content)
        self.vol_btn.set_popover(vol_popover)
        right_box.append(self.vol_btn)
        self._update_vol_icon(self.engine.volume)

        self.append(right_box)

    def _connect_engine(self):
        self.engine.add_state_listener(self._on_state_changed)
        self.engine.on_track_changed = self._on_track_changed
        self.engine.on_position_updated = self._on_position_updated
        self.engine.add_output_listener(self.update_active_device)
        self.engine.add_level_listener(self._on_audio_level)

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
                self._syncing_volume = True  # Viene del motor o del equipo: no se reenvía
                self.vol_scale.set_value(vol)
                self._syncing_volume = False
            self._update_vol_icon(vol)
        else:
            self.vol_icon.set_from_icon_name("audio-volume-high-symbolic")
            self.vol_btn_label.set_label("0 dB")
            self.vol_value_label.set_label("0 dB")

    def _update_output_status_line(self, dev: AudioDevice):
        status, level, tooltip = output_status(self.engine)
        self.output_status_label.set_text(status)
        for cls in ("ok", "warn"):
            self.output_dot.remove_css_class(cls)
        if level:
            self.output_dot.add_css_class(level)
        self.device_btn.set_tooltip_text(f"{i18n.t('player.active_device', name=dev.name)}\n{tooltip}")

    def _on_state_changed(self, state: PlaybackState):
        is_playing = (state == PlaybackState.PLAYING)
        if is_playing:
            self.play_btn.set_icon_name("media-playback-pause-symbolic")
            self.play_btn.add_css_class("is-playing")
        else:
            self.play_btn.set_icon_name("media-playback-start-symbolic")
            self.play_btn.remove_css_class("is-playing")
        # Actualizar scope de la mini-portada
        scope_on = is_playing and self._bar_scope_enabled
        self.bar_scope.set_playing(is_playing)
        self.bar_scope.set_visible(scope_on)

    def set_bar_oscilloscope_enabled(self, enabled: bool):
        """Activa o desactiva el osciloscopio en la mini-portada de la barra."""
        self._bar_scope_enabled = enabled
        is_playing = (self.engine.state == PlaybackState.PLAYING)
        scope_on = is_playing and enabled
        self.bar_scope.set_active(enabled)
        self.bar_scope.set_playing(is_playing and enabled)
        self.bar_scope.set_visible(scope_on)

    def _on_audio_level(self, rms: list[float], peak: list[float]):
        """Callback del motor de audio: alimenta los niveles al osciloscopio de la mini-portada."""
        if self._bar_scope_enabled and (self.engine.state == PlaybackState.PLAYING):
            self.bar_scope.update_levels(rms, peak)

    def update_bar_scope_level(self, rms: list[float], peak: list[float]):
        """Alimenta los niveles de audio al scope de la mini-portada."""
        if self._bar_scope_enabled:
            self.bar_scope.update_levels(rms, peak)


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
        val = round(scale.get_value(), 2)
        if not getattr(self, "_syncing_volume", False):
            self.engine.set_volume(val)
        self._update_vol_icon(val)

    def _on_volume_scroll(self, _controller, _dx: float, dy: float) -> bool:
        """Rueda hacia arriba sube, hacia abajo baja. Los touchpads envían fracciones: se acumulan."""
        if not self.engine.volume_adjustable:
            return True  # Exclusivo sin volumen por hardware: fijo a 0 dB
        self._scroll_accum += dy
        steps = int(self._scroll_accum)
        if steps:
            self._scroll_accum -= steps
            self._step_volume(-steps * VOLUME_SCROLL_STEP)
        return True  # Que la rueda no desplace nada más

    def _step_volume(self, delta: float):
        """Botones − / +: un 1 % cada pulsación (el deslizador emite el cambio)."""
        val = round(min(1.0, max(0.0, self.vol_scale.get_value() + delta)), 2)
        self.vol_scale.set_value(val)

    def _update_vol_icon(self, val: float):
        pct = int(round(val * 100))
        self.vol_btn_label.set_label(f"{pct} %")
        self.vol_value_label.set_label(f"{pct} %")
        self.vol_down_btn.set_sensitive(pct > 0)
        self.vol_up_btn.set_sensitive(pct < 100)
        if val == 0:
            icon = "audio-volume-muted-symbolic"
        elif val < 0.35:
            icon = "audio-volume-low-symbolic"
        elif val < 0.7:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-high-symbolic"
        self.vol_icon.set_from_icon_name(icon)

    def _format_sec(self, seconds: float) -> str:
        s = int(round(max(0.0, seconds)))
        m = s // 60
        sec = s % 60
        return f"{m}:{sec:02d}"

    def _toggle_device_popover(self, *_):
        self._rebuild_device_popover()
        self.device_popover.popup()
        # Busca renderers de red (UPnP/DLNA) y refresca la lista si aparece alguno nuevo
        before = {d.udn for d in upnp.known_devices()}

        def on_found(devs):
            if {d.udn for d in devs} != before:
                GLib.idle_add(self._refresh_device_popover_if_open)

        upnp.discover_async(on_found)

    def _refresh_device_popover_if_open(self):
        if self.device_popover.get_visible():
            self._rebuild_device_popover()
        return False

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
