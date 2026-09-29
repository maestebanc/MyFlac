"""Protocolo org.freedesktop.ReserveDevice1 frente a WirePlumber (sin bus real)."""
import pytest

from myflac.audio import reserve
from myflac.audio.reserve import AudioDeviceReservation


class _FakeInvocation:
    def __init__(self):
        self.value = None
        self.error = None

    def return_value(self, variant):
        self.value = variant.unpack()[0]

    def return_dbus_error(self, name, _msg):
        self.error = name


class _FakeConn:
    def get_unique_name(self):
        return ":1.99"


@pytest.fixture
def reservation(monkeypatch):
    """Reserva de la tarjeta 7 con las llamadas D-Bus sustituidas por un guion controlable."""
    monkeypatch.setattr(reserve.Gio, "bus_get_sync", lambda *_: _FakeConn())
    monkeypatch.setattr(reserve, "_export_object", lambda *_: None)
    monkeypatch.setattr(reserve, "_held", set())
    res = AudioDeviceReservation(7, "DAC")
    res.calls = []
    res.script = {"request": [], "release_accepted": True, "owned": True}

    def request_name(flags):
        res.calls.append(("RequestName", flags))
        return res.script["request"].pop(0)

    def ask_owner_release():
        res.calls.append(("RequestRelease",))
        return res.script["release_accepted"]

    def wait_name_owned(timeout=2.0):
        res.calls.append(("WaitOwned",))
        return res.script["owned"]

    def release_name():
        res.calls.append(("ReleaseName",))

    monkeypatch.setattr(res, "_request_name", request_name)
    monkeypatch.setattr(res, "_ask_owner_release", ask_owner_release)
    monkeypatch.setattr(res, "_wait_name_owned", wait_name_owned)
    monkeypatch.setattr(res, "_release_name", release_name)
    return res


def test_free_card_is_taken_without_asking_anyone(reservation):
    reservation.script["request"] = [1]  # PRIMARY_OWNER
    assert reservation.acquire()
    assert reservation.calls == [("RequestName", 0)]
    assert "org.freedesktop.ReserveDevice1.Audio7" in reserve._held


def test_owned_card_queues_first_and_never_replaces(reservation):
    # Regresión: con REPLACE_EXISTING, WirePlumber fallaba al soltar el nombre y perdía la tarjeta
    reservation.script["request"] = [2]  # IN_QUEUE
    assert reservation.acquire()
    # Flags 0: entra en la cola, sin DO_NOT_QUEUE ni REPLACE_EXISTING
    assert reservation.calls == [("RequestName", 0), ("RequestRelease",), ("WaitOwned",)]


def test_refused_release_leaves_the_queue(reservation):
    reservation.script["request"] = [2]
    reservation.script["release_accepted"] = False
    assert not reservation.acquire()
    assert reservation.calls[-1] == ("ReleaseName",)
    assert not reserve._held


def test_handover_timeout_gives_up_without_forcing(reservation):
    reservation.script["request"] = [2]
    reservation.script["owned"] = False
    assert not reservation.acquire()
    assert reservation.calls == [("RequestName", 0), ("RequestRelease",), ("WaitOwned",), ("ReleaseName",)]


def test_release_stops_denying_before_dropping_the_name(reservation):
    reservation.script["request"] = [1]
    reservation.acquire()
    reservation.release()
    assert not reserve._held
    assert reservation.calls[-1] == ("ReleaseName",)
    assert not reservation.acquired


def test_request_release_is_denied_only_while_held(monkeypatch):
    # WirePlumber pide recuperar la tarjeta en cuanto la cede: hay que contestar siempre, nunca con error
    monkeypatch.setattr(reserve, "_held", {"org.freedesktop.ReserveDevice1.Audio2"})
    path = "/org/freedesktop/ReserveDevice1/Audio2"

    held = _FakeInvocation()
    reserve._on_method_call(None, ":1.5", path, reserve._IFACE, "RequestRelease", None, held)
    assert held.value is False

    reserve._held.clear()
    released = _FakeInvocation()
    reserve._on_method_call(None, ":1.5", path, reserve._IFACE, "RequestRelease", None, released)
    assert released.value is True

    unknown = _FakeInvocation()
    reserve._on_method_call(None, ":1.5", path, reserve._IFACE, "Foo", None, unknown)
    assert unknown.error == "org.freedesktop.DBus.Error.UnknownMethod"
