from __future__ import annotations

import math
from typing import Any

from .models import AnalysisCapability


SPECTRAL_OVERLAP_SCHEMA_VERSION = "chibi-audio-capture-spectral-overlap/v1"


class CaptureSpectralOverlapError(ValueError):
    pass


def _finite_nonnegative(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureSpectralOverlapError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CaptureSpectralOverlapError(f"{field} must be finite and non-negative")
    return result


def _spectrum_for_tap(tap: dict[str, Any]) -> tuple[int, str, dict[str, float], float | None]:
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


def compare_capture_spectral_overlap(
    capture_analysis: dict[str, Any],
    *,
    dominant_band_limit: int = 4,
) -> dict[str, Any]:
    """Compare broad-band spectral occupancy between already-analyzed capture taps.

    This performs no DSP and does not reopen audio. The overlap coefficient is the
    intersection of pair-normalized broad-band energy fractions, bounded to [0, 1].
    It describes similar occupancy, not psychoacoustic masking by itself.
    """

    if capture_analysis.get("schema_version") != "chibi-audio-capture-analysis/v1":
        raise CaptureSpectralOverlapError(
            f"unsupported capture-analysis schema: {capture_analysis.get('schema_version')!r}"
        )
    taps = capture_analysis.get("taps")
    if not isinstance(taps, list) or len(taps) < 2:
        raise CaptureSpectralOverlapError("capture analysis requires at least two taps")
    if isinstance(dominant_band_limit, bool) or not isinstance(dominant_band_limit, int):
        raise CaptureSpectralOverlapError("dominant_band_limit must be an integer")
    if not 1 <= dominant_band_limit <= 16:
        raise CaptureSpectralOverlapError("dominant_band_limit must be between 1 and 16")

    parsed = []
    seen: set[int] = set()
    for raw in taps:
        if not isinstance(raw, dict):
            raise CaptureSpectralOverlapError("capture-analysis tap entry must be an object")
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
            names, left_norm, right_norm = _normalized_common(left_bands, right_bands)
            if not left_norm or not right_norm:
                overlap = cosine = None
                dominant: list[dict[str, Any]] = []
            else:
                overlap_by_band = {
                    name: min(left_norm[name], right_norm[name]) for name in names
                }
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
