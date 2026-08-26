"""Text to speech via espeak-ng."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from rockyvox import speech
from rockyvox.library import Library

HAS_ESPEAK = shutil.which(speech.ESPEAK) is not None
EXTENSIONS = (".mp3", ".wav")


# -- text handling -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hello   there  ", "hello there"),
        ("line one\nline two", "line one line two"),
        ("\tamaze\t", "amaze"),
    ],
)
def test_clean_text_normalises_whitespace(raw, expected):
    assert speech.clean_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", None])
def test_empty_text_is_rejected(raw):
    with pytest.raises(speech.SpeechError, match="nothing to say"):
        speech.clean_text(raw)


def test_over_long_text_is_rejected():
    with pytest.raises(speech.SpeechError, match="limit is"):
        speech.clean_text("a" * (speech.MAX_TEXT_LENGTH + 1))


def test_title_is_truncated_with_an_ellipsis():
    assert speech.title_for("short line") == "short line"
    long_title = speech.title_for("word " * 40)
    assert len(long_title) <= 60
    assert long_title.endswith("…")


# -- voices ------------------------------------------------------------


def test_the_default_voice_is_rocky():
    assert speech.resolve_voice(None).id == "rocky"
    assert speech.resolve_voice("nonsense").id == "rocky"


def test_rocky_is_deeper_and_slower_than_the_plain_translator():
    rocky = speech.resolve_voice("rocky")
    translator = speech.resolve_voice("translator")
    assert rocky.pitch < translator.pitch
    assert rocky.speed < translator.speed


def test_every_voice_stays_inside_espeak_limits():
    for voice in speech.VOICES.values():
        assert 80 <= voice.speed <= 450, voice.id
        assert 0 <= voice.pitch <= 99, voice.id
        assert voice.word_gap_ms >= 0, voice.id


# -- the espeak-ng invocation -----------------------------------------


def test_the_command_line_matches_the_chosen_voice(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        Path(command[command.index("-w") + 1]).write_bytes(b"RIFF" + b"\x00" * 64)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(speech.shutil, "which", lambda _n: "/usr/bin/espeak-ng")
    monkeypatch.setattr(speech.subprocess, "run", fake_run)

    target = tmp_path / "out.wav"
    speech.synthesize("Question.", "astrophage", target=target)

    command = captured["command"]
    voice = speech.VOICES["astrophage"]
    assert command[0] == speech.ESPEAK
    assert command[command.index("-v") + 1] == voice.voice
    assert command[command.index("-s") + 1] == str(voice.speed)
    assert command[command.index("-p") + 1] == str(voice.pitch)
    assert command[-1] == "Question."


def test_a_leading_dash_is_not_read_as_a_flag(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        Path(command[command.index("-w") + 1]).write_bytes(b"RIFF" + b"\x00" * 64)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(speech.shutil, "which", lambda _n: "/usr/bin/espeak-ng")
    monkeypatch.setattr(speech.subprocess, "run", fake_run)

    speech.synthesize("--version is not a flag here", target=tmp_path / "out.wav")
    command = captured["command"]
    assert command[-2] == "--", "the text must be separated from the options"


def test_a_missing_espeak_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _n: None)
    assert speech.available() is False
    with pytest.raises(speech.SpeechError, match="not installed"):
        speech.synthesize("hello")


def test_a_failing_espeak_surfaces_its_last_line(monkeypatch, tmp_path):
    monkeypatch.setattr(speech.shutil, "which", lambda _n: "/usr/bin/espeak-ng")
    monkeypatch.setattr(
        speech.subprocess,
        "run",
        lambda command, **_k: subprocess.CompletedProcess(command, 1, "", "bad voice: zz\n"),
    )
    with pytest.raises(speech.SpeechError, match="bad voice"):
        speech.synthesize("hello", target=tmp_path / "out.wav")


def test_silent_output_is_treated_as_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(speech.shutil, "which", lambda _n: "/usr/bin/espeak-ng")
    monkeypatch.setattr(
        speech.subprocess,
        "run",
        lambda command, **_k: subprocess.CompletedProcess(command, 0, "", ""),
    )
    target = tmp_path / "out.wav"
    with pytest.raises(speech.SpeechError, match="no audio"):
        speech.synthesize("hello", target=target)
    assert not target.exists()


# -- integration with the library --------------------------------------


def test_speak_is_refused_when_espeak_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda _n: None)
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
    )
    try:
        with pytest.raises(Exception, match="espeak-ng is not installed"):
            lib.speak("hello")
    finally:
        lib.close()


def test_speak_rejects_empty_text(tmp_path):
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
    )
    try:
        with pytest.raises(Exception, match="nothing to say"):
            lib.speak("   ")
    finally:
        lib.close()


@pytest.mark.skipif(not HAS_ESPEAK, reason="espeak-ng is not installed here")
def test_a_spoken_line_becomes_a_playable_clip(tmp_path):
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
    )
    try:
        job = lib.speak("Question. Are you amazed?", "rocky")
        assert job.kind == "speech"

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and job.status == "processing":
            time.sleep(0.1)

        assert job.status == "ready", job.error
        clips = lib.clips()
        assert len(clips) == 1
        assert clips[0].title == "Question. Are you amazed?"
        assert clips[0].path.suffix == ".wav"
        assert clips[0].duration > 0
    finally:
        lib.close()
