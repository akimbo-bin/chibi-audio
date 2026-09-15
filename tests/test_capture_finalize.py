import json
import shutil
import subprocess

import pytest

from chibi_audio.capture import CaptureError
from chibi_audio.capture_finalize import (
    TapCaptureInput,
    finalize_aligned_captures,
    probe_audio_file,
    samples_for_beat_range,
)
from chibi_audio.cli import _tap_capture_arg


def test_samples_for_beat_range_is_sample_exact():
    assert samples_for_beat_range(128.0, 136.0, 135.0, 48000) == 170667


def test_samples_for_beat_range_validates_bounds():
    with pytest.raises(CaptureError, match="greater"):
        samples_for_beat_range(8.0, 8.0, 120.0)
    with pytest.raises(CaptureError, match="tempo"):
        samples_for_beat_range(0.0, 4.0, 0.0)


def test_tap_capture_input_validates_id():
    with pytest.raises(CaptureError, match="tap_id"):
        TapCaptureInput(10000, "Main", "x.wav")


def test_cli_tap_argument_preserves_windows_drive_colon():
    parsed = _tap_capture_arg("2:BASS:C:/captures/bass.wav")
    assert parsed.tap_id == 2
    assert parsed.source_label == "BASS"
    assert str(parsed.path).replace("\\", "/") == "C:/captures/bass.wav"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)
def test_finalize_aligned_captures_crops_exact_samples_and_manifest(tmp_path):
    raw_paths = []
    for tap_id, frequency in ((1, 440), (2, 880)):
        path = tmp_path / f"raw-{tap_id}.wav"
        subprocess.run(
            [
                shutil.which("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=1.0",
                "-ac",
                "2",
                "-c:a",
                "pcm_f32le",
                str(path),
            ],
            check=True,
        )
        raw_paths.append(path)

    manifest_path = finalize_aligned_captures(
        experiment_id="unit-proof",
        inputs=[
            TapCaptureInput(1, "Main", raw_paths[0]),
            TapCaptureInput(2, "BASS", raw_paths[1]),
        ],
        output_dir=tmp_path / "final",
        start_beat=0.5,
        end_beat=1.0,
        tempo_bpm=120.0,
        transport_start_beat=0.0,
        transport_stop_beat=2.0,
        include_analysis=False,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["requested_range"]["target_samples"] == 12000
    assert manifest["requested_range"]["raw_start_offset_samples"] == 12000
    assert manifest["alignment"]["raw_sample_counts_equal"] is True
    assert manifest["alignment"]["final_sample_counts_equal"] is True
    assert manifest["alignment"]["exact_requested_samples"] is True
    assert manifest["alignment"]["final_sample_count"] == 12000
    assert manifest["alignment"]["raw_start_offset_samples"] == 12000
    assert [tap["tap_id"] for tap in manifest["taps"]] == [1, 2]

    for tap in manifest["taps"]:
        final = probe_audio_file(tap["final"]["path"])
        assert final["samples"] == 12000
        assert final["sample_rate"] == 48000
        assert final["channels"] == 2
        assert final["sample_fmt"].startswith("flt")
