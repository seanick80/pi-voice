# pi-voice

Voice assistant running on Raspberry Pi 5 with OVOS (OpenVoiceOS) and Hailo AI HAT+ 2.

## What This Is

A general-purpose voice recognition and action platform for Raspberry Pi 5.
Uses OVOS for the voice pipeline (wake word → STT → intent → skill → TTS)
with the Hailo-10H NPU running Whisper base for hardware-accelerated STT.

Integrates with the [Good Morning Dashboard](https://github.com/seanick80/goodmorning)
for display-based actions (timers, weather readout, recipe display, etc.).

## Hardware

- Raspberry Pi 5, 4GB RAM, Debian Trixie 64-bit
- Hailo AI HAT+ 2 (Hailo-10H, PCIe)
- USB webcam with microphone (plughw:2,0)
- Bluetooth speaker (bonelk)

## Voice Pipeline

```
Mic → precise-onnx wake word ("hey mycroft", CPU)
    → Whisper base STT (Hailo-10H NPU via hailo_stt_server)
    → OVOS intent pipeline (Adapt → Padacioso → Fallback)
    → Skill dispatch
    → Piper TTS (en_US-lessac-medium, CPU)
    → BT Speaker
```

### STT Architecture

The Hailo Whisper pipeline requires torch/transformers/hailo_platform (~600MB RSS).
Loading these into the OVOS listener process (4GB Pi) causes swap thrashing and
freezes the audio loop. Instead, we run a separate HTTP server:

```
OVOS listener → ovos-stt-plugin-server → http://127.0.0.1:8080/stt → hailo_stt_server.py
                (lightweight HTTP client)   (separate process, hailo-apps venv)
```

- `hailo_stt_server.py` — standalone HTTP server wrapping the Hailo WhisperPipeline
- `hailo-stt.service` — systemd service running the server on boot
- OVOS config uses `ovos-stt-plugin-server` pointing at `http://127.0.0.1:8080/stt`

## Installation

After deploying Good Morning on the Pi:

```bash
sudo bash /opt/pi-voice/pi-voice-setup.sh
```

This installs OVOS core, plugins, skills, configuration, and systemd services.
See [pi-voice-setup.sh](pi-voice-setup.sh) for details.

### Microphone Override

Default mic device is `plughw:2,0` (USB webcam). Override before running:

```bash
MIC_DEVICE=plughw:1,0 sudo bash /opt/pi-voice/pi-voice-setup.sh
```

## Services

```bash
# Check status
systemctl status ovos-messagebus ovos-listener ovos-audio ovos-core hailo-stt

# View listener logs (wake word + STT activity)
journalctl -u ovos-listener -f

# View Hailo STT server logs
journalctl -u hailo-stt -f

# View all OVOS logs
journalctl -u ovos-messagebus -u ovos-listener -u ovos-audio -u ovos-core -f

# Restart everything
sudo systemctl restart ovos-messagebus ovos-listener ovos-audio ovos-core
```

## Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| Timer | "set a timer for 5 minutes" | Kitchen timer with alarm, integrates with Good Morning dashboard |
| Spotify | "play [song/artist]" | Spotify playback via OCP + raspotify |

## Testing

Say "hey mycroft" near the webcam mic, then say one of:
- "set a timer for 10 seconds"
- "what time is it"
- "play some music"

Check logs for activity:
```bash
journalctl -u ovos-listener -u ovos-core --since '1 min ago' --no-pager
```

## Project Structure

```
pi-voice-setup.sh                          # Reproducible installation script
skills/ovos-skill-timer/                   # Kitchen timer skill
plugins/ovos-stt-plugin-hailo/             # Hailo Whisper STT (plugin + HTTP server)
hailo/                                     # Hailo AI HAT demos (YOLOv8m webcam)
execution-plan.md                          # Phased plan and status tracking
voice-assistant-research.md                # Platform comparison decisions
```

## Status

See [execution-plan.md](execution-plan.md) for current status and next steps.
