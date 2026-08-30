"""The trigger state machine.

Rocky holds a block labelled "Pull me!!! Statement" with a magnet in it, and
the hall sensor sits in the body behind where it seats.

  * magnet ABSENT edge  -> draw the next clip from the shuffle bag, play it
  * still ABSENT        -> after it ends, pause, then replay *the same* clip
  * magnet PRESENT edge -> stop immediately, go quiet
  * next ABSENT edge    -> draw a *new* clip and start over

The gap between repeats waits on the same event that the sensor callbacks
signal, so pushing the block back during that gap is honoured at once rather
than up to a second later.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
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
        armed: bool = True,
        on_armed_change: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_armed_change = on_armed_change
        self._player = player
        self._amp = amp
        self._bag = ShuffleBag(clips)
        self._repeat_gap = max(0.0, repeat_gap_seconds)

        self._cond = threading.Condition()
        self._running = True
        self._magnet_present = magnet_present
        #: While disarmed the sensor is read and reported but never acted on,
        #: so the figurine can be handled without talking. Manual triggers and
        #: previews still work: disarming silences the block, not the device.
        self._armed = armed
        #: Bumped on every absent edge. The worker compares it to the value it
        #: started a session with, which is how "block went back in and came
        #: out again" becomes "advance to the next clip".
        self._generation = 0
        #: The generation the worker has already taken a turn on. A session
        #: that ends while the block is still out -- because the clip could
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
    def armed(self) -> bool:
        with self._cond:
            return self._armed

    def set_armed(self, armed: bool) -> bool:
        """Arm or disarm the magnet trigger.

        Disarming abandons any clip the sensor started, so the figurine goes
        quiet at once rather than finishing its loop.
        """
        armed = bool(armed)
        with self._cond:
            if armed == self._armed:
                return armed
            self._armed = armed
            if not armed:
                # Invalidate the running session and claim the generation, so
                # the worker neither continues nor draws a fresh clip.
                self._generation += 1
                self._served = self._generation
            self._cond.notify_all()
        if not armed:
            self._player.stop()
        log.info("magnet trigger %s", "armed" if armed else "disarmed")
        if self._on_armed_change is not None:
            try:
                self._on_armed_change(armed)
            except Exception as exc:  # noqa: BLE001 - persistence is best effort
                log.warning("arm change hook failed (%s)", exc)
        return armed

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

        A Pi that boots with the block already pulled should report it out,
        but must not start talking thirty seconds after power-on.
        """
        with self._cond:
            self._magnet_present = present
            self._served = self._generation

    # -- sensor edges ----------------------------------------------------
    def on_magnet_absent(self) -> None:
        """The block was pulled: start the next clip, unless disarmed."""
        with self._cond:
            self._magnet_present = False
            if not self._armed:
                # Keep the reported state honest, but do not act on it.
                self._served = self._generation
                return
            self._generation += 1
            self._cond.notify_all()
        # Break the worker out of whatever it is playing so it redraws.
        self._player.stop()

    def on_magnet_present(self) -> None:
        """The block was pushed back in: silence, immediately."""
        with self._cond:
            self._magnet_present = True
            if not self._armed:
                # A preview may be playing; disarmed means the magnet is inert,
                # so it must not cut that off.
                return
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

        Unlike a real pull there is no magnet to put back, so this plays a
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
                    and (
                        self._magnet_present or not self._armed or self._generation == self._served
                    )
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
        """Play ``clip``, repeating it while the block stays out.

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
            and self._armed
            and not self._magnet_present
            and self._generation == session
            and self._oneshot is None
        )
