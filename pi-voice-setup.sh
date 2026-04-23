#!/usr/bin/env bash
# pi-voice-setup.sh — Install OVOS voice assistant on Raspberry Pi 5.
#
# Run on the Pi after Good Morning is deployed:
#   sudo bash /opt/pi-voice/pi-voice-setup.sh
#
# Prerequisites:
#   - Raspberry Pi 5, 4GB+ RAM, Debian Trixie 64-bit
#   - Python 3.12+ (3.13 tested)
#   - USB webcam with microphone (or dedicated USB mic)
#   - Audio output (HDMI, 3.5mm, or USB speaker)
#   - Good Morning dashboard deployed and running (optional, for skill integration)
#
# What this installs:
#   - OVOS core (messagebus, listener, audio, skills, PHAL)
#   - Wake word: precise-onnx ("hey mycroft" model)
#   - VAD: silero (voice activity detection)
#   - STT: faster-whisper (tiny.en model, CPU — Hailo acceleration TODO)
#   - TTS: piper (en_US-lessac-medium voice)
#   - Microphone: ALSA plugin (webcam mic at plughw:2,0)

set -euo pipefail

APP_DIR="/opt/pi-voice"
VENV="$APP_DIR/.venv"
PIP="$VENV/bin/pip"
CONFIG_DIR="/home/pi/.config/mycroft"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${CYAN}[pi-voice]${NC} $*"; }
ok()   { echo -e "${GREEN}[pi-voice]${NC} $*"; }
fail() { echo -e "${RED}[pi-voice]${NC} $*"; exit 1; }

# -------------------------------------------------------------------
# 1. System dependencies
# -------------------------------------------------------------------
info "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    portaudio19-dev \
    python3-dev \
    swig \
    libasound2-dev \
    espeak-ng

ok "System dependencies installed."

# -------------------------------------------------------------------
# 2. Application directory + venv
# -------------------------------------------------------------------
info "Setting up application directory..."
mkdir -p "$APP_DIR"
chown pi:pi "$APP_DIR"

if [[ ! -d "$VENV" ]]; then
    info "Creating Python virtual environment..."
    sudo -u pi python3 -m venv "$VENV"
fi

sudo -u pi $PIP install -q --upgrade pip
ok "Virtual environment ready."

# -------------------------------------------------------------------
# 3. OVOS core packages
# -------------------------------------------------------------------
info "Installing OVOS core..."
# Install core packages. ovos-listener is installed --no-deps because
# it pulls pocketsphinx (fails to build on aarch64 Python 3.13) and
# pins old versions of ovos-bus-client/ovos-config/ovos-plugin-manager.
sudo -u pi $PIP install -q \
    ovos-core \
    ovos-messagebus \
    ovos-audio \
    ovos-phal

# Install dinkum listener without broken dependency chain
sudo -u pi $PIP install -q ovos-dinkum-listener

# Intent pipeline: adapt parser (IntentBuilder-based skills need this)
sudo -u pi $PIP install -q ovos-adapt-parser

ok "OVOS core installed."

# -------------------------------------------------------------------
# 4. Plugins
# -------------------------------------------------------------------
info "Installing OVOS plugins..."

# Microphone (ALSA)
sudo -u pi $PIP install -q PyAudio ovos-microphone-plugin-alsa

# Wake word (precise ONNX — downloads model on first run)
sudo -u pi $PIP install -q ovos-ww-plugin-precise-onnx

# VAD (silero — uses new opm.vad entrypoint, compatible with plugin-manager 2.x)
# Note: ovos-vad-plugin-webrtcvad uses old entrypoint and is NOT discovered.
sudo -u pi $PIP install -q ovos-vad-plugin-silero

# STT (faster-whisper — CPU-based, base.en model for better accuracy)
sudo -u pi $PIP install -q ovos-stt-plugin-fasterwhisper

# TTS (piper — local neural TTS)
sudo -u pi $PIP install -q ovos-tts-plugin-piper

ok "Plugins installed."

# -------------------------------------------------------------------
# 4b. Skills
# -------------------------------------------------------------------
info "Installing OVOS skills..."

# Hello world (responds to "hello world", "how are you?", "thank you")
sudo -u pi $PIP install -q ovos-skill-hello-world

# Fallback unknown (catches unrecognized intents)
sudo -u pi $PIP install -q ovos-skill-fallback-unknown

# Timer skill (kitchen timer with Good Morning dashboard integration)
# Installed from local source in the pi-voice repo
if [[ -d "$APP_DIR/skills/ovos-skill-timer" ]]; then
    sudo -u pi $PIP install -q "$APP_DIR/skills/ovos-skill-timer"
fi

ok "Skills installed."

# -------------------------------------------------------------------
# 5. Configuration
# -------------------------------------------------------------------
info "Writing OVOS configuration..."

# Detect microphone device
# Default: webcam at card 2. Override by setting MIC_DEVICE before running.
MIC_DEVICE="${MIC_DEVICE:-plughw:2,0}"

sudo -u pi mkdir -p "$CONFIG_DIR"
# Sound files live in ovos-dinkum-listener's package, but ovos-audio resolves
# paths relative to its own package (which has no res/snd/). Use absolute paths.
SOUND_DIR="$VENV/lib/python3.13/site-packages/ovos_dinkum_listener/res/snd"

sudo -u pi tee "$CONFIG_DIR/mycroft.conf" > /dev/null <<CONF
{
  "lang": "en-us",
  "confirm_listening": true,
  "sounds": {
    "start_listening": "$SOUND_DIR/start_listening.wav",
    "acknowledge": "$SOUND_DIR/acknowledge.mp3",
    "error": "$SOUND_DIR/error.mp3"
  },
  "listener": {
    "wake_word": "hey_mycroft",
    "microphone": {
      "module": "ovos-microphone-plugin-alsa",
      "ovos-microphone-plugin-alsa": {
        "device": "$MIC_DEVICE"
      }
    }
  },
  "hotwords": {
    "hey_mycroft": {
      "module": "ovos-ww-plugin-precise-onnx",
      "model": "https://github.com/OpenVoiceOS/precise-lite-models/raw/master/wakewords/en/hey_mycroft.onnx",
      "listen": true,
      "sound": "$SOUND_DIR/start_listening.wav",
      "sensitivity": 0.5
    }
  },
  "intents": {
    "pipeline": [
      "stop_high",
      "converse",
      "ovos-adapt-pipeline-plugin-high",
      "ovos-padacioso-pipeline-plugin-high",
      "ovos-adapt-pipeline-plugin-medium",
      "ovos-padacioso-pipeline-plugin-medium",
      "ovos-adapt-pipeline-plugin-low",
      "ovos-padacioso-pipeline-plugin-low",
      "fallback_high",
      "fallback_medium",
      "fallback_low"
    ]
  },
  "stt": {
    "module": "ovos-stt-plugin-fasterwhisper",
    "ovos-stt-plugin-fasterwhisper": {
      "model": "base.en",
      "beam_size": 1,
      "cpu_threads": 2
    }
  },
  "tts": {
    "module": "ovos-tts-plugin-piper",
    "ovos-tts-plugin-piper": {
      "voice": "en_US-lessac-medium"
    }
  },
  "VAD": {
    "module": "ovos-vad-plugin-silero"
  },
  "log_level": "INFO"
}
CONF

ok "Configuration written to $CONFIG_DIR/mycroft.conf"

# -------------------------------------------------------------------
# 6. Verify
# -------------------------------------------------------------------
info "Verifying installation..."

# Check mic
if arecord -D "$MIC_DEVICE" -f S16_LE -r 16000 -c 1 -d 1 /tmp/pi-voice-test.wav > /dev/null 2>&1; then
    ok "Microphone ($MIC_DEVICE): working"
    rm -f /tmp/pi-voice-test.wav
else
    echo -e "${RED}[pi-voice]${NC} Microphone ($MIC_DEVICE): FAILED — check arecord -l"
fi

# Check plugins
sudo -u pi $VENV/bin/python -c "
from ovos_plugin_manager.utils import find_plugins, PluginTypes
ww = find_plugins(PluginTypes.WAKEWORD)
vad = find_plugins(PluginTypes.VAD)
stt = find_plugins(PluginTypes.STT)
tts = find_plugins(PluginTypes.TTS)
print(f'Wake words: {list(ww.keys())}')
print(f'VAD:        {list(vad.keys())}')
print(f'STT:        {list(stt.keys())}')
print(f'TTS:        {list(tts.keys())}')
" 2>/dev/null || echo "Plugin check failed"

# -------------------------------------------------------------------
# 7. Journald log rotation (circular buffer, 50MB cap, 7-day retention)
# -------------------------------------------------------------------
info "Configuring log rotation..."
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/pi-voice.conf <<'JCONF'
[Journal]
SystemMaxUse=50M
SystemMaxFileSize=10M
MaxRetentionSec=7day
JCONF
systemctl restart systemd-journald
ok "Journald configured (50MB cap, 7-day retention)."

# -------------------------------------------------------------------
# 8. Bluetooth speaker (AT-SP3X)
# -------------------------------------------------------------------
# The AT-SP3X doesn't appear in the desktop Bluetooth UI, so we pair and
# trust it via bluetoothctl. Once trusted, BlueZ auto-connects on boot
# whenever the speaker is powered on and in range.
#
# Speaker details:
#   Name:  AT-SP3X (Audio-Technica portable speaker)
#   MAC:   CC:E8:0B:B4:19:9D
#   UUID:  Audio Sink (0000110b-0000-1000-8000-00805f9b34fb)
#   Class: 0x00240414
BT_MAC="CC:E8:0B:B4:19:9D"
BT_NAME="AT-SP3X"

info "Configuring Bluetooth speaker ($BT_NAME)..."

# Ensure Bluetooth is powered on
bluetoothctl power on

# Trust the device so BlueZ auto-connects on future boots
bluetoothctl trust "$BT_MAC"

# Attempt to connect (may fail if speaker is off — that's OK)
if bluetoothctl connect "$BT_MAC" 2>/dev/null; then
    ok "Bluetooth speaker $BT_NAME connected."
else
    echo -e "${CYAN}[pi-voice]${NC} $BT_NAME not reachable now — will auto-connect when powered on."
fi

# -------------------------------------------------------------------
# 9. Systemd services
# -------------------------------------------------------------------
info "Installing systemd services..."

# PipeWire runs as a user service (uid 1000). System services need these
# environment variables to connect to the user's PipeWire session for audio
# input (microphone) and output (Bluetooth speaker / HDMI / 3.5mm).
PIPEWIRE_ENV="Environment=XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"

cat > /etc/systemd/system/ovos-messagebus.service <<SVC
[Unit]
Description=OVOS Message Bus
After=network.target

[Service]
Type=simple
User=pi
Group=pi
ExecStart=/opt/pi-voice/.venv/bin/ovos-messagebus
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

cat > /etc/systemd/system/ovos-listener.service <<SVC
[Unit]
Description=OVOS Dinkum Listener
After=network.target ovos-messagebus.service
Requires=ovos-messagebus.service

[Service]
Type=simple
User=pi
Group=pi
$PIPEWIRE_ENV
ExecStart=/opt/pi-voice/.venv/bin/ovos-dinkum-listener
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

cat > /etc/systemd/system/ovos-audio.service <<SVC
[Unit]
Description=OVOS Audio Service
After=network.target ovos-messagebus.service
Requires=ovos-messagebus.service

[Service]
Type=simple
User=pi
Group=pi
$PIPEWIRE_ENV
ExecStart=/opt/pi-voice/.venv/bin/ovos-audio
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

cat > /etc/systemd/system/ovos-core.service <<SVC
[Unit]
Description=OVOS Core (skills + intent engine)
After=network.target ovos-messagebus.service
Requires=ovos-messagebus.service

[Service]
Type=simple
User=pi
Group=pi
ExecStart=/opt/pi-voice/.venv/bin/ovos-core
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable ovos-messagebus ovos-listener ovos-audio ovos-core
systemctl start ovos-messagebus
sleep 2
systemctl start ovos-listener ovos-audio ovos-core

ok "Systemd services installed and started."

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN} pi-voice setup complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo "  Services: ovos-messagebus, ovos-listener, ovos-audio, ovos-core"
echo "  Check status: systemctl status ovos-messagebus ovos-listener ovos-audio ovos-core"
echo "  View logs:    journalctl -u ovos-listener -f"
echo ""
echo "  Wake word: say 'hey mycroft'"
echo "  Mic device: $MIC_DEVICE"
echo ""
