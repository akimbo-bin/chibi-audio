from __future__ import annotations

import json

import pytest

from chibi_audio.analysis.models import AnalysisCapability, AnalysisReport
from chibi_audio.optimizer import (
    CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION,
    CleanLoudnessEvaluationError,
    CleanLoudnessGoal,
    evaluate_clean_loudness_candidate,
    load_analysis_report,
)


def _report(
    *,
    name: str,
    integrated_lufs: float = -10.0,
    true_peak_dbtp: float = -1.0,
    crest_factor_db: float = 8.0,
    loudness_range_lu: float | None = 6.0,
    energy_above_8khz_fraction: float | None = 0.10,
) -> AnalysisReport:
    loudness = {
        "integrated_lufs": integrated_lufs,
        "true_peak_dbtp": true_peak_dbtp,
    }
    if loudness_range_lu is not None:
        loudness["loudness_range_lu"] = loudness_range_lu
    texture = {}
    if energy_above_8khz_fraction is not None:
        texture["energy_above_8khz_fraction"] = energy_above_8khz_fraction
    return AnalysisReport(
        source_name=name,
        source_size_bytes=1024,
        requested_capabilities=[
            AnalysisCapability.LOUDNESS.value,
            AnalysisCapability.LEVELS.value,
            AnalysisCapability.TEXTURE.value,
        ],
        executed_analyzers=[],
        measurements={
            AnalysisCapability.LOUDNESS.value: loudness,
            AnalysisCapability.LEVELS.value: {"crest_factor_db": crest_factor_db},
            AnalysisCapability.TEXTURE.value: texture,
        },
        content_sha256=("a" if name == "baseline.wav" else "b") * 64,
    )


def _goal(**overrides: float | None) -> CleanLoudnessGoal:
    values: dict[str, float | None] = {
        "min_loudness_gain_lu": 1.0,
        "true_peak_ceiling_dbtp": -0.3,
        "max_crest_factor_loss_db": 1.0,
        "max_loudness_range_loss_lu": 1.5,
        "max_energy_above_8khz_fraction_increase": 0.04,
    }
    values.update(overrides)
    return CleanLoudnessGoal(**values)  # type: ignore[arg-type]


def test_keeps_candidate_that_meets_goal_inside_guardrails() -> None:
    baseline = _report(name="baseline.wav")
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-8.8,
        true_peak_dbtp=-0.5,
        crest_factor_db=7.4,
        loudness_range_lu=5.5,
        energy_above_8khz_fraction=0.12,
    )
    result = evaluate_clean_loudness_candidate(baseline, candidate, goal=_goal())

    assert result["schema_version"] == CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION
    assert result["mutation_effect_state"] == "NOT_STARTED"
    assert result["decision"]["status"] == "keep"
    assert result["decision"]["journal_status"] == "keep"
    assert result["evidence"]["integrated_lufs"]["delta_candidate_minus_baseline"] == pytest.approx(1.2)
    assert {item["status"] for item in result["guardrails"]} == {"pass"}


def test_rejects_true_peak_ceiling_violation_even_when_louder() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-8.5,
        true_peak_dbtp=-0.1,
        crest_factor_db=7.5,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "reject"
    assert "guardrail_failed:true_peak_ceiling" in result["decision"]["reason_codes"]


def test_rejects_excessive_crest_factor_loss() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-8.5,
        true_peak_dbtp=-0.6,
        crest_factor_db=6.5,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "reject"
    assert "guardrail_failed:crest_factor_loss" in result["decision"]["reason_codes"]


def test_refines_positive_gain_below_requested_goal() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-9.6,
        true_peak_dbtp=-0.8,
        crest_factor_db=7.6,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "refine"
    assert result["decision"]["journal_status"] == "refine"
    assert result["decision"]["reason_codes"] == ["positive_loudness_gain_below_goal"]


def test_rejects_candidate_with_no_positive_loudness_gain() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-10.2,
        true_peak_dbtp=-1.1,
        crest_factor_db=8.1,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "reject"
    assert result["decision"]["reason_codes"] == ["no_positive_loudness_gain"]


def test_fails_closed_when_configured_guardrail_evidence_is_missing() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-8.5,
        true_peak_dbtp=-0.6,
        crest_factor_db=7.5,
        energy_above_8khz_fraction=None,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "inconclusive"
    assert result["decision"]["journal_status"] is None
    assert result["missing_required_evidence"] == [
        "candidate.energy_above_8khz_fraction"
    ]
    assert result["guardrails"] == []


def test_rejects_configured_high_frequency_energy_increase() -> None:
    candidate = _report(
        name="candidate.wav",
        integrated_lufs=-8.5,
        true_peak_dbtp=-0.6,
        crest_factor_db=7.5,
        energy_above_8khz_fraction=0.16,
    )
    result = evaluate_clean_loudness_candidate(
        _report(name="baseline.wav"), candidate, goal=_goal()
    )

    assert result["decision"]["status"] == "reject"
    assert (
        "guardrail_failed:energy_above_8khz_fraction_increase"
        in result["decision"]["reason_codes"]
    )


def test_goal_requires_explicit_finite_nonnegative_tolerances() -> None:
    with pytest.raises(CleanLoudnessEvaluationError):
        _goal(max_crest_factor_loss_db=-0.1)
    with pytest.raises(CleanLoudnessEvaluationError):
        _goal(min_loudness_gain_lu=float("nan"))


def test_load_analysis_report_round_trips_json(tmp_path) -> None:
    report = _report(name="baseline.wav")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report.to_dict()), encoding="utf-8")

    loaded = load_analysis_report(path)

    assert loaded.source_name == "baseline.wav"
    assert loaded.content_sha256 == "a" * 64


def test_load_analysis_report_rejects_unknown_schema(tmp_path) -> None:
    report = _report(name="baseline.wav").to_dict()
    report["schema_version"] = "future/v9"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(CleanLoudnessEvaluationError, match="unsupported analysis schema"):
        load_analysis_report(path)
