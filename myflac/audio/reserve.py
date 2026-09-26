"""Reserva de tarjetas de sonido mediante el protocolo D-Bus org.freedesktop.ReserveDevice1.

PipeWire/WirePlumber mantiene abiertas las tarjetas ALSA y publica en el bus de sesión el nombre
org.freedesktop.ReserveDevice1.Audio<N> por cada una. Si otra aplicación adquiere ese nombre con
mayor prioridad, WirePlumber cierra el dispositivo y lo deja libre para acceso exclusivo (hw:X,Y).
"""
from __future__ import annotations

import glob
import time

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from ..logger import get_logger

log = get_logger("audio.reserve")

_IFACE = "org.freedesktop.ReserveDevice1"
_INTROSPECTION_XML = f"""
<node>
  <interface name="{_IFACE}">
    <method name="RequestRelease">
      <arg name="priority" type="i" direction="in"/>
      <arg name="result" type="b" direction="out"/>
    </method>
    <property name="Priority" type="i" access="read"/>
    <property name="ApplicationName" type="s" access="read"/>
    <property name="ApplicationDeviceName" type="s" access="read"/>
  </interface>
</node>
"""

# Flags de org.freedesktop.DBus.RequestName
_REPLACE_EXISTING = 0x2
_DO_NOT_QUEUE = 0x4
_PRIMARY_OWNER = 1
_ALREADY_OWNER = 4

# WirePlumber reserva con prioridad -20; cualquier valor mayor le obliga a liberar
RESERVE_PRIORITY = 10


def wait_until_pcm_closed(card: int, device: int, timeout: float = 2.0) -> bool:
    """
    Espera a que nadie tenga abierto el PCM de reproducción hw:card,device. Al ceder la reserva,
    WirePlumber cierra la tarjeta de forma asíncrona: abrirla antes da "Device or resource busy".
    """
    paths = glob.glob(f"/proc/asound/card{card}/pcm{device}p/sub*/status")
    if not paths:
        return True  # Sin /proc/asound no se puede comprobar; se intentará abrir igualmente
    deadline = time.monotonic() + timeout
    while True:
        busy = False
        for path in paths:
            try:
                with open(path, encoding="utf-8") as f:
                    busy = busy or f.readline().strip() != "closed"
            except OSError:
                pass
        if not busy:
            return True
        if time.monotonic() >= deadline:
            log.warning("hw:%d,%d sigue abierto por otro proceso tras %.1fs", card, device, timeout)
            return False
        time.sleep(0.02)


class AudioDeviceReservation:
    """Reserva una tarjeta ALSA (por índice) frente a PipeWire/WirePlumber."""

    def __init__(self, card_index: int, device_name: str = ""):
        self.card_index = card_index
        self.device_name = device_name
        self.bus_name = f"{_IFACE}.Audio{card_index}"
        self.object_path = f"/org/freedesktop/ReserveDevice1/Audio{card_index}"
        self._conn: Gio.DBusConnection | None = None
        self._registration_id = 0
        self.acquired = False

    def acquire(self) -> bool:
        """Adquiere la reserva pidiendo al propietario actual que libere la tarjeta."""
        if self.acquired:
            return True
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
            self._registration_id = self._conn.register_object(
                self.object_path,
                node_info.interfaces[0],
                self._on_method_call,
                self._on_get_property,
                None,
            )

            result = self._request_name(_DO_NOT_QUEUE)
            if result not in (_PRIMARY_OWNER, _ALREADY_OWNER):
                if not self._ask_owner_release():
                    log.warning("El propietario de %s rechazó liberar la tarjeta", self.bus_name)
                    self.release()
                    return False
                result = self._request_name(_DO_NOT_QUEUE | _REPLACE_EXISTING)

            if result not in (_PRIMARY_OWNER, _ALREADY_OWNER):
                log.warning("No se pudo adquirir %s (resultado=%s)", self.bus_name, result)
                self.release()
                return False

            self.acquired = True
            log.info("Tarjeta ALSA %d reservada en exclusiva (%s)", self.card_index, self.bus_name)
            return True
        except GLib.Error as e:
            log.warning("Error reservando %s: %s", self.bus_name, e.message)
            self.release()
            return False

    def release(self):
        """Libera la reserva para que PipeWire recupere la tarjeta."""
        if not self._conn:
            return
        if self.acquired:
            try:
                self._release_name()
                log.info("Reserva liberada: %s", self.bus_name)
            except GLib.Error as e:
                log.warning("Error liberando %s: %s", self.bus_name, e.message)
        if self._registration_id:
            self._conn.unregister_object(self._registration_id)
            self._registration_id = 0
        self.acquired = False
        self._conn = None

    def _request_name(self, flags: int) -> int:
        reply = self._conn.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "RequestName", GLib.Variant("(su)", (self.bus_name, flags)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        return reply.unpack()[0]

    def _release_name(self):
        self._conn.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "ReleaseName", GLib.Variant("(s)", (self.bus_name,)),
            None, Gio.DBusCallFlags.NONE, 2000, None,
        )

    def _ask_owner_release(self) -> bool:
        try:
            reply = self._conn.call_sync(
                self.bus_name, self.object_path, _IFACE,
                "RequestRelease", GLib.Variant("(i)", (RESERVE_PRIORITY,)),
                GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 5000, None,
            )
            return bool(reply.unpack()[0])
        except GLib.Error as e:
            log.warning("RequestRelease falló en %s: %s", self.bus_name, e.message)
            return False

    def _on_method_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method == "RequestRelease":
            # Mientras MyFlac reproduce en exclusiva no cede la tarjeta
            invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _on_get_property(self, _conn, _sender, _path, _iface, prop):
        if prop == "Priority":
            return GLib.Variant("i", RESERVE_PRIORITY)
        if prop == "ApplicationName":
            return GLib.Variant("s", "MyFlac")
        if prop == "ApplicationDeviceName":
            return GLib.Variant("s", self.device_name or f"hw:{self.card_index}")
        return None
