from __future__ import annotations

import json
from pathlib import Path

import pytest

from chibi_audio.capture import CaptureError
from chibi_audio.experiment_journal import (
    ExperimentChange,
    attach_capture_analysis_report,
    create_experiment_journal,
    verify_experiment_journal,
)
from chibi_audio.optimization_workflow import (
    CleanLoudnessWorkflowError,
    evaluate_bound_clean_loudness_candidate,
    load_bound_journal_analysis,
    persist_bound_clean_loudness_evaluation,
)
from chibi_audio.optimizer import CleanLoudnessGoal


def _write_capture_manifest(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
) -> Path:
    path.write_text(
        json.dumps(
            {
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
                        "tap_id": 201,
                        "source_label": "MAIN",
                        "final": {
                            "path": f"{experiment_id}.wav",
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
        ),
        encoding="utf-8",
    )
    return path


def _write_capture_analysis(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
    integrated_lufs: float,
    true_peak_dbtp: float,
    crest_factor_db: float,
    loudness_range_lu: float,
    high8: float,
) -> Path:
    inner = {
        "source_name": f"{experiment_id}.wav",
        "source_size_bytes": 4096,
        "requested_capabilities": [
            "audio.levels",
            "audio.loudness",
            "audio.texture",
        ],
        "executed_analyzers": [],
        "measurements": {
            "audio.levels": {"crest_factor_db": crest_factor_db},
            "audio.loudness": {
                "integrated_lufs": integrated_lufs,
                "true_peak_dbtp": true_peak_dbtp,
                "loudness_range_lu": loudness_range_lu,
            },
            "audio.texture": {"energy_above_8khz_fraction": high8},
        },
        "content_sha256": content_sha256,
        "analysis_key": ("b" if experiment_id == "baseline" else "d") * 64,
        "cache_hit": False,
        "schema_version": "chibi-audio-analysis/v1",
        "diagnostics": [],
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": "chibi-audio-capture-analysis/v1",
                "capture_manifest": f"{experiment_id}.capture.json",
                "experiment_id": experiment_id,
                "requested_capabilities": [
                    "audio.levels",
                    "audio.loudness",
                    "audio.texture",
                ],
                "taps": [
                    {
                        "tap_id": 201,
                        "source_label": "MAIN",
                        "artifact_path": f"{experiment_id}.wav",
                        "content_sha256": content_sha256,
                        "analysis": inner,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _goal() -> CleanLoudnessGoal:
    return CleanLoudnessGoal(
        min_loudness_gain_lu=1.0,
        true_peak_ceiling_dbtp=-0.3,
        max_crest_factor_loss_db=1.0,
        max_loudness_range_loss_lu=1.5,
        max_energy_above_8khz_fraction_increase=0.04,
    )


def _prepare_pair(tmp_path: Path) -> tuple[Path, Path]:
    baseline_sha = "a" * 64
    candidate_sha = "c" * 64
    baseline_capture = _write_capture_manifest(
        tmp_path / "baseline.capture.json",
        experiment_id="baseline",
        content_sha256=baseline_sha,
    )
    baseline_analysis = _write_capture_analysis(
        tmp_path / "baseline.analysis.json",
        experiment_id="baseline",
        content_sha256=baseline_sha,
        integrated_lufs=-10.0,
        true_peak_dbtp=-1.0,
        crest_factor_db=8.0,
        loudness_range_lu=6.0,
        high8=0.10,
    )
    baseline_journal = create_experiment_journal(
        capture_manifest=baseline_capture,
        output_path=tmp_path / "baseline.experiment.json",
        comparison_id="kiss-clean-loudness",
        variant_role="baseline",
        hypothesis="Establish the exact baseline before a bounded drive candidate.",
    )
    attach_capture_analysis_report(
        baseline_journal,
        analysis_report=baseline_analysis,
        label="clean-loudness",
    )

    candidate_capture = _write_capture_manifest(
        tmp_path / "candidate.capture.json",
        experiment_id="candidate",
        content_sha256=candidate_sha,
    )
    candidate_analysis = _write_capture_analysis(
        tmp_path / "candidate.analysis.json",
        experiment_id="candidate",
        content_sha256=candidate_sha,
        integrated_lufs=-8.8,
        true_peak_dbtp=-0.5,
        crest_factor_db=7.4,
        loudness_range_lu=5.5,
        high8=0.12,
    )
    candidate_journal = create_experiment_journal(
        capture_manifest=candidate_capture,
        output_path=tmp_path / "candidate.experiment.json",
        comparison_id="kiss-clean-loudness",
        variant_role="candidate",
        parent_experiment_id="baseline",
        hypothesis="Test a bounded drive increase against explicit clean-loudness guardrails.",
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
        label="clean-loudness",
    )
    return baseline_journal, candidate_journal


def test_load_bound_journal_analysis_returns_exact_inner_report(tmp_path: Path) -> None:
    baseline, _candidate = _prepare_pair(tmp_path)

    report = load_bound_journal_analysis(
        baseline,
        label="clean-loudness",
        tap_id=201,
        source_label="MAIN",
    )

    assert report.source_name == "baseline.wav"
    assert report.content_sha256 == "a" * 64
    assert report.measurements["audio.loudness"]["integrated_lufs"] == -10.0


def test_evaluate_bound_candidate_uses_verified_journal_evidence(tmp_path: Path) -> None:
    baseline, candidate = _prepare_pair(tmp_path)

    result = evaluate_bound_clean_loudness_candidate(
        baseline,
        candidate,
        baseline_analysis_label="clean-loudness",
        candidate_analysis_label="clean-loudness",
        baseline_tap_id=201,
        candidate_tap_id=201,
        goal=_goal(),
    )

    assert result["mutation_effect_state"] == "NOT_STARTED"
    assert result["decision"]["status"] == "keep"
    assert result["workflow_provenance"]["comparison_id"] == "kiss-clean-loudness"
    assert result["workflow_provenance"]["baseline_experiment_id"] == "baseline"
    assert result["workflow_provenance"]["candidate_experiment_id"] == "candidate"


def test_persist_evaluation_atomically_attaches_without_deciding_for_artist(tmp_path: Path) -> None:
    baseline, candidate = _prepare_pair(tmp_path)
    output = tmp_path / "evaluation.json"

    result = persist_bound_clean_loudness_evaluation(
        baseline,
        candidate,
        output_path=output,
        binding_label="clean-loudness-evaluation",
        baseline_analysis_label="clean-loudness",
        candidate_analysis_label="clean-loudness",
        baseline_tap_id=201,
        candidate_tap_id=201,
        goal=_goal(),
        attached_at_utc="2026-09-16T17:00:00+00:00",
    )

    assert result["artifact_effect_state"] == "STARTED_CONFIRMED"
    assert result["live_mutation_effect_state"] == "NOT_STARTED"
    assert result["evaluation"]["decision"]["status"] == "keep"
    assert output.is_file()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["workflow_provenance"]["candidate_experiment_id"] == "candidate"

    journal = verify_experiment_journal(candidate)
    assert journal["decision"]["status"] == "pending"
    bindings = journal["evidence"]["optimizer_evaluations"]
    assert len(bindings) == 1
    assert bindings[0]["label"] == "clean-loudness-evaluation"
    assert bindings[0]["decision_status"] == "keep"
    assert bindings[0]["attached_at_utc"] == "2026-09-16T17:00:00+00:00"


def test_persist_refuses_existing_output_before_journal_mutation(tmp_path: Path) -> None:
    baseline, candidate = _prepare_pair(tmp_path)
    output = tmp_path / "evaluation.json"
    output.write_text("already here", encoding="utf-8")

    with pytest.raises(CleanLoudnessWorkflowError, match="refusing to overwrite"):
        persist_bound_clean_loudness_evaluation(
            baseline,
            candidate,
            output_path=output,
            binding_label="clean-loudness-evaluation",
            baseline_analysis_label="clean-loudness",
            candidate_analysis_label="clean-loudness",
            goal=_goal(),
        )

    journal = verify_experiment_journal(candidate)
    assert journal["evidence"].get("optimizer_evaluations") is None
    assert output.read_text(encoding="utf-8") == "already here"


def test_load_bound_analysis_requires_tap_selector_when_report_has_multiple_taps(tmp_path: Path) -> None:
    baseline, _candidate = _prepare_pair(tmp_path)
    analysis_path = tmp_path / "baseline.analysis.json"
    payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    second = dict(payload["taps"][0])
    second["tap_id"] = 202
    second["source_label"] = "SECOND"
    payload["taps"].append(second)
    analysis_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="SHA-256 changed"):
        load_bound_journal_analysis(baseline, label="clean-loudness")
