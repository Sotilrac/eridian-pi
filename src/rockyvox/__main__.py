"""Service entry point: wires the hardware to the state machine and the web UI."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from pathlib import Path

from .amp import Max9744
from .config import Config, load_config
from .controller import Controller
from .library import Library
from .player import AplayPlayer
from .sensor import create_sensor
from .web import create_app

log = logging.getLogger("rockyvox")


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
    except OSError as exc:
        log.warning("cannot persist state to %s (%s)", path, exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rockyvox", description="Talking Rocky figurine")
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config: Config = load_config(args.config)
    saved = _read_state(config.state_file)

    amp = Max9744(
        bus=config.i2c_bus,
        address=config.amp_address,
        max_volume=config.max_volume,
        initial_volume=int(saved.get("volume", config.default_volume)),
        shutdown_pin=config.shutdown_pin,
    )
    player = AplayPlayer(device=config.alsa_device)

    controller: Controller | None = None

    def on_library_change() -> None:
        if controller is not None:
            controller.set_clips(library.paths())

    library = Library(
        clips_dir=config.clips_dir,
        default_dir=config.default_dir,
        allowed_extensions=config.allowed_extensions,
        max_clip_seconds=config.max_clip_seconds,
        on_change=on_library_change,
    )

    controller = Controller(
        player=player,
        amp=amp,
        clips=library.paths(),
        repeat_gap_seconds=config.repeat_gap_seconds,
        magnet_present=True,
    )

    sensor = create_sensor(
        pin=config.sensor_pin,
        on_present=controller.on_magnet_present,
        on_absent=controller.on_magnet_absent,
        magnet_present_is_low=config.magnet_present_is_low,
        bounce_seconds=config.bounce_seconds,
    )

    # Report the real position without treating power-on as a lift.
    controller.sync_magnet(sensor.magnet_present)

    clip_count = len(library.clips())
    log.info(
        "%d clip%s loaded; magnet %s; serving on http://%s:%d",
        clip_count,
        "" if clip_count == 1 else "s",
        "present" if sensor.magnet_present else "absent",
        config.host,
        config.port,
    )
    if clip_count == 0:
        log.warning("no clips found; run 'make provision' to install the default clip")

    def shutdown(signum, _frame):
        log.info("signal %d received, shutting down", signum)
        _write_state(config.state_file, {"volume": amp.volume})
        controller.close()
        sensor.close()
        library.close()
        amp.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    app = create_app(config=config, library=library, controller=controller, amp=amp)

    from waitress import serve

    serve(app, host=config.host, port=config.port, threads=4, _quiet=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
