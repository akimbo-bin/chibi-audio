from __future__ import annotations

import json
from pathlib import Path

import pytest

from chibi_audio.capture import CaptureError
from chibi_audio.experiment_journal import (
    ExperimentChange,
    append_experiment_decision,
    attach_capture_analysis_report,
    attach_clean_loudness_evaluation,
    create_experiment_journal,
    verify_experiment_journal,
)


def _write_capture_manifest(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
) -> Path:
    payload = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "requested_range": {
            "start_beat": 96.0,
            "end_beat": 160.0,
            "tempo_bpm": 135.0,
            "sample_rate": 48000,
            "channels": 2,
            "target_samples": 1365333,
        },
        "taps": [
            {
                "tap_id": 1,
                "source_label": "Main",
                "final": {
                    "path": f"{experiment_id}__tap-1-Main.wav",
                    "samples": 1365333,
                    "sha256": content_sha256,
                },
            }
        ],
        "live_session": {
            "set_signature": f"sig-{experiment_id}",
            "song": {
                "name": "KISSKISSKISS Mix - Chibi Baseline",
                "file_path": "C:/Lab/KISSKISSKISS.als",
            },
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_capture_analysis_report(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
) -> Path:
    payload = {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": f"{experiment_id}.capture.json",
        "experiment_id": experiment_id,
        "requested_capabilities": ["audio.loudness", "audio.levels"],
        "taps": [
            {
                "tap_id": 1,
                "source_label": "Main",
                "artifact_path": f"{experiment_id}__tap-1-Main.wav",
                "content_sha256": content_sha256,
                "analysis": {
                    "source_name": f"{experiment_id}__tap-1-Main.wav",
                    "source_size_bytes": 4096,
                    "requested_capabilities": ["audio.loudness", "audio.levels"],
                    "executed_analyzers": [{"name": "numpy_signal"}],
                    "measurements": {
                        "audio.loudness": {"integrated_lufs": -9.0},
                        "audio.levels": {"crest_factor_db": 8.0},
                    },
                    "content_sha256": content_sha256,
                    "analysis_key": ("b" if experiment_id == "baseline" else "d") * 64,
                    "cache_hit": False,
                    "schema_version": "chibi-audio-analysis/v1",
                    "diagnostics": [],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_evaluation(
    path: Path,
    *,
    baseline_sha256: str,
    candidate_sha256: str,
    status: str = "keep",
) -> Path:
    journal_status = status if status in {"keep", "reject", "refine"} else None
    payload = {
        "schema_version": "chibi-audio-clean-loudness-evaluation/v1",
        "objective": "clean_loudness",
        "mutation_effect_state": "NOT_STARTED",
        "baseline": {
            "schema_version": "chibi-audio-analysis/v1",
            "source_name": "baseline.wav",
            "source_size_bytes": 4096,
            "content_sha256": baseline_sha256,
        },
        "candidate": {
            "schema_version": "chibi-audio-analysis/v1",
            "source_name": "candidate.wav",
            "source_size_bytes": 4096,
            "content_sha256": candidate_sha256,
        },
        "decision": {
            "status": status,
            "journal_status": journal_status,
            "reason_codes": [
                "loudness_goal_met_within_guardrails"
                if status == "keep"
                else "test-decision"
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _prepare_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    baseline_sha = "a" * 64
    candidate_sha = "c" * 64

    baseline_capture = _write_capture_manifest(
        tmp_path / "baseline.capture.json",
        experiment_id="baseline",
        content_sha256=baseline_sha,
    )
    baseline_analysis = _write_capture_analysis_report(
        tmp_path / "baseline.analysis.json",
        experiment_id="baseline",
        content_sha256=baseline_sha,
    )
    baseline_journal = create_experiment_journal(
        capture_manifest=baseline_capture,
        output_path=tmp_path / "baseline.experiment.json",
        comparison_id="kiss-clean-loudness",
        variant_role="baseline",
        hypothesis="Measure the clean-loudness frontier from a fixed baseline.",
    )
    attach_capture_analysis_report(
        baseline_journal,
        analysis_report=baseline_analysis,
        label="optimizer-evidence",
    )

    candidate_capture = _write_capture_manifest(
        tmp_path / "candidate.capture.json",
        experiment_id="candidate",
        content_sha256=candidate_sha,
    )
    candidate_analysis = _write_capture_analysis_report(
        tmp_path / "candidate.analysis.json",
        experiment_id="candidate",
        content_sha256=candidate_sha,
    )
    candidate_journal = create_experiment_journal(
        capture_manifest=candidate_capture,
        output_path=tmp_path / "candidate.experiment.json",
        comparison_id="kiss-clean-loudness",
        variant_role="candidate",
        parent_experiment_id="baseline",
        hypothesis="A bounded master-drive increase may gain loudness without crossing the clean frontier.",
        changes=[
            ExperimentChange(
                target="master:Pro-L 2",
                parameter="Gain",
                before=12.4,
                after=12.9,
                unit="dB",
            )
        ],
    )
    attach_capture_analysis_report(
        candidate_journal,
        analysis_report=candidate_analysis,
        label="optimizer-evidence",
    )

    evaluation = _write_evaluation(
        tmp_path / "evaluation.json",
        baseline_sha256=baseline_sha,
        candidate_sha256=candidate_sha,
    )
    return baseline_journal, candidate_journal, evaluation


def test_attach_clean_loudness_evaluation_binds_exact_audio_and_decision(tmp_path: Path) -> None:
    baseline, candidate, evaluation = _prepare_pair(tmp_path)

    attach_clean_loudness_evaluation(
        candidate,
        baseline_journal=baseline,
        evaluation_report=evaluation,
        label="clean loudness",
        attached_at_utc="2026-09-16T16:40:00+00:00",
    )

    journal = verify_experiment_journal(candidate)
    bindings = journal["evidence"]["optimizer_evaluations"]
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["label"] == "clean-loudness"
    assert binding["report_path"] == "evaluation.json"
    assert binding["baseline_journal_path"] == "baseline.experiment.json"
    assert binding["baseline_experiment_id"] == "baseline"
    assert binding["candidate_experiment_id"] == "candidate"
    assert len(binding["baseline_manifest_sha256"]) == 64
    assert len(binding["candidate_manifest_sha256"]) == 64
    assert binding["baseline_content_sha256"] == "a" * 64
    assert binding["candidate_content_sha256"] == "c" * 64
    assert binding["decision_status"] == "keep"
    assert binding["journal_status"] == "keep"
    assert binding["reason_codes"] == ["loudness_goal_met_within_guardrails"]
    assert binding["attached_at_utc"] == "2026-09-16T16:40:00+00:00"
    assert journal["decision"]["status"] == "pending"


def test_verify_refuses_tampered_bound_clean_loudness_evaluation(tmp_path: Path) -> None:
    baseline, candidate, evaluation = _prepare_pair(tmp_path)
    attach_clean_loudness_evaluation(
        candidate,
        baseline_journal=baseline,
        evaluation_report=evaluation,
        label="clean-loudness",
    )

    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["decision"]["reason_codes"] = ["tampered"]
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="bound optimizer evaluation SHA-256 changed"):
        verify_experiment_journal(candidate)


def test_attach_refuses_optimizer_evaluation_for_unbound_candidate_audio(tmp_path: Path) -> None:
    baseline, candidate, evaluation = _prepare_pair(tmp_path)
    _write_evaluation(
        evaluation,
        baseline_sha256="a" * 64,
        candidate_sha256="e" * 64,
    )

    with pytest.raises(CaptureError, match="candidate audio is not bound"):
        attach_clean_loudness_evaluation(
            candidate,
            baseline_journal=baseline,
            evaluation_report=evaluation,
            label="wrong-candidate",
        )


def test_baseline_decision_history_can_advance_without_breaking_optimizer_binding(tmp_path: Path) -> None:
    baseline, candidate, evaluation = _prepare_pair(tmp_path)
    attach_clean_loudness_evaluation(
        candidate,
        baseline_journal=baseline,
        evaluation_report=evaluation,
        label="clean-loudness",
    )

    append_experiment_decision(
        baseline,
        status="keep",
        note="Baseline retained as a listening reference after the optimizer comparison.",
    )

    verified = verify_experiment_journal(candidate)
    assert verified["evidence"]["optimizer_evaluations"][0]["decision_status"] == "keep"

def test_attach_requires_candidate_parent_to_match_baseline_lineage(tmp_path: Path) -> None:
    baseline, candidate, evaluation = _prepare_pair(tmp_path)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["parent_experiment_id"] = "different-baseline"
    candidate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="parent_experiment_id must match"):
        attach_clean_loudness_evaluation(
            candidate,
            baseline_journal=baseline,
            evaluation_report=evaluation,
            label="wrong-lineage",
        )
