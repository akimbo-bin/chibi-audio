from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from .ab_compare import create_level_matched_ab
from .audio import analyze_audio
from .sidechain_verify import _load_manifest, _tap_by_label, verify_sidechain_capture


SIDECHAIN_COMPARISON_SCHEMA_VERSION = "chibi-audio-sidechain-comparison/v1"


class SidechainComparisonError(ValueError):
    pass


def _number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return float(candidate - baseline)


def _audio_metrics(path: Path) -> dict[str, float | None]:
    raw = analyze_audio(path)
    return {
        "integrated_lufs": _number(raw, "integrated_lufs"),
        "true_peak_dbtp": _number(raw, "true_peak_dbtp"),
        "sample_peak_dbfs": _number(raw, "sample_peak_dbfs"),
        "rms_dbfs": _number(raw, "rms_dbfs"),
        "crest_db": _number(raw, "crest_db"),
        "lra_lu": _number(raw, "lra_lu"),
        "stereo_correlation": _number(raw, "stereo_correlation"),
        "side_to_mid_db": _number(raw, "side_to_mid_db"),
    }


def _transfer(pre: dict[str, float | None], post: dict[str, float | None]) -> dict[str, float | None]:
    return {
        "integrated_loudness_lu": _delta(post["integrated_lufs"], pre["integrated_lufs"]),
        "rms_db": _delta(post["rms_dbfs"], pre["rms_dbfs"]),
        "true_peak_db": _delta(post["true_peak_dbtp"], pre["true_peak_dbtp"]),
        "sample_peak_db": _delta(post["sample_peak_dbfs"], pre["sample_peak_dbfs"]),
        "crest_db": _delta(post["crest_db"], pre["crest_db"]),
        "side_to_mid_db": _delta(post["side_to_mid_db"], pre["side_to_mid_db"]),
    }


def _reference_gain_median(verification: dict[str, Any]) -> float | None:
    values = []
    for row in verification.get("events", []):
        value = row.get("reference_chain_gain_db") if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            values.append(float(value))
    return None if not values else float(median(values))


def _variant(
    manifest_path: Path,
    *,
    trigger_label: str,
    target_pre_label: str,
    target_post_label: str,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    trigger = _tap_by_label(manifest_path, manifest, trigger_label)
    target_pre = _tap_by_label(manifest_path, manifest, target_pre_label)
    target_post = _tap_by_label(manifest_path, manifest, target_post_label)
    verification = verify_sidechain_capture(
        manifest_path,
        trigger_label=trigger_label,
        target_pre_label=target_pre_label,
        target_post_label=target_post_label,
    )
    pre_metrics = _audio_metrics(target_pre["artifact"])
    post_metrics = _audio_metrics(target_post["artifact"])
    return {
        "experiment_id": manifest.get("experiment_id"),
        "manifest": str(manifest_path),
        "trigger": {
            "content_sha256": trigger["content_sha256"],
            "tap_id": trigger["tap_id"],
        },
        "target_pre": {
            "content_sha256": target_pre["content_sha256"],
            "tap_id": target_pre["tap_id"],
            "artifact": str(target_pre["artifact"]),
            "metrics": pre_metrics,
        },
        "target_post": {
            "content_sha256": target_post["content_sha256"],
            "tap_id": target_post["tap_id"],
            "artifact": str(target_post["artifact"]),
            "metrics": post_metrics,
        },
        "chain_transfer": _transfer(pre_metrics, post_metrics),
        "verification": verification,
        "reference_chain_gain_db_median": _reference_gain_median(verification),
    }


def _aggregate_delta(candidate: dict[str, Any], baseline: dict[str, Any], key: str) -> float | None:
    ca = candidate["verification"].get("aggregate", {})
    ba = baseline["verification"].get("aggregate", {})
    cv = ca.get(key)
    bv = ba.get(key)
    if not isinstance(cv, (int, float)) or isinstance(cv, bool):
        return None
    if not isinstance(bv, (int, float)) or isinstance(bv, bool):
        return None
    return float(cv) - float(bv)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def compare_sidechain_captures(
    baseline_manifest: str | Path,
    candidate_manifest: str | Path,
    *,
    trigger_label: str,
    target_pre_label: str,
    target_post_label: str,
    output_dir: str | Path,
    comparison_id: str,
) -> Path:
    """Compare two same-stimulus sidechain captures and create a level-matched post A/B."""
    base_path = Path(baseline_manifest).resolve()
    cand_path = Path(candidate_manifest).resolve()
    if base_path == cand_path:
        raise SidechainComparisonError("baseline and candidate manifests must be distinct")
    if not base_path.is_file() or not cand_path.is_file():
        raise FileNotFoundError(base_path if not base_path.is_file() else cand_path)

    baseline = _variant(
        base_path,
        trigger_label=trigger_label,
        target_pre_label=target_pre_label,
        target_post_label=target_post_label,
    )
    candidate = _variant(
        cand_path,
        trigger_label=trigger_label,
        target_pre_label=target_pre_label,
        target_post_label=target_post_label,
    )
    if baseline["trigger"]["content_sha256"] != candidate["trigger"]["content_sha256"]:
        raise SidechainComparisonError(
            "baseline and candidate trigger artifacts differ; refusing to compare different stimuli"
        )

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in comparison_id.strip()).strip("-.")
    if not safe_id:
        raise SidechainComparisonError("comparison_id must contain a usable filename component")
    summary_path = destination / f"{safe_id}__sidechain-comparison.json"
    if summary_path.exists():
        raise SidechainComparisonError(f"refusing to overwrite existing comparison: {summary_path}")

    ab_manifest = create_level_matched_ab(
        left=baseline["target_post"]["artifact"],
        right=candidate["target_post"]["artifact"],
        output_dir=destination,
        comparison_id=safe_id,
        left_label="baseline",
        right_label="candidate",
    )

    base_post = baseline["target_post"]["metrics"]
    cand_post = candidate["target_post"]["metrics"]
    base_pre = baseline["target_pre"]["metrics"]
    cand_pre = candidate["target_pre"]["metrics"]
    base_transfer = baseline["chain_transfer"]
    cand_transfer = candidate["chain_transfer"]
    event_keys = (
        "reduction_p90_db_median",
        "peak_smoothed_reduction_db_median",
        "duration_above_depth_ms_median",
        "positive_reduction_db_ms_median",
        "effective_onset_ms_median",
        "peak_time_ms_median",
        "recovery_complete_ms_median",
        "recovery_from_peak_ms_median",
    )
    transfer_keys = tuple(base_transfer)

    payload = {
        "schema_version": SIDECHAIN_COMPARISON_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "comparison_id": safe_id,
        "labels": {
            "trigger": trigger_label,
            "target_pre": target_pre_label,
            "target_post": target_post_label,
        },
        "comparability": {
            "same_trigger_content": True,
            "trigger_content_sha256": baseline["trigger"]["content_sha256"],
            "baseline_pre_content_sha256": baseline["target_pre"]["content_sha256"],
            "candidate_pre_content_sha256": candidate["target_pre"]["content_sha256"],
            "target_pre_byte_identical": baseline["target_pre"]["content_sha256"] == candidate["target_pre"]["content_sha256"],
            "note": (
                "Event comparison requires identical rendered trigger content. Target-pre may vary between renders; "
                "chain-transfer metrics normalize each post render against its own pre render."
            ),
        },
        "baseline": baseline,
        "candidate": candidate,
        "candidate_minus_baseline": {
            "event_correlated": {key: _aggregate_delta(candidate, baseline, key) for key in event_keys},
            "as_produced_target_pre": {key: _delta(cand_pre.get(key), base_pre.get(key)) for key in base_pre},
            "as_produced_target_post": {key: _delta(cand_post.get(key), base_post.get(key)) for key in base_post},
            "normalized_chain_transfer": {key: _delta(cand_transfer.get(key), base_transfer.get(key)) for key in transfer_keys},
            "reference_chain_gain_db_median": _delta(
                candidate["reference_chain_gain_db_median"], baseline["reference_chain_gain_db_median"]
            ),
        },
        "headroom": {
            "baseline_post_true_peak_dbtp": base_post.get("true_peak_dbtp"),
            "candidate_post_true_peak_dbtp": cand_post.get("true_peak_dbtp"),
            "candidate_relative_peak_headroom_change_db": (
                None
                if base_post.get("true_peak_dbtp") is None or cand_post.get("true_peak_dbtp") is None
                else float(base_post["true_peak_dbtp"] - cand_post["true_peak_dbtp"])
            ),
            "scope_note": (
                "These are internal target-post float-render peaks, not a final-output clipping verdict. Positive relative headroom change means the candidate post render peaked lower."
            ),
        },
        "level_matched_ab_manifest": str(ab_manifest),
        "interpretation_note": (
            "This report is descriptive evidence only. Event-correlated metrics quantify collision-window ducking; "
            "normalized chain-transfer metrics reduce sensitivity to target-pre render variance; the level-matched A/B remains the artist-facing listening check."
        ),
    }
    _atomic_write_json(summary_path, payload)
    return summary_path
