from __future__ import annotations

import pytest

from chibi_audio.analysis import (
    ALIGNMENT_SCHEMA_VERSION,
    AnalysisCapability,
    CaptureEventAlignmentError,
    align_capture_events,
)


def _capture(*taps: tuple[int, str, dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": "capture__manifest.json",
        "experiment_id": "alignment-test",
        "taps": [
            {
                "tap_id": tap_id,
                "source_label": label,
                "analysis": {"measurements": measurements},
            }
            for tap_id, label, measurements in taps
        ],
    }


def test_align_onsets_clusters_cross_tap_events_without_chain_bridging() -> None:
    capture = _capture(
        (1, "drums", {"audio.mir.onsets": {"onset_times_seconds": [1.00, 2.00]}}),
        (2, "bass", {"audio.mir.onsets": {"onset_times_seconds": [1.04, 2.20]}}),
        (3, "synth", {"audio.mir.onsets": {"onset_times_seconds": [1.08, 3.00]}}),
    )

    result = align_capture_events(capture, tolerance_seconds=0.05)

    assert result["schema_version"] == ALIGNMENT_SCHEMA_VERSION
    assert result["capability"] == AnalysisCapability.MIR_ONSETS.value
    assert result["event_count"] == 6
    assert result["cluster_count"] == 5
    assert result["cross_tap_cluster_count"] == 1

    first = result["clusters"][0]
    assert first["tap_ids"] == [1, 2]
    assert first["source_labels"] == ["bass", "drums"]
    assert first["time_seconds"] == pytest.approx(1.02)
    assert first["span_seconds"] == pytest.approx(0.04)
    assert first["cross_tap"] is True

    second = result["clusters"][1]
    assert second["tap_ids"] == [3]
    assert second["time_seconds"] == pytest.approx(1.08)
    assert all(cluster["span_seconds"] <= 0.05 + 1e-12 for cluster in result["clusters"])
    assert "do not prove causal" in result["interpretation_note"]


def test_align_transcription_preserves_note_evidence_and_reports_truncation() -> None:
    capture = _capture(
        (
            10,
            "bass",
            {
                "audio.mir.transcription": {
                    "notes_truncated": False,
                    "note_events": [
                        {"start_seconds": 0.50, "midi_note": 45, "pitch_class": "A", "amplitude": 0.9}
                    ],
                }
            },
        ),
        (
            11,
            "keys",
            {
                "audio.mir.transcription": {
                    "notes_truncated": True,
                    "note_events": [
                        {"start_seconds": 0.52, "midi_note": 69, "pitch_class": "A", "amplitude": 0.7}
                    ],
                }
            },
        ),
    )

    result = align_capture_events(
        capture,
        capability=AnalysisCapability.MIR_TRANSCRIPTION,
        tolerance_seconds=0.03,
    )

    assert result["cluster_count"] == 1
    assert result["cross_tap_cluster_count"] == 1
    assert result["truncated_tap_ids"] == [11]
    members = result["clusters"][0]["members"]
    assert [member["midi_note"] for member in members] == [45, 69]
    assert all(member["event_kind"] == "note_start" for member in members)


def test_align_structure_and_transient_event_shapes() -> None:
    structure = _capture(
        (
            1,
            "mix",
            {
                "audio.mir.structure": {
                    "boundary_candidates_seconds": [8.0],
                    "boundary_candidate_strength": [42.0],
                }
            },
        ),
        (
            2,
            "drums",
            {
                "audio.mir.structure": {
                    "boundary_candidates_seconds": [8.02],
                    "boundary_candidate_strength": [31.0],
                }
            },
        ),
    )
    result = align_capture_events(
        structure,
        capability="audio.mir.structure",
        tolerance_seconds=0.05,
    )
    assert result["clusters"][0]["members"][0]["event_kind"] == "structure_boundary"
    assert result["clusters"][0]["members"][0]["strength"] == pytest.approx(42.0)

    transients = _capture(
        (
            1,
            "kick",
            {
                "audio.transients": {
                    "strongest_event_time_seconds": 2.0,
                    "transient_to_body_db": 10.0,
                    "strongest_frame_rms_dbfs": -4.0,
                }
            },
        )
    )
    result = align_capture_events(
        transients,
        capability=AnalysisCapability.TRANSIENTS,
    )
    assert result["clusters"][0]["members"][0]["event_kind"] == "strongest_transient"
    assert result["clusters"][0]["members"][0]["transient_to_body_db"] == pytest.approx(10.0)


def test_align_refuses_missing_requested_measurement_and_bad_tolerance() -> None:
    capture = _capture((1, "bass", {"audio.levels": {"rms_dbfs": -12.0}}))

    with pytest.raises(CaptureEventAlignmentError, match="does not contain requested capability"):
        align_capture_events(capture)
    with pytest.raises(CaptureEventAlignmentError, match="between 0 and 5"):
        align_capture_events(capture, tolerance_seconds=6.0)
