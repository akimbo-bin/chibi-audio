from __future__ import annotations

import math
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


CORE_VERSION = "0.1.0"


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


class MetadataAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="ffprobe_metadata",
        version=CORE_VERSION,
        capabilities=frozenset({AnalysisCapability.METADATA}),
        cost=AnalysisCost.CHEAP,
        implementation="ffprobe stream metadata",
        upstream="FFmpeg/FFprobe",
        license="LGPL/GPL build-dependent",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        value = dict(context.probe)
        value.pop("path", None)
        return {AnalysisCapability.METADATA.value: value}


class SignalAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_signal",
        version=CORE_VERSION,
        capabilities=frozenset(
            {
                AnalysisCapability.LEVELS,
                AnalysisCapability.ACTIVITY,
                AnalysisCapability.STEREO,
            }
        ),
        cost=AnalysisCost.CHEAP,
        implementation="single decoded NumPy pass",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        requested = context.request.capabilities
        result: dict[str, Any] = {}
        range_payload = _range(context)

        if AnalysisCapability.LEVELS in requested:
            absolute = np.abs(audio)
            per_channel_peak = np.max(absolute, axis=0)
            per_channel_rms = np.sqrt(np.mean(audio * audio, axis=0))
            peak = float(np.max(per_channel_peak))
            rms = float(np.sqrt(np.mean(audio * audio)))
            crest = _db(peak / rms) if peak > 0 and rms > 0 else None
            sample_over_count = int(np.count_nonzero(absolute >= 1.0))
            result[AnalysisCapability.LEVELS.value] = {
                "sample_peak": peak,
                "sample_peak_dbfs": _db(peak),
                "rms": rms,
                "rms_dbfs": _db(rms),
                "crest_factor_db": crest,
                "sample_over_count": sample_over_count,
                "sample_over_fraction": sample_over_count / float(audio.size),
                "true_peak_dbtp": None,
                "true_peak_status": "not_computed_by_signal_analyzer",
                "per_channel": [
                    {
                        "channel_index": index,
                        "sample_peak": float(per_channel_peak[index]),
                        "sample_peak_dbfs": _db(float(per_channel_peak[index])),
                        "rms": float(per_channel_rms[index]),
                        "rms_dbfs": _db(float(per_channel_rms[index])),
                    }
                    for index in range(audio.shape[1])
                ],
                "range": range_payload,
            }

        if AnalysisCapability.ACTIVITY in requested:
            threshold = 10.0 ** (context.request.silence_threshold_dbfs / 20.0)
            active = np.max(np.abs(audio), axis=1) >= threshold
            indices = np.flatnonzero(active)
            if indices.size:
                first = context.absolute_start_seconds + float(indices[0]) / context.request.sample_rate
                last = context.absolute_start_seconds + float(indices[-1]) / context.request.sample_rate
            else:
                first = last = None
            result[AnalysisCapability.ACTIVITY.value] = {
                "threshold_dbfs": context.request.silence_threshold_dbfs,
                "active_frame_fraction": float(np.mean(active)),
                "active_frames": int(np.count_nonzero(active)),
                "first_active_seconds": first,
                "last_active_seconds": last,
                "range": range_payload,
            }

        if AnalysisCapability.STEREO in requested:
            source_channels = int(context.probe["channels"])
            if source_channels != 2:
                result[AnalysisCapability.STEREO.value] = {
                    "available": False,
                    "source_channels": source_channels,
                    "reason": "stereo correlation/M-S evidence requires an original two-channel source",
                    "range": range_payload,
                }
            else:
                left = audio[:, 0]
                right = audio[:, 1]
                left_std = float(np.std(left))
                right_std = float(np.std(right))
                correlation = (
                    float(np.corrcoef(left, right)[0, 1])
                    if left_std > 0.0 and right_std > 0.0
                    else None
                )
                mid = (left + right) * 0.5
                side = (left - right) * 0.5
                mid_energy = float(np.mean(mid * mid))
                side_energy = float(np.mean(side * side))
                total = mid_energy + side_energy
                mid_rms = math.sqrt(mid_energy)
                side_rms = math.sqrt(side_energy)
                result[AnalysisCapability.STEREO.value] = {
                    "available": True,
                    "source_channels": source_channels,
                    "correlation": correlation,
                    "mid_rms": mid_rms,
                    "side_rms": side_rms,
                    "side_energy_fraction": side_energy / total if total > 0.0 else None,
                    "side_to_mid_db": (
                        20.0 * math.log10(side_rms / mid_rms)
                        if side_rms > 0.0 and mid_rms > 0.0
                        else None
                    ),
                    "range": range_payload,
                }

        return result


class SpectrumAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_spectrum",
        version=CORE_VERSION,
        capabilities=frozenset({AnalysisCapability.SPECTRUM}),
        cost=AnalysisCost.MODERATE,
        implementation="bounded Hann-window channel-power FFT",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    bands = (
        ("sub", 20.0, 60.0),
        ("bass", 60.0, 250.0),
        ("low_mid", 250.0, 500.0),
        ("mid", 500.0, 2000.0),
        ("high_mid", 2000.0, 6000.0),
        ("presence", 6000.0, 12000.0),
        ("air", 12000.0, 20000.0),
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        n = context.request.spectral_window_size
        frame_count = len(audio)
        if frame_count <= n:
            starts = [0]
        else:
            count = min(
                context.request.spectral_max_windows,
                max(1, math.ceil(frame_count / n)),
            )
            max_start = frame_count - n
            starts = [int(round(value)) for value in np.linspace(0, max_start, count)]

        aggregate = np.zeros(n // 2 + 1, dtype=np.float64)
        window = np.hanning(n)
        for start in starts:
            segment = audio[start : start + n]
            if len(segment) < n:
                padded = np.zeros((n, audio.shape[1]), dtype=np.float64)
                padded[: len(segment)] = segment
                segment = padded
            spectrum = np.fft.rfft(segment * window[:, None], axis=0)
            aggregate += np.mean(np.abs(spectrum) ** 2, axis=1)

        freqs = np.fft.rfftfreq(n, d=1.0 / context.request.sample_rate)
        total = float(np.sum(aggregate))
        if total <= 0.0:
            centroid = rolloff = None
            band_fraction = {name: 0.0 for name, _, _ in self.bands}
        else:
            centroid = float(np.sum(freqs * aggregate) / total)
            cumulative = np.cumsum(aggregate)
            index = int(np.searchsorted(cumulative, total * context.request.spectral_rolloff_fraction))
            index = min(index, len(freqs) - 1)
            rolloff = float(freqs[index])
            band_fraction = {}
            for name, low, high in self.bands:
                mask = (freqs >= low) & (freqs < min(high, context.request.sample_rate / 2.0))
                band_fraction[name] = float(np.sum(aggregate[mask]) / total)

        return {
            AnalysisCapability.SPECTRUM.value: {
                "spectral_centroid_hz": centroid,
                "rolloff_hz": rolloff,
                "rolloff_fraction": context.request.spectral_rolloff_fraction,
                "band_energy_fraction": band_fraction,
                "sampled_windows": len(starts),
                "window_size": n,
                "method": "channel_power_average_before_band_summary",
                "range": _range(context),
            }
        }


def default_core_analyzers():
    return MetadataAnalyzer(), SignalAnalyzer(), SpectrumAnalyzer()
