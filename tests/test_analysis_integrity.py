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


def _write_pcm16(path: Path, values: list[float], sample_rate: int) -> None:
    payload = bytearray()
    for sample in values:
        value = max(-1.0, min(32767 / 32768, sample))
        integer = -32768 if value <= -1.0 else round(value * 32768)
        packed = struct.pack("<h", max(-32768, min(32767, integer)))
        payload.extend(packed)
        payload.extend(packed)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def test_integrity_localizes_inserted_dropout_and_discontinuity(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    values = [
        0.35 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate)
        for index in range(sample_rate * 2)
    ]
    dropout_start = round(0.8 * sample_rate)
    dropout_end = round(0.9 * sample_rate)
    values[dropout_start:dropout_end] = [0.0] * (dropout_end - dropout_start)
    values[round(1.25 * sample_rate)] = 0.95
    source = tmp_path / "integrity.wav"
    _write_pcm16(source, values, sample_rate)

    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.INTEGRITY}),
        max_cost=AnalysisCost.CHEAP,
        sample_rate=sample_rate,
        silence_threshold_dbfs=-60.0,
    )
    service = AudioAnalysisService()
    assert [item.descriptor.name for item in service.registry.plan(request)] == ["numpy_integrity"]

    evidence = service.analyze(source, request).measurements[AnalysisCapability.INTEGRITY.value]
    assert evidence["sustained_silence_run_count"] >= 1
    assert evidence["longest_sustained_silence_seconds"] >= 0.09
    assert any(abs(row["start_seconds"] - 0.8) < 0.02 for row in evidence["sustained_silence_runs"])
    assert evidence["discontinuity_candidate_count"] >= 1
    assert any(abs(row["time_seconds"] - 1.25) < 0.01 for row in evidence["discontinuity_candidates"])
    assert "candidates rather than defect labels" in evidence["interpretation_note"]


def test_integrity_reports_dc_offset_without_calling_it_a_defect(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 8000
    values = [
        0.1 + 0.2 * math.sin(2.0 * math.pi * 100.0 * index / sample_rate)
        for index in range(sample_rate)
    ]
    source = tmp_path / "dc.wav"
    _write_pcm16(source, values, sample_rate)

    evidence = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(
            capabilities=frozenset({AnalysisCapability.INTEGRITY}),
            max_cost=AnalysisCost.CHEAP,
            sample_rate=sample_rate,
        ),
    ).measurements[AnalysisCapability.INTEGRITY.value]

    assert evidence["max_abs_dc_offset"] == pytest.approx(0.1, abs=0.005)
    assert evidence["near_full_scale_run_count"] == 0
    assert evidence["range"]["duration_seconds"] == pytest.approx(1.0, abs=0.002)
