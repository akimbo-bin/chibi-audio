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
    AnalysisReport,
    AnalysisRequest,
    AudioAnalysisService,
    compare_reports,
)


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_tone(path: Path, frequency: float, *, sample_rate: int = 16000) -> None:
    payload = bytearray()
    for index in range(sample_rate):
        sample = 0.4 * math.sin(2.0 * math.pi * frequency * index / sample_rate)
        value = max(-32768, min(32767, round(sample * 32767)))
        payload.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def test_librosa_timbre_analyzer_returns_bounded_interpretable_fingerprint(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_timbre")
    if not descriptor.available:
        pytest.skip(descriptor.unavailable_reason or "librosa unavailable")

    source = tmp_path / "tone.wav"
    _write_tone(source, 440.0)
    report = service.analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.MIR_TIMBRE}),
            max_cost=AnalysisCost.MODERATE,
            sample_rate=16000,
        ),
    )
    timbre = report.measurements[AnalysisCapability.MIR_TIMBRE.value]

    assert list(timbre["mfcc_shape_mean"]) == [f"c{index}" for index in range(1, 13)]
    assert len(timbre["spectral_contrast_mean_db"]) >= 2
    assert timbre["spectral_bandwidth"]["median_hz"] is not None
    assert timbre["harmonic_energy_fraction"] is not None
    assert timbre["percussive_energy_fraction"] is not None
    assert timbre["harmonic_energy_fraction"] + timbre["percussive_energy_fraction"] == pytest.approx(1.0)
    assert timbre["harmonic_energy_fraction"] > timbre["percussive_energy_fraction"]
    assert "not semantic" in timbre["interpretation_note"]


def test_timbre_requires_moderate_budget() -> None:
    service = AudioAnalysisService()
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_TIMBRE}),
        max_cost=AnalysisCost.CHEAP,
    )
    with pytest.raises(ValueError, match="audio.mir.timbre"):
        service.registry.plan(request)


def _report(name: str, value: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=123,
        requested_capabilities=["audio.mir.timbre"],
        executed_analyzers=[],
        measurements={"audio.mir.timbre": value},
    )


def test_timbre_report_comparison_exposes_shape_similarity_and_component_deltas() -> None:
    left = _report(
        "left.wav",
        {
            "mfcc_shape_mean": {"c1": -10.0, "c2": 5.0, "c3": 2.0},
            "mfcc_shape_std": {"c1": 2.0, "c2": 1.0, "c3": 0.5},
            "spectral_contrast_mean_db": {"band0": 12.0, "band1": 8.0},
            "spectral_bandwidth": {"median_hz": 1800.0},
            "harmonic_energy_fraction": 0.75,
            "percussive_energy_fraction": 0.25,
        },
    )
    right = _report(
        "right.wav",
        {
            "mfcc_shape_mean": {"c1": -9.0, "c2": 4.5, "c3": 2.2},
            "mfcc_shape_std": {"c1": 2.2, "c2": 1.1, "c3": 0.6},
            "spectral_contrast_mean_db": {"band0": 11.0, "band1": 8.5},
            "spectral_bandwidth": {"median_hz": 2300.0},
            "harmonic_energy_fraction": 0.60,
            "percussive_energy_fraction": 0.40,
        },
    )

    comparison = compare_reports(left, right)["comparisons"]["audio.mir.timbre"]

    assert comparison["mfcc_shape_mean_cosine_similarity"] > 0.99
    assert comparison["spectral_contrast_mean_cosine_similarity"] > 0.99
    assert comparison["spectral_bandwidth_median_hz_delta"] == pytest.approx(500.0)
    assert comparison["harmonic_energy_fraction_delta"] == pytest.approx(-0.15)
    assert comparison["percussive_energy_fraction_delta"] == pytest.approx(0.15)
