"""Rocky's lines."""

from __future__ import annotations

import random

from rockyvox.quotes import ROCKY_LINES, random_line, shuffled_lines


def test_there_are_enough_lines_to_be_worth_cycling():
    assert len(ROCKY_LINES) >= 10


def test_the_lines_are_unique_and_non_empty():
    assert len(set(ROCKY_LINES)) == len(ROCKY_LINES)
    assert all(line.strip() for line in ROCKY_LINES)


def test_the_lines_fit_the_synthesiser_limit():
    from rockyvox.speech import MAX_TEXT_LENGTH, clean_text

    for line in ROCKY_LINES:
        assert clean_text(line) == line, line
        assert len(line) <= MAX_TEXT_LENGTH


def test_random_line_comes_from_the_set():
    assert random_line(random.Random(0)) in ROCKY_LINES


def test_shuffled_lines_is_a_permutation():
    lines = shuffled_lines(random.Random(3))
    assert sorted(lines) == sorted(ROCKY_LINES)
    assert lines != list(ROCKY_LINES)
