from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

from .analysis.models import AnalysisCapability, AnalysisReport, SCHEMA_VERSION


CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION = "chibi-audio-clean-loudness-evaluation/v1"


class CleanLoudnessEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CleanLoudnessGoal:
    """Explicit experiment guardrails for one louder-vs-baseline candidate."""

    min_loudness_gain_lu: float
    true_peak_ceiling_dbtp: float
    max_crest_factor_loss_db: float
    max_loudness_range_loss_lu: float | None = None
    max_energy_above_8khz_fraction_increase: float | None = None

    def __post_init__(self) -> None:
        values = {
            "min_loudness_gain_lu": self.min_loudness_gain_lu,
            "true_peak_ceiling_dbtp": self.true_peak_ceiling_dbtp,
            "max_crest_factor_loss_db": self.max_crest_factor_loss_db,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CleanLoudnessEvaluationError(f"{name} must be a finite number")
            if not math.isfinite(float(value)):
                raise CleanLoudnessEvaluationError(f"{name} must be a finite number")
        if self.min_loudness_gain_lu < 0:
            raise CleanLoudnessEvaluationError("min_loudness_gain_lu must be >= 0")
        if self.max_crest_factor_loss_db < 0:
            raise CleanLoudnessEvaluationError("max_crest_factor_loss_db must be >= 0")
        self._validate_optional_nonnegative(
            "max_loudness_range_loss_lu", self.max_loudness_range_loss_lu
        )
        self._validate_optional_nonnegative(
            "max_energy_above_8khz_fraction_increase",
            self.max_energy_above_8khz_fraction_increase,
        )

    @staticmethod
    def _validate_optional_nonnegative(name: str, value: float | None) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CleanLoudnessEvaluationError(f"{name} must be a finite number or None")
        if not math.isfinite(float(value)) or value < 0:
            raise CleanLoudnessEvaluationError(f"{name} must be finite and >= 0")

    def as_dict(self) -> dict[str, float | None]:
        return asdict(self)


def load_analysis_report(path: str | Path) -> AnalysisReport:
    report_path = Path(path)
    try:
        raw_text = report_path.read_text(encoding="utf-8-sig")
        raw = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanLoudnessEvaluationError(
            f"could not read analysis report: {report_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise CleanLoudnessEvaluationError("analysis report must contain a JSON object")
    report = AnalysisReport.from_dict(raw)
    if report.schema_version != SCHEMA_VERSION:
        raise CleanLoudnessEvaluationError(
            f"unsupported analysis schema: {report.schema_version!r}"
        )
    return report


def _measurement(report: AnalysisReport, capability: AnalysisCapability) -> dict[str, Any]:
    value = report.measurements.get(capability.value)
    return value if isinstance(value, dict) else {}


def _number(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _evidence_row(baseline: float | None, candidate: float | None) -> dict[str, float | None]:
    delta = None
    if baseline is not None and candidate is not None:
        delta = candidate - baseline
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta_candidate_minus_baseline": delta,
    }


def _guardrail(
    *,
    name: str,
    passed: bool,
    observed: float,
    limit: float,
    comparison: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "observed": observed,
        "limit": limit,
        "comparison": comparison,
    }


def evaluate_clean_loudness_candidate(
    baseline: AnalysisReport,
    candidate: AnalysisReport,
    *,
    goal: CleanLoudnessGoal,
) -> dict[str, Any]:
    """Evaluate one candidate without changing Live, audio files, or journals."""
    baseline_loudness = _measurement(baseline, AnalysisCapability.LOUDNESS)
    candidate_loudness = _measurement(candidate, AnalysisCapability.LOUDNESS)
    baseline_levels = _measurement(baseline, AnalysisCapability.LEVELS)
    candidate_levels = _measurement(candidate, AnalysisCapability.LEVELS)
    baseline_texture = _measurement(baseline, AnalysisCapability.TEXTURE)
    candidate_texture = _measurement(candidate, AnalysisCapability.TEXTURE)

    baseline_lufs = _number(baseline_loudness, "integrated_lufs")
    candidate_lufs = _number(candidate_loudness, "integrated_lufs")
    baseline_true_peak = _number(baseline_loudness, "true_peak_dbtp")
    candidate_true_peak = _number(candidate_loudness, "true_peak_dbtp")
    baseline_crest = _number(baseline_levels, "crest_factor_db")
    candidate_crest = _number(candidate_levels, "crest_factor_db")
    baseline_lra = _number(baseline_loudness, "loudness_range_lu")
    candidate_lra = _number(candidate_loudness, "loudness_range_lu")
    baseline_high8 = _number(baseline_texture, "energy_above_8khz_fraction")
    candidate_high8 = _number(candidate_texture, "energy_above_8khz_fraction")

    evidence = {
        "integrated_lufs": _evidence_row(baseline_lufs, candidate_lufs),
        "true_peak_dbtp": _evidence_row(baseline_true_peak, candidate_true_peak),
        "crest_factor_db": _evidence_row(baseline_crest, candidate_crest),
        "loudness_range_lu": _evidence_row(baseline_lra, candidate_lra),
        "energy_above_8khz_fraction": _evidence_row(baseline_high8, candidate_high8),
    }

    missing: list[str] = []
    required = {
        "baseline.integrated_lufs": baseline_lufs,
        "candidate.integrated_lufs": candidate_lufs,
        "candidate.true_peak_dbtp": candidate_true_peak,
        "baseline.crest_factor_db": baseline_crest,
        "candidate.crest_factor_db": candidate_crest,
    }
    for name, value in required.items():
        if value is None:
            missing.append(name)
    if goal.max_loudness_range_loss_lu is not None:
        if baseline_lra is None:
            missing.append("baseline.loudness_range_lu")
        if candidate_lra is None:
            missing.append("candidate.loudness_range_lu")
    if goal.max_energy_above_8khz_fraction_increase is not None:
        if baseline_high8 is None:
            missing.append("baseline.energy_above_8khz_fraction")
        if candidate_high8 is None:
            missing.append("candidate.energy_above_8khz_fraction")

    guardrails: list[dict[str, Any]] = []
    if not missing:
        assert baseline_lufs is not None
        assert candidate_lufs is not None
        assert candidate_true_peak is not None
        assert baseline_crest is not None
        assert candidate_crest is not None

        crest_loss = baseline_crest - candidate_crest
        guardrails.append(
            _guardrail(
                name="true_peak_ceiling",
                passed=candidate_true_peak <= goal.true_peak_ceiling_dbtp,
                observed=candidate_true_peak,
                limit=goal.true_peak_ceiling_dbtp,
                comparison="candidate <= limit",
            )
        )
        guardrails.append(
            _guardrail(
                name="crest_factor_loss",
                passed=crest_loss <= goal.max_crest_factor_loss_db,
                observed=crest_loss,
                limit=goal.max_crest_factor_loss_db,
                comparison="loss <= limit",
            )
        )
        if goal.max_loudness_range_loss_lu is not None:
            assert baseline_lra is not None and candidate_lra is not None
            lra_loss = baseline_lra - candidate_lra
            guardrails.append(
                _guardrail(
                    name="loudness_range_loss",
                    passed=lra_loss <= goal.max_loudness_range_loss_lu,
                    observed=lra_loss,
                    limit=goal.max_loudness_range_loss_lu,
                    comparison="loss <= limit",
                )
            )
        if goal.max_energy_above_8khz_fraction_increase is not None:
            assert baseline_high8 is not None and candidate_high8 is not None
            high8_increase = candidate_high8 - baseline_high8
            guardrails.append(
                _guardrail(
                    name="energy_above_8khz_fraction_increase",
                    passed=(
                        high8_increase
                        <= goal.max_energy_above_8khz_fraction_increase
                    ),
                    observed=high8_increase,
                    limit=goal.max_energy_above_8khz_fraction_increase,
                    comparison="increase <= limit",
                )
            )

    status: str
    reasons: list[str]
    if missing:
        status = "inconclusive"
        reasons = ["missing_required_evidence"]
    else:
        assert baseline_lufs is not None and candidate_lufs is not None
        loudness_gain = candidate_lufs - baseline_lufs
        failed = [row["name"] for row in guardrails if row["status"] == "fail"]
        if failed:
            status = "reject"
            reasons = [f"guardrail_failed:{name}" for name in failed]
        elif loudness_gain >= goal.min_loudness_gain_lu:
            status = "keep"
            reasons = ["loudness_goal_met_within_guardrails"]
        elif loudness_gain > 0:
            status = "refine"
            reasons = ["positive_loudness_gain_below_goal"]
        else:
            status = "reject"
            reasons = ["no_positive_loudness_gain"]

    return {
        "schema_version": CLEAN_LOUDNESS_EVALUATION_SCHEMA_VERSION,
        "objective": "clean_loudness",
        "mutation_effect_state": "NOT_STARTED",
        "goal": goal.as_dict(),
        "baseline": {
            "schema_version": baseline.schema_version,
            "source_name": baseline.source_name,
            "source_size_bytes": baseline.source_size_bytes,
            "content_sha256": baseline.content_sha256,
        },
        "candidate": {
            "schema_version": candidate.schema_version,
            "source_name": candidate.source_name,
            "source_size_bytes": candidate.source_size_bytes,
            "content_sha256": candidate.content_sha256,
        },
        "evidence": evidence,
        "missing_required_evidence": missing,
        "guardrails": guardrails,
        "decision": {
            "status": status,
            "journal_status": status if status in {"keep", "reject", "refine"} else None,
            "reason_codes": reasons,
        },
        "interpretation_note": (
            "This is an evidence gate for one explicit experiment goal, not a universal "
            "mastering target or subjective quality judgment. It performs no Ableton mutation."
        ),
    }


