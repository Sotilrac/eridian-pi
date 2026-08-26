"""The question guarding the volume ceiling.

The cap exists because the MAX9744 can deliver 20W into 4 ohms and the
speaker is rated for 10. Lifting it is a real decision about hardware, so it
is gated rather than exposed as a plain toggle.

The book opens with a computer asking a barely conscious Ryland Grace what
two plus two is, and refusing to move on until he answers. Same idea here.
"""

from __future__ import annotations

import re

UNCAP_QUESTION = "What's two plus two?"

#: Grace eventually spits out the word; the digit is fair game too.
_ACCEPTED = frozenset({"4", "four"})
_STRIP = re.compile(r"[^a-z0-9]+")


def answer_is_correct(answer: str | None) -> bool:
    """True for "four", "4", and the obvious variations in spacing and case."""
    return _STRIP.sub("", (answer or "").lower()) in _ACCEPTED
