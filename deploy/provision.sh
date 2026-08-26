#!/usr/bin/env bash
#
# One-time provisioning for Rocky Vox. Idempotent: safe to re-run after
# every deploy. Must be run as root on the Pi, from the deployed tree.
#
#   sudo /opt/rocky/deploy/provision.sh
#
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/rocky}
DATA_DIR=${DATA_DIR:-/srv/rocky}
CONF_DIR=${CONF_DIR:-/etc/rocky}
SERVICE=rocky-vox.service
RUN_USER=${RUN_USER:-rocky}

say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }

if [[ $EUID -ne 0 ]]; then
  warn "must run as root: sudo $0"
  exit 1
fi

reboot_required=0

# --- 1. packages -----------------------------------------------------
# Everything comes from apt. armv6 has almost no prebuilt wheels and
# compiling them on a 1GHz single core is not worth the wait.
say "installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3-flask python3-waitress python3-gpiozero python3-lgpio \
  python3-smbus2 alsa-utils ffmpeg i2c-tools espeak-ng

# --- 2. boot overlays ------------------------------------------------
CONFIG_TXT=/boot/firmware/config.txt
[[ -f $CONFIG_TXT ]] || CONFIG_TXT=/boot/config.txt
if [[ ! -f $CONFIG_TXT ]]; then
  warn "cannot find config.txt; enable I2C and the I2S DAC overlay by hand"
else
  ensure_line() {
    local line=$1
    if grep -qxF "$line" "$CONFIG_TXT"; then
      say "already set: $line"
    else
      say "adding to $(basename "$CONFIG_TXT"): $line"
      printf '\n# added by rocky-vox provision.sh\n%s\n' "$line" >>"$CONFIG_TXT"
      reboot_required=1
    fi
  }
  # I2C carries MAX9744 volume only; audio goes out over I2S.
  ensure_line "dtparam=i2c_arm=on"
  # PCM5102A / UDA1334A on GPIO18 (BCLK), 19 (LRCLK), 21 (DIN).
  ensure_line "dtoverlay=hifiberry-dac"

  if grep -qE '^[[:space:]]*dtparam=audio=on' "$CONFIG_TXT"; then
    say "leaving dtparam=audio=on alone (harmless: the Zero W has no analog out)"
  fi
fi

# --- 3. the i2c-dev char device --------------------------------------
# dtparam=i2c_arm=on enables the controller; i2c-dev is what actually
# creates /dev/i2c-1, and nothing else on a headless image loads it.
say "enabling the i2c-dev module"
printf '# added by rocky-vox provision.sh\ni2c-dev\n' >/etc/modules-load.d/rocky-vox.conf
modprobe i2c-dev || warn "i2c-dev will load on the next boot"

# --- 4. ALSA default device -----------------------------------------
say "installing /etc/asound.conf"
install -m 0644 "$APP_DIR/deploy/asound.conf" /etc/asound.conf

# --- 5. directories ---------------------------------------------------
say "creating $DATA_DIR and $CONF_DIR"
install -d -o "$RUN_USER" -g "$RUN_USER" -m 0755 "$DATA_DIR" "$DATA_DIR/clips" "$DATA_DIR/default"
install -d -m 0755 "$CONF_DIR"

if [[ -f $CONF_DIR/config.toml ]]; then
  say "keeping existing $CONF_DIR/config.toml"
else
  say "installing default $CONF_DIR/config.toml"
  install -m 0644 "$APP_DIR/deploy/config.toml.example" "$CONF_DIR/config.toml"
fi

# --- 6. the built-in clip --------------------------------------------
# Transcoded to WAV like every upload, so playback never has to decode.
say "installing the built-in clip"
python3 - "$APP_DIR" "$DATA_DIR" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "src"))
from rockyvox.config import load_config  # noqa: E402
from rockyvox.library import install_default_clip  # noqa: E402

source = next(iter(sorted((Path(sys.argv[1]) / "media" / "default").glob("*"))), None)
if source is None:
    raise SystemExit("no default clip found in media/default")
# Match whatever the installed config asks for, so the built-in clip is
# mixed the same way as every upload.
config = load_config(Path("/etc/rocky/config.toml"))
target = install_default_clip(source, Path(sys.argv[2]) / "default", config.mono_output)
print(f"    {source.name} -> {target}")
PY
chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR"
# Clips written before the 0644 change keep the 0600 that tempfile gave them.
find "$DATA_DIR" -type f -name '*.wav' -exec chmod 0644 {} +

# --- 7. service -------------------------------------------------------
say "installing $SERVICE"
install -m 0644 "$APP_DIR/deploy/$SERVICE" "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null

# --- 8. report --------------------------------------------------------
if [[ $reboot_required -eq 1 ]]; then
  warn "boot overlays changed: reboot before the DAC and I2C appear"
  warn "  sudo reboot"
else
  say "starting $SERVICE"
  systemctl restart "$SERVICE"
  # Importing Flask and waitress takes the better part of ten seconds on a
  # Zero W, so announce the URL only once the port actually answers.
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null http://127.0.0.1:8080/api/state 2>/dev/null; then
      say "listening on http://$(hostname).local:8080"
      exit 0
    fi
    sleep 0.5
  done
  warn "$SERVICE did not answer within 30s; check: journalctl -u $SERVICE"
  exit 1
fi
