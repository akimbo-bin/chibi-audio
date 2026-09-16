from __future__ import annotations

import json
from pathlib import Path

import pytest

import chibi_audio.artifact_workflows as workflows_module
from chibi_audio.artifact_workflows import ArtifactWorkflowBridge, ArtifactWorkflowError


def test_level_match_bridge_confines_sources_and_returns_relative_outputs(monkeypatch, tmp_path: Path) -> None:
    left = tmp_path / "captures" / "left.wav"
    right = tmp_path / "captures" / "right.wav"
    left.parent.mkdir(parents=True)
    left.write_bytes(b"left")
    right.write_bytes(b"right")
    calls = {}

    def fake_create_level_matched_ab(**kwargs):
        calls.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True)
        left_out = output_dir / "proof__A-level-matched.wav"
        right_out = output_dir / "proof__B-level-matched.wav"
        left_out.write_bytes(b"left matched")
        right_out.write_bytes(b"right matched")
        manifest = output_dir / "proof__level-matched-ab.json"
        manifest.write_text(
            json.dumps(
                {
                    "comparison_id": "proof",
                    "mode": "downward_to_quieter_integrated_loudness",
                    "no_upward_gain": True,
                    "target_lufs": -14.0,
                    "alignment": {"sample_rate": 48000, "channels": 2, "samples": 100},
                    "verification": {"observed_difference_lu": 0.0, "tolerance_lu": 0.15},
                    "variants": [
                        {
                            "label": "A",
                            "gain_db": -1.0,
                            "source": {"loudness": {"integrated_lufs": -13.0}},
                            "level_matched": {
                                "path": left_out.name,
                                "sha256": "a" * 64,
                                "probe": {"samples": 100},
                                "loudness": {"integrated_lufs": -14.0},
                            },
                        },
                        {
                            "label": "B",
                            "gain_db": 0.0,
                            "source": {"loudness": {"integrated_lufs": -14.0}},
                            "level_matched": {
                                "path": right_out.name,
                                "sha256": "b" * 64,
                                "probe": {"samples": 100},
                                "loudness": {"integrated_lufs": -14.0},
                            },
                        },
                    ],
                    "interpretation_note": "evidence only",
                }
            ),
            encoding="utf-8",
        )
        return manifest

    monkeypatch.setattr(workflows_module, "create_level_matched_ab", fake_create_level_matched_ab)
    bridge = ArtifactWorkflowBridge(tmp_path)
    result = bridge.create_level_matched_ab(
        left_artifact="captures/left.wav",
        right_artifact="captures/right.wav",
        comparison_id="proof",
    )

    assert calls["left"] == left.resolve()
    assert calls["right"] == right.resolve()
    assert calls["output_dir"] == tmp_path / "ab-comparisons" / "proof"
    assert result["effect_state"] == "STARTED_CONFIRMED"
    assert result["effect_type"] == "artifact_creation"
    assert result["manifest_artifact"] == "ab-comparisons/proof/proof__level-matched-ab.json"
    assert [item["source_artifact"] for item in result["variants"]] == [
        "captures/left.wav",
        "captures/right.wav",
    ]
    assert [item["level_matched_artifact"] for item in result["variants"]] == [
        "ab-comparisons/proof/proof__A-level-matched.wav",
        "ab-comparisons/proof/proof__B-level-matched.wav",
    ]
    assert str(tmp_path) not in json.dumps(result)


def test_level_match_bridge_rejects_absolute_escape_and_missing_sources(monkeypatch, tmp_path: Path) -> None:
    bridge = ArtifactWorkflowBridge(tmp_path)
    calls = []
    monkeypatch.setattr(workflows_module, "create_level_matched_ab", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(ArtifactWorkflowError, match="relative"):
        bridge.create_level_matched_ab(
            left_artifact=str((tmp_path / "absolute.wav").resolve()),
            right_artifact="right.wav",
            comparison_id="absolute",
        )
    with pytest.raises(ArtifactWorkflowError, match="escapes"):
        bridge.create_level_matched_ab(
            left_artifact="../outside.wav",
            right_artifact="right.wav",
            comparison_id="escape",
        )
    with pytest.raises(ArtifactWorkflowError, match="does not exist"):
        bridge.create_level_matched_ab(
            left_artifact="missing.wav",
            right_artifact="right.wav",
            comparison_id="missing",
        )
    assert calls == []
