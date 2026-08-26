# Rocky Vox

A talking *Project Hail Mary* figurine. Lift Rocky off his base and he says
something; put him back and he stops mid-word; lift him again and he says
something else.

Inside the shell: a Raspberry Pi Zero W, an I2S DAC, a MAX9744 20W class-D
amplifier, a 4Ω speaker and a hall effect sensor watching a magnet in the
base. New lines are added over the LAN, either by uploading audio or by
typing text for the on-board synthesiser.

```
  Pi ──I2S──▶ PCM5102A ──line──▶ MAX9744 ──▶ 4Ω speaker
  Pi ──I2C──────────────────────▶ MAX9744    (volume only)
  hall sensor ──▶ Pi GPIO17
```

A Zero W has no analog output, so something has to produce a line-level
signal. An I2S DAC is the default; a USB sound card or a PWM pin through an
RC filter both work too, and are one provisioning flag apart. See
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
make provision     # packages, overlays, service; add AUDIO=usb or AUDIO=pwm
make shell         # then: sudo reboot, for the overlays
make deploy        # push code and restart
make open          # the control panel
```

Wire it up first — [docs/HARDWARE.md](docs/HARDWARE.md) has the pinout and
the three things that will otherwise waste an evening. The full procedure is
in [docs/SETUP.md](docs/SETUP.md).

## Control panel

`http://<hostname>.local:8080`, open on the LAN. Live status, a 64-segment
volume bar mirroring the amp's 64 hardware steps, drag-and-drop upload, text
to speech, per-clip audition, and a trigger button for testing without a
magnet.

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
