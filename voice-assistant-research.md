# Voice Assistant on Raspberry Pi 5 + Hailo AI HAT+ 2

Research conducted 2026-04-22.

## Goal

General-purpose voice-to-action platform on Pi 5 + Hailo HAT+ 2. Extensible — add
capabilities over time as use cases emerge. Not a turnkey single-purpose solution.

---

## Platform Comparison

### OVOS (OpenVoiceOS) — Chosen

Community successor to Mycroft (which shut down Feb 2023 due to patent troll). Dutch
non-profit foundation registered 2024. Actively maintained as of early 2026.

**Why OVOS wins for general-purpose:**

- Plugin architecture — every component swappable (wake word, STT, TTS, intent parsing)
- Skill system — Python classes that respond to intents; add new actions by writing skills
- Persona pipeline — unrecognized intents fall through to Ollama or Claude for general conversation
- HiveMind — distribute processing across networked devices (Pi as satellite, server as brain)
- Wyoming protocol bridge — can expose components to Home Assistant without being locked in
- raspOVOS pre-built images for Pi (Lite / Hybrid / Offline variants)

**Caveats:** Community-grade software. Pre-built images are "semi-automated and might not
be well tested." Requires comfort with SSH and config files.

**Key resources:**

| Resource | URL |
|---|---|
| raspOVOS images | https://github.com/OpenVoiceOS/raspOVOS |
| ovos-core | https://github.com/OpenVoiceOS/ovos-core |
| Technical manual | https://openvoiceos.github.io/ovos-technical-manual/ |
| Community forum | https://community.openconversational.ai |
| Persona + LLM blog | https://blog.openvoiceos.org/posts/2025-05-06-when-your-voice-assistant-becomes-a-persona |
| Spotify skill | https://github.com/OpenVoiceOS/ovos-skill-spotify |
| Spotify media plugin | https://github.com/OpenVoiceOS/ovos-media-plugin-spotify |

### Home Assistant Voice — Passed

Mature voice pipeline (Wyoming protocol, faster-whisper, Piper, openWakeWord). Excellent
for home automation but the voice layer is designed around HA's Assist intent system.
Adding arbitrary non-HA actions requires workarounds. Better as an integration target
than the core platform.

### Custom Pipeline (ollama-STT-TTS) — Passed

Projects like [ollama-STT-TTS](https://github.com/sancliffe/ollama-STT-TTS) and
[Local-Voice](https://github.com/m15-ai/Local-Voice) are lighter weight and easier to
understand, but you end up rebuilding what OVOS already provides (skill loading, message
bus, plugin management, wake word handling).

### Rhasspy — Dead

Effectively absorbed into Home Assistant's Wyoming ecosystem. The core maintainer works
at Nabu Casa now. Rhasspy 3 "developer preview" is not production-ready and unlikely to
get standalone polish.

### Willow — Wrong Target

ESP32-focused hardware. Not relevant for Pi 5.

---

## Hailo AI HAT+ 2 Role

### Best use: Whisper STT accelerator

Hailo has a demonstrated Whisper integration. Offloads speech-to-text entirely from the
ARM cores, freeing CPU for LLM inference and TTS simultaneously. This is the single
biggest win for voice assistant use.

### Good use: Computer vision

Object detection, person detection (wake display on approach), gesture recognition. The
YOLOv8m demo is already working on the Pi (`c:\sourcecode\ai\hailo\`).

### Poor use: LLM inference

Hailo provides `hailo-ollama` (Ollama-compatible REST API) but benchmarks show it's
**slower than CPU** for small models:

| Model | Hailo-10H | Pi 5 CPU |
|---|---|---|
| DeepSeek R1 1.5B | 6.5 t/s | 9-10 t/s |
| Qwen2 1.5B | ~6.7 t/s | ~8-10 t/s |

Both bottleneck on shared LPDDR4X-4267 memory bandwidth. The only advantage is lower
power draw (7.2W vs 10.2W) and freeing CPU cores.

---

## Pipeline Architecture

```
Mic → openWakeWord (CPU, ~100ms, negligible load)
    → Whisper STT (Hailo-accelerated)
    → OVOS intent pipeline:
        1. Adapt (rule-based, fast)
        2. Padatious (intent classifier)
        3. Persona/LLM fallback (Ollama or Claude API)
    → Action dispatch (OVOS skills)
    → Piper TTS (CPU, near-realtime, medium-quality voice)
    → Speaker
```

### Component Details

**Wake word: openWakeWord**
- MIT licensed, free. Runs 15-20 models simultaneously on a single Pi 3 core.
- Built-in models: "hey jarvis", "alexa", "hey mycroft". Custom models possible.
- Used by Home Assistant. Near-zero overhead.

**STT: faster-whisper (Hailo-accelerated)**
- CTranslate2-based Whisper. `tiny.en` or `base.en` model.
- On CPU alone: ~3s for a typical utterance on Pi 5.
- Hailo acceleration offloads from CPU entirely.
- Alternative: whisper.cpp (C++, lower memory, good ARM NEON support).

**Intent parsing: OVOS multi-stage pipeline**
- Adapt: rule-based keyword matching (fastest, for structured commands)
- Padatious: ML intent classifier (for fuzzy matching)
- Persona fallback: routes to LLM for anything skills don't handle

**LLM: Claude API (initial) → Ollama (later)**
- Claude API: best natural language quality, ~0.5-1.5s round-trip
- Ollama on Pi 5 with gemma3:1b (8-15 t/s) or llama3.2:3b (2-5 t/s)
- OVOS Persona system supports any OpenAI-compatible API endpoint

**TTS: Piper**
- VITS neural TTS, ONNX runtime, ARM-optimized.
- Recommended voice: `en_US-lessac-medium` or `en_US-ryan-medium`
- Near-realtime on Pi 5 with medium-quality models.

**Spotify (nice-to-have):**
- `raspotify` — makes Pi a Spotify Connect device (audio endpoint, requires Premium)
- `ovos-skill-spotify` + `ovos-media-plugin-spotify` — voice search and playback control
- `spotipy` — Python library for Spotify Web API (search, queue, playback)

---

## Ollama on Pi 5 — Model Benchmarks

| Model | Params | Speed (t/s) | RAM | Voice Suitability |
|---|---|---|---|---|
| gemma3:1b | 1B | 8-15 | ~2-3 GB | Best (fast enough for real-time) |
| gemma2:2b | 2B | 8-15 | ~2-3 GB | Good |
| llama3.2:3b | 3B | 2-5 | ~3.5 GB | Acceptable (sweet spot smart vs fast) |
| qwen2.5:3b | 3B | 4-5 | ~5.4 GB | Acceptable |
| 7B models | 7B | 0.5-1 | ~7-8 GB | Impractical for voice |

Pi 5 has 4GB RAM, so models over ~3B will be tight. The 8GB Pi 5 would open up the 3B
models more comfortably.

---

## Other Mycroft Forks

**Neon AI** — enterprise/privacy-focused fork, predates OVOS (2017). More divergent from
Mycroft. Active as of 2025. Cooperative relationship with OVOS, shares plugin infra.
https://neon.ai

**HiveMind** — complementary OVOS project for multi-device distribution. Pi satellites
(mic + speaker) offload STT/TTS/skills to a more powerful server. Useful for multi-room.
https://blog.openvoiceos.org/posts/2025-07-25-A-real-use-case-with-OVOS-and-Hivemind

---

## Open Questions

### Resolved

1. ~~**Audio input hardware**~~ **RESOLVED: USB webcam mic.** Webcam already plugged into
   Pi exposes an ALSA audio input device. Use it for prototyping; upgrade to a dedicated
   mic later if wake word reliability is poor.

2. ~~**raspOVOS vs manual install**~~ **RESOLVED: manual pip install.** The Offline image
   is a full OS that would replace the working Trixie setup (Hailo drivers, Good Morning
   deploy, Docker, Chromium kiosk). OVOS is a Python app — install components via pip
   alongside the current system and run as systemd services:
   ```
   pip install ovos-core ovos-messagebus ovos-audio ovos-listener ovos-phal
   pip install ovos-ww-plugin-precise-onnx ovos-tts-plugin-piper ovos-stt-plugin-fasterwhisper
   ```

3. ~~**Hailo + Whisper integration**~~ Technical investigation task, not a decision.
   Hailo has demonstrated Whisper acceleration; need to verify it works with OVOS's STT
   plugin system (may need a custom plugin or adapter).

### Open

4. **Display switching strategy.** openWakeWord is purely audio — listens fine while Good
   Morning is in the foreground. Two display patterns identified:
   - **In-app overlays** (preferred): OVOS skill hits Good Morning API, dashboard renders
     the content as a widget. No window switching. Best for timer, weather details, etc.
   - **Push-to-foreground** (later): Run Openbox or similar lightweight WM instead of raw
     kiosk. OVOS skill uses `wmctrl` to raise/fullscreen external apps (YouTube, recipe).
     Good Morning stays as the "home" fullscreen window.
   **Decision:** Start with in-app overlays. Defer window management until an external-app
   use case is actually needed.

5. ~~**Pi 5 RAM (4GB)**~~ **RESOLVED: resource audit complete, pi.conf implemented.**
   See [execution-plan.md](execution-plan.md) for the full resource audit table and
   deployment configuration flags. Summary: ~453 MB freed; ~3.1 GB available for OVOS +
   Hailo after switching to SQLite, 1 Gunicorn worker, and lean desktop mode.
