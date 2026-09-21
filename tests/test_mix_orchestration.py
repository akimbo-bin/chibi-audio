from __future__ import annotations

from pathlib import Path
import gzip
import json

import pytest

from chibi_audio.als import inspect_set
from chibi_audio.mix_orchestration import (
    BUS_CONTRIBUTION_WAVE_DERIVATION_SCHEMA_VERSION,
    MASTER_STRESS_WAVE_DERIVATION_SCHEMA_VERSION,
    MixHypothesis,
    MixWavePlanError,
    build_mix_wave_from_master_stress,
    build_source_wave_from_bus_contribution,
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


def _write_master_stress_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "master-stress-capture.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_id": "kiss-stress-fixture",
                "requested_range": {
                    "start_beat": 96.0,
                    "end_beat": 160.0,
                    "tempo_bpm": 135.0,
                },
                "live_session": {
                    "mixer_state": {
                        "tap_targets": [
                            {
                                "source_label": "MASTER_PRE",
                                "track_name": "Main",
                                "placement": "master",
                            },
                            {
                                "source_label": "MASTER_POST",
                                "track_name": "Main",
                                "placement": "master",
                            },
                            {
                                "source_label": "BASS_POST",
                                "track_name": "BASS",
                                "placement": "track",
                            },
                            {
                                "source_label": "DRUMS_POST",
                                "track_name": "DRUMS",
                                "placement": "track",
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _master_stress_attribution(manifest: Path) -> dict:
    return {
        "schema_version": "chibi-audio-master-stress-attribution/v1",
        "capture_manifest": str(manifest),
        "experiment_id": "kiss-stress-fixture",
        "effect_state": "NOT_STARTED",
        "sources": [
            {
                "source_label": "BASS_POST",
                "rms_correlation_to_stress": 0.10,
                "low_band_correlation_to_stress": 0.41,
                "top_stress_rms_uplift_db": 0.50,
                "top_stress_low_band_uplift_db": 2.78,
                "top_stress_active_fraction_delta": 0.02,
            },
            {
                "source_label": "DRUMS_POST",
                "rms_correlation_to_stress": 0.20,
                "low_band_correlation_to_stress": 0.11,
                "top_stress_rms_uplift_db": 1.82,
                "top_stress_low_band_uplift_db": 0.60,
                "top_stress_active_fraction_delta": 0.01,
            },
        ],
        "leaders": {
            "rms_correlation_to_stress": {
                "source_label": "DRUMS_POST",
                "value": 0.20,
            },
            "low_band_correlation_to_stress": {
                "source_label": "BASS_POST",
                "value": 0.41,
            },
            "top_stress_rms_uplift_db": {
                "source_label": "DRUMS_POST",
                "value": 1.82,
            },
            "top_stress_low_band_uplift_db": {
                "source_label": "BASS_POST",
                "value": 2.78,
            },
            "top_stress_active_fraction_delta": None,
        },
        "stress_events": {
            "time_reference": "premaster_capture_start",
            "minimum_separation_ms": 250.0,
            "events": [
                {"rank": 1, "center_time_s": 4.0, "stress_db": 1.6},
                {"rank": 2, "center_time_s": 10.0, "stress_db": 1.4},
            ],
        },
    }


def test_master_stress_evidence_derives_two_metric_specific_bus_workers(tmp_path):
    manifest = _write_master_stress_manifest(tmp_path)
    attribution = _master_stress_attribution(manifest)
    snapshot = _snapshot()
    snapshot["tempo"] = 135.0

    plan = build_mix_wave_from_master_stress(
        snapshot,
        attribution,
        evidence_ref="artifact:kiss-master-stress",
        diagnostic_seconds=4.0,
    )

    assert plan["effect_state"] == "NOT_STARTED"
    assert plan["ready_for_parallel_analysis"] is True
    assert plan["blockers"] == []
    assert [item["hypothesis_id"] for item in plan["workers"]] == [
        "master-stress-bass",
        "master-stress-drums",
    ]
    assert [item["role"] for item in plan["workers"]] == [
        "bus_investigator",
        "bus_investigator",
    ]
    assert all(item["live_mutation_authorized"] is False for item in plan["workers"])
    assert [item["name"] for item in plan["workers"][0]["child_targets"]] == ["SUB"]
    assert [item["name"] for item in plan["workers"][1]["child_targets"]] == [
        "KICK",
        "SNARE",
    ]
    assert "low_band_stress_correlation=0.41" in plan["workers"][0]["rationale"]
    assert "full_band_stress_correlation=0.2" in plan["workers"][1]["rationale"]
    assert plan["diagnostic_range"]["fast_path"] is True
    assert plan["diagnostic_range"]["anchor_beat"] == pytest.approx(105.0)
    assert plan["diagnostic_range"]["start_beat"] == pytest.approx(100.5)
    assert plan["diagnostic_range"]["end_beat"] == pytest.approx(109.5)

    derivation = plan["evidence_derivation"]
    assert (
        derivation["schema_version"]
        == MASTER_STRESS_WAVE_DERIVATION_SCHEMA_VERSION
    )
    assert derivation["no_overall_winner"] is True
    assert derivation["source_target_map"] == {
        "BASS_POST": "BASS",
        "DRUMS_POST": "DRUMS",
    }
    assert derivation["stress_event_beats"] == pytest.approx([105.0, 118.5])
    by_target = {
        item["target_name"]: item["metrics"]
        for item in derivation["hypothesis_evidence"]
    }
    assert {row["dimension"] for row in by_target["BASS"]} == {
        "low_band_stress_correlation",
        "low_band_top_stress_uplift",
    }
    assert {row["dimension"] for row in by_target["DRUMS"]} == {
        "full_band_stress_correlation",
        "full_band_top_stress_uplift",
    }


def test_master_stress_wave_refuses_tempo_drift_for_event_anchoring(tmp_path):
    manifest = _write_master_stress_manifest(tmp_path)
    snapshot = _snapshot()
    snapshot["tempo"] = 136.0

    plan = build_mix_wave_from_master_stress(
        snapshot,
        _master_stress_attribution(manifest),
    )

    assert plan["ready_for_parallel_analysis"] is False
    assert plan["evidence_derivation"]["stress_event_beats"] == []
    assert "capture_tempo_mismatch:135->136" in plan["blockers"]
    assert plan["diagnostic_range"]["fast_path"] is False


def test_master_stress_wave_rejects_untrusted_leader_value(tmp_path):
    manifest = _write_master_stress_manifest(tmp_path)
    attribution = _master_stress_attribution(manifest)
    attribution["leaders"]["rms_correlation_to_stress"]["value"] = 0.99
    snapshot = _snapshot()
    snapshot["tempo"] = 135.0

    with pytest.raises(MixWavePlanError, match="disagrees with source row"):
        build_mix_wave_from_master_stress(snapshot, attribution)


def _write_bus_contribution_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "bus-contribution-capture.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_id": "drums-child-fixture",
                "requested_range": {
                    "start_beat": 96.0,
                    "end_beat": 160.0,
                    "tempo_bpm": 135.0,
                },
                "live_session": {
                    "mixer_state": {
                        "tap_targets": [
                            {
                                "source_label": "DRUMS_POST",
                                "track_name": "DRUMS",
                                "placement": "track",
                            },
                            {
                                "source_label": "DRUMS_CHILD_1",
                                "track_name": "KICK",
                                "placement": "track",
                            },
                            {
                                "source_label": "DRUMS_CHILD_2",
                                "track_name": "SNARE",
                                "placement": "track",
                            },
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _bus_contribution_attribution(manifest: Path) -> dict:
    return {
        "schema_version": "chibi-audio-bus-contribution-attribution/v1",
        "capture_manifest": str(manifest),
        "experiment_id": "drums-child-fixture",
        "effect_state": "NOT_STARTED",
        "reference_bus": {
            "source_label": "DRUMS_POST",
            "track_name": "DRUMS",
        },
        "sources": [
            {
                "source_label": "DRUMS_CHILD_1",
                "rms_correlation_to_bus": 0.61,
                "low_band_correlation_to_bus": 0.52,
                "top_bus_rms_uplift_db": 4.2,
                "top_bus_low_band_uplift_db": 5.1,
                "active_window_fraction": 0.72,
                "active_fraction_within_top_bus": 1.0,
                "top_bus_active_fraction_delta": 0.40,
            },
            {
                "source_label": "DRUMS_CHILD_2",
                "rms_correlation_to_bus": 0.93,
                "low_band_correlation_to_bus": 0.85,
                "top_bus_rms_uplift_db": 12.2,
                "top_bus_low_band_uplift_db": 17.3,
                "active_window_fraction": 0.06,
                "active_fraction_within_top_bus": 0.14,
                "top_bus_active_fraction_delta": 0.08,
            },
        ],
        "leaders": {
            "rms_correlation_to_bus": {
                "source_label": "DRUMS_CHILD_2",
                "value": 0.93,
            },
            "low_band_correlation_to_bus": {
                "source_label": "DRUMS_CHILD_2",
                "value": 0.85,
            },
            "top_bus_rms_uplift_db": {
                "source_label": "DRUMS_CHILD_2",
                "value": 12.2,
            },
            "top_bus_low_band_uplift_db": {
                "source_label": "DRUMS_CHILD_2",
                "value": 17.3,
            },
            "top_bus_active_fraction_delta": {
                "source_label": "DRUMS_CHILD_1",
                "value": 0.40,
            },
        },
        "bus_events": {
            "time_reference": "capture_start",
            "minimum_separation_ms": 250.0,
            "events": [
                {"rank": 1, "center_time_s": 4.0, "bus_rms_dbfs": -4.9},
                {"rank": 2, "center_time_s": 10.0, "bus_rms_dbfs": -5.0},
            ],
        },
        "no_overall_winner": True,
    }


def test_bus_contribution_derives_distinct_source_follow_up_workers(tmp_path):
    manifest = _write_bus_contribution_manifest(tmp_path)
    attribution = _bus_contribution_attribution(manifest)
    snapshot = _snapshot()
    snapshot["tempo"] = 135.0

    plan = build_source_wave_from_bus_contribution(
        snapshot,
        attribution,
        evidence_ref="artifact:drums-child-census",
        diagnostic_seconds=4.0,
    )

    assert plan["effect_state"] == "NOT_STARTED"
    assert plan["ready_for_parallel_analysis"] is True
    assert plan["blockers"] == []
    assert [item["hypothesis_id"] for item in plan["workers"]] == [
        "bus-contribution-kick",
        "bus-contribution-snare",
    ]
    assert [item["role"] for item in plan["workers"]] == [
        "source_investigator",
        "source_investigator",
    ]
    assert all(item["child_targets"] == [] for item in plan["workers"])
    assert all(
        item["live_mutation_authorized"] is False
        for item in plan["workers"]
    )
    assert "top_bus_activity_delta=0.4" in plan["workers"][0]["rationale"]
    assert "active_window_fraction=0.72" in plan["workers"][0]["rationale"]
    assert "full_band_bus_correlation=0.93" in plan["workers"][1]["rationale"]
    assert "top_bus_full_band_uplift=12.2" in plan["workers"][1]["rationale"]
    assert "active_window_fraction=0.06" in plan["workers"][1]["rationale"]

    assert plan["diagnostic_range"]["fast_path"] is True
    assert plan["diagnostic_range"]["anchor_beat"] == pytest.approx(105.0)
    assert plan["diagnostic_range"]["start_beat"] == pytest.approx(100.5)
    assert plan["diagnostic_range"]["end_beat"] == pytest.approx(109.5)

    assert len(plan["capture_stages"]) == 1
    stage = plan["capture_stages"][0]
    assert stage["stage"] == "source_follow_up"
    assert stage["reuse_reference_bus_evidence"] is True
    assert [item["name"] for item in stage["targets"]] == ["KICK", "SNARE"]

    derivation = plan["evidence_derivation"]
    assert (
        derivation["schema_version"]
        == BUS_CONTRIBUTION_WAVE_DERIVATION_SCHEMA_VERSION
    )
    assert derivation["reuse_reference_bus_evidence"] is True
    assert derivation["no_overall_winner"] is True
    assert derivation["source_target_map"] == {
        "DRUMS_CHILD_1": "KICK",
        "DRUMS_CHILD_2": "SNARE",
    }
    assert derivation["bus_event_beats"] == pytest.approx([105.0, 118.5])
    by_target = {
        item["target_name"]: item
        for item in derivation["hypothesis_evidence"]
    }
    assert {row["dimension"] for row in by_target["KICK"]["metrics"]} == {
        "top_bus_activity_delta",
    }
    assert by_target["KICK"]["activity_context"]["active_window_fraction"] == 0.72
    assert {row["dimension"] for row in by_target["SNARE"]["metrics"]} == {
        "full_band_bus_correlation",
        "low_band_bus_correlation",
        "top_bus_full_band_uplift",
        "top_bus_low_band_uplift",
    }
    assert by_target["SNARE"]["activity_context"]["active_window_fraction"] == 0.06


def test_bus_contribution_wave_refuses_tempo_drift_for_event_anchoring(tmp_path):
    manifest = _write_bus_contribution_manifest(tmp_path)
    snapshot = _snapshot()
    snapshot["tempo"] = 136.0

    plan = build_source_wave_from_bus_contribution(
        snapshot,
        _bus_contribution_attribution(manifest),
    )

    assert plan["ready_for_parallel_analysis"] is False
    assert plan["evidence_derivation"]["bus_event_beats"] == []
    assert "capture_tempo_mismatch:135->136" in plan["blockers"]
    assert plan["diagnostic_range"]["fast_path"] is False


def test_bus_contribution_wave_rejects_untrusted_leader_value(tmp_path):
    manifest = _write_bus_contribution_manifest(tmp_path)
    attribution = _bus_contribution_attribution(manifest)
    attribution["leaders"]["rms_correlation_to_bus"]["value"] = 0.99
    snapshot = _snapshot()
    snapshot["tempo"] = 135.0

    with pytest.raises(MixWavePlanError, match="disagrees with source row"):
        build_source_wave_from_bus_contribution(snapshot, attribution)
