from __future__ import annotations

import math
from pathlib import Path
import random
import shutil
import struct
import wave

import pytest

from chibi_audio.analysis import (
    AnalysisCapability,
    AnalysisCost,
    AnalysisRequest,
    AudioAnalysisService,
)


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_pcm16(path: Path, frames: list[tuple[float, float]], sample_rate: int = 48000) -> None:
    payload = bytearray()
    for left, right in frames:
        for sample in (left, right):
            sample = max(-1.0, min(32767 / 32768, sample))
            value = -32768 if sample <= -1.0 else round(sample * 32768)
            payload.extend(struct.pack("<h", max(-32768, min(32767, value))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def test_transient_envelope_is_cheap_and_localizes_strongest_event(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 16000
    count = sample_rate * 2
    frames = []
    burst_start = int(0.75 * sample_rate)
    burst_length = int(0.20 * sample_rate)
    for index in range(count):
        if burst_start <= index < burst_start + burst_length:
            offset = index - burst_start
            envelope = math.exp(-offset / (0.035 * sample_rate))
            value = 0.9 * envelope * math.sin(2 * math.pi * 1400 * offset / sample_rate)
        else:
            value = 0.0
        frames.append((value, value))
    source = tmp_path / "transient.wav"
    _write_pcm16(source, frames, sample_rate)

    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.TRANSIENTS}),
        max_cost=AnalysisCost.CHEAP,
        sample_rate=sample_rate,
    )
    service = AudioAnalysisService()
    plan = service.registry.plan(request)
    assert [analyzer.descriptor.name for analyzer in plan] == ["numpy_transient_envelope"]

    evidence = service.analyze(source, request).measurements[AnalysisCapability.TRANSIENTS.value]
    assert evidence["strongest_event_time_seconds"] == pytest.approx(0.78, abs=0.08)
    assert evidence["strongest_frame_rms_dbfs"] is not None
    assert evidence["strong_rise_density_per_second"] >= 0.0
    assert evidence["range"]["duration_seconds"] == pytest.approx(2.0, abs=0.002)


def test_texture_separates_tonal_and_noise_like_material(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 16000
    seconds = 1.0
    count = int(sample_rate * seconds)
    tone = []
    noise = []
    rng = random.Random(12345)
    for index in range(count):
        value = 0.45 * math.sin(2 * math.pi * 440 * index / sample_rate)
        tone.append((value, value))
        noise_value = rng.uniform(-0.45, 0.45)
        noise.append((noise_value, noise_value))

    tone_path = tmp_path / "tone.wav"
    noise_path = tmp_path / "noise.wav"
    _write_pcm16(tone_path, tone, sample_rate)
    _write_pcm16(noise_path, noise, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.TEXTURE}),
        max_cost=AnalysisCost.MODERATE,
        sample_rate=sample_rate,
        spectral_window_size=2048,
        spectral_max_windows=8,
    )
    service = AudioAnalysisService()

    tone_evidence = service.analyze(tone_path, request).measurements[AnalysisCapability.TEXTURE.value]
    noise_evidence = service.analyze(noise_path, request).measurements[AnalysisCapability.TEXTURE.value]

    assert noise_evidence["spectral_flatness_mean"] > tone_evidence["spectral_flatness_mean"]
    assert noise_evidence["zero_crossing_fraction"] > tone_evidence["zero_crossing_fraction"]
    assert noise_evidence["energy_above_4khz_fraction"] > tone_evidence["energy_above_4khz_fraction"]


def test_frequency_dependent_stereo_finds_low_in_phase_and_high_opposed(tmp_path: Path) -> None:
    _require_ffmpeg()
    sample_rate = 48000
    count = sample_rate
    frames = []
    for index in range(count):
        low = 0.30 * math.sin(2 * math.pi * 120 * index / sample_rate)
        high = 0.20 * math.sin(2 * math.pi * 5000 * index / sample_rate)
        frames.append((low + high, low - high))
    source = tmp_path / "band-stereo.wav"
    _write_pcm16(source, frames, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.STEREO_BANDS}),
        max_cost=AnalysisCost.MODERATE,
        spectral_window_size=4096,
        spectral_max_windows=8,
    )

    evidence = AudioAnalysisService().analyze(source, request).measurements[
        AnalysisCapability.STEREO_BANDS.value
    ]
    assert evidence["available"] is True
    assert evidence["bands"]["low"]["correlation_evidence"] > 0.95
    assert evidence["bands"]["low"]["side_energy_fraction"] < 0.05
    assert evidence["bands"]["high_mid"]["correlation_evidence"] < -0.95
    assert evidence["bands"]["high_mid"]["side_energy_fraction"] > 0.95


def test_librosa_structure_localizes_large_spectral_change_when_available(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_mir")
    if not descriptor.available:
        pytest.skip(descriptor.unavailable_reason or "librosa unavailable")

    sample_rate = 16000
    count = sample_rate * 4
    frames = []
    for index in range(count):
        time = index / sample_rate
        frequency = 220.0 if time < 2.0 else 1800.0
        value = 0.4 * math.sin(2 * math.pi * frequency * time)
        frames.append((value, value))
    source = tmp_path / "structure.wav"
    _write_pcm16(source, frames, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_STRUCTURE}),
        max_cost=AnalysisCost.MODERATE,
        sample_rate=sample_rate,
    )

    evidence = service.analyze(source, request).measurements[AnalysisCapability.MIR_STRUCTURE.value]
    assert evidence["boundary_candidates_seconds"]
    assert min(abs(value - 2.0) for value in evidence["boundary_candidates_seconds"]) < 0.30
    assert evidence["novelty_p95"] >= evidence["novelty_median"]
    assert set(evidence["local_tempo_evidence"]) == {"median_bpm", "p10_bpm", "p90_bpm"}
