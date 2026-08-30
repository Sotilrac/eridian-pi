"""Hall sensor wiring, driven through gpiozero's mock pin factory.

These prove the electrical convention maps to the right callbacks: an
open-collector hall pulls the line LOW with a magnet present, so LOW must
mean "block on the base" and HIGH must mean "block pulled off".
"""

from __future__ import annotations

import queue

import pytest

gpiozero = pytest.importorskip("gpiozero")
from gpiozero import Device  # noqa: E402
from gpiozero.pins.mock import MockFactory  # noqa: E402

from rockyvox.sensor import NullSensor, create_sensor  # noqa: E402

PIN = 17


@pytest.fixture
def pin_factory():
    factory = MockFactory()
    previous = Device.pin_factory
    Device.pin_factory = factory
    yield factory
    Device.pin_factory = previous
    factory.close()


@pytest.fixture
def events():
    return queue.Queue()


def build(events, pin_factory, magnet_present_is_low=True):
    sensor = create_sensor(
        pin=PIN,
        on_present=lambda: events.put("present"),
        on_absent=lambda: events.put("absent"),
        magnet_present_is_low=magnet_present_is_low,
        bounce_seconds=0.0,
    )
    assert not isinstance(sensor, NullSensor), "the mock factory should have been used"
    return sensor


def pin_of(factory):
    return factory.pin(PIN)


# gpiozero's mock pin drives itself high when the pull-up is configured, so
# the line must be moved *after* the Button exists, not before.


def test_the_idle_line_reads_as_a_lifted_figurine(events, pin_factory):
    sensor = build(events, pin_factory)
    try:
        assert sensor.magnet_present is False
    finally:
        sensor.close()


def test_a_low_line_reads_as_a_seated_magnet(events, pin_factory):
    sensor = build(events, pin_factory)
    try:
        pin_of(pin_factory).drive_low()
        assert events.get(timeout=2) == "present"
        assert sensor.magnet_present is True
    finally:
        sensor.close()


def test_the_startup_state_does_not_fire_an_edge(events, pin_factory):
    # A Pi that boots with the block already off must come up quiet.
    sensor = build(events, pin_factory)
    try:
        assert sensor.magnet_present is False
        with pytest.raises(queue.Empty):
            events.get(timeout=0.3)
    finally:
        sensor.close()


def test_lifting_and_seating_fire_the_right_callbacks(events, pin_factory):
    pin = pin_of(pin_factory)
    sensor = build(events, pin_factory)
    try:
        pin.drive_low()
        assert events.get(timeout=2) == "present"
        pin.drive_high()
        assert events.get(timeout=2) == "absent"
        pin.drive_low()
        assert events.get(timeout=2) == "present"
    finally:
        sensor.close()


def test_inverted_polarity_swaps_the_callbacks(events, pin_factory):
    pin = pin_of(pin_factory)
    sensor = build(events, pin_factory, magnet_present_is_low=False)
    try:
        assert sensor.magnet_present is True
        pin.drive_low()
        assert events.get(timeout=2) == "absent"
        assert sensor.magnet_present is False
    finally:
        sensor.close()


def test_a_missing_pin_factory_degrades_to_a_null_sensor(monkeypatch):
    monkeypatch.setattr(Device, "pin_factory", None)
    monkeypatch.setenv("GPIOZERO_PIN_FACTORY", "definitely-not-a-factory")

    sensor = create_sensor(pin=PIN, on_present=lambda: None, on_absent=lambda: None)
    assert isinstance(sensor, NullSensor)
    assert sensor.magnet_present is True
    sensor.close()
