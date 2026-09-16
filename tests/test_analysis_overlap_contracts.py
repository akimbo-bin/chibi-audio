from chibi_audio.analysis import (
    SPECTRAL_OVERLAP_SCHEMA_VERSION,
    SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION,
    compare_capture_spectral_overlap,
    compare_capture_spectral_overlap_timeline,
)


def test_overlap_helpers_have_distinct_stable_public_contracts() -> None:
    assert SPECTRAL_OVERLAP_SCHEMA_VERSION == "chibi-audio-capture-spectral-overlap/v1"
    assert (
        SPECTRAL_OVERLAP_TIMELINE_SCHEMA_VERSION
        == "chibi-audio-capture-spectral-overlap-timeline/v1"
    )
    assert callable(compare_capture_spectral_overlap)
    assert callable(compare_capture_spectral_overlap_timeline)
    assert compare_capture_spectral_overlap is not compare_capture_spectral_overlap_timeline
