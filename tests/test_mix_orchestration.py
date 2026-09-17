from __future__ import annotations

from pathlib import Path
import gzip

from chibi_audio.als import inspect_set
from chibi_audio.mix_orchestration import (
    MixHypothesis,
    build_mix_wave_plan,
    project_snapshot_from_saved_set,
)


def _track(index, track_id, name, *, foldable=False, parent=None):
    value = {
        "index": index,
        "id": track_id,
        "name": name,
        "is_foldable": foldable,
    }
    if parent is not None:
        value["is_grouped"] = True
        value["group_track"] = {"id": parent[0], "name": parent[1]}
    return value


def _snapshot():
    return {
        "set_signature": "sig-kiss",
        "tempo": 120.0,
        "master_track": {"id": 900, "name": "Main"},
        "tracks": [
            _track(0, 10, "DRUMS", foldable=True),
            _track(1, 11, "KICK", parent=(10, "DRUMS")),
            _track(2, 12, "SNARE", parent=(10, "DRUMS")),
            _track(3, 20, "BASS", foldable=True),
            _track(4, 21, "SUB", parent=(20, "BASS")),
            _track(5, 30, "VOX", foldable=True),
            _track(6, 31, "LEAD", parent=(30, "VOX")),
            _track(7, 40, "FX", foldable=True),
        ],
    }


def _section():
    return {"name": "house-drop", "start_beat": 96.0, "end_beat": 128.0}


def test_plan_dispatches_parallel_bus_workers_and_child_census():
    plan = build_mix_wave_plan(
        _snapshot(),
        section=_section(),
        event_beats=[104.0],
        hypotheses=[
            MixHypothesis(
                "drum-stress",
                "bus",
                ("DRUMS",),
                "Drums lead full-band master-stress evidence.",
                ("stress:drums",),
                priority=1,
            ),
            MixHypothesis(
                "bass-stress",
                "bus",
                ("BASS",),
                "Bass leads low-band master-stress evidence.",
                ("stress:bass",),
                priority=2,
            ),
        ],
    )
    assert plan["effect_state"] == "NOT_STARTED"
    assert plan["orchestrator"]["authority"] == "chibi_core"
    assert plan["execution_policy"]["parallel_analysis_allowed"] is True
    assert plan["execution_policy"]["parallel_live_mutation_allowed"] is False
    assert [item["hypothesis_id"] for item in plan["workers"]] == [
        "drum-stress",
        "bass-stress",
    ]
    assert [item["name"] for item in plan["workers"][0]["child_targets"]] == [
        "KICK",
        "SNARE",
    ]
    stages = plan["capture_stages"]
    assert stages[0]["stage"] == "bus_census"
    assert [item["name"] for item in stages[0]["targets"]] == [
        "Main",
        "DRUMS",
        "BASS",
        "VOX",
        "FX",
    ]
    assert [item["stage"] for item in stages[1:]] == [
        "suspect_bus_census",
        "suspect_bus_census",
    ]
    assert plan["ready_for_parallel_analysis"] is True


def test_event_window_is_short_and_section_bounded():
    plan = build_mix_wave_plan(
        _snapshot(),
        section=_section(),
        event_beats=[104.0],
        diagnostic_seconds=4.0,
        hypotheses=[MixHypothesis("drums", "bus", ("DRUMS",), "Inspect drums.")],
    )
    window = plan["diagnostic_range"]
    assert window["fast_path"] is True
    assert window["window_reason"] == "stress_event"
    assert window["anchor_beat"] == 104.0
    assert window["start_beat"] == 100.0
    assert window["end_beat"] == 108.0


def test_no_event_falls_back_to_full_section_without_guessing():
    plan = build_mix_wave_plan(
        _snapshot(),
        section=_section(),
        hypotheses=[MixHypothesis("drums", "bus", ("DRUMS",), "Inspect drums.")],
    )
    assert plan["diagnostic_range"] == {
        "start_beat": 96.0,
        "end_beat": 128.0,
        "fast_path": False,
        "window_reason": "section_fallback_no_event_beats",
    }


def test_missing_target_is_a_blocker_not_an_invented_assignment():
    plan = build_mix_wave_plan(
        _snapshot(),
        section=_section(),
        hypotheses=[
            MixHypothesis("ghost", "bus", ("NOT A TRACK",), "Do not guess targets.")
        ],
    )
    assert plan["workers"][0]["targets"] == []
    assert plan["blockers"] == ["target_not_unique_or_missing:NOT A TRACK"]
    assert plan["ready_for_parallel_analysis"] is False


def test_parallel_worker_budget_is_hard_bound():
    hypotheses = [
        MixHypothesis(f"h{i}", "bus", ("DRUMS",), f"Hypothesis {i}.", priority=i)
        for i in range(1, 7)
    ]
    plan = build_mix_wave_plan(
        _snapshot(),
        section=_section(),
        hypotheses=hypotheses,
        max_parallel_workers=3,
    )
    assert [item["hypothesis_id"] for item in plan["workers"]] == ["h1", "h2", "h3"]
    assert plan["parallel_worker_limit"] == 3


def test_bridge_track_summary_exposes_parent_group_identity():
    source = (
        Path(__file__).parents[1]
        / "bridge"
        / "ChibiAudioBridge"
        / "bridge.py"
    ).read_text(encoding="utf-8")
    assert '"is_grouped"' in source
    assert 'group_track = getattr(track, "group_track", None)' in source
    assert 'summary["group_track"]' in source


def test_saved_set_activity_filters_silent_bus_children():
    report = {
        "path": "C:/Lab/KISS.als",
        "track_count": 3,
        "tracks": [
            {"id": "10", "type": "GroupTrack", "name": "DRUMS", "group_id": "-1", "arrangement_clips": []},
            {"id": "11", "type": "AudioTrack", "name": "KICK", "group_id": "10", "arrangement_clips": [{"type": "AudioClip", "start_beat": 100.0, "end_beat": 108.0, "disabled": False}]},
            {"id": "12", "type": "AudioTrack", "name": "OLD LOOP", "group_id": "10", "arrangement_clips": [{"type": "AudioClip", "start_beat": 32.0, "end_beat": 40.0, "disabled": False}]},
        ],
    }
    snapshot = project_snapshot_from_saved_set(
        report,
        set_signature="sig-kiss",
        tempo_bpm=120.0,
        master_track={"id": 900, "name": "Main"},
    )
    plan = build_mix_wave_plan(
        snapshot,
        section=_section(),
        event_beats=[104.0],
        hypotheses=[MixHypothesis("drums", "bus", ("DRUMS",), "Inspect active drum children.")],
    )
    assert [item["name"] for item in plan["workers"][0]["child_targets"]] == ["KICK"]


def test_inspect_set_reports_arrangement_clip_spans(tmp_path):
    xml = """<Ableton><LiveSet><Tracks><AudioTrack Id='11'><Name><UserName Value='KICK'/><EffectiveName Value='KICK'/></Name><Color Value='1'/><TrackGroupId Value='10'/><DeviceChain><MainSequencer><Sample><ArrangerAutomation><Events><AudioClip Id='1' Time='100'><CurrentStart Value='100'/><CurrentEnd Value='108'/><Disabled Value='false'/></AudioClip><AudioClip Id='2' Time='120'><CurrentStart Value='120'/><CurrentEnd Value='124'/><Disabled Value='true'/></AudioClip></Events></ArrangerAutomation></Sample></MainSequencer><Devices/></DeviceChain></AudioTrack></Tracks></LiveSet></Ableton>"""
    path = tmp_path / "fixture.als"
    with gzip.open(path, "wb") as stream:
        stream.write(xml.encode("utf-8"))
    report = inspect_set(path)
    clips = report["tracks"][0]["arrangement_clips"]
    assert clips == [
        {"type": "AudioClip", "start_beat": 100.0, "end_beat": 108.0, "disabled": False},
        {"type": "AudioClip", "start_beat": 120.0, "end_beat": 124.0, "disabled": True},
    ]
