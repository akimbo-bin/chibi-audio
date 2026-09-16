from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import wave

import numpy as np
import pytest

from chibi_audio.sidechain_verify import SidechainVerificationError, verify_sidechain_capture


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe are required for rendered sidechain verification",
)


def _write_wav(path: Path, values: np.ndarray, sample_rate: int) -> dict[str, object]:
    clipped = np.clip(values, -0.999, 0.999)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    stereo = np.column_stack((pcm, pcm))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(stereo.tobytes())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stat = path.stat()
    return {
        "path": path.name,
        "sha256": digest,
        "bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _fixture(tmp_path: Path, *, duck: bool = True) -> Path:
    sample_rate = 8000
    duration = 5.0
    count = int(sample_rate * duration)
    time = np.arange(count, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(12345)
    amplitude = 0.15 * (0.75 + 0.20 * np.sin(2.0 * math.pi * 0.63 * time))
    target_pre = amplitude * rng.normal(0.0, 0.75, count)
    trigger = np.zeros(count, dtype=np.float64)
    gain = np.full(count, 0.70, dtype=np.float64)
    for event in (1.0, 2.0, 3.0, 4.0):
        start = int(event * sample_rate)
        trigger[start : start + int(0.004 * sample_rate)] = 0.80
        if duck:
            duck_start = start + int(0.030 * sample_rate)
            hold_end = duck_start + int(0.050 * sample_rate)
            recover_end = hold_end + int(0.060 * sample_rate)
            gain[duck_start:hold_end] *= 10.0 ** (-12.0 / 20.0)
            if recover_end > hold_end:
                curve_db = np.linspace(-12.0, 0.0, recover_end - hold_end, endpoint=False)
                gain[hold_end:recover_end] *= 10.0 ** (curve_db / 20.0)
    processed = target_pre * gain
    delay = int(0.012 * sample_rate)
    target_post = np.zeros_like(processed)
    target_post[delay:] = processed[:-delay]

    taps = []
    for tap_id, label, values in (
        (1, "TRIGGER", trigger),
        (2, "TARGET_PRE", target_pre),
        (3, "TARGET_POST", target_post),
    ):
        path = tmp_path / f"tap-{tap_id}-{label}.wav"
        final = _write_wav(path, values, sample_rate)
        taps.append({"tap_id": tap_id, "source_label": label, "final": final})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "experiment_id": "fixture", "taps": taps}),
        encoding="utf-8",
    )
    return manifest


def test_verifier_measures_known_event_correlated_duck(tmp_path):
    manifest = _fixture(tmp_path)
    result = verify_sidechain_capture(
        manifest,
        trigger_label="TRIGGER",
        target_pre_label="TARGET_PRE",
        target_post_label="TARGET_POST",
    )
    assert result["effect_state"] == "NOT_STARTED"
    assert result["status"] == "MEASURED"
    assert result["trigger"]["event_count"] == 4
    assert result["eligible_event_count"] == 4
    assert result["observed_event_correlated_ducking"] is True
    assert 8.0 <= result["target_alignment"]["post_delay_ms"] <= 16.0
    aggregate = result["aggregate"]
    assert aggregate["reduction_p90_db_median"] >= 8.0
    assert 15.0 <= aggregate["effective_onset_ms_median"] <= 50.0
    assert 35.0 <= aggregate["duration_above_depth_ms_median"] <= 130.0
    assert aggregate["recovery_complete_ms_median"] is not None


def test_verifier_does_not_invent_ducking_for_static_chain(tmp_path):
    manifest = _fixture(tmp_path, duck=False)
    result = verify_sidechain_capture(
        manifest,
        trigger_label="TRIGGER",
        target_pre_label="TARGET_PRE",
        target_post_label="TARGET_POST",
    )
    assert result["status"] == "MEASURED"
    assert result["observed_event_correlated_ducking"] is False
    assert abs(result["aggregate"]["reduction_p90_db_median"]) < 0.75


def test_verifier_rejects_missing_or_duplicate_labels(tmp_path):
    manifest = _fixture(tmp_path)
    with pytest.raises(SidechainVerificationError, match="distinct"):
        verify_sidechain_capture(
            manifest,
            trigger_label="TRIGGER",
            target_pre_label="TARGET_PRE",
            target_post_label="TARGET_PRE",
        )
    with pytest.raises(SidechainVerificationError, match="exactly one tap"):
        verify_sidechain_capture(
            manifest,
            trigger_label="MISSING",
            target_pre_label="TARGET_PRE",
            target_post_label="TARGET_POST",
        )


def test_verifier_rejects_finalized_artifact_identity_change(tmp_path):
    manifest = _fixture(tmp_path)
    target = tmp_path / "tap-3-TARGET_POST.wav"
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(SidechainVerificationError, match="size changed"):
        verify_sidechain_capture(
            manifest,
            trigger_label="TRIGGER",
            target_pre_label="TARGET_PRE",
            target_post_label="TARGET_POST",
        )
