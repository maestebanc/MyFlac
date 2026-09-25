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
from .devices import AudioDevice, find_device_by_id, get_default_device
from .track import AudioTrack

log = get_logger("audio.engine")

if not Gst.is_initialized():
    Gst.init(None)


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class AudioEngine:
    def __init__(self, device_id: str = "default", volume: float = 1.0):
        self.device_id = device_id
        self.volume = max(0.0, min(1.0, volume))

        self.current_track: AudioTrack | None = None
        self.next_track: AudioTrack | None = None
        self.state = PlaybackState.STOPPED

        self._playbin: Gst.Element | None = None
        self._sink: Gst.Element | None = None
        self._bus: Gst.Bus | None = None
        self._timer_id: int | None = None

        # Callbacks y Listeners múltiples
        self.on_state_changed: Callable[[PlaybackState], None] | None = None
        self._state_listeners: list[Callable[[PlaybackState], None]] = []
        self.on_track_changed: Callable[[AudioTrack], None] | None = None
        self.on_position_updated: Callable[[float, float], None] | None = None
        self.on_track_finished: Callable[[], None] | None = None
        self.on_error: Callable[[str], None] | None = None

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

        # Conectar al bus de mensajes
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_bus_message)

        # Gapless: encadenar siguiente pista
        self._playbin.connect("about-to-finish", self._on_about_to_finish)

        # Fijar volumen inicial
        self._playbin.set_property("volume", self.volume)

    def _apply_audio_sink(self):
        """Crea el sink adecuado del mezclador del sistema (PipeWire / Pulse)."""
        if not self._playbin:
            return

        device = find_device_by_id(self.device_id) or get_default_device(self.device_id)
        sink = None

        # Intentar crear pipewiresink con target-object si no es default
        if Gst.ElementFactory.find("pipewiresink"):
            sink = Gst.ElementFactory.make("pipewiresink", "pw_sink")
            if sink and device.id != "default":
                try:
                    sink.set_property("target-object", device.id)
                    log.info("pipewiresink direccionado a target-object='%s' (%s)", device.id, device.name)
                except Exception as e:
                    log.warning("No se pudo fijar target-object en pipewiresink: %s", e)
        elif Gst.ElementFactory.find("pulsesink"):
            sink = Gst.ElementFactory.make("pulsesink", "pulse_sink")
            if sink and device.id != "default":
                try:
                    sink.set_property("device", device.id)
                    log.info("pulsesink direccionado a device='%s' (%s)", device.id, device.name)
                except Exception as e:
                    log.warning("No se pudo fijar device en pulsesink: %s", e)

        if sink is None:
            sink = Gst.ElementFactory.make("autoaudiosink", "auto_sink")
            log.info("Usando autoaudiosink por defecto")

        self._sink = sink
        self._playbin.set_property("audio-sink", self._sink)

    def set_device(self, device_id: str):
        """Cambia el dispositivo de salida del mezclador."""
        if self.device_id == device_id:
            return
        log.info("Cambiando salida de audio a: '%s'", device_id)
        self.device_id = device_id
        was_playing = (self.state == PlaybackState.PLAYING)
        current_pos = self.get_position()
        curr_track = self.current_track

        self._init_pipeline()

        if curr_track:
            self.load_track(curr_track, play_now=was_playing)
            if current_pos > 0:
                GLib.timeout_add(150, lambda: (self.seek(current_pos), False)[1])

    def set_volume(self, vol: float):
        """Ajusta el volumen software (0.0 a 1.0)."""
        self.volume = max(0.0, min(1.0, vol))
        if self._playbin:
            self._playbin.set_property("volume", self.volume)

    def load_track(self, track: AudioTrack, play_now: bool = True):
        """Carga una pista para reproducción."""
        self.current_track = track
        uri = "file://" + urllib.parse.quote(os.path.abspath(track.filepath))
        log.info("Cargando pista: '%s' (%s) | URI: %s", track.title, track.badge_full, uri)

        self.stop()
        self._playbin.set_property("uri", uri)

        if play_now:
            self.play()
        else:
            self._playbin.set_state(Gst.State.PAUSED)
            self.state = PlaybackState.PAUSED
            self._notify_state_changed()

        if self.on_track_changed:
            self.on_track_changed(track)

    def queue_next_track(self, track: AudioTrack | None):
        self.next_track = track

    def _on_about_to_finish(self, _playbin):
        if self.next_track:
            next_uri = "file://" + urllib.parse.quote(os.path.abspath(self.next_track.filepath))
            log.info("Encadenando siguiente pista gapless: '%s'", self.next_track.title)
            self._playbin.set_property("uri", next_uri)
            self.current_track = self.next_track
            self.next_track = None
            if self.on_track_changed:
                self.on_track_changed(self.current_track)

    def play(self):
        if not self._playbin or not self.current_track:
            return
        log.info("Iniciando reproducción: '%s'", self.current_track.title)
        ret = self._playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            log.error("Fallo al reproducir en GStreamer")
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
        self._playbin.set_state(Gst.State.PAUSED)
        self.state = PlaybackState.PAUSED
        self._stop_timer()
        self._notify_state_changed()

    def toggle_play_pause(self):
        if self.state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self):
        if not self._playbin:
            return
        self._playbin.set_state(Gst.State.NULL)
        self.state = PlaybackState.STOPPED
        self._stop_timer()
        self._notify_state_changed()
        if self.on_position_updated:
            self.on_position_updated(0.0, self.get_duration())

    def seek(self, position_seconds: float):
        if not self._playbin or self.state == PlaybackState.STOPPED:
            return
        target_ns = int(max(0.0, position_seconds) * Gst.SECOND)
        self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            target_ns,
        )
        if self.on_position_updated:
            self.on_position_updated(position_seconds, self.get_duration())

    def get_position(self) -> float:
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

    def _on_timer_tick(self) -> bool:
        if self.state != PlaybackState.PLAYING:
            return False
        pos = self.get_position()
        dur = self.get_duration()
        if self.on_position_updated:
            self.on_position_updated(pos, dur)
        return True

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message):
        m_type = message.type
        if m_type == Gst.MessageType.EOS:
            log.info("Fin de pista alcanzado (EOS)")
            self.stop()
            if self.on_track_finished:
                self.on_track_finished()
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
            self.stop()
            if self.on_error:
                self.on_error(err.message)

    def _cleanup_pipeline(self):
        self._stop_timer()
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._playbin = None
        self._sink = None
