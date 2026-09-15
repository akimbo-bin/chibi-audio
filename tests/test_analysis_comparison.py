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


def test_comparison_covers_production_pitch_transcription_and_semantics() -> None:
    left = _report(
        "left.wav",
        {
            "audio.transients": {
                "strongest_event_time_seconds": 1.0,
                "strongest_frame_rms_dbfs": -8.0,
                "transient_to_body_db": 9.0,
                "microdynamic_p95_to_p10_db": 12.0,
                "strongest_event_attack_10_to_90_ms": 18.0,
                "strongest_event_decay_to_minus_12db_ms": 140.0,
                "strong_rise_density_per_second": 2.0,
            },
            "audio.texture": {
                "spectral_flatness_mean": 0.10,
                "spectral_flux_mean": 0.20,
                "zero_crossing_fraction": 0.12,
                "energy_above_4khz_fraction": 0.25,
                "energy_above_8khz_fraction": 0.08,
            },
            "audio.stereo.bands": {
                "available": True,
                "bands": {
                    "low": {
                        "correlation_evidence": 0.95,
                        "side_energy_fraction": 0.05,
                        "side_to_mid_db": -12.0,
                    }
                },
            },
            "audio.mir.structure": {
                "boundary_candidates_seconds": [4.0, 8.0],
                "novelty_median": 2.0,
                "novelty_p95": 8.0,
                "local_tempo_evidence": {"median_bpm": 120.0, "p10_bpm": 118.0, "p90_bpm": 122.0},
            },
            "audio.mir.pitch": {
                "voiced_frame_fraction": 0.80,
                "median_hz": 440.0,
                "median_midi": 69.0,
                "pitch_range_p10_to_p90_semitones": 3.0,
                "median_voicing_probability": 0.90,
                "median_pitch_class_evidence": "A",
            },
            "audio.mir.transcription": {
                "note_count": 8,
                "peak_estimated_polyphony": 2,
                "pitch_midi_min": 57,
                "pitch_midi_max": 76,
                "duration_amplitude_weighted_pitch_class_profile": {"A": 0.7, "E": 0.3},
            },
            "audio.semantic": {
                "queries_ranked": [
                    {
                        "query": "bright metallic hi-hat",
                        "mean_cosine_similarity": 0.20,
                        "min_window_cosine_similarity": 0.10,
                        "max_window_cosine_similarity": 0.30,
                        "strongest_window": {"start_seconds": 1.0, "end_seconds": 11.0},
                    },
                    {
                        "query": "dark closed hi-hat",
                        "mean_cosine_similarity": 0.70,
                        "min_window_cosine_similarity": 0.60,
                        "max_window_cosine_similarity": 0.80,
                        "strongest_window": {"start_seconds": 3.0, "end_seconds": 13.0},
                    },
                ]
            },
        },
    )
    right = _report(
        "right.wav",
        {
            "audio.transients": {
                "strongest_event_time_seconds": 1.25,
                "strongest_frame_rms_dbfs": -6.0,
                "transient_to_body_db": 11.0,
                "microdynamic_p95_to_p10_db": 10.0,
                "strongest_event_attack_10_to_90_ms": 12.0,
                "strongest_event_decay_to_minus_12db_ms": 180.0,
                "strong_rise_density_per_second": 3.0,
            },
            "audio.texture": {
                "spectral_flatness_mean": 0.18,
                "spectral_flux_mean": 0.35,
                "zero_crossing_fraction": 0.20,
                "energy_above_4khz_fraction": 0.40,
                "energy_above_8khz_fraction": 0.15,
            },
            "audio.stereo.bands": {
                "available": True,
                "bands": {
                    "low": {
                        "correlation_evidence": 0.75,
                        "side_energy_fraction": 0.15,
                        "side_to_mid_db": -7.0,
                    }
                },
            },
            "audio.mir.structure": {
                "boundary_candidates_seconds": [4.0, 8.0, 12.0],
                "novelty_median": 3.0,
                "novelty_p95": 10.0,
                "local_tempo_evidence": {"median_bpm": 124.0, "p10_bpm": 121.0, "p90_bpm": 127.0},
            },
            "audio.mir.pitch": {
                "voiced_frame_fraction": 0.70,
                "median_hz": 466.16,
                "median_midi": 70.0,
                "pitch_range_p10_to_p90_semitones": 5.0,
                "median_voicing_probability": 0.85,
                "median_pitch_class_evidence": "A#",
            },
            "audio.mir.transcription": {
                "note_count": 11,
                "peak_estimated_polyphony": 3,
                "pitch_midi_min": 58,
                "pitch_midi_max": 79,
                "duration_amplitude_weighted_pitch_class_profile": {"A": 0.6, "E": 0.4},
            },
            "audio.semantic": {
                "queries_ranked": [
                    {
                        "query": "bright metallic hi-hat",
                        "mean_cosine_similarity": 0.65,
                        "min_window_cosine_similarity": 0.40,
                        "max_window_cosine_similarity": 0.80,
                        "strongest_window": {"start_seconds": 2.5, "end_seconds": 12.5},
                    },
                    {
                        "query": "noisy shaker",
                        "mean_cosine_similarity": 0.55,
                        "min_window_cosine_similarity": 0.30,
                        "max_window_cosine_similarity": 0.70,
                        "strongest_window": {"start_seconds": 5.0, "end_seconds": 15.0},
                    },
                ]
            },
        },
    )

    result = compare_reports(left, right)
    compared = result["comparisons"]

    assert compared["audio.transients"]["transient_to_body_db_delta"] == pytest.approx(2.0)
    assert compared["audio.transients"]["strongest_event_attack_10_to_90_ms_delta"] == pytest.approx(-6.0)
    assert compared["audio.texture"]["energy_above_8khz_fraction_delta"] == pytest.approx(0.07)
    assert compared["audio.stereo.bands"]["bands"]["low"]["correlation_evidence_delta"] == pytest.approx(-0.20)
    assert compared["audio.mir.structure"]["boundary_candidate_count_delta"] == 1
    assert compared["audio.mir.structure"]["local_tempo_median_bpm_delta"] == pytest.approx(4.0)
    assert compared["audio.mir.pitch"]["median_midi_delta_semitones"] == pytest.approx(1.0)
    assert compared["audio.mir.pitch"]["left_median_pitch_class_evidence"] == "A"
    assert compared["audio.mir.pitch"]["right_median_pitch_class_evidence"] == "A#"
    assert compared["audio.mir.transcription"]["note_count_delta"] == pytest.approx(3.0)
    assert compared["audio.mir.transcription"]["peak_estimated_polyphony_delta"] == pytest.approx(1.0)
    assert compared["audio.mir.transcription"]["pitch_class_profile_cosine_similarity"] > 0.98
    semantic = compared["audio.semantic"]
    assert semantic["common_queries"] == ["bright metallic hi-hat"]
    assert semantic["queries"]["bright metallic hi-hat"]["mean_cosine_similarity_delta"] == pytest.approx(0.45)
    assert semantic["queries"]["bright metallic hi-hat"]["strongest_window_start_seconds_delta"] == pytest.approx(1.5)
    assert "probability" in semantic["interpretation_note"]


def test_comparison_ignores_capabilities_not_present_on_both_sides() -> None:
    left = _report("left.wav", {"audio.levels": {"rms_dbfs": -10.0}})
    right = _report("right.wav", {"audio.loudness": {"integrated_lufs": -12.0}})

    result = compare_reports(left, right)

    assert result["common_capabilities"] == []
    assert result["comparisons"] == {}
