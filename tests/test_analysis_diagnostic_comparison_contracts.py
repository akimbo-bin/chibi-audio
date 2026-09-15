from chibi_audio.analysis import AnalysisReport, compare_reports


def _report(name: str, measurements: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=1,
        requested_capabilities=sorted(measurements),
        executed_analyzers=[],
        measurements=measurements,
    )


def test_unavailable_stereo_timeline_does_not_fabricate_numeric_deltas() -> None:
    left = _report(
        "mono-left.wav",
        {"audio.stereo.timeline": {"available": False, "source_channels": 1}},
    )
    right = _report(
        "mono-right.wav",
        {"audio.stereo.timeline": {"available": False, "source_channels": 1}},
    )

    result = compare_reports(left, right)
    stereo = result["comparisons"]["audio.stereo.timeline"]

    assert result["direction"] == "right_minus_left"
    assert stereo["left_available"] is False
    assert stereo["right_available"] is False
    assert stereo["correlation_median_delta"] is None
    assert stereo["side_energy_fraction_median_delta"] is None
    assert stereo["widest_sampled_side_energy_fraction_delta"] is None
