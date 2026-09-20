from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from chibi_audio.analysis import stress
from chibi_audio.analysis.stress import (
    MasterStressAttributionError,
    attribute_capture_master_stress,
)


def _write_manifest(tmp_path: Path, arrays: dict[str, np.ndarray]) -> Path:
    taps = []
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
    manifest = tmp_path / "capture.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "experiment_id": "stress-fixture", "taps": taps}),
        encoding="utf-8",
    )
    return manifest


def _synthetic_capture(sample_rate: int = 8000, seconds: float = 8.0):
    rng = np.random.default_rng(20260916)
    frames = int(sample_rate * seconds)
    time = np.arange(frames, dtype=np.float64) / sample_rate

    bass_env = 0.025 + 0.15 * np.square(0.5 + 0.5 * np.sin(2.0 * np.pi * 0.73 * time))
    drums_env = 0.045 + 0.035 * np.square(0.5 + 0.5 * np.sin(2.0 * np.pi * 1.37 * time + 0.9))
    bass = rng.normal(size=(frames, 2)) * bass_env[:, None]
    drums = rng.normal(size=(frames, 2)) * drums_env[:, None]
    premaster = bass + drums + rng.normal(scale=0.008, size=(frames, 2))

    stress_control = (bass_env - bass_env.min()) / (bass_env.max() - bass_env.min())
    attenuation_db = -3.5 * stress_control
    processed = premaster * np.power(10.0, attenuation_db / 20.0)[:, None]
    delay_frames = int(round(0.08 * sample_rate))
    master = np.zeros_like(processed)
    master[delay_frames:] = processed[:-delay_frames]
    return {
        "MASTER_PRE": premaster.astype(np.float32),
        "MASTER_POST": master.astype(np.float32),
        "BASS_POST": bass.astype(np.float32),
        "DRUMS_POST": drums.astype(np.float32),
    }, delay_frames


def _patch_audio_io(monkeypatch, arrays: dict[str, np.ndarray], *, sample_rate: int = 8000):
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

    monkeypatch.setattr(stress, "probe_audio", fake_probe)
    monkeypatch.setattr(stress, "decode_audio_segment", fake_decode)


def test_attributes_latency_corrected_master_stress_to_dominant_source(monkeypatch, tmp_path):
    arrays, _delay_frames = _synthetic_capture()
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)

    result = attribute_capture_master_stress(
        manifest,
        premaster_label="MASTER_PRE",
        master_label="MASTER_POST",
        source_labels=["BASS_POST", "DRUMS_POST"],
        window_ms=100.0,
        hop_ms=10.0,
        max_latency_ms=200.0,
        low_band_hz=250.0,
    )

    assert result["effect_state"] == "NOT_STARTED"
    assert result["alignment"]["post_delay_ms"] == pytest.approx(80.0, abs=10.1)
    assert result["alignment"]["envelope_correlation"] > 0.80
    assert result["master_chain"]["stress_p90_db"] > 0.2
    assert [row["source_label"] for row in result["sources"]] == ["BASS_POST", "DRUMS_POST"]
    bass, drums = result["sources"]
    assert bass["rms_correlation_to_stress"] > drums["rms_correlation_to_stress"]
    assert bass["rms_correlation_to_stress"] > 0.6
    assert bass["top_stress_rms_uplift_db"] > drums["top_stress_rms_uplift_db"]
    assert result["leaders"]["rms_correlation_to_stress"]["source_label"] == "BASS_POST"
    assert result["leaders"]["top_stress_rms_uplift_db"]["source_label"] == "BASS_POST"
    assert "no overall winner is inferred" in result["interpretation_note"]


def test_rejects_manifest_artifact_hash_change(monkeypatch, tmp_path):
    arrays, _ = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["taps"][0]["final"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    _patch_audio_io(monkeypatch, arrays)

    with pytest.raises(MasterStressAttributionError, match="SHA-256 changed"):
        attribute_capture_master_stress(
            manifest,
            premaster_label="MASTER_PRE",
            master_label="MASTER_POST",
            source_labels=["BASS_POST"],
        )


def test_rejects_missing_exact_sample_count(monkeypatch, tmp_path):
    arrays, _ = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)
    original_probe = stress.probe_audio

    def missing_count(path):
        result = dict(original_probe(path))
        if Path(path).name == "DRUMS_POST.wav":
            result["samples"] = None
        return result

    monkeypatch.setattr(stress, "probe_audio", missing_count)
    with pytest.raises(MasterStressAttributionError, match="exact sample counts"):
        attribute_capture_master_stress(
            manifest,
            premaster_label="MASTER_PRE",
            master_label="MASTER_POST",
            source_labels=["BASS_POST", "DRUMS_POST"],
        )


def test_refuses_ambiguous_or_duplicate_labels(monkeypatch, tmp_path):
    arrays, _ = _synthetic_capture(seconds=2.0)
    manifest = _write_manifest(tmp_path, arrays)
    _patch_audio_io(monkeypatch, arrays)

    with pytest.raises(MasterStressAttributionError, match="source_labels must be unique"):
        attribute_capture_master_stress(
            manifest,
            premaster_label="MASTER_PRE",
            master_label="MASTER_POST",
            source_labels=["BASS_POST", "BASS_POST"],
        )
    with pytest.raises(MasterStressAttributionError, match="must be distinct"):
        attribute_capture_master_stress(
            manifest,
            premaster_label="MASTER_PRE",
            master_label="MASTER_POST",
            source_labels=["MASTER_POST"],
        )
