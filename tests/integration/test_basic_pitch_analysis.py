from __future__ import annotations

import math
from pathlib import Path
import struct
import wave

from chibi_audio.analysis import AnalysisCapability, AnalysisCost, AnalysisRequest, AudioAnalysisService


def _write_a4(path: Path, *, sample_rate: int = 22050, seconds: float = 2.0) -> None:
    payload = bytearray()
    for index in range(round(sample_rate * seconds)):
        envelope = min(1.0, index / (0.03 * sample_rate))
        value = 0.55 * envelope * math.sin(2.0 * math.pi * 440.0 * index / sample_rate)
        packed = struct.pack("<h", round(value * 32767))
        payload.extend(packed)
        payload.extend(packed)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(payload)


def test_basic_pitch_real_model_detects_a4(tmp_path: Path) -> None:
    source = tmp_path / "a4.wav"
    _write_a4(source)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_TRANSCRIPTION}),
        max_cost=AnalysisCost.EXPENSIVE,
        transcription_max_notes=32,
    )
    service = AudioAnalysisService()
    descriptor = next(
        item for item in service.registry.descriptors() if item.name == "basic_pitch_transcription"
    )
    assert descriptor.available, descriptor.unavailable_reason

    evidence = service.analyze(source, request).measurements[
        AnalysisCapability.MIR_TRANSCRIPTION.value
    ]
    assert evidence["note_count"] >= 1
    assert any(abs(note["midi_note"] - 69) <= 1 for note in evidence["note_events"])
    assert evidence["notes_truncated"] is False
