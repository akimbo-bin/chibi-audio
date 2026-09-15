from __future__ import annotations

import pytest

from chibi_audio.analysis import (
    CaptureSpectralOverlapError,
    SPECTRAL_OVERLAP_SCHEMA_VERSION,
    SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION,
    compare_capture_spectral_overlap,
    compare_capture_spectral_overlap_timeline,
)


def _tap(
    tap_id: int,
    label: str,
    bands: dict[str, float],
    *,
    rms_dbfs: float | None = None,
) -> dict[str, object]:
    measurements: dict[str, object] = {
        "audio.spectrum": {"band_energy_fraction": bands},
    }
    if rms_dbfs is not None:
        measurements["audio.levels"] = {"rms_dbfs": rms_dbfs}
    return {
        "tap_id": tap_id,
        "source_label": label,
        "analysis": {"measurements": measurements},
    }


def _timeline_tap(
    tap_id: int,
    label: str,
    rows: list[tuple[float, dict[str, float]]],
) -> dict[str, object]:
    return {
        "tap_id": tap_id,
        "source_label": label,
        "analysis": {
            "measurements": {
                "audio.spectrum.timeline": {
                    "timeline": [
                        {"time_seconds": time_seconds, "band_energy_fraction": bands}
                        for time_seconds, bands in rows
                    ]
                }
            }
        },
    }


def _capture(*taps: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": "capture__manifest.json",
        "experiment_id": "overlap-test",
        "taps": list(taps),
    }


def test_capture_spectral_overlap_ranks_similar_broad_band_occupancy() -> None:
    capture = _capture(
        _tap(1, "bass", {"bass": 0.80, "mid": 0.20, "presence": 0.0}, rms_dbfs=-12.0),
        _tap(2, "kick", {"bass": 0.70, "mid": 0.30, "presence": 0.0}, rms_dbfs=-9.0),
        _tap(3, "hat", {"bass": 0.0, "mid": 0.10, "presence": 0.90}, rms_dbfs=-18.0),
    )

    result = compare_capture_spectral_overlap(capture, dominant_band_limit=2)

    assert result["schema_version"] == SPECTRAL_OVERLAP_SCHEMA_VERSION
    assert result["pair_count"] == 3
    strongest = result["pairs"][0]
    assert {strongest["left"]["source_label"], strongest["right"]["source_label"]} == {"bass", "kick"}
    assert strongest["spectral_overlap_coefficient"] == pytest.approx(0.90)
    assert strongest["spectral_cosine_similarity"] > 0.97
    assert strongest["right_minus_left_rms_db"] == pytest.approx(3.0)
    assert strongest["dominant_overlapping_bands"][0]["band"] == "bass"
    assert "not proof" in result["interpretation_note"]


def test_capture_spectral_overlap_normalizes_only_pair_common_bands() -> None:
    capture = _capture(
        _tap(1, "one", {"bass": 0.5, "mid": 0.5, "air": 0.0}),
        _tap(2, "two", {"bass": 0.25, "mid": 0.25, "presence": 0.5}),
    )

    pair = compare_capture_spectral_overlap(capture)["pairs"][0]

    assert pair["common_bands"] == ["bass", "mid"]
    assert pair["spectral_overlap_coefficient"] == pytest.approx(1.0)
    assert pair["spectral_cosine_similarity"] == pytest.approx(1.0)


def test_capture_spectral_overlap_fails_closed_when_a_tap_lacks_spectrum() -> None:
    capture = _capture(
        _tap(1, "bass", {"bass": 1.0}),
        {
            "tap_id": 2,
            "source_label": "missing",
            "analysis": {"measurements": {"audio.levels": {"rms_dbfs": -10.0}}},
        },
    )

    with pytest.raises(CaptureSpectralOverlapError, match="audio.spectrum"):
        compare_capture_spectral_overlap(capture)


def test_capture_spectral_overlap_validates_schema_pair_count_and_bounds() -> None:
    with pytest.raises(CaptureSpectralOverlapError, match="unsupported"):
        compare_capture_spectral_overlap({"schema_version": "wrong", "taps": []})
    with pytest.raises(CaptureSpectralOverlapError, match="at least two"):
        compare_capture_spectral_overlap(_capture(_tap(1, "only", {"bass": 1.0})))
    with pytest.raises(CaptureSpectralOverlapError, match="between 1 and 16"):
        compare_capture_spectral_overlap(
            _capture(_tap(1, "one", {"bass": 1.0}), _tap(2, "two", {"bass": 1.0})),
            dominant_band_limit=0,
        )


def test_timeline_overlap_localizes_strongest_shared_band_moments() -> None:
    capture = _capture(
        _timeline_tap(
            1,
            "bass",
            [
                (1.00, {"low": 0.90, "mid": 0.10, "high": 0.0}),
                (2.00, {"low": 0.20, "mid": 0.80, "high": 0.0}),
                (3.00, {"low": 0.10, "mid": 0.10, "high": 0.80}),
            ],
        ),
        _timeline_tap(
            2,
            "synth",
            [
                (1.02, {"low": 0.80, "mid": 0.20, "high": 0.0}),
                (2.01, {"low": 0.10, "mid": 0.90, "high": 0.0}),
                (3.04, {"low": 0.70, "mid": 0.20, "high": 0.10}),
            ],
        ),
    )

    result = compare_capture_spectral_overlap_timeline(
        capture,
        time_tolerance_seconds=0.05,
        max_moments_per_pair=2,
    )

    assert result["schema_version"] == SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION
    pair = result["pairs"][0]
    assert pair["matched_window_count"] == 3
    assert pair["unmatched_left_window_count"] == 0
    assert pair["unmatched_right_window_count"] == 0
    assert pair["overlap_coefficient"]["median"] == pytest.approx(0.90)
    assert len(pair["strongest_overlap_moments"]) == 2
    strongest = pair["strongest_overlap_moments"][0]
    assert strongest["spectral_overlap_coefficient"] == pytest.approx(0.90)
    assert strongest["dominant_overlapping_bands"][0]["band"] in {"low", "mid"}
    assert abs(strongest["right_minus_left_time_seconds"]) <= 0.05
    assert "not proof" in result["interpretation_note"]


def test_timeline_overlap_matching_is_one_to_one_and_never_reuses_a_window() -> None:
    capture = _capture(
        _timeline_tap(
            1,
            "left",
            [
                (1.00, {"low": 1.0}),
                (1.04, {"low": 1.0}),
            ],
        ),
        _timeline_tap(2, "right", [(1.02, {"low": 1.0})]),
    )

    pair = compare_capture_spectral_overlap_timeline(
        capture,
        time_tolerance_seconds=0.03,
    )["pairs"][0]

    assert pair["matched_window_count"] == 1
    assert pair["unmatched_left_window_count"] == 1
    assert pair["unmatched_right_window_count"] == 0
    assert len(pair["strongest_overlap_moments"]) == 1


def test_timeline_overlap_reports_unmatched_windows_when_sampling_times_do_not_align() -> None:
    capture = _capture(
        _timeline_tap(1, "left", [(1.0, {"low": 1.0}), (2.0, {"low": 1.0})]),
        _timeline_tap(2, "right", [(1.2, {"low": 1.0}), (2.2, {"low": 1.0})]),
    )

    pair = compare_capture_spectral_overlap_timeline(
        capture,
        time_tolerance_seconds=0.05,
    )["pairs"][0]

    assert pair["matched_window_count"] == 0
    assert pair["overlap_coefficient"] == {"p10": None, "median": None, "p90": None}
    assert pair["strongest_overlap_moments"] == []


def test_timeline_overlap_fails_closed_on_unsorted_rows_and_bad_bounds() -> None:
    unsorted = _capture(
        _timeline_tap(1, "one", [(2.0, {"low": 1.0}), (1.0, {"low": 1.0})]),
        _timeline_tap(2, "two", [(1.0, {"low": 1.0})]),
    )
    with pytest.raises(CaptureSpectralOverlapError, match="time-sorted"):
        compare_capture_spectral_overlap_timeline(unsorted)

    valid = _capture(
        _timeline_tap(1, "one", [(1.0, {"low": 1.0})]),
        _timeline_tap(2, "two", [(1.0, {"low": 1.0})]),
    )
    with pytest.raises(CaptureSpectralOverlapError, match="between 0 and 5"):
        compare_capture_spectral_overlap_timeline(valid, time_tolerance_seconds=6.0)
    with pytest.raises(CaptureSpectralOverlapError, match="between 1 and 16"):
        compare_capture_spectral_overlap_timeline(valid, max_moments_per_pair=0)
