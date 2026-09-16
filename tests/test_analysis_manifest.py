from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import wave

import pytest

from chibi_audio.analysis import (
    AnalysisCapability,
    AnalysisRequest,
    CaptureManifestAnalysisError,
    analyze_capture_manifest,
)


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")


def _write_tone(path: Path, frequency: float, *, sample_rate: int = 8000) -> None:
    payload = bytearray()
    for index in range(sample_rate // 10):
        sample = 0.25 * math.sin(2.0 * math.pi * frequency * index / sample_rate)
        value = max(-32768, min(32767, round(sample * 32768)))
        payload.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))


def _artifact(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": path.name,
        "bytes": stat.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "modified_ns": stat.st_mtime_ns,
        "sample_rate": 8000,
        "channels": 2,
    }


def _manifest(tmp_path: Path) -> Path:
    first = tmp_path / "tap-1.wav"
    second = tmp_path / "tap-2.wav"
    _write_tone(first, 220.0)
    _write_tone(second, 880.0)
    manifest = {
        "schema_version": 1,
        "experiment_id": "analysis-manifest-test",
        "taps": [
            {"tap_id": 1, "source_label": "bass", "final": _artifact(first)},
            {"tap_id": 2, "source_label": "drums", "final": _artifact(second)},
        ],
    }
    path = tmp_path / "analysis-manifest-test__manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_manifest_analyzes_all_finalized_taps_and_reuses_capture_hash(tmp_path: Path) -> None:
    _require_ffmpeg()
    manifest_path = _manifest(tmp_path)
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["tap_id"]: item["final"]["sha256"] for item in source["taps"]}

    result = analyze_capture_manifest(
        manifest_path,
        AnalysisRequest(capabilities=frozenset({AnalysisCapability.LEVELS}), sample_rate=8000),
        cache_dir=tmp_path / "cache",
    )

    assert result["experiment_id"] == "analysis-manifest-test"
    assert [item["tap_id"] for item in result["taps"]] == [1, 2]
    for item in result["taps"]:
        assert item["content_sha256"] == expected[item["tap_id"]]
        assert item["analysis"]["content_sha256"] == expected[item["tap_id"]]
        assert item["analysis"]["analysis_key"] is not None
        assert "audio.levels" in item["analysis"]["measurements"]


def test_manifest_can_select_one_tap_without_analyzing_others(tmp_path: Path) -> None:
    _require_ffmpeg()
    manifest_path = _manifest(tmp_path)

    result = analyze_capture_manifest(
        manifest_path,
        AnalysisRequest(capabilities=frozenset({AnalysisCapability.METADATA}), sample_rate=8000),
        tap_ids=[2],
    )

    assert len(result["taps"]) == 1
    assert result["taps"][0]["tap_id"] == 2
    assert result["taps"][0]["source_label"] == "drums"


def test_manifest_refuses_stale_final_artifact_before_trusting_recorded_hash(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    stale = tmp_path / "tap-1.wav"
    with stale.open("ab") as handle:
        handle.write(b"changed-after-finalization")

    with pytest.raises(CaptureManifestAnalysisError, match="size changed"):
        analyze_capture_manifest(
            manifest_path,
            AnalysisRequest(capabilities=frozenset({AnalysisCapability.METADATA}), sample_rate=8000),
            tap_ids=[1],
        )


def test_manifest_refuses_missing_requested_tap(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)

    with pytest.raises(CaptureManifestAnalysisError, match="not present"):
        analyze_capture_manifest(
            manifest_path,
            AnalysisRequest(capabilities=frozenset({AnalysisCapability.METADATA}), sample_rate=8000),
            tap_ids=[99],
        )

def test_manifest_supports_legacy_cwd_relative_final_path(monkeypatch, tmp_path: Path) -> None:
    _require_ffmpeg()
    artifact = tmp_path / "legacy.wav"
    _write_tone(artifact, 330.0)
    manifest_dir = tmp_path / "nested"
    manifest_dir.mkdir()
    record = _artifact(artifact)
    record["path"] = artifact.name
    manifest = {
        "schema_version": 1,
        "experiment_id": "legacy-cwd-path",
        "taps": [{"tap_id": 1, "source_label": "legacy", "final": record}],
    }
    manifest_path = manifest_dir / "legacy__manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = analyze_capture_manifest(
        manifest_path,
        AnalysisRequest(capabilities=frozenset({AnalysisCapability.METADATA}), sample_rate=8000),
    )

    assert Path(result["taps"][0]["artifact_path"]) == artifact
