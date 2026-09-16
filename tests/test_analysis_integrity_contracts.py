from chibi_audio.analysis import AnalysisCapability, AnalysisCost, AnalysisRequest, AudioAnalysisService


def test_integrity_capability_is_public_cheap_and_uses_request_silence_threshold() -> None:
    service = AudioAnalysisService()
    catalog = {
        capability: descriptor
        for descriptor in service.capability_report()
        for capability in descriptor["capabilities"]
    }
    descriptor = catalog["audio.integrity"]
    assert descriptor["name"] == "numpy_integrity"
    assert descriptor["cost"] == "CHEAP"
    assert descriptor["available"] is True

    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.INTEGRITY}),
        max_cost=AnalysisCost.CHEAP,
        silence_threshold_dbfs=-72.0,
    )
    plan = service.registry.plan(request)
    assert [analyzer.descriptor.name for analyzer in plan] == ["numpy_integrity"]
    assert request.cache_payload()["silence_threshold_dbfs"] == -72.0
