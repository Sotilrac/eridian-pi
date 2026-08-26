"""The question guarding the volume ceiling."""

from __future__ import annotations

import pytest

from rockyvox.gate import UNCAP_QUESTION, answer_is_correct


@pytest.mark.parametrize(
    "answer",
    ["four", "Four", "FOUR", "  four  ", "4", " 4.", "four!", "Four?"],
)
def test_the_right_answer_is_accepted_however_it_is_typed(answer):
    assert answer_is_correct(answer) is True


@pytest.mark.parametrize(
    "answer",
    ["", "   ", None, "5", "fourteen", "for", "2+2", "twenty-two", "IV", "0x4"],
)
def test_everything_else_is_refused(answer):
    assert answer_is_correct(answer) is False


def test_the_question_is_the_one_from_the_book():
    assert UNCAP_QUESTION == "What's two plus two?"
