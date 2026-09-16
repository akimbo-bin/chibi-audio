from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import wave

import pytest

from chibi_audio.analysis import AnalysisCapability, AnalysisCost, AnalysisRequest, AudioAnalysisService


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_pcm16(path: Path, frames: list[tuple[float, ...]], sample_rate: int) -> None:
    payload = bytearray()
    channels = len(frames[0])
    for frame in frames:
        assert len(frame) == channels
        for sample in frame:
            sample = max(-1.0, min(32767 / 32768, sample))
            value = -32768 if sample <= -1.0 else round(sample * 32768)
            payload.extend(struct.pack("<h", max(-32768, min(32767, value))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def test_stereo_timeline_localizes_polarity_transition(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    frames: list[tuple[float, float]] = []
    for index in range(sample_rate * 2):
        value = 0.45 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate)
        right = value if index < sample_rate else -value
        frames.append((value, right))
    source = tmp_path / "stereo-transition.wav"
    _write_pcm16(source, frames, sample_rate)

    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.STEREO_TIMELINE}),
        max_cost=AnalysisCost.CHEAP,
        sample_rate=sample_rate,
        timeline_max_points=12,
    )
    service = AudioAnalysisService()
    assert [item.descriptor.name for item in service.registry.plan(request)] == ["numpy_stereo_timeline"]

    evidence = service.analyze(source, request).measurements[AnalysisCapability.STEREO_TIMELINE.value]
    assert evidence["available"] is True
    assert evidence["timeline_points"] <= 12
    assert evidence["timeline"][0]["correlation"] > 0.95
    assert evidence["timeline"][-1]["correlation"] < -0.95
    assert evidence["widest_sampled_window"]["side_energy_fraction"] > 0.95
    assert evidence["most_negative_correlation_window"]["correlation"] < -0.95


def test_stereo_timeline_refuses_original_mono_source(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    frames = [
        (0.4 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate),)
        for index in range(sample_rate)
    ]
    source = tmp_path / "mono.wav"
    _write_pcm16(source, frames, sample_rate)

    evidence = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.STEREO_TIMELINE}),
            max_cost=AnalysisCost.CHEAP,
            sample_rate=sample_rate,
        ),
    ).measurements[AnalysisCapability.STEREO_TIMELINE.value]
    assert evidence["available"] is False
    assert evidence["source_channels"] == 1
    assert "original two-channel" in evidence["reason"]


def test_loop_seam_distinguishes_periodic_boundary_from_broken_tail(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    clean: list[tuple[float, float]] = []
    for index in range(sample_rate):
        value = 0.5 * math.sin(2.0 * math.pi * 100.0 * index / sample_rate)
        clean.append((value, value))
    broken = list(clean)
    edge_frames = round(0.02 * sample_rate)
    for offset in range(edge_frames):
        original = broken[-edge_frames + offset][0]
        altered = -original + 0.25 * (offset / max(1, edge_frames - 1))
        broken[-edge_frames + offset] = (altered, altered)

    clean_path = tmp_path / "clean-loop.wav"
    broken_path = tmp_path / "broken-loop.wav"
    _write_pcm16(clean_path, clean, sample_rate)
    _write_pcm16(broken_path, broken, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.LOOP_SEAM}),
        max_cost=AnalysisCost.CHEAP,
        sample_rate=sample_rate,
    )
    service = AudioAnalysisService()
    assert [item.descriptor.name for item in service.registry.plan(request)] == ["numpy_loop_seam"]

    clean_evidence = service.analyze(clean_path, request).measurements[AnalysisCapability.LOOP_SEAM.value]
    broken_evidence = service.analyze(broken_path, request).measurements[AnalysisCapability.LOOP_SEAM.value]

    assert clean_evidence["available"] is True
    assert clean_evidence["head_tail_waveform_correlation"] > 0.99
    assert clean_evidence["max_abs_derivative_discontinuity"] < 0.01
    assert broken_evidence["max_abs_derivative_discontinuity"] > clean_evidence["max_abs_derivative_discontinuity"] * 5.0
    assert broken_evidence["head_tail_waveform_correlation"] < -0.9
    assert broken_evidence["head_tail_waveform_rmse_relative_to_peak"] > clean_evidence["head_tail_waveform_rmse_relative_to_peak"]


def test_loop_seam_reports_exact_requested_range(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    frames: list[tuple[float, float]] = []
    for index in range(sample_rate * 2):
        value = 0.35 * math.sin(2.0 * math.pi * 125.0 * index / sample_rate)
        frames.append((value, value))
    source = tmp_path / "range.wav"
    _write_pcm16(source, frames, sample_rate)

    evidence = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.LOOP_SEAM}),
            max_cost=AnalysisCost.CHEAP,
            sample_rate=sample_rate,
            start_seconds=0.5,
            end_seconds=1.5,
        ),
    ).measurements[AnalysisCapability.LOOP_SEAM.value]

    assert evidence["range"]["start_seconds"] == pytest.approx(0.5)
    assert evidence["range"]["end_seconds"] == pytest.approx(1.5, abs=0.002)
    assert evidence["range"]["duration_seconds"] == pytest.approx(1.0, abs=0.002)
    assert "binary judgement" in evidence["interpretation_note"]
