from __future__ import annotations

import json
from pathlib import Path

from chibi_audio.organization import (
    build_project_context,
    load_organization_schema,
    write_project_context,
)


SCHEMA_PATH = Path(__file__).parents[1] / "PROJECT_ORGANIZATION.md"


def _track(index, track_id, kind, name, group_id, clips=(), devices=()):
    return {
        "index": index,
        "id": str(track_id),
        "type": kind,
        "name": name,
        "color": index,
        "group_id": str(group_id),
        "devices": list(devices),
        "arrangement_clips": list(clips),
    }


def _clip(start, end, disabled=False):
    return {"type": "AudioClip", "start_beat": start, "end_beat": end, "disabled": disabled}


def test_repo_schema_loads_machine_readable_preferences():
    schema = load_organization_schema(SCHEMA_PATH)
    assert schema["schema_version"] == 1
    assert [item["role"] for item in schema["top_level"]] == [
        "vox",
        "music",
        "bass",
        "sidechain",
        "drums",
        "fx",
    ]
    assert schema["_sha256"]


def test_project_context_classifies_bus_and_drum_roles_with_chronology():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/KISS.als",
        "track_count": 6,
        "tracks": [
            _track(0, 10, "GroupTrack", "VOX", -1),
            _track(1, 20, "GroupTrack", "DRUMS", -1),
            _track(2, 21, "AudioTrack", "Drop Kick", 20, [_clip(100, 108)]),
            _track(3, 22, "AudioTrack", "Intro Clap", 20, [_clip(8, 16)]),
            _track(4, 30, "GroupTrack", "BASS", -1),
            _track(5, 31, "MidiTrack", "Serum 2", 30, [_clip(96, 128)]),
        ],
    }
    context = build_project_context(report, schema)
    by_name = {item["name"]: item for item in context["tracks"]}
    assert by_name["Drop Kick"]["semantic_role"] == "drums.kick"
    assert by_name["Intro Clap"]["semantic_role"] == "drums.snare_clap"
    assert by_name["Drop Kick"]["height_class"] == "compact"
    assert by_name["Serum 2"]["root_role"] == "bass"
    assert [item["name"] for item in context["structural_plan"]["top_level_order"]] == [
        "VOX",
        "BASS",
        "DRUMS",
    ]
    assert [item["name"] for item in context["structural_plan"]["current_top_level_order"]] == [
        "VOX",
        "DRUMS",
        "BASS",
    ]
    assert context["structural_plan"]["reorder_required"] is True
    assert context["structural_plan"]["routing_equivalence_required"] is True
    assert context["structural_plan"]["execution_state"] == "REFUSED_ROUTING_EQUIVALENCE_NOT_PROVEN"
    assert {item["code"] for item in context["structural_plan"]["blockers"]} == {
        "BOUNDED_REORDER_CAPABILITY_MISSING",
        "ROUTING_EQUIVALENCE_PROOF_MISSING",
    }
    assert [item["name"] for item in context["structural_plan"]["drum_order"]] == [
        "Drop Kick",
        "Intro Clap",
    ]
    assert context["effect_state"] == "NOT_STARTED"


def test_structural_plan_is_noop_when_top_level_order_already_matches():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 3,
        "tracks": [
            _track(0, 10, "GroupTrack", "VOX", -1),
            _track(1, 20, "GroupTrack", "BASS", -1),
            _track(2, 30, "GroupTrack", "DRUMS", -1),
        ],
    }

    context = build_project_context(report, schema)
    structural = context["structural_plan"]

    assert structural["reorder_required"] is False
    assert structural["routing_equivalence_required"] is False
    assert structural["blockers"] == []
    assert structural["execution_state"] == "NO_STRUCTURAL_CHANGE_NEEDED"


def test_unknown_family_remains_unresolved_instead_of_being_guessed():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 1,
        "tracks": [_track(0, 1, "AudioTrack", "Mystery Texture", -1, [_clip(0, 4)])],
    }
    context = build_project_context(report, schema)
    assert context["tracks"][0]["semantic_role"] == "unclassified"
    assert context["unresolved"][0]["name"] == "Mystery Texture"
    assert context["presentation_plan"]["concrete_edits"] == []


def test_source_family_color_consensus_normalizes_only_strong_same_source_outlier():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 7,
        "tracks": [
            {**_track(0, 10, "GroupTrack", "BASS", -1), "color": 22},
            {**_track(1, 11, "MidiTrack", "37-Serum 2", 10), "color": 22},
            {**_track(2, 12, "MidiTrack", "38-Serum 2", 10), "color": 22},
            {**_track(3, 13, "MidiTrack", "39-Serum 2", 10), "color": 21},
            {**_track(4, 14, "MidiTrack", "40-Serum 2", 10), "color": 22},
            {**_track(5, 15, "MidiTrack", "41-Serum 2", 10), "color": 22},
            {**_track(6, 16, "AudioTrack", "36-Demucs Bass", 10), "color": 20},
        ],
    }

    context = build_project_context(report, schema)
    edits = context["presentation_plan"]["concrete_edits"]

    assert len(edits) == 1
    assert edits[0]["track_id"] == "13"
    assert edits[0]["expected_current_value"] == 21
    assert edits[0]["value"] == 22
    assert edits[0]["basis"] == "source_family_consensus"
    assert edits[0]["confidence"] == 0.8


def test_source_family_consensus_requires_eighty_percent_and_preserves_distinct_sources():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 6,
        "tracks": [
            {**_track(0, 10, "GroupTrack", "VOX", -1), "color": 22},
            {**_track(1, 11, "AudioTrack", "1-Vocal Stem", 10), "color": 22},
            {**_track(2, 12, "AudioTrack", "2-Vocal Stem", 10), "color": 21},
            {**_track(3, 13, "AudioTrack", "3-Vocal Stem", 10), "color": 22},
            {**_track(4, 14, "AudioTrack", "4-Vocal Stem", 10), "color": 21},
            {**_track(5, 15, "AudioTrack", "Special Acapella", 10), "color": 19},
        ],
    }

    context = build_project_context(report, schema)

    assert context["presentation_plan"]["concrete_edits"] == []
    acapella = next(
        item
        for item in context["presentation_plan"]["color_intents"]
        if item["track_id"] == "15"
    )
    assert acapella["basis"] == "preserve_existing"
    assert acapella["proposed_color_index"] == 19


def test_explicit_schema_color_overrides_existing_and_consensus():
    schema = load_organization_schema(SCHEMA_PATH)
    schema["color_indices"] = {"bass": 7}
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 2,
        "tracks": [
            {**_track(0, 10, "GroupTrack", "BASS", -1), "color": 22},
            {**_track(1, 11, "MidiTrack", "37-Serum 2", 10), "color": 22},
        ],
    }

    context = build_project_context(report, schema)
    edits = context["presentation_plan"]["concrete_edits"]

    assert len(edits) == 2
    assert all(item["value"] == 7 for item in edits)
    assert all(item["basis"] == "schema" for item in edits)
    assert all(item["confidence"] == 1.0 for item in edits)


def test_full_presentation_plan_preserves_names_and_emits_height_confidence():
    schema = load_organization_schema(SCHEMA_PATH)
    report = {
        "path": "C:/Lab/Test.als",
        "track_count": 2,
        "tracks": [
            _track(0, 10, "GroupTrack", "VOX", -1),
            _track(1, 11, "AudioTrack", "1-Lead Vocal", 10),
        ],
    }

    context = build_project_context(report, schema)
    presentation = context["presentation_plan"]

    assert len(presentation["naming_intents"]) == 2
    assert all(item["action"] == "preserve" for item in presentation["naming_intents"])
    assert len(presentation["height_intents"]) == 2
    assert presentation["height_intents"][0]["height_class"] == "tall"
    assert presentation["height_intents"][1]["height_class"] == "medium"
    assert all("confidence" in item for item in presentation["height_intents"])


def test_context_write_is_durable_json(tmp_path):
    target = tmp_path / "context.json"
    payload = {"schema_version": "test", "effect_state": "NOT_STARTED"}
    written = write_project_context(target, payload)
    assert written == target.resolve()
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not target.with_suffix(".json.tmp").exists()
