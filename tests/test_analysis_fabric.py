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


def _sine(frequency: float, seconds: float, amplitude: float = 0.5, sample_rate: int = 48000):
    count = round(seconds * sample_rate)
    return [
        (
            amplitude * math.sin(2 * math.pi * frequency * index / sample_rate),
            amplitude * math.sin(2 * math.pi * frequency * index / sample_rate),
        )
        for index in range(count)
    ]


def _pulse_train(seconds: float = 2.0, sample_rate: int = 48000):
    count = round(seconds * sample_rate)
    starts = [round(value * sample_rate) for value in (0.25, 0.75, 1.25, 1.75)]
    burst = round(0.02 * sample_rate)
    frames = []
    for index in range(count):
        active_start = next((start for start in starts if start <= index < start + burst), None)
        if active_start is None:
            value = 0.0
        else:
            offset = index - active_start
            value = 0.8 * math.sin(2 * math.pi * 2000 * offset / sample_rate)
        frames.append((value, value))
    return frames


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def test_capability_report_exposes_optional_librosa_without_requiring_it() -> None:
    report = AudioAnalysisService().capability_report()
    by_name = {item["name"]: item for item in report}

    assert by_name["numpy_signal"]["available"] is True
    assert by_name["numpy_spectrum"]["cost"] == "MODERATE"
    assert by_name["ffmpeg_loudnorm"]["capabilities"] == ["audio.loudness"]
    assert by_name["librosa_mir"]["license"] == "ISC"
    assert "audio.mir.onsets" in by_name["librosa_mir"]["capabilities"]


def test_cost_budget_refuses_spectrum_when_only_cheap_is_allowed() -> None:
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.SPECTRUM}),
        max_cost=AnalysisCost.CHEAP,
    )
    with pytest.raises(AnalysisUnavailable, match="audio.spectrum"):
        AudioAnalysisService().registry.plan(request)


def test_signal_capabilities_share_one_analyzer() -> None:
    request = AnalysisRequest(
        capabilities=frozenset(
            {AnalysisCapability.LEVELS, AnalysisCapability.ACTIVITY, AnalysisCapability.STEREO}
        )
    )
    plan = AudioAnalysisService().registry.plan(request)
    assert [analyzer.descriptor.name for analyzer in plan] == ["numpy_signal"]


def test_time_range_limits_analysis_and_reports_absolute_activity(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "range.wav"
    sample_rate = 8000
    frames = [(0.0, 0.0)] * sample_rate + [(0.5, 0.5)] * sample_rate + [(0.0, 0.0)] * sample_rate
    _write_pcm16(source, frames, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.LEVELS, AnalysisCapability.ACTIVITY}),
        start_seconds=0.5,
        end_seconds=2.5,
        sample_rate=sample_rate,
    )

    report = AudioAnalysisService().analyze(source, request)
    levels = report.measurements[AnalysisCapability.LEVELS.value]
    activity = report.measurements[AnalysisCapability.ACTIVITY.value]

    assert levels["range"]["duration_seconds"] == pytest.approx(2.0, abs=0.002)
    assert activity["first_active_seconds"] == pytest.approx(1.0, abs=0.002)
    assert activity["last_active_seconds"] == pytest.approx(1.999875, abs=0.001)
    assert activity["active_frame_fraction"] == pytest.approx(0.5, abs=0.002)


def test_spectrum_uses_channel_power_not_mono_sum(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "opposed.wav"
    sample_rate = 48000
    count = round(0.2 * sample_rate)
    frames = []
    for index in range(count):
        value = 0.6 * math.sin(2 * math.pi * 1000 * index / sample_rate)
        frames.append((value, -value))
    _write_pcm16(source, frames, sample_rate)
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.SPECTRUM}),
        max_cost=AnalysisCost.MODERATE,
        spectral_window_size=2048,
        spectral_max_windows=4,
    )

    spectrum = AudioAnalysisService().analyze(source, request).measurements[AnalysisCapability.SPECTRUM.value]

    assert spectrum["spectral_centroid_hz"] == pytest.approx(1000, abs=25)
    assert spectrum["band_energy_fraction"]["mid"] > 0.98


def test_loudness_is_opt_in_and_bounded_to_requested_range(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "loudness.wav"
    _write_pcm16(source, _sine(440, 3.0, amplitude=0.25))
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.LOUDNESS}),
        max_cost=AnalysisCost.MODERATE,
        start_seconds=0.5,
        end_seconds=2.5,
    )

    loudness = AudioAnalysisService().analyze(source, request).measurements[AnalysisCapability.LOUDNESS.value]

    assert loudness["integrated_lufs"] is not None
    assert loudness["true_peak_dbtp"] is not None
    assert loudness["range"]["start_seconds"] == pytest.approx(0.5)
    assert loudness["range"]["end_seconds"] == pytest.approx(2.5)


def test_librosa_tonal_adapter_runs_when_available(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_mir")
    if not descriptor.available:
        pytest.skip(descriptor.unavailable_reason or "librosa unavailable")
    source = tmp_path / "a440.wav"
    _write_pcm16(source, _sine(440, 1.0, amplitude=0.4))
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_TONAL}),
        max_cost=AnalysisCost.MODERATE,
    )

    tonal = service.analyze(source, request).measurements[AnalysisCapability.MIR_TONAL.value]

    assert tonal["dominant_pitch_class_evidence"] == "A"
    assert tonal["chroma_profile"]["A"] == max(tonal["chroma_profile"].values())
    assert tonal["tonal_concentration"] is not None


def test_librosa_onset_adapter_detects_synthetic_pulses_when_available(tmp_path: Path) -> None:
    _require_ffmpeg()
    service = AudioAnalysisService()
    descriptor = next(item for item in service.registry.descriptors() if item.name == "librosa_mir")
    if not descriptor.available:
        pytest.skip(descriptor.unavailable_reason or "librosa unavailable")
    source = tmp_path / "pulses.wav"
    _write_pcm16(source, _pulse_train())
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.MIR_ONSETS}),
        max_cost=AnalysisCost.MODERATE,
    )

    onsets = service.analyze(source, request).measurements[AnalysisCapability.MIR_ONSETS.value]

    assert onsets["onset_count"] >= 3
    assert len(onsets["onset_times_seconds"]) == onsets["onset_count"]
    assert onsets["tempo_bpm_evidence"] is not None


def test_exact_content_and_config_reuse_cache(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "tone.wav"
    _write_pcm16(source, _sine(440, 0.05))
    cache = tmp_path / "cache"
    request = AnalysisRequest(capabilities=frozenset({AnalysisCapability.LEVELS}))
    service = AudioAnalysisService()

    first = service.analyze(source, request, cache_dir=cache)
    second = service.analyze(source, request, cache_dir=cache)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.analysis_key == second.analysis_key
    assert first.measurements == second.measurements


def test_caller_supplied_capture_hash_avoids_hash_requirement(tmp_path: Path) -> None:
    _require_ffmpeg()
    source = tmp_path / "tone.wav"
    _write_pcm16(source, _sine(440, 0.02))
    supplied = "ab" * 32

    report = AudioAnalysisService().analyze(
        source,
        AnalysisRequest(capabilities=frozenset({AnalysisCapability.LEVELS})),
        content_sha256=supplied,
    )

    assert report.content_sha256 == supplied
    assert report.analysis_key is not None


def test_request_rejects_invalid_ranges_and_fft_sizes() -> None:
    with pytest.raises(ValueError, match="greater"):
        AnalysisRequest(start_seconds=2.0, end_seconds=1.0)
    with pytest.raises(ValueError, match="power of two"):
        AnalysisRequest(spectral_window_size=1000)
