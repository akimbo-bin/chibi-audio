from __future__ import annotations

import math
from typing import Any

from .models import AnalysisCapability


SPECTRAL_OVERLAP_SCHEMA_VERSION = "chibi-audio-capture-spectral-overlap/v1"
SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION = "chibi-audio-capture-spectral-overlap-timeline/v1"


class CaptureSpectralOverlapError(ValueError):
    pass


def _finite_nonnegative(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureSpectralOverlapError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CaptureSpectralOverlapError(f"{field} must be finite and non-negative")
    return result


def _finite_time(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureSpectralOverlapError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CaptureSpectralOverlapError(f"{field} must be finite and non-negative")
    return result


def _analysis_measurements(tap: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    try:
        tap_id = int(tap.get("tap_id"))
    except (TypeError, ValueError) as exc:
        raise CaptureSpectralOverlapError("capture-analysis tap_id must be an integer") from exc
    source_label = str(tap.get("source_label") or "")
    analysis = tap.get("analysis")
    if not isinstance(analysis, dict):
        raise CaptureSpectralOverlapError(f"tap {tap_id} has no analysis report")
    measurements = analysis.get("measurements")
    if not isinstance(measurements, dict):
        raise CaptureSpectralOverlapError(f"tap {tap_id} analysis has no measurements")
    return tap_id, source_label, measurements


def _spectrum_for_tap(tap: dict[str, Any]) -> tuple[int, str, dict[str, float], float | None]:
    tap_id, source_label, measurements = _analysis_measurements(tap)
    spectrum = measurements.get(AnalysisCapability.SPECTRUM.value)
    if not isinstance(spectrum, dict):
        raise CaptureSpectralOverlapError(
            f"tap {tap_id} analysis does not contain {AnalysisCapability.SPECTRUM.value}"
        )
    raw_bands = spectrum.get("band_energy_fraction")
    if not isinstance(raw_bands, dict) or not raw_bands:
        raise CaptureSpectralOverlapError(f"tap {tap_id} spectrum has no band_energy_fraction")
    bands = {
        str(name): _finite_nonnegative(value, field=f"tap {tap_id} band {name!r}")
        for name, value in raw_bands.items()
    }

    rms_dbfs = None
    levels = measurements.get(AnalysisCapability.LEVELS.value)
    if isinstance(levels, dict):
        candidate = levels.get("rms_dbfs")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            candidate = float(candidate)
            if math.isfinite(candidate):
                rms_dbfs = candidate
    return tap_id, source_label, bands, rms_dbfs


def _spectral_timeline_for_tap(
    tap: dict[str, Any],
) -> tuple[int, str, list[tuple[float, dict[str, float]]]]:
    tap_id, source_label, measurements = _analysis_measurements(tap)
    spectrum = measurements.get(AnalysisCapability.SPECTRAL_TIMELINE.value)
    if not isinstance(spectrum, dict):
        raise CaptureSpectralOverlapError(
            f"tap {tap_id} analysis does not contain {AnalysisCapability.SPECTRAL_TIMELINE.value}"
        )
    timeline = spectrum.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise CaptureSpectralOverlapError(f"tap {tap_id} spectral timeline is empty or invalid")

    parsed: list[tuple[float, dict[str, float]]] = []
    previous = -1.0
    for index, row in enumerate(timeline):
        if not isinstance(row, dict):
            raise CaptureSpectralOverlapError(f"tap {tap_id} timeline row {index} must be an object")
        time_seconds = _finite_time(
            row.get("time_seconds"),
            field=f"tap {tap_id} timeline row {index} time_seconds",
        )
        if time_seconds < previous:
            raise CaptureSpectralOverlapError(f"tap {tap_id} spectral timeline must be time-sorted")
        previous = time_seconds
        raw_bands = row.get("band_energy_fraction")
        if not isinstance(raw_bands, dict) or not raw_bands:
            raise CaptureSpectralOverlapError(
                f"tap {tap_id} timeline row {index} has no band_energy_fraction"
            )
        bands = {
            str(name): _finite_nonnegative(
                value,
                field=f"tap {tap_id} timeline row {index} band {name!r}",
            )
            for name, value in raw_bands.items()
        }
        parsed.append((time_seconds, bands))
    return tap_id, source_label, parsed


def _normalized_common(
    left: dict[str, float],
    right: dict[str, float],
) -> tuple[list[str], dict[str, float], dict[str, float]]:
    names = sorted(set(left) & set(right))
    if not names:
        return [], {}, {}
    left_total = sum(left[name] for name in names)
    right_total = sum(right[name] for name in names)
    if left_total <= 0.0 or right_total <= 0.0:
        return names, {}, {}
    return (
        names,
        {name: left[name] / left_total for name in names},
        {name: right[name] / right_total for name in names},
    )


def _overlap_evidence(
    left: dict[str, float],
    right: dict[str, float],
    *,
    dominant_band_limit: int,
) -> tuple[list[str], float | None, float | None, list[dict[str, Any]]]:
    names, left_norm, right_norm = _normalized_common(left, right)
    if not left_norm or not right_norm:
        return names, None, None, []
    overlap_by_band = {name: min(left_norm[name], right_norm[name]) for name in names}
    overlap = sum(overlap_by_band.values())
    dot = sum(left_norm[name] * right_norm[name] for name in names)
    left_length = math.sqrt(sum(left_norm[name] ** 2 for name in names))
    right_length = math.sqrt(sum(right_norm[name] ** 2 for name in names))
    cosine = dot / (left_length * right_length) if left_length > 0 and right_length > 0 else None
    dominant = [
        {
            "band": name,
            "overlap_fraction": overlap_by_band[name],
            "left_fraction_normalized": left_norm[name],
            "right_fraction_normalized": right_norm[name],
        }
        for name in sorted(
            names,
            key=lambda candidate: overlap_by_band[candidate],
            reverse=True,
        )[:dominant_band_limit]
        if overlap_by_band[name] > 0.0
    ]
    return names, overlap, cosine, dominant


def _validate_capture(capture_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    if capture_analysis.get("schema_version") != "chibi-audio-capture-analysis/v1":
        raise CaptureSpectralOverlapError(
            f"unsupported capture-analysis schema: {capture_analysis.get('schema_version')!r}"
        )
    taps = capture_analysis.get("taps")
    if not isinstance(taps, list) or len(taps) < 2:
        raise CaptureSpectralOverlapError("capture analysis requires at least two taps")
    if not all(isinstance(value, dict) for value in taps):
        raise CaptureSpectralOverlapError("capture-analysis tap entry must be an object")
    return taps


def _validate_dominant_band_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureSpectralOverlapError("dominant_band_limit must be an integer")
    if not 1 <= value <= 16:
        raise CaptureSpectralOverlapError("dominant_band_limit must be between 1 and 16")
    return value


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _match_timeline_windows(
    left: list[tuple[float, dict[str, float]]],
    right: list[tuple[float, dict[str, float]]],
    *,
    tolerance_seconds: float,
) -> list[tuple[tuple[float, dict[str, float]], tuple[float, dict[str, float]]]]:
    """Greedy monotonic one-to-one nearest matching within a bounded tolerance."""

    matches = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_time = left[left_index][0]
        while (
            right_index + 1 < len(right)
            and abs(right[right_index + 1][0] - left_time)
            < abs(right[right_index][0] - left_time)
        ):
            right_index += 1

        right_time = right[right_index][0]
        delta = right_time - left_time
        if abs(delta) <= tolerance_seconds:
            matches.append((left[left_index], right[right_index]))
            left_index += 1
            right_index += 1
        elif left_time < right_time:
            left_index += 1
        else:
            right_index += 1
    return matches


def compare_capture_spectral_overlap(
    capture_analysis: dict[str, Any],
    *,
    dominant_band_limit: int = 4,
) -> dict[str, Any]:
    """Compare broad-band spectral occupancy between already-analyzed capture taps."""

    taps = _validate_capture(capture_analysis)
    dominant_band_limit = _validate_dominant_band_limit(dominant_band_limit)

    parsed = []
    seen: set[int] = set()
    for raw in taps:
        item = _spectrum_for_tap(raw)
        if item[0] in seen:
            raise CaptureSpectralOverlapError(f"duplicate tap_id in capture analysis: {item[0]}")
        seen.add(item[0])
        parsed.append(item)

    pairs: list[dict[str, Any]] = []
    for left_index in range(len(parsed)):
        for right_index in range(left_index + 1, len(parsed)):
            left_id, left_label, left_bands, left_rms = parsed[left_index]
            right_id, right_label, right_bands, right_rms = parsed[right_index]
            names, overlap, cosine, dominant = _overlap_evidence(
                left_bands,
                right_bands,
                dominant_band_limit=dominant_band_limit,
            )
            rms_difference = (
                right_rms - left_rms if left_rms is not None and right_rms is not None else None
            )
            pairs.append(
                {
                    "left": {"tap_id": left_id, "source_label": left_label, "rms_dbfs": left_rms},
                    "right": {"tap_id": right_id, "source_label": right_label, "rms_dbfs": right_rms},
                    "common_bands": names,
                    "spectral_overlap_coefficient": overlap,
                    "spectral_cosine_similarity": cosine,
                    "right_minus_left_rms_db": rms_difference,
                    "dominant_overlapping_bands": dominant,
                }
            )

    pairs.sort(
        key=lambda item: (
            item["spectral_overlap_coefficient"] is not None,
            item["spectral_overlap_coefficient"] or -1.0,
        ),
        reverse=True,
    )
    return {
        "schema_version": SPECTRAL_OVERLAP_SCHEMA_VERSION,
        "capture_manifest": capture_analysis.get("capture_manifest"),
        "experiment_id": capture_analysis.get("experiment_id"),
        "tap_count": len(parsed),
        "pair_count": len(pairs),
        "pairs": pairs,
        "interpretation_note": (
            "broad-band spectral overlap is occupancy evidence, not proof of audible masking; "
            "relative level, timing, phase, harmonics, arrangement and auditory context also matter"
        ),
    }


def compare_capture_spectral_overlap_timeline(
    capture_analysis: dict[str, Any],
    *,
    time_tolerance_seconds: float = 0.05,
    dominant_band_limit: int = 4,
    max_moments_per_pair: int = 5,
) -> dict[str, Any]:
    """Compare time-localized broad-band occupancy across aligned capture taps.

    Timelines are matched monotonically one-to-one, so a sampled window cannot be
    reused to create multiple overlap moments. This performs no DSP and never
    reopens audio.
    """

    taps = _validate_capture(capture_analysis)
    dominant_band_limit = _validate_dominant_band_limit(dominant_band_limit)
    if isinstance(time_tolerance_seconds, bool) or not isinstance(
        time_tolerance_seconds, (int, float)
    ):
        raise CaptureSpectralOverlapError("time_tolerance_seconds must be numeric")
    tolerance = float(time_tolerance_seconds)
    if not math.isfinite(tolerance) or tolerance < 0.0 or tolerance > 5.0:
        raise CaptureSpectralOverlapError(
            "time_tolerance_seconds must be finite and between 0 and 5"
        )
    if isinstance(max_moments_per_pair, bool) or not isinstance(max_moments_per_pair, int):
        raise CaptureSpectralOverlapError("max_moments_per_pair must be an integer")
    if not 1 <= max_moments_per_pair <= 16:
        raise CaptureSpectralOverlapError("max_moments_per_pair must be between 1 and 16")

    parsed = []
    seen: set[int] = set()
    for raw in taps:
        item = _spectral_timeline_for_tap(raw)
        if item[0] in seen:
            raise CaptureSpectralOverlapError(f"duplicate tap_id in capture analysis: {item[0]}")
        seen.add(item[0])
        parsed.append(item)

    pairs: list[dict[str, Any]] = []
    for left_index in range(len(parsed)):
        for right_index in range(left_index + 1, len(parsed)):
            left_id, left_label, left_timeline = parsed[left_index]
            right_id, right_label, right_timeline = parsed[right_index]
            matches = _match_timeline_windows(
                left_timeline,
                right_timeline,
                tolerance_seconds=tolerance,
            )
            moments: list[dict[str, Any]] = []
            overlap_values: list[float] = []
            cosine_values: list[float] = []
            for (left_time, left_bands), (right_time, right_bands) in matches:
                names, overlap, cosine, dominant = _overlap_evidence(
                    left_bands,
                    right_bands,
                    dominant_band_limit=dominant_band_limit,
                )
                if overlap is not None:
                    overlap_values.append(overlap)
                if cosine is not None:
                    cosine_values.append(cosine)
                moments.append(
                    {
                        "time_seconds": (left_time + right_time) * 0.5,
                        "left_time_seconds": left_time,
                        "right_time_seconds": right_time,
                        "right_minus_left_time_seconds": right_time - left_time,
                        "common_bands": names,
                        "spectral_overlap_coefficient": overlap,
                        "spectral_cosine_similarity": cosine,
                        "dominant_overlapping_bands": dominant,
                    }
                )

            strongest = sorted(
                (value for value in moments if value["spectral_overlap_coefficient"] is not None),
                key=lambda value: value["spectral_overlap_coefficient"],
                reverse=True,
            )[:max_moments_per_pair]
            pairs.append(
                {
                    "left": {"tap_id": left_id, "source_label": left_label},
                    "right": {"tap_id": right_id, "source_label": right_label},
                    "left_window_count": len(left_timeline),
                    "right_window_count": len(right_timeline),
                    "matched_window_count": len(matches),
                    "unmatched_left_window_count": len(left_timeline) - len(matches),
                    "unmatched_right_window_count": len(right_timeline) - len(matches),
                    "overlap_coefficient": {
                        "p10": _percentile(overlap_values, 0.10),
                        "median": _percentile(overlap_values, 0.50),
                        "p90": _percentile(overlap_values, 0.90),
                    },
                    "cosine_similarity": {
                        "p10": _percentile(cosine_values, 0.10),
                        "median": _percentile(cosine_values, 0.50),
                        "p90": _percentile(cosine_values, 0.90),
                    },
                    "strongest_overlap_moments": strongest,
                }
            )

    pairs.sort(
        key=lambda item: (
            item["overlap_coefficient"]["median"] is not None,
            item["overlap_coefficient"]["median"] or -1.0,
            item["overlap_coefficient"]["p90"] or -1.0,
        ),
        reverse=True,
    )
    return {
        "schema_version": SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION,
        "capture_manifest": capture_analysis.get("capture_manifest"),
        "experiment_id": capture_analysis.get("experiment_id"),
        "tap_count": len(parsed),
        "pair_count": len(pairs),
        "time_tolerance_seconds": tolerance,
        "max_moments_per_pair": max_moments_per_pair,
        "pairs": pairs,
        "interpretation_note": (
            "time-localized broad-band overlap is sampled occupancy evidence, not proof of audible masking; "
            "the one-to-one matching prevents a sampled window from being reused across multiple moments"
        ),
    }
