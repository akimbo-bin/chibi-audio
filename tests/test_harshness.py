import pytest

np = pytest.importorskip("numpy")

from chibi_audio.harshness import analyze_harshness_array, compare_harshness_reports


def test_harshness_ranking_finds_bright_transient_burst():
    sample_rate = 48000
    time = np.arange(sample_rate * 2) / sample_rate
    signal = 0.08 * np.sin(2.0 * np.pi * 500.0 * time)

    start = sample_rate
    end = sample_rate + int(0.06 * sample_rate)
    burst_time = np.arange(end - start) / sample_rate
    signal[start:end] += (
        0.7
        * np.sin(2.0 * np.pi * 9000.0 * burst_time)
        * np.hanning(end - start)
    )

    report = analyze_harshness_array(
        np.column_stack([signal, signal]),
        sample_rate,
        top_events=4,
    )
    assert report["metric_status"].startswith("relative_diagnostic")
    assert report["events"]
    assert 0.90 <= report["events"][0]["start_s"] <= 1.08
    assert report["events"][0]["high_6_20k_pct"] > 10.0


def test_harshness_comparison_is_explicitly_relative():
    quiet = {
        "summary": {
            "p95_high_6_20k_pct": 1,
            "p95_centroid_hz": 1000,
            "p95_sharpness_proxy": 1,
        },
        "events": [{"score": 0.2, "start_s": 0.5}],
    }
    bright = {
        "summary": {
            "p95_high_6_20k_pct": 20,
            "p95_centroid_hz": 7000,
            "p95_sharpness_proxy": 3,
        },
        "events": [{"score": 0.9, "start_s": 1.0}],
    }
    result = compare_harshness_reports({"quiet": quiet, "bright": bright})
    assert result["ranking"][0]["label"] == "bright"
    assert "Relative diagnostic" in result["warning"]
