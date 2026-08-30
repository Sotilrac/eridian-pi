# Rocky Vox

A talking *Project Hail Mary* figurine. Lift Rocky off his base and he says
something; put him back and he stops mid-word; lift him again and he says
something else.

Inside the shell: a Raspberry Pi Zero W, a MAX9744 20W class-D amplifier on a
12V USB-C PD supply, a 4 ohm speaker and a hall effect sensor watching a
magnet in the base. New lines are added over the LAN, either by uploading
audio or by typing text for the on-board synthesiser.

```
  Pi GPIO18 --[ 220R / 44nF ]--> MAX9744 --> 4 ohm speaker
  Pi GPIO2/3 (I2C) ------------> MAX9744     volume only, at 0x4B
  Hall sensor -----------------> Pi GPIO24
```

A Zero W has no analog output, so something has to produce a line-level
signal. This one filters a PWM pin into the amplifier, which costs two
passive components and a little hiss. An I2S DAC board or a USB sound card
are each one provisioning flag away. See
[docs/HARDWARE.md](docs/HARDWARE.md).

## Behaviour

| Event | Response |
|---|---|
| Magnet leaves | draw the next clip from the shuffle bag and play it |
| Magnet still away | when the clip ends, pause a second, replay the same clip |
| Magnet returns | stop immediately, mid-word |
| Magnet leaves again | a *different* clip |

The shuffle bag plays every clip once before any clip plays twice, and never
repeats across a reshuffle. The built-in clip is locked into the rotation and
cannot be deleted.

## Quickstart

```
make provision     # packages, overlays, service; add AUDIO=i2s or AUDIO=usb
make shell         # then: sudo reboot, for the overlays
make deploy        # push code and restart
make open          # the control panel
```

Wire it up first. [docs/HARDWARE.md](docs/HARDWARE.md) has the pinout, the
supply, and the parts that will otherwise waste an evening. The full
procedure is in [docs/SETUP.md](docs/SETUP.md).

## Control panel

`http://<hostname>.local:8080`, open on the LAN. Live status, a 64-segment
volume bar mirroring the amp's 64 hardware steps, drag-and-drop upload, text
to speech, per-clip audition, a trigger button for testing without a magnet,
a toggle that disarms the magnet so the figurine can be handled in silence,
and a collapsed panel documenting the API behind all of it. Volume and armed
state are both persisted, because the figurine gets unplugged rather than
shut down.

## Development

```
make venv && make check
```

The suite runs anywhere: the hardware modules import their libraries lazily
and the tests drive fakes, with one case using gpiozero's mock pin factory to
prove the pin edges map to the right callbacks. No Pi required.

## Layout

| Path | |
|---|---|
| `src/rockyvox/controller.py` | the trigger state machine |
| `src/rockyvox/library.py` | ingest, transcode, listing, deletion |
| `src/rockyvox/speech.py` | espeak-ng text to speech |
| `src/rockyvox/amp.py` | MAX9744 volume over I2C |
| `src/rockyvox/sensor.py` | hall effect input |
| `src/rockyvox/web.py` | the LAN control panel |
| `deploy/` | systemd unit, ALSA config, provisioning |
| `docs/` | hardware and setup |
| `archive/` | files kept from the earlier setup |

`make help` lists every target.

## License

The code is MIT, in [LICENSE](LICENSE). Three things bundled with it are not
mine and keep their own terms:

- `src/rockyvox/static/jetbrains-mono.woff2` is JetBrains Mono under the SIL
  Open Font License 1.1, which permits redistribution. See
  [FONT-LICENSE.txt](src/rockyvox/static/FONT-LICENSE.txt).
- `media/default/amaze1.mp3` is a short excerpt of Rocky's voice, included as
  the built-in clip so a fresh install boots with something to say. It is
  used here as fair use: a few seconds, non-commercial, in a fan project that
  neither substitutes for the original nor competes with it. If you own it
  and would rather it were not here, open an issue and it goes.
- The lines in `src/rockyvox/quotes.py` are quoted from *Project Hail Mary* by
  Andy Weir, as placeholder text for the synthesiser's input box.

*Project Hail Mary* and Rocky belong to Andy Weir. This is a fan project with
no affiliation to, or endorsement from, the author or the film's producers.
