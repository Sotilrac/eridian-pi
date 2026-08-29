"""Config loading: defaults, overrides, and tolerance of junk."""

from __future__ import annotations

from pathlib import Path

from rockyvox.config import Config, load_config


def test_a_missing_file_yields_the_defaults(tmp_path):
    config = load_config(tmp_path / "absent.toml")
    assert config == Config()
    assert config.sensor_pin == 24
    assert config.amp_address == 0x4B
    assert config.repeat_gap_seconds == 1.0


def test_values_are_overridden(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "sensor_pin = 22",
                "max_volume = 40",
                "repeat_gap_seconds = 2.5",
                "magnet_present_is_low = false",
                'clips_dir = "/tmp/clips"',
            ]
        )
    )
    config = load_config(path)

    assert config.sensor_pin == 22
    assert config.max_volume == 40
    assert config.repeat_gap_seconds == 2.5
    assert config.magnet_present_is_low is False
    assert config.clips_dir == Path("/tmp/clips")
    assert config.port == Config().port  # untouched keys keep their default


def test_unknown_keys_do_not_stop_the_service_booting(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('sensor_pin = 5\nwarp_factor = "nine"\n')
    assert load_config(path).sensor_pin == 5


def test_the_shutdown_pin_is_optional(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("shutdown_pin = 27\n")
    assert load_config(path).shutdown_pin == 27

    path.write_text("shutdown_pin = -1\n")
    assert load_config(path).shutdown_pin is None

    assert Config().shutdown_pin is None


def test_allowed_extensions_become_a_tuple(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('allowed_extensions = [".mp3", ".wav"]\n')
    assert load_config(path).allowed_extensions == (".mp3", ".wav")


def test_the_shipped_example_config_parses():
    example = Path(__file__).resolve().parents[1] / "deploy" / "config.toml.example"
    config = load_config(example)
    assert config.sensor_pin == 24
    assert config.amp_address == 0x4B
    assert config.max_volume == 45
    assert config.clips_dir == Path("/srv/rocky/clips")
