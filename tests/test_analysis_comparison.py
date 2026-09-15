from __future__ import annotations

import pytest

from chibi_audio.analysis import AnalysisReport, compare_reports


def _report(name: str, measurements: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=123,
        requested_capabilities=sorted(measurements),
        executed_analyzers=[],
        measurements=measurements,
        content_sha256=("ab" if name == "left.wav" else "cd") * 32,
        analysis_key=("12" if name == "left.wav" else "34") * 32,
    )


def test_comparison_reports_right_minus_left_for_mix_evidence() -> None:
    left = _report(
        "left.wav",
        {
            "audio.levels": {
                "sample_peak_dbfs": -3.0,
                "rms_dbfs": -12.0,
                "crest_factor_db": 9.0,
                "sample_over_count": 0,
            },
            "audio.loudness": {
                "integrated_lufs": -14.0,
                "true_peak_dbtp": -2.0,
                "loudness_range_lu": 5.0,
            },
            "audio.stereo": {
                "correlation": 0.8,
                "side_energy_fraction": 0.2,
                "side_to_mid_db": -6.0,
            },
            "audio.spectrum": {
                "spectral_centroid_hz": 2500.0,
                "rolloff_hz": 9000.0,
                "band_energy_fraction": {"bass": 0.25, "presence": 0.12},
            },
        },
    )
    right = _report(
        "right.wav",
        {
            "audio.levels": {
                "sample_peak_dbfs": -1.0,
                "rms_dbfs": -9.5,
                "crest_factor_db": 8.5,
                "sample_over_count": 2,
            },
            "audio.loudness": {
                "integrated_lufs": -11.0,
                "true_peak_dbtp": -0.8,
                "loudness_range_lu": 4.0,
            },
            "audio.stereo": {
                "correlation": 0.65,
                "side_energy_fraction": 0.3,
                "side_to_mid_db": -3.0,
            },
            "audio.spectrum": {
                "spectral_centroid_hz": 3000.0,
                "rolloff_hz": 10000.0,
                "band_energy_fraction": {"bass": 0.20, "presence": 0.18},
            },
        },
    )

    result = compare_reports(left, right, left_label="build", right_label="drop")

    assert result["direction"] == "right_minus_left"
    assert result["left"]["label"] == "build"
    assert result["right"]["label"] == "drop"
    assert result["comparisons"]["audio.levels"]["rms_dbfs_delta"] == pytest.approx(2.5)
    assert result["comparisons"]["audio.loudness"]["integrated_lufs_delta"] == pytest.approx(3.0)
    assert result["comparisons"]["audio.stereo"]["side_energy_fraction_delta"] == pytest.approx(0.1)
    assert result["comparisons"]["audio.spectrum"]["spectral_centroid_hz_delta"] == pytest.approx(500.0)
    assert result["comparisons"]["audio.spectrum"]["band_energy_fraction_delta"]["bass"] == pytest.approx(-0.05)
    assert result["comparisons"]["audio.spectrum"]["band_energy_fraction_delta"]["presence"] == pytest.approx(0.06)


def test_tonal_comparison_returns_similarity_without_claiming_key() -> None:
    left = _report(
        "left.wav",
        {
            "audio.mir.tonal": {
                "chroma_profile": {"A": 0.8, "E": 0.2},
                "dominant_pitch_class_evidence": "A",
                "tonal_concentration": 0.8,
            }
        },
    )
    right = _report(
        "right.wav",
        {
            "audio.mir.tonal": {
                "chroma_profile": {"A": 0.7, "E": 0.3},
                "dominant_pitch_class_evidence": "A",
                "tonal_concentration": 0.7,
            }
        },
    )

    result = compare_reports(left, right)
    tonal = result["comparisons"]["audio.mir.tonal"]

    assert tonal["chroma_cosine_similarity"] > 0.98
    assert tonal["left_dominant_pitch_class_evidence"] == "A"
    assert tonal["right_dominant_pitch_class_evidence"] == "A"
    assert tonal["tonal_concentration_delta"] == pytest.approx(-0.1)
    assert "better/worse" in result["interpretation_note"]


def test_comparison_ignores_capabilities_not_present_on_both_sides() -> None:
    left = _report("left.wav", {"audio.levels": {"rms_dbfs": -10.0}})
    right = _report("right.wav", {"audio.loudness": {"integrated_lufs": -12.0}})

    result = compare_reports(left, right)

    assert result["common_capabilities"] == []
    assert result["comparisons"] == {}
