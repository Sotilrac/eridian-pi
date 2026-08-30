"""The clip library: listing, ingest and deletion.

Uploads are transcoded once, at ingest, to 44.1kHz/16-bit, summed to mono and
loudness-normalised so a quiet clip does not vanish next to a loud one. That
front-loads all the CPU cost, leaving playback as a bare PCM push.

Transcoding a clip takes 5-15 seconds on a Zero W, so ingest runs on a single
background worker and the web UI polls for the result.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import speech

log = logging.getLogger(__name__)

DEFAULT_CLIP_ID = "default"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FFMPEG_TIMEOUT = 600
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
#: Sum both input channels into both outputs. The figurine has one speaker,
#: so anything panned away from it would otherwise be lost. The card wants two
#: channels, so both carry the same mix. aformat comes first because a mono
#: source (espeak-ng output, for one) has no c1 for the pan to reference.
_MONO_SUM = "aformat=channel_layouts=stereo,pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"

#: Downmix before normalising, so loudnorm targets what is actually heard.
_FILTERS = f"{_MONO_SUM},{_LOUDNORM}"


class ClipError(Exception):
    """An upload that cannot be turned into a playable clip."""


@dataclass(frozen=True)
class Clip:
    id: str
    title: str
    path: Path
    duration: float = 0.0
    size: int = 0
    added_at: float = 0.0
    locked: bool = False

    def to_json(self) -> dict:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass
class Job:
    id: str
    title: str
    status: str = "processing"  # processing | ready | failed
    kind: str = "upload"  # upload | speech
    error: str = ""
    created_at: float = 0.0


def slugify(name: str) -> str:
    stem = Path(name).stem.lower()
    slug = _SLUG_RE.sub("-", stem).strip("-")
    return slug[:48] or "clip"


class Library:
    def __init__(
        self,
        clips_dir: Path,
        default_dir: Path,
        allowed_extensions: tuple[str, ...],
        max_clip_seconds: float = 300.0,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.clips_dir = Path(clips_dir)
        self.default_dir = Path(default_dir)
        self.allowed_extensions = tuple(e.lower() for e in allowed_extensions)
        self.max_clip_seconds = max_clip_seconds
        self._on_change = on_change
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queue: list[tuple[str, Callable[[], Path]]] = []
        self._wake = threading.Event()
        self._stopping = threading.Event()

        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.default_dir.mkdir(parents=True, exist_ok=True)

        self._worker = threading.Thread(target=self._run, name="ingest", daemon=True)
        self._worker.start()

    # -- listing ---------------------------------------------------------
    def default_clip(self) -> Clip | None:
        """The shipped clip. Always in rotation, never deletable."""
        candidates = sorted(self.default_dir.glob("*.wav"))
        if not candidates:
            return None
        path = candidates[0]
        stat = path.stat()
        return Clip(
            id=DEFAULT_CLIP_ID,
            title=path.stem,
            path=path,
            duration=_wav_duration(path),
            size=stat.st_size,
            added_at=stat.st_mtime,
            locked=True,
        )

    def clips(self) -> list[Clip]:
        """The default first, then uploads oldest-first."""
        result = []
        default = self.default_clip()
        if default is not None:
            result.append(default)

        uploads = []
        for meta_path in self.clips_dir.glob("*.json"):
            clip = self._read_meta(meta_path)
            if clip is not None:
                uploads.append(clip)
        uploads.sort(key=lambda c: c.added_at)
        result.extend(uploads)
        return result

    def paths(self) -> list[str]:
        return [str(clip.path) for clip in self.clips()]

    def get(self, clip_id: str) -> Clip | None:
        return next((clip for clip in self.clips() if clip.id == clip_id), None)

    def _read_meta(self, meta_path: Path) -> Clip | None:
        try:
            data = json.loads(meta_path.read_text())
            path = Path(data["path"])
            if not path.exists():
                return None
            return Clip(
                id=data["id"],
                title=data["title"],
                path=path,
                duration=float(data.get("duration", 0.0)),
                size=int(data.get("size", path.stat().st_size)),
                added_at=float(data.get("added_at", meta_path.stat().st_mtime)),
                locked=False,
            )
        except (OSError, ValueError, KeyError) as exc:
            log.warning("ignoring unreadable clip metadata %s (%s)", meta_path.name, exc)
            return None

    # -- deletion --------------------------------------------------------
    def delete(self, clip_id: str) -> None:
        clip = self.get(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if clip.locked:
            raise PermissionError("the built-in clip cannot be deleted")
        clip.path.unlink(missing_ok=True)
        (self.clips_dir / f"{clip.id}.json").unlink(missing_ok=True)
        self._notify()

    # -- ingest ----------------------------------------------------------
    def submit(self, source: Path, original_name: str) -> Job:
        """Queue an already-saved upload for transcoding.

        ``source`` is consumed: the worker deletes it when it is done.
        """
        suffix = Path(original_name).suffix.lower()
        if suffix not in self.allowed_extensions:
            source.unlink(missing_ok=True)
            raise ClipError(f"unsupported file type '{suffix or original_name}'")

        title = Path(original_name).stem[:80]
        return self._enqueue(
            slug=slugify(original_name),
            title=title,
            kind="upload",
            producer=lambda: source,
        )

    def speak(self, text: str, voice_id: str | None = None) -> Job:
        """Queue a line of text to be synthesised and added to the bank."""
        try:
            spoken = speech.clean_text(text)
        except speech.SpeechError as exc:
            raise ClipError(str(exc)) from exc
        if not speech.available():
            raise ClipError("espeak-ng is not installed on this device")

        voice = speech.resolve_voice(voice_id)
        return self._enqueue(
            slug=f"say-{slugify(spoken)}",
            title=speech.title_for(spoken),
            kind="speech",
            producer=lambda: speech.synthesize(spoken, voice.id),
        )

    def _enqueue(self, slug: str, title: str, kind: str, producer) -> Job:
        job_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        job = Job(
            id=job_id,
            title=title or job_id,
            kind=kind,
            created_at=time.time(),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._queue.append((job_id, producer))
        self._wake.set()
        return job

    def jobs(self) -> list[Job]:
        """Pending and recently-failed jobs, newest last."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.status != "ready"]
        jobs.sort(key=lambda j: j.created_at)
        return jobs

    def clear_job(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def _run(self) -> None:
        while not self._stopping.is_set():
            with self._lock:
                item = self._queue.pop(0) if self._queue else None
            if item is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue

            job_id, producer = item
            title = self._jobs[job_id].title
            source: Path | None = None
            try:
                source = producer()
                self._transcode(job_id, source, title)
                self._set_job(job_id, "ready")
                self._notify()
            except (ClipError, speech.SpeechError) as exc:
                log.warning("clip '%s' rejected: %s", title, exc)
                self._set_job(job_id, "failed", str(exc))
            except Exception as exc:
                log.exception("clip '%s' failed", title)
                self._set_job(job_id, "failed", str(exc))
            finally:
                if source is not None:
                    source.unlink(missing_ok=True)

    def _set_job(self, job_id: str, status: str, error: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = status
                job.error = error

    def _transcode(self, job_id: str, source: Path, title: str) -> None:
        duration = probe_duration(source)
        if duration > self.max_clip_seconds:
            raise ClipError(f"clip is {duration:.0f}s, limit is {self.max_clip_seconds:.0f}s")

        target = self.clips_dir / f"{job_id}.wav"
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=self.clips_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-af",
                    _FILTERS,
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "wav",
                    str(tmp_path),
                ],
                capture_output=True,
                text=True,
                timeout=_FFMPEG_TIMEOUT,
            )
            if result.returncode != 0:
                raise ClipError(_last_ffmpeg_error(result.stderr))
            tmp_path.replace(target)
            # NamedTemporaryFile creates at 0600; clips are not secrets and
            # this keeps them readable if the service user ever changes.
            target.chmod(0o644)
        except subprocess.TimeoutExpired as exc:
            raise ClipError("transcode timed out") from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        meta = {
            "id": job_id,
            "title": title,
            "path": str(target),
            "duration": _wav_duration(target) or duration,
            "size": target.stat().st_size,
            "added_at": time.time(),
        }
        (self.clips_dir / f"{job_id}.json").write_text(json.dumps(meta, indent=2))

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                log.exception("library change handler failed")

    def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        self._worker.join(timeout=2.0)


def probe_duration(path: Path) -> float:
    """Duration in seconds. Raises ClipError if there is no audio stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise ClipError("ffprobe is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClipError("probe timed out") from exc

    if result.returncode != 0:
        raise ClipError("file is not readable audio")
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise ClipError("file is not readable audio") from exc

    streams = data.get("streams") or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ClipError("file contains no audio stream")
    try:
        return float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _wav_duration(path: Path) -> float:
    """Duration straight from the WAV header, no subprocess needed."""
    import wave

    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / rate if rate else 0.0
    except Exception:  # noqa: BLE001 - a malformed header is not worth a crash
        return 0.0


def _last_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else "transcode failed"


def install_default_clip(source: Path, default_dir: Path) -> Path:
    """Transcode the shipped default clip into ``default_dir``. Idempotent."""
    default_dir.mkdir(parents=True, exist_ok=True)
    target = default_dir / f"{source.stem}.wav"
    # Record the filter chain alongside the result, so a change to it remixes
    # the built-in clip even though the source file has not moved.
    recipe = _FILTERS
    stamp = default_dir / ".recipe"
    if (
        target.exists()
        and target.stat().st_mtime >= source.stat().st_mtime
        and stamp.exists()
        and stamp.read_text() == recipe
    ):
        return target
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=default_dir, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-af",
                _FILTERS,
                "-ar",
                "44100",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT,
        )
        if result.returncode != 0:
            raise ClipError(_last_ffmpeg_error(result.stderr))
        shutil.move(str(tmp_path), target)
        target.chmod(0o644)
        stamp.write_text(recipe)
    finally:
        tmp_path.unlink(missing_ok=True)
    return target
