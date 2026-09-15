from pathlib import Path

import pytest

from chibi_audio.capture import CaptureError, CapturePlan, default_capture_filename, wait_for_stable_capture, write_capture_manifest


def test_capture_plan_and_filename(tmp_path):
    plan = CapturePlan("house A/B #1", "DRUMS main", tmp_path / "x.wav", 64.0, 32.0)
    assert plan.experiment_id == "house-A-B-1"
    assert plan.source_label == "DRUMS-main"
    assert plan.end_beat == 96.0
    assert default_capture_filename(plan.experiment_id, plan.source_label) == "house-A-B-1__DRUMS-main.wav"


def test_manifest_and_stable_capture(tmp_path):
    plan = CapturePlan("exp", "master", tmp_path / "master.wav", 64, 16)
    manifest = write_capture_manifest(plan, tmp_path / "manifest.json")
    assert manifest.exists()
    path = tmp_path / "capture.wav"
    path.write_bytes(b"R" * 128)
    artifact = wait_for_stable_capture(path, timeout=1.0, stable_for=0.02, poll_interval=0.01)
    assert artifact.bytes == 128
    assert len(artifact.sha256) == 64


def test_capture_plan_rejects_invalid_duration(tmp_path):
    with pytest.raises(CaptureError, match="duration_beats"):
        CapturePlan("exp", "master", tmp_path / "x.wav", 0, 0)
