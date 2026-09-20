from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .reference_separation import EXPECTED_STEMS, STEM_ANALYSIS_SCHEMA_VERSION


STEM_COMPARISON_SCHEMA_VERSION = "chibi-audio-reference-stem-comparison/v1"


class StemComparisonError(ValueError):
    pass


def _load(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = value
    else:
        path = Path(value).resolve()
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != STEM_ANALYSIS_SCHEMA_VERSION:
        raise StemComparisonError("unsupported stem-analysis schema")
    return payload


def _finite(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StemComparisonError(f"missing numeric field: {field}") from exc
    if not math.isfinite(number):
        raise StemComparisonError(f"non-finite numeric field: {field}")
    return number


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("stems") or []:
        role = str(row.get("role") or "")
        if role in result:
            raise StemComparisonError(f"duplicate stem role: {role}")
        if role not in EXPECTED_STEMS:
            raise StemComparisonError(f"unexpected stem role: {role}")
        result[role] = row
    if set(result) != set(EXPECTED_STEMS):
        raise StemComparisonError("stem analysis does not contain exactly the expected roles")
    return result


def _summary(row: dict[str, Any]) -> dict[str, float]:
    measurements = row.get("analysis", {}).get("measurements") or {}
    levels = measurements.get("audio.levels") or {}
    loudness = measurements.get("audio.loudness") or {}
    spectrum = measurements.get("audio.spectrum") or {}
    stereo = measurements.get("audio.stereo") or {}
    dynamics = measurements.get("audio.dynamics") or {}
    bands = spectrum.get("band_energy_fraction") or {}
    sub = _finite(bands.get("sub"), field="audio.spectrum.band_energy_fraction.sub")
    bass = _finite(bands.get("bass"), field="audio.spectrum.band_energy_fraction.bass")
    return {
        "integrated_lufs": _finite(loudness.get("integrated_lufs"), field="audio.loudness.integrated_lufs"),
        "true_peak_dbtp": _finite(loudness.get("true_peak_dbtp"), field="audio.loudness.true_peak_dbtp"),
        "rms_dbfs": _finite(levels.get("rms_dbfs"), field="audio.levels.rms_dbfs"),
        "crest_factor_db": _finite(levels.get("crest_factor_db"), field="audio.levels.crest_factor_db"),
        "low_band_20_250_fraction": sub + bass,
        "spectral_centroid_hz": _finite(spectrum.get("spectral_centroid_hz"), field="audio.spectrum.spectral_centroid_hz"),
        "stereo_correlation": _finite(stereo.get("correlation"), field="audio.stereo.correlation"),
        "side_to_mid_db": _finite(stereo.get("side_to_mid_db"), field="audio.stereo.side_to_mid_db"),
        "active_window_fraction": _finite(dynamics.get("active_window_fraction"), field="audio.dynamics.active_window_fraction"),
    }


def _deltas(baseline: dict[str, float], candidate: dict[str, float]) -> dict[str, float]:
    return {key: candidate[key] - baseline[key] for key in baseline}


def compare_stem_analyses(
    baseline: str | Path | dict[str, Any],
    candidate: str | Path | dict[str, Any],
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> dict[str, Any]:
    baseline_payload = _load(baseline)
    candidate_payload = _load(candidate)
    baseline_rows = _rows(baseline_payload)
    candidate_rows = _rows(candidate_payload)
    comparisons = []
    for role in EXPECTED_STEMS:
        before = _summary(baseline_rows[role])
        after = _summary(candidate_rows[role])
        comparisons.append(
            {
                "role": role,
                "baseline": before,
                "candidate": after,
                "candidate_minus_baseline": _deltas(before, after),
            }
        )

    largest_loudness = max(
        comparisons,
        key=lambda row: abs(row["candidate_minus_baseline"]["integrated_lufs"]),
    )
    largest_low_band = max(
        comparisons,
        key=lambda row: abs(row["candidate_minus_baseline"]["low_band_20_250_fraction"]),
    )
    return {
        "schema_version": STEM_COMPARISON_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "baseline": {"label": baseline_label, "source": baseline_payload.get("source")},
        "candidate": {"label": candidate_label, "source": candidate_payload.get("source")},
        "stems": comparisons,
        "evidence_summary": {
            "largest_absolute_integrated_lufs_change": {
                "role": largest_loudness["role"],
                "delta_lu": largest_loudness["candidate_minus_baseline"]["integrated_lufs"],
            },
            "largest_absolute_20_250_fraction_change": {
                "role": largest_low_band["role"],
                "delta_fraction": largest_low_band["candidate_minus_baseline"]["low_band_20_250_fraction"],
            },
        },
        "interpretation_note": (
            "Stem deltas are descriptive evidence from model-estimated separations. "
            "Separated stems may contain bleed or artifacts and should not be assumed to sum linearly to the master."
        ),
    }
