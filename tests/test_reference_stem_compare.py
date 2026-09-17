from __future__ import annotations

from copy import deepcopy

import pytest

from chibi_audio.reference_separation import EXPECTED_STEMS, STEM_ANALYSIS_SCHEMA_VERSION
from chibi_audio.reference_stem_compare import (
    STEM_COMPARISON_SCHEMA_VERSION,
    StemComparisonError,
    compare_stem_analyses,
)


def _stem(role: str, *, lufs: float, low: float, centroid: float) -> dict:
    return {
        "role": role,
        "analysis": {
            "measurements": {
                "audio.levels": {"rms_dbfs": lufs - 1.0, "crest_factor_db": 8.0},
                "audio.loudness": {"integrated_lufs": lufs, "true_peak_dbtp": -1.0},
                "audio.spectrum": {
                    "spectral_centroid_hz": centroid,
                    "band_energy_fraction": {"sub": low * 0.4, "bass": low * 0.6},
                },
                "audio.stereo": {"correlation": 0.9, "side_to_mid_db": -12.0},
                "audio.dynamics": {"active_window_fraction": 1.0},
            }
        },
    }


def _payload(offset: float = 0.0) -> dict:
    return {
        "schema_version": STEM_ANALYSIS_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "source": {"sha256": f"sha-{offset}"},
        "stems": [
            _stem("drums", lufs=-12.0 + offset, low=0.6, centroid=700.0),
            _stem("bass", lufs=-14.0 + offset * 2.0, low=0.95 + offset * 0.01, centroid=80.0),
            _stem("vocals", lufs=-18.0, low=0.1, centroid=1800.0),
            _stem("other", lufs=-20.0, low=0.2, centroid=1200.0),
        ],
    }


def test_compare_stem_analyses_reports_role_deltas_and_summary() -> None:
    result = compare_stem_analyses(_payload(), _payload(0.5), baseline_label="A", candidate_label="B")
    assert result["schema_version"] == STEM_COMPARISON_SCHEMA_VERSION
    assert result["effect_state"] == "NOT_STARTED"
    assert [row["role"] for row in result["stems"]] == list(EXPECTED_STEMS)
    bass = next(row for row in result["stems"] if row["role"] == "bass")
    assert bass["candidate_minus_baseline"]["integrated_lufs"] == pytest.approx(1.0)
    assert bass["candidate_minus_baseline"]["low_band_20_250_fraction"] == pytest.approx(0.005)
    assert result["evidence_summary"]["largest_absolute_integrated_lufs_change"]["role"] == "bass"
    assert "model-estimated" in result["interpretation_note"]


def test_compare_stem_analyses_rejects_missing_role() -> None:
    candidate = _payload(0.5)
    candidate["stems"] = candidate["stems"][:-1]
    with pytest.raises(StemComparisonError, match="expected roles"):
        compare_stem_analyses(_payload(), candidate)


def test_compare_stem_analyses_rejects_missing_measurement() -> None:
    candidate = deepcopy(_payload(0.5))
    candidate["stems"][0]["analysis"]["measurements"]["audio.spectrum"]["band_energy_fraction"].pop("sub")
    with pytest.raises(StemComparisonError, match="missing numeric field"):
        compare_stem_analyses(_payload(), candidate)
