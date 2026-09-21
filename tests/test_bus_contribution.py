from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from chibi_audio.analysis import contribution
from chibi_audio.analysis.contribution import (
    BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION,
    BusContributionAttributionError,
    attribute_capture_bus_contribution,
)


def _synthetic_capture(sample_rate: int = 8000, seconds: float = 8.0):
    frames = int(sample_rate * seconds)
    time = np.arange(frames, dtype=np.float64) / float(sample_rate)

    persistent_env = 0.055 + 0.035 * (
        0.5 + 0.5 * np.sin(2.0 * np.pi * 0.73 * time)
    )
    persistent = persistent_env * np.sin(2.0 * np.pi * 90.0 * time)

    trigger_env = np.full(frames, 0.0005, dtype=np.float64)
    for center in np.arange(0.45, seconds, 0.9):
        distance = np.abs(time - center)
        trigger_env += 0.30 * np.exp(-0.5 * np.square(distance / 0.035))
        shoulder = np.abs(time - (center + 0.22))
        trigger_env += 0.012 * np.exp(-0.5 * np.square(shoulder / 0.06))
    trigger = trigger_env * np.sin(2.0 * np.pi * 70.0 * time)

    unrelated_env = 0.018 + 0.008 * (
        0.5 + 0.5 * np.sin(2.0 * np.pi * 1.31 * time + 0.4)
    )
    unrelated = unrelated_env * np.sin(2.0 * np.pi * 900.0 * time)

    bus = persistent + trigger + unrelated
    silent = np.zeros(frames, dtype=np.float64)

    def stereo(values):
        return np.column_stack((values, values)).astype(np.float32)

    return {
        "BUS_POST": stereo(bus),
        "PERSISTENT": stereo(persistent),
        "TRIGGER": stereo(trigger),
        "UNRELATED": stereo(unrelated),
        "SILENT": stereo(silent),
    }


def _write_manifest(tmp_path: Path, arrays: dict[str, np.ndarray]) -> Path:
    taps = []
    tap_targets = []
    for tap_id, (label, _audio) in enumerate(arrays.items(), start=1):
        artifact = tmp_path / f"{label}.wav"
        artifact.write_bytes((label + "-fixture").encode("ascii"))
        taps.append(
            {
                "tap_id": tap_id,
                "source_label": label,
                "final": {
                    "path": artifact.name,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                },
            }
        )
        tap_targets.append(
            {
                "tap_id": tap_id,
                "source_label": label,
                "track_name": label.replace("_", " "),
                "track_index": tap_id + 10,
                "track_id": tap_id + 1000,
                "mute": label == "SILENT",
                "solo": False,
            }
        )
    manifest = tmp_path / "capture.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_id": "bus-contribution-fixture",
                "taps": taps,
                "live_session": {
                    "mixer_state": {
                        "tap_targets": tap_targets,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _patch_audio_io(
    monkeypatch,
    arrays: dict[str, np.ndarray],
    *,
    sample_rate: int = 8000,
):
    by_name = {f"{label}.wav": audio for label, audio in arrays.items()}

    def fake_probe(path):
        audio = by_name[Path(path).name]
        return {
            "path": str(path),
            "sample_rate": sample_rate,
            "channels": audio.shape[1],
            "samples": audio.shape[0],
            "duration_s": audio.shape[0] / sample_rate,
        }

    def fake_decode(path, _request, *, sample_rate=None, channels=2):
        assert sample_rate == 8000
        assert channels == 2
        return by_name[Path(path).name]

    monkeypatch.setattr(contribution, "probe_audio", fake_probe)
    monkeypatch.setattr(contribution, "decode_audio_segment", fake_decode)


def test_attributes_persistent_and_sparse_sources_without_overall_winner(
    monkeypatch,
    tmp_path,
):
    arrays = _synthetic_capture()
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)

    result = attribute_capture_bus_contribution(
        manifest,
        bus_label="BUS_POST",
        source_labels=["PERSISTENT", "TRIGGER", "UNRELATED", "SILENT"],
    )

    assert result["schema_version"] == BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION
    assert result["effect_state"] == "NOT_STARTED"
    assert result["no_overall_winner"] is True
    assert result["reference_bus"]["track_name"] == "BUS POST"
    assert result["windowing"]["active_bus_window_count"] >= 20
    assert result["windowing"]["top_bus_threshold_dbfs"] < 0.0

    by_label = {row["source_label"]: row for row in result["sources"]}
    assert by_label["PERSISTENT"]["active_window_fraction"] > 0.95
    assert 0.05 < by_label["TRIGGER"]["active_window_fraction"] < 0.5
    assert by_label["TRIGGER"]["top_bus_active_fraction_delta"] > 0.1
    assert by_label["TRIGGER"]["top_bus_rms_uplift_db"] > 6.0
    assert by_label["UNRELATED"]["low_band_correlation_to_bus"] < 0.5

    silent = by_label["SILENT"]
    assert silent["mute"] is True
    assert silent["active_window_fraction"] == 0.0
    assert silent["rms_correlation_to_bus"] is None
    assert silent["low_band_correlation_to_bus"] is None
    assert silent["top_bus_rms_uplift_db"] is None
    assert silent["top_bus_low_band_uplift_db"] is None

    assert result["leaders"]["top_bus_rms_uplift_db"]["source_label"] == "TRIGGER"
    assert result["leaders"]["top_bus_active_fraction_delta"]["source_label"] == "TRIGGER"

    events = result["bus_events"]["events"]
    assert result["bus_events"]["time_reference"] == "capture_start"
    assert result["bus_events"]["minimum_separation_ms"] == 250.0
    assert 1 <= len(events) <= 8
    assert events[0]["rank"] == 1
    assert events[0]["bus_rms_dbfs"] >= events[-1]["bus_rms_dbfs"]
    assert all(0.0 <= event["center_time_s"] <= 8.0 for event in events)
    assert all(
        abs(left["center_time_s"] - right["center_time_s"]) >= 0.24
        for index, left in enumerate(events)
        for right in events[index + 1 :]
    )
    assert "no overall winner is inferred" in result["interpretation_note"]


def test_rejects_finalized_artifact_hash_change(monkeypatch, tmp_path):
    arrays = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["taps"][0]["final"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BusContributionAttributionError, match="SHA-256 changed"):
        attribute_capture_bus_contribution(
            manifest,
            bus_label="BUS_POST",
            source_labels=["PERSISTENT"],
        )


def test_rejects_mismatched_capture_shape(monkeypatch, tmp_path):
    arrays = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)
    original_probe = contribution.probe_audio

    def mismatched_probe(path):
        result = dict(original_probe(path))
        if Path(path).name == "TRIGGER.wav":
            result["samples"] = int(result["samples"]) - 1
        return result

    monkeypatch.setattr(contribution, "probe_audio", mismatched_probe)

    with pytest.raises(
        BusContributionAttributionError,
        match="identical sample rate, channels and sample count",
    ):
        attribute_capture_bus_contribution(
            manifest,
            bus_label="BUS_POST",
            source_labels=["PERSISTENT", "TRIGGER"],
        )


def test_rejects_duplicate_or_bus_source_labels(monkeypatch, tmp_path):
    arrays = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)

    with pytest.raises(BusContributionAttributionError, match="must be unique"):
        attribute_capture_bus_contribution(
            manifest,
            bus_label="BUS_POST",
            source_labels=["TRIGGER", "TRIGGER"],
        )

    with pytest.raises(BusContributionAttributionError, match="must be distinct"):
        attribute_capture_bus_contribution(
            manifest,
            bus_label="BUS_POST",
            source_labels=["BUS_POST"],
        )
