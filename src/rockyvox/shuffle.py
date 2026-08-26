"""A shuffle bag: every clip plays once before any clip plays twice."""

from __future__ import annotations

import random
import threading
from collections.abc import Iterable, Sequence


class ShuffleBag:
    """Draws items in a random order without repeats until the bag empties.

    When the bag refills, the first draw of the new bag is swapped away from
    the previously drawn item so a reshuffle never produces a back-to-back
    repeat across the seam.
    """

    def __init__(self, items: Iterable[str] = (), rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._items: list[str] = []
        self._bag: list[str] = []
        self._last: str | None = None
        self.replace(items)

    @property
    def items(self) -> Sequence[str]:
        with self._lock:
            return tuple(self._items)

    @property
    def last_drawn(self) -> str | None:
        with self._lock:
            return self._last

    def replace(self, items: Iterable[str]) -> None:
        """Swap in a new item set, discarding whatever was left in the bag.

        Called whenever the clip library changes. ``_last`` survives so the
        no-immediate-repeat rule still holds across an upload or delete.
        """
        with self._lock:
            self._items = list(items)
            self._bag = []
            if self._last is not None and self._last not in self._items:
                self._last = None

    def draw(self) -> str | None:
        """Return the next item, or ``None`` when there is nothing to draw."""
        with self._lock:
            if not self._items:
                return None
            if not self._bag:
                self._refill()
            item = self._bag.pop()
            self._last = item
            return item

    def _refill(self) -> None:
        """Reshuffle, keeping the seam free of a back-to-back repeat."""
        self._bag = list(self._items)
        self._rng.shuffle(self._bag)
        # draw() pops from the end, so the *last* element is the next draw.
        if len(self._bag) > 1 and self._bag[-1] == self._last:
            self._bag[-1], self._bag[0] = self._bag[0], self._bag[-1]
