from __future__ import annotations

import math
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


TIMELINE_VERSION = "0.1.0"

_BANDS = (
    ("sub", 20.0, 80.0),
    ("low", 80.0, 250.0),
    ("low_mid", 250.0, 500.0),
    ("mid", 500.0, 2000.0),
    ("high_mid", 2000.0, 6000.0),
    ("high", 6000.0, 12000.0),
    ("air", 12000.0, 20000.0),
)


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


def _even_indices(count: int, maximum: int, np) -> list[int]:
    if count <= maximum:
        return list(range(count))
    return sorted({int(round(value)) for value in np.linspace(0, count - 1, maximum)})


def _even_starts(frame_count: int, window_size: int, maximum: int, np) -> list[int]:
    if frame_count <= window_size:
        return [0]
    count = min(maximum, max(2, math.ceil(frame_count / window_size)))
    last = frame_count - window_size
    return sorted({int(round(value)) for value in np.linspace(0, last, count)})


def _padded_segment(audio, start: int, length: int, np):
    segment = audio[start : start + length]
    if len(segment) == length:
        return segment
    padded = np.zeros((length, audio.shape[1]), dtype=np.float64)
    padded[: len(segment)] = segment
    return padded


class DynamicsTimelineAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_dynamics_timeline",
        version=TIMELINE_VERSION,
        capabilities=frozenset({AnalysisCapability.DYNAMICS}),
        cost=AnalysisCost.CHEAP,
        implementation="bounded 400 ms channel-power RMS dynamics timeline",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        sr = context.request.sample_rate
        frame_size = min(len(audio), max(64, round(0.4 * sr)))
        hop_size = max(1, frame_size // 2)

        if len(audio) <= frame_size:
            starts = [0]
        else:
            starts = list(range(0, len(audio) - frame_size + 1, hop_size))
            final = len(audio) - frame_size
            if starts[-1] != final:
                starts.append(final)

        rms_values = []
        for start in starts:
            segment = audio[start : start + frame_size]
            channel_power = np.mean(segment * segment, axis=1)
            rms_values.append(math.sqrt(float(np.mean(channel_power))))
        rms = np.asarray(rms_values, dtype=np.float64)

        threshold = 10.0 ** (context.request.silence_threshold_dbfs / 20.0)
        active = rms >= threshold
        active_rms = rms[active]

        if active_rms.size:
            p10 = float(np.percentile(active_rms, 10))
            median = float(np.median(active_rms))
            p90 = float(np.percentile(active_rms, 90))
            macro_range = 20.0 * math.log10(p90 / p10) if p10 > 0.0 and p90 > 0.0 else None
        else:
            p10 = median = p90 = 0.0
            macro_range = None

        loudest_index = int(np.argmax(rms))
        active_indices = np.flatnonzero(active)
        quietest_index = (
            int(active_indices[np.argmin(rms[active_indices])]) if active_indices.size else None
        )

        split = max(1, len(rms) // 2)
        first = rms[:split]
        second = rms[split:] if split < len(rms) else rms[:split]
        first_active = first[first >= threshold]
        second_active = second[second >= threshold]
        first_median = float(np.median(first_active)) if first_active.size else 0.0
        second_median = float(np.median(second_active)) if second_active.size else 0.0
        first_db = _db(first_median)
        second_db = _db(second_median)
        second_minus_first = (
            second_db - first_db if first_db is not None and second_db is not None else None
        )

        db_values = [_db(float(value)) for value in rms]
        largest_change = None
        largest_abs = -1.0
        for index in range(1, len(db_values)):
            before = db_values[index - 1]
            after = db_values[index]
            if before is None or after is None:
                continue
            delta = after - before
            if abs(delta) > largest_abs:
                largest_abs = abs(delta)
                largest_change = {
                    "from_time_seconds": context.absolute_start_seconds
                    + (starts[index - 1] + frame_size * 0.5) / sr,
                    "to_time_seconds": context.absolute_start_seconds
                    + (starts[index] + frame_size * 0.5) / sr,
                    "rms_change_db": delta,
                }

        timeline = []
        for index in _even_indices(len(starts), context.request.timeline_max_points, np):
            timeline.append(
                {
                    "time_seconds": context.absolute_start_seconds
                    + (starts[index] + frame_size * 0.5) / sr,
                    "rms_dbfs": db_values[index],
                    "active": bool(active[index]),
                }
            )

        def _window_payload(index: int | None) -> dict[str, float | None] | None:
            if index is None:
                return None
            return {
                "time_seconds": context.absolute_start_seconds
                + (starts[index] + frame_size * 0.5) / sr,
                "rms_dbfs": db_values[index],
            }

        return {
            AnalysisCapability.DYNAMICS.value: {
                "active_window_fraction": float(np.mean(active)),
                "active_rms_p10_dbfs": _db(p10),
                "active_rms_median_dbfs": _db(median),
                "active_rms_p90_dbfs": _db(p90),
                "macro_dynamic_p90_to_p10_db": macro_range,
                "first_half_active_median_rms_dbfs": first_db,
                "second_half_active_median_rms_dbfs": second_db,
                "second_minus_first_half_db": second_minus_first,
                "loudest_window": _window_payload(loudest_index),
                "quietest_active_window": _window_payload(quietest_index),
                "largest_adjacent_rms_change": largest_change,
                "window_size_seconds": frame_size / float(sr),
                "hop_size_seconds": hop_size / float(sr),
                "timeline": timeline,
                "timeline_points": len(timeline),
                "interpretation_note": (
                    "these are channel-power RMS dynamics, not LUFS; they describe level movement "
                    "inside the requested range and do not imply a preferred amount of dynamics"
                ),
                "range": _range(context),
            }
        }


class SpectralTimelineAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_spectral_timeline",
        version=TIMELINE_VERSION,
        capabilities=frozenset({AnalysisCapability.SPECTRAL_TIMELINE}),
        cost=AnalysisCost.MODERATE,
        implementation="bounded evenly sampled channel-power FFT spectral timeline",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        sr = context.request.sample_rate
        n = context.request.spectral_window_size
        maximum = min(context.request.timeline_max_points, context.request.spectral_max_windows)
        starts = _even_starts(len(audio), n, maximum, np)
        window = np.hanning(n)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)

        rows: list[dict[str, Any]] = []
        band_series: dict[str, list[float]] = {name: [] for name, _, _ in _BANDS}
        centroids: list[float] = []

        for start in starts:
            segment = _padded_segment(audio, start, n, np)
            spectrum = np.fft.rfft(segment * window[:, None], axis=0)
            power = np.mean(np.abs(spectrum) ** 2, axis=1)
            total = float(np.sum(power))
            if total > 0.0:
                centroid = float(np.sum(freqs * power) / total)
            else:
                centroid = 0.0
            centroids.append(centroid)

            bands: dict[str, float] = {}
            for name, low, high in _BANDS:
                upper = min(high, sr / 2.0)
                mask = (freqs >= low) & (freqs < upper)
                fraction = float(np.sum(power[mask]) / total) if total > 0.0 and np.any(mask) else 0.0
                bands[name] = fraction
                band_series[name].append(fraction)

            rows.append(
                {
                    "time_seconds": context.absolute_start_seconds + (start + n * 0.5) / sr,
                    "spectral_centroid_hz": centroid if total > 0.0 else None,
                    "band_energy_fraction": bands,
                }
            )

        centroid_array = np.asarray(centroids, dtype=np.float64)
        nonzero_centroids = centroid_array[centroid_array > 0.0]
        if nonzero_centroids.size:
            centroid_summary = {
                "p10_hz": float(np.percentile(nonzero_centroids, 10)),
                "median_hz": float(np.median(nonzero_centroids)),
                "p90_hz": float(np.percentile(nonzero_centroids, 90)),
                "p90_minus_p10_hz": float(
                    np.percentile(nonzero_centroids, 90) - np.percentile(nonzero_centroids, 10)
                ),
            }
        else:
            centroid_summary = {
                "p10_hz": None,
                "median_hz": None,
                "p90_hz": None,
                "p90_minus_p10_hz": None,
            }

        band_summary: dict[str, dict[str, float]] = {}
        for name, values in band_series.items():
            array = np.asarray(values, dtype=np.float64)
            p10 = float(np.percentile(array, 10)) if array.size else 0.0
            median = float(np.median(array)) if array.size else 0.0
            p90 = float(np.percentile(array, 90)) if array.size else 0.0
            band_summary[name] = {
                "p10_fraction": p10,
                "median_fraction": median,
                "p90_fraction": p90,
                "p90_minus_p10_fraction": p90 - p10,
            }

        largest_shift = None
        largest_distance = -1.0
        ordered_names = [name for name, _, _ in _BANDS]
        for index in range(1, len(rows)):
            before = rows[index - 1]["band_energy_fraction"]
            after = rows[index]["band_energy_fraction"]
            distance = math.sqrt(
                sum((float(after[name]) - float(before[name])) ** 2 for name in ordered_names)
            )
            if distance > largest_distance:
                largest_distance = distance
                largest_shift = {
                    "from_time_seconds": rows[index - 1]["time_seconds"],
                    "to_time_seconds": rows[index]["time_seconds"],
                    "band_fraction_euclidean_distance": distance,
                }

        return {
            AnalysisCapability.SPECTRAL_TIMELINE.value: {
                "spectral_centroid": centroid_summary,
                "bands": band_summary,
                "largest_sampled_spectral_shift": largest_shift,
                "timeline": rows,
                "sampled_windows": len(rows),
                "window_size": n,
                "method": "evenly sampled Hann-window channel-power FFT summaries",
                "interpretation_note": (
                    "time-varying band balance is evidence only; it does not by itself imply harshness, "
                    "mud, brightness, or an EQ prescription"
                ),
                "range": _range(context),
            }
        }


def timeline_analyzers():
    return DynamicsTimelineAnalyzer(), SpectralTimelineAnalyzer()
