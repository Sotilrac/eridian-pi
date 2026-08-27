"""The LAN control panel's HTTP surface."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from rockyvox.config import Config
from rockyvox.controller import Controller
from rockyvox.library import Library, install_default_clip
from rockyvox.web import create_app


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        clips_dir=tmp_path / "clips",
        default_dir=tmp_path / "default",
        state_file=tmp_path / "state.json",
        max_upload_bytes=1024 * 1024,
        allowed_extensions=(".mp3", ".wav"),
    )


@pytest.fixture
def library(config):
    lib = Library(
        clips_dir=config.clips_dir,
        default_dir=config.default_dir,
        allowed_extensions=config.allowed_extensions,
        max_clip_seconds=config.max_clip_seconds,
    )
    yield lib
    lib.close()


@pytest.fixture
def controller(player, amp):
    ctl = Controller(player=player, amp=amp, clips=[], repeat_gap_seconds=0.01)
    yield ctl
    ctl.close()


@pytest.fixture
def client(config, library, controller, amp):
    app = create_app(config=config, library=library, controller=controller, amp=amp)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def seeded(library, controller, tone):
    """A library holding just the locked built-in clip."""
    install_default_clip(tone, library.default_dir)
    controller.set_clips(library.paths())
    return library


def test_the_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"ROCKY" in response.data


def test_state_reports_the_hardware(client, amp):
    body = client.get("/api/state").get_json()
    assert body["magnet_present"] is True
    assert body["playing"] is False
    assert body["volume"] == amp.volume
    assert body["clips"] == []


def test_volume_is_applied_to_the_amp(client, amp):
    body = client.post("/api/volume", json={"value": 41}).get_json()
    assert body["volume"] == 41
    assert amp.volume == 41


def test_volume_is_clamped_to_the_configured_ceiling(client, amp):
    amp.configure_cap(45)
    assert client.post("/api/volume", json={"value": 63}).get_json()["volume"] == 45


@pytest.mark.parametrize("payload", [{}, {"value": "loud"}, {"nope": 1}])
def test_a_malformed_volume_is_rejected(client, payload):
    assert client.post("/api/volume", json=payload).status_code == 400


def test_trigger_plays_a_clip(client, seeded, player):
    response = client.post("/api/trigger")
    assert response.status_code == 200
    assert player.next_start().suffix == ".wav"


def test_trigger_with_an_empty_library_is_a_conflict(client):
    assert client.post("/api/trigger").status_code == 409


def test_preview_plays_the_named_clip(client, seeded, player):
    clip_id = client.get("/api/clips").get_json()["clips"][0]["id"]
    assert client.post(f"/api/clips/{clip_id}/preview").status_code == 200
    assert player.next_start().suffix == ".wav"


def test_preview_of_an_unknown_clip_is_a_404(client):
    assert client.post("/api/clips/ghost/preview").status_code == 404


def test_stop_halts_playback(client, seeded, player):
    client.post("/api/trigger")
    player.next_start()
    assert client.post("/api/stop").status_code == 200
    assert player.stop_calls >= 1


def test_the_builtin_clip_refuses_deletion(client, seeded):
    response = client.delete("/api/clips/default")
    assert response.status_code == 403
    assert "cannot be deleted" in response.get_json()["error"]


def test_deleting_an_unknown_clip_is_a_404(client):
    assert client.delete("/api/clips/ghost").status_code == 404


def test_an_upload_is_accepted_and_transcoded(client, library, tone):
    data = {"file": (io.BytesIO(tone.read_bytes()), "Astrophage.mp3")}
    response = client.post("/api/clips", data=data, content_type="multipart/form-data")
    assert response.status_code == 202

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not library.clips():
        time.sleep(0.1)

    clips = client.get("/api/clips").get_json()["clips"]
    assert [c["title"] for c in clips] == ["Astrophage"]


def test_an_upload_with_no_file_is_rejected(client):
    assert client.post("/api/clips", data={}, content_type="multipart/form-data").status_code == 400


def test_an_upload_of_the_wrong_type_is_rejected(client):
    data = {"file": (io.BytesIO(b"MZ"), "payload.exe")}
    response = client.post("/api/clips", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "unsupported" in response.get_json()["error"]


def test_an_oversized_upload_gets_a_413_with_json(client):
    data = {"file": (io.BytesIO(b"\x00" * (2 * 1024 * 1024)), "huge.mp3")}
    response = client.post("/api/clips", data=data, content_type="multipart/form-data")
    assert response.status_code == 413
    assert "limit" in response.get_json()["error"]


def test_unknown_api_routes_answer_json(client):
    response = client.get("/api/nonsense")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not found"


def test_a_failed_upload_surfaces_as_a_job(client, library, tmp_path):
    data = {"file": (io.BytesIO(b"not audio"), "broken.wav")}
    client.post("/api/clips", data=data, content_type="multipart/form-data")

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        jobs = client.get("/api/state").get_json()["jobs"]
        if jobs and jobs[0]["status"] == "failed":
            return
        time.sleep(0.1)
    raise AssertionError("the rejected upload never surfaced as a failed job")


def test_static_assets_are_self_hosted(client):
    for asset in ("app.css", "app.js", "favicon.svg", "jetbrains-mono.woff2"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200, asset
        response.close()


def test_the_page_references_no_external_hosts():
    root = Path(__file__).resolve().parents[1] / "src" / "rockyvox"
    for path in [
        root / "templates" / "index.html",
        root / "static" / "app.css",
        root / "static" / "app.js",
    ]:
        text = path.read_text()
        assert "//fonts.googleapis" not in text
        assert "https://" not in text.replace("https://scripts.sil.org", ""), path.name


# -- speech ------------------------------------------------------------


def test_voices_are_advertised(client):
    body = client.get("/api/voices").get_json()
    assert {v["id"] for v in body["voices"]} == {"translator"}
    assert isinstance(body["available"], bool)


def test_speak_queues_a_job(client, monkeypatch):
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: "/usr/bin/espeak-ng")
    response = client.post("/api/speak", json={"text": "Amaze."})
    assert response.status_code == 202
    assert response.get_json()["title"] == "Amaze."


def test_speak_with_no_text_is_rejected(client, monkeypatch):
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: "/usr/bin/espeak-ng")
    response = client.post("/api/speak", json={"text": "   "})
    assert response.status_code == 400
    assert "nothing to say" in response.get_json()["error"]


def test_speak_without_espeak_installed_is_rejected(client, monkeypatch):
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: None)
    response = client.post("/api/speak", json={"text": "Amaze."})
    assert response.status_code == 400
    assert "espeak-ng" in response.get_json()["error"]


def test_the_page_offers_the_synthesiser_when_espeak_is_present(
    config, library, controller, amp, monkeypatch
):
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: "/usr/bin/espeak-ng")
    app = create_app(config=config, library=library, controller=controller, amp=amp)
    body = app.test_client().get("/").data
    assert b"Translator input" in body
    assert b"Rocky" in body


def test_the_page_explains_how_to_install_espeak_when_missing(
    config, library, controller, amp, monkeypatch
):
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: None)
    app = create_app(config=config, library=library, controller=controller, amp=amp)
    body = app.test_client().get("/").data
    assert b"apt install espeak-ng" in body


def test_state_resolves_the_playing_file_back_to_a_clip_id(client, seeded, player):
    assert client.get("/api/state").get_json()["current_id"] is None

    client.post("/api/trigger")
    player.next_start()

    body = client.get("/api/state").get_json()
    assert body["current_id"] == "default"
    assert body["playing"] is True


def test_playing_and_current_never_disagree(client, seeded, player):
    """A payload claiming playback must always name the clip."""
    client.post("/api/trigger")
    player.next_start()

    for _ in range(20):
        body = client.get("/api/state").get_json()
        assert body["playing"] == (body["current"] is not None)


# -- the volume ceiling ------------------------------------------------


def test_the_ceiling_holds_until_the_question_is_answered(client, amp):
    amp.configure_cap(45)

    body = client.get("/api/state").get_json()
    assert body["volume_max"] == 45
    assert body["volume_cap"] == 45
    assert body["uncapped"] is False
    assert client.post("/api/volume", json={"value": 63}).get_json()["volume"] == 45


@pytest.mark.parametrize("answer", ["four", "4", " Four. "])
def test_the_right_answer_lifts_the_ceiling(client, amp, answer):
    amp.configure_cap(45)

    response = client.post("/api/uncap", json={"answer": answer})
    assert response.status_code == 200
    assert response.get_json()["volume_max"] == 63

    assert client.post("/api/volume", json={"value": 63}).get_json()["volume"] == 63
    assert client.get("/api/state").get_json()["uncapped"] is True


@pytest.mark.parametrize("answer", ["five", "", "2+2", None])
def test_a_wrong_answer_leaves_the_ceiling_alone(client, amp, answer):
    amp.configure_cap(45)

    response = client.post("/api/uncap", json={"answer": answer})
    assert response.status_code == 403
    assert response.get_json()["error"] == "Incorrect."
    assert response.get_json()["question"] == "What's two plus two?"
    assert amp.max_volume == 45


def test_recap_restores_the_ceiling_and_pulls_the_level_down(client, amp):
    amp.configure_cap(45)

    client.post("/api/uncap", json={"answer": "four"})
    client.post("/api/volume", json={"value": 60})

    body = client.post("/api/recap").get_json()
    assert body["uncapped"] is False
    assert body["volume_max"] == 45
    assert body["volume"] == 45, "a level above the restored cap must come down"


def test_uncapping_an_already_uncapped_amp_needs_no_answer(client, amp):
    amp.configure_cap(63)
    assert client.post("/api/uncap", json={}).status_code == 200


def test_the_page_carries_the_uncap_question(client):
    assert b"two plus two" in client.get("/").data


def test_the_page_carries_rocky_lines_for_the_placeholder(
    config, library, controller, amp, monkeypatch
):
    # The lines only render alongside the synthesiser they seed.
    monkeypatch.setattr("rockyvox.speech.shutil.which", lambda _n: "/usr/bin/espeak-ng")
    app = create_app(config=config, library=library, controller=controller, amp=amp)
    body = app.test_client().get("/").data
    assert b'id="rocky-lines"' in body
    assert b"Fist my bump." in body
