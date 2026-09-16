from __future__ import annotations

import json
from pathlib import Path

import pytest

import chibi_audio.sidechain_compare as compare


def _install_fakes(monkeypatch, tmp_path: Path, *, same_trigger: bool = True):
    base = tmp_path / "baseline.json"
    cand = tmp_path / "candidate.json"
    base.write_text("{}", encoding="utf-8")
    cand.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        compare,
        "_load_manifest",
        lambda path: {"schema_version": 1, "experiment_id": "candidate" if path.name.startswith("candidate") else "baseline"},
    )

    def fake_tap(manifest_path, _manifest, label):
        side = "candidate" if manifest_path.name.startswith("candidate") else "baseline"
        sha = {
            ("baseline", "TRIGGER"): "a" * 64,
            ("candidate", "TRIGGER"): ("a" if same_trigger else "f") * 64,
            ("baseline", "PRE"): "b" * 64,
            ("candidate", "PRE"): "c" * 64,
            ("baseline", "POST"): "d" * 64,
            ("candidate", "POST"): "e" * 64,
        }[(side, label)]
        artifact = tmp_path / f"{side}-{label}.wav"
        artifact.write_bytes(b"wav")
        return {"tap_id": 1, "source_label": label, "artifact": artifact, "content_sha256": sha}

    monkeypatch.setattr(compare, "_tap_by_label", fake_tap)

    def fake_verify(path, **_kwargs):
        candidate = path.name.startswith("candidate")
        return {
            "aggregate": {
                "reduction_p90_db_median": 8.0 if candidate else 10.0,
                "peak_smoothed_reduction_db_median": 12.0 if candidate else 15.0,
                "duration_above_depth_ms_median": 60.0 if candidate else 70.0,
                "positive_reduction_db_ms_median": 900.0 if candidate else 1100.0,
                "effective_onset_ms_median": 30.0,
                "peak_time_ms_median": 50.0,
                "recovery_complete_ms_median": 120.0 if candidate else 130.0,
                "recovery_from_peak_ms_median": 70.0 if candidate else 80.0,
            },
            "events": [{"reference_chain_gain_db": -1.0}, {"reference_chain_gain_db": -0.8}],
        }

    monkeypatch.setattr(compare, "verify_sidechain_capture", fake_verify)

    metrics = {
        "baseline-PRE.wav": {"integrated_lufs": -12.0, "true_peak_dbtp": 1.5, "sample_peak_dbfs": 1.4, "rms_dbfs": -11.0, "crest_db": 12.4, "lra_lu": 3.0, "stereo_correlation": 0.90, "side_to_mid_db": -13.0},
        "baseline-POST.wav": {"integrated_lufs": -13.0, "true_peak_dbtp": 2.0, "sample_peak_dbfs": 1.9, "rms_dbfs": -12.2, "crest_db": 14.1, "lra_lu": 3.5, "stereo_correlation": 0.96, "side_to_mid_db": -18.0},
        "candidate-PRE.wav": {"integrated_lufs": -12.2, "true_peak_dbtp": 1.5, "sample_peak_dbfs": 1.4, "rms_dbfs": -11.2, "crest_db": 12.5, "lra_lu": 3.0, "stereo_correlation": 0.90, "side_to_mid_db": -13.0},
        "candidate-POST.wav": {"integrated_lufs": -13.0, "true_peak_dbtp": 1.6, "sample_peak_dbfs": 1.5, "rms_dbfs": -12.1, "crest_db": 13.8, "lra_lu": 3.4, "stereo_correlation": 0.95, "side_to_mid_db": -17.5},
    }
    monkeypatch.setattr(compare, "analyze_audio", lambda path: metrics[path.name])

    calls = []
    def fake_ab(**kwargs):
        calls.append(kwargs)
        out = Path(kwargs["output_dir"]) / f"{kwargs['comparison_id']}__level-matched-ab.json"
        out.write_text(json.dumps({"schema_version": "fake"}), encoding="utf-8")
        return out
    monkeypatch.setattr(compare, "create_level_matched_ab", fake_ab)
    return base, cand, calls


def test_compare_normalizes_each_variant_and_creates_level_matched_ab(monkeypatch, tmp_path):
    base, cand, calls = _install_fakes(monkeypatch, tmp_path)
    summary = compare.compare_sidechain_captures(
        base,
        cand,
        trigger_label="TRIGGER",
        target_pre_label="PRE",
        target_post_label="POST",
        output_dir=tmp_path / "out",
        comparison_id="proof",
    )
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["schema_version"] == compare.SIDECHAIN_COMPARISON_SCHEMA_VERSION
    assert payload["effect_state"] == "NOT_STARTED"
    assert payload["comparability"]["same_trigger_content"] is True
    assert payload["comparability"]["target_pre_byte_identical"] is False
    assert payload["candidate_minus_baseline"]["event_correlated"]["reduction_p90_db_median"] == -2.0
    assert payload["baseline"]["chain_transfer"]["integrated_loudness_lu"] == -1.0
    assert payload["candidate"]["chain_transfer"]["integrated_loudness_lu"] == pytest.approx(-0.8)
    assert payload["candidate_minus_baseline"]["normalized_chain_transfer"]["integrated_loudness_lu"] == pytest.approx(0.2)
    assert payload["headroom"]["candidate_relative_peak_headroom_change_db"] == pytest.approx(0.4)
    assert len(calls) == 1
    assert calls[0]["left_label"] == "baseline"
    assert calls[0]["right_label"] == "candidate"


def test_compare_refuses_different_trigger_stimulus_before_ab(monkeypatch, tmp_path):
    base, cand, calls = _install_fakes(monkeypatch, tmp_path, same_trigger=False)
    with pytest.raises(compare.SidechainComparisonError, match="different stimuli"):
        compare.compare_sidechain_captures(
            base,
            cand,
            trigger_label="TRIGGER",
            target_pre_label="PRE",
            target_post_label="POST",
            output_dir=tmp_path / "out",
            comparison_id="proof",
        )
    assert calls == []


def test_compare_refuses_summary_overwrite(monkeypatch, tmp_path):
    base, cand, _calls = _install_fakes(monkeypatch, tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "proof__sidechain-comparison.json").write_text("{}", encoding="utf-8")
    with pytest.raises(compare.SidechainComparisonError, match="refusing to overwrite"):
        compare.compare_sidechain_captures(
            base,
            cand,
            trigger_label="TRIGGER",
            target_pre_label="PRE",
            target_post_label="POST",
            output_dir=out,
            comparison_id="proof",
        )
