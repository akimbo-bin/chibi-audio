from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .capture import CaptureError, _safe_id


JOURNAL_SCHEMA_VERSION = 1
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
            json.dumps(self.before)
            json.dumps(self.after)
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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def _validate_capture_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise CaptureError("experiment journal currently requires capture manifest schema_version=1")
    if not str(manifest.get("experiment_id") or "").strip():
        raise CaptureError("capture manifest is missing experiment_id")
    if not isinstance(manifest.get("requested_range"), dict):
        raise CaptureError("capture manifest is missing requested_range")
    if not isinstance(manifest.get("taps"), list) or not manifest["taps"]:
        raise CaptureError("capture manifest must contain at least one tap")


def _relative_reference(target: Path, base: Path) -> str:
    try:
        return Path(os.path.relpath(target, base)).as_posix()
    except ValueError:
        return str(target)


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

    manifest_path = Path(manifest_ref)
    if not manifest_path.is_absolute():
        manifest_path = journal_path.parent / manifest_path
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise CaptureError(f"bound capture manifest does not exist: {manifest_path}")
    if _sha256(manifest_path) != expected_hash:
        raise CaptureError("bound capture manifest SHA-256 changed")

    manifest = _load_json_object(manifest_path)
    _validate_capture_manifest(manifest)
    if str(manifest.get("experiment_id")) != expected_experiment:
        raise CaptureError("bound capture manifest experiment_id changed")
    return journal


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
