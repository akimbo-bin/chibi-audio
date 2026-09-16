from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import wave

import pytest

from chibi_audio.analysis import (
    AnalysisCapability,
    AnalysisCost,
    AnalysisRequest,
    AnalysisUnavailable,
    AudioAnalysisService,
)


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_tone_step(
    path: Path,
    *,
    first_frequency: float,
    second_frequency: float,
    first_amplitude: float,
    second_amplitude: float,
    seconds_per_half: float,
    sample_rate: int,
) -> None:
    payload = bytearray()
    half_frames = round(seconds_per_half * sample_rate)
    for index in range(half_frames * 2):
        if index < half_frames:
            frequency = first_frequency
            amplitude = first_amplitude
            local_index = index
        else:
            frequency = second_frequency
            amplitude = second_amplitude
            local_index = index - half_frames
        sample = amplitude * math.sin(2.0 * math.pi * frequency * local_index / sample_rate)
        value = max(-32768, min(32767, round(sample * 32767)))
        payload.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def test_dynamics_timeline_detects_large_level_step(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "level-step.wav"
    _write_tone_step(
        source,
        first_frequency=220.0,
        second_frequency=220.0,
        first_amplitude=0.05,
        second_amplitude=0.5,
        seconds_per_half=2.0,
        sample_rate=8000,
    )

    report = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.DYNAMICS}),
            max_cost=AnalysisCost.CHEAP,
            sample_rate=8000,
            timeline_max_points=12,
        ),
    )
    dynamics = report.measurements[AnalysisCapability.DYNAMICS.value]

    assert dynamics["second_minus_first_half_db"] > 15.0
    assert dynamics["macro_dynamic_p90_to_p10_db"] > 15.0
    assert dynamics["loudest_window"]["time_seconds"] > 2.0
    assert dynamics["timeline_points"] <= 12
    assert "not LUFS" in dynamics["interpretation_note"]


def test_spectral_timeline_detects_low_to_high_transition(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "spectral-step.wav"
    _write_tone_step(
        source,
        first_frequency=100.0,
        second_frequency=8000.0,
        first_amplitude=0.4,
        second_amplitude=0.4,
        seconds_per_half=2.0,
        sample_rate=48000,
    )

    report = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.SPECTRAL_TIMELINE}),
            max_cost=AnalysisCost.MODERATE,
            sample_rate=48000,
            spectral_window_size=2048,
            spectral_max_windows=24,
            timeline_max_points=24,
        ),
    )
    spectrum = report.measurements[AnalysisCapability.SPECTRAL_TIMELINE.value]

    assert spectrum["sampled_windows"] <= 24
    assert spectrum["spectral_centroid"]["p90_minus_p10_hz"] > 5000.0
    assert spectrum["timeline"][0]["band_energy_fraction"]["low"] > 0.8
    assert spectrum["timeline"][-1]["band_energy_fraction"]["high"] > 0.8
    assert spectrum["largest_sampled_spectral_shift"]["band_fraction_euclidean_distance"] > 0.5


def test_spectral_timeline_respects_cost_budget() -> None:
    service = AudioAnalysisService()
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.SPECTRAL_TIMELINE}),
        max_cost=AnalysisCost.CHEAP,
    )
    with pytest.raises(AnalysisUnavailable, match="audio.spectrum.timeline"):
        service.registry.plan(request)

    dynamics_plan = service.registry.plan(
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.DYNAMICS}),
            max_cost=AnalysisCost.CHEAP,
        )
    )
    assert [item.descriptor.name for item in dynamics_plan] == ["numpy_dynamics_timeline"]


def test_timeline_point_bound_is_validated_and_cached() -> None:
    with pytest.raises(ValueError, match="timeline_max_points"):
        AnalysisRequest(timeline_max_points=3)

    first = AnalysisRequest(timeline_max_points=16).cache_payload()
    second = AnalysisRequest(timeline_max_points=32).cache_payload()
    assert first["timeline_max_points"] == 16
    assert first != second
