from __future__ import annotations

import math
from typing import Any, Iterable

from .analysis.overlap import (
    compare_capture_spectral_overlap,
    compare_capture_spectral_overlap_timeline,
)


SIDECHAIN_INTENT_SCHEMA_VERSION = "chibi-audio-sidechain-intent/v1"


class SidechainIntentError(ValueError):
    pass


DEFAULT_INTENT_HEURISTICS: dict[str, float] = {
    "no_action_global_overlap_max": 0.15,
    "no_action_timeline_p90_max": 0.25,
    "frequency_selective_global_overlap_min": 0.25,
    "frequency_selective_timeline_median_min": 0.30,
    "frequency_selective_strongest_overlap_min": 0.70,
    "frequency_selective_top3_share_min": 0.75,
    "event_selective_timeline_median_max": 0.30,
    "event_selective_timeline_p90_min": 0.60,
    "event_selective_strongest_overlap_min": 0.65,
    "full_band_global_overlap_min": 0.65,
    "full_band_timeline_median_min": 0.55,
    "full_band_timeline_p10_min": 0.25,
    "full_band_cosine_median_min": 0.75,
    "full_band_top3_share_max": 0.70,
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _labels(capture_analysis: dict[str, Any]) -> list[str]:
    taps = capture_analysis.get("taps")
    if not isinstance(taps, list) or not taps:
        raise SidechainIntentError("capture analysis contains no taps")
    labels: list[str] = []
    for raw in taps:
        if not isinstance(raw, dict):
            raise SidechainIntentError("capture-analysis tap entry must be an object")
        label = str(raw.get("source_label") or "").strip()
        if not label:
            raise SidechainIntentError("every capture-analysis tap requires a non-empty source_label")
        labels.append(label)
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise SidechainIntentError(
            "capture-analysis source labels must be unique for intent selection: " + ", ".join(duplicates)
        )
    return labels


def _pair_key(left: str, right: str) -> frozenset[str]:
    return frozenset((left, right))


def _pair_map(report: dict[str, Any]) -> dict[frozenset[str], dict[str, Any]]:
    result: dict[frozenset[str], dict[str, Any]] = {}
    for row in report.get("pairs", []):
        left = str((row.get("left") or {}).get("source_label") or "")
        right = str((row.get("right") or {}).get("source_label") or "")
        key = _pair_key(left, right)
        if not left or not right or len(key) != 2:
            raise SidechainIntentError("overlap report contains an invalid source-label pair")
        if key in result:
            raise SidechainIntentError(f"overlap report contains duplicate pair: {left!r}, {right!r}")
        result[key] = row
    return result


def _source_oriented_rms_delta(pair: dict[str, Any], source_label: str) -> float | None:
    delta = _finite(pair.get("right_minus_left_rms_db"))
    if delta is None:
        return None
    left = str((pair.get("left") or {}).get("source_label") or "")
    return delta if left == source_label else -delta


def _top3_overlap_share(pair: dict[str, Any]) -> float | None:
    overlap = _finite(pair.get("spectral_overlap_coefficient"))
    if overlap is None or overlap <= 1.0e-12:
        return None
    rows = pair.get("dominant_overlapping_bands")
    if not isinstance(rows, list):
        return None
    values = sorted(
        (
            value
            for raw in rows
            if isinstance(raw, dict)
            and (value := _finite(raw.get("overlap_fraction"))) is not None
        ),
        reverse=True,
    )
    if not values:
        return None
    return min(1.0, float(sum(values[:3]) / overlap))


def _strongest_moment(timeline_pair: dict[str, Any]) -> dict[str, Any] | None:
    rows = timeline_pair.get("strongest_overlap_moments")
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    return first if isinstance(first, dict) else None


def _processing_proposal(
    *,
    global_overlap: float | None,
    timeline_p10: float | None,
    timeline_median: float | None,
    timeline_p90: float | None,
    cosine_median: float | None,
    strongest_overlap: float | None,
    top3_share: float | None,
    thresholds: dict[str, float],
) -> tuple[str, str, list[str]]:
    if (
        global_overlap is not None
        and timeline_p90 is not None
        and global_overlap <= thresholds["no_action_global_overlap_max"]
        and timeline_p90 <= thresholds["no_action_timeline_p90_max"]
    ):
        return (
            "none",
            "NO_ACTION_EVIDENCE",
            [
                "global spectral overlap is below the declared no-action ceiling",
                "even the timeline p90 overlap is below the declared no-action ceiling",
            ],
        )

    if (
        global_overlap is not None
        and timeline_p10 is not None
        and timeline_median is not None
        and cosine_median is not None
        and top3_share is not None
        and global_overlap >= thresholds["full_band_global_overlap_min"]
        and timeline_median >= thresholds["full_band_timeline_median_min"]
        and timeline_p10 >= thresholds["full_band_timeline_p10_min"]
        and cosine_median >= thresholds["full_band_cosine_median_min"]
        and top3_share <= thresholds["full_band_top3_share_max"]
    ):
        return (
            "full_band_gain_duck",
            "FULL_BAND_DUCK_CANDIDATE",
            [
                "overlap is high globally and remains high across the timeline",
                "spectral similarity is high and overlap is not concentrated in only a few dominant bands",
            ],
        )

    if (
        global_overlap is not None
        and timeline_median is not None
        and strongest_overlap is not None
        and top3_share is not None
        and global_overlap >= thresholds["frequency_selective_global_overlap_min"]
        and timeline_median >= thresholds["frequency_selective_timeline_median_min"]
        and strongest_overlap >= thresholds["frequency_selective_strongest_overlap_min"]
        and top3_share >= thresholds["frequency_selective_top3_share_min"]
    ):
        return (
            "frequency_selective_duck",
            "FREQUENCY_SELECTIVE_DUCK_CANDIDATE",
            [
                "overlap is material both globally and in typical timeline windows",
                "strongest overlap moments are concentrated in a small number of frequency bands",
            ],
        )

    if (
        timeline_median is not None
        and timeline_p90 is not None
        and strongest_overlap is not None
        and timeline_median <= thresholds["event_selective_timeline_median_max"]
        and timeline_p90 >= thresholds["event_selective_timeline_p90_min"]
        and strongest_overlap >= thresholds["event_selective_strongest_overlap_min"]
    ):
        return (
            "event_selective_duck",
            "EVENT_SELECTIVE_DUCK_CANDIDATE",
            [
                "typical overlap is limited but high-overlap windows recur in the upper timeline percentile",
                "the strongest localized collision exceeds the declared event-selective threshold",
            ],
        )

    return (
        "evidence_review",
        "REVIEW_OVERLAP_EVIDENCE",
        ["the measured overlap does not satisfy one of the declared processing-class heuristics"],
    )


def propose_sidechain_intents(
    capture_analysis: dict[str, Any],
    *,
    source_label: str,
    target_labels: Iterable[str] | None = None,
    time_tolerance_seconds: float = 0.08,
    max_moments_per_pair: int = 6,
    heuristics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Propose sidechain processing classes from spectral occupancy evidence only.

    The returned processing classes are transparent heuristic proposals, not claims
    that sidechaining is artistically necessary or that masking is perceptually proven.
    """
    labels = _labels(capture_analysis)
    source = source_label.strip()
    if labels.count(source) != 1:
        raise SidechainIntentError(f"source_label must match exactly one capture tap: {source!r}")

    if target_labels is None:
        targets = [label for label in labels if label != source]
    else:
        targets = [str(value).strip() for value in target_labels]
        if any(not value for value in targets):
            raise SidechainIntentError("target_labels cannot contain empty labels")
        if len(set(targets)) != len(targets):
            raise SidechainIntentError("target_labels must be unique")
        if source in targets:
            raise SidechainIntentError("source_label cannot also be a target_label")
        missing = [label for label in targets if label not in labels]
        if missing:
            raise SidechainIntentError("target_labels are not present in capture analysis: " + ", ".join(missing))
    if not targets:
        raise SidechainIntentError("at least one target label is required")

    thresholds = dict(DEFAULT_INTENT_HEURISTICS)
    if heuristics:
        unknown = sorted(set(heuristics) - set(thresholds))
        if unknown:
            raise SidechainIntentError("unknown sidechain intent heuristic keys: " + ", ".join(unknown))
        for key, raw in heuristics.items():
            value = _finite(raw)
            if value is None or value < 0.0 or value > 1.0:
                raise SidechainIntentError(f"heuristic {key!r} must be finite and between 0 and 1")
            thresholds[key] = value

    global_report = compare_capture_spectral_overlap(capture_analysis, dominant_band_limit=8)
    timeline_report = compare_capture_spectral_overlap_timeline(
        capture_analysis,
        time_tolerance_seconds=time_tolerance_seconds,
        dominant_band_limit=8,
        max_moments_per_pair=max_moments_per_pair,
    )
    global_pairs = _pair_map(global_report)
    timeline_pairs = _pair_map(timeline_report)

    candidates: list[dict[str, Any]] = []
    for target in targets:
        key = _pair_key(source, target)
        global_pair = global_pairs.get(key)
        timeline_pair = timeline_pairs.get(key)
        if global_pair is None or timeline_pair is None:
            raise SidechainIntentError(f"capture analysis does not provide complete overlap evidence for {source!r} -> {target!r}")

        overlap_stats = timeline_pair.get("overlap_coefficient") or {}
        cosine_stats = timeline_pair.get("cosine_similarity") or {}
        global_overlap = _finite(global_pair.get("spectral_overlap_coefficient"))
        timeline_p10 = _finite(overlap_stats.get("p10"))
        timeline_median = _finite(overlap_stats.get("median"))
        timeline_p90 = _finite(overlap_stats.get("p90"))
        cosine_median = _finite(cosine_stats.get("median"))
        strongest = _strongest_moment(timeline_pair)
        strongest_overlap = None if strongest is None else _finite(strongest.get("spectral_overlap_coefficient"))
        top3_share = _top3_overlap_share(global_pair)
        processing_class, evidence_status, basis = _processing_proposal(
            global_overlap=global_overlap,
            timeline_p10=timeline_p10,
            timeline_median=timeline_median,
            timeline_p90=timeline_p90,
            cosine_median=cosine_median,
            strongest_overlap=strongest_overlap,
            top3_share=top3_share,
            thresholds=thresholds,
        )
        candidates.append(
            {
                "source_label": source,
                "target_label": target,
                "processing_class_proposal": processing_class,
                "evidence_status": evidence_status,
                "proposal_basis": basis,
                "global": {
                    "spectral_overlap_coefficient": global_overlap,
                    "spectral_cosine_similarity": _finite(global_pair.get("spectral_cosine_similarity")),
                    "target_minus_source_rms_db": _source_oriented_rms_delta(global_pair, source),
                    "top3_overlap_share": top3_share,
                    "dominant_overlapping_bands": global_pair.get("dominant_overlapping_bands") or [],
                },
                "timeline": {
                    "matched_window_count": timeline_pair.get("matched_window_count"),
                    "overlap_coefficient": {
                        "p10": timeline_p10,
                        "median": timeline_median,
                        "p90": timeline_p90,
                    },
                    "cosine_similarity": {
                        "p10": _finite(cosine_stats.get("p10")),
                        "median": cosine_median,
                        "p90": _finite(cosine_stats.get("p90")),
                    },
                    "strongest_overlap_moment": strongest,
                },
                "method_examples": {
                    "none": [],
                    "frequency_selective_duck": ["external_sidechain_dynamic_eq", "spectral_carving"],
                    "event_selective_duck": ["short_gain_envelope", "transient_triggered_dynamic_eq"],
                    "full_band_gain_duck": ["native_sidechain_compressor", "volume_shape"],
                    "evidence_review": [],
                }[processing_class],
            }
        )

    candidates.sort(
        key=lambda row: (
            row["timeline"]["overlap_coefficient"]["median"] is not None,
            row["timeline"]["overlap_coefficient"]["median"] or -1.0,
            row["timeline"]["overlap_coefficient"]["p90"] or -1.0,
        ),
        reverse=True,
    )
    return {
        "schema_version": SIDECHAIN_INTENT_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "capture_manifest": capture_analysis.get("capture_manifest"),
        "experiment_id": capture_analysis.get("experiment_id"),
        "source_label": source,
        "candidate_count": len(candidates),
        "evidence_order": "timeline_median_overlap_descending_then_p90",
        "heuristics": thresholds,
        "candidates": candidates,
        "interpretation_note": (
            "Processing classes are bounded heuristic proposals from spectral occupancy evidence. They do not prove audible masking, "
            "do not imply that a change should be applied, and do not authorize Live mutations. Artist intent, level, arrangement, "
            "phase and listening evidence remain separate inputs."
        ),
    }
