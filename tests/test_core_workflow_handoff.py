from __future__ import annotations

import json

import pytest

from chibi_audio.core_workflow_handoff import (
    CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION,
    CoreWorkflowHandoffError,
    acquire_live_mutation_lease,
    attach_specialist_child,
    build_core_workflow_handoff,
    persist_core_workflow_handoff,
    release_live_mutation_lease,
)
from chibi_audio.workflow_commands import build_workflow_command


def _context():
    def track(index, track_id, name, role):
        return {
            "track_id": str(track_id),
            "index": index,
            "type": "GroupTrack" if name != "SIDECHAIN" else "MidiTrack",
            "name": name,
            "group_id": "-1",
            "root_group_id": str(track_id) if name != "SIDECHAIN" else None,
            "root_group_name": name if name != "SIDECHAIN" else None,
            "root_role": role,
            "semantic_role": role,
            "role_confidence": 0.98,
            "role_reason": "fixture",
            "activity": {
                "span_count": 0,
                "first_active_beat": None,
                "last_active_beat": None,
                "active_duration_beats": 0.0,
                "spans": [],
            },
            "device_count": 0,
            "current_color_index": 3,
            "color_role": role,
            "height_class": "tall",
            "order_key": [index],
        }

    return {
        "schema_version": "chibi-audio-project-context/v1",
        "effect_state": "NOT_STARTED",
        "mode": "plan",
        "source_set": {"path": "C:/Lab/KISS.als", "track_count": 3},
        "organization_schema": {
            "path": "PROJECT_ORGANIZATION.md",
            "sha256": "a" * 64,
            "version": 1,
        },
        "tracks": [
            track(0, 10, "BASS", "bass"),
            track(1, 20, "SIDECHAIN", "sidechain"),
            track(2, 30, "DRUMS", "drums"),
        ],
        "unresolved": [],
        "presentation_plan": {
            "concrete_edits": [],
            "naming_intents": [],
            "color_intents": [],
            "height_intents": [],
        },
        "structural_plan": {
            "current_top_level_order": [],
            "top_level_order": [],
            "drum_order": [],
            "reorder_required": False,
            "routing_equivalence_required": False,
            "blockers": [],
            "execution_state": "NO_STRUCTURAL_CHANGE_NEEDED",
        },
    }


def _command(intent, workflow_id, *, parent=None, context=None):
    return build_workflow_command(
        context or _context(),
        intent=intent,
        project_ref="kiss-lab",
        workflow_id=workflow_id,
        parent_workflow_id=parent,
        goal=f"Plan {intent}",
        mode="bounded_wave",
        set_signature="sig-kiss",
        budget={"max_mutations": 1, "max_renders": 2, "max_child_jobs": 2},
    )


def test_core_handoff_records_real_enrollment_boundary_without_claiming_authority():
    handoff = build_core_workflow_handoff(
        _command("mix", "mix-1"),
        enrollment_state="PENDING_CORE_PROJECT",
        enrollment_blocker="No configured Chibi Core audio project is exposed by the bounded adapter.",
    )

    assert handoff["schema_version"] == CORE_WORKFLOW_HANDOFF_SCHEMA_VERSION
    assert handoff["desired_authority"] == "chibi_core"
    assert handoff["core_enrollment"]["state"] == "PENDING_CORE_PROJECT"
    assert handoff["stop_reason"] == "core_project_enrollment_required"
    assert handoff["effect_certainty"] == "NOT_STARTED"
    assert handoff["serialized_live_executor"]["required"] is True


def test_mix_can_attach_sidechain_child_with_same_exact_project_identity():
    parent = _command("mix", "mix-1")
    child = _command("sidechain", "sidechain-1", parent="mix-1")
    handoff = attach_specialist_child(
        build_core_workflow_handoff(parent),
        child,
    )

    assert len(handoff["children"]) == 1
    row = handoff["children"][0]
    assert row["workflow_id"] == "sidechain-1"
    assert row["intent"] == "sidechain"
    assert row["live_mutation_authorized"] is False
    assert (
        row["command"]["project_identity"]
        == handoff["parent"]["command"]["project_identity"]
    )


def test_child_with_different_context_identity_is_rejected():
    parent = _command("mix", "mix-1")
    other = _context()
    other["tracks"][0]["semantic_role"] = "custom-low-end"
    child = _command(
        "sidechain",
        "sidechain-1",
        parent="mix-1",
        context=other,
    )

    with pytest.raises(CoreWorkflowHandoffError, match="project identity"):
        attach_specialist_child(build_core_workflow_handoff(parent), child)


def test_serialized_live_mutation_lease_rejects_concurrent_owner():
    handoff = attach_specialist_child(
        build_core_workflow_handoff(_command("mix", "mix-1")),
        _command("sidechain", "sidechain-1", parent="mix-1"),
    )
    leased = acquire_live_mutation_lease(
        handoff,
        workflow_id="sidechain-1",
        lease_id="lease-sidechain-1",
    )

    assert leased["serialized_live_executor"]["active_lease"] == {
        "lease_id": "lease-sidechain-1",
        "workflow_id": "sidechain-1",
    }
    with pytest.raises(CoreWorkflowHandoffError, match="already owns"):
        acquire_live_mutation_lease(
            leased,
            workflow_id="mix-1",
            lease_id="lease-mix-1",
        )


def test_release_records_effect_certainty_and_allows_next_serialized_owner():
    handoff = attach_specialist_child(
        build_core_workflow_handoff(_command("mix", "mix-1")),
        _command("master", "master-1", parent="mix-1"),
    )
    leased = acquire_live_mutation_lease(
        handoff,
        workflow_id="master-1",
        lease_id="lease-master-1",
    )
    released = release_live_mutation_lease(
        leased,
        lease_id="lease-master-1",
        effect_certainty="STARTED_CONFIRMED",
        evidence_refs=["capture:drop-1"],
    )
    next_lease = acquire_live_mutation_lease(
        released,
        workflow_id="mix-1",
        lease_id="lease-mix-2",
    )

    history = next_lease["serialized_live_executor"]["lease_history"]
    assert history == [
        {
            "lease_id": "lease-master-1",
            "workflow_id": "master-1",
            "effect_certainty": "STARTED_CONFIRMED",
            "evidence_refs": ["capture:drop-1"],
        }
    ]
    assert next_lease["effect_certainty"] == "STARTED_CONFIRMED"
    assert next_lease["serialized_live_executor"]["active_lease"]["workflow_id"] == "mix-1"


def test_core_handoff_persists_atomically(tmp_path):
    handoff = attach_specialist_child(
        build_core_workflow_handoff(_command("mix", "mix-1")),
        _command("sidechain", "sidechain-1", parent="mix-1"),
    )
    path = tmp_path / "core-handoff.json"

    written = persist_core_workflow_handoff(path, handoff)

    assert written == path.resolve()
    assert json.loads(path.read_text(encoding="utf-8")) == handoff
    assert not path.with_suffix(".json.tmp").exists()


def test_enrolled_handoff_cannot_retain_enrollment_blocker():
    with pytest.raises(CoreWorkflowHandoffError, match="cannot retain"):
        build_core_workflow_handoff(
            _command("mix", "mix-1"),
            enrollment_state="ENROLLED",
            enrollment_blocker="stale blocker",
        )
