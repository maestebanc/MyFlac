"""Motor de reproducción de audio con GStreamer y mezclador del sistema para MyFlac."""
from __future__ import annotations

import os
import urllib.parse
from enum import Enum
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst

from ..logger import get_logger
from .. import i18n
from .devices import (
    AudioDevice,
    find_device_by_id,
    get_default_device,
    resolve_hardware_device,
    wait_for_device,
)
from .reserve import AudioDeviceReservation
from .track import AudioTrack

log = get_logger("audio.engine")

if not Gst.is_initialized():
    Gst.init(None)


# GstPlayFlags de playbin3
_PLAY_FLAG_AUDIO = 0x02
_PLAY_FLAG_NATIVE_AUDIO = 0x20


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class AudioEngine:
    def __init__(self, device_id: str = "default", volume: float = 1.0, exclusive: bool = False):
        self.device_id = device_id
        self.volume = max(0.0, min(1.0, volume))

        # Modo exclusivo: preferencia del usuario y estado real (puede caer al mezclador si falla)
        self.exclusive = exclusive
        self.exclusive_active = False
        self.hw_device: AudioDevice | None = None
        self._reservation: AudioDeviceReservation | None = None
        self._released_node: str | None = None  # Salida devuelta a PipeWire que aún puede no estar lista
        # Pista que el DAC no admite en exclusivo: se reproduce por el mezclador y luego se vuelve
        self._exclusive_bypass_track: AudioTrack | None = None

        self.current_track: AudioTrack | None = None
        self.next_track: AudioTrack | None = None
        self._gapless_pending: AudioTrack | None = None
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

        log.info("Inicializando AudioEngine con mezclador del sistema (device_id='%s')", device_id)
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

        self._apply_audio_sink()

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
        self._playbin.set_property("volume", 1.0 if self.exclusive_active else self.volume)

    @staticmethod
    def _make_level_element(name: str) -> Gst.Element | None:
        level = Gst.ElementFactory.make("level", name)
        if level:
            level.set_property("post-messages", True)
            level.set_property("interval", 33000000)  # ~33 ms (~30 fps)
        return level

    def _apply_audio_sink(self):
        """Crea el sink: ALSA hw directo en modo exclusivo o el mezclador del sistema."""
        if not self._playbin:
            return

        self._release_reservation()
        self.exclusive_active = False
        self.hw_device = None

        if self.exclusive and self._exclusive_bypass_track is None:
            sink = self._build_exclusive_sink()
            if sink is not None:
                self._sink = sink
                self.exclusive_active = True
                # Sin volumen software ni conversiones de playsink: la muestra llega intacta al DAC
                self._playbin.set_property("flags", _PLAY_FLAG_AUDIO | _PLAY_FLAG_NATIVE_AUDIO)
                self._playbin.set_property("audio-sink", self._sink)
                return

        device = find_device_by_id(self.device_id)
        if self._released_node:
            # WirePlumber recrea la salida unos instantes después de recuperar la tarjeta (con otro
            # node.name): sin esperar, el audio acabaría en la salida por defecto del sistema
            released, self._released_node = self._released_node, None
            fresh = wait_for_device(released)
            if device is None or device.id != "default":
                device = fresh or device
        device = device or get_default_device(self.device_id)
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

    def _build_exclusive_sink(self) -> Gst.Element | None:
        """Reserva la tarjeta frente a PipeWire y crea un bin alsasink hw:X,Y bit-perfect."""
        hw_dev = resolve_hardware_device(self.device_id)
        if hw_dev is None:
            log.warning("Modo exclusivo no disponible para '%s' (no es una salida ALSA)", self.device_id)
            return None
        if not Gst.ElementFactory.find("alsasink"):
            log.warning("Modo exclusivo no disponible: falta el elemento alsasink")
            return None

        reservation = AudioDeviceReservation(hw_dev.alsa_card, hw_dev.id)
        if not reservation.acquire():
            log.warning("No se pudo reservar la tarjeta %s; se usará el mezclador", hw_dev.hw_path)
            return None

        # tee ─┬─ queue ─ audioconvert (sin dither: solo reempaqueta, p.ej. S24_32 → S24_3) ─ alsasink
        #      └─ queue ─ audioconvert ─ level ─ fakesink   (solo análisis para el osciloscopio)
        desc = (
            "tee name=t "
            "t. ! queue ! audioconvert dithering=none noise-shaping=none ! "
            f"alsasink name=hw_sink device={hw_dev.hw_path} "
            "t. ! queue ! audioconvert ! "
            "level name=myflac_audio_level post-messages=true interval=33000000 ! "
            "fakesink sync=true async=false"
        )
        try:
            sink_bin = Gst.parse_bin_from_description(desc, False)
        except GLib.Error as e:
            log.error("No se pudo crear el sink exclusivo: %s", e.message)
            reservation.release()
            return None

        tee_pad = sink_bin.get_by_name("t").get_static_pad("sink")
        sink_bin.add_pad(Gst.GhostPad.new("sink", tee_pad))

        self._reservation = reservation
        self.hw_device = hw_dev
        log.info("Modo exclusivo: salida directa a %s (%s)", hw_dev.hw_path, hw_dev.name)
        return sink_bin

    def _release_reservation(self):
        if self._reservation:
            self._reservation.release()
            self._reservation = None
            if self.hw_device:
                self._released_node = self.hw_device.id

    def _rebuild_output(self, track: AudioTrack | None = None, position: float | None = None):
        """Reconstruye el pipeline con la salida actual conservando pista y posición."""
        was_playing = self._want_playing
        current_pos = self.get_position() if position is None else position
        curr_track = track or self.current_track

        self._init_pipeline()
        self._notify_output_changed()

        if curr_track:
            self.load_track(curr_track, play_now=was_playing, initial_position=current_pos)

    def set_device(self, device_id: str):
        """Cambia el dispositivo de salida."""
        if self.device_id == device_id:
            return
        log.info("Cambiando salida de audio a: '%s'", device_id)
        self.device_id = device_id
        self._rebuild_output()

    def set_exclusive(self, enabled: bool):
        """Activa o desactiva el modo exclusivo bit-perfect (ALSA hw directo)."""
        if self.exclusive == enabled and self.exclusive_active == enabled:
            return
        log.info("Modo exclusivo %s", "activado" if enabled else "desactivado")
        self.exclusive = enabled
        self._exclusive_bypass_track = None
        self._rebuild_output()

    def set_volume(self, vol: float):
        """Ajusta el volumen software (0.0 a 1.0). Se ignora en modo exclusivo."""
        self.volume = max(0.0, min(1.0, vol))
        if self._playbin and not self.exclusive_active:
            self._playbin.set_property("volume", self.volume)

    def load_track(self, track: AudioTrack, play_now: bool = True, initial_position: float = 0.0):
        """Carga una pista para reproducción de forma segura y sin bloqueos."""
        if self._exclusive_bypass_track is not None and track is not self._exclusive_bypass_track:
            self._restore_exclusive()
        self.current_track = track
        self._gapless_pending = None
        self._pending_seek = initial_position if initial_position > 0.0 else None
        self._is_prerolled = False
        uri = "file://" + urllib.parse.quote(os.path.abspath(track.filepath))
        log.info("Cargando pista: '%s' (%s) | URI: %s", track.title, track.badge_full, uri)

        if not self._playbin:
            self._init_pipeline()

        self._stop_timer()
        # En GStreamer playbin3, para cambiar de pista se pasa a READY (no a NULL para evitar reabrir sinks)
        self._playbin.set_state(Gst.State.READY)
        self._playbin.set_property("uri", uri)

        if play_now:
            self.play()
        else:
            self._playbin.set_state(Gst.State.PAUSED)
            self.state = PlaybackState.PAUSED
            self._notify_state_changed()

        self._notify_track_changed(track)
        if initial_position > 0.0:
            self._notify_position(initial_position, self.get_duration())

    def queue_next_track(self, track: AudioTrack | None):
        self.next_track = track

    def _on_about_to_finish(self, _playbin):
        # Se ejecuta en un hilo de streaming de GStreamer: solo encadena la URI. El cambio de
        # pista se notifica al llegar STREAM_START al bus, cuando la nueva pista empieza a sonar.
        if self.next_track:
            next_uri = "file://" + urllib.parse.quote(os.path.abspath(self.next_track.filepath))
            log.info("Encadenando siguiente pista gapless: '%s'", self.next_track.title)
            self._playbin.set_property("uri", next_uri)
            self._gapless_pending = self.next_track
            self.next_track = None

    def play(self):
        if not self._playbin or not self.current_track:
            return
        log.info("Iniciando reproducción: '%s'", self.current_track.title)
        self._want_playing = True
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
        if not self._playbin:
            return
        log.info("Pausando reproducción")
        self._want_playing = False
        self._playbin.set_state(Gst.State.PAUSED)
        self.state = PlaybackState.PAUSED
        self._stop_timer()
        self._notify_state_changed()
        self._notify_level([-100.0, -100.0], [-100.0, -100.0])

    def toggle_play_pause(self):
        if self.state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self):
        if not self._playbin:
            return
        self._pending_seek = None
        self._is_prerolled = False
        self._want_playing = False
        self._playbin.set_state(Gst.State.READY)
        self.state = PlaybackState.STOPPED
        self._stop_timer()
        self._notify_state_changed()
        self._notify_level([-100.0, -100.0], [-100.0, -100.0])
        self._notify_position(0.0, self.get_duration())

    def seek(self, position_seconds: float):
        """Solicita avanzar o retroceder en la pista actual de forma segura y sin bloqueos."""
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
            if self.exclusive_active:
                self._fallback_to_mixer(err, debug or "")
                return
            self.stop()
            if self.on_error:
                self.on_error(err.message)

    def _fallback_to_mixer(self, err: GLib.Error, debug: str):
        """El DAC rechazó el modo exclusivo (ocupado, frecuencia o formato no soportado)."""
        # Si el fallo llega al encadenar una pista gapless, la afectada es la pendiente
        track = self._gapless_pending or self.current_track
        position = 0.0 if self._gapless_pending else None
        self._gapless_pending = None

        if "not-negotiated" in debug and track is not None:
            # Frecuencia o formato no soportado por el DAC: solo esta pista va por el mezclador
            log.warning("El DAC no admite '%s' (%s) en exclusivo; se usa el mezclador para esta pista",
                        track.title, track.badge_full)
            self._exclusive_bypass_track = track
            message = i18n.t("devices.exclusive_format_unsupported", format=track.badge_full)
        else:
            log.warning("Fallo en modo exclusivo (%s); volviendo al mezclador del sistema", err.message)
            self.exclusive = False
            message = i18n.t("devices.exclusive_failed", reason=err.message)

        self._rebuild_output(track, position)
        if self.on_error:
            self.on_error(message)

    def _restore_exclusive(self):
        self._exclusive_bypass_track = None
        self._init_pipeline()
        self._notify_output_changed()

    def _restore_exclusive_and_reload(self) -> bool:
        if self._exclusive_bypass_track is not None:
            self._exclusive_bypass_track = None
            self._rebuild_output()
        return False

    def shutdown(self):
        """Detiene la reproducción y devuelve la tarjeta a PipeWire."""
        self._cleanup_pipeline()

    def _cleanup_pipeline(self):
        self._stop_timer()
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._playbin = None
        self._release_reservation()
        self._sink = None
        self._level_filter = None
