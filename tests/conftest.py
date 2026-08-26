"""Fakes standing in for the Pi's hardware so the suite runs anywhere."""

from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path

import pytest


class FakePlayer:
    """A player whose clips end only when the test says so."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._finish = threading.Event()
        self._finish.set()
        self._interrupted = False
        self._current: Path | None = None
        self.starts: queue.Queue[Path] = queue.Queue()
        self.plays: list[Path] = []
        self.stop_calls = 0

    # -- Player protocol ------------------------------------------------
    def snapshot(self) -> tuple[bool, Path | None]:
        with self._lock:
            return self._current is not None, self._current

    @property
    def is_playing(self) -> bool:
        return self.snapshot()[0]

    @property
    def current(self) -> Path | None:
        return self.snapshot()[1]

    def play_blocking(self, path: Path) -> bool:
        with self._lock:
            finish = threading.Event()
            self._finish = finish
            self._interrupted = False
            self._current = path
            self.plays.append(path)
        self.starts.put(path)

        finish.wait(timeout=5.0)

        with self._lock:
            self._current = None
            return not self._interrupted

    def stop(self) -> None:
        with self._lock:
            self.stop_calls += 1
            self._interrupted = self._current is not None
            finish = self._finish
        finish.set()

    # -- test controls ---------------------------------------------------
    def finish(self) -> None:
        """End the current clip as if it had played out."""
        with self._lock:
            finish = self._finish
        finish.set()

    def next_start(self, timeout: float = 2.0) -> Path:
        return self.starts.get(timeout=timeout)

    def expect_silence(self, seconds: float = 0.35) -> None:
        try:
            unexpected = self.starts.get(timeout=seconds)
        except queue.Empty:
            return
        raise AssertionError(f"expected silence but {unexpected.name} started")


class FakeAmp:
    def __init__(self, volume: int = 30, max_volume: int = 63) -> None:
        self._volume = volume
        self._configured_max = max_volume
        self._max_volume = max_volume
        self.enabled = False
        self.enable_calls: list[bool] = []

    @property
    def online(self) -> bool:
        return True

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
        self._max_volume = max(0, min(63, int(value)))
        self._volume = min(self._volume, self._max_volume)
        return self._max_volume

    def configure_cap(self, value: int) -> None:
        """Test hook: set the cap as though it had come from config."""
        self._configured_max = value
        self.set_max_volume(value)

    def set_volume(self, value: int) -> int:
        self._volume = max(0, min(self._max_volume, int(value)))
        return self._volume

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.enable_calls.append(self.enabled)

    def close(self) -> None:
        pass


class FakeBus:
    """Records I2C byte writes, and can be told to fail like a missing amp."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []
        self.fail = False

    def write_byte(self, address: int, value: int) -> None:
        if self.fail:
            raise OSError(121, "Remote I/O error")
        self.writes.append((address, value))

    def close(self) -> None:
        pass


@pytest.fixture
def player() -> FakePlayer:
    return FakePlayer()


@pytest.fixture
def amp() -> FakeAmp:
    return FakeAmp()


@pytest.fixture
def tone(tmp_path_factory) -> Path:
    """A real one-second mp3, so ingest tests exercise ffmpeg for real."""
    path = tmp_path_factory.mktemp("audio") / "tone.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "9",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus()
