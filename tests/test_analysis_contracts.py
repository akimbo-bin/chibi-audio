from chibi_audio.analysis import AnalysisCapability, AnalysisCost, AnalysisRequest


def test_request_normalizes_json_facing_strings() -> None:
    request = AnalysisRequest(
        capabilities=frozenset({"audio.levels", "audio.spectrum"}),
        max_cost="MODERATE",
    )

    assert request.capabilities == frozenset(
        {AnalysisCapability.LEVELS, AnalysisCapability.SPECTRUM}
    )
    assert request.max_cost is AnalysisCost.MODERATE
    assert request.cache_payload()["max_cost"] == "MODERATE"
