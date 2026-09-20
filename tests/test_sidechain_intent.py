from __future__ import annotations

import pytest

from chibi_audio.sidechain_intent import (
    SIDECHAIN_INTENT_SCHEMA_VERSION,
    SidechainIntentError,
    propose_sidechain_intents,
)


def _tap(tap_id, label, global_bands, timeline_bands, *, rms_dbfs=-18.0):
    return {
        "tap_id": tap_id,
        "source_label": label,
        "analysis": {
            "measurements": {
                "audio.levels": {"rms_dbfs": rms_dbfs},
                "audio.spectrum": {"band_energy_fraction": global_bands},
                "audio.spectrum.timeline": {
                    "timeline": [
                        {"time_seconds": float(index), "band_energy_fraction": bands}
                        for index, bands in enumerate(timeline_bands)
                    ]
                },
            }
        },
    }


def _capture(*taps):
    return {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": "capture.json",
        "experiment_id": "intent-fixture",
        "taps": list(taps),
    }


def test_intent_proposes_frequency_selective_for_persistent_concentrated_overlap():
    source_rows = [
        {"low": 0.05, "low_mid": 0.25, "mid": 0.55, "high_mid": 0.15}
        for _ in range(10)
    ]
    target_rows = [
        {"low": 0.05, "low_mid": 0.35, "mid": 0.42, "high_mid": 0.18}
        for _ in range(10)
    ]
    result = propose_sidechain_intents(
        _capture(
            _tap(1, "VOX", source_rows[0], source_rows, rms_dbfs=-18.0),
            _tap(2, "FX", target_rows[0], target_rows, rms_dbfs=-28.0),
        ),
        source_label="VOX",
    )
    assert result["schema_version"] == SIDECHAIN_INTENT_SCHEMA_VERSION
    assert result["effect_state"] == "NOT_STARTED"
    row = result["candidates"][0]
    assert row["target_label"] == "FX"
    assert row["processing_class_proposal"] == "frequency_selective_duck"
    assert row["evidence_status"] == "FREQUENCY_SELECTIVE_DUCK_CANDIDATE"
    assert row["global"]["top3_overlap_share"] >= 0.75
    assert row["method_examples"] == ["external_sidechain_dynamic_eq", "spectral_carving"]


def test_intent_reports_no_action_when_overlap_stays_low():
    source_rows = [{"low": 0.0, "mid": 0.9, "high": 0.1} for _ in range(10)]
    bass_rows = [{"low": 0.95, "mid": 0.02, "high": 0.03} for _ in range(10)]
    result = propose_sidechain_intents(
        _capture(_tap(1, "VOX", source_rows[0], source_rows), _tap(2, "BASS", bass_rows[0], bass_rows)),
        source_label="VOX",
    )
    row = result["candidates"][0]
    assert row["processing_class_proposal"] == "none"
    assert row["evidence_status"] == "NO_ACTION_EVIDENCE"
    assert row["timeline"]["overlap_coefficient"]["p90"] <= result["heuristics"]["no_action_timeline_p90_max"]


def test_intent_proposes_event_selective_when_collisions_are_sporadic():
    source = {"low": 0.05, "low_mid": 0.25, "mid": 0.45, "high_mid": 0.25}
    low = {"low": 0.85, "low_mid": 0.10, "mid": 0.04, "high_mid": 0.01}
    high = {"low": 0.03, "low_mid": 0.27, "mid": 0.45, "high_mid": 0.25}
    target_rows = [low] * 8 + [high] * 2
    result = propose_sidechain_intents(
        _capture(_tap(1, "VOX", source, [source] * 10), _tap(2, "DRUMS", high, target_rows)),
        source_label="VOX",
    )
    row = result["candidates"][0]
    assert row["processing_class_proposal"] == "event_selective_duck"
    assert row["evidence_status"] == "EVENT_SELECTIVE_DUCK_CANDIDATE"
    assert row["timeline"]["overlap_coefficient"]["median"] <= result["heuristics"]["event_selective_timeline_median_max"]
    assert row["timeline"]["overlap_coefficient"]["p90"] >= result["heuristics"]["event_selective_timeline_p90_min"]


def test_intent_can_propose_full_band_when_overlap_is_broad_and_persistent():
    bands = {"sub": 1.0, "low": 1.0, "low_mid": 1.0, "mid": 1.0, "high_mid": 1.0, "high": 1.0, "air": 1.0}
    result = propose_sidechain_intents(
        _capture(_tap(1, "SRC", bands, [bands] * 10), _tap(2, "TARGET", bands, [bands] * 10)),
        source_label="SRC",
    )
    row = result["candidates"][0]
    assert row["processing_class_proposal"] == "full_band_gain_duck"
    assert row["evidence_status"] == "FULL_BAND_DUCK_CANDIDATE"
    assert row["global"]["top3_overlap_share"] < result["heuristics"]["full_band_top3_share_max"]


def test_intent_preserves_all_targets_and_orders_by_observed_median_overlap():
    source = {"low": 0.05, "low_mid": 0.25, "mid": 0.55, "high_mid": 0.15}
    fx = {"low": 0.05, "low_mid": 0.35, "mid": 0.42, "high_mid": 0.18}
    bass = {"low": 0.95, "low_mid": 0.03, "mid": 0.01, "high_mid": 0.01}
    result = propose_sidechain_intents(
        _capture(
            _tap(1, "VOX", source, [source] * 10),
            _tap(2, "FX", fx, [fx] * 10),
            _tap(3, "BASS", bass, [bass] * 10),
        ),
        source_label="VOX",
    )
    assert result["candidate_count"] == 2
    assert [row["target_label"] for row in result["candidates"]] == ["FX", "BASS"]
    assert result["evidence_order"] == "timeline_median_overlap_descending_then_p90"


def test_intent_fails_closed_on_duplicate_or_missing_labels():
    bands = {"low": 0.5, "mid": 0.5}
    duplicate = _capture(_tap(1, "VOX", bands, [bands] * 4), _tap(2, "VOX", bands, [bands] * 4))
    with pytest.raises(SidechainIntentError, match="must be unique"):
        propose_sidechain_intents(duplicate, source_label="VOX")

    valid = _capture(_tap(1, "VOX", bands, [bands] * 4), _tap(2, "FX", bands, [bands] * 4))
    with pytest.raises(SidechainIntentError, match="exactly one"):
        propose_sidechain_intents(valid, source_label="MISSING")
    with pytest.raises(SidechainIntentError, match="not present"):
        propose_sidechain_intents(valid, source_label="VOX", target_labels=["NOPE"])
