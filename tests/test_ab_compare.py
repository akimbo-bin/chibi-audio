from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import wave

import pytest

from chibi_audio.ab_compare import LevelMatchedAbError, create_level_matched_ab


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required for level-match integration tests")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_stereo_tone(
    path: Path,
    *,
    amplitude: float,
    frames: int = 96_000,
    sample_rate: int = 48_000,
    frequency: float = 440.0,
) -> Path:
    data = bytearray()
    for index in range(frames):
        sample = int(round(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency * index / sample_rate)))
        sample = max(-32767, min(32767, sample))
        data.extend(struct.pack("<hh", sample, sample))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data)
    return path


def test_create_level_matched_ab_is_downward_only_aligned_and_non_destructive(tmp_path: Path) -> None:
    _require_ffmpeg()
    left = _write_stereo_tone(tmp_path / "louder.wav", amplitude=0.50)
    right = _write_stereo_tone(tmp_path / "quieter.wav", amplitude=0.25)
    left_before_hash = _sha256(left)
    right_before_hash = _sha256(right)

    manifest_path = create_level_matched_ab(
        left=left,
        right=right,
        output_dir=tmp_path / "ab",
        comparison_id="drop-one",
        left_label="candidate",
        right_label="baseline",
    )

    assert _sha256(left) == left_before_hash
    assert _sha256(right) == right_before_hash

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "chibi-audio-level-matched-ab/v1"
    assert manifest["mode"] == "downward_to_quieter_integrated_loudness"
    assert manifest["no_upward_gain"] is True
    assert manifest["alignment"] == {"sample_rate": 48000, "channels": 2, "samples": 96000}
    assert manifest["verification"]["observed_difference_lu"] <= manifest["verification"]["tolerance_lu"]

    variants = {item["label"]: item for item in manifest["variants"]}
    candidate = variants["candidate"]
    baseline = variants["baseline"]
    assert candidate["gain_db"] < -5.5
    assert candidate["gain_db"] <= 0.0
    assert baseline["gain_db"] <= 1.0e-9
    assert abs(baseline["gain_db"]) < 0.1

    for variant in variants.values():
        output = manifest_path.parent / variant["level_matched"]["path"]
        assert output.is_file()
        assert variant["level_matched"]["sha256"] == _sha256(output)
        assert variant["level_matched"]["probe"]["samples"] == 96000
        assert "flt" in variant["level_matched"]["probe"]["sample_fmt"]
        assert variant["level_matched"]["probe"]["path"] == variant["level_matched"]["path"]

    with pytest.raises(LevelMatchedAbError, match="refusing to overwrite"):
        create_level_matched_ab(
            left=left,
            right=right,
            output_dir=tmp_path / "ab",
            comparison_id="drop-one",
            left_label="candidate",
            right_label="baseline",
        )


def test_create_level_matched_ab_refuses_unaligned_inputs_before_render(tmp_path: Path) -> None:
    _require_ffmpeg()
    left = _write_stereo_tone(tmp_path / "left.wav", amplitude=0.4, frames=48_000)
    right = _write_stereo_tone(tmp_path / "right.wav", amplitude=0.4, frames=47_999)

    with pytest.raises(LevelMatchedAbError, match="identical sample counts"):
        create_level_matched_ab(
            left=left,
            right=right,
            output_dir=tmp_path / "ab",
            comparison_id="unaligned",
        )

    assert not (tmp_path / "ab").exists()


def test_create_level_matched_ab_refuses_same_source_or_colliding_labels(tmp_path: Path) -> None:
    _require_ffmpeg()
    left = _write_stereo_tone(tmp_path / "left.wav", amplitude=0.4)
    right = _write_stereo_tone(tmp_path / "right.wav", amplitude=0.3)

    with pytest.raises(LevelMatchedAbError, match="distinct audio files"):
        create_level_matched_ab(
            left=left,
            right=left,
            output_dir=tmp_path / "same-source",
            comparison_id="same-source",
        )

    with pytest.raises(LevelMatchedAbError, match="labels must remain distinct"):
        create_level_matched_ab(
            left=left,
            right=right,
            output_dir=tmp_path / "labels",
            comparison_id="labels",
            left_label="A B",
            right_label="A-B",
        )


def test_create_level_matched_ab_cleans_outputs_if_manifest_write_fails(monkeypatch, tmp_path: Path) -> None:
    _require_ffmpeg()
    import chibi_audio.ab_compare as ab

    left = _write_stereo_tone(tmp_path / "left.wav", amplitude=0.5)
    right = _write_stereo_tone(tmp_path / "right.wav", amplitude=0.25)
    output_dir = tmp_path / "ab"

    def fail_manifest_write(*_args, **_kwargs):
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(ab, "_atomic_write_json", fail_manifest_write)

    with pytest.raises(RuntimeError, match="manifest write failed"):
        ab.create_level_matched_ab(
            left=left,
            right=right,
            output_dir=output_dir,
            comparison_id="cleanup-proof",
            left_label="candidate",
            right_label="baseline",
        )

    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_level_match_ab_cli_routes_to_artifact_creator(monkeypatch, tmp_path: Path, capsys) -> None:
    import chibi_audio.cli as cli

    manifest = tmp_path / "result.json"
    manifest.write_text("{\"ok\": true}\n", encoding="utf-8")
    calls = {}

    def fake_create_level_matched_ab(**kwargs):
        calls.update(kwargs)
        return manifest

    monkeypatch.setattr(cli, "create_level_matched_ab", fake_create_level_matched_ab)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "chibi-audio",
            "level-match-ab",
            "left.wav",
            "right.wav",
            "--output-dir",
            str(tmp_path / "ab"),
            "--comparison-id",
            "drop-proof",
            "--left-label",
            "candidate",
            "--right-label",
            "baseline",
        ],
    )

    cli.main()

    assert calls == {
        "left": "left.wav",
        "right": "right.wav",
        "output_dir": str(tmp_path / "ab"),
        "comparison_id": "drop-proof",
        "left_label": "candidate",
        "right_label": "baseline",
    }
    assert capsys.readouterr().out == "{\"ok\": true}\n"
