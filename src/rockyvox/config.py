"""Runtime configuration, loaded from TOML with sane defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/rocky/config.toml")


@dataclass(frozen=True)
class Config:
    # --- storage -------------------------------------------------------
    clips_dir: Path = Path("/srv/rocky/clips")
    default_dir: Path = Path("/srv/rocky/default")
    state_file: Path = Path("/srv/rocky/state.json")

    # --- hall effect sensor --------------------------------------------
    sensor_pin: int = 17
    #: True when the sensor pulls the line LOW with the magnet present
    #: (open-collector halls such as the A3144). Flip to invert the trigger.
    magnet_present_is_low: bool = True
    bounce_seconds: float = 0.05

    # --- playback ------------------------------------------------------
    #: Gap between repeats of the same clip while the magnet stays away.
    repeat_gap_seconds: float = 1.0
    alsa_device: str = "default"
    #: Sum left and right into both channels at ingest. The figurine drives a
    #: single speaker from one amplifier channel, so without this anything
    #: panned right is lost. Set false only if a second speaker is wired.
    mono_output: bool = True

    # --- MAX9744 amplifier ---------------------------------------------
    i2c_bus: int = 1
    amp_address: int = 0x4B
    #: Ceiling for the 0-63 hardware volume. Keeps a 10W speaker alive on
    #: an amp that can deliver 20W.
    max_volume: int = 45
    default_volume: int = 30
    #: Optional GPIO wired to the MAX9744 SHDN pin; mutes the amp when idle
    #: so the class-D output stage does not hiss inside the shell.
    shutdown_pin: int | None = None

    # --- web -----------------------------------------------------------
    # A LAN appliance is meant to be reachable from the LAN.
    host: str = "0.0.0.0"
    port: int = 8080
    max_upload_bytes: int = 32 * 1024 * 1024
    max_clip_seconds: float = 300.0

    #: Extensions accepted by the upload endpoint.
    allowed_extensions: tuple[str, ...] = field(
        default=(".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a", ".aac", ".opus", ".wma")
    )


_PATH_FIELDS = {"clips_dir", "default_dir", "state_file"}


def load_config(path: Path | None = None) -> Config:
    """Read ``path`` if it exists, overlaying it onto the defaults.

    Unknown keys are ignored so a config written for a newer version does not
    stop the service from booting.
    """
    path = path or DEFAULT_CONFIG_PATH
    data: dict = {}
    if path.exists():
        with path.open("rb") as handle:
            data = tomllib.load(handle)

    known = {f.name for f in fields(Config)}
    kwargs = {}
    for key, value in data.items():
        if key not in known:
            continue
        if key in _PATH_FIELDS:
            value = Path(value)
        elif key == "allowed_extensions":
            value = tuple(value)
        elif key == "shutdown_pin" and value in (None, "", -1):
            value = None
        kwargs[key] = value

    return Config(**kwargs)
