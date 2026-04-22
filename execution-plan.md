# pi-voice Execution Plan

This file tracks what to build and current status. For architecture decisions, platform
comparison, component rationale, and open questions, see
[voice-assistant-research.md](voice-assistant-research.md).

---

## Getting Started Plan

### Phase 0: Resource audit — COMPLETE

1. ~~Measure current RAM usage on Pi~~ Done: 1.3 GB used, 2.7 GB available
2. ~~Evaluate SQLite migration~~ Done: zero Postgres-specific features, clean switch
3. ~~Verify tests pass~~ Done: all 150 tests pass on SQLite
4. ~~Implement pi.conf~~ Done: 4 flags (database, workers, desktop, vnc)
5. ~~Deploy to Pi~~ Done: 864 MB used, 3.1 GB available after optimization

### Phase 1: Voice loop — COMPLETE

1. ~~Verify webcam mic works on Pi~~ Done: card 2, plughw:2,0, 16kHz mono capture OK
2. ~~Install OVOS components via pip~~ Done: see [pi-voice-setup.sh](pi-voice-setup.sh)
3. ~~Get wake word + VAD + STT + TTS configured~~ Done: listener starts, wake word loop running
4. ~~Create systemd services for OVOS~~ Done: messagebus, listener, audio, core — all enabled and auto-starting
5. ~~Verify end-to-end~~ Done (2026-04-22): "hey mycroft" → wake word detected → STT transcribed "How are you" → padacioso matched HowAreYou.intent → TTS spoke "Pretty well"
6. **TODO: Connect a speaker to hear TTS output**
7. **TODO: Test Whisper STT on Hailo (move from CPU to NPU)**

### Phase 2: First skill

7. Build kitchen timer: Good Morning countdown widget + OVOS skill + API endpoint
8. Proves the full voice → Hailo STT → intent → Good Morning API → UI loop

### Phase 3: Conversational fallback

9. Set up hailo-ollama with DeepSeek R1 1.5B or Qwen2 1.5B as Persona fallback
10. Accept ~11-13s latency for general conversation — this is about exploring Hailo
11. Claude API available as escape hatch, not the default

### Phase 4: Iterate

12. Add skills as use cases emerge (weather readout, recipe display, Spotify, etc.)

### Backlog

- Integration test framework (messagebus-level tests for skills, pipeline, STT/TTS)
- ~~Fix Google OAuth login on Good Morning~~ Done: settings-based config, Site domain fix, Chromium --ozone-platform=wayland
- Slideshow mode tweaks
- Connect speaker and verify TTS audio output
- Wake word customization (switch from "hey mycroft" to a custom word)

---

## First Skill: Kitchen Timer

The kitchen timer is the first concrete deliverable. Architecture:

1. **OVOS Adapt intent** parses "set a timer for 5 minutes"
2. **OVOS skill** POSTs to Good Morning backend API (`/api/timer/`)
3. **Good Morning backend** creates timer model, tracks countdown
4. **Good Morning frontend** renders countdown widget (replaces or overlays clock widget)
5. **Timer expiry**: backend notifies frontend (WebSocket or polling), OVOS plays audio alert

This proves the full voice→API→UI loop with zero window management. The timer widget
lives inside Good Morning as a first-class widget, same as clock/weather/stocks.

### Follow-on skills (backlog)

- "What's the weather?" — read from Good Morning's cached weather data, speak it
- "Show recipe [name]" — display recipe in Good Morning as an overlay or dedicated view
- "Play [song] on Spotify" — via ovos-skill-spotify + raspotify
- "Show dashboard" / "go home" — dismiss overlays, return to default layout

---

## Latency Budget — What "Slow" Actually Means

For **structured voice commands** (timer, play music, show dashboard):

| Stage | Component | Latency |
|---|---|---|
| Wake word | openWakeWord on CPU | ~100ms |
| Speech-to-text | Whisper on Hailo | 1-3s |
| Intent parsing | OVOS Adapt/Padatious (no LLM) | instant |
| Action dispatch | REST call to Good Morning API | instant |
| TTS confirmation | Piper on CPU | 1-2s |
| **Total** | | **2-5 seconds** |

For **general conversation** (LLM fallback, ~50 token response):

| LLM backend | Inference time | Total wake-to-speech |
|---|---|---|
| Hailo (1.5B model) | ~8s | ~11-13s |
| CPU Ollama (1.5B) | ~5s | ~8-10s |
| Claude API | ~1-1.5s | ~4-6s |

**Recommendation:** Run as much as possible on Hailo — STT and LLM inference. The point
is to explore the hardware's capabilities, not optimize for speed. Accept ~11-13s
wake-to-speech for general conversation. Use Hailo LLM (hailo-ollama with DeepSeek R1
1.5B or Qwen2 1.5B) as the conversational fallback. Claude API is available as an
escape hatch but not the default.

---

## Deployment Configuration (pi/pi.conf)

All flags are implemented and tested. See `goodmorning/pi/pi.conf` for details.

| Flag | Default | Options | Savings |
|---|---|---|---|
| GM_DATABASE | sqlite | sqlite, postgres | ~180 MB |
| GM_WORKERS | 1 | 1, 2, ... | ~100 MB per worker |
| GM_DESKTOP | lean | lean, full | ~130 MB |
| GM_VNC | off | on, off | ~43 MB |

Scripts updated: pi-setup.sh, pi-update.sh, pi-health.sh, deploy.sh.
All 150 backend tests pass on SQLite. settings.py handles empty DATABASE_URL
gracefully (falls through to SQLite with WAL mode).

---

## Resource Audit (Live Measurement, 2026-04-22)

**System:** Pi 5 4GB, Trixie Desktop, Good Morning running.

| Metric | Before | After | Change |
|---|---|---|---|
| RAM used | 1.3 GB | 864 MB | -436 MB |
| RAM available | 2.7 GB | 3.1 GB | +400 MB |

| Component | RSS (MB) | After Optimization | Action |
|---|---|---|---|
| Chromium (7 procs) | ~1,074 | ~1,074 | Keep (needed for display) |
| labwc compositor | 107 | 107 | Keep (display server) |
| Gunicorn (master+2w) | 232 | ~130 (1 worker) | GM_WORKERS=1 |
| APScheduler | 88 | 88 | Keep |
| pipewire+wireplumber | 57 | 57 | Keep (audio for voice) |
| xdg-desktop-portal | 57 | 57 | Keep (Chromium needs it) |
| wf-panel-pi (taskbar) | 55 | 0 | GM_DESKTOP=lean |
| wayvnc (VNC) | 43 | 0 | GM_VNC=off |
| pcmanfm (file mgr) | 42 | 0 | GM_DESKTOP=lean |
| squeekboard (keyboard) | 33 | 0 | GM_DESKTOP=lean |
| PostgreSQL (procs) | ~52 | 0 | GM_DATABASE=sqlite |
| PostgreSQL shared_buf | 128 | 0 | GM_DATABASE=sqlite |
| **Savings** | | **~453 MB** | |
