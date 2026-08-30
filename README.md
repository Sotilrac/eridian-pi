# Rocky Vox

![Rocky](media/amaze.gif)

A talking *Project Hail Mary* figurine. A magnetic block labelled
`Pull me!!! Statement` sits on the base. Pull it off and Rocky says something;
put it back and he stops mid-word; pull it off again and he says something
else.

New speech can be added/removed via HTTP (served page or API), either by
uploading audio files or by using the text-to-speech engine. The shuffle list plays
every clip once before reshuffling and starting over. One default clip cannot be
deleted.

## BOM

* [Raspberry Pi Zero W](https://www.raspberrypi.com/products/raspberry-pi-zero-w/)
* [Adafruit MAX9744](https://www.adafruit.com/product/1752) 20W class-D
amplifier
* USB-C PD adapter
* 4 ohm speaker
* hall effect sensor
* 220 ohm resistor
* 44nF capacitor

## Wiring

Connections by Pi header pin.

```
  Pi GPIO18 (pin 12) --[ 220R ]--+--> MAX9744 L in --> 4 ohm speaker
                                 |
                             [ 44nF ]
                                 |
  Pi GND (pin 6) ----------------+--> MAX9744 GND

  Pi 3V3  (pin 1) ------------------> MAX9744 Vi2c    3.3V, never 5V
  Pi GPIO2 (pin 3) -----------------> MAX9744 SDA     volume only, at 0x4B
  Pi GPIO3 (pin 5) -----------------> MAX9744 SCL
  Pi GND  (pin 9) ------------------> MAX9744 GND     the ground bond

  USB-C PD source, 12V -------------> MAX9744 PWR input terminal

  Pi 3V3   (pin 17) ----------------> hall sensor VCC
  Pi GPIO24 (pin 18) <-------------- hall sensor OUT
  Pi GND   (pin 20) ----------------> hall sensor GND
```

Audio is mono (speaker on the amp's left channel).

### Rudimentary RC filter

The Pi Zero W has no analog output, so GPIO18 is remapped to a PWM channel and
low-pass filtered into something the amp's line input will accept. 220 ohm with
44nF puts the corner at 16.5kHz.

*Possible improvement:* a [PCM5102A I2S DAC](https://www.adafruit.com/product/6251)
on GPIO18/19/21 with `dtoverlay=hifiberry-dac` could replace the filter with a
16-bit line output.

### MAX9744 amp

Leave `Analog`, `AD1` and `AD2` all **open**. That keeps
the chip in digital mode, where volume arrives over I2C, and `AD1`/`AD2` puts it
at address `0x4B`.

The amp gets a USB-C PD source through a fixed-12V trigger board. 30W or more.

At 12V the amp delivers close to its full 20W into 4 ohms and the speaker is
rated for 10W, so `max_volume` is the only thing protecting it.

In digital mode the MAX9744 powers up at its lowest volume setting. The output
stage idles and hisses, and no audio passes. `make i2c-scan` must show `0x4b`,
then `make volume V=40` gives it gain.

`i2cdetect` doesn't work for this chip, which takes a bare volume byte and
supports no reads. Write a byte instead:

```sh
python3 -c "import smbus2; smbus2.SMBus(1).write_byte(0x4b, 20)"
```

### Hall sensor

Magnet present pulls the line LOW, so the service reads LOW as "block on the
base". If that is backwards, set `magnet_present_is_low = false` rather than
rewiring. Unipolar halls respond to one pole only, so if nothing triggers at
all, flip the magnet over.

## Control panel

`http://erid.local:8080`, open on the LAN. Live status, a 64-segment volume
bar mirroring the amp's 64 hardware steps, drag-and-drop upload, text to
speech, per-clip playback, and a trigger button for testing without touching
the block.

Uploads are transcoded once at ingest to 44.1kHz 16-bit and loudness
normalised, which takes ~15s. All the CPU cost is paid upfront so playback is a
bare PCM push and clips start instantly. Synthesis uses espeak-ng.

The toggle beside `Magnet trigger` (or `POST /api/arm`) disables the hall
sensor: it is still read and reported in `/api/state`, but clips are not triggered.

Volume and armed state are both saved a couple of seconds after they change,
so they survive power-cycling.

The `API` panel lists the endpoints the page uses. No auth implemented.

## Setup

The Pi runs Raspbian Trixie, headless, with passwordless sudo. Everything
assumes an SSH alias named `erid`, which is the `PI` the Makefile defaults to:

```
Host erid
    User rocky
    Hostname erid.local
    IdentityFile ~/.ssh/id_rsa_rocky
```

Point `Hostname` at the mDNS name, not an address, or every `make`
target breaks the day the lease moves. Override with `make deploy PI=myhost`.

Wire it up first, and leave the amp's supply unplugged until the wiring has
been checked twice. A reversed speaker lead is survivable; a reversed supply
is not. Then:

```bash
make provision     # packages, overlays, service
make shell         # then: sudo reboot, for the overlays
make deploy        # push code and restart
make open          # the control panel
```

Provisioning installs the apt packages, writes its marked overlay block
in `/boot/firmware/config.txt`, loads `i2c-dev` so `/dev/i2c-1` appears,
generates `/etc/asound.conf`, creates `/srv/rocky` and `/etc/rocky`,
transcodes the built-in clip, and enables `rocky-vox.service`.

Then check the hardware:

```bash
make i2c-scan      # expect 0x4b
make aplay-l       # expect the Headphones card
make speaker-test  # pink noise
make volume V=20   # audibly quieter
make state         # magnet, armed, volume, amp_online
```

The Pi's ALSA mixer sits in front of the amp, so park it at 0dB and store it.
The amp then does all the attenuating:

```bash
ssh erid 'sudo amixer -c Headphones sset PCM -- 0 && sudo alsactl store'
```

The `--` prevents `amixer` from reading a negative value as a flag and failing
silently. `alsactl store` prevents the level from returning to full scale on
reboot.

## Configuration

`/etc/rocky/config.toml` on the Pi; `deploy/config.toml.example` documents
every key. Provisioning never overwrites an existing config, so local edits
survive a re-run.

| Key | Default | What it does |
|---|---|---|
| `sensor_pin` | `24` | BCM pin the hall sensor's output is on |
| `magnet_present_is_low` | `true` | flip if the trigger is inverted |
| `bounce_seconds` | `0.05` | raise if a knock retriggers it |
| `repeat_gap_seconds` | `1.0` | pause between repeats while the block is off |
| `max_volume` | `45` | ceiling on the amp's 0-63 scale |
| `shutdown_pin` | unset | GPIO27, if `SHDN` is wired; mutes the amp when idle |

Restart after editing: `make restart`.

## Development

No Pi required. The hardware modules import their libraries lazily
and the suite runs against fakes, with one test driving gpiozero's mock pin
factory to prove the real pin edges map to the right callbacks.

```
make venv && make check
```

| Path | |
|---|---|
| `src/rockyvox/controller.py` | the trigger state machine |
| `src/rockyvox/library.py` | ingest, transcode, listing, deletion |
| `src/rockyvox/speech.py` | espeak-ng text to speech |
| `src/rockyvox/amp.py` | MAX9744 volume over I2C |
| `src/rockyvox/sensor.py` | hall effect input |
| `src/rockyvox/web.py` | the LAN control panel |
| `deploy/` | systemd unit, ALSA config, provisioning |
| `archive/` | files kept from the earlier setup |

`make help` lists every target.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `i2cdetect` finds nothing | `dtparam=i2c_arm=on` missing, `i2c-dev` unloaded, or no reboot yet |
| `i2cdetect: command not found` | it lives in `/usr/sbin`, which SSH does not put on `PATH` |
| `0x4b` missing but the bus scans | amp unpowered, or `Vi2c` not on 3V3 |
| `amp_online: false` in `/api/state` | amp unpowered, or the I2C wiring is off |
| Amp hisses but passes no audio | volume never set over I2C: `make i2c-scan`, then `make volume V=40` |
| Quiet even at full volume | PD source has no 12V profile and fell back to 5V |
| Amp cuts out on loud passages | PD current contract too small; use a bigger source |
| Volume back at full scale after reboot | `alsactl store` never run |
| Distortion at high volume | lower `max_volume` |
| Talks with the block on, quiet when pulled off | set `magnet_present_is_low = false` |
| Pulling the block off does nothing | the trigger is disarmed; check the toggle or `/api/state` |
| Retriggers on a knock | raise `bounce_seconds` |

## License

MIT, in [LICENSE](LICENSE).

Bundled with it, under other terms:

- `src/rockyvox/static/jetbrains-mono.woff2` is JetBrains Mono, Copyright 2020
  [The JetBrains Mono Project Authors](https://github.com/JetBrains/JetBrainsMono),
  licensed under the [SIL Open Font License 1.1](https://scripts.sil.org/OFL),
  which permits redistribution.
- `media/default/amaze1.mp3` is a short excerpt of Rocky's voice, used here as
  fair use: a few seconds, non-commercial, in a fan project that neither
  substitutes for the original nor competes with it. If you own it and would
  rather it were not here, open an issue and it goes.
- The lines in `src/rockyvox/quotes.py` are quoted from *Project Hail Mary* by
  Andy Weir, as placeholder text for the synthesiser's input box.

*Project Hail Mary* and Rocky belong to Andy Weir. This is a fan project with
no affiliation to, or endorsement from, the author or the film's producers.
