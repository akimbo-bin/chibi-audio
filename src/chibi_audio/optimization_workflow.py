from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analysis.models import AnalysisReport
from .capture import CaptureError
from .experiment_journal import (
    attach_clean_loudness_evaluation,
    verify_experiment_journal,
)
from .optimizer import CleanLoudnessGoal, evaluate_clean_loudness_candidate


class CleanLoudnessWorkflowError(ValueError):
    pass


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanLoudnessWorkflowError(f"could not read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise CleanLoudnessWorkflowError(f"expected JSON object: {path}")
    return payload


def _resolve_reference(reference: str, base: Path) -> Path:
    path = Path(reference)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _analysis_binding(journal: dict[str, Any], label: str) -> dict[str, Any]:
    evidence = journal.get("evidence")
    if not isinstance(evidence, dict):
        raise CleanLoudnessWorkflowError("experiment journal has no evidence object")
    bindings = evidence.get("analysis_reports")
    if not isinstance(bindings, list):
        raise CleanLoudnessWorkflowError("experiment journal has no analysis report bindings")
    matches = [
        item
        for item in bindings
        if isinstance(item, dict) and item.get("label") == label
    ]
    if len(matches) != 1:
        if not matches:
            raise CleanLoudnessWorkflowError(
                f"analysis label is not bound to experiment journal: {label}"
            )
        raise CleanLoudnessWorkflowError(
            f"analysis label is ambiguous in experiment journal: {label}"
        )
    return matches[0]


def load_bound_journal_analysis(
    journal_path: str | Path,
    *,
    label: str,
    tap_id: int | None = None,
    source_label: str | None = None,
) -> AnalysisReport:
    """Load one exact analysis/v1 report through a verified experiment-journal binding."""
    path = Path(journal_path)
    journal = verify_experiment_journal(path)
    binding = _analysis_binding(journal, label)
    report_ref = binding.get("report_path")
    if not isinstance(report_ref, str) or not report_ref:
        raise CleanLoudnessWorkflowError("analysis binding has no report_path")
    report_path = _resolve_reference(report_ref, path.parent)
    capture_report = _load_json_object(report_path)
    taps = capture_report.get("taps")
    if not isinstance(taps, list) or not taps:
        raise CleanLoudnessWorkflowError("bound capture-analysis report has no taps")

    selected: list[dict[str, Any]] = []
    for item in taps:
        if not isinstance(item, dict):
            continue
        if tap_id is not None and item.get("tap_id") != tap_id:
            continue
        if source_label is not None and item.get("source_label") != source_label:
            continue
        selected.append(item)
    if len(selected) != 1:
        if not selected:
            raise CleanLoudnessWorkflowError(
                "no bound analysis tap matches the requested tap identity"
            )
        raise CleanLoudnessWorkflowError(
            "analysis binding contains multiple taps; specify tap_id and/or source_label"
        )

    entry = selected[0]
    inner = entry.get("analysis")
    if not isinstance(inner, dict):
        raise CleanLoudnessWorkflowError("bound analysis tap has no analysis/v1 payload")
    report = AnalysisReport.from_dict(inner)
    content_sha = entry.get("content_sha256")
    if not isinstance(content_sha, str) or report.content_sha256 != content_sha:
        raise CleanLoudnessWorkflowError(
            "bound analysis tap content identity does not match its analysis/v1 payload"
        )
    return report


def _validate_journal_pair(
    baseline_path: Path,
    candidate_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = verify_experiment_journal(baseline_path)
    candidate = verify_experiment_journal(candidate_path)
    if baseline.get("variant_role") != "baseline":
        raise CleanLoudnessWorkflowError("baseline journal must have variant_role=baseline")
    if candidate.get("variant_role") != "candidate":
        raise CleanLoudnessWorkflowError("candidate journal must have variant_role=candidate")
    if baseline.get("comparison_id") != candidate.get("comparison_id"):
        raise CleanLoudnessWorkflowError(
            "baseline and candidate journals must share comparison_id"
        )
    baseline_capture = baseline.get("capture")
    candidate_capture = candidate.get("capture")
    if not isinstance(baseline_capture, dict) or not isinstance(candidate_capture, dict):
        raise CleanLoudnessWorkflowError("experiment journal capture lineage is invalid")
    baseline_experiment = str(baseline_capture.get("experiment_id") or "")
    if str(candidate.get("parent_experiment_id") or "") != baseline_experiment:
        raise CleanLoudnessWorkflowError(
            "candidate parent_experiment_id must match baseline experiment_id"
        )
    return baseline, candidate


def evaluate_bound_clean_loudness_candidate(
    baseline_journal: str | Path,
    candidate_journal: str | Path,
    *,
    baseline_analysis_label: str,
    candidate_analysis_label: str,
    goal: CleanLoudnessGoal,
    baseline_tap_id: int | None = None,
    candidate_tap_id: int | None = None,
    baseline_source_label: str | None = None,
    candidate_source_label: str | None = None,
) -> dict[str, Any]:
    """Evaluate exact journal-bound evidence without mutating Live or either journal."""
    baseline_path = Path(baseline_journal)
    candidate_path = Path(candidate_journal)
    baseline, candidate = _validate_journal_pair(baseline_path, candidate_path)
    baseline_report = load_bound_journal_analysis(
        baseline_path,
        label=baseline_analysis_label,
        tap_id=baseline_tap_id,
        source_label=baseline_source_label,
    )
    candidate_report = load_bound_journal_analysis(
        candidate_path,
        label=candidate_analysis_label,
        tap_id=candidate_tap_id,
        source_label=candidate_source_label,
    )
    result = evaluate_clean_loudness_candidate(
        baseline_report,
        candidate_report,
        goal=goal,
    )
    baseline_capture = baseline["capture"]
    candidate_capture = candidate["capture"]
    result["workflow_provenance"] = {
        "comparison_id": baseline["comparison_id"],
        "baseline_experiment_id": baseline_capture["experiment_id"],
        "candidate_experiment_id": candidate_capture["experiment_id"],
        "baseline_analysis_label": baseline_analysis_label,
        "candidate_analysis_label": candidate_analysis_label,
        "baseline_tap_id": baseline_tap_id,
        "candidate_tap_id": candidate_tap_id,
        "baseline_source_label": baseline_source_label,
        "candidate_source_label": candidate_source_label,
    }
    return result


def persist_bound_clean_loudness_evaluation(
    baseline_journal: str | Path,
    candidate_journal: str | Path,
    *,
    output_path: str | Path,
    binding_label: str,
    baseline_analysis_label: str,
    candidate_analysis_label: str,
    goal: CleanLoudnessGoal,
    baseline_tap_id: int | None = None,
    candidate_tap_id: int | None = None,
    baseline_source_label: str | None = None,
    candidate_source_label: str | None = None,
    attached_at_utc: str | None = None,
) -> dict[str, Any]:
    """Persist + bind one exact evaluation; never change the journal decision state."""
    baseline_path = Path(baseline_journal).resolve()
    candidate_path = Path(candidate_journal).resolve()
    output = Path(output_path).resolve()
    if output in {baseline_path, candidate_path}:
        raise CleanLoudnessWorkflowError(
            "evaluation output must be separate from both experiment journals"
        )
    if output.exists():
        raise CleanLoudnessWorkflowError(
            f"refusing to overwrite existing evaluation artifact: {output}"
        )

    evaluation = evaluate_bound_clean_loudness_candidate(
        baseline_path,
        candidate_path,
        baseline_analysis_label=baseline_analysis_label,
        candidate_analysis_label=candidate_analysis_label,
        goal=goal,
        baseline_tap_id=baseline_tap_id,
        candidate_tap_id=candidate_tap_id,
        baseline_source_label=baseline_source_label,
        candidate_source_label=candidate_source_label,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(evaluation, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temp.replace(output)
        try:
            attach_clean_loudness_evaluation(
                candidate_path,
                baseline_journal=baseline_path,
                evaluation_report=output,
                label=binding_label,
                attached_at_utc=attached_at_utc,
            )
        except Exception:
            output.unlink(missing_ok=True)
            raise
    finally:
        temp.unlink(missing_ok=True)

    candidate = verify_experiment_journal(candidate_path)
    return {
        "artifact_effect_state": "STARTED_CONFIRMED",
        "live_mutation_effect_state": "NOT_STARTED",
        "evaluation_path": str(output),
        "candidate_journal": str(candidate_path),
        "journal_decision_status": candidate["decision"]["status"],
        "evaluation": evaluation,
    }
