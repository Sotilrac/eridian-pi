"""The LAN control panel.

No authentication by design: this is an appliance on a home network and the
worst an intruder can do is make a figurine talk.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .amp import VOLUME_MAX, Amplifier
from .config import Config
from .controller import Controller
from .library import ClipError, Library
from .speech import VOICES, SpeechError
from .speech import available as speech_available

log = logging.getLogger(__name__)


def create_app(
    config: Config,
    library: Library,
    controller: Controller,
    amp: Amplifier,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_bytes
    app.config["JSON_SORT_KEYS"] = False

    def state_payload() -> dict:
        playing, current = controller.playback_snapshot()
        clips = library.clips()
        # Resolve the playing file back to a clip id here rather than making
        # the browser guess from the filename.
        current_id = next((c.id for c in clips if current and c.path == current), None)
        return {
            "playing": playing,
            "current": current.name if current else None,
            "current_id": current_id,
            "magnet_present": controller.magnet_present,
            "volume": amp.volume,
            "volume_max": amp.max_volume,
            "volume_ceiling": VOLUME_MAX,
            "amp_online": amp.online,
            "clips": [_clip_json(c) for c in clips],
            "jobs": [
                {
                    "id": j.id,
                    "title": j.title,
                    "status": j.status,
                    "kind": j.kind,
                    "error": j.error,
                }
                for j in library.jobs()
            ],
        }

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            max_upload_mb=config.max_upload_bytes // (1024 * 1024),
            max_clip_seconds=int(config.max_clip_seconds),
            accept=",".join(config.allowed_extensions),
            voices=list(VOICES.values()),
            speech_available=speech_available(),
        )

    @app.get("/api/state")
    def api_state():
        return jsonify(state_payload())

    @app.get("/api/clips")
    def api_clips():
        return jsonify({"clips": [_clip_json(c) for c in library.clips()]})

    @app.post("/api/clips")
    def api_upload():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "no file supplied"}), 400

        suffix = Path(upload.filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        upload.save(tmp_path)

        try:
            job = library.submit(tmp_path, upload.filename)
        except ClipError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job": job.id, "title": job.title, "status": job.status}), 202

    @app.delete("/api/clips/<clip_id>")
    def api_delete(clip_id: str):
        try:
            library.delete(clip_id)
        except KeyError:
            return jsonify({"error": "no such clip"}), 404
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        return jsonify({"ok": True})

    @app.post("/api/clips/<clip_id>/preview")
    def api_preview(clip_id: str):
        clip = library.get(clip_id)
        if clip is None:
            return jsonify({"error": "no such clip"}), 404
        controller.play_once(clip.path)
        return jsonify({"ok": True, "playing": clip.title})

    @app.get("/api/voices")
    def api_voices():
        return jsonify(
            {
                "available": speech_available(),
                "voices": [{"id": v.id, "label": v.label} for v in VOICES.values()],
            }
        )

    @app.post("/api/speak")
    def api_speak():
        payload = request.get_json(silent=True) or {}
        try:
            job = library.speak(payload.get("text", ""), payload.get("voice"))
        except (ClipError, SpeechError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"job": job.id, "title": job.title, "status": job.status}), 202

    @app.post("/api/stop")
    def api_stop():
        controller.stop()
        return jsonify({"ok": True})

    @app.post("/api/trigger")
    def api_trigger():
        played = controller.trigger_once()
        if played is None:
            return jsonify({"error": "the clip library is empty"}), 409
        return jsonify({"ok": True, "playing": played.stem})

    @app.post("/api/volume")
    def api_volume():
        payload = request.get_json(silent=True) or {}
        try:
            requested = int(payload["value"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "expected {'value': 0-63}"}), 400
        applied = amp.set_volume(requested)
        return jsonify({"volume": applied, "amp_online": amp.online})

    @app.errorhandler(413)
    def api_too_large(_exc):
        limit = config.max_upload_bytes // (1024 * 1024)
        return jsonify({"error": f"file exceeds the {limit}MB limit"}), 413

    @app.errorhandler(404)
    def api_not_found(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return exc

    return app


def _clip_json(clip) -> dict:
    return {
        "id": clip.id,
        "title": clip.title,
        "duration": round(clip.duration, 1),
        "size": clip.size,
        "locked": clip.locked,
    }
