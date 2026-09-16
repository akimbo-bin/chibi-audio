import pytest

from chibi_audio.analysis import AnalysisReport, compare_reports


def _report(name: str, measurements: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=1,
        requested_capabilities=sorted(measurements),
        executed_analyzers=[],
        measurements=measurements,
    )


def test_compare_reports_includes_continuity_and_integrity_deltas() -> None:
    left = _report(
        "left.wav",
        {
            "audio.stereo.timeline": {
                "available": True,
                "correlation": {"p10": 0.4, "median": 0.8, "p90": 0.95},
                "side_energy_fraction": {"p10": 0.05, "median": 0.1, "p90": 0.2},
                "left_minus_right_rms_db": {"p10": -2.0, "median": -1.0, "p90": 0.0},
                "widest_sampled_window": {"side_energy_fraction": 0.25},
                "most_negative_correlation_window": {"correlation": -0.1},
            },
            "audio.loop.seam": {
                "available": True,
                "max_abs_endpoint_jump": 0.01,
                "endpoint_jump_relative_to_peak": 0.02,
                "max_abs_derivative_discontinuity": 0.04,
                "derivative_discontinuity_relative_to_peak": 0.08,
                "head_minus_tail_rms_db": -0.5,
                "head_tail_waveform_rmse_relative_to_peak": 0.1,
                "head_tail_waveform_correlation": 0.9,
            },
            "audio.integrity": {
                "max_abs_dc_offset": 0.01,
                "near_full_scale_frame_count": 2,
                "near_full_scale_run_count": 1,
                "sustained_silence_run_count": 1,
                "longest_sustained_silence_seconds": 0.1,
                "discontinuity_candidate_count": 2,
                "discontinuity_threshold_sample_step": 0.2,
            },
        },
    )
    right = _report(
        "right.wav",
        {
            "audio.stereo.timeline": {
                "available": True,
                "correlation": {"p10": 0.1, "median": 0.5, "p90": 0.9},
                "side_energy_fraction": {"p10": 0.1, "median": 0.2, "p90": 0.4},
                "left_minus_right_rms_db": {"p10": -1.0, "median": 1.0, "p90": 2.0},
                "widest_sampled_window": {"side_energy_fraction": 0.5},
                "most_negative_correlation_window": {"correlation": -0.5},
            },
            "audio.loop.seam": {
                "available": True,
                "max_abs_endpoint_jump": 0.03,
                "endpoint_jump_relative_to_peak": 0.06,
                "max_abs_derivative_discontinuity": 0.1,
                "derivative_discontinuity_relative_to_peak": 0.2,
                "head_minus_tail_rms_db": 0.5,
                "head_tail_waveform_rmse_relative_to_peak": 0.3,
                "head_tail_waveform_correlation": 0.6,
            },
            "audio.integrity": {
                "max_abs_dc_offset": 0.02,
                "near_full_scale_frame_count": 5,
                "near_full_scale_run_count": 2,
                "sustained_silence_run_count": 3,
                "longest_sustained_silence_seconds": 0.3,
                "discontinuity_candidate_count": 4,
                "discontinuity_threshold_sample_step": 0.3,
            },
        },
    )

    result = compare_reports(left, right)
    assert result["direction"] == "right_minus_left"

    stereo = result["comparisons"]["audio.stereo.timeline"]
    assert stereo["correlation_median_delta"] == pytest.approx(-0.3)
    assert stereo["side_energy_fraction_median_delta"] == pytest.approx(0.1)
    assert stereo["widest_sampled_side_energy_fraction_delta"] == pytest.approx(0.25)
    assert stereo["most_negative_correlation_delta"] == pytest.approx(-0.4)

    seam = result["comparisons"]["audio.loop.seam"]
    assert seam["max_abs_endpoint_jump_delta"] == pytest.approx(0.02)
    assert seam["max_abs_derivative_discontinuity_delta"] == pytest.approx(0.06)
    assert seam["head_tail_waveform_correlation_delta"] == pytest.approx(-0.3)

    integrity = result["comparisons"]["audio.integrity"]
    assert integrity["max_abs_dc_offset_delta"] == pytest.approx(0.01)
    assert integrity["near_full_scale_frame_count_delta"] == pytest.approx(3.0)
    assert integrity["sustained_silence_run_count_delta"] == pytest.approx(2.0)
    assert integrity["longest_sustained_silence_seconds_delta"] == pytest.approx(0.2)
    assert integrity["discontinuity_candidate_count_delta"] == pytest.approx(2.0)
