from __future__ import annotations

import pytest

from chibi_audio.analysis import AnalysisReport
from chibi_audio.analysis.sample_similarity import (
    SAMPLE_SIMILARITY_SCHEMA_VERSION,
    SampleSimilarityError,
    rank_sample_similarity,
)


def _report(name: str, measurements: dict[str, object]) -> AnalysisReport:
    return AnalysisReport(
        source_name=name,
        source_size_bytes=123,
        requested_capabilities=sorted(measurements),
        executed_analyzers=[],
        measurements=measurements,
        content_sha256=(name[0].encode().hex()[:2] or "aa") * 32,
    )


def _semantic(**scores: float) -> dict[str, object]:
    return {
        "queries_ranked": [
            {"query": query, "mean_cosine_similarity": score}
            for query, score in scores.items()
        ]
    }


def test_sample_similarity_keeps_rankings_separate_and_orders_each_axis() -> None:
    reference = _report(
        "reference.wav",
        {
            "audio.mir.timbre": {
                "mfcc_shape_mean": {"c1": 1.0, "c2": 0.0},
                "spectral_contrast_mean_db": {"band0": 1.0, "band1": 0.0},
            },
            "audio.spectrum": {"band_energy_fraction": {"bass": 0.8, "high": 0.2}},
            "audio.mir.tonal": {"chroma_profile": {"A": 0.8, "E": 0.2}},
            "audio.semantic": _semantic(dark=0.2, metallic=0.8),
        },
    )
    close = _report(
        "close.wav",
        {
            "audio.mir.timbre": {
                "mfcc_shape_mean": {"c1": 0.95, "c2": 0.05},
                "spectral_contrast_mean_db": {"band0": 0.9, "band1": 0.1},
            },
            "audio.spectrum": {"band_energy_fraction": {"bass": 0.75, "high": 0.25}},
            "audio.mir.tonal": {"chroma_profile": {"A": 0.75, "E": 0.25}},
            "audio.semantic": _semantic(dark=0.25, metallic=0.75),
        },
    )
    far = _report(
        "far.wav",
        {
            "audio.mir.timbre": {
                "mfcc_shape_mean": {"c1": 0.0, "c2": 1.0},
                "spectral_contrast_mean_db": {"band0": 0.0, "band1": 1.0},
            },
            "audio.spectrum": {"band_energy_fraction": {"bass": 0.1, "high": 0.9}},
            "audio.mir.tonal": {"chroma_profile": {"A": 0.1, "E": 0.9}},
            "audio.semantic": _semantic(dark=0.8, metallic=0.2),
        },
    )

    result = rank_sample_similarity(reference, [far, close])

    assert result["schema_version"] == SAMPLE_SIMILARITY_SCHEMA_VERSION
    assert result["candidate_count"] == 2
    rankings = result["rankings"]
    assert rankings["timbre_mfcc_shape_cosine"]["candidates"][0]["source_name"] == "close.wav"
    assert rankings["spectral_band_cosine"]["candidates"][0]["source_name"] == "close.wav"
    assert rankings["tonal_chroma_cosine"]["candidates"][0]["source_name"] == "close.wav"
    semantic = rankings["semantic_profile_mean_absolute_delta"]
    assert semantic["direction"] == "lower_is_more_similar"
    assert semantic["candidates"][0]["source_name"] == "close.wav"
    assert semantic["candidates"][0]["value"] == pytest.approx(0.05)
    assert "combined score" in result["interpretation_note"]


def test_sample_similarity_semantic_axis_uses_only_common_prompts() -> None:
    reference = _report("reference.wav", {"audio.semantic": _semantic(dark=0.2, bright=0.7)})
    candidate = _report("candidate.wav", {"audio.semantic": _semantic(dark=0.4, noisy=0.9)})

    result = rank_sample_similarity(reference, [candidate])
    semantic = result["candidates"][0]["evidence"]["semantic"]

    assert semantic["common_queries"] == ["dark"]
    assert semantic["common_query_count"] == 1
    assert semantic["mean_absolute_score_delta"] == pytest.approx(0.2)
    assert semantic["profile_cosine_similarity"] is None


def test_sample_similarity_keeps_candidates_without_shared_evidence_but_omits_them_from_rankings() -> None:
    reference = _report(
        "reference.wav",
        {"audio.mir.timbre": {"mfcc_shape_mean": {"c1": 1.0, "c2": 0.0}}},
    )
    candidate = _report("unknown.wav", {"audio.levels": {"rms_dbfs": -10.0}})

    result = rank_sample_similarity(reference, [candidate])

    assert result["candidates"][0]["available_axes"] == []
    assert result["rankings"]["timbre_mfcc_shape_cosine"]["candidates"] == []
    assert result["rankings"]["semantic_profile_mean_absolute_delta"]["candidates"] == []


def test_sample_similarity_requires_at_least_one_analysis_report_candidate() -> None:
    reference = _report("reference.wav", {})
    with pytest.raises(SampleSimilarityError, match="at least one"):
        rank_sample_similarity(reference, [])
    with pytest.raises(SampleSimilarityError, match="AnalysisReport"):
        rank_sample_similarity(reference, [object()])  # type: ignore[list-item]
