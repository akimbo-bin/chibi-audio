from __future__ import annotations

import json
from pathlib import Path

import pytest

from chibi_audio.capture import CaptureError
from chibi_audio.experiment_journal import (
    ExperimentChange,
    append_experiment_decision,
    create_experiment_journal,
    verify_experiment_journal,
)


def _write_capture_manifest(path: Path, *, experiment_id: str = "drop-a") -> Path:
    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "requested_range": {
            "start_beat": 64.0,
            "end_beat": 72.0,
            "tempo_bpm": 135.0,
            "sample_rate": 48000,
            "channels": 2,
            "target_samples": 170667,
        },
        "taps": [
            {
                "tap_id": 1,
                "source_label": "Main",
                "final": {"path": "drop-a__tap-1-Main.wav", "samples": 170667},
            }
        ],
        "live_session": {
            "set_signature": "sig-123",
            "song": {
                "name": "KISSKISSKISS Mix - Chibi Baseline",
                "file_path": "C:/Lab/KISSKISSKISS.als",
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_create_baseline_journal_binds_exact_capture_manifest(tmp_path: Path) -> None:
    capture = _write_capture_manifest(tmp_path / "capture.json")
    journal_path = create_experiment_journal(
        capture_manifest=capture,
        output_path=tmp_path / "baseline.experiment.json",
        comparison_id="house-drop-loudness",
        variant_role="baseline",
        hypothesis="Reducing upstream peak stress may preserve more transient crest at the same output ceiling.",
        created_at_utc="2026-09-15T20:00:00+00:00",
    )

    journal = verify_experiment_journal(journal_path)
    assert journal["schema_version"] == 1
    assert journal["comparison_id"] == "house-drop-loudness"
    assert journal["variant_role"] == "baseline"
    assert journal["changes"] == []
    assert journal["decision"] == {"status": "pending", "history": []}
    assert journal["capture"]["experiment_id"] == "drop-a"
    assert journal["capture"]["set_signature"] == "sig-123"
    assert journal["capture"]["requested_range"]["start_beat"] == 64.0
    assert journal["capture"]["manifest_path"] == "capture.json"
    assert len(journal["capture"]["manifest_sha256"]) == 64


def test_candidate_requires_declared_change_and_records_artist_decision(tmp_path: Path) -> None:
    capture = _write_capture_manifest(tmp_path / "candidate-capture.json", experiment_id="drop-b")
    change = ExperimentChange(
        target="track:D61",
        parameter="Mixer Volume",
        before=0.0,
        after=-1.0,
        unit="dB",
    )
    journal_path = create_experiment_journal(
        capture_manifest=capture,
        output_path=tmp_path / "candidate.experiment.json",
        comparison_id="house-drop-loudness",
        variant_role="candidate",
        parent_experiment_id="drop-a",
        hypothesis="A 1 dB D61 trim will reduce low-frequency limiter stress without changing later sections.",
        changes=[change],
        created_at_utc="2026-09-15T20:01:00+00:00",
    )

    append_experiment_decision(
        journal_path,
        status="keep",
        note="Artist preferred the candidate after level-matched listening.",
        recorded_at_utc="2026-09-15T20:02:00+00:00",
    )
    append_experiment_decision(
        journal_path,
        status="refine",
        note="Keep the direction but test a smaller trim for the full-track version.",
        recorded_at_utc="2026-09-15T20:03:00+00:00",
    )

    journal = verify_experiment_journal(journal_path)
    assert journal["parent_experiment_id"] == "drop-a"
    assert journal["changes"] == [
        {
            "target": "track:D61",
            "parameter": "Mixer Volume",
            "before": 0.0,
            "after": -1.0,
            "unit": "dB",
        }
    ]
    assert journal["decision"]["status"] == "refine"
    assert [event["status"] for event in journal["decision"]["history"]] == ["keep", "refine"]
    assert journal["decision"]["history"][0]["note"].startswith("Artist preferred")


def test_verify_refuses_capture_manifest_tampering(tmp_path: Path) -> None:
    capture = _write_capture_manifest(tmp_path / "capture.json")
    journal_path = create_experiment_journal(
        capture_manifest=capture,
        output_path=tmp_path / "baseline.experiment.json",
        comparison_id="tamper-proof",
        variant_role="baseline",
        hypothesis="Bind this journal to the exact finalized capture evidence.",
    )

    payload = json.loads(capture.read_text(encoding="utf-8"))
    payload["requested_range"]["end_beat"] = 80.0
    capture.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="SHA-256 changed"):
        verify_experiment_journal(journal_path)


def test_invalid_roles_decisions_and_changes_fail_closed(tmp_path: Path) -> None:
    capture = _write_capture_manifest(tmp_path / "capture.json")

    with pytest.raises(CaptureError, match="variant_role"):
        create_experiment_journal(
            capture_manifest=capture,
            output_path=tmp_path / "bad-role.json",
            comparison_id="x",
            variant_role="winner",
            hypothesis="invalid",
        )

    with pytest.raises(CaptureError, match="candidate experiment journal requires"):
        create_experiment_journal(
            capture_manifest=capture,
            output_path=tmp_path / "no-change.json",
            comparison_id="x",
            variant_role="candidate",
            hypothesis="candidate without an explicit mutation should be refused",
        )

    with pytest.raises(CaptureError, match="target must not be empty"):
        ExperimentChange(target=" ", parameter="Gain", before=0, after=1)

    journal_path = create_experiment_journal(
        capture_manifest=capture,
        output_path=tmp_path / "baseline.json",
        comparison_id="x",
        variant_role="baseline",
        hypothesis="decision validation",
    )
    with pytest.raises(CaptureError, match="decision status"):
        append_experiment_decision(journal_path, status="best")
