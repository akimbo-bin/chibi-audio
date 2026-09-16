from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .capture import CaptureError, _safe_id
from .optimizer import CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION


JOURNAL_SCHEMA_VERSION = 1
CAPTURE_ANALYSIS_SCHEMA_VERSION = "chibi-audio-capture-analysis/v1"
ANALYSIS_REPORT_SCHEMA_VERSION = "chibi-audio-analysis/v1"
VARIANT_ROLES = frozenset({"baseline", "candidate"})
DECISION_STATUSES = frozenset({"keep", "reject", "refine"})


@dataclass(frozen=True, slots=True)
class ExperimentChange:
    target: str
    parameter: str
    before: Any
    after: Any
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise CaptureError("change target must not be empty")
        if not self.parameter.strip():
            raise CaptureError("change parameter must not be empty")
        try:
            json.dumps(self.before, allow_nan=False)
            json.dumps(self.after, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise CaptureError("change before/after values must be JSON serializable") from exc

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "target": self.target,
            "parameter": self.parameter,
            "before": self.before,
            "after": self.after,
        }
        if self.unit is not None:
            result["unit"] = self.unit
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureError(f"could not read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise CaptureError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CaptureError(f"could not hash file: {path}") from exc
    return digest.hexdigest()


def _normalize_sha256(value: object, *, context: str) -> str:
    if not isinstance(value, str):
        raise CaptureError(f"{context} has no valid SHA-256")
    normalized = value.lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise CaptureError(f"{context} has no valid SHA-256")
    return normalized


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def _validate_capture_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise CaptureError("experiment journal currently requires capture manifest schema_version=1")
    if not str(manifest.get("experiment_id") or "").strip():
        raise CaptureError("capture manifest is missing experiment_id")
    if not isinstance(manifest.get("requested_range"), dict):
        raise CaptureError("capture manifest is missing requested_range")
    taps = manifest.get("taps")
    if not isinstance(taps, list) or not taps:
        raise CaptureError("capture manifest must contain at least one tap")

    seen_tap_ids: set[int] = set()
    for entry in taps:
        if not isinstance(entry, dict):
            raise CaptureError("capture manifest tap entry must be an object")
        tap_id = entry.get("tap_id")
        if isinstance(tap_id, bool) or not isinstance(tap_id, int):
            raise CaptureError("capture manifest tap_id must be an integer")
        if tap_id in seen_tap_ids:
            raise CaptureError(f"capture manifest contains duplicate tap_id: {tap_id}")
        seen_tap_ids.add(tap_id)

        final = entry.get("final")
        if not isinstance(final, dict):
            raise CaptureError(f"capture manifest tap {tap_id} has no finalized artifact")
        if not str(final.get("path") or "").strip():
            raise CaptureError(f"capture manifest tap {tap_id} finalized artifact has no path")
        _normalize_sha256(final.get("sha256"), context=f"capture manifest tap {tap_id} finalized artifact")


def _relative_reference(target: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(target, base)).as_posix()
    except ValueError:
        return str(target)


def _resolve_reference(reference: str, base: Path) -> Path:
    path = Path(reference)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _capture_final_hashes(manifest: dict[str, Any]) -> dict[int, str]:
    _validate_capture_manifest(manifest)
    return {
        int(entry["tap_id"]): _normalize_sha256(
            entry["final"]["sha256"],
            context=f"capture manifest tap {entry['tap_id']} finalized artifact",
        )
        for entry in manifest["taps"]
    }


def _validate_capture_analysis_report(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != CAPTURE_ANALYSIS_SCHEMA_VERSION:
        raise CaptureError(
            f"analysis report must use {CAPTURE_ANALYSIS_SCHEMA_VERSION}"
        )
    expected_experiment = str(manifest.get("experiment_id") or "")
    if str(report.get("experiment_id") or "") != expected_experiment:
        raise CaptureError("analysis report experiment_id does not match bound capture manifest")

    capabilities = report.get("requested_capabilities")
    if (
        not isinstance(capabilities, list)
        or not capabilities
        or any(not isinstance(value, str) or not value.strip() for value in capabilities)
    ):
        raise CaptureError("analysis report requested_capabilities must be a non-empty string list")

    taps = report.get("taps")
    if not isinstance(taps, list) or not taps:
        raise CaptureError("analysis report must contain at least one analyzed tap")

    expected_hashes = _capture_final_hashes(manifest)
    seen: set[int] = set()
    summaries: list[dict[str, Any]] = []
    for entry in taps:
        if not isinstance(entry, dict):
            raise CaptureError("analysis report tap entry must be an object")
        tap_id = entry.get("tap_id")
        if isinstance(tap_id, bool) or not isinstance(tap_id, int):
            raise CaptureError("analysis report tap_id must be an integer")
        if tap_id in seen:
            raise CaptureError(f"analysis report contains duplicate tap_id: {tap_id}")
        seen.add(tap_id)
        if tap_id not in expected_hashes:
            raise CaptureError(f"analysis report tap {tap_id} is not present in bound capture manifest")

        content_sha256 = _normalize_sha256(
            entry.get("content_sha256"),
            context=f"analysis report tap {tap_id} content",
        )
        if content_sha256 != expected_hashes[tap_id]:
            raise CaptureError(f"analysis report tap {tap_id} content SHA-256 does not match bound capture artifact")

        analysis = entry.get("analysis")
        if not isinstance(analysis, dict) or analysis.get("schema_version") != ANALYSIS_REPORT_SCHEMA_VERSION:
            raise CaptureError(
                f"analysis report tap {tap_id} must contain {ANALYSIS_REPORT_SCHEMA_VERSION} evidence"
            )
        inner_sha256 = _normalize_sha256(
            analysis.get("content_sha256"),
            context=f"analysis report tap {tap_id} inner evidence content",
        )
        if inner_sha256 != content_sha256:
            raise CaptureError(f"analysis report tap {tap_id} inner evidence content SHA-256 mismatch")

        analysis_key = analysis.get("analysis_key")
        if analysis_key is not None:
            analysis_key = _normalize_sha256(
                analysis_key,
                context=f"analysis report tap {tap_id} analysis_key",
            )

        summaries.append(
            {
                "tap_id": tap_id,
                "source_label": str(entry.get("source_label") or ""),
                "content_sha256": content_sha256,
                "analysis_key": analysis_key,
            }
        )

    return {
        "schema_version": CAPTURE_ANALYSIS_SCHEMA_VERSION,
        "experiment_id": expected_experiment,
        "requested_capabilities": list(capabilities),
        "taps": summaries,
    }


def _verify_analysis_bindings(
    journal_path: Path,
    journal: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    evidence = journal.get("evidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        raise CaptureError("experiment journal evidence must be an object")
    reports = evidence.get("analysis_reports", [])
    if not isinstance(reports, list):
        raise CaptureError("experiment journal analysis_reports must be a list")

    seen_labels: set[str] = set()
    for binding in reports:
        if not isinstance(binding, dict):
            raise CaptureError("experiment journal analysis report binding must be an object")
        label = str(binding.get("label") or "")
        report_ref = str(binding.get("report_path") or "")
        expected_hash = _normalize_sha256(
            binding.get("report_sha256"),
            context=f"analysis report binding {label or '<unlabeled>'}",
        )
        if not label or not report_ref:
            raise CaptureError("experiment journal analysis report binding is incomplete")
        if label in seen_labels:
            raise CaptureError(f"experiment journal contains duplicate analysis label: {label}")
        seen_labels.add(label)

        report_path = _resolve_reference(report_ref, journal_path.parent)
        if not report_path.is_file():
            raise CaptureError(f"bound analysis report does not exist: {report_path}")
        if _sha256(report_path) != expected_hash:
            raise CaptureError(f"bound analysis report SHA-256 changed: {label}")
        report = _load_json_object(report_path)
        _validate_capture_analysis_report(report, manifest)


def _journal_analysis_hashes(journal: dict[str, Any]) -> set[str]:
    evidence = journal.get("evidence")
    if not isinstance(evidence, dict):
        return set()
    reports = evidence.get("analysis_reports", [])
    if not isinstance(reports, list):
        return set()
    hashes: set[str] = set()
    for binding in reports:
        if not isinstance(binding, dict):
            continue
        taps = binding.get("taps", [])
        if not isinstance(taps, list):
            continue
        for tap in taps:
            if not isinstance(tap, dict):
                continue
            value = tap.get("content_sha256")
            if isinstance(value, str):
                hashes.add(_normalize_sha256(value, context="journal analysis content"))
    return hashes


def _validate_clean_loudness_evaluation(
    report: dict[str, Any],
    *,
    baseline_hashes: set[str],
    candidate_hashes: set[str],
) -> dict[str, Any]:
    if report.get("schema_version") != CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION:
        raise CaptureError(
            f"optimizer evaluation must use {CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION}"
        )
    if report.get("objective") != "clean_loudness":
        raise CaptureError("optimizer evaluation objective must be clean_loudness")
    if report.get("mutation_effect_state") != "NOT_STARTED":
        raise CaptureError(
            "optimizer evaluation must be evidence-only with mutation_effect_state=NOT_STARTED"
        )

    baseline = report.get("baseline")
    candidate = report.get("candidate")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise CaptureError("optimizer evaluation must identify baseline and candidate evidence")
    if baseline.get("schema_version") != ANALYSIS_REPORT_SCHEMA_VERSION:
        raise CaptureError("optimizer baseline must identify an analysis/v1 report")
    if candidate.get("schema_version") != ANALYSIS_REPORT_SCHEMA_VERSION:
        raise CaptureError("optimizer candidate must identify an analysis/v1 report")
    baseline_sha = _normalize_sha256(
        baseline.get("content_sha256"), context="optimizer baseline content"
    )
    candidate_sha = _normalize_sha256(
        candidate.get("content_sha256"), context="optimizer candidate content"
    )
    if baseline_sha not in baseline_hashes:
        raise CaptureError(
            "optimizer baseline audio is not bound to the baseline experiment journal"
        )
    if candidate_sha not in candidate_hashes:
        raise CaptureError(
            "optimizer candidate audio is not bound to the candidate experiment journal"
        )

    decision = report.get("decision")
    if not isinstance(decision, dict):
        raise CaptureError("optimizer evaluation is missing decision state")
    status = str(decision.get("status") or "")
    if status not in {"keep", "reject", "refine", "inconclusive"}:
        raise CaptureError("optimizer evaluation decision status is invalid")
    journal_status = decision.get("journal_status")
    expected_journal_status = status if status in DECISION_STATUSES else None
    if journal_status != expected_journal_status:
        raise CaptureError(
            "optimizer evaluation journal_status is inconsistent with decision status"
        )
    reasons = decision.get("reason_codes")
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(value, str) or not value.strip() for value in reasons)
    ):
        raise CaptureError(
            "optimizer evaluation reason_codes must be a non-empty string list"
        )

    return {
        "schema_version": CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION,
        "objective": "clean_loudness",
        "baseline_content_sha256": baseline_sha,
        "candidate_content_sha256": candidate_sha,
        "decision_status": status,
        "journal_status": journal_status,
        "reason_codes": list(reasons),
    }


def _verify_optimizer_bindings(journal_path: Path, journal: dict[str, Any]) -> None:
    evidence = journal.get("evidence")
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        raise CaptureError("experiment journal evidence must be an object")
    bindings = evidence.get("optimizer_evaluations", [])
    if not isinstance(bindings, list):
        raise CaptureError("experiment journal optimizer_evaluations must be a list")
    if bindings and journal.get("variant_role") != "candidate":
        raise CaptureError("optimizer evaluations may only be bound to candidate journals")

    seen_labels: set[str] = set()
    candidate_hashes = _journal_analysis_hashes(journal)
    for binding in bindings:
        if not isinstance(binding, dict):
            raise CaptureError("optimizer evaluation binding must be an object")
        label = str(binding.get("label") or "")
        report_ref = str(binding.get("report_path") or "")
        baseline_ref = str(binding.get("baseline_journal_path") or "")
        if not label or not report_ref or not baseline_ref:
            raise CaptureError("optimizer evaluation binding is incomplete")
        if label in seen_labels:
            raise CaptureError(f"experiment journal contains duplicate optimizer label: {label}")
        seen_labels.add(label)

        report_path = _resolve_reference(report_ref, journal_path.parent)
        baseline_path = _resolve_reference(baseline_ref, journal_path.parent)
        if report_path.resolve() == journal_path.resolve():
            raise CaptureError("optimizer evaluation report must be separate from the candidate journal")
        if baseline_path.resolve() == journal_path.resolve():
            raise CaptureError("optimizer baseline journal must be separate from the candidate journal")
        if not report_path.is_file():
            raise CaptureError(f"bound optimizer evaluation does not exist: {report_path}")
        expected_report_hash = _normalize_sha256(
            binding.get("report_sha256"),
            context=f"optimizer evaluation binding {label}",
        )
        if _sha256(report_path) != expected_report_hash:
            raise CaptureError(f"bound optimizer evaluation SHA-256 changed: {label}")

        baseline_journal = verify_experiment_journal(baseline_path)
        if baseline_journal.get("variant_role") != "baseline":
            raise CaptureError("optimizer baseline journal must have variant_role=baseline")
        if baseline_journal.get("comparison_id") != journal.get("comparison_id"):
            raise CaptureError("optimizer baseline/candidate journals must share comparison_id")
        baseline_capture = baseline_journal.get("capture")
        candidate_capture = journal.get("capture")
        if not isinstance(baseline_capture, dict) or not isinstance(candidate_capture, dict):
            raise CaptureError("optimizer journal capture lineage is invalid")
        baseline_experiment_id = str(baseline_capture.get("experiment_id") or "")
        if str(journal.get("parent_experiment_id") or "") != baseline_experiment_id:
            raise CaptureError("optimizer candidate parent_experiment_id must match baseline experiment_id")
        lineage = {
            "baseline_experiment_id": baseline_experiment_id,
            "baseline_manifest_sha256": str(baseline_capture.get("manifest_sha256") or ""),
            "candidate_experiment_id": str(candidate_capture.get("experiment_id") or ""),
            "candidate_manifest_sha256": str(candidate_capture.get("manifest_sha256") or ""),
        }
        for key, value in lineage.items():
            if binding.get(key) != value:
                raise CaptureError(f"optimizer evaluation binding lineage changed: {label}.{key}")

        summary = _validate_clean_loudness_evaluation(
            _load_json_object(report_path),
            baseline_hashes=_journal_analysis_hashes(baseline_journal),
            candidate_hashes=candidate_hashes,
        )
        for key in (
            "schema_version",
            "objective",
            "baseline_content_sha256",
            "candidate_content_sha256",
            "decision_status",
            "journal_status",
            "reason_codes",
        ):
            if binding.get(key) != summary[key]:
                raise CaptureError(f"optimizer evaluation binding summary changed: {label}.{key}")


def create_experiment_journal(
    *,
    capture_manifest: str | Path,
    output_path: str | Path,
    comparison_id: str,
    variant_role: str,
    hypothesis: str,
    changes: Iterable[ExperimentChange] = (),
    parent_experiment_id: str | None = None,
    created_at_utc: str | None = None,
) -> Path:
    manifest_path = Path(capture_manifest)
    output = Path(output_path)
    if manifest_path.resolve() == output.resolve():
        raise CaptureError("experiment journal output_path must not overwrite the bound capture manifest")
    manifest = _load_json_object(manifest_path)
    _validate_capture_manifest(manifest)

    role = variant_role.strip().lower()
    if role not in VARIANT_ROLES:
        raise CaptureError(f"variant_role must be one of: {', '.join(sorted(VARIANT_ROLES))}")
    hypothesis_text = hypothesis.strip()
    if not hypothesis_text:
        raise CaptureError("hypothesis must not be empty")

    change_items = list(changes)
    if role == "candidate" and not change_items:
        raise CaptureError("candidate experiment journal requires at least one declared change")

    safe_comparison = _safe_id(comparison_id)
    capture_experiment_id = str(manifest["experiment_id"])
    live_session = manifest.get("live_session") if isinstance(manifest.get("live_session"), dict) else {}
    song = live_session.get("song") if isinstance(live_session.get("song"), dict) else {}

    payload: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "comparison_id": safe_comparison,
        "variant_role": role,
        "capture": {
            "manifest_path": _relative_reference(manifest_path.resolve(), output.parent.resolve()),
            "manifest_sha256": _sha256(manifest_path),
            "experiment_id": capture_experiment_id,
            "requested_range": manifest["requested_range"],
            "set_signature": live_session.get("set_signature"),
            "song": {
                "name": song.get("name"),
                "file_path": song.get("file_path"),
            },
        },
        "hypothesis": hypothesis_text,
        "changes": [item.as_dict() for item in change_items],
        "evidence": {"analysis_reports": []},
        "decision": {
            "status": "pending",
            "history": [],
        },
        "created_at_utc": created_at_utc or _utc_now(),
    }
    if parent_experiment_id is not None:
        parent = parent_experiment_id.strip()
        if not parent:
            raise CaptureError("parent_experiment_id must not be empty when provided")
        payload["parent_experiment_id"] = parent

    return _atomic_write_json(output, payload)


def verify_experiment_journal(path: str | Path) -> dict[str, Any]:
    journal_path = Path(path)
    journal = _load_json_object(journal_path)
    if journal.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise CaptureError("unsupported experiment journal schema_version")
    capture = journal.get("capture")
    if not isinstance(capture, dict):
        raise CaptureError("experiment journal is missing capture binding")
    manifest_ref = str(capture.get("manifest_path") or "")
    expected_hash = str(capture.get("manifest_sha256") or "")
    expected_experiment = str(capture.get("experiment_id") or "")
    if not manifest_ref or not expected_hash or not expected_experiment:
        raise CaptureError("experiment journal capture binding is incomplete")

    manifest_path = _resolve_reference(manifest_ref, journal_path.parent)
    if not manifest_path.is_file():
        raise CaptureError(f"bound capture manifest does not exist: {manifest_path}")
    if _sha256(manifest_path) != expected_hash:
        raise CaptureError("bound capture manifest SHA-256 changed")

    manifest = _load_json_object(manifest_path)
    _validate_capture_manifest(manifest)
    if str(manifest.get("experiment_id")) != expected_experiment:
        raise CaptureError("bound capture manifest experiment_id changed")
    _verify_analysis_bindings(journal_path, journal, manifest)
    _verify_optimizer_bindings(journal_path, journal)
    return journal


def attach_capture_analysis_report(
    path: str | Path,
    *,
    analysis_report: str | Path,
    label: str,
    attached_at_utc: str | None = None,
) -> Path:
    """Bind one persisted capture-analysis result to the journal by exact file/audio identity."""
    journal_path = Path(path)
    journal = verify_experiment_journal(journal_path)
    capture = journal["capture"]
    manifest_path = _resolve_reference(str(capture["manifest_path"]), journal_path.parent)
    manifest = _load_json_object(manifest_path)

    report_path = Path(analysis_report)
    if report_path.resolve() in {journal_path.resolve(), manifest_path.resolve()}:
        raise CaptureError("analysis report must be separate from the journal and capture manifest")
    report = _load_json_object(report_path)
    summary = _validate_capture_analysis_report(report, manifest)

    safe_label = _safe_id(label)
    evidence = journal.get("evidence")
    if evidence is None:
        evidence = {"analysis_reports": []}
        journal["evidence"] = evidence
    if not isinstance(evidence, dict):
        raise CaptureError("experiment journal evidence must be an object")
    reports = evidence.get("analysis_reports")
    if reports is None:
        reports = []
        evidence["analysis_reports"] = reports
    if not isinstance(reports, list):
        raise CaptureError("experiment journal analysis_reports must be a list")
    if any(isinstance(item, dict) and item.get("label") == safe_label for item in reports):
        raise CaptureError(f"analysis report label is already bound: {safe_label}")

    reports.append(
        {
            "label": safe_label,
            "report_path": _relative_reference(report_path.resolve(), journal_path.parent.resolve()),
            "report_sha256": _sha256(report_path),
            "schema_version": summary["schema_version"],
            "experiment_id": summary["experiment_id"],
            "requested_capabilities": summary["requested_capabilities"],
            "taps": summary["taps"],
            "attached_at_utc": attached_at_utc or _utc_now(),
        }
    )
    return _atomic_write_json(journal_path, journal)


def attach_clean_loudness_evaluation(
    path: str | Path,
    *,
    baseline_journal: str | Path,
    evaluation_report: str | Path,
    label: str,
    attached_at_utc: str | None = None,
) -> Path:
    """Bind one evidence-only clean-loudness evaluation to exact baseline/candidate evidence."""
    journal_path = Path(path)
    journal = verify_experiment_journal(journal_path)
    if journal.get("variant_role") != "candidate":
        raise CaptureError("optimizer evaluation may only be attached to a candidate journal")

    baseline_path = Path(baseline_journal)
    if baseline_path.resolve() == journal_path.resolve():
        raise CaptureError("optimizer baseline journal must be separate from the candidate journal")
    baseline = verify_experiment_journal(baseline_path)
    if baseline.get("variant_role") != "baseline":
        raise CaptureError("optimizer baseline journal must have variant_role=baseline")
    if baseline.get("comparison_id") != journal.get("comparison_id"):
        raise CaptureError("optimizer baseline/candidate journals must share comparison_id")
    baseline_capture = baseline.get("capture")
    candidate_capture = journal.get("capture")
    if not isinstance(baseline_capture, dict) or not isinstance(candidate_capture, dict):
        raise CaptureError("optimizer journal capture lineage is invalid")
    baseline_experiment_id = str(baseline_capture.get("experiment_id") or "")
    if str(journal.get("parent_experiment_id") or "") != baseline_experiment_id:
        raise CaptureError("optimizer candidate parent_experiment_id must match baseline experiment_id")

    report_path = Path(evaluation_report)
    if report_path.resolve() in {journal_path.resolve(), baseline_path.resolve()}:
        raise CaptureError("optimizer evaluation report must be separate from both journals")
    report = _load_json_object(report_path)
    summary = _validate_clean_loudness_evaluation(
        report,
        baseline_hashes=_journal_analysis_hashes(baseline),
        candidate_hashes=_journal_analysis_hashes(journal),
    )

    safe_label = _safe_id(label)
    evidence = journal.get("evidence")
    if evidence is None:
        evidence = {"analysis_reports": []}
        journal["evidence"] = evidence
    if not isinstance(evidence, dict):
        raise CaptureError("experiment journal evidence must be an object")
    bindings = evidence.get("optimizer_evaluations")
    if bindings is None:
        bindings = []
        evidence["optimizer_evaluations"] = bindings
    if not isinstance(bindings, list):
        raise CaptureError("experiment journal optimizer_evaluations must be a list")
    if any(isinstance(item, dict) and item.get("label") == safe_label for item in bindings):
        raise CaptureError(f"optimizer evaluation label is already bound: {safe_label}")

    bindings.append(
        {
            "label": safe_label,
            "report_path": _relative_reference(report_path.resolve(), journal_path.parent.resolve()),
            "report_sha256": _sha256(report_path),
            "baseline_journal_path": _relative_reference(baseline_path.resolve(), journal_path.parent.resolve()),
            "baseline_experiment_id": baseline_experiment_id,
            "baseline_manifest_sha256": str(baseline_capture.get("manifest_sha256") or ""),
            "candidate_experiment_id": str(candidate_capture.get("experiment_id") or ""),
            "candidate_manifest_sha256": str(candidate_capture.get("manifest_sha256") or ""),
            **summary,
            "attached_at_utc": attached_at_utc or _utc_now(),
        }
    )
    return _atomic_write_json(journal_path, journal)


def append_experiment_decision(
    path: str | Path,
    *,
    status: str,
    note: str | None = None,
    recorded_at_utc: str | None = None,
) -> Path:
    journal_path = Path(path)
    journal = verify_experiment_journal(journal_path)
    decision_status = status.strip().lower()
    if decision_status not in DECISION_STATUSES:
        raise CaptureError(f"decision status must be one of: {', '.join(sorted(DECISION_STATUSES))}")

    decision = journal.get("decision")
    if not isinstance(decision, dict):
        raise CaptureError("experiment journal is missing decision state")
    history = decision.get("history")
    if not isinstance(history, list):
        raise CaptureError("experiment journal decision history is invalid")

    event: dict[str, Any] = {
        "status": decision_status,
        "recorded_at_utc": recorded_at_utc or _utc_now(),
    }
    if note is not None:
        note_text = note.strip()
        if not note_text:
            raise CaptureError("decision note must not be empty when provided")
        event["note"] = note_text
    history.append(event)
    decision["status"] = decision_status
    return _atomic_write_json(journal_path, journal)
