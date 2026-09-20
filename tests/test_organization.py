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
    assert [item["name"] for item in context["structural_plan"]["drum_order"]] == [
        "Drop Kick",
        "Intro Clap",
    ]
    assert context["effect_state"] == "NOT_STARTED"


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


def test_context_write_is_durable_json(tmp_path):
    target = tmp_path / "context.json"
    payload = {"schema_version": "test", "effect_state": "NOT_STARTED"}
    written = write_project_context(target, payload)
    assert written == target.resolve()
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not target.with_suffix(".json.tmp").exists()
