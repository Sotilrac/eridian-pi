"""Hall effect sensor input.

Digital halls such as the A3144 have an open-collector output: they pull the
line LOW while a magnet is present and let the Pi's internal pull-up take it
HIGH when the magnet leaves. In gpiozero terms, with ``pull_up=True``,
magnet present reads as "pressed".

The polarity is configurable so a sensor with the opposite sense, or a magnet
mounted the other way round, needs no code change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)


class Sensor(Protocol):
    @property
    def magnet_present(self) -> bool: ...

    def close(self) -> None: ...


class HallSensor:
    """Wraps a gpiozero ``Button`` and reports magnet edges.

    The initial state is read but deliberately *not* fired as an edge: a Pi
    that boots with the block already pulled should come up quiet rather than
    launching into a clip 30 seconds after power-on.
    """

    def __init__(
        self,
        pin: int,
        on_present: Callable[[], None],
        on_absent: Callable[[], None],
        magnet_present_is_low: bool = True,
        bounce_seconds: float = 0.05,
    ) -> None:
        from gpiozero import Button  # imported lazily: absent on dev machines

        self._present_is_low = magnet_present_is_low
        self._button = Button(pin, pull_up=True, bounce_time=bounce_seconds or None)

        low_handler, high_handler = (
            (on_present, on_absent) if magnet_present_is_low else (on_absent, on_present)
        )
        # "pressed" is the line going LOW, "released" is it going HIGH.
        self._button.when_pressed = lambda *_: low_handler()
        self._button.when_released = lambda *_: high_handler()

        log.info(
            "hall sensor on GPIO%d; magnet %s at startup",
            pin,
            "present" if self.magnet_present else "absent",
        )

    @property
    def magnet_present(self) -> bool:
        line_is_low = self._button.is_pressed
        return line_is_low if self._present_is_low else not line_is_low

    def close(self) -> None:
        self._button.close()


class NullSensor:
    """Stand-in for machines with no GPIO. The web trigger still works."""

    def __init__(self, magnet_present: bool = True) -> None:
        self._present = magnet_present

    @property
    def magnet_present(self) -> bool:
        return self._present

    def close(self) -> None:
        pass


def create_sensor(
    pin: int,
    on_present: Callable[[], None],
    on_absent: Callable[[], None],
    magnet_present_is_low: bool = True,
    bounce_seconds: float = 0.05,
) -> Sensor:
    """Build a real sensor, falling back to a null one if GPIO is unavailable."""
    try:
        return HallSensor(
            pin=pin,
            on_present=on_present,
            on_absent=on_absent,
            magnet_present_is_low=magnet_present_is_low,
            bounce_seconds=bounce_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - missing lib, busy pin, no /dev/gpiochip
        log.warning("hall sensor on GPIO%d unavailable (%s); running without it", pin, exc)
        return NullSensor()
