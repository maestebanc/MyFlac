"""Motor de reproducción de audio con GStreamer y mezclador del sistema para MyFlac."""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
from enum import Enum
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst

from ..logger import get_logger
from .. import i18n
from .hwmixer import HardwareMixer
from .devices import (
    AudioDevice,
    base_node_name,
    find_device_by_id,
    find_published_device,
    get_default_device,
    resolve_hardware_device,
)
from .reserve import AudioDeviceReservation, pcm_is_closed, wait_until_pcm_closed
from .track import AudioTrack
from .upnp import REMOTE_PREFIX, RemoteRenderer, find_known_device

log = get_logger("audio.engine")

if not Gst.is_initialized():
    Gst.init(None)


# En pausa o parado, el DAC se devuelve a PipeWire tras este margen. Reservar y liberar la tarjeta
# en ciclos muy seguidos (pausa/play, fin de pista y siguiente) deja a WirePlumber sin recrearla.
_EXCLUSIVE_RELEASE_DELAY_S = 10

# GstPlayFlags de playbin3
_PLAY_FLAG_AUDIO = 0x02
_PLAY_FLAG_SOFT_VOLUME = 0x10
_PLAY_FLAG_NATIVE_AUDIO = 0x20


def _format_depth(fmt: str) -> int | None:
    """Bits útiles de un formato PCM de GStreamer: S16LE → 16, S24_32LE → 24, S32LE → 32."""
    m = re.match(r"[SU](\d+)", fmt)
    return int(m.group(1)) if m else None


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class AudioEngine:
    def __init__(self, device_id: str = "default", volume: float = 1.0, exclusive: bool = False):
        self.device_id = device_id
        self._sw_volume = max(0.0, min(1.0, volume))  # Volumen de GStreamer (solo con el mezclador)
        # En exclusivo: mezclador ALSA propio del DAC, si lo tiene, y el volumen elegido para él
        self.hw_mixer: HardwareMixer | None = None
        self._hw_volume_target: float | None = None

        # Modo exclusivo: preferencia del usuario y estado real (puede caer al mezclador si falla)
        self.exclusive = exclusive
        self.exclusive_active = False
        self.resampling_active = False
        self.depth_reduced = False  # El DAC recibe menos bits de los que tiene la pista
        # DSD: nativo al DAC (sin DoP ni conversión) o convertido a PCM si el DAC no lo admite
        self._dsd_mode = False
        self.output_dsd = False
        self.dsd_to_pcm = False
        # Frecuencias DSD que el DAC (o alsasink) no aceptó en nativo, por tarjeta: van como PCM
        self._dsd_rejected: dict[int, set[int]] = {}
        self.output_sample_rate: int = 0
        self.output_bit_depth: int = 0
        self.hw_device: AudioDevice | None = None
        self._reservation: AudioDeviceReservation | None = None
        self._released_node: str | None = None  # Salida devuelta a PipeWire que aún puede no estar lista
        # En exclusivo, el DAC solo se retiene mientras suena: en pausa o parado se devuelve a PipeWire
        self._hw_suspended = False
        self._release_timer: int | None = None
        # Pista que el DAC no admite en exclusivo: se reproduce por el mezclador y luego se vuelve
        self._exclusive_bypass_track: AudioTrack | None = None
        self._fallback_scheduled = False
        # Reserva pedida de antemano mientras se espera a que WirePlumber cierre la tarjeta
        self._prepared_reservation: AudioDeviceReservation | None = None
        # Reconstrucción de la salida en curso (se espera sin bloquear la interfaz)
        self._rebuild_timer: int | None = None
        self._rebuild_finish: Callable[[], None] | None = None
        self._rebuild_gen = 0  # Invalida esperas y reservas asíncronas de una reconstrucción anulada
        # Pista que cargará la reconstrucción en curso (la última que se haya pedido mientras espera)
        self._rebuild_request: tuple[AudioTrack, float] | None = None
        self._resume_pending = False
        self._levels_enabled = True

        self.current_track: AudioTrack | None = None
        self.next_track: AudioTrack | None = None
        self._gapless_pending: AudioTrack | None = None
        self._error_seen = False  # Error en la pista actual: no encadenar la siguiente
        self._want_playing = False  # Intención del usuario (sobrevive a errores transitorios)
        self.state = PlaybackState.STOPPED

        self._playbin: Gst.Element | None = None
        self._sink: Gst.Element | None = None
        self._level_filter: Gst.Element | None = None
        self._bus: Gst.Bus | None = None
        self._timer_id: int | None = None
        self._pending_seek: float | None = None
        self._is_prerolled: bool = False

        # Callbacks y Listeners múltiples
        self.on_state_changed: Callable[[PlaybackState], None] | None = None
        self._state_listeners: list[Callable[[PlaybackState], None]] = []
        self.on_track_changed: Callable[[AudioTrack], None] | None = None
        self._track_listeners: list[Callable[[AudioTrack], None]] = []
        self._level_listeners: list[Callable[[list[float], list[float]], None]] = []
        self.on_position_updated: Callable[[float, float], None] | None = None
        self._position_listeners: list[Callable[[float, float], None]] = []
        self.on_track_finished: Callable[[], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self._output_listeners: list[Callable[[], None]] = []
        # Renderer UPnP/DLNA activo: si no es None, el audio no pasa por GStreamer
        self._remote: RemoteRenderer | None = None
        # Último reintento por URL de streaming caducada, por pista
        self._stream_retry_ts: dict[int, float] = {}

        log.info("Inicializando AudioEngine (device_id='%s', exclusivo=%s)", device_id, exclusive)
        self._init_pipeline()

    def add_state_listener(self, callback: Callable[[PlaybackState], None]):
        """Registra un listener para cambios de estado de reproducción (play/pause/stop)."""
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def remove_state_listener(self, callback: Callable[[PlaybackState], None]):
        """Elimina un listener de estado previamente registrado."""
        if callback in self._state_listeners:
            self._state_listeners.remove(callback)

    def add_track_listener(self, callback: Callable[[AudioTrack], None]):
        """Registra un listener para cambios de pista en reproducción."""
        if callback not in self._track_listeners:
            self._track_listeners.append(callback)

    def remove_track_listener(self, callback: Callable[[AudioTrack], None]):
        """Elimina un listener de cambio de pista previamente registrado."""
        if callback in self._track_listeners:
            self._track_listeners.remove(callback)

    def add_level_listener(self, callback: Callable[[list[float], list[float]], None]):
        """Registra un listener para recibir niveles de audio en tiempo real (RMS, Peak en dB)."""
        if callback not in self._level_listeners:
            self._level_listeners.append(callback)

    def remove_level_listener(self, callback: Callable[[list[float], list[float]], None]):
        """Elimina un listener de niveles de audio previamente registrado."""
        if callback in self._level_listeners:
            self._level_listeners.remove(callback)

    def add_position_listener(self, callback: Callable[[float, float], None]):
        """Registra un listener para actualizaciones periódicas de posición (pos, dur)."""
        if callback not in self._position_listeners:
            self._position_listeners.append(callback)

    def remove_position_listener(self, callback: Callable[[float, float], None]):
        """Elimina un listener de posición previamente registrado."""
        if callback in self._position_listeners:
            self._position_listeners.remove(callback)

    def add_output_listener(self, callback: Callable[[], None]):
        """Registra un listener para cambios de salida (dispositivo o modo exclusivo)."""
        if callback not in self._output_listeners:
            self._output_listeners.append(callback)

    def remove_output_listener(self, callback: Callable[[], None]):
        """Elimina un listener de salida previamente registrado."""
        if callback in self._output_listeners:
            self._output_listeners.remove(callback)

    def _notify_output_changed(self):
        for listener in list(self._output_listeners):
            try:
                listener()
            except Exception as e:
                log.exception("Error en listener de salida: %s", e)

    @property
    def position(self) -> float:
        """Propiedad de acceso directo a la posición actual de reproducción en segundos."""
        return self.get_position()

    def _notify_level(self, rms: list[float], peak: list[float]):
        """Notifica los niveles de audio en dB a los listeners registrados."""
        for listener in list(self._level_listeners):
            try:
                listener(rms, peak)
            except Exception as e:
                log.exception("Error en listener de nivel de audio: %s", e)

    def renotify_track_changed(self):
        """Vuelve a avisar de la pista actual (p. ej. cuando su portada termina de cargarse)."""
        if self.current_track:
            self._notify_track_changed(self.current_track)

    def _notify_track_changed(self, track: AudioTrack):
        """Notifica cambio de pista a todos los listeners registrados."""
        if self.on_track_changed:
            try:
                self.on_track_changed(track)
            except Exception as e:
                log.exception("Error en callback on_track_changed: %s", e)
        for listener in list(self._track_listeners):
            try:
                listener(track)
            except Exception as e:
                log.exception("Error en listener de cambio de pista: %s", e)

    def _notify_state_changed(self):
        """Notifica a todos los listeners registrados y al callback legado."""
        if self.on_state_changed:
            try:
                self.on_state_changed(self.state)
            except Exception as e:
                log.exception("Error en callback on_state_changed: %s", e)
        for listener in list(self._state_listeners):
            try:
                listener(self.state)
            except Exception as e:
                log.exception("Error en listener de estado: %s", e)

    def _init_pipeline(self):
        """Crea y configura el reproductor GStreamer playbin3."""
        if self._playbin is not None:
            self._cleanup_pipeline()

        self._playbin = Gst.ElementFactory.make("playbin3", "myflac_player")
        if self._playbin is None:
            log.critical("No se pudo instanciar playbin3 en GStreamer")
            raise RuntimeError("No se pudo instanciar playbin3 en GStreamer")

        # Solo audio: sin esto, la portada incrustada de un DSF/MP3 llega como pista de vídeo y
        # playbin3 abre una ventana (xvimagesink) al usar el mezclador del sistema
        self._playbin.set_property("flags", _PLAY_FLAG_AUDIO | _PLAY_FLAG_SOFT_VOLUME)
        self._apply_audio_sink()
        if self._dsd_mode:
            self._allow_dsd_passthrough()

        # Filtro de nivel en tiempo real para osciloscopio y vúmetro. En modo exclusivo va en una
        # rama aparte del sink (ver _build_exclusive_sink) para no alterar el formato de la muestra.
        if not self.exclusive_active:
            self._level_filter = self._make_level_element("myflac_audio_level")
            if self._level_filter:
                try:
                    self._playbin.set_property("audio-filter", self._level_filter)
                except Exception as e:
                    log.warning("No se pudo asignar audio-filter en playbin3: %s", e)

        # Conectar al bus de mensajes
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_bus_message)

        # Gapless: encadenar siguiente pista
        self._playbin.connect("about-to-finish", self._on_about_to_finish)

        # Fijar volumen inicial (en exclusivo, siempre 0 dB)
        self._playbin.set_property("volume", 1.0 if self.exclusive_active else self._sw_volume)

    def _allow_dsd_passthrough(self):
        """
        playbin3 decodifica el DSD a PCM aunque el sink acepte audio/x-dsd: se amplían las caps de
        su uridecodebin3 para que el flujo DSD del demuxer llegue tal cual a dsdconvert ! alsasink.
        """
        it = self._playbin.iterate_recurse()
        while True:
            res, element = it.next()
            if res != Gst.IteratorResult.OK:
                break
            factory = element.get_factory()
            if factory and factory.get_name() == "uridecodebin3":
                caps = element.get_property("caps")
                element.set_property("caps", Gst.Caps.from_string(caps.to_string() + "; audio/x-dsd"))

    def _set_dsd_pcm_rate(self, track: AudioTrack):
        """
        DSD convertido a PCM en exclusivo: se fija la mayor frecuencia de la familia de 44,1 kHz que
        admita el DAC (352,8 kHz en el iFi), con relación entera respecto al DSD. Sin esto,
        audioresample elegiría la máxima del DAC (384 kHz), una conversión menos limpia.
        """
        if not (self.exclusive_active and isinstance(self._sink, Gst.Bin)):
            return
        capsfilter = self._sink.get_by_name("dsd_pcm_rate")
        if capsfilter is None:
            return
        caps = Gst.Caps.new_any()
        if track.is_dsd and self.hw_device and self.hw_device.max_sample_rate:
            rate = 44100
            while rate * 2 <= min(self.hw_device.max_sample_rate, track.sample_rate // 8):
                rate *= 2
            caps = Gst.Caps.from_string(f"audio/x-raw,rate={rate}")
        capsfilter.set_property("caps", caps)

    def _wants_dsd(self, track: AudioTrack | None) -> bool:
        """La pista es DSD y va a un DAC en exclusivo que lo admite de forma nativa."""
        if track is None or not track.is_dsd or not self.exclusive or self.device_id == "default":
            return False
        if self._exclusive_bypass_track is not None:
            return False
        hw_dev = self.hw_device or self._resolve_hw_device()
        if not (hw_dev and hw_dev.dsd_native):
            return False
        return track.sample_rate not in self._dsd_rejected.get(hw_dev.alsa_card, set())

    def _make_level_element(self, name: str) -> Gst.Element | None:
        level = Gst.ElementFactory.make("level", name)
        if level:
            level.set_property("post-messages", self._levels_enabled)
            level.set_property("interval", 33000000)  # ~33 ms (~30 fps)
        return level

    def _apply_audio_sink(self):
        """Crea el sink: ALSA hw directo en modo exclusivo o el mezclador del sistema."""
        if not self._playbin:
            return

        self._release_reservation()
        self._close_hw_mixer()
        self.exclusive_active = False
        self._hw_suspended = False
        self.resampling_active = False
        self.depth_reduced = False
        self.output_sample_rate = 0
        self.output_bit_depth = 0
        self.output_dsd = False
        self.dsd_to_pcm = False

        if self.exclusive and self.device_id != "default" and self._exclusive_bypass_track is None:
            # La tarjeta solo se toma aquí si _rebuild_output ya la reservó (de forma asíncrona). En
            # otro caso (arranque en pausa...) el sink se crea en espera y play() la reserva sin bloquear.
            reserve = self._prepared_reservation is not None
            sink = self._build_exclusive_sink(reserve)
            if sink is not None:
                self._sink = sink
                self._released_node = None
                self.exclusive_active = True
                # Sin volumen software ni conversiones de playsink: la muestra llega intacta al DAC
                self._playbin.set_property("flags", _PLAY_FLAG_AUDIO | _PLAY_FLAG_NATIVE_AUDIO)
                self._playbin.set_property("audio-sink", self._sink)
                return

        self.hw_device = None
        self._dsd_mode = False
        # Si se acaba de devolver la tarjeta a PipeWire, _rebuild_output ya esperó (sin bloquear)
        # a que WirePlumber volviera a publicar la salida, que puede tener otro sufijo .N
        self._released_node = None
        device = find_device_by_id(self.device_id) or get_default_device(self.device_id)
        sink = None

        # Priorizar pulsesink (conecta a PipeWire vía pipewire-pulse de forma robusta y sin bloqueos en PAUSED)
        if Gst.ElementFactory.find("pulsesink"):
            sink = Gst.ElementFactory.make("pulsesink", "pulse_sink")
            if sink and device.id != "default":
                try:
                    sink.set_property("device", device.id)
                    log.info("pulsesink direccionado a device='%s' (%s)", device.id, device.name)
                except Exception as e:
                    log.warning("No se pudo fijar device en pulsesink: %s", e)
        elif Gst.ElementFactory.find("pipewiresink"):
            sink = Gst.ElementFactory.make("pipewiresink", "pw_sink")
            if sink and device.id != "default":
                try:
                    sink.set_property("target-object", device.id)
                    log.info("pipewiresink direccionado a target-object='%s' (%s)", device.id, device.name)
                except Exception as e:
                    log.warning("No se pudo fijar target-object en pipewiresink: %s", e)

        if sink is None:
            sink = Gst.ElementFactory.make("autoaudiosink", "auto_sink")
            log.info("Usando autoaudiosink por defecto")

        self._sink = sink
        self._playbin.set_property("audio-sink", self._sink)

    def _build_exclusive_sink(self, reserve: bool = True) -> Gst.Element | None:
        """Crea un bin alsasink hw:X,Y bit-perfect y, si reserve, reserva ya la tarjeta frente a PipeWire."""
        if self.device_id == "default":
            return None
        hw_dev = self._resolve_hw_device()
        if hw_dev is None:
            log.warning("Modo exclusivo no disponible para '%s' (no es una salida ALSA)", self.device_id)
            return None
        if not Gst.ElementFactory.find("alsasink"):
            log.warning("Modo exclusivo no disponible: falta el elemento alsasink")
            return None

        reservation, self._prepared_reservation = self._prepared_reservation, None
        if reservation is not None and (not reserve or reservation.card_index != hw_dev.alsa_card):
            reservation.release()
            reservation = None
        if reservation is not None:
            # Inmediato: _rebuild_output ya esperó (sin bloquear) a que WirePlumber cerrara la tarjeta
            wait_until_pcm_closed(hw_dev.alsa_card, hw_dev.alsa_device)

        if self._dsd_mode and hw_dev.dsd_native:
            # DSD nativo: dsdconvert solo reagrupa los bits (DSDU8 planar → DSD_U32_BE del DAC).
            # El osciloscopio no puede analizar DSD: en este modo queda en reposo.
            desc = f"dsdconvert ! alsasink name=hw_sink device={hw_dev.hw_path}"
            return self._finish_exclusive_bin(desc, hw_dev, reservation)
        self._dsd_mode = False

        # tee ─┬─ queue ─ audioconvert ─ audioresample (quality=10: passthrough si coincide, downsample si excede) ─ alsasink
        #      └─ queue ─ audioconvert ─ level ─ fakesink   (solo análisis para el osciloscopio)
        desc = (
            "tee name=t "
            "t. ! queue ! audioconvert dithering=none noise-shaping=none ! "
            "audioresample quality=10 ! capsfilter name=dsd_pcm_rate ! "
            f"alsasink name=hw_sink device={hw_dev.hw_path} "
            "t. ! queue ! audioconvert ! "
            f"level name=myflac_audio_level post-messages={str(self._levels_enabled).lower()} "
            "interval=33000000 ! "
            "fakesink sync=true async=false"
        )
        return self._finish_exclusive_bin(desc, hw_dev, reservation)

    def _finish_exclusive_bin(self, desc: str, hw_dev: AudioDevice,
                              reservation: AudioDeviceReservation | None) -> Gst.Element | None:
        try:
            sink_bin = Gst.parse_bin_from_description(desc, True)
        except GLib.Error as e:
            log.error("No se pudo crear el sink exclusivo: %s", e.message)
            if reservation:
                reservation.release()
            return None

        hw_sink = sink_bin.get_by_name("hw_sink")
        if hw_sink:
            pad = hw_sink.get_static_pad("sink")
            if pad:
                pad.connect("notify::caps", self._on_hw_sink_caps)

        self._reservation = reservation
        self._hw_suspended = reservation is None  # Sin reserva: play() la pedirá sin bloquear
        self.hw_device = hw_dev
        self._open_hw_mixer()
        log.info("Modo exclusivo%s: salida directa a %s (%s)",
                 " DSD nativo" if self._dsd_mode else "", hw_dev.hw_path, hw_dev.name)
        return sink_bin

    def _on_hw_sink_caps(self, pad: Gst.Pad, _pspec):
        """Comprueba en las caps negociadas con el DAC si la muestra llega intacta (frecuencia y bits)."""
        # Se ejecuta en un hilo de streaming. En una transición gapless las caps nuevas llegan antes
        # de que el hilo principal procese STREAM_START: la pista que suena es la encadenada.
        caps = pad.get_current_caps()
        if not caps or caps.get_size() == 0:
            return
        s = caps.get_structure(0)
        track = self._gapless_pending or self.current_track
        ok_rate, rate = s.get_int("rate")
        if s.get_name() == "audio/x-dsd":
            # En GStreamer la "rate" del DSD es de bytes por canal: DSD64 = 2 822 400 bits/s = 352 800
            self.output_dsd = True
            self.dsd_to_pcm = False
            self.output_sample_rate = rate * 8 if ok_rate else 0
            self.output_bit_depth = 1
            self.resampling_active = False
            self.depth_reduced = False
            log.info("Caps negociadas en DAC: DSD nativo %s (DSD%d)", s.get_string("format") or "?",
                     self.output_sample_rate // 44100)
            GLib.idle_add(self._notify_output_changed)
            return
        self.output_dsd = False
        self.dsd_to_pcm = bool(track and track.is_dsd)
        fmt = s.get_string("format") or ""
        depth = _format_depth(fmt)

        self.output_sample_rate = rate if ok_rate else 0
        self.output_bit_depth = depth or 0
        if track and track.sample_rate and ok_rate:
            self.resampling_active = rate != track.sample_rate
        else:
            self.resampling_active = False
        # 24 bits en un contenedor de 32 es relleno sin pérdida; menos bits que la pista, no.
        # DSD convertido a PCM no se compara (dsd_to_pcm ya lo indica)
        if self.dsd_to_pcm:
            self.resampling_active = False
            self.depth_reduced = False
        elif track and track.bits_per_sample > 1 and depth:
            self.depth_reduced = depth < track.bits_per_sample
        else:
            self.depth_reduced = fmt.startswith("F")
        log.info("Caps negociadas en DAC: %s Hz %s (pista: %s Hz / %s bits) -> Resampling=%s, Bits reducidos=%s",
                 rate if ok_rate else "?", fmt or "?",
                 track.sample_rate if track else 0, track.bits_per_sample if track else 0,
                 self.resampling_active, self.depth_reduced)
        GLib.idle_add(self._notify_output_changed)

    @property
    def is_bitperfect(self) -> bool:
        return self.exclusive_active and not self.resampling_active and not self.depth_reduced \
            and not self.dsd_to_pcm

    def set_levels_enabled(self, enabled: bool):
        """Activa o pausa los mensajes de nivel (osciloscopio). Sin él, no se generan 30 mensajes/s."""
        self._levels_enabled = enabled
        level = self._level_filter
        if level is None and isinstance(self._sink, Gst.Bin):
            level = self._sink.get_by_name("myflac_audio_level")
        if level is not None:
            level.set_property("post-messages", enabled)

    def _resolve_hw_device(self) -> AudioDevice | None:
        """Tarjeta ALSA de la salida actual, aunque PipeWire aún no la haya vuelto a publicar."""
        hw_dev = resolve_hardware_device(self.device_id)
        if hw_dev is None and self.hw_device and base_node_name(self.hw_device.id) == base_node_name(self.device_id):
            hw_dev = self.hw_device
        return hw_dev

    def _schedule_release(self):
        """Devuelve el DAC a PipeWire si sigue sin sonar pasado el margen."""
        if not self.exclusive_active or self._hw_suspended:
            return
        self._cancel_release()
        self._release_timer = GLib.timeout_add_seconds(_EXCLUSIVE_RELEASE_DELAY_S, self._on_release_timeout)

    def _cancel_release(self):
        if self._release_timer is not None:
            GLib.source_remove(self._release_timer)
            self._release_timer = None

    def _on_release_timeout(self) -> bool:
        self._release_timer = None
        if self.state != PlaybackState.PLAYING:
            self._suspend_exclusive(keep_position=True)
        return False

    def _suspend_exclusive(self, keep_position: bool):
        """Cierra el DAC y lo devuelve a PipeWire (pausa o parada en modo exclusivo)."""
        self._cancel_release()
        if not self.exclusive_active or self._hw_suspended:
            return
        if keep_position:
            position = self.get_position()
            self._pending_seek = position if position > 0.0 else None
        self._is_prerolled = False
        self._playbin.set_state(Gst.State.NULL)
        self._release_reservation()
        self._hw_suspended = True
        log.info("DAC liberado mientras no suena (%s)", self.hw_device.hw_path if self.hw_device else "?")

    def _resume_exclusive(self) -> bool:
        """
        Prepara el DAC para reproducir. True si ya está listo; False si se está reservando (play()
        se repetirá solo al terminar) o si no se pudo y la pista pasó al mezclador.
        """
        if not self.exclusive_active or not self._hw_suspended:
            return True
        if self._resume_pending:
            return False
        self._resume_pending = True
        hw_dev = self.hw_device
        playbin = self._playbin
        reservation = AudioDeviceReservation(hw_dev.alsa_card, hw_dev.id)

        def stale() -> bool:
            return self._playbin is not playbin or not self.exclusive_active or not self._hw_suspended

        def ready():
            self._resume_pending = False
            if self._playbin is not playbin or not self.exclusive_active or self._reservation is not reservation:
                return
            if self._want_playing:
                self.play()
            else:
                self._schedule_release()  # Se pausó mientras se reservaba

        def on_reserved(ok: bool):
            if stale():
                self._resume_pending = False
                reservation.release()
                return
            if ok:
                self._reservation = reservation
                self._hw_suspended = False
                log.info("DAC recuperado para reproducir (%s)", hw_dev.hw_path)
                self._reapply_hw_volume()
                self._wait_until(lambda: pcm_is_closed(hw_dev.alsa_card, hw_dev.alsa_device), 2.0, 20,
                                 f"{hw_dev.hw_path} sigue abierto por otro proceso", ready)
                return
            self._resume_pending = False
            log.warning("No se pudo recuperar el DAC %s; esta pista va por el mezclador", hw_dev.hw_path)
            position = self._pending_seek or 0.0
            self._exclusive_bypass_track = self.current_track
            next_track = self.next_track
            self._rebuild_output(self.current_track, position)
            self.next_track = next_track
            if self.on_error:
                self.on_error(i18n.t("devices.exclusive_failed", reason=i18n.t("devices.exclusive_busy")))

        reservation.acquire_async(on_reserved)
        return False

    def _wait_until(self, check: Callable[[], bool], timeout: float, interval_ms: int, what: str,
                    then: Callable[[], None], user_msg: str | None = None) -> int | None:
        """Llama a then() cuando check() se cumpla o pase el timeout, sin bloquear. Devuelve el timer."""
        if check():
            then()
            return None
        deadline = time.monotonic() + timeout

        def poll() -> bool:
            ok = check()
            if not ok and time.monotonic() < deadline:
                return True
            if not ok:
                log.warning("%s tras %.1fs; se continúa igualmente", what, timeout)
                if user_msg and self.on_error:
                    self.on_error(user_msg)
            then()
            return False

        return GLib.timeout_add(interval_ms, poll)

    def _release_reservation(self):
        if self._reservation:
            self._restore_hw_volume()
            self._reservation.release()
            self._reservation = None
            if self.hw_device:
                self._released_node = self.hw_device.id

    def _rebuild_output(self, track: AudioTrack | None = None, position: float | None = None):
        """
        Reconstruye el pipeline con la salida actual conservando pista y posición.

        Al cambiar entre exclusivo y mezclador hay que esperar a WirePlumber: que ceda la tarjeta y
        la cierre antes de abrirla en hw:X,Y, o que vuelva a publicar la salida tras devolvérsela.
        Todo se hace de forma asíncrona para no congelar la interfaz.
        """
        current_pos = self.get_position() if position is None else position
        curr_track = track or self.current_track

        self._cancel_pending_rebuild()
        # Si la nueva salida es el mismo DAC en exclusivo (p. ej. cambio PCM ↔ DSD), la reserva se
        # conserva: soltarla y pedirla de nuevo al instante deja a WirePlumber en un estado roto
        target_exclusive = self.exclusive and self.device_id != "default" and self._exclusive_bypass_track is None
        target_hw = self._resolve_hw_device() if target_exclusive else None
        kept = None
        if self._reservation and target_hw and self._reservation.card_index == target_hw.alsa_card:
            kept, self._reservation = self._reservation, None
        self._cleanup_pipeline()  # Devuelve la tarjeta a PipeWire si estaba en exclusivo (y no se conserva)
        self._pending_seek = current_pos if current_pos > 0.0 else None
        self._rebuild_gen += 1
        gen = self._rebuild_gen
        self._rebuild_request = (curr_track, current_pos) if curr_track else None
        # DSD nativo o PCM según la pista que va a sonar: una sola construcción de la salida
        self._dsd_mode = self._wants_dsd(curr_track)
        if kept is not None:
            self._prepared_reservation = kept

        def finish():
            if gen != self._rebuild_gen:
                return
            self._rebuild_timer = None
            self._rebuild_finish = None
            request, self._rebuild_request = self._rebuild_request, None
            self._init_pipeline()
            self._notify_output_changed()
            if request:
                self.load_track(request[0], play_now=self._want_playing, initial_position=request[1])

        self._rebuild_finish = finish

        if self.exclusive and self.device_id != "default" and self._exclusive_bypass_track is None \
                and self._want_playing and self._prepared_reservation is None:
            hw_dev = self._resolve_hw_device()
            if hw_dev is not None and hw_dev.alsa_card is not None:
                reservation = AudioDeviceReservation(hw_dev.alsa_card, hw_dev.id)

                def on_reserved(ok: bool):
                    if gen != self._rebuild_gen:
                        reservation.release()
                        return
                    if not ok:
                        # WirePlumber no la cede: esta pista suena por el mezclador
                        request = self._rebuild_request
                        self._exclusive_bypass_track = request[0] if request else None
                        if self.on_error:
                            self.on_error(i18n.t("devices.exclusive_failed",
                                                 reason=i18n.t("devices.exclusive_busy")))
                        finish()
                        return
                    self._prepared_reservation = reservation
                    card, device = hw_dev.alsa_card, hw_dev.alsa_device
                    self._rebuild_timer = self._wait_until(
                        lambda: pcm_is_closed(card, device), 2.0, 20,
                        f"hw:{card},{device} sigue abierto por otro proceso", finish)

                reservation.acquire_async(on_reserved)
                return

        released = self._released_node
        if released and self.device_id != "default" and find_published_device(released) is None:
            name = self.hw_device.name if self.hw_device else released
            self._rebuild_timer = self._wait_until(
                lambda: find_published_device(released) is not None, 3.0, 150,
                f"La salida '{released}' no ha reaparecido en PipeWire", finish,
                user_msg=i18n.t("devices.wireplumber_lost", name=name))
            return
        finish()

    def _cancel_pending_rebuild(self):
        self._rebuild_gen += 1
        if self._rebuild_timer is not None:
            GLib.source_remove(self._rebuild_timer)
            self._rebuild_timer = None
        self._rebuild_finish = None
        if self._prepared_reservation is not None:
            self._prepared_reservation.release()
            self._prepared_reservation = None

    def set_output(self, device_id: str, exclusive: bool):
        """Cambia a la vez dispositivo y modo exclusivo reconstruyendo la salida una sola vez."""
        if device_id.startswith(REMOTE_PREFIX):
            self._enter_remote(device_id)
            return
        was_remote = self._remote is not None
        if was_remote:
            self._leave_remote()
        if device_id == "default" and exclusive:
            log.warning("No se puede activar el modo exclusivo para la salida predeterminada del sistema")
            exclusive = False
        same_device = self.device_id == device_id
        if not was_remote and same_device and self.exclusive == exclusive and self.exclusive_active == exclusive \
                and self._exclusive_bypass_track is None:
            return
        log.info("Salida de audio: '%s' (exclusivo=%s)", device_id, exclusive)
        if not same_device:
            self._hw_volume_target = None  # Cada DAC conserva su propio volumen de hardware
        self.device_id = device_id
        self.exclusive = exclusive
        self._exclusive_bypass_track = None
        self._rebuild_output()

    def set_device(self, device_id: str):
        """Cambia el dispositivo de salida conservando el modo exclusivo si es el mismo dispositivo."""
        if self.device_id == device_id:
            return
        self.set_output(device_id, self.exclusive and device_id != "default")

    def set_exclusive(self, enabled: bool):
        """Activa o desactiva el modo exclusivo bit-perfect (ALSA hw directo)."""
        self.set_output(self.device_id, enabled)

    @property
    def remote_active(self) -> bool:
        """True si la salida es un dispositivo de red UPnP/DLNA (el audio no pasa por GStreamer)."""
        return self._remote is not None

    def _enter_remote(self, device_id: str):
        """Pasa la reproducción a un renderer UPnP/DLNA conservando pista, posición y estado."""
        dev = find_known_device(device_id)
        if dev is None:
            name = device_id.removeprefix(REMOTE_PREFIX)
            log.warning("Dispositivo de red no encontrado: %s", device_id)
            if self.on_error:
                self.on_error(i18n.t("devices.network_not_found", name=name))
            return
        if self._remote is not None and self.device_id == device_id:
            return
        log.info("Salida de red UPnP/DLNA: '%s' (%s)", dev.name, dev.host)
        track = self.current_track
        position = self.get_position() if track else 0.0
        was_playing = self.state == PlaybackState.PLAYING
        if self._remote is not None:
            self._remote.stop_now()
            self._remote.shutdown()
            self._remote = None

        # El pipeline local se desmonta por completo (devuelve el DAC a PipeWire si estaba en exclusivo)
        self._cancel_pending_rebuild()
        self._rebuild_finish = None
        self._rebuild_request = None
        self._cleanup_pipeline()
        self._hw_suspended = False
        self._exclusive_bypass_track = None
        self.exclusive = False
        self.exclusive_active = False
        self.hw_device = None
        self.resampling_active = False
        self.depth_reduced = False
        self.output_dsd = False
        self.dsd_to_pcm = False
        self._pending_seek = None
        self._stop_timer()

        self.device_id = device_id
        self._remote = RemoteRenderer(
            dev,
            on_state=self._on_remote_state,
            on_finished=self._on_remote_finished,
            on_error=self._on_remote_error,
            on_volume=self._notify_output_changed,
            on_advanced=self._on_remote_advanced,
        )
        self._notify_output_changed()
        if track:
            self.load_track(track, play_now=was_playing, initial_position=position)

    def _leave_remote(self):
        """Abandona el renderer de red; el llamador reconstruye la salida local."""
        remote = self._remote
        if remote is None:
            return
        position = remote.position
        remote.stop_now()
        remote.shutdown()
        self._remote = None
        self._pending_seek = position if position > 0.0 else None
        self._stop_timer()

    def _on_remote_state(self, state: str):
        """El dispositivo cambió de estado por su cuenta (botones físicos o su propia app)."""
        if self._remote is None:
            return
        if state == "PLAYING" and self.state != PlaybackState.PLAYING:
            self._want_playing = True
            self.state = PlaybackState.PLAYING
            self._start_timer()
            self._notify_state_changed()
        elif state == "PAUSED" and self.state == PlaybackState.PLAYING:
            self._want_playing = False
            self.state = PlaybackState.PAUSED
            self._stop_timer()
            self._notify_state_changed()
        elif state == "STOPPED" and self.state != PlaybackState.STOPPED:
            self._want_playing = False
            self.state = PlaybackState.STOPPED
            self._stop_timer()
            self._notify_state_changed()

    def _on_remote_finished(self):
        if self._remote is None:
            return
        log.info("Fin de pista en el dispositivo de red")
        self.stop()
        if self.on_track_finished:
            self.on_track_finished()

    def _on_remote_advanced(self, track: AudioTrack):
        """El dispositivo de red pasó solo a la pista encadenada (sin silencio entre pistas)."""
        if self._remote is None:
            return
        log.info("Pista encadenada en reproducción en '%s': '%s'", self._remote.device.name, track.title)
        if self.next_track is track:
            self.next_track = None
        self.current_track = track
        self.output_sample_rate = track.sample_rate or 0
        self.output_bit_depth = track.bits_per_sample or 0
        self._notify_track_changed(track)
        self._notify_position(self.get_position(), self.get_duration())

    def _on_remote_error(self, reason: str):
        if self._remote is None:
            return
        name = self._remote.device.name
        log.error("Error en la salida de red '%s': %s", name, reason)
        self._want_playing = False
        if self.state != PlaybackState.STOPPED:
            self.state = PlaybackState.PAUSED
            self._stop_timer()
            self._notify_state_changed()
        if self.on_error:
            self.on_error(i18n.t("devices.network_failed", name=name, reason=reason))

    @property
    def volume(self) -> float:
        """Volumen efectivo: el del dispositivo de red, el del DAC en exclusivo (si tiene control propio) o el de GStreamer."""
        if self._remote is not None and self._remote.volume is not None:
            return self._remote.volume
        if self.exclusive_active and self.hw_mixer:
            return self.hw_mixer.get_volume()
        return self._sw_volume

    @property
    def software_volume(self) -> float:
        return self._sw_volume

    @property
    def volume_adjustable(self) -> bool:
        """En exclusivo solo se puede ajustar si el DAC tiene volumen por hardware."""
        if self._remote is not None:
            return bool(self._remote.device.rc_url)
        return not self.exclusive_active or self.hw_mixer is not None

    def set_volume(self, vol: float):
        """Ajusta el volumen: en el dispositivo de red, por hardware en el DAC en exclusivo, o por software con el mezclador."""
        vol = max(0.0, min(1.0, vol))
        if self._remote is not None:
            self._remote.set_volume(vol)
            return
        if self.exclusive_active:
            if self.hw_mixer:
                self._hw_volume_target = vol
                self.hw_mixer.set_volume(vol)
            return
        self._sw_volume = vol
        if self._playbin:
            self._playbin.set_property("volume", vol)

    def _open_hw_mixer(self):
        self._close_hw_mixer()
        if self.hw_device and self.hw_device.alsa_card is not None:
            self.hw_mixer = HardwareMixer.open(self.hw_device.alsa_card)
            self._reapply_hw_volume()

    def _close_hw_mixer(self):
        if self.hw_mixer:
            self._restore_hw_volume()
            self.hw_mixer.close()
            self.hw_mixer = None

    def _restore_hw_volume(self):
        # La tarjeta vuelve a PipeWire y a las demás aplicaciones con el volumen que tenía
        if self.hw_mixer:
            self.hw_mixer.restore_initial()

    def _reapply_hw_volume(self):
        # Al devolver la tarjeta, PipeWire restaura en el mezclador su propio volumen
        if self.hw_mixer and self._hw_volume_target is not None:
            self.hw_mixer.set_volume(self._hw_volume_target)

    def load_track(self, track: AudioTrack, play_now: bool = True, initial_position: float = 0.0):
        """Carga una pista para reproducción de forma segura y sin bloqueos."""
        if self._remote is not None:
            self.current_track = track
            self.next_track = None  # load() del renderer descarta la encadenada: se vuelve a encadenar
            self._gapless_pending = None
            self._error_seen = False
            self._pending_seek = None
            self._want_playing = play_now
            self.output_sample_rate = track.sample_rate or 0
            self.output_bit_depth = track.bits_per_sample or 0
            log.info("Cargando pista en '%s': '%s' (%s)", self._remote.device.name, track.title, track.badge_full)
            self._remote.load(track, play_now, initial_position)
            self.state = PlaybackState.PLAYING if play_now else PlaybackState.PAUSED
            if play_now:
                self._start_timer()
            else:
                self._stop_timer()
            self._notify_state_changed()
            self._notify_track_changed(track)
            self._notify_position(initial_position, self.get_duration())
            return
        if self._rebuild_finish is not None:
            # Salida aún en preparación: cargará esta pista cuando esté lista
            self._rebuild_request = (track, initial_position)
            self._want_playing = play_now
            self.current_track = track
            self._pending_seek = initial_position if initial_position > 0.0 else None
            self._notify_track_changed(track)
            return
        if self.exclusive_active and self._wants_dsd(track) != self._dsd_mode:
            # DSD nativo y PCM necesitan un sink distinto: se reconstruye la salida para esta pista
            self._dsd_mode = not self._dsd_mode
            self._want_playing = play_now
            self._rebuild_output(track, initial_position)
            return
        if self._exclusive_bypass_track is not None and track is not self._exclusive_bypass_track:
            # Terminó la pista que el DAC no admitía: se vuelve al exclusivo con la nueva
            self._exclusive_bypass_track = None
            self._want_playing = play_now
            self._rebuild_output(track, initial_position)
            return
        self.current_track = track
        self._gapless_pending = None
        self._error_seen = False
        self._pending_seek = initial_position if initial_position > 0.0 else None
        self._is_prerolled = False
        self.depth_reduced = False
        self.output_bit_depth = 0

        # Previsión hasta que el DAC negocie las caps (_on_hw_sink_caps la confirma)
        self.output_dsd = self.exclusive_active and self._dsd_mode and track.is_dsd
        self.dsd_to_pcm = self.exclusive_active and track.is_dsd and not self.output_dsd
        if self.output_dsd or self.dsd_to_pcm:
            self.resampling_active = False
            self.output_sample_rate = track.sample_rate or 0
        elif self.exclusive_active and self.hw_device:
            if self.hw_device.max_sample_rate and track.sample_rate and track.sample_rate > self.hw_device.max_sample_rate:
                self.resampling_active = True
                self.output_sample_rate = self.hw_device.max_sample_rate
            else:
                self.resampling_active = False
                self.output_sample_rate = track.sample_rate or 0
        else:
            self.resampling_active = False
            self.output_sample_rate = track.sample_rate or 0

        if track.filepath.startswith(("http://", "https://")):
            uri = track.filepath
        else:
            uri = "file://" + urllib.parse.quote(os.path.abspath(track.filepath))
        log.info("Cargando pista: '%s' (%s) | URI: %s", track.title, track.badge_full, uri)

        if not self._playbin:
            self._init_pipeline()

        self._stop_timer()
        # En GStreamer playbin3, para cambiar de pista se pasa a READY (no a NULL para evitar reabrir sinks).
        # En exclusivo, READY ya abre el DAC: se pasa a NULL y solo se abre al reproducir.
        self._playbin.set_state(Gst.State.NULL if self.exclusive_active else Gst.State.READY)
        self._set_dsd_pcm_rate(track)
        self._playbin.set_property("uri", uri)

        if play_now:
            self.play()
        elif self.exclusive_active:
            self._schedule_release()
            self.state = PlaybackState.PAUSED
            self._notify_state_changed()
        else:
            self._playbin.set_state(Gst.State.PAUSED)
            self.state = PlaybackState.PAUSED
            self._notify_state_changed()

        self._notify_track_changed(track)
        if initial_position > 0.0:
            self._notify_position(initial_position, self.get_duration())

    def queue_next_track(self, track: AudioTrack | None):
        same = track is self.next_track
        self.next_track = track
        if self._remote is not None and not same:
            self._remote.set_next(track)

    def _on_about_to_finish(self, playbin):
        # Se ejecuta en un hilo de streaming de GStreamer: solo encadena la URI. El cambio de
        # pista se notifica al llegar STREAM_START al bus, cuando la nueva pista empieza a sonar.
        # Un pipeline ya sustituido, una pista que no llegó a sonar o que falló (p. ej. el DAC no se
        # pudo abrir) también emiten esta señal: encadenar ahí saltaría pistas o tocaría el pipeline
        # nuevo desde otro hilo.
        if playbin is not self._playbin or not self._is_prerolled or self._error_seen:
            return
        next_track = self.next_track
        if next_track and self.exclusive_active and self._wants_dsd(next_track) != self._dsd_mode:
            return  # Cambio DSD ↔ PCM: la siguiente pista se carga al terminar esta, con otro sink
        if next_track:
            if next_track.filepath.startswith(("http://", "https://")):
                next_uri = next_track.filepath
            else:
                next_uri = "file://" + urllib.parse.quote(os.path.abspath(next_track.filepath))
            log.info("Encadenando siguiente pista gapless: '%s'", next_track.title)
            playbin.set_property("uri", next_uri)
            self._gapless_pending = next_track
            self.next_track = None

    def play(self):
        if self._remote is not None:
            track = self.current_track
            if track is None:
                return
            self._want_playing = True
            if self.state == PlaybackState.STOPPED:
                self._remote.load(track, True, 0.0)  # Tras una parada hay que volver a cargar la pista
            else:
                self._remote.play()
            self.state = PlaybackState.PLAYING
            self._start_timer()
            self._notify_state_changed()
            return
        if self._rebuild_finish is not None:
            self._want_playing = True  # Empezará a sonar al terminar de preparar la salida
            return
        if not self._playbin or not self.current_track:
            return
        log.info("Iniciando reproducción: '%s'", self.current_track.title)
        self._want_playing = True
        self._cancel_release()
        if not self._resume_exclusive():
            return  # Reservando el DAC (play() se repetirá al terminar) o ya va por el mezclador
        ret = self._playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            log.error("Fallo al reproducir en GStreamer")
            if self.exclusive_active:
                # El mensaje ERROR del bus gestiona la vuelta al mezclador y reanuda la reproducción
                self.state = PlaybackState.PLAYING
                return
            if self.on_error:
                self.on_error("Error al iniciar reproducción en el mezclador de audio.")
            return

        self.state = PlaybackState.PLAYING
        self._start_timer()
        self._notify_state_changed()

    def pause(self):
        if self._remote is not None:
            if self.current_track is None:
                return
            log.info("Pausando reproducción en '%s'", self._remote.device.name)
            self._want_playing = False
            self._remote.pause()
            self.state = PlaybackState.PAUSED
            self._stop_timer()
            self._notify_state_changed()
            return
        if self._rebuild_finish is not None:
            self._want_playing = False
            self.state = PlaybackState.PAUSED
            self._notify_state_changed()
            return
        if not self._playbin:
            return
        log.info("Pausando reproducción")
        self._want_playing = False
        if self.exclusive_active and self._hw_suspended:
            pass  # El DAC ya está devuelto a PipeWire; play() lo volverá a reservar
        else:
            # En exclusivo el DAC se retiene unos segundos para reanudar al instante
            self._playbin.set_state(Gst.State.PAUSED)
            self._schedule_release()
        self.state = PlaybackState.PAUSED
        self._stop_timer()
        self._notify_state_changed()
        self._notify_level([-100.0, -100.0], [-100.0, -100.0])

    def toggle_play_pause(self):
        if self._rebuild_finish is not None:
            if self._want_playing:
                self.pause()
            else:
                self.play()
            return
        if self.state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self):
        if self._remote is not None:
            self._want_playing = False
            self._remote.stop()
            self.state = PlaybackState.STOPPED
            self._stop_timer()
            self._notify_state_changed()
            self._notify_position(0.0, self.get_duration())
            return
        if self._rebuild_finish is not None:
            self._want_playing = False
        if not self._playbin:
            return
        self._pending_seek = None
        self._is_prerolled = False
        self._want_playing = False
        self.resampling_active = False
        self.depth_reduced = False
        self.output_sample_rate = 0
        self.output_bit_depth = 0
        if self.exclusive_active:
            # NULL cierra el PCM; la reserva se mantiene unos segundos por si llega la siguiente pista
            self._playbin.set_state(Gst.State.NULL)
            self._schedule_release()
        else:
            self._playbin.set_state(Gst.State.READY)
        self.state = PlaybackState.STOPPED
        self._stop_timer()
        self._notify_state_changed()
        self._notify_level([-100.0, -100.0], [-100.0, -100.0])
        self._notify_position(0.0, self.get_duration())

    def seek(self, position_seconds: float):
        """Solicita avanzar o retroceder en la pista actual de forma segura y sin bloqueos."""
        if self._remote is not None:
            if self.state == PlaybackState.STOPPED:
                return
            position_seconds = max(0.0, position_seconds)
            dur = self.get_duration()
            if dur > 0:
                position_seconds = min(position_seconds, max(0.0, dur - 0.5))
            self._remote.seek(position_seconds)
            self._notify_position(position_seconds, dur)
            return
        if not self._playbin or self.state == PlaybackState.STOPPED:
            return

        position_seconds = max(0.0, position_seconds)
        dur = self.get_duration()
        if dur > 0:
            position_seconds = min(position_seconds, dur)

        # Si el pipeline aún no ha completado el preroll (ASYNC_DONE), encolar el seek para evitar bloqueos
        ret, cur, pend = self._playbin.get_state(0)
        if cur < Gst.State.PAUSED or pend != Gst.State.VOID_PENDING or ret == Gst.StateChangeReturn.ASYNC or not self._is_prerolled:
            log.debug("Pipeline aún en preroll o transición; encolando seek a %.2fs", position_seconds)
            self._pending_seek = position_seconds
            self._notify_position(position_seconds, dur)
            return

        self._perform_seek(position_seconds)

    def _perform_seek(self, position_seconds: float):
        """Aplica la operación de seek sobre el pipeline de GStreamer."""
        if not self._playbin:
            return
        target_ns = int(max(0.0, position_seconds) * Gst.SECOND)
        ret = self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            target_ns,
        )
        if not ret:
            log.warning("seek_simple a %.2fs no pudo ser despachado por GStreamer", position_seconds)
        self._notify_position(position_seconds, self.get_duration())

    def get_position(self) -> float:
        if self._remote is not None:
            return self._remote.position if self.state != PlaybackState.STOPPED else 0.0
        if self._pending_seek is not None:
            return self._pending_seek
        if not self._playbin or self.state == PlaybackState.STOPPED:
            return 0.0
        success, pos_ns = self._playbin.query_position(Gst.Format.TIME)
        return (pos_ns / Gst.SECOND) if success else 0.0

    def get_duration(self) -> float:
        if self.current_track and self.current_track.duration > 0:
            return self.current_track.duration
        if self._playbin and self.state != PlaybackState.STOPPED:
            success, dur_ns = self._playbin.query_duration(Gst.Format.TIME)
            if success and dur_ns > 0:
                return dur_ns / Gst.SECOND
        return 0.0

    def _start_timer(self):
        if self._timer_id is None:
            self._timer_id = GLib.timeout_add(100, self._on_timer_tick)

    def _stop_timer(self):
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _notify_position(self, pos: float, dur: float):
        if self.on_position_updated:
            try:
                self.on_position_updated(pos, dur)
            except Exception as e:
                log.exception("Error en on_position_updated: %s", e)
        for listener in list(self._position_listeners):
            try:
                listener(pos, dur)
            except Exception as e:
                log.exception("Error en position_listener: %s", e)

    def _on_timer_tick(self) -> bool:
        if self.state != PlaybackState.PLAYING:
            return False
        pos = self.get_position()
        dur = self.get_duration()
        self._notify_position(pos, dur)
        return True

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message):
        m_type = message.type
        if m_type == Gst.MessageType.EOS:
            log.info("Fin de pista alcanzado (EOS)")
            self.stop()
            if self.on_track_finished:
                self.on_track_finished()
        elif m_type == Gst.MessageType.STREAM_START:
            if self._gapless_pending is not None:
                self.current_track = self._gapless_pending
                self._gapless_pending = None
                log.info("Pista gapless en reproducción: '%s'", self.current_track.title)
                self._notify_track_changed(self.current_track)
                if self._exclusive_bypass_track is not None:
                    # Terminó la pista no admitida por el DAC: recuperar el modo exclusivo
                    GLib.idle_add(self._restore_exclusive_and_reload)
        elif m_type == Gst.MessageType.ASYNC_DONE:
            self._is_prerolled = True
            if self._pending_seek is not None:
                pos = self._pending_seek
                self._pending_seek = None
                log.debug("ASYNC_DONE recibido en bus: ejecutando seek encolado a %.2fs", pos)
                self._perform_seek(pos)
        elif m_type == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if s and s.get_name() == "level":
                rms = s.get_value("rms")
                peak = s.get_value("peak")
                if rms is not None and peak is not None and self._level_listeners:
                    self._notify_level(rms, peak)
        elif m_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._playbin:
                old_state, new_state, _pending = message.parse_state_changed()
                if new_state == Gst.State.PLAYING and self.state != PlaybackState.PLAYING:
                    self.state = PlaybackState.PLAYING
                    self._start_timer()
                    self._notify_state_changed()
                elif new_state == Gst.State.PAUSED and old_state == Gst.State.PLAYING and self.state != PlaybackState.PAUSED:
                    self.state = PlaybackState.PAUSED
                    self._stop_timer()
                    self._notify_state_changed()
        elif m_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            log.error("Error en GStreamer: %s (debug: %s)", err.message, debug)
            self._error_seen = True
            if self._retry_expired_stream(err):
                return
            if self.exclusive_active:
                if not self._fallback_scheduled:
                    # Fuera del manejador del bus del pipeline que falló, que se va a destruir
                    self._fallback_scheduled = True
                    GLib.idle_add(self._fallback_to_mixer, err, debug or "")
                return
            self.stop()
            if self.on_error:
                self.on_error(err.message)

    def _retry_expired_stream(self, err: GLib.Error) -> bool:
        """
        Las URL firmadas de streaming caducan: si la descarga de una pista de streaming falla, se pide
        una URL nueva una vez y se reanuda en el mismo punto. Devuelve True si se reintenta.
        """
        if GLib.quark_to_string(err.domain) != "gst-resource-error-quark":
            return False
        pending = self._gapless_pending
        track = pending or self.current_track
        if track is None or not track.is_stream or not callable(track.stream_resolver):
            return False
        now = time.monotonic()
        if now - self._stream_retry_ts.get(id(track), 0.0) < 60:
            return False  # Ya se reintentó hace poco: es otro problema
        self._stream_retry_ts[id(track)] = now
        position = 0.0 if pending is not None else self.get_position()
        play_now = self._want_playing or self.state == PlaybackState.PLAYING
        log.warning("Fallo de descarga en '%s': se pide una URL nueva y se reanuda en %.1fs",
                    track.title, position)
        self._gapless_pending = None

        def worker():
            try:
                track.resolve_stream()
            except Exception as e:
                log.error("No se pudo renovar la URL de '%s': %s", track.title, e)
                msg = i18n.t(f"{track.stream_service}.err.stream_unavailable", title=track.title, error=e)
                GLib.idle_add(lambda: (self.on_error and self.on_error(msg), False)[1])
                return
            GLib.idle_add(lambda: (self.load_track(track, play_now=play_now, initial_position=position), False)[1])

        GLib.idle_add(lambda: (self.stop(), False)[1])
        threading.Thread(target=worker, daemon=True, name="stream-renew").start()
        return True

    def _fallback_to_mixer(self, err: GLib.Error, debug: str) -> bool:
        """
        El DAC rechazó el modo exclusivo (ocupado, frecuencia o formato no soportado): la pista que
        falló suena por el mezclador y la siguiente vuelve a intentarlo en exclusivo.
        """
        self._fallback_scheduled = False
        if not self.exclusive_active:
            return False
        pending = self._gapless_pending
        self._gapless_pending = None
        if pending is not None and self._is_prerolled:
            # La pista actual sonaba y falló la encadenada (p. ej. otra frecuencia): es la afectada
            track, position = pending, 0.0
        else:
            # Falló al abrir el DAC o al empezar: es la actual; la encadenada vuelve a la cola
            track, position = self.current_track, None
            if pending is not None and self.next_track is None:
                self.next_track = pending
        if track is None:
            return False

        if "not-negotiated" in debug and self._dsd_mode and track.is_dsd and self.hw_device:
            # alsasink (GStreamer 1.28) solo anuncia DSD64 aunque el DAC admita DSD128/256: esta
            # frecuencia se convierte a PCM sin salir del exclusivo y no se vuelve a intentar
            self._dsd_rejected.setdefault(self.hw_device.alsa_card, set()).add(track.sample_rate)
            dsd = f"DSD{track.sample_rate // 44100}"
            log.warning("%s no se pudo negociar en nativo con %s; se convierte a PCM en exclusivo",
                        dsd, self.hw_device.hw_path)
            next_track = self.next_track
            self._rebuild_output(track, position)  # Conserva la reserva: mismo DAC
            self.next_track = next_track
            if self.on_error:
                self.on_error(i18n.t("devices.dsd_native_rejected", dsd=dsd))
            return False

        if "not-negotiated" in debug:
            log.warning("El DAC no admite '%s' (%s) en exclusivo; se usa el mezclador para esta pista",
                        track.title, track.badge_full)
            message = i18n.t("devices.exclusive_format_unsupported", format=track.badge_full)
        else:
            log.warning("Fallo en modo exclusivo con '%s' (%s); esta pista va por el mezclador",
                        track.title, err.message)
            message = i18n.t("devices.exclusive_failed", reason=err.message)
        self._exclusive_bypass_track = track

        next_track = self.next_track
        self._rebuild_output(track, position)
        self.next_track = next_track
        if self.on_error:
            self.on_error(message)
        return False

    def _restore_exclusive_and_reload(self) -> bool:
        if self._exclusive_bypass_track is not None:
            self._exclusive_bypass_track = None
            self._rebuild_output()
        return False

    def shutdown(self):
        """Detiene la reproducción y devuelve la tarjeta a PipeWire."""
        if self._remote is not None:
            self._remote.stop_now(wait=True)
            self._remote.shutdown()
            self._remote = None
        self._cancel_pending_rebuild()
        self._cleanup_pipeline()

    def _cleanup_pipeline(self):
        self._stop_timer()
        self._close_hw_mixer()
        self._cancel_release()
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._playbin = None
        self._release_reservation()
        self._sink = None
        self._level_filter = None
