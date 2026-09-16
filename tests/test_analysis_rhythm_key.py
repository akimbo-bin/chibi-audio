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
    AnalysisReport,
    AnalysisRequest,
    AudioAnalysisService,
    align_capture_events,
    compare_reports,
)
from chibi_audio.analysis.librosa_adapter import _MAJOR_PROFILE, _key_candidates


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_pulse_train(path: Path, *, bpm: float = 120.0, seconds: float = 4.0, sample_rate: int = 22050) -> None:
    beat_seconds = 60.0 / bpm
    starts = [round(value * sample_rate) for value in np.arange(0.5, seconds, beat_seconds)]
    burst = max(1, round(0.025 * sample_rate))
    payload = bytearray()
    for index in range(round(seconds * sample_rate)):
        active = next((start for start in starts if start <= index < start + burst), None)
        if active is None:
            sample = 0.0
        else:
            offset = index - active
            sample = 0.85 * math.sin(2.0 * math.pi * 1800.0 * offset / sample_rate)
        value = max(-32768, min(32767, round(sample * 32768)))
        payload.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def _report(name: str, measurements: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=1,
        requested_capabilities=sorted(measurements),
        executed_analyzers=[],
        measurements=measurements,
    )


def test_librosa_descriptor_advertises_beats_and_key() -> None:
    descriptor = next(
        item for item in AudioAnalysisService().registry.descriptors() if item.name == "librosa_mir"
    )
    assert AnalysisCapability.MIR_BEATS in descriptor.capabilities
    assert AnalysisCapability.MIR_KEY in descriptor.capabilities
    assert descriptor.cost is AnalysisCost.MODERATE


def test_key_template_ranking_recovers_c_major_reference_profile() -> None:
    candidates = _key_candidates(np, np.asarray(_MAJOR_PROFILE, dtype=np.float64))
    assert len(candidates) == 24
    assert candidates[0]["label"] == "C major"
    assert candidates[0]["template_correlation"] == pytest.approx(1.0)
    assert candidates[0]["template_correlation"] > candidates[1]["template_correlation"]


def test_beat_grid_runs_on_real_librosa_path(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_mir")
    if not descriptor.available:
        pytest.skip(descriptor.unavailable_reason or "librosa unavailable")

    source = tmp_path / "beats.wav"
    _write_pulse_train(source)
    report = service.analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.MIR_BEATS}),
            max_cost=AnalysisCost.MODERATE,
            sample_rate=22050,
        ),
    )
    beats = report.measurements[AnalysisCapability.MIR_BEATS.value]

    assert beats["beat_count"] >= 4
    assert len(beats["beat_times_seconds"]) == beats["beat_count"]
    assert beats["tempo_bpm_evidence"] == pytest.approx(120.0, abs=8.0)
    assert beats["beat_interval_median_seconds"] == pytest.approx(0.5, abs=0.08)
    assert beats["beat_interval_coefficient_of_variation"] is not None
    assert "not authoritative" in beats["interpretation_note"]


def test_beat_events_align_across_capture_taps() -> None:
    capture = {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": "manifest.json",
        "experiment_id": "beats",
        "taps": [
            {
                "tap_id": 1,
                "source_label": "drums",
                "analysis": {"measurements": {"audio.mir.beats": {"beat_times_seconds": [1.0, 1.5]}}},
            },
            {
                "tap_id": 2,
                "source_label": "bass",
                "analysis": {"measurements": {"audio.mir.beats": {"beat_times_seconds": [1.02, 1.52]}}},
            },
        ],
    }

    result = align_capture_events(
        capture,
        capability=AnalysisCapability.MIR_BEATS,
        tolerance_seconds=0.03,
    )

    assert result["cluster_count"] == 2
    assert result["cross_tap_cluster_count"] == 2
    assert all(member["event_kind"] == "beat" for cluster in result["clusters"] for member in cluster["members"])


def test_report_comparison_carries_beat_and_key_candidate_evidence() -> None:
    left = _report(
        "left.wav",
        {
            "audio.mir.beats": {
                "beat_count": 8,
                "beat_density_per_second": 2.0,
                "tempo_bpm_evidence": 120.0,
                "beat_interval_median_seconds": 0.5,
                "beat_interval_coefficient_of_variation": 0.02,
            },
            "audio.mir.key": {
                "chroma_profile": {"C": 0.6, "E": 0.25, "G": 0.15},
                "top_candidate": {"label": "C major", "template_correlation": 0.9},
                "candidate_margin_to_second": 0.1,
            },
        },
    )
    right = _report(
        "right.wav",
        {
            "audio.mir.beats": {
                "beat_count": 10,
                "beat_density_per_second": 2.1,
                "tempo_bpm_evidence": 122.0,
                "beat_interval_median_seconds": 0.49,
                "beat_interval_coefficient_of_variation": 0.03,
            },
            "audio.mir.key": {
                "chroma_profile": {"C": 0.58, "E": 0.27, "G": 0.15},
                "top_candidate": {"label": "C major", "template_correlation": 0.88},
                "candidate_margin_to_second": 0.08,
            },
        },
    )

    result = compare_reports(left, right)
    beats = result["comparisons"]["audio.mir.beats"]
    key = result["comparisons"]["audio.mir.key"]

    assert beats["beat_count_delta"] == pytest.approx(2.0)
    assert beats["tempo_bpm_evidence_delta"] == pytest.approx(2.0)
    assert beats["beat_interval_coefficient_of_variation_delta"] == pytest.approx(0.01)
    assert key["left_top_candidate"] == "C major"
    assert key["right_top_candidate"] == "C major"
    assert key["chroma_cosine_similarity"] > 0.99
    assert key["candidate_margin_to_second_delta"] == pytest.approx(-0.02)
