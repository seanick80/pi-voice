"""Lightweight HTTP server wrapping Hailo Whisper STT.

Runs as a standalone process so the heavy torch/transformers/hailo_platform
imports don't load into the OVOS listener process (which only has 4GB RAM).

OVOS connects via ovos-stt-plugin-server pointing at http://127.0.0.1:8080.

Usage:
    /opt/hailo-apps/.venv/bin/python /opt/pi-voice/plugins/ovos-stt-plugin-hailo/hailo_stt_server.py
"""

from __future__ import annotations

import io
import sys
import time
import wave
from http.server import HTTPServer, BaseHTTPRequestHandler

import numpy as np

# Add hailo-apps to path
sys.path.insert(0, "/opt/hailo-apps")

# Globals — initialized once at startup
pipeline = None
chunk_length = None


def init_pipeline(variant: str = "base", arch: str = "hailo10h") -> None:
    """Initialize the Hailo Whisper pipeline (one-time)."""
    global pipeline, chunk_length

    from hailo_apps.python.core.common.core import resolve_hef_paths
    from hailo_apps.python.core.common.defines import (
        RESOURCES_ROOT_PATH_DEFAULT,
        RESOURCES_NPY_DIR_NAME,
        WHISPER_H8_APP,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.whisper_pipeline import (
        WhisperPipeline,
    )
    from pathlib import Path

    variant_models = {
        "base": {
            "hailo10h": (
                "base-whisper-encoder-10s",
                "base-whisper-decoder-10s-out-seq-64",
            ),
        },
        "tiny": {
            "hailo10h": (
                "tiny-whisper-encoder-10s",
                "tiny-whisper-decoder-fixed-sequence",
            ),
        },
    }

    encoder_name, decoder_name = variant_models[variant][arch]
    resolved = resolve_hef_paths(
        hef_paths=[encoder_name, decoder_name],
        app_name=WHISPER_H8_APP,
        arch=arch,
    )

    npy_dir = str(Path(RESOURCES_ROOT_PATH_DEFAULT) / RESOURCES_NPY_DIR_NAME)
    add_embed = arch in ("hailo8", "hailo8l")

    print(f"[hailo-stt] Initializing pipeline (variant={variant}, arch={arch})...")
    pipeline = WhisperPipeline(
        str(resolved[0].path),
        str(resolved[1].path),
        variant=variant,
        npy_dir=npy_dir,
        add_embed=add_embed,
    )
    chunk_length = pipeline.get_chunk_length()
    print(f"[hailo-stt] Ready (chunk_length={chunk_length}s)")


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe WAV audio bytes to text."""
    from hailo_apps.python.standalone_apps.speech_recognition.audio_utils import (
        improve_audio,
        preprocess_audio,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.postprocessing import (
        clean_transcription,
    )

    # Parse WAV
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        sr = wf.getframerate()
        sw = wf.getsampwidth()

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if len(samples) == 0:
        return ""

    # Resample to 16kHz if needed
    if sr != 16000:
        from scipy.signal import resample
        samples = resample(samples, int(len(samples) * 16000 / sr))

    samples, start_time = improve_audio(samples)
    if start_time is None:
        return ""

    offset = max(start_time - 0.2, 0)
    mels = preprocess_audio(samples, chunk_length=chunk_length, chunk_offset=offset)

    t0 = time.monotonic()
    results = []
    for mel in mels:
        pipeline.send_data(mel)
        time.sleep(0.05)
        text = pipeline.get_transcription()
        results.append(text)

    full_text = clean_transcription(" ".join(results)).strip()
    elapsed = time.monotonic() - t0
    print(f"[hailo-stt] '{full_text}' ({elapsed:.1f}s)")
    return full_text


class STTHandler(BaseHTTPRequestHandler):
    """Handle POST /stt with WAV body, return plain text transcription."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        audio_bytes = self.rfile.read(length)

        text = transcribe(audio_bytes)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, fmt, *args) -> None:
        # Suppress default access logs
        pass


def main() -> None:
    init_pipeline()
    server = HTTPServer(("127.0.0.1", 8080), STTHandler)
    print("[hailo-stt] Listening on http://127.0.0.1:8080")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[hailo-stt] Shutting down.")
        pipeline.stop()


if __name__ == "__main__":
    main()
