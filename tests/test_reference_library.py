from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chibi_audio.reference_library import (
    REFERENCE_COMPARISON_SCHEMA_VERSION,
    REFERENCE_LIBRARY_SCHEMA_VERSION,
    ReferenceLibrary,
    ReferenceLibraryError,
    compare_reference_summaries,
)


class FakeReport:
    def __init__(self, digest: str):
        self.digest = digest

    def to_dict(self):
        return {
            "schema_version": "chibi-audio-analysis/v1",
            "content_sha256": self.digest,
            "measurements": {"audio.levels": {"rms_dbfs": -12.0}},
        }


class FakeService:
    def __init__(self):
        self.calls = []

    def analyze(self, path, request, *, cache_dir=None, content_sha256=None):
        self.calls.append(
            {
                "path": Path(path),
                "request": request,
                "cache_dir": Path(cache_dir) if cache_dir is not None else None,
                "content_sha256": content_sha256,
            }
        )
        return FakeReport(content_sha256)


def summary_for(path, **kwargs):
    size = Path(path).stat().st_size
    return {
        "integrated_lufs": -10.0 - size,
        "true_peak_dbtp": -1.0,
        "rms_dbfs": -12.0 - size,
        "crest_db": 7.0,
        "stereo_correlation": 0.8,
        "side_to_mid_db": -9.0,
        "loudest_window": {
            "start_s": 12.0,
            "end_s": 24.0,
            "rms_dbfs": -9.0 - size,
            "bands": {"20-50_pct": 20.0, "50-80_pct": 30.0, "80-150_pct": 10.0},
        },
    }


def test_register_is_local_sha_keyed_and_reuses_same_content(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"same-audio")
    second.write_bytes(b"same-audio")
    service = FakeService()
    library = ReferenceLibrary(tmp_path / "refs", service=service, summary_analyzer=summary_for)

    one = library.register(first, display_name="One", project="KISS", set_name="club")
    two = library.register(second, display_name="Alias", project="KISS", set_name="club")

    digest = hashlib.sha256(b"same-audio").hexdigest()
    assert one["content_sha256"] == digest
    assert one["reused_content"] is False
    assert two["reused_content"] is True
    payload = library.load()
    assert payload["schema_version"] == REFERENCE_LIBRARY_SCHEMA_VERSION
    assert list(payload["references"]) == [digest]
    assert payload["references"][digest]["names"] == ["Alias", "One"]
    assert len(payload["references"][digest]["locations"]) == 2
    assert payload["projects"]["KISS"]["sets"]["club"] == [digest]
    assert len(service.calls) == 2
    assert all(call["content_sha256"] == digest for call in service.calls)
    assert all(call["cache_dir"] == (tmp_path / "refs" / "analysis-cache").resolve() for call in service.calls)


def test_verify_detects_content_change_without_mutating_registry(tmp_path: Path) -> None:
    source = tmp_path / "ref.wav"
    source.write_bytes(b"original")
    library = ReferenceLibrary(tmp_path / "refs", service=FakeService(), summary_analyzer=summary_for)
    result = library.register(source, project="KISS")
    digest = result["content_sha256"]
    assert library.verify(digest)["verified"] is True

    source.write_bytes(b"changed")
    verification = library.verify(digest)
    assert verification["verified"] is False
    assert verification["locations"][0]["status"] == "CONTENT_CHANGED"
    assert digest in library.load()["references"]


def test_reference_sets_and_registration_validation(tmp_path: Path) -> None:
    source = tmp_path / "ref.wav"
    source.write_bytes(b"audio")
    library = ReferenceLibrary(tmp_path / "refs", service=FakeService(), summary_analyzer=summary_for)
    with pytest.raises(ReferenceLibraryError, match="set_name requires project"):
        library.register(source, set_name="club")
    library.register(source, display_name="Ref", project="KISS", set_name="club")
    rows = library.reference_set("KISS", "club")
    assert len(rows) == 1
    assert rows[0]["names"] == ["Ref"]
    with pytest.raises(ReferenceLibraryError, match="unknown reference set"):
        library.reference_set("KISS", "missing")


def test_comparison_is_descriptive_and_section_aware() -> None:
    candidate = {
        "integrated_lufs": -8.0,
        "true_peak_dbtp": -0.8,
        "rms_dbfs": -9.0,
        "crest_db": 8.0,
        "stereo_correlation": 0.7,
        "side_to_mid_db": -8.0,
        "loudest_window": {
            "start_s": 20.0,
            "end_s": 32.0,
            "rms_dbfs": -7.0,
            "bands": {"20-50_pct": 25.0, "50-80_pct": 25.0},
        },
    }
    reference = {
        "integrated_lufs": -9.5,
        "true_peak_dbtp": -1.0,
        "rms_dbfs": -10.0,
        "crest_db": 7.0,
        "stereo_correlation": 0.9,
        "side_to_mid_db": -10.0,
        "loudest_window": {
            "start_s": 40.0,
            "end_s": 52.0,
            "rms_dbfs": -8.0,
            "bands": {"20-50_pct": 20.0, "50-80_pct": 30.0},
        },
    }
    result = compare_reference_summaries(candidate, reference, candidate_label="KISS", reference_label="Ref")
    assert result["schema_version"] == REFERENCE_COMPARISON_SCHEMA_VERSION
    assert result["whole_track_delta_candidate_minus_reference"]["integrated_lufs"] == pytest.approx(1.5)
    assert result["loudest_window"]["rms_delta_db"] == pytest.approx(1.0)
    assert result["loudest_window"]["band_energy_percentage_point_delta"] == {
        "20-50_pct": pytest.approx(5.0),
        "50-80_pct": pytest.approx(-5.0),
    }
    assert "not a target" in result["interpretation_note"]


def test_compare_candidate_uses_named_set(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    candidate = tmp_path / "candidate.wav"
    reference.write_bytes(b"ref")
    candidate.write_bytes(b"candidate")
    library = ReferenceLibrary(tmp_path / "refs", service=FakeService(), summary_analyzer=summary_for)
    library.register(reference, display_name="Reference", project="KISS", set_name="main")
    result = library.compare_candidate(candidate, project="KISS", set_name="main", candidate_label="KISS")
    assert result["effect_state"] == "NOT_STARTED"
    assert result["comparison_count"] == 1
    assert result["comparisons"][0]["candidate_label"] == "KISS"
    assert result["comparisons"][0]["reference_label"] == "Reference"
