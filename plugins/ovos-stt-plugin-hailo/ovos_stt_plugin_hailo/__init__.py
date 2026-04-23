"""OVOS STT plugin that runs Whisper on a Hailo NPU (8/8L/10H)."""

from __future__ import annotations

import site
import sys
import time
from pathlib import Path
from typing import Set

# The hailo-apps repo and its venv have the heavy dependencies (torch,
# transformers, hailo_platform).  Add them to sys.path so this plugin
# can import them from the OVOS venv without duplicating installs.
_EXTRA_PATHS = [
    "/opt/hailo-apps",
    "/opt/hailo-apps/.venv/lib/python3.13/site-packages",
    "/usr/lib/python3/dist-packages",  # system hailo_platform
]
for _p in _EXTRA_PATHS:
    if _p not in sys.path:
        sys.path.append(_p)

import numpy as np
from ovos_plugin_manager.templates.stt import STT
from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements


class HailoWhisperSTT(STT):
    """Speech-to-text using Whisper on a Hailo NPU.

    Config example (in mycroft.conf):
        "stt": {
            "module": "ovos-stt-plugin-hailo",
            "ovos-stt-plugin-hailo": {
                "variant": "base",
                "arch": "hailo10h"
            }
        }
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._pipeline = None
        self._chunk_length = None
        variant = self.config.get("variant", "base")
        arch = self.config.get("arch", "hailo10h")
        LOG.info("HailoWhisperSTT: variant=%s, arch=%s", variant, arch)
        self._variant = variant
        self._arch = arch

    @classproperty
    def runtime_requirements(cls) -> RuntimeRequirements:
        return RuntimeRequirements(
            internet_before_load=False,
            network_before_load=False,
            requires_internet=False,
            requires_network=False,
            no_internet_fallback=True,
            no_network_fallback=True,
        )

    def _ensure_pipeline(self) -> None:
        """Lazy-init the Hailo Whisper pipeline on first use."""
        if self._pipeline is not None:
            return

        from hailo_apps.python.core.common.core import resolve_hef_paths
        from hailo_apps.python.core.common.defines import (
            RESOURCES_ROOT_PATH_DEFAULT,
            RESOURCES_NPY_DIR_NAME,
            WHISPER_H8_APP,
        )
        from hailo_apps.python.standalone_apps.speech_recognition.whisper_pipeline import (
            WhisperPipeline,
        )

        # Model name lookup — same table as the standalone app
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
            "tiny.en": {
                "hailo10h": (
                    "tiny_en-whisper-encoder-10s",
                    "tiny_en-whisper-decoder-fixed-sequence",
                ),
            },
        }

        encoder_name, decoder_name = variant_models[self._variant][self._arch]
        resolved = resolve_hef_paths(
            hef_paths=[encoder_name, decoder_name],
            app_name=WHISPER_H8_APP,
            arch=self._arch,
        )
        encoder_path = str(resolved[0].path)
        decoder_path = str(resolved[1].path)

        npy_dir = str(Path(RESOURCES_ROOT_PATH_DEFAULT) / RESOURCES_NPY_DIR_NAME)
        add_embed = self._arch in ("hailo8", "hailo8l")

        LOG.info("HailoWhisperSTT: initializing pipeline...")
        LOG.info("  encoder: %s", encoder_path)
        LOG.info("  decoder: %s", decoder_path)

        self._pipeline = WhisperPipeline(
            encoder_path,
            decoder_path,
            variant=self._variant,
            npy_dir=npy_dir,
            add_embed=add_embed,
        )
        self._chunk_length = self._pipeline.get_chunk_length()
        LOG.info("HailoWhisperSTT: ready (chunk_length=%ds)", self._chunk_length)

    def execute(self, audio, language: str | None = None) -> str:
        """Transcribe audio using the Hailo Whisper pipeline.

        Args:
            audio: An AudioData object (from ovos_plugin_manager.utils.audio)
                   containing raw PCM audio at some sample rate.
            language: Ignored — Whisper base handles English.

        Returns:
            Transcribed text string.
        """
        self._ensure_pipeline()

        from hailo_apps.python.standalone_apps.speech_recognition.audio_utils import (
            improve_audio,
            preprocess_audio,
        )
        from hailo_apps.python.standalone_apps.speech_recognition.postprocessing import (
            clean_transcription,
        )

        # Convert AudioData to float32 numpy array at 16kHz
        raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

        if len(samples) == 0:
            return ""

        # Normalize and detect speech
        samples, start_time = improve_audio(samples)
        if start_time is None:
            LOG.debug("HailoWhisperSTT: no speech detected")
            return ""

        offset = max(start_time - 0.2, 0)
        mels = preprocess_audio(
            samples,
            chunk_length=self._chunk_length,
            chunk_offset=offset,
        )

        t0 = time.monotonic()
        results = []
        for mel in mels:
            self._pipeline.send_data(mel)
            time.sleep(0.05)
            text = self._pipeline.get_transcription()
            results.append(text)

        full_text = clean_transcription(" ".join(results)).strip()
        elapsed = time.monotonic() - t0
        LOG.info("HailoWhisperSTT: '%s' (%.1fs)", full_text, elapsed)
        return full_text

    @classproperty
    def available_languages(cls) -> Set[str]:
        return {"en"}


# Config entry for OPM discovery
HailoWhisperSTTConfig = {
    "lang": "en-us",
    "variant": "base",
    "arch": "hailo10h",
}
