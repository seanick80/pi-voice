"""Setup for ovos-stt-plugin-hailo — Whisper on Hailo NPU."""

from setuptools import setup, find_packages

setup(
    name="ovos-stt-plugin-hailo",
    version="0.1.0",
    description="OVOS STT plugin running Whisper on Hailo NPU (8/8L/10H)",
    packages=find_packages(),
    install_requires=[
        "ovos-plugin-manager>=0.0.1",
        "numpy",
    ],
    entry_points={
        "opm.stt": [
            "ovos-stt-plugin-hailo = ovos_stt_plugin_hailo:HailoWhisperSTT",
        ],
        "opm.stt.config": [
            "ovos-stt-plugin-hailo.config = ovos_stt_plugin_hailo:HailoWhisperSTTConfig",
        ],
    },
)
