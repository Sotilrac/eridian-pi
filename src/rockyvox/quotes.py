"""Rocky's own lines, used to seed the synthesiser's input field.

Drawn from the published book-quote collections rather than from memory.
Lines circulating from the film adaptation were left out where they looked
unreliable; one widely reposted list has Rocky naming a character from a
different Andy Weir novel entirely.

They are only placeholder text, so extend the tuple freely.
"""

from __future__ import annotations

import random

#: Rocky's speech has a shape to it: the trailing "question", the flat
#: one-word verdicts, the compound nouns built out of words he already knows.
ROCKY_LINES: tuple[str, ...] = (
    "Fist my bump.",
    "Amaze. Amaze. Amaze.",
    "Usually you not stupid. Why stupid, question?",
    "Grumpy. Angry. Stupid. How long since last sleep, question?",
    "Good. Proud. I am scary space monster. You are leaky space blob.",
    "This is happy. Your face opening is in sad mode. Why, question?",
    "Question? You observe? You watch me sleep? Why, friend?",
    "Be careful. You are friend now.",
    "Need word: to risk self to help another.",
    "Understand.",
    "Sarcasm.",
    "Work fast.",
    "Check tanks!",
    "Only us.",
    "Thank.",
)


def random_line(rng: random.Random | None = None) -> str:
    return (rng or random).choice(ROCKY_LINES)


def shuffled_lines(rng: random.Random | None = None) -> list[str]:
    """Every line in a random order, so the UI cycles without repeating."""
    lines = list(ROCKY_LINES)
    (rng or random).shuffle(lines)
    return lines
