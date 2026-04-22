# pi-voice

Voice assistant running on Raspberry Pi 5 with OVOS (OpenVoiceOS) and Hailo AI HAT+ 2.

## What This Is

A general-purpose voice recognition and action platform for Raspberry Pi 5.
Uses OVOS for the voice pipeline (wake word → STT → intent → skill → TTS)
with the Hailo accelerator planned for Whisper STT offload.

Integrates with the [Good Morning Dashboard](https://github.com/seanick80/goodmorning)
for display-based actions (timers, weather readout, recipe display, etc.).

## Hardware

- Raspberry Pi 5, 4GB RAM, Debian Trixie 64-bit
- Hailo AI HAT+ 2 (Hailo-10H, PCIe)
- USB webcam with microphone (plughw:2,0)
- Speaker (USB, 3.5mm, or HDMI) — for TTS output

## Voice Pipeline

```
Mic → precise-onnx wake word ("hey mycroft", CPU)
    → faster-whisper STT (tiny.en, CPU — Hailo TODO)
    → OVOS intent pipeline (Adapt → Padacioso → Fallback)
    → Skill dispatch
    → Piper TTS (en_US-lessac-medium, CPU)
    → Speaker
```

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
systemctl status ovos-messagebus ovos-listener ovos-audio ovos-core

# View listener logs (wake word + STT activity)
journalctl -u ovos-listener -f

# View all OVOS logs
journalctl -u ovos-messagebus -u ovos-listener -u ovos-audio -u ovos-core -f

# Restart everything
sudo systemctl restart ovos-messagebus ovos-listener ovos-audio ovos-core
```

## Testing

Say "hey mycroft" near the webcam mic, then say one of:
- "hello world"
- "how are you"
- "thank you"

Check logs for activity:
```bash
journalctl -u ovos-listener -u ovos-core --since '1 min ago' --no-pager
```

Send a test utterance programmatically (bypasses microphone):
```python
from ovos_bus_client import MessageBusClient, Message
import time
client = MessageBusClient()
client.run_in_thread()
time.sleep(2)
client.emit(Message('recognizer_loop:utterance',
    {'utterances': ['hello world'], 'lang': 'en-us'}))
```

## Project Structure

```
pi-voice-setup.sh         # Reproducible installation script
execution-plan.md          # Phased plan and status tracking
voice-assistant-research.md # Platform comparison and architecture decisions
hailo/                     # Hailo AI HAT demos (YOLOv8m webcam)
```

## Status

See [execution-plan.md](execution-plan.md) for current status and next steps.
