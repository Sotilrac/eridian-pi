"""The trigger state machine.

Lift Rocky and he speaks; keep him lifted and the same clip loops; set him
down and he stops mid-word; lift him again and he says something new.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rockyvox.controller import Controller

CLIPS = [f"/clips/{name}.wav" for name in "abcdef"]
GAP = 0.02


@pytest.fixture
def controller(player, amp):
    ctl = Controller(player=player, amp=amp, clips=CLIPS, repeat_gap_seconds=GAP)
    yield ctl
    ctl.close()


def test_starts_quiet_with_the_magnet_seated(controller, player):
    assert controller.magnet_present is True
    player.expect_silence()


def test_lifting_starts_a_clip(controller, player):
    controller.on_magnet_absent()
    assert str(player.next_start()) in CLIPS
    assert controller.magnet_present is False


def test_staying_lifted_repeats_the_same_clip(controller, player):
    controller.on_magnet_absent()
    first = player.next_start()

    for _ in range(3):
        player.finish()
        assert player.next_start() == first, "a held magnet must loop one clip"


def test_seating_stops_playback_immediately(controller, player):
    controller.on_magnet_absent()
    player.next_start()

    controller.on_magnet_present()

    assert player.stop_calls >= 1
    player.expect_silence()
    assert controller.magnet_present is True


def test_lifting_again_advances_to_a_different_clip(controller, player):
    controller.on_magnet_absent()
    first = player.next_start()

    controller.on_magnet_present()
    controller.on_magnet_absent()
    second = player.next_start()

    assert second != first


def test_seating_during_the_repeat_gap_is_honoured(player, amp):
    # A long gap so the test would catch a controller that slept through it.
    ctl = Controller(player=player, amp=amp, clips=CLIPS, repeat_gap_seconds=1.0)
    try:
        ctl.on_magnet_absent()
        player.next_start()
        player.finish()  # clip ends, the gap begins
        ctl.on_magnet_present()  # put him down mid-gap
        player.expect_silence(seconds=1.4)
    finally:
        ctl.close()


def test_an_empty_library_does_not_spin(player, amp):
    ctl = Controller(player=player, amp=amp, clips=[], repeat_gap_seconds=GAP)
    try:
        ctl.on_magnet_absent()
        player.expect_silence()
        assert player.plays == []
    finally:
        ctl.close()


def test_a_clip_added_later_becomes_playable(player, amp):
    ctl = Controller(player=player, amp=amp, clips=[], repeat_gap_seconds=GAP)
    try:
        ctl.set_clips(["/clips/new.wav"])
        ctl.on_magnet_absent()
        assert player.next_start() == Path("/clips/new.wav")
    finally:
        ctl.close()


def test_a_failing_clip_stops_instead_of_looping(controller, player):
    controller.on_magnet_absent()
    player.next_start()
    # stop() marks the play as interrupted, which is what a failed aplay
    # looks like from the controller's side.
    player.stop()
    player.expect_silence()


def test_play_once_plays_exactly_once(controller, player):
    controller.play_once(Path("/clips/preview.wav"))
    assert player.next_start() == Path("/clips/preview.wav")
    player.finish()
    player.expect_silence()


def test_trigger_once_draws_from_the_bag(controller, player):
    played = controller.trigger_once()
    assert str(played) in CLIPS
    assert player.next_start() == played
    player.finish()
    player.expect_silence()


def test_trigger_once_on_an_empty_library_returns_none(player, amp):
    ctl = Controller(player=player, amp=amp, clips=[], repeat_gap_seconds=GAP)
    try:
        assert ctl.trigger_once() is None
    finally:
        ctl.close()


def test_lifting_preempts_a_preview(controller, player):
    controller.play_once(Path("/clips/preview.wav"))
    player.next_start()

    controller.on_magnet_absent()
    assert str(player.next_start()) in CLIPS


def test_the_amp_is_enabled_only_while_a_clip_runs(controller, player, amp):
    controller.on_magnet_absent()
    player.next_start()
    assert amp.enabled is True

    controller.on_magnet_present()
    player.expect_silence()
    assert amp.enabled is False


def test_sync_magnet_adopts_the_reading_without_playing(controller, player):
    controller.sync_magnet(present=False)

    assert controller.magnet_present is False
    player.expect_silence()  # booting while lifted must not start a clip


def test_a_lift_after_sync_still_triggers(controller, player):
    controller.sync_magnet(present=False)
    player.expect_silence()

    controller.on_magnet_present()
    controller.on_magnet_absent()
    assert str(player.next_start()) in CLIPS


# -- arming ------------------------------------------------------------


def test_a_disarmed_sensor_is_ignored(controller, player):
    controller.set_armed(False)
    controller.on_magnet_absent()
    player.expect_silence()
    # The reading is still reported honestly, it is just not acted on.
    assert controller.magnet_present is False


def test_disarming_mid_clip_goes_quiet_at_once(controller, player):
    controller.on_magnet_absent()
    player.next_start()
    before = player.stop_calls
    controller.set_armed(False)
    assert player.stop_calls > before


def test_rearming_does_not_replay_the_clip_that_was_cut_off(controller, player):
    controller.on_magnet_absent()
    player.next_start()
    controller.set_armed(False)
    controller.set_armed(True)
    # Still lifted, but no fresh edge has happened, so it stays silent.
    player.expect_silence()


def test_a_disarmed_magnet_does_not_cut_off_a_preview(controller, player, tmp_path):
    clip = tmp_path / "preview.wav"
    clip.write_bytes(b"RIFF")
    controller.set_armed(False)
    controller.play_once(clip)
    player.next_start()
    before = player.stop_calls
    controller.on_magnet_present()
    assert player.stop_calls == before


def test_manual_trigger_still_works_when_disarmed(controller, player):
    controller.set_armed(False)
    assert controller.trigger_once() is not None
    player.next_start()


def test_setting_the_same_arm_state_twice_is_a_no_op(controller):
    changes = []
    controller._on_armed_change = changes.append
    assert controller.set_armed(True) is True
    assert changes == []
    controller.set_armed(False)
    assert changes == [False]
