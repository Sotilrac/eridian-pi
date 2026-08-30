"""Text to speech via espeak-ng.

Rocky speaks through a translator box, so a formant synthesiser is the right
instrument rather than a compromise: espeak-ng sounds like a machine working
out how to pronounce English, which is the character. It is also one of the
few engines that runs comfortably on an armv6 single core -- the neural
options ship no binaries for this architecture.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ESPEAK = "espeak-ng"
_TIMEOUT = 120
MAX_TEXT_LENGTH = 1000


class SpeechError(Exception):
    """Text that cannot be turned into speech."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    #: An espeak-ng voice name, optionally with a +variant suffix.
    voice: str
    #: Words per minute, 80-450.
    speed: int = 175
    #: 0-99. Lower is deeper.
    pitch: int = 50
    #: Milliseconds of silence inserted between words.
    word_gap_ms: int = 0


#: One voice only. The plain formant translator is the closest thing to how
#: Rocky sounds, and offering alternatives just invited worse ones.
VOICES: dict[str, Voice] = {
    v.id: v
    for v in (Voice(id="translator", label="Translator", voice="en-us", speed=175, pitch=50),)
}

DEFAULT_VOICE = "translator"


def available() -> bool:
    return shutil.which(ESPEAK) is not None


def resolve_voice(voice_id: str | None) -> Voice:
    return VOICES.get(voice_id or DEFAULT_VOICE, VOICES[DEFAULT_VOICE])


def clean_text(text: str) -> str:
    """Normalise submitted text, or raise if there is nothing to say."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise SpeechError("nothing to say")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise SpeechError(f"text is {len(cleaned)} characters, limit is {MAX_TEXT_LENGTH}")
    return cleaned


def title_for(text: str, limit: int = 60) -> str:
    """A clip title derived from the spoken line."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def synthesize(text: str, voice_id: str | None = None, target: Path | None = None) -> Path:
    """Render ``text`` to a WAV file and return its path.

    The caller owns the result and is responsible for deleting it.
    """
    if not available():
        raise SpeechError("espeak-ng is not installed")

    spoken = clean_text(text)
    voice = resolve_voice(voice_id)

    if target is None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            target = Path(tmp.name)

    command = [
        ESPEAK,
        "-v",
        voice.voice,
        "-s",
        str(voice.speed),
        "-p",
        str(voice.pitch),
        "-g",
        str(voice.word_gap_ms),
        "-w",
        str(target),
        "--",
        spoken,  # -- stops a line starting with '-' being read as a flag
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as exc:
        target.unlink(missing_ok=True)
        raise SpeechError("espeak-ng is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        target.unlink(missing_ok=True)
        raise SpeechError("speech synthesis timed out") from exc

    if result.returncode != 0:
        target.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()
        raise SpeechError(detail[-1][:200] if detail else "speech synthesis failed")

    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise SpeechError("speech synthesis produced no audio")

    return target
