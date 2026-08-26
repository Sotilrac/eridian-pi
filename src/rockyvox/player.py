"""Audio playback via ``aplay``.

Clips are transcoded to WAV at upload time, so playback here is a raw PCM
push with no decoding. On a 1GHz armv6 single core that is the difference
between a clip starting the instant the magnet leaves and starting a beat
later, which is the whole feel of the thing.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

_TERMINATE_GRACE_SECONDS = 2.0


class Player(Protocol):
    def play_blocking(self, path: Path) -> bool: ...

    def stop(self) -> None: ...

    def snapshot(self) -> tuple[bool, Path | None]: ...

    @property
    def is_playing(self) -> bool: ...

    @property
    def current(self) -> Path | None: ...


class AplayPlayer:
    def __init__(self, device: str = "default") -> None:
        self._device = device
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._current: Path | None = None

    def snapshot(self) -> tuple[bool, Path | None]:
        """Whether a clip is running and which one, read under one lock.

        Two separate reads can straddle a start or a stop and report
        "playing, but nothing is playing".
        """
        with self._lock:
            active = self._proc is not None and self._proc.poll() is None
            return active, (self._current if active else None)

    @property
    def is_playing(self) -> bool:
        return self.snapshot()[0]

    @property
    def current(self) -> Path | None:
        return self.snapshot()[1]

    def play_blocking(self, path: Path) -> bool:
        """Play ``path`` to completion.

        Returns True if the clip finished on its own, False if it was stopped
        or failed to start. Blocks the calling thread; ``stop()`` is safe to
        call from another one.
        """
        try:
            proc = self._start(path)
        except OSError as exc:
            log.error("cannot start aplay for %s (%s)", path, exc)
            return False

        returncode = proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._current = None

        if returncode != 0:
            # A negative code means we signalled it, which is a normal stop.
            if returncode > 0:
                log.warning("aplay exited %d playing %s", returncode, path.name)
            return False
        return True

    def _start(self, path: Path) -> subprocess.Popen:
        self.stop()
        proc = subprocess.Popen(
            ["aplay", "-q", "-D", self._device, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._proc = proc
            self._current = path
        return proc

    def stop(self) -> None:
        """Kill any running clip. Idempotent, and safe to call from any thread."""
        with self._lock:
            proc = self._proc
            self._proc = None
            self._current = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            log.warning("aplay ignored SIGTERM; killing")
            proc.kill()
            proc.wait()
