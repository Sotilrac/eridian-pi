"""MAX9744 volume control over I2C."""

from __future__ import annotations

import pytest

from rockyvox.amp import Max9744, NullAmplifier


@pytest.fixture
def make_amp(bus, monkeypatch):
    monkeypatch.setattr(Max9744, "_open_bus", lambda self, _n: bus)
    monkeypatch.setattr(Max9744, "_open_shutdown", lambda self, _p: None)

    def build(**kwargs):
        return Max9744(**kwargs)

    return build


def test_the_initial_volume_is_written_at_startup(make_amp, bus):
    make_amp(initial_volume=21)
    assert bus.writes == [(0x4B, 21)]


def test_volume_is_a_bare_byte_at_the_device_address(make_amp, bus):
    amp = make_amp(initial_volume=0, address=0x4C)
    bus.writes.clear()
    amp.set_volume(63)
    assert bus.writes == [(0x4C, 63)]


def test_volume_is_capped_to_protect_the_speaker(make_amp, bus):
    amp = make_amp(initial_volume=0, max_volume=45)
    bus.writes.clear()

    assert amp.set_volume(63) == 45
    assert amp.volume == 45
    assert bus.writes == [(0x4B, 45)]


def test_negative_volume_clamps_to_mute(make_amp):
    amp = make_amp(initial_volume=10)
    assert amp.set_volume(-5) == 0


def test_a_missing_amp_does_not_raise(make_amp, bus):
    amp = make_amp(initial_volume=10)
    bus.fail = True

    assert amp.set_volume(20) == 20  # the request is still recorded
    assert amp.volume == 20
    assert amp.online is False


def test_the_amp_reports_online_once_a_write_lands(make_amp):
    amp = make_amp(initial_volume=10)
    assert amp.online is True


def test_no_i2c_bus_degrades_quietly(monkeypatch):
    monkeypatch.setattr(Max9744, "_open_bus", lambda self, _n: None)
    monkeypatch.setattr(Max9744, "_open_shutdown", lambda self, _p: None)

    amp = Max9744(initial_volume=30)
    assert amp.online is False
    assert amp.set_volume(40) == 40
    amp.set_enabled(True)  # no SHDN wired: a no-op, not a crash
    amp.close()


def test_shdn_is_driven_when_wired(make_amp, monkeypatch):
    class FakeOutput:
        def __init__(self):
            self.value = False
            self.closed = False

        def close(self):
            self.closed = True

    pin = FakeOutput()
    monkeypatch.setattr(Max9744, "_open_shutdown", lambda self, _p: pin)

    amp = make_amp(initial_volume=10, shutdown_pin=27)
    amp.set_enabled(True)
    assert pin.value is True
    amp.set_enabled(False)
    assert pin.value is False
    amp.close()
    assert pin.closed is True


def test_the_null_amp_satisfies_the_protocol():
    amp = NullAmplifier(initial_volume=30, max_volume=45)
    assert amp.online is False
    assert amp.set_volume(99) == 45
    amp.set_enabled(True)
    assert amp.enabled is True
    amp.close()
