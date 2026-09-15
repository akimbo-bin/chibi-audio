from __future__ import annotations

import math
from typing import Any

from .models import AnalysisCapability, AnalysisReport


COMPARISON_SCHEMA_VERSION = "chibi-audio-analysis-comparison/v1"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    first = _number(left.get(key))
    second = _number(right.get(key))
    if first is None or second is None:
        return None
    return second - first


def _chroma_similarity(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    first = left.get("chroma_profile")
    second = right.get("chroma_profile")
    if not isinstance(first, dict) or not isinstance(second, dict):
        return None
    names = sorted(set(first) & set(second))
    if not names:
        return None
    a = [_number(first.get(name)) or 0.0 for name in names]
    b = [_number(second.get(name)) or 0.0 for name in names]
    numerator = sum(x * y for x, y in zip(a, b, strict=True))
    a_norm = math.sqrt(sum(x * x for x in a))
    b_norm = math.sqrt(sum(y * y for y in b))
    if a_norm <= 0.0 or b_norm <= 0.0:
        return None
    return numerator / (a_norm * b_norm)


def compare_reports(
    left: AnalysisReport,
    right: AnalysisReport,
    *,
    left_label: str = "left",
    right_label: str = "right",
) -> dict[str, Any]:
    """Compare already-computed evidence without invoking another analyzer.

    Deltas are always ``right - left``. The function deliberately exposes only
    measurement-to-measurement evidence; it does not label one side better/worse.
    """

    common = sorted(set(left.measurements) & set(right.measurements))
    comparisons: dict[str, Any] = {}

    levels_key = AnalysisCapability.LEVELS.value
    if levels_key in common:
        a = left.measurements[levels_key]
        b = right.measurements[levels_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[levels_key] = {
                "sample_peak_dbfs_delta": _delta(a, b, "sample_peak_dbfs"),
                "rms_dbfs_delta": _delta(a, b, "rms_dbfs"),
                "crest_factor_db_delta": _delta(a, b, "crest_factor_db"),
                "sample_over_count_delta": _delta(a, b, "sample_over_count"),
            }

    activity_key = AnalysisCapability.ACTIVITY.value
    if activity_key in common:
        a = left.measurements[activity_key]
        b = right.measurements[activity_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[activity_key] = {
                "active_frame_fraction_delta": _delta(a, b, "active_frame_fraction"),
            }

    stereo_key = AnalysisCapability.STEREO.value
    if stereo_key in common:
        a = left.measurements[stereo_key]
        b = right.measurements[stereo_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[stereo_key] = {
                "correlation_delta": _delta(a, b, "correlation"),
                "side_energy_fraction_delta": _delta(a, b, "side_energy_fraction"),
                "side_to_mid_db_delta": _delta(a, b, "side_to_mid_db"),
            }

    spectrum_key = AnalysisCapability.SPECTRUM.value
    if spectrum_key in common:
        a = left.measurements[spectrum_key]
        b = right.measurements[spectrum_key]
        if isinstance(a, dict) and isinstance(b, dict):
            first_bands = a.get("band_energy_fraction")
            second_bands = b.get("band_energy_fraction")
            band_deltas: dict[str, float | None] = {}
            if isinstance(first_bands, dict) and isinstance(second_bands, dict):
                for name in sorted(set(first_bands) & set(second_bands)):
                    first = _number(first_bands.get(name))
                    second = _number(second_bands.get(name))
                    band_deltas[name] = None if first is None or second is None else second - first
            comparisons[spectrum_key] = {
                "spectral_centroid_hz_delta": _delta(a, b, "spectral_centroid_hz"),
                "rolloff_hz_delta": _delta(a, b, "rolloff_hz"),
                "band_energy_fraction_delta": band_deltas,
            }

    loudness_key = AnalysisCapability.LOUDNESS.value
    if loudness_key in common:
        a = left.measurements[loudness_key]
        b = right.measurements[loudness_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[loudness_key] = {
                "integrated_lufs_delta": _delta(a, b, "integrated_lufs"),
                "true_peak_dbtp_delta": _delta(a, b, "true_peak_dbtp"),
                "loudness_range_lu_delta": _delta(a, b, "loudness_range_lu"),
            }

    onsets_key = AnalysisCapability.MIR_ONSETS.value
    if onsets_key in common:
        a = left.measurements[onsets_key]
        b = right.measurements[onsets_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[onsets_key] = {
                "onset_density_per_second_delta": _delta(a, b, "onset_density_per_second"),
                "tempo_bpm_evidence_delta": _delta(a, b, "tempo_bpm_evidence"),
            }

    tonal_key = AnalysisCapability.MIR_TONAL.value
    if tonal_key in common:
        a = left.measurements[tonal_key]
        b = right.measurements[tonal_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[tonal_key] = {
                "chroma_cosine_similarity": _chroma_similarity(a, b),
                "left_dominant_pitch_class_evidence": a.get("dominant_pitch_class_evidence"),
                "right_dominant_pitch_class_evidence": b.get("dominant_pitch_class_evidence"),
                "tonal_concentration_delta": _delta(a, b, "tonal_concentration"),
            }

    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "direction": "right_minus_left",
        "left": {
            "label": left_label,
            "source_name": left.source_name,
            "content_sha256": left.content_sha256,
            "analysis_key": left.analysis_key,
        },
        "right": {
            "label": right_label,
            "source_name": right.source_name,
            "content_sha256": right.content_sha256,
            "analysis_key": right.analysis_key,
        },
        "common_capabilities": common,
        "comparisons": comparisons,
        "interpretation_note": "numeric deltas are evidence only and do not imply better/worse",
    }
