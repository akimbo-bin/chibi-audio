from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import wave

import numpy as np
import pytest

from chibi_audio.analysis import (
    AnalysisCapability,
    AnalysisCost,
    AnalysisRequest,
    AudioAnalysisService,
)
from chibi_audio.analysis.basic_pitch_adapter import (
    _pitch_class_profile,
    _polyphony_peak,
    basic_pitch_descriptor,
)
from chibi_audio.analysis.semantic import _window_starts, hf_clap_descriptor


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.fail("analysis CI contract requires ffmpeg and ffprobe")


def _write_sine(path: Path, frequency: float, *, sample_rate: int = 16000, seconds: float = 1.5) -> None:
    payload = bytearray()
    for index in range(round(sample_rate * seconds)):
        value = 0.5 * math.sin(2.0 * math.pi * frequency * index / sample_rate)
        packed = struct.pack("<h", round(value * 32767))
        payload.extend(packed)
        payload.extend(packed)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(payload)


def test_semantic_request_requires_bounded_queries_and_enters_cache_identity() -> None:
    with pytest.raises(ValueError, match="semantic query"):
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.SEMANTIC}),
            max_cost=AnalysisCost.EXPENSIVE,
        )

    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.SEMANTIC}),
        max_cost=AnalysisCost.EXPENSIVE,
        semantic_queries=("dark closed hi-hat", "bright metallic hi-hat"),
        semantic_max_windows=7,
    )
    assert request.cache_payload()["semantic_queries"] == [
        "dark closed hi-hat",
        "bright metallic hi-hat",
    ]
    assert request.cache_payload()["semantic_max_windows"] == 7


def test_clap_is_fail_closed_without_explicit_local_model_identity(monkeypatch) -> None:
    monkeypatch.delenv("CHIBI_AUDIO_CLAP_MODEL_DIR", raising=False)
    monkeypatch.delenv("CHIBI_AUDIO_CLAP_MODEL_SHA256", raising=False)
    descriptor = hf_clap_descriptor()
    assert descriptor.cost is AnalysisCost.EXPENSIVE
    assert descriptor.available is False
    assert "CHIBI_AUDIO_CLAP_MODEL_DIR" in (descriptor.unavailable_reason or "")
    assert "CHIBI_AUDIO_CLAP_MODEL_SHA256" in (descriptor.unavailable_reason or "")


def test_semantic_window_selection_is_deterministic_and_bounded() -> None:
    assert _window_starts(100, 1000, 12, np) == [0]
    first = _window_starts(48000 * 35, 48000 * 10, 3, np)
    second = _window_starts(48000 * 35, 48000 * 10, 3, np)
    assert first == second
    assert first[0] == 0
    assert first[-1] == 48000 * 25
    assert len(first) == 3


def test_basic_pitch_helpers_summarize_full_event_set_without_model_runtime() -> None:
    events = [
        (0.0, 1.0, 60, 1.0, None),
        (0.5, 1.5, 64, 0.5, None),
        (1.5, 2.0, 67, 1.0, None),
    ]
    assert _polyphony_peak(events) == 2
    profile = _pitch_class_profile(events)
    assert profile["C"] > profile["E"]
    assert profile["G"] > 0.0

    descriptor = basic_pitch_descriptor()
    assert descriptor.cost is AnalysisCost.EXPENSIVE
    assert AnalysisCapability.MIR_TRANSCRIPTION in descriptor.capabilities


def test_librosa_pyin_tracks_monophonic_a4(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    librosa_descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_mir")
    assert librosa_descriptor.available, librosa_descriptor.unavailable_reason

    source = tmp_path / "a4.wav"
    _write_sine(source, 440.0)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_PITCH}),
        max_cost=AnalysisCost.MODERATE,
        sample_rate=16000,
    )
    evidence = service.analyze(source, request).measurements[AnalysisCapability.MIR_PITCH.value]

    assert evidence["voiced_frame_fraction"] > 0.70
    assert evidence["median_hz"] == pytest.approx(440.0, rel=0.03)
    assert evidence["median_midi"] == pytest.approx(69.0, abs=0.35)
    assert evidence["median_pitch_class_evidence"] == "A"
