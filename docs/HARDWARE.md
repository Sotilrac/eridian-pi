# Hardware

Everything inside the Rocky figurine, what it connects to, and the three
things that will waste an evening if you skip them.

## Signal path

The MAX9744's I2C link carries **volume only**. Audio never travels over
I2C: it leaves the Pi as an I2S bitstream, becomes an analog line signal in
the DAC, and only then reaches the amplifier.

```
  Pi ──I2S (GPIO18/19/21)──▶ PCM5102A ──analog line──▶ MAX9744 ──▶ 4Ω speaker
  Pi ──I2C (GPIO2/3)───────────────────────────────────▶ MAX9744   (volume, 0x4B)
  hall sensor ──digital (GPIO17)──▶ Pi
```

A Pi Zero W has no analog output at all. Its only built-in audio device is
the HDMI codec, which is why the DAC is not optional.

## Bill of materials

| Item | Notes |
|---|---|
| Raspberry Pi Zero W | Raspbian Trixie, headless |
| Adafruit MAX9744 20W class-D amp (#1752) | 4.5–14V, I2C volume at `0x4B` |
| An audio path out of the Pi | **pick one of three**, see below |
| Digital hall effect sensor | A3144, US5881 or DRV5032 — see below |
| Neodymium disc magnet | in the base or lid |
| 4Ω 10W speaker | into the amp's terminal block |
| 9V 2A DC supply, 2.1mm barrel | for the amp **only** |
| 3.5mm patch lead | DAC line out → amp input |

## Getting audio out of the Pi

A Pi Zero W has no analog output. Its only built-in audio device is the HDMI
codec, so something has to turn the digital signal into a line-level one
before the amplifier can do anything with it. There are three ways, and the
software supports all of them: pick one and pass it to provisioning.

| | `AUDIO=i2s` | `AUDIO=usb` | `AUDIO=pwm` |
|---|---|---|---|
| What it needs | a PCM5102A-class DAC board | a USB sound card and an OTG adapter | 2 resistors and 4 capacitors |
| Cost | around $7 | often already in a drawer | pennies |
| Quality | clean, full 16-bit | good | audible noise floor |
| Soldering | header pins | none | a little |
| Costs you | GPIO18/19/21 | the USB gadget network | GPIO18/19 |

Whichever you choose, the I2C wiring to the amplifier is identical: it only
ever carries volume.

```
make provision AUDIO=i2s     # the default
make provision AUDIO=usb
make provision AUDIO=pwm
```

Switching later is one command. The overlays live in a marked block in
`config.txt` that is rewritten wholesale, so changing backend removes the
previous one rather than leaving it behind claiming GPIO18.

### `AUDIO=i2s` — an I2S DAC board

The best-sounding option. Any PCM5102A breakout works (GY-PCM5102, HiLetgo,
and similar), as does the Adafruit UDA1334A #3678. Wire it per the pinout
below and feed its line output into the amp's 3.5mm jack.

### `AUDIO=usb` — a USB sound card

The Pi Zero W has exactly one USB data port: the inner micro-USB marked
`USB`. The outer one is `PWR IN` and carries power only. So a dongle needs a
**micro-USB OTG adapter** (micro-B male to USB-A female) to reach it.

Two things to know before committing to this route:

The port is very likely already busy. Raspberry Pi OS images set up for
USB-ethernet gadget mode carry `modules-load=dwc2,g_ether` in
`/boot/firmware/cmdline.txt` and bring up a `usb0` interface, which puts the
controller in *peripheral* mode. A sound card needs *host* mode. Removing
that from `cmdline.txt` and rebooting frees the port and gives up the `usb0`
network in exchange. Check with `ip -brief addr show usb0` before deciding.

Provisioning will not touch `cmdline.txt` on your behalf. If it cannot find
a USB sound card it says so and stops, rather than quietly leaving you with
no audio device.

### `AUDIO=pwm` — GPIO through an RC filter

No extra board: the SoC's PWM channels are remapped onto GPIO18 and GPIO19
and low-pass filtered into something a line input will accept. This is what
the Pi's own analog output does.

Per channel:

```
  GPIO18 ──[ 270R ]──┬──[ 10uF ]──▶ MAX9744 L in
                     │   (+ toward the resistor)
                  [ 33nF ]
                     │
                    GND

  GPIO19 ──[ 270R ]──┬──[ 10uF ]──▶ MAX9744 R in
                     │
                  [ 33nF ]
                     │
                    GND
```

The 270R/33nF pair is the low-pass filter that turns the PWM carrier back
into audio. The 10uF in series blocks the roughly 1.65V DC offset that PWM
output sits at, which the amplifier would otherwise happily amplify into the
speaker.

Expect an audible hiss, especially through a 20W amplifier. It matters less
here than it would for music, because the synthesised voice is band-limited
and gruff to begin with, but it is the compromise option and worth knowing
that going in.

## Pinout

One row per wire, ordered by physical header pin so it can be worked
through top to bottom. A dot means that device takes nothing from this pin.

| Pi pin | BCM | MAX9744 | PCM5102A | Hall sensor | Purpose |
|---|---|---|---|---|---|
| 1 | 3V3 | `Vi2c` | · | · | I2C level reference. **3.3V, never 5V** |
| 2 | 5V | · | `VIN` | · | DAC power |
| 3 | GPIO2 | `SDA` | · | · | volume data |
| 4 | 5V | · | · | `VCC` | sensor power, see the voltage note below |
| 5 | GPIO3 | `SCL` | · | · | volume clock |
| 6 | GND | · | `GND` | · | DAC ground |
| 9 | GND | `GND` | · | · | amp ground, and the ground bond |
| 11 | GPIO17 | · | · | `OUT` | trigger input, internal pull-up |
| 12 | GPIO18 | · | `BCK` | · | I2S bit clock |
| 13 | GPIO27 | `SHDN` *(optional)* | · | · | mutes the amp between clips |
| 25 | GND | · | · | `GND` | sensor ground |
| 35 | GPIO19 | · | `LRCK` / `LCK` | · | I2S word select |
| 40 | GPIO21 | · | `DIN` | · | I2S data |

Not on the header, because it does not touch the Pi:

| From | To | Purpose |
|---|---|---|
| PCM5102A `LOUT` / `ROUT` / `AGND` | MAX9744 input (3.5mm jack or `L` / `R` / `GND`) | the audio itself |
| 9V PSU | MAX9744 barrel jack | amp power, **never the Pi's 5V rail** |
| MAX9744 `L+` / `L-` | 4Ω speaker | either channel carries the full mix, see below |

### Grounds

Every ground above is one net. Pin 9 is the wire that matters: it bonds the
Pi to the amp, and through the amp's barrel jack to the 9V supply. Without
it the amp's input has no reference to the signal arriving from the DAC, and
the result is hum, hiss, or nothing at all.

The audio cable's sleeve is a second path between the DAC and the amp. At
this scale that is harmless, so there is no need to lift it.

### One speaker, both channels

The amp is stereo and the figurine has one speaker, so clips are summed to
mono at ingest and written to both channels. Either amplifier output then
carries the whole mix. Without that, everything panned right in a stereo clip
would be wired to a speaker that does not exist.

Wire a second speaker to `R+` / `R-` and set `mono_output = false` in
`/etc/rocky/config.toml` to get the stereo image back. Re-run `make provision`
afterwards: the built-in clip is re-mixed to match, and anything already
uploaded needs uploading again.

### The optional SHDN wire

Worth adding. Without it the class-D output stage idles at full gain and the
speaker hisses inside the shell between clips; with it the service mutes the
amp whenever nothing is playing. Set `shutdown_pin = 27` in
`/etc/rocky/config.toml` once it is wired.

## Hall sensor voltage

A3144 and US5881 are specified from 4.5V and 3.5V respectively, so they are
out of spec on the Pi's 3.3V rail. Both have **open-collector** outputs,
which gives the correct wiring for free:

- `VCC` → **5V** (pin 4), inside spec
- `OUT` → **GPIO17**, relying on the Pi's *internal 3.3V pull-up*
- `GND` → common ground

The output transistor only ever pulls the line down, so it can never present
more than 3.3V to the GPIO. This is safe.

Two variations:

- A **push-pull** hall (uncommon) drives the line high actively and would put
  5V on the pin. Either run it from 3V3 if its datasheet allows, or use a
  divider (e.g. 10kΩ / 20kΩ).
- A natively low-voltage part such as the **TI DRV5032** (1.65–5.5V) can go
  straight onto 3V3 with nothing else needed. This is the tidiest option if
  you are buying new.

**Polarity.** With a magnet present the output pulls LOW; with the magnet
gone the internal pull-up takes it HIGH. The service reads LOW as "seated"
and HIGH as "lifted".

If Rocky talks while seated and falls silent when lifted, the sensor or the
magnet's pole is the other way round. Do not rewire anything — set
`magnet_present_is_low = false` in `/etc/rocky/config.toml` and restart.

Unipolar halls like the A3144 respond to one magnetic pole only. If nothing
triggers at all, flip the magnet over before suspecting the wiring.

## Amplifier power

**Do not power the MAX9744 from the Pi's 5V rail.** 20W of class-D draws
several amps on peaks and will brown out the Pi mid-clip. Give it its own
barrel-jack supply and tie its ground to the Pi's.

**Use 9V, not 12V.** At 12V into 4Ω the MAX9744 delivers close to 20W, and
the speaker is rated for 10W. At 9V full scale lands near the speaker's
rating instead. Two further guards, both worth keeping:

- `max_volume` in the config caps the digital side (45 of 63 by default)
- run the amp at 9V rather than 12V, as above

**Do not fit the bundled 1kΩ potentiometer.** The board ships in digital
(I2C) mode. Fitting the pot means closing the `Analog`, `AD1` and `AD2`
solder jumpers, which switches the board to analog mode and disables I2C
volume control entirely — the one thing this project relies on for volume.

## The amp is silent until something sets its volume

Worth knowing before you spend an evening on it. In digital mode the
MAX9744 powers up at its **lowest volume setting** and stays there. Adafruit
says so plainly: "When you power up the amplifier and feed in audio you
won't hear anything! This is normal!"

So a correctly wired amp with a good source sounds exactly like a broken
one: the class-D output stage idles and hisses through the speaker, and no
audio passes. Nothing is wrong. Until an I2C master writes a volume byte to
`0x4B`, there is no gain.

This bites hardest on the bench, where the amp is often powered with no Pi
attached. Before suspecting the source, the cable or the speaker:

```sh
make i2c-scan          # 0x4b must appear in the grid
make volume V=40       # write a volume byte
```

If `0x4b` does not appear, no volume byte can ever land, and the amp will
stay silent no matter how good the audio feeding it is.

## PCM5102A jumpers

On the common GY-PCM5102 board:

- tie **`SCK` to GND** so the chip runs from its internal PLL
- leave the `FLT` / `DEMP` / `XSMT` / `FMT` solder jumpers at their defaults
  (`FMT` low selects I2S, `XSMT` pulled high leaves the output unmuted)

A floating `SCK` is the single most common cause of a board that is wired
correctly and still silent.

## Boot configuration

`deploy/provision.sh` owns a marked block in `/boot/firmware/config.txt` and
rewrites it on every run. Changes here need a reboot.

```
# >>> rocky-vox >>>
dtparam=i2c_arm=on        # /dev/i2c-1, for the amp's volume register
dtoverlay=hifiberry-dac   # AUDIO=i2s only
# <<< rocky-vox <<<
```

`AUDIO=pwm` swaps the second line for `dtoverlay=audremap,pins_18_19`;
`AUDIO=usb` needs no overlay at all. Editing anything outside the markers is
safe, and the block never touches the rest of the file.

`dtparam=i2c_arm=on` enables the controller but does not on its own create
`/dev/i2c-1`. The `i2c-dev` module has to be loaded too, and nothing on a
headless image does it, so provisioning writes
`/etc/modules-load.d/rocky-vox.conf`.

`/etc/asound.conf` is generated from `deploy/asound.conf.in` with the card
for the chosen backend filled in, by *name* rather than index, so it survives
the HDMI codec probing in a different order after an update.

The PCM5102A has no hardware mixer, so `amixer` cannot change the level and
`alsamixer` will show nothing. That is expected: volume lives on the
MAX9744, over I2C.

## Checks

```
make i2c-scan      # 0x4b appears in the grid
make aplay-l       # the card for your AUDIO= backend
make speaker-test  # pink noise, left then right
make volume V=20   # audibly quieter
make volume V=45   # audibly louder
```

| Symptom | Likely cause |
|---|---|
| `i2cdetect` finds nothing | `dtparam=i2c_arm=on` missing, `i2c-dev` unloaded, or no reboot yet |
| `i2cdetect: command not found` | it lives in `/usr/sbin`, which SSH does not put on `PATH` |
| `0x4b` missing but the bus scans | amp unpowered, or `Vi2c` not on 3V3 |
| No card in `aplay -l` | wrong `AUDIO=` backend, or no reboot yet |
| No USB card with `AUDIO=usb` | port still in gadget mode, or no OTG adapter |
| Card present, no sound | amp volume never set over I2C (see above); `SCK` floating on the DAC; or `SHDN` held low |
| Amp hisses but passes no audio | classic never-set-volume symptom: `make i2c-scan`, then `make volume V=40` |
| Hiss between clips | wire `SHDN` to GPIO27 and set `shutdown_pin` |
| Distortion at high volume | lower `max_volume`, use 9V not 12V |
| Talks when seated, quiet when lifted | set `magnet_present_is_low = false` |
| Never triggers | flip the magnet over (unipolar sensors need one pole) |
| Retriggers on a knock | raise `bounce_seconds` |
