"""The shuffle bag: every clip once before any clip twice."""

from __future__ import annotations

import random
from itertools import pairwise

from rockyvox.shuffle import ShuffleBag

CLIPS = ["a", "b", "c", "d", "e"]


def test_a_full_cycle_yields_every_clip_exactly_once():
    bag = ShuffleBag(CLIPS, rng=random.Random(1))
    drawn = [bag.draw() for _ in CLIPS]
    assert sorted(drawn) == sorted(CLIPS)


def test_order_varies_between_cycles():
    bag = ShuffleBag(CLIPS, rng=random.Random(7))
    first = [bag.draw() for _ in CLIPS]
    second = [bag.draw() for _ in CLIPS]
    assert sorted(first) == sorted(second)
    assert first != second


def test_no_repeat_across_the_reshuffle_seam():
    # Every seed must hold: the guard swaps the collision away, it does not
    # rely on the shuffle happening to avoid it.
    for seed in range(60):
        bag = ShuffleBag(CLIPS, rng=random.Random(seed))
        drawn = [bag.draw() for _ in range(len(CLIPS) * 3)]
        repeats = [(x, y) for x, y in pairwise(drawn) if x == y]
        assert not repeats, f"seed {seed} repeated {repeats}"


def test_a_single_clip_is_drawn_over_and_over():
    bag = ShuffleBag(["only"])
    assert [bag.draw() for _ in range(4)] == ["only"] * 4


def test_an_empty_bag_draws_nothing():
    bag = ShuffleBag([])
    assert bag.draw() is None


def test_replace_swaps_the_contents():
    bag = ShuffleBag(["a", "b"])
    bag.draw()
    bag.replace(["x", "y", "z"])
    assert set(bag.items) == {"x", "y", "z"}
    assert bag.draw() in {"x", "y", "z"}


def test_replace_keeps_the_no_repeat_rule_when_the_clip_survives():
    # An upload rebuilds the bag mid-cycle; the clip just played must not
    # come straight back.
    for seed in range(40):
        bag = ShuffleBag(CLIPS, rng=random.Random(seed))
        last = bag.draw()
        bag.replace([*CLIPS, "new"])
        assert bag.draw() != last, f"seed {seed}"


def test_replace_forgets_a_last_clip_that_was_deleted():
    bag = ShuffleBag(["a", "b"])
    while bag.last_drawn != "a":
        bag.draw()
    bag.replace(["b", "c"])
    assert bag.last_drawn is None
