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


def _nested_delta(
    left: dict[str, Any],
    right: dict[str, Any],
    parent: str,
    key: str,
) -> float | None:
    first_parent = left.get(parent)
    second_parent = right.get(parent)
    if not isinstance(first_parent, dict) or not isinstance(second_parent, dict):
        return None
    return _delta(first_parent, second_parent, key)


def _sequence_count_delta(left: dict[str, Any], right: dict[str, Any], key: str) -> int | None:
    first = left.get(key)
    second = right.get(key)
    if not isinstance(first, list) or not isinstance(second, list):
        return None
    return len(second) - len(first)


def _mapping_cosine(first: object, second: object) -> float | None:
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


def _semantic_by_query(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = value.get("queries_ranked")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = row.get("query")
        if isinstance(query, str) and query and query not in result:
            result[query] = row
    return result


def _top_candidate_label(value: dict[str, Any]) -> str | None:
    candidate = value.get("top_candidate")
    if not isinstance(candidate, dict):
        return None
    label = candidate.get("label")
    return label if isinstance(label, str) and label else None


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

    transients_key = AnalysisCapability.TRANSIENTS.value
    if transients_key in common:
        a = left.measurements[transients_key]
        b = right.measurements[transients_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[transients_key] = {
                "strongest_event_time_seconds_delta": _delta(a, b, "strongest_event_time_seconds"),
                "strongest_frame_rms_dbfs_delta": _delta(a, b, "strongest_frame_rms_dbfs"),
                "transient_to_body_db_delta": _delta(a, b, "transient_to_body_db"),
                "microdynamic_p95_to_p10_db_delta": _delta(a, b, "microdynamic_p95_to_p10_db"),
                "strongest_event_attack_10_to_90_ms_delta": _delta(a, b, "strongest_event_attack_10_to_90_ms"),
                "strongest_event_decay_to_minus_12db_ms_delta": _delta(a, b, "strongest_event_decay_to_minus_12db_ms"),
                "strong_rise_density_per_second_delta": _delta(a, b, "strong_rise_density_per_second"),
            }

    texture_key = AnalysisCapability.TEXTURE.value
    if texture_key in common:
        a = left.measurements[texture_key]
        b = right.measurements[texture_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[texture_key] = {
                "spectral_flatness_mean_delta": _delta(a, b, "spectral_flatness_mean"),
                "spectral_flux_mean_delta": _delta(a, b, "spectral_flux_mean"),
                "zero_crossing_fraction_delta": _delta(a, b, "zero_crossing_fraction"),
                "energy_above_4khz_fraction_delta": _delta(a, b, "energy_above_4khz_fraction"),
                "energy_above_8khz_fraction_delta": _delta(a, b, "energy_above_8khz_fraction"),
            }

    stereo_bands_key = AnalysisCapability.STEREO_BANDS.value
    if stereo_bands_key in common:
        a = left.measurements[stereo_bands_key]
        b = right.measurements[stereo_bands_key]
        if isinstance(a, dict) and isinstance(b, dict):
            first_bands = a.get("bands")
            second_bands = b.get("bands")
            band_comparisons: dict[str, dict[str, float | None]] = {}
            if isinstance(first_bands, dict) and isinstance(second_bands, dict):
                for name in sorted(set(first_bands) & set(second_bands)):
                    first = first_bands.get(name)
                    second = second_bands.get(name)
                    if not isinstance(first, dict) or not isinstance(second, dict):
                        continue
                    band_comparisons[name] = {
                        "correlation_evidence_delta": _delta(first, second, "correlation_evidence"),
                        "side_energy_fraction_delta": _delta(first, second, "side_energy_fraction"),
                        "side_to_mid_db_delta": _delta(first, second, "side_to_mid_db"),
                    }
            comparisons[stereo_bands_key] = {
                "left_available": a.get("available"),
                "right_available": b.get("available"),
                "bands": band_comparisons,
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
                "onset_count_delta": _delta(a, b, "onset_count"),
                "onset_density_per_second_delta": _delta(a, b, "onset_density_per_second"),
                "tempo_bpm_evidence_delta": _delta(a, b, "tempo_bpm_evidence"),
            }

    beats_key = AnalysisCapability.MIR_BEATS.value
    if beats_key in common:
        a = left.measurements[beats_key]
        b = right.measurements[beats_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[beats_key] = {
                "beat_count_delta": _delta(a, b, "beat_count"),
                "beat_density_per_second_delta": _delta(a, b, "beat_density_per_second"),
                "tempo_bpm_evidence_delta": _delta(a, b, "tempo_bpm_evidence"),
                "beat_interval_median_seconds_delta": _delta(a, b, "beat_interval_median_seconds"),
                "beat_interval_coefficient_of_variation_delta": _delta(
                    a, b, "beat_interval_coefficient_of_variation"
                ),
            }

    tonal_key = AnalysisCapability.MIR_TONAL.value
    if tonal_key in common:
        a = left.measurements[tonal_key]
        b = right.measurements[tonal_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[tonal_key] = {
                "chroma_cosine_similarity": _mapping_cosine(a.get("chroma_profile"), b.get("chroma_profile")),
                "left_dominant_pitch_class_evidence": a.get("dominant_pitch_class_evidence"),
                "right_dominant_pitch_class_evidence": b.get("dominant_pitch_class_evidence"),
                "tonal_concentration_delta": _delta(a, b, "tonal_concentration"),
            }

    key_key = AnalysisCapability.MIR_KEY.value
    if key_key in common:
        a = left.measurements[key_key]
        b = right.measurements[key_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[key_key] = {
                "chroma_cosine_similarity": _mapping_cosine(a.get("chroma_profile"), b.get("chroma_profile")),
                "left_top_candidate": _top_candidate_label(a),
                "right_top_candidate": _top_candidate_label(b),
                "candidate_margin_to_second_delta": _delta(a, b, "candidate_margin_to_second"),
                "interpretation_note": "key candidates are signal-derived rankings; matching labels do not establish authoritative project key",
            }

    structure_key = AnalysisCapability.MIR_STRUCTURE.value
    if structure_key in common:
        a = left.measurements[structure_key]
        b = right.measurements[structure_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[structure_key] = {
                "boundary_candidate_count_delta": _sequence_count_delta(a, b, "boundary_candidates_seconds"),
                "novelty_median_delta": _delta(a, b, "novelty_median"),
                "novelty_p95_delta": _delta(a, b, "novelty_p95"),
                "local_tempo_median_bpm_delta": _nested_delta(a, b, "local_tempo_evidence", "median_bpm"),
                "local_tempo_p10_bpm_delta": _nested_delta(a, b, "local_tempo_evidence", "p10_bpm"),
                "local_tempo_p90_bpm_delta": _nested_delta(a, b, "local_tempo_evidence", "p90_bpm"),
            }

    pitch_key = AnalysisCapability.MIR_PITCH.value
    if pitch_key in common:
        a = left.measurements[pitch_key]
        b = right.measurements[pitch_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[pitch_key] = {
                "voiced_frame_fraction_delta": _delta(a, b, "voiced_frame_fraction"),
                "median_hz_delta": _delta(a, b, "median_hz"),
                "median_midi_delta_semitones": _delta(a, b, "median_midi"),
                "pitch_range_p10_to_p90_semitones_delta": _delta(a, b, "pitch_range_p10_to_p90_semitones"),
                "median_voicing_probability_delta": _delta(a, b, "median_voicing_probability"),
                "left_median_pitch_class_evidence": a.get("median_pitch_class_evidence"),
                "right_median_pitch_class_evidence": b.get("median_pitch_class_evidence"),
            }

    transcription_key = AnalysisCapability.MIR_TRANSCRIPTION.value
    if transcription_key in common:
        a = left.measurements[transcription_key]
        b = right.measurements[transcription_key]
        if isinstance(a, dict) and isinstance(b, dict):
            comparisons[transcription_key] = {
                "note_count_delta": _delta(a, b, "note_count"),
                "peak_estimated_polyphony_delta": _delta(a, b, "peak_estimated_polyphony"),
                "pitch_midi_min_delta": _delta(a, b, "pitch_midi_min"),
                "pitch_midi_max_delta": _delta(a, b, "pitch_midi_max"),
                "pitch_class_profile_cosine_similarity": _mapping_cosine(
                    a.get("duration_amplitude_weighted_pitch_class_profile"),
                    b.get("duration_amplitude_weighted_pitch_class_profile"),
                ),
            }

    semantic_key = AnalysisCapability.SEMANTIC.value
    if semantic_key in common:
        a = left.measurements[semantic_key]
        b = right.measurements[semantic_key]
        if isinstance(a, dict) and isinstance(b, dict):
            first_queries = _semantic_by_query(a)
            second_queries = _semantic_by_query(b)
            query_comparisons: dict[str, dict[str, float | None]] = {}
            for query in sorted(set(first_queries) & set(second_queries)):
                first = first_queries[query]
                second = second_queries[query]
                query_comparisons[query] = {
                    "mean_cosine_similarity_delta": _delta(first, second, "mean_cosine_similarity"),
                    "min_window_cosine_similarity_delta": _delta(first, second, "min_window_cosine_similarity"),
                    "max_window_cosine_similarity_delta": _delta(first, second, "max_window_cosine_similarity"),
                    "strongest_window_start_seconds_delta": _nested_delta(first, second, "strongest_window", "start_seconds"),
                }
            comparisons[semantic_key] = {
                "common_queries": sorted(query_comparisons),
                "queries": query_comparisons,
                "interpretation_note": "semantic score deltas compare only identical supplied queries and are not probability deltas",
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
