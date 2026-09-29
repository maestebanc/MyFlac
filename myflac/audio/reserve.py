"""Reserva de tarjetas de sonido mediante el protocolo D-Bus org.freedesktop.ReserveDevice1.

PipeWire/WirePlumber mantiene abiertas las tarjetas ALSA y publica en el bus de sesión el nombre
org.freedesktop.ReserveDevice1.Audio<N> por cada una. Si otra aplicación adquiere ese nombre con
mayor prioridad, WirePlumber cierra el dispositivo y lo deja libre para acceso exclusivo (hw:X,Y).
"""
from __future__ import annotations

import glob
import time
from typing import Callable

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

# Respuestas de org.freedesktop.DBus.RequestName
_PRIMARY_OWNER = 1
_IN_QUEUE = 2
_ALREADY_OWNER = 4

# WirePlumber reserva con prioridad -20; cualquier valor mayor le obliga a liberar
RESERVE_PRIORITY = 10


def pcm_is_closed(card: int, device: int | None) -> bool:
    """True si nadie tiene abierto el PCM de reproducción hw:card,device (según /proc/asound)."""
    paths = glob.glob(f"/proc/asound/card{card}/pcm{device or 0}p/sub*/status")
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                if f.readline().strip() != "closed":
                    return False
        except OSError:
            pass
    return True  # Sin /proc/asound no se puede comprobar; se intentará abrir igualmente


def wait_until_pcm_closed(card: int, device: int | None, timeout: float = 2.0) -> bool:
    """
    Espera a que nadie tenga abierto el PCM de reproducción hw:card,device. Al ceder la reserva,
    WirePlumber cierra la tarjeta de forma asíncrona: abrirla antes da "Device or resource busy".
    Bloquea: el motor solo la usa cuando no ha podido esperar antes con temporizadores de GLib.
    """
    deadline = time.monotonic() + timeout
    while not pcm_is_closed(card, device):
        if time.monotonic() >= deadline:
            log.warning("hw:%d,%s sigue abierto por otro proceso tras %.1fs", card, device, timeout)
            return False
        time.sleep(0.02)
    return True


# Objetos D-Bus exportados por tarjeta y reservas que MyFlac tiene ahora mismo. Los objetos se
# mantienen registrados mientras viva la aplicación: WirePlumber intenta recuperar la tarjeta en
# cuanto la cede y nos llama a RequestRelease. Si esa llamada falla porque el objeto ya se retiró
# (reserva liberada entre medias), WirePlumber abandona la tarjeta hasta que se reinicia.
_exported: dict[int, int] = {}
# Momento en que se liberó cada tarjeta. Si se vuelve a pedir en pocos milisegundos, WirePlumber
# está aún a mitad de recuperarla y su estado interno se corrompe ("assertion 'self->owner_id == 0'
# failed"): deja de gestionar la tarjeta hasta reiniciarlo. Se espera este margen antes de pedirla.
_last_release: dict[int, float] = {}
REACQUIRE_COOLDOWN_S = 1.0
_held: set[str] = set()
_device_names: dict[int, str] = {}


def _on_method_call(_conn, _sender, path, _iface, method, _params, invocation):
    if method == "RequestRelease":
        bus_name = _IFACE + "." + path.rsplit("/", 1)[-1]
        # Mientras MyFlac reproduce en exclusiva no cede la tarjeta; si ya no la tiene, no se opone
        invocation.return_value(GLib.Variant("(b)", (bus_name not in _held,)))
    else:
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)


def _on_get_property(_conn, _sender, path, _iface, prop):
    card = int(path.rsplit("Audio", 1)[-1])
    if prop == "Priority":
        return GLib.Variant("i", RESERVE_PRIORITY)
    if prop == "ApplicationName":
        return GLib.Variant("s", "MyFlac")
    if prop == "ApplicationDeviceName":
        return GLib.Variant("s", _device_names.get(card) or f"hw:{card}")
    return None


def _export_object(conn: Gio.DBusConnection, card: int, object_path: str):
    if card in _exported:
        return
    node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
    _exported[card] = conn.register_object(
        object_path, node_info.interfaces[0], _on_method_call, _on_get_property, None,
    )


class AudioDeviceReservation:
    """Reserva una tarjeta ALSA (por índice) frente a PipeWire/WirePlumber."""

    def __init__(self, card_index: int, device_name: str = ""):
        self.card_index = card_index
        self.device_name = device_name
        self.bus_name = f"{_IFACE}.Audio{card_index}"
        self.object_path = f"/org/freedesktop/ReserveDevice1/Audio{card_index}"
        self._conn: Gio.DBusConnection | None = None
        self.acquired = False

    def acquire(self) -> bool:
        """Adquiere la reserva pidiendo al propietario actual que libere la tarjeta."""
        if self.acquired:
            return True
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if self.device_name:
                _device_names[self.card_index] = self.device_name
            _export_object(self._conn, self.card_index, self.object_path)

            # Primero se entra en la cola del nombre y después se pide al propietario que lo suelte:
            # el bus nos pasa la propiedad en el mismo instante en que WirePlumber lo libera.
            # - Con REPLACE_EXISTING se le quitaba antes de que lo soltara: su ReleaseName fallaba
            #   ("Unexpected reply 3") y su máquina de estados quedaba rota.
            # - Esperando a que quedara libre, WirePlumber lo recuperaba él mismo antes que nosotros.
            result = self._request_name(0)
            if result == _IN_QUEUE:
                if not self._ask_owner_release():
                    log.warning("El propietario de %s rechazó liberar la tarjeta", self.bus_name)
                    self._leave_name_queue()
                    return False
                if self._wait_name_owned():
                    result = _PRIMARY_OWNER
                else:
                    log.warning("%s no se ha liberado a tiempo; no se fuerza para no bloquear WirePlumber",
                                self.bus_name)
                    self._leave_name_queue()

            if result not in (_PRIMARY_OWNER, _ALREADY_OWNER):
                log.warning("No se pudo adquirir %s (resultado=%s)", self.bus_name, result)
                return False

            _held.add(self.bus_name)
            self.acquired = True
            log.info("Tarjeta ALSA %d reservada en exclusiva (%s)", self.card_index, self.bus_name)
            return True
        except GLib.Error as e:
            log.warning("Error reservando %s: %s", self.bus_name, e.message)
            self._leave_name_queue()
            return False

    def acquire_async(self, callback: Callable[[bool], None]):
        """
        Como acquire(), pero sin bloquear el hilo principal: la petición a WirePlumber es asíncrona
        y la espera del traspaso del nombre se hace con temporizadores de GLib. callback(éxito).
        """
        if self.acquired:
            GLib.idle_add(lambda: (callback(True), False)[1])
            return
        wait = _last_release.get(self.card_index, 0.0) + REACQUIRE_COOLDOWN_S - time.monotonic()
        if wait > 0:
            GLib.timeout_add(int(wait * 1000) + 1, lambda: (self.acquire_async(callback), False)[1])
            return

        def done(ok: bool):
            if ok:
                _held.add(self.bus_name)
                self.acquired = True
                log.info("Tarjeta ALSA %d reservada en exclusiva (%s)", self.card_index, self.bus_name)
            else:
                self._leave_name_queue()
            callback(ok)

        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            if self.device_name:
                _device_names[self.card_index] = self.device_name
            _export_object(self._conn, self.card_index, self.object_path)
            result = self._request_name(0)  # Al demonio de D-Bus: inmediato
        except GLib.Error as e:
            log.warning("Error reservando %s: %s", self.bus_name, e.message)
            GLib.idle_add(lambda: (done(False), False)[1])
            return

        if result in (_PRIMARY_OWNER, _ALREADY_OWNER):
            GLib.idle_add(lambda: (done(True), False)[1])
            return
        if result != _IN_QUEUE:
            log.warning("No se pudo adquirir %s (resultado=%s)", self.bus_name, result)
            GLib.idle_add(lambda: (done(False), False)[1])
            return

        me = self._conn.get_unique_name()
        deadline = time.monotonic() + 2.0

        def poll_owner() -> bool:
            try:
                reply = self._conn.call_sync(
                    "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                    "GetNameOwner", GLib.Variant("(s)", (self.bus_name,)),
                    GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NONE, 1000, None,
                )
                if reply.unpack()[0] == me:
                    done(True)
                    return False
            except GLib.Error:
                pass  # Sin propietario durante el traspaso
            if time.monotonic() >= deadline:
                log.warning("%s no se ha liberado a tiempo; no se fuerza para no bloquear WirePlumber",
                            self.bus_name)
                done(False)
                return False
            return True

        def on_release_reply(conn, res):
            try:
                accepted = bool(conn.call_finish(res).unpack()[0])
            except GLib.Error as e:
                log.warning("RequestRelease falló en %s: %s", self.bus_name, e.message)
                accepted = False
            if not accepted:
                log.warning("El propietario de %s rechazó liberar la tarjeta", self.bus_name)
                done(False)
                return
            if poll_owner():
                GLib.timeout_add(10, poll_owner)

        self._conn.call(
            self.bus_name, self.object_path, _IFACE,
            "RequestRelease", GLib.Variant("(i)", (RESERVE_PRIORITY,)),
            GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NONE, 5000, None, on_release_reply,
        )

    def release(self):
        """Libera la reserva para que PipeWire recupere la tarjeta."""
        if not self.acquired or not self._conn:
            return
        # Primero se deja de negar la tarjeta y después se suelta el nombre
        _held.discard(self.bus_name)
        _last_release[self.card_index] = time.monotonic()
        try:
            self._release_name()
            log.info("Reserva liberada: %s", self.bus_name)
        except GLib.Error as e:
            log.warning("Error liberando %s: %s", self.bus_name, e.message)
        self.acquired = False

    def _request_name(self, flags: int) -> int:
        reply = self._conn.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "RequestName", GLib.Variant("(su)", (self.bus_name, flags)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        return reply.unpack()[0]

    def _wait_name_owned(self, timeout: float = 2.0) -> bool:
        """Espera a que el bus nos pase el nombre desde la cola (cuando el propietario lo suelte)."""
        me = self._conn.get_unique_name()
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = self._conn.call_sync(
                    "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                    "GetNameOwner", GLib.Variant("(s)", (self.bus_name,)),
                    GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NONE, 1000, None,
                )
                if reply.unpack()[0] == me:
                    return True
            except GLib.Error:
                pass  # Sin propietario durante el traspaso
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _leave_name_queue(self):
        if not self._conn:
            return
        try:
            self._release_name()
        except GLib.Error:
            pass

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
