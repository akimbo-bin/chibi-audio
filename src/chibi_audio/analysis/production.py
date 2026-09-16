from __future__ import annotations

import math
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


PRODUCTION_VERSION = "0.1.0"


def _db(value: float) -> float | None:
    if value <= 0.0:
        return None
    return 20.0 * math.log10(value)


def _range(context: AnalysisContext) -> dict[str, float]:
    start = context.absolute_start_seconds
    duration = context.decoded_duration_seconds
    return {
        "start_seconds": start,
        "end_seconds": start + duration,
        "duration_seconds": duration,
    }


def _window_starts(frame_count: int, window_size: int, max_windows: int, np) -> list[int]:
    if frame_count <= window_size:
        return [0]
    count = min(max_windows, max(1, math.ceil(frame_count / window_size)))
    max_start = frame_count - window_size
    return [int(round(value)) for value in np.linspace(0, max_start, count)]


def _padded_segment(audio, start: int, length: int, np):
    segment = audio[start : start + length]
    if len(segment) == length:
        return segment
    padded = np.zeros((length, audio.shape[1]), dtype=np.float64)
    padded[: len(segment)] = segment
    return padded


class TransientEnvelopeAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_transient_envelope",
        version=PRODUCTION_VERSION,
        capabilities=frozenset({AnalysisCapability.TRANSIENTS}),
        cost=AnalysisCost.CHEAP,
        implementation="frame-RMS envelope / strongest-event attack-decay evidence",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        mono = np.mean(audio, axis=1)
        sr = context.request.sample_rate
        frame_size = min(1024, max(64, len(mono)))
        hop_size = min(256, frame_size)

        if len(mono) <= frame_size:
            starts = [0]
        else:
            starts = list(range(0, len(mono) - frame_size + 1, hop_size))
            final = len(mono) - frame_size
            if starts[-1] != final:
                starts.append(final)

        frame_rms = np.asarray(
            [
                math.sqrt(float(np.mean(mono[start : start + frame_size] ** 2)))
                for start in starts
            ],
            dtype=np.float64,
        )
        peak_index = int(np.argmax(frame_rms))
        peak_rms = float(frame_rms[peak_index])
        median_rms = float(np.median(frame_rms))
        p95_rms = float(np.percentile(frame_rms, 95))
        p10_rms = float(np.percentile(frame_rms, 10))

        attack_ms = None
        decay_ms = None
        if peak_rms > 0.0 and len(frame_rms) > 1:
            ten = peak_rms * 0.10
            ninety = peak_rms * 0.90
            before = frame_rms[: peak_index + 1]
            low_candidates = np.flatnonzero(before <= ten)
            high_candidates = np.flatnonzero(before >= ninety)
            if low_candidates.size and high_candidates.size:
                low_index = int(low_candidates[-1])
                high_after_low = high_candidates[high_candidates >= low_index]
                if high_after_low.size:
                    high_index = int(high_after_low[0])
                    attack_ms = max(0.0, (starts[high_index] - starts[low_index]) * 1000.0 / sr)

            decay_target = peak_rms * (10.0 ** (-12.0 / 20.0))
            after = frame_rms[peak_index:]
            decay_candidates = np.flatnonzero(after <= decay_target)
            if decay_candidates.size:
                decay_index = peak_index + int(decay_candidates[0])
                decay_ms = max(0.0, (starts[decay_index] - starts[peak_index]) * 1000.0 / sr)

        differences = np.diff(frame_rms, prepend=frame_rms[0])
        positive = differences[differences > 0.0]
        transient_count = 0
        if positive.size:
            threshold = float(np.percentile(positive, 90))
            for index in range(1, len(differences) - 1):
                if (
                    differences[index] >= threshold
                    and differences[index] > differences[index - 1]
                    and differences[index] >= differences[index + 1]
                ):
                    transient_count += 1

        strongest_time = (
            context.absolute_start_seconds
            + (starts[peak_index] + frame_size * 0.5) / float(sr)
        )
        duration = max(context.decoded_duration_seconds, 1e-12)
        transient_to_body_db = (
            _db(peak_rms / median_rms) if peak_rms > 0.0 and median_rms > 0.0 else None
        )
        microdynamic_range_db = (
            _db(p95_rms / p10_rms) if p95_rms > 0.0 and p10_rms > 0.0 else None
        )

        return {
            AnalysisCapability.TRANSIENTS.value: {
                "strongest_event_time_seconds": strongest_time,
                "strongest_frame_rms_dbfs": _db(peak_rms),
                "median_frame_rms_dbfs": _db(median_rms),
                "transient_to_body_db": transient_to_body_db,
                "microdynamic_p95_to_p10_db": microdynamic_range_db,
                "strongest_event_attack_10_to_90_ms": attack_ms,
                "strongest_event_decay_to_minus_12db_ms": decay_ms,
                "strong_rise_count": transient_count,
                "strong_rise_density_per_second": transient_count / duration,
                "frame_size_samples": frame_size,
                "hop_size_samples": hop_size,
                "interpretation_note": (
                    "attack/decay describe the strongest frame-RMS event in the requested range; "
                    "they are evidence, not a judgement of punch or quality"
                ),
                "range": _range(context),
            }
        }


class ProductionSpectrumAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_production_spectrum",
        version=PRODUCTION_VERSION,
        capabilities=frozenset(
            {AnalysisCapability.TEXTURE, AnalysisCapability.STEREO_BANDS}
        ),
        cost=AnalysisCost.MODERATE,
        implementation="bounded channel FFT texture and frequency-dependent M/S evidence",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    bands = (
        ("sub", 20.0, 80.0),
        ("low", 80.0, 250.0),
        ("low_mid", 250.0, 500.0),
        ("mid", 500.0, 2000.0),
        ("high_mid", 2000.0, 6000.0),
        ("high", 6000.0, 12000.0),
        ("air", 12000.0, 20000.0),
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        requested = context.request.capabilities
        sr = context.request.sample_rate
        n = context.request.spectral_window_size
        starts = _window_starts(len(audio), n, context.request.spectral_max_windows, np)
        window = np.hanning(n)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        epsilon = 1e-20

        texture_power = np.zeros(len(freqs), dtype=np.float64)
        flatness_values: list[float] = []
        flux_values: list[float] = []
        previous_magnitude = None

        band_accumulator = {
            name: {
                "left": 0.0,
                "right": 0.0,
                "cross": 0.0,
                "mid": 0.0,
                "side": 0.0,
                "bins": 0,
            }
            for name, _, _ in self.bands
        }

        for start in starts:
            segment = _padded_segment(audio, start, n, np)
            spectrum = np.fft.rfft(segment * window[:, None], axis=0)
            power = np.abs(spectrum) ** 2
            channel_power = np.mean(power, axis=1)
            texture_power += channel_power

            positive_power = channel_power[1:]
            if positive_power.size and float(np.mean(positive_power)) > 0.0:
                flatness_values.append(
                    float(
                        np.exp(np.mean(np.log(positive_power + epsilon)))
                        / (np.mean(positive_power) + epsilon)
                    )
                )

            magnitude = np.sqrt(channel_power)
            norm = float(np.linalg.norm(magnitude))
            normalized = magnitude / norm if norm > 0.0 else magnitude
            if previous_magnitude is not None:
                flux_values.append(float(np.linalg.norm(np.maximum(normalized - previous_magnitude, 0.0))))
            previous_magnitude = normalized

            if int(context.probe["channels"]) == 2:
                left = spectrum[:, 0]
                right = spectrum[:, 1]
                mid = (left + right) * 0.5
                side = (left - right) * 0.5
                for name, low, high in self.bands:
                    upper = min(high, sr / 2.0)
                    mask = (freqs >= low) & (freqs < upper)
                    if not np.any(mask):
                        continue
                    values = band_accumulator[name]
                    values["left"] += float(np.sum(np.abs(left[mask]) ** 2))
                    values["right"] += float(np.sum(np.abs(right[mask]) ** 2))
                    values["cross"] += float(np.sum(np.real(left[mask] * np.conj(right[mask]))))
                    values["mid"] += float(np.sum(np.abs(mid[mask]) ** 2))
                    values["side"] += float(np.sum(np.abs(side[mask]) ** 2))
                    values["bins"] += int(np.count_nonzero(mask))

        result: dict[str, Any] = {}
        total_power = float(np.sum(texture_power))

        if AnalysisCapability.TEXTURE in requested:
            mono = np.mean(audio, axis=1)
            if len(mono) > 1:
                signs = np.signbit(mono)
                zcr = float(np.mean(signs[1:] != signs[:-1]))
            else:
                zcr = 0.0
            bright_mask = freqs >= 4000.0
            very_high_mask = freqs >= 8000.0
            result[AnalysisCapability.TEXTURE.value] = {
                "spectral_flatness_mean": (
                    float(np.mean(flatness_values)) if flatness_values else None
                ),
                "spectral_flux_mean": float(np.mean(flux_values)) if flux_values else 0.0,
                "zero_crossing_fraction": zcr,
                "energy_above_4khz_fraction": (
                    float(np.sum(texture_power[bright_mask]) / total_power)
                    if total_power > 0.0
                    else 0.0
                ),
                "energy_above_8khz_fraction": (
                    float(np.sum(texture_power[very_high_mask]) / total_power)
                    if total_power > 0.0
                    else 0.0
                ),
                "sampled_windows": len(starts),
                "window_size": n,
                "interpretation_note": (
                    "flatness/flux/zero-crossing/brightness are signal descriptors; "
                    "they do not imply harshness, clarity, or quality on their own"
                ),
                "range": _range(context),
            }

        if AnalysisCapability.STEREO_BANDS in requested:
            source_channels = int(context.probe["channels"])
            if source_channels != 2:
                result[AnalysisCapability.STEREO_BANDS.value] = {
                    "available": False,
                    "source_channels": source_channels,
                    "reason": "frequency-dependent stereo evidence requires an original two-channel source",
                    "range": _range(context),
                }
            else:
                bands: dict[str, Any] = {}
                for name, low, high in self.bands:
                    values = band_accumulator[name]
                    left_power = values["left"]
                    right_power = values["right"]
                    denominator = math.sqrt(left_power * right_power)
                    correlation = values["cross"] / denominator if denominator > 0.0 else None
                    if correlation is not None:
                        correlation = max(-1.0, min(1.0, correlation))
                    ms_total = values["mid"] + values["side"]
                    bands[name] = {
                        "low_hz": low,
                        "high_hz": min(high, sr / 2.0),
                        "correlation_evidence": correlation,
                        "side_energy_fraction": (
                            values["side"] / ms_total if ms_total > 0.0 else None
                        ),
                        "side_to_mid_db": (
                            10.0 * math.log10(values["side"] / values["mid"])
                            if values["side"] > 0.0 and values["mid"] > 0.0
                            else None
                        ),
                        "sampled_bins": values["bins"],
                    }
                result[AnalysisCapability.STEREO_BANDS.value] = {
                    "available": True,
                    "source_channels": source_channels,
                    "bands": bands,
                    "method": "windowed complex cross-power and mid/side energy by frequency band",
                    "interpretation_note": (
                        "band correlation and side energy are diagnostic evidence for mono compatibility/width; "
                        "they are not automatic instructions to narrow a mix"
                    ),
                    "range": _range(context),
                }

        return result


def production_analyzers():
    return TransientEnvelopeAnalyzer(), ProductionSpectrumAnalyzer()
