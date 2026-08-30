"""Clip ingest, listing and deletion. Exercises ffmpeg for real."""

from __future__ import annotations

import shutil
import subprocess
import time
import wave
from pathlib import Path

import pytest

from rockyvox.library import (
    DEFAULT_CLIP_ID,
    ClipError,
    Library,
    install_default_clip,
    probe_duration,
    slugify,
)

EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac")


@pytest.fixture
def library(tmp_path):
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
        max_clip_seconds=300.0,
    )
    yield lib
    lib.close()


def wait_for(predicate, timeout=60.0, interval=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def ingest(library, tone, name="Rocky Says Hello.mp3"):
    source = library.clips_dir.parent / name
    shutil.copy(tone, source)
    job = library.submit(source, name)
    assert wait_for(lambda: job.status != "processing"), "ingest never finished"
    return job


# -- ingest -----------------------------------------------------------


def test_an_upload_is_transcoded_to_wav(library, tone):
    job = ingest(library, tone)
    assert job.status == "ready", job.error

    clips = library.clips()
    assert len(clips) == 1
    clip = clips[0]
    assert clip.path.suffix == ".wav"
    assert clip.title == "Rocky Says Hello"
    assert clip.locked is False


def test_the_transcode_is_44100_16bit(library, tone):
    # Two channels because the card wants two; both carry the same mono mix,
    # which test_a_stereo_clip_is_summed_so_one_speaker_hears_everything pins.
    ingest(library, tone)
    with wave.open(str(library.clips()[0].path), "rb") as handle:
        assert handle.getframerate() == 44100
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2


def test_the_source_upload_is_cleaned_up(library, tone):
    source = library.clips_dir.parent / "temp.mp3"
    shutil.copy(tone, source)
    job = library.submit(source, "temp.mp3")
    assert wait_for(lambda: job.status != "processing")
    assert not source.exists()


def test_a_rejected_extension_never_reaches_ffmpeg(library, tmp_path):
    source = tmp_path / "malware.exe"
    source.write_bytes(b"MZ")
    with pytest.raises(ClipError, match="unsupported file type"):
        library.submit(source, "malware.exe")
    assert not source.exists()


def test_a_file_with_no_audio_stream_is_rejected(library, tmp_path):
    source = tmp_path / "notaudio.wav"
    source.write_bytes(b"this is not a wav file at all")
    job = library.submit(source, "notaudio.wav")
    assert wait_for(lambda: job.status != "processing")
    assert job.status == "failed"
    assert library.clips() == []


def test_an_over_long_clip_is_rejected(tmp_path, tone):
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
        max_clip_seconds=0.5,  # the tone is one second
    )
    try:
        job = ingest(lib, tone)
        assert job.status == "failed"
        assert "limit is" in job.error
    finally:
        lib.close()


def test_two_uploads_of_the_same_name_do_not_collide(library, tone):
    ingest(library, tone, "same.mp3")
    ingest(library, tone, "same.mp3")
    clips = library.clips()
    assert len(clips) == 2
    assert clips[0].id != clips[1].id


def test_ingest_notifies_the_change_handler(tmp_path, tone):
    seen = []
    lib = Library(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        allowed_extensions=EXTENSIONS,
        on_change=lambda: seen.append(1),
    )
    try:
        ingest(lib, tone)
        assert seen, "the shuffle bag was never told to rebuild"
    finally:
        lib.close()


# -- the built-in clip -------------------------------------------------


def test_the_default_clip_is_listed_first_and_locked(library, tone):
    install_default_clip(tone, library.default_dir)
    ingest(library, tone)

    clips = library.clips()
    assert clips[0].id == DEFAULT_CLIP_ID
    assert clips[0].locked is True
    assert clips[1].locked is False


def test_the_default_clip_cannot_be_deleted(library, tone):
    install_default_clip(tone, library.default_dir)
    with pytest.raises(PermissionError):
        library.delete(DEFAULT_CLIP_ID)
    assert library.default_clip() is not None


def test_install_default_clip_is_idempotent(library, tone):
    first = install_default_clip(tone, library.default_dir)
    stamp = first.stat().st_mtime_ns
    second = install_default_clip(tone, library.default_dir)
    assert second == first
    assert second.stat().st_mtime_ns == stamp


# -- deletion ----------------------------------------------------------


def test_deleting_an_upload_removes_the_wav_and_its_metadata(library, tone):
    ingest(library, tone)
    clip = library.clips()[0]

    library.delete(clip.id)

    assert library.clips() == []
    assert not clip.path.exists()
    assert not (library.clips_dir / f"{clip.id}.json").exists()


def test_deleting_an_unknown_clip_raises(library):
    with pytest.raises(KeyError):
        library.delete("nope")


# -- helpers -----------------------------------------------------------


def test_probe_duration_reads_a_real_file(tone):
    assert probe_duration(tone) == pytest.approx(1.0, abs=0.15)


def test_probe_duration_rejects_junk(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"\x00" * 64)
    with pytest.raises(ClipError):
        probe_duration(junk)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Rocky Says Hello.mp3", "rocky-says-hello"),
        ("  ***  .wav", "clip"),
        ("Ünïcødé Tïtlé.ogg", "n-c-d-t-tl"),
        ("a" * 90 + ".mp3", "a" * 48),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def test_unreadable_metadata_is_skipped_not_fatal(library, tone):
    ingest(library, tone)
    (library.clips_dir / "broken.json").write_text("{ not json")
    assert len(library.clips()) == 1


def test_metadata_pointing_at_a_missing_wav_is_skipped(library, tone):
    ingest(library, tone)
    clip = library.clips()[0]
    Path(clip.path).unlink()
    assert library.clips() == []


# -- one speaker, one channel ------------------------------------------


def stereo_tone(tmp_path: Path, left: int, right: int) -> Path:
    """A clip with a different tone hard-panned to each channel."""
    path = tmp_path / f"panned-{left}-{right}.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={left}:duration=1",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={right}:duration=1",
            "-filter_complex",
            "[0:a][1:a]join=inputs=2:channel_layout=stereo[out]",
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def channels_of(path: Path) -> tuple[bytes, bytes]:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 2
        frames = handle.readframes(handle.getnframes())
    return frames[0::4] + frames[1::4], frames[2::4] + frames[3::4]


def test_a_stereo_clip_is_summed_so_one_speaker_hears_everything(library, tmp_path):
    # Rocky has a single speaker on a single amplifier channel. Without the
    # downmix, everything panned right would never be heard.
    source = stereo_tone(tmp_path, 300, 900)
    job = library.submit(source, "panned.wav")
    assert wait_for(lambda: job.status != "processing")
    assert job.status == "ready", job.error

    left, right = channels_of(library.clips()[0].path)
    assert left == right, "the two channels must carry the same summed mix"
    assert set(left) != {0}, "and it must not be silence"


def test_a_mono_source_survives_the_downmix(library, tone, tmp_path):
    # espeak-ng emits mono, which has no right channel for the pan to sum.
    mono = tmp_path / "mono.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", str(tone), "-ac", "1", str(mono)],
        check=True,
        capture_output=True,
    )
    job = library.submit(mono, "mono.wav")
    assert wait_for(lambda: job.status != "processing")
    assert job.status == "ready", job.error

    left, right = channels_of(library.clips()[0].path)
    assert left == right
    assert set(left) != {0}


def test_changing_the_mix_re_transcodes_the_built_in_clip(library, tone):
    # The source never changes, so an mtime check alone would leave the
    # built-in clip mixed the old way for ever after the filters are edited.
    install_default_clip(tone, library.default_dir)
    first = library.default_clip().path.stat().st_mtime_ns

    # Stand in for an edit to the filter chain.
    (library.default_dir / ".recipe").write_text("some,other,filters")
    install_default_clip(tone, library.default_dir)
    assert library.default_clip().path.stat().st_mtime_ns != first

    stable = library.default_clip().path.stat().st_mtime_ns
    install_default_clip(tone, library.default_dir)
    assert library.default_clip().path.stat().st_mtime_ns == stable


def test_clips_are_written_world_readable(library, tone):
    ingest(library, tone)
    assert library.clips()[0].path.stat().st_mode & 0o777 == 0o644

    install_default_clip(tone, library.default_dir)
    assert library.default_clip().path.stat().st_mode & 0o777 == 0o644
