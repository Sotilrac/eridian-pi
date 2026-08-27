# Setup

Start to finish, from a fresh Raspberry Pi OS install to a talking figurine.

## 1. Prepare the Pi

Raspbian Trixie (Debian 13), headless, on the network, with SSH working and
passwordless sudo. Everything below assumes an SSH alias named `erid`, which
is the `PI` the Makefile defaults to:

```
Host erid
    User rocky
    Hostname erid.local
    IdentityFile ~/.ssh/id_rsa_rocky
```

Point `Hostname` at the mDNS name rather than an address. The Pi's lease
moves, and every `make` target breaks the day it does. `avahi-daemon` runs by
default on Raspberry Pi OS, so `<hostname>.local` resolves without setup.

Use a different alias by passing it through: `make deploy PI=myhost`. If mDNS
is not available on your network, an address works too, at the cost of having
to edit it when the lease changes.

## 2. Wire it up

Follow [HARDWARE.md](HARDWARE.md). Do this before provisioning so the
verification steps have something to talk to. Leave the amp's supply
unplugged until the wiring has been checked twice — a reversed speaker lead
is survivable, a reversed supply is not.

## 3. Provision

```
make provision AUDIO=i2s     # an I2S DAC board, the default
make provision AUDIO=usb     # a USB sound card on the OTG port
make provision AUDIO=pwm     # GPIO18/19 through an RC filter
```

Pick the audio path that matches the parts you have; the comparison table in
[HARDWARE.md](HARDWARE.md) covers the trade-offs. Switching later is the same
command with a different value.

This is idempotent, so it is safe to re-run at any point. It:

1. installs `python3-flask`, `python3-waitress`, `python3-gpiozero`,
   `python3-lgpio`, `python3-smbus2`, `alsa-utils`, `ffmpeg`, `i2c-tools`
   and `espeak-ng` from apt — nothing comes from pip, because armv6 has
   almost no prebuilt wheels and compiling them on a 1GHz single core is a
   long evening
2. rewrites its marked overlay block in `/boot/firmware/config.txt` for the
   chosen backend, and loads `i2c-dev` so `/dev/i2c-1` appears
3. generates `/etc/asound.conf` pointing ALSA at that backend's card
4. creates `/srv/rocky/{clips,default}` and `/etc/rocky/config.toml`
5. transcodes the built-in clip into `/srv/rocky/default`
6. installs and enables `rocky-vox.service`

The overlays only take effect after a restart:

```
make shell
sudo reboot
```

## 4. Verify the hardware

```
make i2c-scan      # expect 0x4b
make aplay-l       # expect the card for your AUDIO= backend
make speaker-test  # pink noise, left then right
```

If any of these fail, the table at the end of [HARDWARE.md](HARDWARE.md)
lists the usual causes.

## 5. Verify the behaviour

```
make status                       # active (running)
make trigger                      # a clip plays with no magnet involved
make volume V=20                  # audibly quieter
make open                         # the control panel
```

Then the real thing, with the magnet:

| Do this | Expect |
|---|---|
| Lift Rocky off the base | a clip starts |
| Keep him lifted | the same clip repeats, one second apart |
| Set him down | silence, immediately, mid-word |
| Lift him again | a *different* clip |
| Repeat until every clip has played | no clip repeats until all have |

## 6. Add clips

Open `http://<hostname>.local:8080` from anything on the LAN. There are two
ways to add a clip, and both land in the same shuffle bag:

- **Upload** — drag audio onto the dropzone. It is transcoded once, on
  ingest, to 44.1kHz/16-bit stereo WAV and loudness-normalised so a quiet
  clip does not vanish next to a loud one. That takes 5–15 seconds on a Zero
  W; the row shows `PROCESSING` until it is done. All the CPU cost is paid
  here so that playback is a bare PCM push and a clip starts the instant the
  magnet leaves.
- **Synthesize** — type a line and pick a voice. Rocky speaks through a
  translator box in the book, so a formant synthesiser is the right
  instrument rather than a compromise. espeak-ng is also one of the few
  engines that runs comfortably on armv6; the neural options ship no
  binaries for this architecture.

The built-in clip is locked: it always sits in the rotation and the API
refuses to delete it.

## 7. Day-to-day

```
make deploy    # push code and restart
make logs      # follow the journal
make restart
make status
make state     # the service's JSON state
```

## Configuration

`/etc/rocky/config.toml` on the Pi; `deploy/config.toml.example` documents
every key. Provisioning never overwrites an existing config, so local edits
survive a re-run. The ones worth knowing:

| Key | Default | What it does |
|---|---|---|
| `sensor_pin` | `17` | BCM pin the hall sensor's output is on |
| `magnet_present_is_low` | `true` | flip if the trigger is inverted |
| `bounce_seconds` | `0.05` | raise if a knock retriggers it |
| `repeat_gap_seconds` | `1.0` | pause between repeats while lifted |
| `mono_output` | `true` | sum L+R into both channels for a single speaker |
| `max_volume` | `45` | ceiling on the amp's 0–63 scale |
| `shutdown_pin` | unset | set to `27` once `SHDN` is wired |

Restart after editing: `make restart`.

## Development

Nothing here needs a Pi. The hardware modules import their libraries lazily
and the suite runs against fakes, with one test driving gpiozero's mock pin
factory to prove the real pin edges map to the right callbacks.

```
make venv    # uv venv + dev dependencies
make test    # pytest
make lint    # ruff
make check   # everything pre-commit runs, over every file
make hooks   # install the git pre-commit hook
```
