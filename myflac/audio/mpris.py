"""Servidor D-Bus MPRIS2 para MyFlac (org.mpris.MediaPlayer2).

Permite el control de reproducción desde el teclado (teclas multimedia),
auriculares Bluetooth, interfaz de bloqueo y bandeja de medios de GNOME Shell.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from ..logger import get_logger
from .engine import PlaybackState
from .track import AudioTrack

if TYPE_CHECKING:
    from ..ui.main_window import MainWindow
    from .engine import AudioEngine

log = get_logger(__name__)

MPRIS_INTROSPECTION_XML = """
<!DOCTYPE node PUBLIC '-//freedesktop//DTD D-BUS Object Introspection 1.0//EN'
'http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd'>
<node>
  <interface name='org.mpris.MediaPlayer2'>
    <method name='Raise'/>
    <method name='Quit'/>
    <property name='CanQuit' type='b' access='read'/>
    <property name='CanRaise' type='b' access='read'/>
    <property name='HasTrackList' type='b' access='read'/>
    <property name='Identity' type='s' access='read'/>
    <property name='DesktopEntry' type='s' access='read'/>
    <property name='SupportedUriSchemes' type='as' access='read'/>
    <property name='SupportedMimeTypes' type='as' access='read'/>
  </interface>
  <interface name='org.mpris.MediaPlayer2.Player'>
    <method name='Next'/>
    <method name='Previous'/>
    <method name='Pause'/>
    <method name='PlayPause'/>
    <method name='Stop'/>
    <method name='Play'/>
    <method name='Seek'>
      <arg direction='in' name='Offset' type='x'/>
    </method>
    <method name='SetPosition'>
      <arg direction='in' name='TrackId' type='o'/>
      <arg direction='in' name='Position' type='x'/>
    </method>
    <method name='OpenUri'>
      <arg direction='in' name='Uri' type='s'/>
    </method>
    <signal name='Seeked'>
      <arg name='Position' type='x'/>
    </signal>
    <property name='PlaybackStatus' type='s' access='read'/>
    <property name='LoopStatus' type='s' access='readwrite'/>
    <property name='Rate' type='d' access='readwrite'/>
    <property name='Shuffle' type='b' access='readwrite'/>
    <property name='Metadata' type='a{sv}' access='read'/>
    <property name='Volume' type='d' access='readwrite'/>
    <property name='Position' type='x' access='read'/>
    <property name='MinimumRate' type='d' access='read'/>
    <property name='MaximumRate' type='d' access='read'/>
    <property name='CanGoNext' type='b' access='read'/>
    <property name='CanGoPrevious' type='b' access='read'/>
    <property name='CanPlay' type='b' access='read'/>
    <property name='CanPause' type='b' access='read'/>
    <property name='CanSeek' type='b' access='read'/>
    <property name='CanControl' type='b' access='read'/>
  </interface>
</node>
"""


class MprisServer:
    """Implementa las interfaces MPRIS2 org.mpris.MediaPlayer2 y Player."""

    def __init__(self, window: MainWindow, engine: AudioEngine):
        self.window = window
        self.engine = engine
        self._connection: Gio.DBusConnection | None = None
        self._owner_id: int = 0
        self._reg_root_id: int = 0
        self._reg_player_id: int = 0

        # Ruta en caché para la carátula de la pista en reproducción
        cache_dir = os.path.join(GLib.get_user_cache_dir(), "myflac")
        os.makedirs(cache_dir, exist_ok=True)
        self._cover_cache_path = os.path.join(cache_dir, "current_mpris_cover.png")
        self._has_cached_cover = False

        # Registrar listeners en el motor
        self.engine.add_state_listener(self._on_playback_state_changed)
        self.engine.add_track_listener(self._on_track_changed)

        self._start_server()

    def _start_server(self):
        """Inicia el registro del servicio D-Bus MPRIS2 en el bus de sesión."""
        bus_name = f"org.mpris.MediaPlayer2.myflac.instance{os.getpid()}"
        primary_name = "org.mpris.MediaPlayer2.myflac"

        node_info = Gio.DBusNodeInfo.new_for_xml(MPRIS_INTROSPECTION_XML)
        self._root_iface = node_info.lookup_interface("org.mpris.MediaPlayer2")
        self._player_iface = node_info.lookup_interface("org.mpris.MediaPlayer2.Player")

        def on_bus_acquired(conn: Gio.DBusConnection, _name: str):
            self._connection = conn
            try:
                self._reg_root_id = conn.register_object(
                    "/org/mpris/MediaPlayer2",
                    self._root_iface,
                    self._handle_root_method,
                    self._handle_root_get_property,
                    None,
                )
                self._reg_player_id = conn.register_object(
                    "/org/mpris/MediaPlayer2",
                    self._player_iface,
                    self._handle_player_method,
                    self._handle_player_get_property,
                    self._handle_player_set_property,
                )
                log.info("Servidor D-Bus MPRIS2 registrado en /org/mpris/MediaPlayer2")
            except Exception as e:
                log.error("Error registrando objetos MPRIS2 en D-Bus: %s", e)

        def on_name_acquired(_conn: Gio.DBusConnection, name: str):
            log.info("Nombre de bus MPRIS2 adquirido: %s", name)

        def on_name_lost(_conn: Gio.DBusConnection, name: str):
            log.warning("Nombre de bus MPRIS2 perdido: %s", name)

        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            primary_name,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE,
            on_bus_acquired,
            on_name_acquired,
            on_name_lost,
        )

    def stop(self):
        """Detiene y desregistra el servidor MPRIS2."""
        if self._connection:
            if self._reg_root_id > 0:
                self._connection.unregister_object(self._reg_root_id)
                self._reg_root_id = 0
            if self._reg_player_id > 0:
                self._connection.unregister_object(self._reg_player_id)
                self._reg_player_id = 0
            self._connection = None
        if self._owner_id > 0:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0
        if self.engine:
            self.engine.remove_state_listener(self._on_playback_state_changed)
            self.engine.remove_track_listener(self._on_track_changed)

    # -------------------------------------------------------------------------
    # Métodos y propiedades org.mpris.MediaPlayer2
    # -------------------------------------------------------------------------

    def _handle_root_method(
        self,
        _conn: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        _params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ):
        if method == "Raise":
            GLib.idle_add(self._action_raise)
            invocation.return_value(None)
        elif method == "Quit":
            GLib.idle_add(self._action_quit)
            invocation.return_value(None)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                f"Método '{method}' desconocido en org.mpris.MediaPlayer2",
            )

    def _handle_root_get_property(
        self,
        _conn: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        prop: str,
    ) -> GLib.Variant | None:
        if prop == "CanQuit":
            return GLib.Variant("b", True)
        elif prop == "CanRaise":
            return GLib.Variant("b", True)
        elif prop == "HasTrackList":
            return GLib.Variant("b", False)
        elif prop == "Identity":
            return GLib.Variant("s", "MyFlac")
        elif prop == "DesktopEntry":
            return GLib.Variant("s", "com.maestebanc.MyFlac")
        elif prop == "SupportedUriSchemes":
            return GLib.Variant("as", ["file"])
        elif prop == "SupportedMimeTypes":
            return GLib.Variant(
                "as",
                [
                    "audio/flac",
                    "audio/x-flac",
                    "audio/wav",
                    "audio/x-wav",
                    "audio/dsd",
                    "audio/x-dsd",
                ],
            )
        return None

    # -------------------------------------------------------------------------
    # Métodos y propiedades org.mpris.MediaPlayer2.Player
    # -------------------------------------------------------------------------

    def _handle_player_method(
        self,
        _conn: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ):
        if method == "Play":
            GLib.idle_add(self.engine.play)
            invocation.return_value(None)
        elif method == "Pause":
            GLib.idle_add(self.engine.pause)
            invocation.return_value(None)
        elif method == "PlayPause":
            GLib.idle_add(self.engine.toggle_play_pause)
            invocation.return_value(None)
        elif method == "Stop":
            GLib.idle_add(self.engine.stop)
            invocation.return_value(None)
        elif method == "Next":
            GLib.idle_add(self.window._play_next)
            invocation.return_value(None)
        elif method == "Previous":
            GLib.idle_add(self.window._play_previous)
            invocation.return_value(None)
        elif method == "Seek":
            offset_us = params[0]
            current_pos = self.engine.get_position()
            target_pos = max(0.0, current_pos + (offset_us / 1_000_000.0))
            GLib.idle_add(self.engine.seek, target_pos)
            invocation.return_value(None)
        elif method == "SetPosition":
            _track_id, pos_us = params[0], params[1]
            target_pos = max(0.0, pos_us / 1_000_000.0)
            GLib.idle_add(self.engine.seek, target_pos)
            invocation.return_value(None)
        elif method == "OpenUri":
            uri = params[0]
            log.info("MPRIS OpenUri solicitado: %s", uri)
            invocation.return_value(None)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(),
                Gio.DBusError.UNKNOWN_METHOD,
                f"Método '{method}' desconocido en org.mpris.MediaPlayer2.Player",
            )

    def _handle_player_get_property(
        self,
        _conn: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        prop: str,
    ) -> GLib.Variant | None:
        if prop == "PlaybackStatus":
            if self.engine.state == PlaybackState.PLAYING:
                status = "Playing"
            elif self.engine.state == PlaybackState.PAUSED:
                status = "Paused"
            else:
                status = "Stopped"
            return GLib.Variant("s", status)
        elif prop == "LoopStatus":
            mode = "none"
            if self.window and hasattr(self.window, "cfg"):
                mode = self.window.cfg.get("repeat_mode", "none")
            if mode == "one":
                return GLib.Variant("s", "Track")
            elif mode == "all":
                return GLib.Variant("s", "Playlist")
            return GLib.Variant("s", "None")
        elif prop == "Rate":
            return GLib.Variant("d", 1.0)
        elif prop == "Shuffle":
            is_shuffled = False
            if self.window and hasattr(self.window, "cfg"):
                is_shuffled = self.window.cfg.get("shuffle", False)
            return GLib.Variant("b", is_shuffled)
        elif prop == "Metadata":
            return self._build_metadata_variant()
        elif prop == "Volume":
            return GLib.Variant("d", self.engine.volume)
        elif prop == "Position":
            pos_us = int(self.engine.get_position() * 1_000_000.0)
            return GLib.Variant("x", pos_us)
        elif prop in ("MinimumRate", "MaximumRate"):
            return GLib.Variant("d", 1.0)
        elif prop in ("CanGoNext", "CanGoPrevious", "CanPlay", "CanPause", "CanSeek", "CanControl"):
            return GLib.Variant("b", True)
        return None

    def _handle_player_set_property(
        self,
        _conn: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        prop: str,
        value: GLib.Variant,
    ) -> bool:
        if prop == "Volume":
            vol = value.get_double()
            GLib.idle_add(self.engine.set_volume, vol)
            self._notify_property_changed({"Volume": GLib.Variant("d", vol)})
            return True
        elif prop == "LoopStatus":
            val = value.get_string()
            if val == "Track":
                mode = "one"
            elif val == "Playlist":
                mode = "all"
            else:
                mode = "none"
            if self.window and hasattr(self.window, "set_repeat_mode"):
                if GLib.MainContext.default().is_owner():
                    self.window.set_repeat_mode(mode)
                else:
                    GLib.idle_add(self.window.set_repeat_mode, mode)
            else:
                self._notify_property_changed({"LoopStatus": GLib.Variant("s", val)})
            return True
        elif prop == "Shuffle":
            shuf = value.get_boolean()
            if self.window and hasattr(self.window, "set_shuffle"):
                if GLib.MainContext.default().is_owner():
                    self.window.set_shuffle(shuf)
                else:
                    GLib.idle_add(self.window.set_shuffle, shuf)
            else:
                self._notify_property_changed({"Shuffle": GLib.Variant("b", shuf)})
            return True
        return False

    def _build_metadata_variant(self) -> GLib.Variant:
        track = self.engine.current_track
        meta: dict[str, GLib.Variant] = {}

        if not track:
            meta["mpris:trackid"] = GLib.Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")
            return GLib.Variant("a{sv}", meta)

        track_hash = abs(hash(track.filepath))
        meta["mpris:trackid"] = GLib.Variant("o", f"/org/mpris/MediaPlayer2/track/{track_hash}")
        meta["mpris:length"] = GLib.Variant("x", int(track.duration * 1_000_000.0))
        meta["xesam:title"] = GLib.Variant("s", track.title or os.path.basename(track.filepath))

        if track.artist:
            meta["xesam:artist"] = GLib.Variant("as", [track.artist])
        if track.album:
            meta["xesam:album"] = GLib.Variant("s", track.album)
        if track.album_artist or track.artist:
            meta["xesam:albumArtist"] = GLib.Variant("as", [track.album_artist or track.artist])

        meta["xesam:url"] = GLib.Variant("s", "file://" + os.path.abspath(track.filepath))

        if self._has_cached_cover and os.path.isfile(self._cover_cache_path):
            meta["mpris:artUrl"] = GLib.Variant("s", "file://" + os.path.abspath(self._cover_cache_path))

        return GLib.Variant("a{sv}", meta)

    # -------------------------------------------------------------------------
    # Notificaciones de cambio al bus D-Bus
    # -------------------------------------------------------------------------

    def _notify_property_changed(self, changed_props: dict[str, GLib.Variant]):
        if not self._connection:
            return
        try:
            params = GLib.Variant(
                "(sa{sv}as)",
                (
                    "org.mpris.MediaPlayer2.Player",
                    changed_props,
                    [],
                ),
            )
            self._connection.emit_signal(
                None,
                "/org/mpris/MediaPlayer2",
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                params,
            )
        except Exception as e:
            log.warning("Error emitiendo PropertiesChanged MPRIS2: %s", e)

    notify_property_changed = _notify_property_changed

    def _on_playback_state_changed(self, state: PlaybackState):
        if state == PlaybackState.PLAYING:
            status = "Playing"
        elif state == PlaybackState.PAUSED:
            status = "Paused"
        else:
            status = "Stopped"

        self._notify_property_changed({"PlaybackStatus": GLib.Variant("s", status)})

    def _on_track_changed(self, track: AudioTrack):
        # Actualizar carátula en caché para clientes MPRIS
        self._has_cached_cover = False
        try:
            cover_info = track.get_cover_image_bytes()
            if cover_info:
                data, _ = cover_info
                with open(self._cover_cache_path, "wb") as f:
                    f.write(data)
                self._has_cached_cover = True
        except Exception as e:
            log.warning("No se pudo cachear carátula para MPRIS: %s", e)

        # Notificar metadatos nuevos
        self._notify_property_changed({
            "Metadata": self._build_metadata_variant(),
            "PlaybackStatus": GLib.Variant("s", "Playing" if self.engine.state == PlaybackState.PLAYING else "Paused"),
        })

    # -------------------------------------------------------------------------
    # Acciones de la aplicación
    # -------------------------------------------------------------------------

    def _action_raise(self):
        if self.window:
            self.window.present()

    def _action_quit(self):
        app = self.window.get_application()
        if app:
            app.quit()
        else:
            self.window.close()
