from __future__ import annotations

import json

import pytest

from chibi_audio.workflow_commands import (
    WORKFLOW_COMMAND_SCHEMA_VERSION,
    WORKFLOW_RESULT_SCHEMA_VERSION,
    WorkflowCommandError,
    build_workflow_command,
    build_workflow_result,
    intent_context_view,
    load_project_context,
    project_context_identity,
)


def _track(
    index,
    track_id,
    name,
    *,
    kind="AudioTrack",
    group_id="-1",
    root_group_id=None,
    root_group_name=None,
    root_role=None,
    semantic_role="unclassified",
    confidence=0.9,
):
    return {
        "track_id": str(track_id),
        "index": index,
        "type": kind,
        "name": name,
        "group_id": str(group_id),
        "root_group_id": root_group_id,
        "root_group_name": root_group_name,
        "root_role": root_role,
        "semantic_role": semantic_role,
        "role_confidence": confidence,
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
        "color_role": semantic_role,
        "height_class": "medium",
        "order_key": [index],
    }


def _context():
    return {
        "schema_version": "chibi-audio-project-context/v1",
        "effect_state": "NOT_STARTED",
        "mode": "plan",
        "source_set": {
            "path": "C:/Lab/KISS.als",
            "track_count": 6,
        },
        "organization_schema": {
            "path": "PROJECT_ORGANIZATION.md",
            "sha256": "a" * 64,
            "version": 1,
        },
        "tracks": [
            _track(0, 10, "VOX", kind="GroupTrack", semantic_role="vox", root_role="vox"),
            _track(
                1,
                11,
                "LEAD",
                group_id="10",
                root_group_id="10",
                root_group_name="VOX",
                root_role="vox",
                semantic_role="vox",
            ),
            _track(2, 20, "BASS", kind="GroupTrack", semantic_role="bass", root_role="bass"),
            _track(
                3,
                21,
                "SUB",
                group_id="20",
                root_group_id="20",
                root_group_name="BASS",
                root_role="bass",
                semantic_role="bass",
            ),
            _track(4, 30, "SIDECHAIN", semantic_role="sidechain", root_role="sidechain"),
            _track(5, 40, "DRUMS", kind="GroupTrack", semantic_role="drums", root_role="drums"),
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


def test_load_project_context_validates_durable_context(tmp_path):
    path = tmp_path / "context.json"
    path.write_text(json.dumps(_context()), encoding="utf-8")

    loaded = load_project_context(path)

    assert loaded["source_set"]["path"] == "C:/Lab/KISS.als"
    identity = project_context_identity(loaded)
    assert identity["schema_version"] == "chibi-audio-project-context/v1"
    assert len(identity["content_sha256"]) == 64
    assert identity["source_set_track_count"] == 6


def test_mix_context_view_uses_persisted_roles_without_rescanning():
    context = _context()
    context["tracks"][2]["semantic_role"] = "artist_custom_low_end"

    view = intent_context_view(context, "mix")

    assert view["source"] == "persisted_project_context"
    assert "artist_custom_low_end" in view["roles"]
    assert [item["name"] for item in view["roles"]["artist_custom_low_end"]] == ["BASS"]
    assert [item["name"] for item in view["top_level_buses"]] == [
        "VOX",
        "BASS",
        "SIDECHAIN",
        "DRUMS",
    ]


def test_sidechain_context_view_uses_persisted_trigger_and_target_roles():
    view = intent_context_view(_context(), "sidechain")

    assert [item["name"] for item in view["trigger_candidates"]] == ["SIDECHAIN"]
    assert [item["name"] for item in view["target_bus_candidates"]] == [
        "VOX",
        "BASS",
        "DRUMS",
    ]


def test_master_context_view_reuses_top_level_bus_context():
    view = intent_context_view(_context(), "master")

    assert [item["name"] for item in view["major_buses"]] == [
        "VOX",
        "BASS",
        "SIDECHAIN",
        "DRUMS",
    ]
    assert view["role_counts"]["bass"] == 2
    assert view["organization_structural_state"] == "NO_STRUCTURAL_CHANGE_NEEDED"


def test_workflow_command_has_one_stable_envelope_for_all_intents():
    context = _context()
    for intent in ("organize", "mix", "sidechain", "master"):
        command = build_workflow_command(
            context,
            intent=intent,
            project_ref="kiss-lab",
            workflow_id=f"wf-{intent}",
            parent_workflow_id=None,
            goal=f"Plan {intent}",
            mode="plan",
            guardrails={"no_gui_fallback": True},
            budget={"max_mutations": 0, "max_renders": 2, "max_child_jobs": 4},
            set_signature="sig-kiss",
        )

        assert command["schema_version"] == WORKFLOW_COMMAND_SCHEMA_VERSION
        assert command["intent"] == intent
        assert command["effect_certainty"] == "NOT_STARTED"
        assert command["project_identity"]["set_signature"] == "sig-kiss"
        assert command["project_identity"]["project_context"]["content_sha256"]
        assert command["context_view"]["source"] == "persisted_project_context"
        assert command["child_jobs"] == []
        assert command["applied_changes"] == []
        assert command["rollback_provenance"] == []


def test_child_workflow_preserves_parent_link_and_context_identity():
    context = _context()
    parent = build_workflow_command(
        context,
        intent="mix",
        project_ref="kiss-lab",
        workflow_id="mix-1",
        goal="Improve the mix",
    )
    child = build_workflow_command(
        context,
        intent="sidechain",
        project_ref="kiss-lab",
        workflow_id="sidechain-1",
        parent_workflow_id=parent["workflow_id"],
        goal="Audit kick-to-bass ducking",
    )

    assert child["parent_workflow_id"] == "mix-1"
    assert (
        child["project_identity"]["project_context"]["content_sha256"]
        == parent["project_identity"]["project_context"]["content_sha256"]
    )


def test_workflow_result_preserves_identity_and_effect_certainty():
    command = build_workflow_command(
        _context(),
        intent="master",
        project_ref="kiss-lab",
        workflow_id="master-1",
        goal="Find clean loudness knee",
    )

    result = build_workflow_result(
        command,
        status="blocked",
        stop_reason="artist_decision_required",
        child_jobs=[{"workflow_id": "analysis-1", "status": "done"}],
        evidence_refs=["capture:drop-1"],
        artist_decision_required=True,
    )

    assert result["schema_version"] == WORKFLOW_RESULT_SCHEMA_VERSION
    assert result["workflow_id"] == "master-1"
    assert result["effect_certainty"] == "NOT_STARTED"
    assert result["project_identity"] == command["project_identity"]
    assert result["best_so_far"]["evidence_refs"] == ["capture:drop-1"]
    assert result["artist_decision_required"] is True


def test_workflow_contract_fails_closed_on_invalid_context_or_budget(tmp_path):
    bad = _context()
    bad["schema_version"] = "wrong"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(WorkflowCommandError, match="schema_version"):
        load_project_context(path)

    with pytest.raises(WorkflowCommandError, match="max_mutations"):
        build_workflow_command(
            _context(),
            intent="mix",
            project_ref="kiss",
            workflow_id="mix-1",
            goal="Mix",
            budget={"max_mutations": -1},
        )
