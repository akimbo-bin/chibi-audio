from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .workflow_commands import WORKFLOW_COMMAND_SCHEMA_VERSION


CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION = "chibi-audio-core-workflow-handoff/v1"


class CoreWorkflowHandoffError(ValueError):
    pass


def _validate_command(command: dict[str, Any]) -> None:
    if command.get("schema_version") != WORKFLOW_COMMAND_SCHEMA_VERSION:
        raise CoreWorkflowHandoffError("workflow command schema is invalid")
    if not str(command.get("workflow_id") or "").strip():
        raise CoreWorkflowHandoffError("workflow command requires workflow_id")
    if not str(command.get("project_ref") or "").strip():
        raise CoreWorkflowHandoffError("workflow command requires project_ref")
    project_identity = command.get("project_identity")
    if not isinstance(project_identity, dict):
        raise CoreWorkflowHandoffError("workflow command requires project_identity")
    context = project_identity.get("project_context")
    if not isinstance(context, dict) or not str(context.get("content_sha256") or ""):
        raise CoreWorkflowHandoffError(
            "workflow command requires project-context content identity"
        )


def build_core_workflow_handoff(
    parent_command: dict[str, Any],
    *,
    enrollment_state: str = "PENDING_CORE_PROJECT",
    enrollment_blocker: str | None = None,
) -> dict[str, Any]:
    _validate_command(parent_command)
    if parent_command.get("intent") != "mix":
        raise CoreWorkflowHandoffError("Core parent workflow must use intent='mix'")
    if parent_command.get("parent_workflow_id") is not None:
        raise CoreWorkflowHandoffError("Core parent workflow cannot itself have a parent")
    if enrollment_state not in {"PENDING_CORE_PROJECT", "ENROLLED"}:
        raise CoreWorkflowHandoffError(
            "enrollment_state must be PENDING_CORE_PROJECT or ENROLLED"
        )
    if enrollment_state == "ENROLLED" and enrollment_blocker:
        raise CoreWorkflowHandoffError(
            "an enrolled Core handoff cannot retain an enrollment blocker"
        )

    return {
        "schema_version": CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION,
        "desired_authority": "chibi_core",
        "core_enrollment": {
            "state": enrollment_state,
            "blocker": enrollment_blocker,
        },
        "project_ref": parent_command["project_ref"],
        "project_identity": copy.deepcopy(parent_command["project_identity"]),
        "parent": {
            "workflow_id": parent_command["workflow_id"],
            "intent": "mix",
            "status": "PLANNED",
            "command": copy.deepcopy(parent_command),
        },
        "children": [],
        "serialized_live_executor": {
            "required": True,
            "active_lease": None,
            "lease_history": [],
        },
        "effect_certainty": "NOT_STARTED",
        "best_so_far": {
            "checkpoint_ref": None,
            "evidence_refs": [],
        },
        "stop_reason": (
            "core_project_enrollment_required"
            if enrollment_state == "PENDING_CORE_PROJECT"
            else None
        ),
    }


def attach_specialist_child(
    handoff: dict[str, Any],
    child_command: dict[str, Any],
) -> dict[str, Any]:
    _validate_command(child_command)
    if handoff.get("schema_version") != CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION:
        raise CoreWorkflowHandoffError("Core handoff schema is invalid")
    if child_command.get("intent") not in {"sidechain", "master"}:
        raise CoreWorkflowHandoffError(
            "Core mix child must use sidechain or master intent"
        )
    parent = handoff.get("parent") or {}
    parent_workflow_id = str(parent.get("workflow_id") or "")
    if child_command.get("parent_workflow_id") != parent_workflow_id:
        raise CoreWorkflowHandoffError(
            "child parent_workflow_id must match Core parent workflow_id"
        )
    if child_command.get("project_ref") != handoff.get("project_ref"):
        raise CoreWorkflowHandoffError(
            "child project_ref must match Core parent project_ref"
        )
    if child_command.get("project_identity") != handoff.get("project_identity"):
        raise CoreWorkflowHandoffError(
            "child project identity must exactly match Core parent identity"
        )
    existing = {
        str(item.get("workflow_id"))
        for item in handoff.get("children") or []
    }
    workflow_id = str(child_command["workflow_id"])
    if workflow_id in existing:
        raise CoreWorkflowHandoffError(
            f"duplicate specialist child workflow_id: {workflow_id}"
        )

    result = copy.deepcopy(handoff)
    result["children"].append(
        {
            "workflow_id": workflow_id,
            "intent": child_command["intent"],
            "status": "PLANNED",
            "live_mutation_authorized": False,
            "command": copy.deepcopy(child_command),
        }
    )
    return result


def acquire_live_mutation_lease(
    handoff: dict[str, Any],
    *,
    workflow_id: str,
    lease_id: str,
) -> dict[str, Any]:
    if handoff.get("schema_version") != CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION:
        raise CoreWorkflowHandoffError("Core handoff schema is invalid")
    if not str(workflow_id).strip() or not str(lease_id).strip():
        raise CoreWorkflowHandoffError("workflow_id and lease_id must not be empty")
    executor = handoff.get("serialized_live_executor")
    if not isinstance(executor, dict) or executor.get("required") is not True:
        raise CoreWorkflowHandoffError("serialized Live executor contract is missing")
    if executor.get("active_lease") is not None:
        raise CoreWorkflowHandoffError(
            "another workflow already owns the serialized Live mutation lease"
        )

    known = {str((handoff.get("parent") or {}).get("workflow_id") or "")}
    known.update(
        str(item.get("workflow_id") or "")
        for item in handoff.get("children") or []
    )
    if workflow_id not in known:
        raise CoreWorkflowHandoffError(
            "mutation lease workflow_id is not the parent or a registered child"
        )

    result = copy.deepcopy(handoff)
    result["serialized_live_executor"]["active_lease"] = {
        "lease_id": lease_id,
        "workflow_id": workflow_id,
    }
    return result


def release_live_mutation_lease(
    handoff: dict[str, Any],
    *,
    lease_id: str,
    effect_certainty: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if effect_certainty not in {"NOT_STARTED", "STARTED_CONFIRMED", "UNKNOWN"}:
        raise CoreWorkflowHandoffError("invalid effect certainty")
    executor = handoff.get("serialized_live_executor")
    if not isinstance(executor, dict):
        raise CoreWorkflowHandoffError("serialized Live executor contract is missing")
    active = executor.get("active_lease")
    if not isinstance(active, dict) or active.get("lease_id") != lease_id:
        raise CoreWorkflowHandoffError("active mutation lease does not match lease_id")

    result = copy.deepcopy(handoff)
    result["serialized_live_executor"]["active_lease"] = None
    result["serialized_live_executor"]["lease_history"].append(
        {
            "lease_id": lease_id,
            "workflow_id": active["workflow_id"],
            "effect_certainty": effect_certainty,
            "evidence_refs": list(evidence_refs or []),
        }
    )
    result["effect_certainty"] = effect_certainty
    return result


def persist_core_workflow_handoff(
    path: str | Path,
    handoff: dict[str, Any],
) -> Path:
    if handoff.get("schema_version") != CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION:
        raise CoreWorkflowHandoffError("Core handoff schema is invalid")
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(target)
    return target
