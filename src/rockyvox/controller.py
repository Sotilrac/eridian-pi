"""The trigger state machine.

  * magnet ABSENT edge  -> draw the next clip from the shuffle bag, play it
  * still ABSENT        -> after it ends, pause, then replay *the same* clip
  * magnet PRESENT edge -> stop immediately, go quiet
  * next ABSENT edge    -> draw a *new* clip and start over

The gap between repeats waits on the same event that the sensor callbacks
signal, so putting the figurine back down during that gap is honoured at once
rather than up to a second later.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from pathlib import Path

from .amp import Amplifier
from .player import Player
from .shuffle import ShuffleBag

log = logging.getLogger(__name__)

#: Let the MAX9744's click-and-pop suppression settle after releasing SHDN.
AMP_SETTLE_SECONDS = 0.05


class Controller:
    def __init__(
        self,
        player: Player,
        amp: Amplifier,
        clips: Iterable[str] = (),
        repeat_gap_seconds: float = 1.0,
        magnet_present: bool = True,
    ) -> None:
        self._player = player
        self._amp = amp
        self._bag = ShuffleBag(clips)
        self._repeat_gap = max(0.0, repeat_gap_seconds)

        self._cond = threading.Condition()
        self._running = True
        self._magnet_present = magnet_present
        #: Bumped on every absent edge. The worker compares it to the value it
        #: started a session with, which is how "magnet came back and left
        #: again" becomes "advance to the next clip".
        self._generation = 0
        #: The generation the worker has already taken a turn on. A session
        #: that ends while the magnet is still away -- because the clip could
        #: not be played, or the library is empty -- must stay quiet until a
        #: fresh edge arrives rather than grabbing the next clip.
        self._served = 0
        self._oneshot: Path | None = None

        self._worker = threading.Thread(target=self._run, name="controller", daemon=True)
        self._worker.start()

    # -- state -----------------------------------------------------------
    @property
    def magnet_present(self) -> bool:
        with self._cond:
            return self._magnet_present

    @property
    def is_playing(self) -> bool:
        return self._player.is_playing

    @property
    def current_clip(self) -> Path | None:
        return self._player.current

    def playback_snapshot(self) -> tuple[bool, Path | None]:
        """Whether a clip is running and which one, consistent with each other."""
        return self._player.snapshot()

    def set_clips(self, clips: Iterable[str]) -> None:
        """Rebuild the bag after an upload or delete."""
        self._bag.replace(clips)

    def sync_magnet(self, present: bool) -> None:
        """Adopt the sensor's reading at startup without treating it as an edge.

        A Pi that boots while Rocky is lifted should report him lifted, but
        must not start talking thirty seconds after power-on.
        """
        with self._cond:
            self._magnet_present = present
            self._served = self._generation

    # -- sensor edges ----------------------------------------------------
    def on_magnet_absent(self) -> None:
        """Rocky was lifted: start the next clip."""
        with self._cond:
            self._magnet_present = False
            self._generation += 1
            self._cond.notify_all()
        # Break the worker out of whatever it is playing so it redraws.
        self._player.stop()

    def on_magnet_present(self) -> None:
        """Rocky was set back down: silence, immediately."""
        with self._cond:
            self._magnet_present = True
            self._cond.notify_all()
        self._player.stop()

    # -- manual control --------------------------------------------------
    def play_once(self, path: Path) -> None:
        """Play one clip and stop. Used by the web preview."""
        with self._cond:
            self._oneshot = Path(path)
            self._cond.notify_all()
        self._player.stop()

    def trigger_once(self) -> Path | None:
        """Draw and play the next clip once, as if the magnet had left.

        Unlike a real lift there is no magnet to put back, so this plays a
        single clip rather than repeating. Handy for testing with no hardware.
        """
        clip = self._bag.draw()
        if clip is None:
            return None
        path = Path(clip)
        self.play_once(path)
        return path

    def stop(self) -> None:
        with self._cond:
            self._oneshot = None
            self._cond.notify_all()
        self._player.stop()

    def close(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        self._player.stop()
        self._worker.join(timeout=3.0)

    # -- worker ----------------------------------------------------------
    def _run(self) -> None:
        while True:
            with self._cond:
                while (
                    self._running
                    and self._oneshot is None
                    and (self._magnet_present or self._generation == self._served)
                ):
                    self._cond.wait()
                if not self._running:
                    return
                if self._oneshot is not None:
                    session = None
                    clip = self._oneshot
                    self._oneshot = None
                else:
                    session = self._generation
                    self._served = session
                    drawn = self._bag.draw()
                    clip = Path(drawn) if drawn else None

            if clip is None:
                log.warning("magnet released but the clip library is empty")
                continue

            self._play_session(clip, session)

    def _play_session(self, clip: Path, session: int | None) -> None:
        """Play ``clip``, repeating it while the magnet stays away.

        ``session is None`` means a one-shot: play it exactly once.
        """
        self._amp.set_enabled(True)
        if AMP_SETTLE_SECONDS:
            with self._cond:
                self._cond.wait(timeout=AMP_SETTLE_SECONDS)
        try:
            while True:
                completed = self._player.play_blocking(clip)

                if session is None:
                    return
                with self._cond:
                    if not self._still_active(session):
                        return
                    if not completed:
                        # Nobody interrupted us, so aplay itself failed. Bail
                        # out instead of hammering an unplayable file.
                        log.error("playback of %s failed; stopping", clip.name)
                        return
                    self._cond.wait(timeout=self._repeat_gap)
                    if not self._still_active(session):
                        return
        finally:
            self._amp.set_enabled(False)

    def _still_active(self, session: int) -> bool:
        """True while this session still owns the speaker. Caller holds the lock."""
        return (
            self._running
            and not self._magnet_present
            and self._generation == session
            and self._oneshot is None
        )
