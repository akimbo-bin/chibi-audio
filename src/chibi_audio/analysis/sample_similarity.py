from __future__ import annotations

import math
from typing import Any, Iterable

from .models import AnalysisCapability, AnalysisReport


SAMPLE_SIMILARITY_SCHEMA_VERSION = "chibi-audio-sample-similarity/v1"


class SampleSimilarityError(ValueError):
    pass


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mapping_cosine(first: object, second: object) -> float | None:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return None
    names = sorted(set(first) & set(second))
    if not names:
        return None
    left = [_number(first.get(name)) or 0.0 for name in names]
    right = [_number(second.get(name)) or 0.0 for name in names]
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return None
    return numerator / (left_norm * right_norm)


def _measurement(report: AnalysisReport, capability: AnalysisCapability) -> dict[str, Any] | None:
    value = report.measurements.get(capability.value)
    return value if isinstance(value, dict) else None


def _semantic_profile(value: dict[str, Any] | None) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    rows = value.get("queries_ranked")
    if not isinstance(rows, list):
        return {}
    result: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = row.get("query")
        score = _number(row.get("mean_cosine_similarity"))
        if isinstance(query, str) and query and score is not None and query not in result:
            result[query] = score
    return result


def _semantic_evidence(
    reference: dict[str, float],
    candidate: dict[str, float],
) -> dict[str, Any] | None:
    common = sorted(set(reference) & set(candidate))
    if not common:
        return None
    deltas = {name: candidate[name] - reference[name] for name in common}
    absolute = [abs(value) for value in deltas.values()]
    rms = math.sqrt(sum(value * value for value in deltas.values()) / len(deltas))
    profile_cosine = None
    if len(common) >= 2:
        profile_cosine = _mapping_cosine(
            {name: reference[name] for name in common},
            {name: candidate[name] for name in common},
        )
    return {
        "common_queries": common,
        "common_query_count": len(common),
        "mean_absolute_score_delta": sum(absolute) / len(absolute),
        "root_mean_square_score_delta": rms,
        "profile_cosine_similarity": profile_cosine,
        "query_score_delta": deltas,
        "interpretation_note": (
            "same-prompt CLAP score profiles are relative semantic evidence; score distance is not a probability distance"
        ),
    }


def _identity(report: AnalysisReport, index: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_name": report.source_name,
        "content_sha256": report.content_sha256,
        "analysis_key": report.analysis_key,
    }
    if index is not None:
        result["candidate_index"] = index
    return result


def _rank(
    candidates: list[dict[str, Any]],
    *,
    path: tuple[str, ...],
    descending: bool,
) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        value: object = candidate.get("evidence")
        for name in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(name)
        score = _number(value)
        if score is None:
            continue
        rows.append(
            {
                **candidate["candidate"],
                "value": score,
            }
        )
    return sorted(rows, key=lambda row: row["value"], reverse=descending)


def rank_sample_similarity(
    reference: AnalysisReport,
    candidates: Iterable[AnalysisReport],
) -> dict[str, Any]:
    """Rank already-computed sample evidence along separate similarity axes.

    No audio is reopened and no combined score is produced. Each axis preserves a
    distinct meaning so callers can choose timbral, spectral, tonal or semantic
    similarity appropriate to the task.
    """

    values = tuple(candidates)
    if not values:
        raise SampleSimilarityError("at least one candidate report is required")
    if any(not isinstance(value, AnalysisReport) for value in values):
        raise SampleSimilarityError("all candidates must be AnalysisReport instances")

    reference_timbre = _measurement(reference, AnalysisCapability.MIR_TIMBRE)
    reference_spectrum = _measurement(reference, AnalysisCapability.SPECTRUM)
    reference_tonal = _measurement(reference, AnalysisCapability.MIR_TONAL)
    reference_semantic = _semantic_profile(_measurement(reference, AnalysisCapability.SEMANTIC))

    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(values):
        evidence: dict[str, Any] = {}

        candidate_timbre = _measurement(candidate, AnalysisCapability.MIR_TIMBRE)
        if reference_timbre is not None and candidate_timbre is not None:
            evidence["timbre"] = {
                "mfcc_shape_mean_cosine_similarity": _mapping_cosine(
                    reference_timbre.get("mfcc_shape_mean"),
                    candidate_timbre.get("mfcc_shape_mean"),
                ),
                "spectral_contrast_mean_cosine_similarity": _mapping_cosine(
                    reference_timbre.get("spectral_contrast_mean_db"),
                    candidate_timbre.get("spectral_contrast_mean_db"),
                ),
            }

        candidate_spectrum = _measurement(candidate, AnalysisCapability.SPECTRUM)
        if reference_spectrum is not None and candidate_spectrum is not None:
            evidence["spectrum"] = {
                "band_energy_cosine_similarity": _mapping_cosine(
                    reference_spectrum.get("band_energy_fraction"),
                    candidate_spectrum.get("band_energy_fraction"),
                )
            }

        candidate_tonal = _measurement(candidate, AnalysisCapability.MIR_TONAL)
        if reference_tonal is not None and candidate_tonal is not None:
            evidence["tonal"] = {
                "chroma_cosine_similarity": _mapping_cosine(
                    reference_tonal.get("chroma_profile"),
                    candidate_tonal.get("chroma_profile"),
                )
            }

        candidate_semantic = _semantic_profile(_measurement(candidate, AnalysisCapability.SEMANTIC))
        semantic = _semantic_evidence(reference_semantic, candidate_semantic)
        if semantic is not None:
            evidence["semantic"] = semantic

        rows.append(
            {
                "candidate": _identity(candidate, index),
                "available_axes": sorted(evidence),
                "evidence": evidence,
            }
        )

    rankings = {
        "timbre_mfcc_shape_cosine": {
            "direction": "higher_is_more_similar",
            "candidates": _rank(
                rows,
                path=("timbre", "mfcc_shape_mean_cosine_similarity"),
                descending=True,
            ),
        },
        "timbre_spectral_contrast_cosine": {
            "direction": "higher_is_more_similar",
            "candidates": _rank(
                rows,
                path=("timbre", "spectral_contrast_mean_cosine_similarity"),
                descending=True,
            ),
        },
        "spectral_band_cosine": {
            "direction": "higher_is_more_similar",
            "candidates": _rank(
                rows,
                path=("spectrum", "band_energy_cosine_similarity"),
                descending=True,
            ),
        },
        "tonal_chroma_cosine": {
            "direction": "higher_is_more_similar",
            "candidates": _rank(
                rows,
                path=("tonal", "chroma_cosine_similarity"),
                descending=True,
            ),
        },
        "semantic_profile_mean_absolute_delta": {
            "direction": "lower_is_more_similar",
            "candidates": _rank(
                rows,
                path=("semantic", "mean_absolute_score_delta"),
                descending=False,
            ),
        },
    }

    return {
        "schema_version": SAMPLE_SIMILARITY_SCHEMA_VERSION,
        "reference": _identity(reference),
        "candidate_count": len(rows),
        "candidates": rows,
        "rankings": rankings,
        "interpretation_note": (
            "similarity axes remain separate by design; this helper does not produce an opaque combined score or a quality ranking"
        ),
    }
