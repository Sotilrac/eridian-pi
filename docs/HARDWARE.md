# Hardware

Everything inside the Rocky figurine, what it connects to, and the parts
that will otherwise waste an evening.

## As built

Describes the figurine that exists rather than the reference design. Where
the two differ, this section wins and the alternatives are further down.

```
  Pi GPIO18 --[ 220R ]--+--> MAX9744 L in --> 4 ohm speaker
                        |
                    [ 44nF ]
                        |
  Pi GND ---------------+--> MAX9744 GND

  Pi GPIO2/3 (I2C) ------> MAX9744 at 0x4B      volume only, never audio
  Hall sensor GPIO24 ----> Pi                   the pull block's magnet
  USB-C PD source -------> MAX9744 barrel jack  12V, amp only
```

| | |
|---|---|
| Audio backend | `AUDIO=pwm`, one channel, GPIO18 through an RC filter |
| Amp volume | I2C, digital mode, address `0x4B` |
| Amp supply | USB-C PD trigger at 12V into the barrel jack |
| Hall sensor | A3144-class, `VCC` on 3V3, `OUT` on GPIO24 |
| Trigger | magnet in the block Rocky holds, sensor in the body behind it |
| Speaker | one 4 ohm 10W, on the amp's left channel |
| `SHDN` | not wired; the output stage hisses between clips |

The MAX9744's I2C link carries volume only. Audio never travels over I2C: it
leaves the Pi as a filtered PWM signal and arrives at the amplifier as an
analog line-level one.

A Pi Zero W has no analog output at all. Its only built-in audio device is
the HDMI codec, which is why the signal has to be manufactured somehow.

## Bill of materials

| Item | Notes |
|---|---|
| Raspberry Pi Zero W | Raspbian Trixie, headless |
| Adafruit MAX9744 20W class-D amp (#1752) | 4.5-14V, I2C volume at `0x4B` |
| An audio path out of the Pi | pick one of three, see below |
| Digital hall effect sensor | A3144, US5881 or DRV5032, see below |
| Neodymium disc magnet | in the `Pull me!!! Statement` block |
| 4 ohm 10W speaker | into the amp's terminal block |
| 220 ohm resistor, 44nF ceramic | the PWM filter, one channel |
| USB-C PD trigger board, fixed 12V | amp supply, see the power section |
| 2.1mm centre-positive barrel lead | trigger board to the amp |

## Getting audio out of the Pi

Something has to turn the Pi's digital signal into a line-level one before
the amplifier can do anything with it. There are three ways, and the software
supports all of them: pick one and pass it to provisioning.

| | `AUDIO=pwm` (built) | `AUDIO=i2s` | `AUDIO=usb` |
|---|---|---|---|
| What it needs | a resistor and a capacitor | a PCM5102A-class DAC board | a USB sound card and an OTG adapter |
| Cost | pennies | around $7 | often already in a drawer |
| Quality | audible noise floor | clean, full 16-bit | good |
| Soldering | a little | header pins | none |
| Costs you | GPIO18/19 | GPIO18/19/21 | the USB gadget network |

Whichever you choose, the I2C wiring to the amplifier is identical: it only
ever carries volume.

```
make provision AUDIO=pwm     # the default, and what is fitted
make provision AUDIO=i2s
make provision AUDIO=usb
```

Switching later is one command. The overlays live in a marked block in
`config.txt` that is rewritten wholesale, so changing backend removes the
previous one rather than leaving it behind claiming GPIO18.

### `AUDIO=pwm` - GPIO through an RC filter

The SoC's PWM channels are remapped onto GPIO18 and GPIO19 and low-pass
filtered into something a line input will accept. This is what the Pi's own
analog output does on the models that have one.

Built and verified on 2026-08-27, driving a 4 ohm speaker from one channel.

**One channel is enough.** The figurine has a single speaker and ingest
already downmixes to mono, so only GPIO18 is wired. GPIO19 is left alone.

**No DC blocking capacitor is needed.** The Adafruit board has input coupling
caps of its own; their guide says so directly: "The inputs do have blocking
capacitors ... it's OK to connect them up directly without extra audio
blocking caps." That reduces the filter to two components.

```
  Pi pin 12 (GPIO18) --[ 220R ]--+--> MAX9744 L in
                                 |
                             [ 44nF ]
                                 |
  Pi pin 6  (GND) ---------------+--> MAX9744 GND
```

| Part | Value | Notes |
|---|---|---|
| R | 220 ohm | anything 180 to 470 ohm works |
| C | 44nF | two 22nF ceramics in parallel, both marked `223` |

A ceramic marked `223` is 22nF: two significant digits, then the number of
zeros, in picofarads. Two in parallel add to 44nF.

Pick R and C so that `R x C` lands near 9us. Anything from 5us to 20us sounds
fine for speech. 220 ohm with 44nF puts the corner at 16.5kHz, close to the
filter on the Pi's own analog output. Below about 5kHz the result goes
muffled; above about 30kHz too much of the PWM carrier reaches the amplifier.

If only one 22nF is to hand, pair it with 390 or 470 ohm instead.

Expect an audible hiss, especially through a 20W amplifier. It matters less
here than it would for music, because the synthesised voice is band-limited
and gruff to begin with, but it is the compromise option and worth knowing
that going in. Wiring `SHDN` removes the hiss between clips, though not
during them.

### `AUDIO=i2s` - an I2S DAC board

The best-sounding option. Any PCM5102A breakout works (GY-PCM5102, HiLetgo,
and similar), as does the Adafruit UDA1334A #3678. Wire it per the pinout
below and feed its line output into the amp's 3.5mm jack.

On the common GY-PCM5102 board, tie `SCK` to GND so the chip runs from its
internal PLL, and leave the `FLT` / `DEMP` / `XSMT` / `FMT` solder jumpers at
their defaults (`FMT` low selects I2S, `XSMT` pulled high leaves the output
unmuted). A floating `SCK` is the most common cause of a board that is wired
correctly and still silent.

The PCM5102A has no hardware mixer, so `amixer` cannot change the level and
`alsamixer` shows nothing. That is expected: with an I2S DAC, volume lives
entirely on the MAX9744.

### `AUDIO=usb` - a USB sound card

The Pi Zero W has exactly one USB data port: the inner micro-USB marked
`USB`. The outer one is `PWR IN` and carries power only. So a dongle needs a
**micro-USB OTG adapter** (micro-B male to USB-A female) to reach it.

Before committing to this route:

The port is very likely already busy. Raspberry Pi OS images set up for
USB-ethernet gadget mode carry `modules-load=dwc2,g_ether` in
`/boot/firmware/cmdline.txt` and bring up a `usb0` interface, which puts the
controller in *peripheral* mode. A sound card needs *host* mode. Removing
that from `cmdline.txt` and rebooting frees the port and gives up the `usb0`
network in exchange. Check with `ip -brief addr show usb0` before deciding.

Provisioning will not touch `cmdline.txt` on your behalf. If it cannot find a
USB sound card it says so and stops, rather than leaving you with no audio
device.

Ingest still writes 44.1kHz stereo WAV, and many cheap dongles are 48kHz mono
only, so this backend needs the sample rate in `library.py` changed to match
the device before it will play anything.

## Pinout

One row per wire, ordered by physical header pin so it can be worked through
top to bottom. A dot means that device takes nothing from this pin.

The `PWM` column is the build that is in the figurine. The `I2S` column is
the alternative if a PCM5102A is ever fitted. Wire one or the other, never
both, since they share GPIO18.

| Pi pin | BCM | MAX9744 | PWM (built) | I2S (alt) | Hall sensor | Purpose |
|---|---|---|---|---|---|---|
| 1 | 3V3 | `Vi2c` | · | · | · | I2C level reference. 3.3V, never 5V |
| 2 | 5V | · | · | `VIN` | · | DAC power |
| 3 | GPIO2 | `SDA` | · | · | · | volume data |
| 4 | 5V | · | · | · | *(alt `VCC`)* | 5V option for the sensor, see the voltage note |
| 5 | GPIO3 | `SCL` | · | · | · | volume clock |
| 6 | GND | · | filter ground | `GND` | · | return for the RC filter |
| 9 | GND | `GND` | · | · | · | amp ground, and the ground bond |
| 12 | GPIO18 | `L` in | **220R + 44nF** | `BCK` | · | the audio itself |
| 13 | GPIO27 | `SHDN` *(optional)* | · | · | · | mutes the amp between clips |
| 17 | 3V3 | · | · | · | `VCC` | sensor power as built |
| 18 | GPIO24 | · | · | · | `OUT` | trigger input, internal pull-up |
| 20 | GND | · | · | · | `GND` | sensor ground |
| 35 | GPIO19 | · | unused | `LRCK` / `LCK` | · | second PWM channel, not wired |
| 40 | GPIO21 | · | · | `DIN` | · | I2S data |

The sensor sits on pins 17, 18 and 20 so its three wires leave the header as
one bundle from a single corner, which is easier to dress inside the shell
than three wires from opposite ends. Any spare GPIO works; set `sensor_pin`
to match. Pin 1 is taken by the amp's `Vi2c`, which is why 3V3 comes from
pin 17 rather than pin 1.

Not on the header, because it does not touch the Pi:

| From | To | Purpose |
|---|---|---|
| USB-C PD trigger, 12V | MAX9744 barrel jack | amp power, never the Pi's 5V rail |
| MAX9744 `L+` / `L-` | 4 ohm speaker | either channel carries the full mix, see below |
| PCM5102A `LOUT` / `ROUT` / `AGND` | MAX9744 input (3.5mm jack or `L` / `R` / `GND`) | only with `AUDIO=i2s` |

### Grounds

Every ground above is one net. Pin 9 is the wire that matters: it bonds the
Pi to the amp, and through the amp's barrel jack to the 12V supply. Without
it the amp's input has no reference to the signal arriving from the filter,
and the result is hum, hiss, or nothing at all.

### One speaker, both channels

The amp is stereo and the figurine has one speaker, so clips are summed to
mono at ingest and written to both channels. Either amplifier output then
carries the whole mix. Without that, everything panned right in a stereo clip
would be wired to a speaker that does not exist.

Wire a second speaker to `R+` / `R-` and set `mono_output = false` in
`/etc/rocky/config.toml` to get the stereo image back. With `AUDIO=pwm` that
also means filtering GPIO19 with a second 220R/44nF pair into the amp's right
input. Re-run `make provision` afterwards: the built-in clip is re-mixed to
match, and anything already uploaded needs uploading again.

### The optional SHDN wire

Worth adding. Without it the class-D output stage idles at full gain and the
speaker hisses inside the shell between clips; with it the service mutes the
amp whenever nothing is playing. Wire GPIO27 (pin 13) to `SHDN` and set
`shutdown_pin = 27` in `/etc/rocky/config.toml`.

## Amplifier power

**Never power the MAX9744 from the Pi's 5V rail.** 20W of class-D draws
several amps on peaks and will brown out the Pi mid-clip. Give it its own
supply and tie its ground to the Pi's.

### The USB-C PD adapter

The amp is powered from a USB-C PD source through a fixed-12V trigger board
into its barrel jack. The Pi keeps its own micro-USB supply, so this replaces
the 9V wall wart rather than feeding both. A PD source is not a dumb 12V
brick, though, and several things have to line up:

The source has to actually offer 12V. A 12V fixed PDO is optional in the USB
PD spec, and plenty of chargers advertise 5V, 9V, 15V and 20V while skipping
12V entirely; phone-oriented chargers are the usual offenders, laptop bricks
usually have it. A trigger board asking for a profile the source does not
advertise falls back to 5V, which the MAX9744 will run on (its minimum is
4.5V) at roughly a sixth of the power. The symptom is an amp that works but
is far too quiet at any volume setting.

The cable has to be a real USB-C to USB-C data cable. A C-to-A cable or a
charge-only lead gives the trigger board nothing to negotiate over, and the
result is the same silent fallback to 5V.

The current contract has to cover the peaks. At 12V into 4 ohms the amp can
pull several amps on transients, well past what the 12V profile on a small
charger allows. Exceeding the contract makes the source cut out and
renegotiate, which sounds like the amp resetting on bass hits. A 30W or
larger source with a 12V profile has enough headroom for one channel at the
volume cap.

Barrel polarity is centre-positive, and the MAX9744 has no reverse
protection.

### 12V versus 9V

Power into a fixed load goes with the square of the supply voltage, so 12V
delivers roughly 1.8 times what 9V does: near the amp's full 20W into 4 ohms,
against a speaker rated for 10W. Running at 12V therefore puts the whole
burden of not destroying the speaker on the volume setting.

`max_volume` in `/etc/rocky/config.toml` is that guard, capping the amp's
0-63 hardware volume at 45 by default. Set it by ear against the loudest clip
in the bank rather than by arithmetic, and back it off if anything distorts.
The web UI's ceiling can be lifted at runtime, but it asks a question first
and restores itself on restart.

At 9V the speaker's rating and the amp's full output land close enough
together that the cap matters much less. If a 9V supply is available and the
extra volume is not needed, it is the safer choice.

### Do not fit the bundled potentiometer

The board ships in digital (I2C) mode. Analog mode means closing the
`Analog`, `AD1` and `AD2` solder jumpers, which disables I2C volume control
entirely, the one thing this project relies on for volume. In analog mode
`amp.py`, the web volume slider, the `max_volume` cap and the uncapping gate
all become no-ops.

`AD1` and `AD2` double as the **I2C address select pins**. Leaving them open
is what puts the amp at `0x4B`, which is the address `config.toml` and `make
i2c-scan` expect.

**Fitting the pot alone does nothing.** With the pot in place but the three
jumpers open, the chip stays in digital mode, the pot is not connected to
anything that sets gain, and the volume stays at minimum. Turning the knob
has no effect. A board in this half-converted state looks and behaves exactly
like a dead amp.

## The amp is silent until something sets its volume

Worth knowing before you spend an evening on it. In digital mode the MAX9744
powers up at its lowest volume setting and stays there. Adafruit says so
plainly: "When you power up the amplifier and feed in audio you won't hear
anything! This is normal!"

So a correctly wired amp with a good source sounds exactly like a broken one:
the class-D output stage idles and hisses through the speaker, and no audio
passes. Nothing is wrong. Until an I2C master writes a volume byte to `0x4B`,
there is no gain.

This bites hardest on the bench, where the amp is often powered with no Pi
attached. Before suspecting the source, the cable or the speaker:

```sh
make i2c-scan          # 0x4b must appear in the grid
make volume V=40       # write a volume byte
```

If `0x4b` does not appear, no volume byte can ever land, and the amp stays
silent no matter how good the audio feeding it is.

`i2cdetect` is also the wrong tool for this chip. The MAX9744 takes a bare
volume byte and supports no reads at all, so the default probe can hang on it
even when the bus is fine. Write a byte instead:

```sh
python3 -c "import smbus2; smbus2.SMBus(1).write_byte(0x4b, 20)"
```

## Converting the amp between analog and digital mode

This amp was converted to analog mode, run that way for an evening, and
converted back. The round trip cost more time than everything else in the
build, so the procedure and the failure modes are written down here.

To get I2C volume back from an analog-mode board:

1. Wick open all three solder jumpers: `Analog`, `AD1`, `AD2`. All three, not
   just the first. Any one left closed keeps the chip in analog mode. Clear
   them **completely** and check continuity with a meter: a pad that looks
   clean can still hold a hair-thin bridge, and a partial bridge is worse
   than no attempt because it fails intermittently.
2. Remove the potentiometer from the `Pot Vol` pads. With `Analog` open it is
   inert anyway.
3. Wire four pins: Pi 1 to `Vi2c`, Pi 3 to `SDA`, Pi 5 to `SCL`, Pi 9 to
   `GND`. `Vi2c` takes 3.3V, never 5V.
4. `make i2c-scan`. `0x4b` has to appear before anything else will work.
5. `make volume V=40`.

The amp comes up at minimum volume in digital mode and stays there until a
volume byte arrives, so silence between step 3 and step 5 is expected. The
service writes `default_volume` at startup once the amp answers.

### Reading a half-cleared jumper

A partly-wicked `Analog` pad produces different faults depending on how much
solder is left. Read the I2C lines at idle before suspecting anything else:

```sh
python3 -c "
import lgpio
h=lgpio.gpiochip_open(0)
for pin,name in ((2,'SDA'),(3,'SCL')):
    lgpio.gpio_claim_input(h,pin); print(name, lgpio.gpio_read(h,pin)); lgpio.gpio_free(h,pin)"
```

| SDA | SCL | Meaning |
|---|---|---|
| 1 | 1 | bus is idle and healthy; a failure here is elsewhere |
| 1 | 0 | jumper still fully bridged. `i2cdetect` hangs rather than returning |
| 1 | 1, but every write is `ETIMEDOUT` | jumper partly bridged, or an intermittent contact |

`ETIMEDOUT` (errno 110) is not the same as no device. A missing chip gives
`ENXIO` or `EREMOTEIO` quickly. A timeout means the transfer never completed,
which points at the bus rather than the address.

Dropping the bus to 10kHz with `dtparam=i2c_arm_baudrate=10000` in
`config.txt` makes a marginal bus limp along and is a useful way to confirm
the diagnosis. It is a workaround, not a fix. Once the jumpers are properly
cleared, take it back out: provisioning does not write that line, so it
survives only until the next hand edit.

### An amp in analog mode still runs

With the jumpers closed the volume comes from the pot, `/api/state` reports
`amp_online: false`, and the web UI's volume slider does nothing. The service
itself runs normally: every I2C call fails soft by design, so the sensor,
playback and the whole control panel keep working on a bench with no amp
attached at all.

## Two volume controls in series

With `AUDIO=pwm` the Pi's `Headphones` card has a real ALSA mixer, unlike the
PCM5102A, so there are two attenuators in the chain. Putting them in the
wrong order costs level and adds hiss:

- ALSA `PCM` on the Pi: leave at 0dB and store it. PWM has a fixed noise
  floor, so attenuating here throws away signal and keeps the hiss.
- MAX9744 over I2C, 0-63: this is the volume control. The web slider, `make
  volume`, and the uncapping gate all drive it.

```sh
sudo amixer -c Headphones sset PCM -- 0
sudo alsactl store
```

The `--` matters. Without it `amixer` parses a leading-dash value such as
`-2500` as a command-line flag and silently does nothing.

`alsactl store` matters too. `alsa-restore` reapplies a saved level at boot
and the stock default is 0dB, so an unstored setting comes back at full scale
on the next reboot.

## Hall sensor

### Voltage

A3144 and US5881 are specified from 4.5V and 3.5V respectively, so they are
out of spec on the Pi's 3.3V rail. Both have **open-collector** outputs,
which gives the correct wiring for free:

- `VCC` to 3V3 (pin 17) as built, or 5V (pin 4) to stay inside spec
- `OUT` to GPIO24 (pin 18), relying on the Pi's internal 3.3V pull-up
- `GND` to common ground (pin 20)

The output transistor only ever pulls the line down, so whichever rail powers
the sensor, the GPIO never sees more than 3.3V. This is safe either way.

This figurine runs its sensor from 3V3 and it triggers reliably at the
distance the magnet sits at when the block is pushed in. Under-spec hall
parts lose sensitivity before they stop working outright, so if triggering
ever gets unreliable, particularly with a weak magnet or a wider gap, moving
`VCC` to pin 2 or 4 is the first thing to try and needs no change in
software.

Variations:

- A push-pull hall (uncommon) drives the line high actively and would put 5V
  on the pin. Either run it from 3V3 if its datasheet allows, or use a
  divider (e.g. 10k / 20k).
- A natively low-voltage part such as the TI DRV5032 (1.65-5.5V) can go
  straight onto 3V3 with nothing else needed. This is the tidiest option if
  you are buying new.

### Polarity

With a magnet present the output pulls LOW; with the magnet gone the internal
pull-up takes it HIGH. The service reads LOW as "block seated" and HIGH as
"block pulled".

If Rocky talks with the block pushed in and falls silent when it is pulled,
the sensor or the magnet's pole is the other way round. Do not rewire
anything, set `magnet_present_is_low = false` in `/etc/rocky/config.toml`
and restart.

Unipolar halls like the A3144 respond to one magnetic pole only. If nothing
triggers at all, flip the magnet over before suspecting the wiring.

### Disarming

The magnet trigger can be switched off without unplugging anything, from the
toggle beside "Magnet trigger" in the control panel or over the API:

```sh
curl -sX POST http://<host>:8080/api/arm -H 'content-type: application/json' \
     -d '{"armed": false}'
```

While disarmed the sensor is still read and still reported in `/api/state`,
but pulling the block does nothing. Manual triggers and per-clip previews
keep working, which makes this the setting to use while handling the figurine
or working on the shell. The state survives a restart.

## Boot configuration

`deploy/provision.sh` owns a marked block in `/boot/firmware/config.txt` and
rewrites it on every run. Changes here need a reboot.

```
# >>> rocky-vox >>>
dtparam=i2c_arm=on                 # /dev/i2c-1, for the amp's volume register
dtparam=audio=on                   # AUDIO=pwm
dtoverlay=audremap,pins_18_19      # AUDIO=pwm
# <<< rocky-vox <<<
```

`AUDIO=i2s` swaps the last two lines for `dtoverlay=hifiberry-dac`;
`AUDIO=usb` needs no overlay at all. Editing anything outside the markers is
safe, and the block never touches the rest of the file.

`dtparam=i2c_arm=on` enables the controller but does not on its own create
`/dev/i2c-1`. The `i2c-dev` module has to be loaded too, and nothing on a
headless image does it, so provisioning writes
`/etc/modules-load.d/rocky-vox.conf`.

`/etc/asound.conf` is generated from `deploy/asound.conf.in` with the card
for the chosen backend filled in, by *name* rather than index, so it survives
the HDMI codec probing in a different order after an update.

## State that outlives a power cut

The figurine gets unplugged rather than shut down, so anything that only
saved on SIGTERM would be lost every time. The volume level and the armed
state are both written to `state_file` a couple of seconds after they change,
and read back at startup. Dragging the volume slider costs one SD card write,
not one per frame.

## Checks

```
make i2c-scan      # 0x4b appears in the grid
make aplay-l       # the card for your AUDIO= backend
make speaker-test  # pink noise, left then right
make volume V=20   # audibly quieter
make volume V=45   # audibly louder
make state         # magnet, armed, volume, amp_online
```

| Symptom | Likely cause |
|---|---|
| `i2cdetect` finds nothing | `dtparam=i2c_arm=on` missing, `i2c-dev` unloaded, or no reboot yet |
| `i2cdetect: command not found` | it lives in `/usr/sbin`, which SSH does not put on `PATH` |
| `i2cdetect` hangs | mode jumper still bridged, or it is probing the write-only MAX9744 |
| `0x4b` missing but the bus scans | amp unpowered, or `Vi2c` not on 3V3 |
| Every I2C write is `ETIMEDOUT` | mode jumper partly bridged; read SDA and SCL at idle |
| `amp_online: false` in `/api/state` | amp unpowered, in analog mode, or the I2C wiring is off |
| No card in `aplay -l` | wrong `AUDIO=` backend, or no reboot yet |
| No USB card with `AUDIO=usb` | port still in gadget mode, or no OTG adapter |
| Card present, no sound | amp volume never set over I2C (see above), or `SHDN` held low |
| Amp hisses but passes no audio | classic never-set-volume symptom: `make i2c-scan`, then `make volume V=40` |
| Quiet even at full volume | PD source has no 12V profile and fell back to 5V |
| Amp cuts out on loud passages | PD current contract too small; use a bigger source |
| Volume back at full scale after reboot | `alsactl store` never run |
| Hiss between clips | wire `SHDN` to GPIO27 and set `shutdown_pin` |
| Distortion at high volume | lower `max_volume`, or drop the supply to 9V |
| Talks with the block in, quiet when pulled | set `magnet_present_is_low = false` |
| Pulling the block does nothing at all | the trigger is disarmed; check the toggle or `/api/state` |
| Never triggers, armed or not | flip the magnet over (unipolar sensors need one pole) |
| Retriggers on a knock | raise `bounce_seconds` |
