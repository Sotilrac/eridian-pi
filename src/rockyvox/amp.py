"""MAX9744 20W class-D amplifier control over I2C.

The MAX9744 has no registers: volume is a single raw byte, 0-63, written to
the device address. I2C carries volume only -- audio reaches the amp as an
analog line signal from the I2S DAC.

Every hardware call fails soft. An unpowered or unwired amp logs a warning
and the rest of the appliance (sensor, playback, web UI) keeps working.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

VOLUME_MIN = 0
VOLUME_MAX = 63


class Amplifier(Protocol):
    """The surface the controller and web layer depend on."""

    @property
    def volume(self) -> int: ...

    @property
    def max_volume(self) -> int: ...

    @property
    def configured_max_volume(self) -> int: ...

    def set_max_volume(self, value: int) -> int: ...

    def set_volume(self, value: int) -> int: ...

    def set_enabled(self, enabled: bool) -> None: ...

    @property
    def online(self) -> bool: ...

    def close(self) -> None: ...


class Max9744:
    def __init__(
        self,
        bus: int = 1,
        address: int = 0x4B,
        max_volume: int = VOLUME_MAX,
        initial_volume: int = 30,
        shutdown_pin: int | None = None,
        on_change: Callable[[int], None] | None = None,
    ) -> None:
        #: Called with the new level whenever the volume moves, so
        #: the caller can persist it. A figurine gets unplugged rather than
        #: shut down, so waiting for SIGTERM to save loses the setting.
        self._on_change = on_change
        self._address = address
        self._bus_number = bus
        #: The cap from config, and the cap currently in force. They differ
        #: only while the ceiling has been deliberately lifted.
        self._configured_max = max(VOLUME_MIN, min(VOLUME_MAX, max_volume))
        self._max_volume = self._configured_max
        self._lock = threading.Lock()
        self._volume = self._clamp(initial_volume)
        self._online = False
        self._bus = self._open_bus(bus)
        self._shutdown = self._open_shutdown(shutdown_pin)
        self.set_volume(self._volume)

    # -- construction helpers ------------------------------------------
    def _open_bus(self, bus: int):
        try:
            from smbus2 import SMBus  # imported lazily: absent on dev machines
        except ImportError:
            log.warning("smbus2 unavailable; amplifier volume control disabled")
            return None
        try:
            return SMBus(bus)
        except OSError as exc:
            log.warning("cannot open I2C bus %d (%s); is dtparam=i2c_arm=on set?", bus, exc)
            return None

    def _open_shutdown(self, pin: int | None):
        if pin is None:
            return None
        try:
            from gpiozero import DigitalOutputDevice
        except ImportError:
            log.warning("gpiozero unavailable; SHDN pin %d not driven", pin)
            return None
        try:
            # active_high: SHDN high enables the amplifier.
            return DigitalOutputDevice(pin, active_high=True, initial_value=False)
        except Exception as exc:  # noqa: BLE001 - any pin failure is non-fatal
            log.warning("cannot claim SHDN pin %d (%s)", pin, exc)
            return None

    # -- public API ------------------------------------------------------
    @property
    def online(self) -> bool:
        return self._online

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def max_volume(self) -> int:
        return self._max_volume

    @property
    def configured_max_volume(self) -> int:
        return self._configured_max

    def set_max_volume(self, value: int) -> int:
        """Raise or lower the ceiling, pulling the level down if it now exceeds it.

        Deliberately not persisted: the cap is there to keep a 10W speaker
        alive on a 20W amplifier, so lifting it should not outlive a reboot.
        """
        self._max_volume = max(VOLUME_MIN, min(VOLUME_MAX, int(value)))
        if self._volume > self._max_volume:
            self.set_volume(self._max_volume)
        return self._max_volume

    def _clamp(self, value: int) -> int:
        return max(VOLUME_MIN, min(self._max_volume, int(value)))

    def set_volume(self, value: int) -> int:
        """Write a clamped 0-63 level to the amp. Returns the level applied."""
        level = self._clamp(value)
        with self._lock:
            changed = level != self._volume
            self._volume = level
            if self._bus is None:
                self._online = False
            else:
                try:
                    self._bus.write_byte(self._address, level & 0x3F)
                    self._online = True
                except OSError as exc:
                    if self._online:
                        log.warning("MAX9744 at 0x%02x not responding (%s)", self._address, exc)
                    self._online = False
        # Outside the lock: the hook writes a file and must not block I2C.
        if changed:
            self._notify(level)
        return level

    def _notify(self, level: int) -> None:
        """Tell the owner the level moved. Never let that break playback."""
        if self._on_change is None:
            return
        try:
            self._on_change(level)
        except Exception as exc:  # noqa: BLE001 - persistence is best effort
            log.warning("volume change hook failed (%s)", exc)

    def set_enabled(self, enabled: bool) -> None:
        """Drive SHDN, if wired. Silences idle class-D hiss between clips."""
        if self._shutdown is None:
            return
        try:
            self._shutdown.value = bool(enabled)
        except Exception as exc:  # noqa: BLE001
            log.warning("cannot drive SHDN (%s)", exc)

    def close(self) -> None:
        self.set_enabled(False)
        if self._shutdown is not None:
            self._shutdown.close()
            self._shutdown = None
        if self._bus is not None:
            self._bus.close()
            self._bus = None


class NullAmplifier:
    """Stand-in used on machines with no I2C, and in tests."""

    def __init__(self, initial_volume: int = 30, max_volume: int = VOLUME_MAX) -> None:
        self._configured_max = max_volume
        self._max_volume = max_volume
        self._volume = min(initial_volume, max_volume)
        self.enabled = False

    @property
    def online(self) -> bool:
        return False

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def max_volume(self) -> int:
        return self._max_volume

    @property
    def configured_max_volume(self) -> int:
        return self._configured_max

    def set_max_volume(self, value: int) -> int:
        self._max_volume = max(VOLUME_MIN, min(VOLUME_MAX, int(value)))
        self._volume = min(self._volume, self._max_volume)
        return self._max_volume

    def set_volume(self, value: int) -> int:
        self._volume = max(VOLUME_MIN, min(self._max_volume, int(value)))
        return self._volume

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def close(self) -> None:
        pass
