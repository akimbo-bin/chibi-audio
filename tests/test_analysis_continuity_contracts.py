from chibi_audio.analysis import AnalysisCapability, AnalysisCost, AnalysisRequest, AudioAnalysisService


def test_continuity_capabilities_are_public_cheap_and_independently_plannable() -> None:
    service = AudioAnalysisService()
    catalog = {
        capability: descriptor
        for descriptor in service.capability_report()
        for capability in descriptor["capabilities"]
    }

    assert catalog["audio.stereo.timeline"]["name"] == "numpy_stereo_timeline"
    assert catalog["audio.stereo.timeline"]["cost"] == "CHEAP"
    assert catalog["audio.loop.seam"]["name"] == "numpy_loop_seam"
    assert catalog["audio.loop.seam"]["cost"] == "CHEAP"

    for capability, analyzer_name in (
        (AnalysisCapability.STEREO_TIMELINE, "numpy_stereo_timeline"),
        (AnalysisCapability.LOOP_SEAM, "numpy_loop_seam"),
    ):
        plan = service.registry.plan(
            AnalysisRequest(capabilities=frozenset({capability}), max_cost=AnalysisCost.CHEAP)
        )
        assert [analyzer.descriptor.name for analyzer in plan] == [analyzer_name]
