from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .organization import ORGANIZATION_CONTEXT_SCHEMA_VERSION


WORKFLOW_COMMAND_SCHEMA_VERSION = "chibi-audio-workflow-command/v1"
WORKFLOW_RESULT_SCHEMA_VERSION = "chibi-audio-workflow-result/v1"
WORKFLOW_INTENTS = frozenset({"organize", "mix", "sidechain", "master"})
WORKFLOW_MODES = frozenset({"plan", "bounded_wave", "run_until_boundary"})
EFFECT_CERTAINTY_STATES = frozenset({"NOT_STARTED", "STARTED_CONFIRMED", "UNKNOWN"})


class WorkflowCommandError(ValueError):
    pass


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_project_context(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowCommandError(f"could not read project context: {source}") from exc
    if not isinstance(payload, dict):
        raise WorkflowCommandError("project context must contain a JSON object")
    validate_project_context(payload)
    return payload


def validate_project_context(context: dict[str, Any]) -> None:
    if context.get("schema_version") != ORGANIZATION_CONTEXT_SCHEMA_VERSION:
        raise WorkflowCommandError(
            "project context schema_version must be "
            f"{ORGANIZATION_CONTEXT_SCHEMA_VERSION!r}"
        )
    tracks = context.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise WorkflowCommandError("project context requires a non-empty tracks list")
    seen_ids: set[str] = set()
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise WorkflowCommandError(f"project context track {index} must be an object")
        track_id = str(track.get("track_id") or "")
        name = str(track.get("name") or "")
        if not track_id:
            raise WorkflowCommandError(f"project context track {index} has no track_id")
        if track_id in seen_ids:
            raise WorkflowCommandError(f"project context has duplicate track_id: {track_id}")
        if not name:
            raise WorkflowCommandError(f"project context track {track_id} has no name")
        seen_ids.add(track_id)
    presentation = context.get("presentation_plan")
    structural = context.get("structural_plan")
    if not isinstance(presentation, dict):
        raise WorkflowCommandError("project context requires presentation_plan")
    if not isinstance(structural, dict):
        raise WorkflowCommandError("project context requires structural_plan")


def project_context_identity(context: dict[str, Any]) -> dict[str, Any]:
    validate_project_context(context)
    source_set = context.get("source_set") or {}
    organization_schema = context.get("organization_schema") or {}
    return {
        "schema_version": context["schema_version"],
        "content_sha256": _canonical_sha256(context),
        "source_set_path": source_set.get("path"),
        "source_set_track_count": source_set.get("track_count"),
        "organization_schema_sha256": organization_schema.get("sha256"),
    }


def _track_ref(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "track_id": str(track["track_id"]),
        "index": int(track.get("index", 0)),
        "name": str(track["name"]),
        "type": track.get("type"),
        "group_id": track.get("group_id"),
        "root_group_id": track.get("root_group_id"),
        "root_group_name": track.get("root_group_name"),
        "root_role": track.get("root_role"),
        "semantic_role": track.get("semantic_role"),
        "role_confidence": track.get("role_confidence"),
        "activity": track.get("activity") or {},
        "device_count": int(track.get("device_count") or 0),
    }


def _top_level_tracks(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for track in context["tracks"]:
        if str(track.get("group_id")) not in {"-1", "None", ""}:
            continue
        if track.get("type") == "ReturnTrack":
            continue
        rows.append(_track_ref(track))
    rows.sort(key=lambda item: item["index"])
    return rows


def _roles(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in context["tracks"]:
        role = str(raw.get("semantic_role") or "unclassified")
        grouped.setdefault(role, []).append(_track_ref(raw))
    for rows in grouped.values():
        rows.sort(key=lambda item: item["index"])
    return dict(sorted(grouped.items()))


def intent_context_view(
    context: dict[str, Any],
    intent: str,
) -> dict[str, Any]:
    validate_project_context(context)
    if intent not in WORKFLOW_INTENTS:
        raise WorkflowCommandError(f"unsupported workflow intent: {intent}")

    tracks = [_track_ref(item) for item in context["tracks"]]
    unresolved = list(context.get("unresolved") or [])
    top_level = _top_level_tracks(context)
    roles = _roles(context)

    common = {
        "source": "persisted_project_context",
        "context_schema_version": context["schema_version"],
        "track_count": len(tracks),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }

    if intent == "organize":
        return {
            **common,
            "presentation_plan": context.get("presentation_plan") or {},
            "structural_plan": context.get("structural_plan") or {},
        }

    if intent == "mix":
        return {
            **common,
            "top_level_buses": top_level,
            "roles": roles,
            "structural_blockers": list(
                (context.get("structural_plan") or {}).get("blockers") or []
            ),
        }

    if intent == "sidechain":
        triggers = [
            item
            for item in tracks
            if item.get("root_role") == "sidechain"
            or item.get("semantic_role") == "sidechain"
        ]
        targets = [
            item
            for item in top_level
            if item.get("semantic_role") not in {"sidechain", "unclassified"}
        ]
        return {
            **common,
            "trigger_candidates": triggers,
            "target_bus_candidates": targets,
            "roles": roles,
        }

    return {
        **common,
        "major_buses": top_level,
        "role_counts": {
            role: len(items)
            for role, items in roles.items()
        },
        "organization_structural_state": (
            context.get("structural_plan") or {}
        ).get("execution_state"),
    }


def _normalize_goal(goal: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(goal, str):
        value = goal.strip()
        if not value:
            raise WorkflowCommandError("goal must not be empty")
        return {"summary": value}
    if isinstance(goal, dict) and goal:
        return dict(goal)
    raise WorkflowCommandError("goal must be a non-empty string or object")


def _normalize_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(budget or {})
    for key in ("max_mutations", "max_renders", "max_child_jobs"):
        if key not in value:
            continue
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise WorkflowCommandError(f"{key} must be an integer >= 0")
    return value


def build_workflow_command(
    context: dict[str, Any],
    *,
    intent: str,
    project_ref: str,
    workflow_id: str,
    goal: str | dict[str, Any],
    mode: str = "plan",
    guardrails: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    set_signature: str | None = None,
    parent_workflow_id: str | None = None,
) -> dict[str, Any]:
    validate_project_context(context)
    if intent not in WORKFLOW_INTENTS:
        raise WorkflowCommandError(f"unsupported workflow intent: {intent}")
    if mode not in WORKFLOW_MODES:
        raise WorkflowCommandError(f"unsupported workflow mode: {mode}")
    if not str(project_ref).strip():
        raise WorkflowCommandError("project_ref must not be empty")
    if not str(workflow_id).strip():
        raise WorkflowCommandError("workflow_id must not be empty")
    if parent_workflow_id is not None and not str(parent_workflow_id).strip():
        raise WorkflowCommandError("parent_workflow_id must be non-empty when provided")
    if set_signature is not None and not str(set_signature).strip():
        raise WorkflowCommandError("set_signature must be non-empty when provided")

    identity = project_context_identity(context)
    return {
        "schema_version": WORKFLOW_COMMAND_SCHEMA_VERSION,
        "intent": intent,
        "project_ref": str(project_ref),
        "workflow_id": str(workflow_id),
        "parent_workflow_id": (
            None if parent_workflow_id is None else str(parent_workflow_id)
        ),
        "goal": _normalize_goal(goal),
        "guardrails": dict(guardrails or {}),
        "mode": mode,
        "project_identity": {
            "set_signature": set_signature,
            "project_context": identity,
        },
        "budget": _normalize_budget(budget),
        "effect_certainty": "NOT_STARTED",
        "best_so_far": {
            "checkpoint_ref": None,
            "evidence_refs": [],
        },
        "child_jobs": [],
        "applied_changes": [],
        "rejected_changes": [],
        "rollback_provenance": [],
        "stop_reason": None,
        "artist_decision_required": False,
        "context_view": intent_context_view(context, intent),
    }


def build_workflow_result(
    command: dict[str, Any],
    *,
    status: str,
    effect_certainty: str = "NOT_STARTED",
    stop_reason: str | None = None,
    child_jobs: list[dict[str, Any]] | None = None,
    applied_changes: list[dict[str, Any]] | None = None,
    rejected_changes: list[dict[str, Any]] | None = None,
    rollback_provenance: list[dict[str, Any]] | None = None,
    evidence_refs: list[str] | None = None,
    checkpoint_ref: str | None = None,
    artist_decision_required: bool = False,
) -> dict[str, Any]:
    if command.get("schema_version") != WORKFLOW_COMMAND_SCHEMA_VERSION:
        raise WorkflowCommandError("result requires a valid workflow command")
    if not str(status).strip():
        raise WorkflowCommandError("result status must not be empty")
    if effect_certainty not in EFFECT_CERTAINTY_STATES:
        raise WorkflowCommandError(
            f"unsupported effect certainty: {effect_certainty}"
        )
    return {
        "schema_version": WORKFLOW_RESULT_SCHEMA_VERSION,
        "intent": command["intent"],
        "project_ref": command["project_ref"],
        "workflow_id": command["workflow_id"],
        "parent_workflow_id": command.get("parent_workflow_id"),
        "status": str(status),
        "mode": command["mode"],
        "project_identity": command["project_identity"],
        "effect_certainty": effect_certainty,
        "best_so_far": {
            "checkpoint_ref": checkpoint_ref,
            "evidence_refs": list(evidence_refs or []),
        },
        "child_jobs": list(child_jobs or []),
        "applied_changes": list(applied_changes or []),
        "rejected_changes": list(rejected_changes or []),
        "rollback_provenance": list(rollback_provenance or []),
        "stop_reason": stop_reason,
        "artist_decision_required": bool(artist_decision_required),
    }
