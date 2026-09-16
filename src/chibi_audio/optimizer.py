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



CLEAN_LOUDNESS_SWEEP_SCHEMA_VERSION = "chibi-audio-clean-loudness-sweep/v1"


@dataclass(frozen=True, slots=True)
class CleanLoudnessSweepPolicy:
    """Explicit bounds for interpreting an already-rendered master-drive sweep."""

    max_points: int
    min_marginal_lu_per_db: float

    def __post_init__(self) -> None:
        if isinstance(self.max_points, bool) or not isinstance(self.max_points, int) or self.max_points <= 0:
            raise CleanLoudnessEvaluationError("max_points must be a positive integer")
        value = self.min_marginal_lu_per_db
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CleanLoudnessEvaluationError("min_marginal_lu_per_db must be a finite number")
        if not math.isfinite(float(value)) or value < 0:
            raise CleanLoudnessEvaluationError("min_marginal_lu_per_db must be finite and >= 0")

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


def _report_identity(report: AnalysisReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "source_name": report.source_name,
        "source_size_bytes": report.source_size_bytes,
        "content_sha256": report.content_sha256,
    }


def _exact_content_sha256(report: AnalysisReport, *, context: str) -> str:
    value = report.content_sha256
    if not isinstance(value, str):
        raise CleanLoudnessEvaluationError(f"{context} requires exact content_sha256 evidence")
    normalized = value.lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise CleanLoudnessEvaluationError(f"{context} requires exact content_sha256 evidence")
    return normalized


def evaluate_clean_loudness_sweep(
    baseline: AnalysisReport,
    candidates: list[tuple[float, AnalysisReport]],
    *,
    goal: CleanLoudnessGoal,
    policy: CleanLoudnessSweepPolicy,
) -> dict[str, Any]:
    """Estimate the clean-loudness frontier from bounded, already-rendered candidates.

    This is evidence-only. It never renders, mutates Live, or writes journals. Once a
    point fails a configured guardrail, lacks required evidence, or falls below the
    configured marginal-efficiency threshold, later points cannot reopen the frontier.
    """
    if not candidates:
        raise CleanLoudnessEvaluationError("clean loudness sweep requires at least one candidate")
    if len(candidates) > policy.max_points:
        raise CleanLoudnessEvaluationError(
            f"clean loudness sweep has {len(candidates)} points, exceeding max_points={policy.max_points}"
        )

    baseline_content_sha256 = _exact_content_sha256(
        baseline, context="clean loudness sweep baseline"
    )
    normalized: list[tuple[float, AnalysisReport]] = []
    seen_drives: set[float] = set()
    seen_content_sha256: set[str] = {baseline_content_sha256}
    for raw_drive, report in candidates:
        if isinstance(raw_drive, bool) or not isinstance(raw_drive, (int, float)):
            raise CleanLoudnessEvaluationError("sweep drive values must be finite numbers")
        drive = float(raw_drive)
        if not math.isfinite(drive) or drive <= 0:
            raise CleanLoudnessEvaluationError("sweep drive values must be finite and > 0 dB")
        if drive in seen_drives:
            raise CleanLoudnessEvaluationError(f"duplicate sweep drive value: {drive}")
        content_sha256 = _exact_content_sha256(
            report, context=f"clean loudness sweep drive {drive}"
        )
        if content_sha256 in seen_content_sha256:
            raise CleanLoudnessEvaluationError(
                f"duplicate sweep audio content_sha256 at drive {drive}"
            )
        seen_drives.add(drive)
        seen_content_sha256.add(content_sha256)
        normalized.append((drive, report))
    normalized.sort(key=lambda item: item[0])

    baseline_lufs = _number(
        _measurement(baseline, AnalysisCapability.LOUDNESS), "integrated_lufs"
    )
    if baseline_lufs is None:
        return {
            "schema_version": CLEAN_LOUDNESS_SWEEP_SCHEMA_VERSION,
            "objective": "clean_loudness_knee",
            "mutation_effect_state": "NOT_STARTED",
            "goal": goal.as_dict(),
            "policy": policy.as_dict(),
            "baseline": _report_identity(baseline),
            "points": [],
            "clean_frontier": None,
            "knee": {
                "estimated": False,
                "reason": "missing_baseline_loudness",
                "last_clean_point": None,
                "first_degraded_point": None,
            },
            "interpretation_note": (
                "The sweep could not be interpreted because baseline integrated loudness evidence is missing. "
                "No Ableton mutation or render was attempted."
            ),
        }

    previous_drive = 0.0
    previous_lufs = baseline_lufs
    frontier_open = True
    last_clean_point: dict[str, Any] = {
        "drive_db": 0.0,
        "candidate": _report_identity(baseline),
    }
    first_degraded_point: dict[str, Any] | None = None
    stop_reason: str | None = None
    points: list[dict[str, Any]] = []

    for drive, report in normalized:
        evaluation = evaluate_clean_loudness_candidate(baseline, report, goal=goal)
        candidate_lufs = _number(
            _measurement(report, AnalysisCapability.LOUDNESS), "integrated_lufs"
        )
        marginal_lu_per_db = None
        if candidate_lufs is not None:
            marginal_lu_per_db = (candidate_lufs - previous_lufs) / (drive - previous_drive)

        decision_status = str(evaluation["decision"]["status"])
        point_reason: str | None = None
        clean_frontier_point = False
        if frontier_open:
            if decision_status == "inconclusive":
                point_reason = "inconclusive_evidence"
            elif decision_status == "reject":
                point_reason = "candidate_rejected"
            elif marginal_lu_per_db is None:
                point_reason = "missing_marginal_loudness_evidence"
            elif marginal_lu_per_db < policy.min_marginal_lu_per_db:
                point_reason = "marginal_efficiency_below_threshold"
            else:
                clean_frontier_point = True
                last_clean_point = {
                    "drive_db": drive,
                    "candidate": _report_identity(report),
                }

            if point_reason is not None:
                frontier_open = False
                stop_reason = point_reason
                first_degraded_point = {
                    "drive_db": drive,
                    "candidate": _report_identity(report),
                }

        points.append(
            {
                "drive_db": drive,
                "candidate": _report_identity(report),
                "marginal_lu_per_db": marginal_lu_per_db,
                "clean_frontier_point": clean_frontier_point,
                "frontier_stop_reason": point_reason,
                "evaluation": evaluation,
            }
        )
        previous_drive = drive
        if candidate_lufs is not None:
            previous_lufs = candidate_lufs

    if stop_reason is None:
        stop_reason = "highest_tested_point_remains_clean"

    return {
        "schema_version": CLEAN_LOUDNESS_SWEEP_SCHEMA_VERSION,
        "objective": "clean_loudness_knee",
        "mutation_effect_state": "NOT_STARTED",
        "goal": goal.as_dict(),
        "policy": policy.as_dict(),
        "baseline": _report_identity(baseline),
        "points": points,
        "clean_frontier": last_clean_point,
        "knee": {
            "estimated": first_degraded_point is not None,
            "reason": stop_reason,
            "last_clean_point": last_clean_point,
            "first_degraded_point": first_degraded_point,
        },
        "interpretation_note": (
            "This estimates a clean-loudness frontier from already-rendered evidence only. "
            "It does not authorize, perform, or replay any Ableton mutation or render."
        ),
    }
