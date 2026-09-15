import pytest

from chibi_audio.control import (
    ControlPlanError,
    build_audition_plan,
    diff_parameter_snapshots,
    parameter_snapshot,
    snapshot_track_controls,
)


def _summary():
    return {
        "set_signature": "sig-1",
        "tracks": [
            {"index": 0, "id": 100, "name": "Kick", "mute": False, "solo": False},
            {"index": 1, "id": 101, "name": "Bass", "mute": False, "solo": True},
            {"index": 2, "id": 102, "name": "Hats", "mute": True, "solo": False},
        ],
    }


def test_audition_plan_restores_exact_prior_state():
    plan = build_audition_plan(
        snapshot_track_controls(_summary()),
        solo_track_indices=[2],
    )
    apply = {(item["track_index"], item["property"]): item for item in plan["apply"]}
    restore = {(item["track_index"], item["property"]): item for item in plan["restore"]}

    assert apply[(1, "solo")]["value"] is False
    assert apply[(2, "solo")]["value"] is True
    assert restore[(1, "solo")]["expected_current_value"] is False
    assert restore[(1, "solo")]["value"] is True
    assert restore[(2, "solo")]["expected_current_value"] is True
    assert plan["set_signature"] == "sig-1"


def test_audition_plan_rejects_unknown_track():
    with pytest.raises(ControlPlanError, match="unknown track indices"):
        build_audition_plan(
            snapshot_track_controls(_summary()),
            solo_track_indices=[99],
        )


def test_parameter_diff_reports_only_changes():
    before = parameter_snapshot(
        track_index=1,
        track_name="Bass",
        device_index=0,
        device_name="Saturn 2",
        device_id=200,
        parameters=[
            {"id": 1, "name": "Mix", "value": 0.5, "display": "50%"},
            {"id": 2, "name": "Drive", "value": 0.2, "display": "20%"},
        ],
    )
    after = parameter_snapshot(
        track_index=1,
        track_name="Bass",
        device_index=0,
        device_name="Saturn 2",
        device_id=200,
        parameters=[
            {"id": 1, "name": "Mix", "value": 0.4, "display": "40%"},
            {"id": 2, "name": "Drive", "value": 0.2, "display": "20%"},
        ],
    )
    changes = diff_parameter_snapshots(before, after)
    assert len(changes) == 1
    assert changes[0]["name"] == "Mix"
    assert changes[0]["before_value"] == 0.5
    assert changes[0]["after_value"] == 0.4


def test_parameter_diff_refuses_different_device_identity():
    before = parameter_snapshot(
        track_index=1,
        track_name="Bass",
        device_index=0,
        device_name="Saturn 2",
        device_id=200,
        parameters=[],
    )
    after = parameter_snapshot(
        track_index=1,
        track_name="Bass",
        device_index=0,
        device_name="Saturn 2",
        device_id=201,
        parameters=[],
    )
    with pytest.raises(ControlPlanError, match="different track/device"):
        diff_parameter_snapshots(before, after)
