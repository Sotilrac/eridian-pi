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
| PCM5102A I2S DAC breakout | GY-PCM5102 or Adafruit UDA1334A (#3678) |
| Digital hall effect sensor | A3144, US5881 or DRV5032 — see below |
| Neodymium disc magnet | in the base or lid |
| 4Ω 10W speaker | into the amp's terminal block |
| 9V 2A DC supply, 2.1mm barrel | for the amp **only** |
| 3.5mm patch lead | DAC line out → amp input |

## Pinout

BCM numbering; the physical pin is given for the header.

| Pin | BCM | To | Purpose |
|---|---|---|---|
| 1 | 3V3 | MAX9744 `Vi2c` | I2C level reference — **3.3V, never 5V** |
| 3 | GPIO2 | MAX9744 `SDA` | volume data |
| 5 | GPIO3 | MAX9744 `SCL` | volume clock |
| 2 | 5V | PCM5102A `VIN` | DAC power |
| 12 | GPIO18 | PCM5102A `BCK` | I2S bit clock |
| 35 | GPIO19 | PCM5102A `LRCK` / `LCK` | I2S word select |
| 40 | GPIO21 | PCM5102A `DIN` | I2S data |
| 4 | 5V | hall sensor `VCC` | see the voltage note |
| 11 | GPIO17 | hall sensor `OUT` | trigger, internal pull-up |
| 13 | GPIO27 | MAX9744 `SHDN` *(optional)* | mutes the amp between clips |
| 6, 9, 14, 20, 25, 39 | GND | every board and the PSU | **common ground is mandatory** |

The optional `SHDN` wire is worth adding. Without it the class-D output
stage idles at full gain and the speaker hisses inside the shell between
clips; with it the service mutes the amp whenever nothing is playing. Set
`shutdown_pin = 27` in `/etc/rocky/config.toml` once it is wired.

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

- the board's onboard trim pot sets an analog gain ceiling — back it off
  until the loudest clip is as loud as you ever want it
- `max_volume` in the config caps the digital side (45 of 63 by default)

## PCM5102A jumpers

On the common GY-PCM5102 board:

- tie **`SCK` to GND** so the chip runs from its internal PLL
- leave the `FLT` / `DEMP` / `XSMT` / `FMT` solder jumpers at their defaults
  (`FMT` low selects I2S, `XSMT` pulled high leaves the output unmuted)

A floating `SCK` is the single most common cause of a board that is wired
correctly and still silent.

## Boot configuration

Both lines are added by `deploy/provision.sh`, and both need a reboot:

```
dtparam=i2c_arm=on      # /dev/i2c-1, for the amp's volume register
dtoverlay=hifiberry-dac # I2S out on GPIO18/19/21, for the PCM5102A
```

`dtparam=audio=on` can stay; it is harmless on a Zero W, which has no analog
output for it to enable.

`/etc/asound.conf` points the default ALSA device at the DAC by card *name*
rather than index, so it survives the HDMI codec probing in a different order
after an update.

The PCM5102A has no hardware mixer, so `amixer` cannot change the level and
`alsamixer` will show nothing. That is expected: volume lives on the
MAX9744, over I2C.

## Checks

```
make i2c-scan      # 0x4b appears in the grid
make aplay-l       # card 0: sndrpihifiberry
make speaker-test  # pink noise, left then right
make volume V=20   # audibly quieter
make volume V=45   # audibly louder
```

| Symptom | Likely cause |
|---|---|
| `i2cdetect` finds nothing | `dtparam=i2c_arm=on` missing, or no reboot yet |
| `0x4b` missing but the bus scans | amp unpowered, or `Vi2c` not on 3V3 |
| No card in `aplay -l` | `dtoverlay=hifiberry-dac` missing, or no reboot yet |
| Card present, no sound | `SCK` floating on the DAC; or `SHDN` held low |
| Hiss between clips | wire `SHDN` to GPIO27 and set `shutdown_pin` |
| Distortion at high volume | lower `max_volume`, back off the trim pot, use 9V |
| Talks when seated, quiet when lifted | set `magnet_present_is_low = false` |
| Never triggers | flip the magnet over (unipolar sensors need one pole) |
| Retriggers on a knock | raise `bounce_seconds` |
