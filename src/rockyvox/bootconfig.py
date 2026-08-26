"""Managing the overlay lines this project owns in ``config.txt``.

Appending is not enough once there is more than one way to get audio out of
the Pi: switching from the I2S DAC to a USB dongle has to *remove* the DAC
overlay, not leave it behind fighting for GPIO18. So the lines live in a
marked block that is rewritten wholesale on every run.

Run as a module to apply it:

    python3 -m rockyvox.bootconfig --backend usb --path /boot/firmware/config.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BEGIN = "# >>> rocky-vox >>>"
END = "# <<< rocky-vox <<<"

#: I2C is needed for the amplifier's volume whichever way the audio travels.
_I2C = "dtparam=i2c_arm=on"

BACKENDS: dict[str, tuple[str, ...]] = {
    # PCM5102A or similar on GPIO18/19/21.
    "i2s": (_I2C, "dtoverlay=hifiberry-dac"),
    # The SoC's PWM channels remapped onto GPIO18/19, into an RC filter.
    "pwm": (_I2C, "dtparam=audio=on", "dtoverlay=audremap,pins_18_19"),
    # A USB sound card needs no overlay at all, just host mode on the port.
    "usb": (_I2C,),
}

#: The ALSA card each backend produces, by name rather than index so it
#: survives the HDMI codec probing in a different order after an update.
#: USB dongles have no predictable name, so that one is detected instead.
CARDS: dict[str, str | None] = {
    "i2s": "sndrpihifiberry",
    "pwm": "Headphones",
    "usb": None,
}

_BLOCK = re.compile(
    rf"\n*{re.escape(BEGIN)}\n.*?{re.escape(END)}\n?",
    re.DOTALL,
)
#: Lines written by the first version of the provisioner, before the block.
_LEGACY = re.compile(r"\n*# added by rocky-vox provision\.sh\n[^\n]*\n?")


def render_block(backend: str) -> str:
    try:
        lines = BACKENDS[backend]
    except KeyError:
        raise ValueError(f"unknown audio backend '{backend}'") from None
    body = "\n".join(lines)
    return f"{BEGIN}\n{body}\n{END}\n"


def apply_block(text: str, backend: str) -> str:
    """Return ``text`` with this project's block replaced by ``backend``'s."""
    stripped = _BLOCK.sub("\n", text)
    stripped = _LEGACY.sub("\n", stripped)
    stripped = stripped.rstrip("\n")
    return f"{stripped}\n\n{render_block(backend)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rockyvox.bootconfig")
    parser.add_argument("--backend", required=True, choices=sorted(BACKENDS))
    parser.add_argument("--path", type=Path, required=True)
    args = parser.parse_args(argv)

    before = args.path.read_text()
    after = apply_block(before, args.backend)
    if before == after:
        print("unchanged")
        return 0

    args.path.write_text(after)
    print("changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
