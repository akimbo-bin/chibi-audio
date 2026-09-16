from pathlib import Path

import pytest

import chibi_audio.managed_capture as managed
from chibi_audio.capture import CaptureError
from chibi_audio.capture_session import CaptureSessionTap
from chibi_audio.capture_topology import CaptureTopologyLease, PreparedTopologyTap


def _lease():
    return CaptureTopologyLease(
        initial_set_signature="sig-plan",
        final_set_signature="sig-prepared",
        taps=(
            PreparedTopologyTap(
                tap_id=2,
                source_label="BASS_PRE",
                target="BASS",
                placement="track",
                signal_point="pre_fx",
                track_name="BASS",
                track_index=34,
                track_id=200,
                device_id=1000,
                device_index=0,
                created=True,
                prior_tap_id=0,
                tap_id_changed=True,
            ),
        ),
    )


def test_managed_capture_fences_runner_to_prepared_signature_and_restores(monkeypatch, tmp_path):
    lease = _lease()
    calls = {}

    def fake_prepare(specs, **kwargs):
        calls["prepare_specs"] = list(specs)
        calls["prepare_kwargs"] = kwargs
        return lease

    def fake_runner(**kwargs):
        calls["runner"] = kwargs
        path = tmp_path / "manifest.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def fake_restore(observed_lease, **kwargs):
        calls["restore_lease"] = observed_lease
        calls["restore_kwargs"] = kwargs
        return {"final_set_signature": "sig-restored", "actions": []}

    monkeypatch.setattr(managed, "prepare_capture_topology", fake_prepare)
    monkeypatch.setattr(managed, "restore_capture_topology", fake_restore)

    result = managed.run_managed_capture_session(
        experiment_id="proof",
        taps=[CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx")],
        output_dir=tmp_path,
        start_beat=32.0,
        end_beat=48.0,
        expected_set_signature="sig-plan",
        remove_created_after=False,
        capture_runner=fake_runner,
    )

    assert result.manifest_path == tmp_path / "manifest.json"
    assert result.topology is lease
    assert calls["runner"]["expected_set_signature"] == "sig-prepared"
    assert calls["runner"]["taps"] == lease.session_specs()
    assert calls["restore_lease"] is lease
    assert calls["restore_kwargs"]["expected_set_signature"] == "sig-prepared"
    assert calls["restore_kwargs"]["remove_created"] is False


def test_managed_capture_failure_forces_created_tap_cleanup(monkeypatch, tmp_path):
    lease = _lease()
    calls = {}

    monkeypatch.setattr(managed, "prepare_capture_topology", lambda *_args, **_kwargs: lease)

    def failing_runner(**_kwargs):
        raise RuntimeError("capture failed")

    def fake_restore(_lease, **kwargs):
        calls["restore_kwargs"] = kwargs
        return {"actions": [{"action": "remove_created"}]}

    monkeypatch.setattr(managed, "restore_capture_topology", fake_restore)

    with pytest.raises(RuntimeError, match="capture failed"):
        managed.run_managed_capture_session(
            experiment_id="proof",
            taps=[CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx")],
            output_dir=tmp_path,
            start_beat=32.0,
            end_beat=48.0,
            remove_created_after=False,
            capture_runner=failing_runner,
        )

    assert calls["restore_kwargs"]["remove_created"] is True
    assert calls["restore_kwargs"]["expected_set_signature"] == "sig-prepared"


def test_managed_capture_reports_cleanup_failure_after_finalized_manifest(monkeypatch, tmp_path):
    lease = _lease()
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(managed, "prepare_capture_topology", lambda *_args, **_kwargs: lease)
    monkeypatch.setattr(managed, "restore_capture_topology", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("restore failed")))

    with pytest.raises(CaptureError, match="capture finalized at .*manifest.json.*restore was incomplete"):
        managed.run_managed_capture_session(
            experiment_id="proof",
            taps=[CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx")],
            output_dir=tmp_path,
            start_beat=32.0,
            end_beat=48.0,
            capture_runner=lambda **_kwargs: Path(manifest),
        )
