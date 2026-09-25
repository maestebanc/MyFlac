"""Motor de reproducción de audio bit-perfect con GStreamer para MyFlac."""
from __future__ import annotations

import os
import urllib.parse
from enum import Enum
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst

from .devices import AudioDevice, find_device_by_id, get_default_device
from .track import AudioTrack

# Inicializar GStreamer
if not Gst.is_initialized():
    Gst.init(None)


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class AudioEngine:
    def __init__(self, device_id: str = "auto", bitperfect: bool = True, volume_bypass: bool = True):
        self.device_id = device_id
        self.bitperfect = bitperfect
        self.volume_bypass = volume_bypass
        self.volume = 1.0

        self.current_track: AudioTrack | None = None
        self.next_track: AudioTrack | None = None
        self.state = PlaybackState.STOPPED

        self._playbin: Gst.Element | None = None
        self._sink: Gst.Element | None = None
        self._bus: Gst.Bus | None = None
        self._bus_watch_id: int | None = None
        self._timer_id: int | None = None

        # Callbacks registrados por la UI
        self.on_state_changed: Callable[[PlaybackState], None] | None = None
        self.on_track_changed: Callable[[AudioTrack], None] | None = None
        self.on_position_updated: Callable[[float, float], None] | None = None  # pos_s, dur_s
        self.on_bitperfect_status: Callable[[dict], None] | None = None
        self.on_track_finished: Callable[[], None] | None = None
        self.on_error: Callable[[str], None] | None = None

        self._init_pipeline()

    def _init_pipeline(self):
        """Crea y configura el reproductor GStreamer playbin3."""
        if self._playbin is not None:
            self._cleanup_pipeline()

        self._playbin = Gst.ElementFactory.make("playbin3", "myflac_player")
        if self._playbin is None:
            raise RuntimeError("No se pudo instanciar playbin3 en GStreamer")

        self._apply_audio_sink()

        # Conectar al bus de mensajes de GStreamer
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_bus_message)

        # Gapless: señal 'about-to-finish' para pre-cargar la siguiente pista sin hueco
        self._playbin.connect("about-to-finish", self._on_about_to_finish)

        # Ajuste inicial de volumen
        if self.volume_bypass and self.bitperfect:
            self._playbin.set_property("volume", 1.0)
        else:
            self._playbin.set_property("volume", self.volume)

    def _apply_audio_sink(self):
        """Crea el sink adecuado (ALSA directo hw:X,Y o PipeWire) según configuración."""
        if not self._playbin:
            return

        device = find_device_by_id(self.device_id) or get_default_device(self.device_id)
        sink = None

        if device.id == "pipewire" or not self.bitperfect:
            # Salida compartida
            sink = Gst.ElementFactory.make("pipewiresink", "pw_sink")
            if not sink:
                sink = Gst.ElementFactory.make("autoaudiosink", "auto_sink")
        else:
            # Modo exclusivo Bit-Perfect ALSA
            sink = Gst.ElementFactory.make("alsasink", "alsa_hw_sink")
            if sink:
                # Fijar dispositivo ALSA exacto (ej: 'hw:CARD=Audio,DEV=0' o 'hw:2,0')
                sink.set_property("device", device.id)
                sink.set_property("sync", True)

        if sink is None:
            sink = Gst.ElementFactory.make("autoaudiosink", "fallback_sink")

        self._sink = sink
        self._playbin.set_property("audio-sink", self._sink)

    def set_device(self, device_id: str):
        """Cambia el dispositivo de salida."""
        if self.device_id == device_id:
            return
        self.device_id = device_id
        was_playing = (self.state == PlaybackState.PLAYING)
        current_pos = self.get_position()
        curr_track = self.current_track

        self._init_pipeline()

        if curr_track:
            self.load_track(curr_track, play_now=was_playing)
            if current_pos > 0:
                GLib.timeout_add(150, lambda: (self.seek(current_pos), False)[1])

    def set_bitperfect_mode(self, enabled: bool):
        """Activa o desactiva el modo bit-perfect exclusivo."""
        if self.bitperfect == enabled:
            return
        self.bitperfect = enabled
        was_playing = (self.state == PlaybackState.PLAYING)
        current_pos = self.get_position()
        curr_track = self.current_track

        self._init_pipeline()

        if curr_track:
            self.load_track(curr_track, play_now=was_playing)
            if current_pos > 0:
                GLib.timeout_add(150, lambda: (self.seek(current_pos), False)[1])

    def set_volume_bypass(self, bypass: bool):
        """Fija el volumen al 100% (0 dB sin alteración) o permite volumen software."""
        self.volume_bypass = bypass
        if self._playbin:
            if bypass and self.bitperfect:
                self._playbin.set_property("volume", 1.0)
            else:
                self._playbin.set_property("volume", self.volume)
        self._audit_bitperfect_status()

    def set_volume(self, vol: float):
        """Ajusta el volumen software (0.0 a 1.0)."""
        self.volume = max(0.0, min(1.0, vol))
        if self._playbin and (not self.volume_bypass or not self.bitperfect):
            self._playbin.set_property("volume", self.volume)
        self._audit_bitperfect_status()

    def load_track(self, track: AudioTrack, play_now: bool = True):
        """Carga una pista para reproducción."""
        self.current_track = track
        uri = "file://" + urllib.parse.quote(os.path.abspath(track.filepath))

        self.stop()
        self._playbin.set_property("uri", uri)

        if play_now:
            self.play()
        else:
            self._playbin.set_state(Gst.State.PAUSED)
            self.state = PlaybackState.PAUSED
            if self.on_state_changed:
                self.on_state_changed(self.state)

        if self.on_track_changed:
            self.on_track_changed(track)

    def queue_next_track(self, track: AudioTrack | None):
        """Establece la siguiente pista en cola para reproducción continua sin pausa (gapless)."""
        self.next_track = track

    def _on_about_to_finish(self, _playbin):
        """Señal GStreamer para encadenar la siguiente canción sin corte alguno."""
        if self.next_track:
            next_uri = "file://" + urllib.parse.quote(os.path.abspath(self.next_track.filepath))
            self._playbin.set_property("uri", next_uri)
            self.current_track = self.next_track
            self.next_track = None
            if self.on_track_changed:
                self.on_track_changed(self.current_track)

    def play(self):
        """Inicia o reanuda la reproducción."""
        if not self._playbin or not self.current_track:
            return
        ret = self._playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            if self.on_error:
                self.on_error(f"Error al abrir dispositivo ALSA en modo exclusivo.")
            return

        self.state = PlaybackState.PLAYING
        self._start_timer()
        if self.on_state_changed:
            self.on_state_changed(self.state)

        # Esperar brevemente a que los caps negocien para auditar bit-perfect
        GLib.timeout_add(200, self._audit_bitperfect_status)

    def pause(self):
        """Pone en pausa la reproducción."""
        if not self._playbin:
            return
        self._playbin.set_state(Gst.State.PAUSED)
        self.state = PlaybackState.PAUSED
        self._stop_timer()
        if self.on_state_changed:
            self.on_state_changed(self.state)

    def toggle_play_pause(self):
        if self.state == PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self):
        """Detiene la reproducción y libera el reloj/dispositivo."""
        if not self._playbin:
            return
        self._playbin.set_state(Gst.State.NULL)
        self.state = PlaybackState.STOPPED
        self._stop_timer()
        if self.on_state_changed:
            self.on_state_changed(self.state)
        if self.on_position_updated:
            self.on_position_updated(0.0, self.get_duration())

    def seek(self, position_seconds: float):
        """Desplaza la posición de reproducción a position_seconds."""
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
        """Obtiene la posición actual de reproducción en segundos."""
        if not self._playbin or self.state == PlaybackState.STOPPED:
            return 0.0
        success, pos_ns = self._playbin.query_position(Gst.Format.TIME)
        return (pos_ns / Gst.SECOND) if success else 0.0

    def get_duration(self) -> float:
        """Obtiene la duración total en segundos."""
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
        """Tick cada 100ms para actualizar barra de tiempo suavemente."""
        if self.state != PlaybackState.PLAYING:
            return False
        pos = self.get_position()
        dur = self.get_duration()
        if self.on_position_updated:
            self.on_position_updated(pos, dur)
        return True

    def _audit_bitperfect_status(self) -> bool:
        """Interroga los caps negociados en el sink ALSA para verificar que no haya resampling ni alteración."""
        if not self.on_bitperfect_status or not self.current_track or not self._sink:
            return False

        device = find_device_by_id(self.device_id) or get_default_device(self.device_id)
        sink_pad = self._sink.get_static_pad("sink")
        caps = sink_pad.get_current_caps() if sink_pad else None

        rate = None
        fmt = None
        channels = None

        if caps and caps.get_size() > 0:
            struct = caps.get_structure(0)
            rate = struct.get_value("rate")
            fmt = struct.get_value("format")
            channels = struct.get_value("channels")

        # Comprobación de fidelidad bit-perfect
        source_rate = self.current_track.sample_rate
        source_channels = self.current_track.channels
        
        is_exact_rate = (rate == source_rate) if rate else False
        is_exact_chan = (channels == source_channels) if channels else True
        is_vol_pure = self.volume_bypass or abs(self.volume - 1.0) < 0.001
        
        is_bitperfect = (
            self.bitperfect
            and device.is_exclusive
            and is_exact_rate
            and is_exact_chan
            and is_vol_pure
        )

        status_info = {
            "is_bitperfect": is_bitperfect,
            "device_name": device.name,
            "device_id": device.id,
            "is_exclusive": device.is_exclusive and self.bitperfect,
            "source_rate": source_rate,
            "source_depth": self.current_track.bits_per_sample,
            "source_channels": source_channels,
            "sink_rate": rate,
            "sink_format": fmt,
            "sink_channels": channels,
            "volume_bypass": self.volume_bypass,
            "volume": self.volume,
        }

        self.on_bitperfect_status(status_info)
        return False

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message):
        """Maneja eventos de GStreamer del bus."""
        m_type = message.type
        if m_type == Gst.MessageType.EOS:
            self.stop()
            if self.on_track_finished:
                self.on_track_finished()
        elif m_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self.stop()
            if self.on_error:
                self.on_error(f"{err.message}")
        elif m_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._playbin:
                old_state, new_state, pending = message.parse_state_changed()
                if new_state == Gst.State.PLAYING:
                    self._audit_bitperfect_status()

    def _cleanup_pipeline(self):
        self._stop_timer()
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._playbin = None
        self._sink = None
