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
    create_clean_loudness_journal_sweep,
    create_experiment_journal,
    verify_clean_loudness_journal_sweep,
    verify_experiment_journal,
)

from chibi_audio.optimizer import CleanLoudnessGoal, CleanLoudnessSweepPolicy


def _write_capture_manifest(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
    tap_id: int = 1,
    source_label: str = "Main",
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
                "tap_id": tap_id,
                "source_label": source_label,
                "final": {
                    "path": f"{experiment_id}__tap-{tap_id}-{source_label}.wav",
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

def _write_sweep_analysis_report(
    path: Path,
    *,
    experiment_id: str,
    content_sha256: str,
    integrated_lufs: float,
    true_peak_dbtp: float,
    crest_factor_db: float,
    tap_id: int = 1,
    source_label: str = "Main",
) -> Path:
    payload = {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": f"{experiment_id}.capture.json",
        "experiment_id": experiment_id,
        "requested_capabilities": ["audio.loudness", "audio.levels"],
        "taps": [
            {
                "tap_id": tap_id,
                "source_label": source_label,
                "artifact_path": f"{experiment_id}__tap-{tap_id}-{source_label}.wav",
                "content_sha256": content_sha256,
                "analysis": {
                    "source_name": f"{experiment_id}__tap-{tap_id}-{source_label}.wav",
                    "source_size_bytes": 4096,
                    "requested_capabilities": ["audio.loudness", "audio.levels"],
                    "executed_analyzers": [{"name": "numpy_signal"}],
                    "measurements": {
                        "audio.loudness": {
                            "integrated_lufs": integrated_lufs,
                            "true_peak_dbtp": true_peak_dbtp,
                        },
                        "audio.levels": {
                            "crest_factor_db": crest_factor_db,
                        },
                    },
                    "content_sha256": content_sha256,
                    "analysis_key": content_sha256,
                    "cache_hit": False,
                    "schema_version": "chibi-audio-analysis/v1",
                    "diagnostics": [],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _prepare_sweep_family(
    tmp_path: Path,
    *,
    tap_ids: tuple[int, int, int, int] = (1, 1, 1, 1),
    source_label: str = "Main",
) -> tuple[Path, list[tuple[float, Path]], list[Path]]:
    comparison_id = "kiss-master-drive-sweep"
    baseline_hash = "1" * 64
    baseline_capture = _write_capture_manifest(
        tmp_path / "sweep-baseline.capture.json",
        experiment_id="sweep-baseline",
        content_sha256=baseline_hash,
        tap_id=tap_ids[0],
        source_label=source_label,
    )
    baseline_analysis = _write_sweep_analysis_report(
        tmp_path / "sweep-baseline.analysis.json",
        experiment_id="sweep-baseline",
        content_sha256=baseline_hash,
        integrated_lufs=-10.0,
        true_peak_dbtp=-1.2,
        crest_factor_db=8.0,
        tap_id=tap_ids[0],
        source_label=source_label,
    )
    baseline_journal = create_experiment_journal(
        capture_manifest=baseline_capture,
        output_path=tmp_path / "sweep-baseline.experiment.json",
        comparison_id=comparison_id,
        variant_role="baseline",
        hypothesis="Measure a fixed master-drive clean-loudness frontier.",
    )
    attach_capture_analysis_report(
        baseline_journal,
        analysis_report=baseline_analysis,
        label="optimizer-evidence",
    )

    specs = [
        (0.5, "sweep-candidate-a", "2" * 64, -9.4, -1.0, 7.8),
        (1.0, "sweep-candidate-b", "3" * 64, -8.9, -0.9, 7.6),
        (1.5, "sweep-candidate-c", "4" * 64, -8.75, -0.85, 7.5),
    ]
    candidates: list[tuple[float, Path]] = []
    analysis_paths: list[Path] = []
    for candidate_index, (drive_db, experiment_id, content_sha, lufs, true_peak, crest) in enumerate(specs, start=1):
        capture = _write_capture_manifest(
            tmp_path / f"{experiment_id}.capture.json",
            experiment_id=experiment_id,
            content_sha256=content_sha,
            tap_id=tap_ids[candidate_index],
            source_label=source_label,
        )
        analysis = _write_sweep_analysis_report(
            tmp_path / f"{experiment_id}.analysis.json",
            experiment_id=experiment_id,
            content_sha256=content_sha,
            integrated_lufs=lufs,
            true_peak_dbtp=true_peak,
            crest_factor_db=crest,
            tap_id=tap_ids[candidate_index],
            source_label=source_label,
        )
        journal = create_experiment_journal(
            capture_manifest=capture,
            output_path=tmp_path / f"{experiment_id}.experiment.json",
            comparison_id=comparison_id,
            variant_role="candidate",
            parent_experiment_id="sweep-baseline",
            hypothesis=f"Test +{drive_db:.1f} dB master drive against the same baseline.",
            changes=[
                ExperimentChange(
                    target="master:Pro-L 2",
                    parameter="Gain",
                    before=12.4,
                    after=12.4 + drive_db,
                    unit="dB",
                )
            ],
        )
        attach_capture_analysis_report(
            journal,
            analysis_report=analysis,
            label="optimizer-evidence",
        )
        candidates.append((drive_db, journal))
        analysis_paths.append(analysis)
    return baseline_journal, candidates, analysis_paths


def _sweep_goal() -> CleanLoudnessGoal:
    return CleanLoudnessGoal(
        min_loudness_gain_lu=0.0,
        true_peak_ceiling_dbtp=-0.5,
        max_crest_factor_loss_db=1.0,
    )


def test_journal_sweep_persists_and_recomputes_clean_loudness_knee(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    output = tmp_path / "clean-loudness-sweep.json"

    create_clean_loudness_journal_sweep(
        baseline_journal=baseline,
        candidates=[candidates[2], candidates[0], candidates[1]],
        analysis_label="optimizer-evidence",
        tap_id=1,
        drive_target="master:Pro-L 2",
        drive_parameter="Gain",
        goal=_sweep_goal(),
        policy=CleanLoudnessSweepPolicy(
            max_points=4,
            min_marginal_lu_per_db=0.5,
        ),
        output_path=output,
        created_at_utc="2026-09-16T17:10:00+00:00",
    )

    payload = verify_clean_loudness_journal_sweep(output)
    assert payload["mutation_effect_state"] == "NOT_STARTED"
    assert [item["drive_db"] for item in payload["candidates"]] == [0.5, 1.0, 1.5]
    assert payload["baseline"]["experiment_id"] == "sweep-baseline"
    assert payload["drive_change"] == {
        "target": "master:Pro-L 2",
        "parameter": "Gain",
        "unit": "dB",
    }
    assert payload["candidates"][0]["declared_change"] == {
        "target": "master:Pro-L 2",
        "parameter": "Gain",
        "before": 12.4,
        "after": 12.9,
        "unit": "dB",
    }
    assert payload["sweep"]["knee"]["estimated"] is True
    assert payload["sweep"]["knee"]["reason"] == "marginal_efficiency_below_threshold"
    assert payload["sweep"]["knee"]["last_clean_point"]["drive_db"] == 1.0
    assert payload["sweep"]["knee"]["first_degraded_point"]["drive_db"] == 1.5



def test_journal_sweep_source_label_supports_session_local_tap_ids(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(
        tmp_path,
        tap_ids=(201, 203, 204, 205),
        source_label="MASTER",
    )
    output = tmp_path / "source-label-sweep.json"

    create_clean_loudness_journal_sweep(
        baseline_journal=baseline,
        candidates=candidates,
        analysis_label="optimizer-evidence",
        source_label="MASTER",
        drive_target="master:Pro-L 2",
        drive_parameter="Gain",
        goal=_sweep_goal(),
        policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
        output_path=output,
    )

    payload = verify_clean_loudness_journal_sweep(output)
    assert payload["source_label"] == "MASTER"
    assert "tap_id" not in payload
    assert [item["drive_db"] for item in payload["candidates"]] == [0.5, 1.0, 1.5]

def test_journal_sweep_verifier_refuses_tampered_sweep_result(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    output = tmp_path / "clean-loudness-sweep.json"
    create_clean_loudness_journal_sweep(
        baseline_journal=baseline,
        candidates=candidates,
        analysis_label="optimizer-evidence",
        tap_id=1,
        drive_target="master:Pro-L 2",
        drive_parameter="Gain",
        goal=_sweep_goal(),
        policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["sweep"]["knee"]["reason"] = "tampered"
    output.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="no longer matches bound journal evidence"):
        verify_clean_loudness_journal_sweep(output)


def test_journal_sweep_verifier_refuses_tampered_candidate_analysis(tmp_path: Path) -> None:
    baseline, candidates, analysis_paths = _prepare_sweep_family(tmp_path)
    output = tmp_path / "clean-loudness-sweep.json"
    create_clean_loudness_journal_sweep(
        baseline_journal=baseline,
        candidates=candidates,
        analysis_label="optimizer-evidence",
        tap_id=1,
        drive_target="master:Pro-L 2",
        drive_parameter="Gain",
        goal=_sweep_goal(),
        policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
        output_path=output,
    )

    payload = json.loads(analysis_paths[1].read_text(encoding="utf-8"))
    payload["taps"][0]["analysis"]["measurements"]["audio.loudness"]["integrated_lufs"] = -6.0
    analysis_paths[1].write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="bound analysis report SHA-256 changed"):
        verify_clean_loudness_journal_sweep(output)


def test_journal_sweep_refuses_candidate_from_different_family(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    foreign = candidates[0][1]
    payload = json.loads(foreign.read_text(encoding="utf-8"))
    payload["comparison_id"] = "other-comparison"
    foreign.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CaptureError, match="must share comparison_id"):
        create_clean_loudness_journal_sweep(
            baseline_journal=baseline,
            candidates=candidates,
            analysis_label="optimizer-evidence",
            tap_id=1,
            drive_target="master:Pro-L 2",
            drive_parameter="Gain",
            goal=_sweep_goal(),
            policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
            output_path=tmp_path / "should-not-exist.json",
        )


def test_journal_sweep_refuses_overwriting_bound_journal(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)

    with pytest.raises(CaptureError, match="must not overwrite"):
        create_clean_loudness_journal_sweep(
            baseline_journal=baseline,
            candidates=candidates,
            analysis_label="optimizer-evidence",
            tap_id=1,
            drive_target="master:Pro-L 2",
            drive_parameter="Gain",
            goal=_sweep_goal(),
            policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
            output_path=candidates[0][1],
        )


def test_journal_sweep_refuses_invalid_drive_before_writing_output(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    output = tmp_path / "invalid-drive.json"

    with pytest.raises(CaptureError, match="candidate drive"):
        create_clean_loudness_journal_sweep(
            baseline_journal=baseline,
            candidates=[("loud", candidates[0][1])],  # type: ignore[list-item]
            analysis_label="optimizer-evidence",
            tap_id=1,
            drive_target="master:Pro-L 2",
            drive_parameter="Gain",
            goal=_sweep_goal(),
            policy=CleanLoudnessSweepPolicy(max_points=1, min_marginal_lu_per_db=0.5),
            output_path=output,
        )
    assert not output.exists()

def test_journal_sweep_refuses_drive_label_mismatch_with_declared_change(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    output = tmp_path / "mislabeled-drive.json"

    with pytest.raises(CaptureError, match="does not match declared experiment change"):
        create_clean_loudness_journal_sweep(
            baseline_journal=baseline,
            candidates=[(0.75, candidates[0][1])],
            analysis_label="optimizer-evidence",
            tap_id=1,
            drive_target="master:Pro-L 2",
            drive_parameter="Gain",
            goal=_sweep_goal(),
            policy=CleanLoudnessSweepPolicy(max_points=1, min_marginal_lu_per_db=0.5),
            output_path=output,
        )
    assert not output.exists()


def test_journal_sweep_verifier_refuses_declared_change_relabeling(tmp_path: Path) -> None:
    baseline, candidates, _ = _prepare_sweep_family(tmp_path)
    output = tmp_path / "declared-change.json"
    create_clean_loudness_journal_sweep(
        baseline_journal=baseline,
        candidates=candidates,
        analysis_label="optimizer-evidence",
        tap_id=1,
        drive_target="master:Pro-L 2",
        drive_parameter="Gain",
        goal=_sweep_goal(),
        policy=CleanLoudnessSweepPolicy(max_points=3, min_marginal_lu_per_db=0.5),
        output_path=output,
    )

    candidate_path = candidates[0][1]
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["changes"][0]["before"] = 13.0
    candidate["changes"][0]["after"] = 13.5
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(CaptureError, match="declared change no longer matches journal"):
        verify_clean_loudness_journal_sweep(output)
