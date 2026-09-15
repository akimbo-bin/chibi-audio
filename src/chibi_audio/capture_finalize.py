from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .capture import CaptureArtifact, CaptureError, _safe_id


@dataclass(frozen=True, slots=True)
class TapCaptureInput:
    tap_id: int
    source_label: str
    path: Path

    def __post_init__(self) -> None:
        if self.tap_id < 0 or self.tap_id > 9999:
            raise CaptureError("tap_id must be between 0 and 9999")
        object.__setattr__(self, "source_label", _safe_id(self.source_label))
        object.__setattr__(self, "path", Path(self.path))


def samples_for_beat_range(
    start_beat: float,
    end_beat: float,
    tempo_bpm: float,
    sample_rate: int = 48000,
) -> int:
    if start_beat < 0:
        raise CaptureError("start_beat must be >= 0")
    if end_beat <= start_beat:
        raise CaptureError("end_beat must be greater than start_beat")
    if tempo_bpm <= 0:
        raise CaptureError("tempo_bpm must be > 0")
    if sample_rate < 8000 or sample_rate > 384000:
        raise CaptureError("sample_rate is outside the supported range")
    duration_seconds = (end_beat - start_beat) * 60.0 / tempo_bpm
    return int(round(duration_seconds * sample_rate))


def _exe(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise CaptureError(f"Required executable is not available on PATH: {name}")
    return value


def probe_audio_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise CaptureError(f"capture file does not exist: {source}")
    command = [
        _exe("ffprobe"), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels,sample_fmt,duration_ts,time_base,duration",
        "-of", "json", str(source),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise CaptureError(completed.stderr.strip() or f"ffprobe failed for {source}")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if len(streams) != 1:
        raise CaptureError(f"expected exactly one audio stream in {source}")
    stream = streams[0]
    if stream.get("duration_ts") is None:
        raise CaptureError(f"ffprobe did not report duration_ts for {source}")
    return {
        "path": str(source),
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "sample_fmt": str(stream.get("sample_fmt") or ""),
        "samples": int(stream["duration_ts"]),
        "time_base": str(stream.get("time_base") or ""),
        "duration_s": float(stream.get("duration") or 0.0),
    }


def _artifact(path: Path) -> CaptureArtifact:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return CaptureArtifact(path, stat.st_size, digest.hexdigest(), stat.st_mtime_ns)


def crop_capture_exact(
    source: str | Path,
    target: str | Path,
    *,
    samples: int,
    start_sample: int = 0,
    sample_rate: int = 48000,
    channels: int = 2,
) -> CaptureArtifact:
    if samples <= 0:
        raise CaptureError("samples must be > 0")
    if start_sample < 0:
        raise CaptureError("start_sample must be >= 0")
    source_path = Path(source)
    target_path = Path(target)
    info = probe_audio_file(source_path)
    if info["sample_rate"] != sample_rate:
        raise CaptureError(
            f"source sample rate {info['sample_rate']} does not match expected {sample_rate}: {source_path}"
        )
    if info["channels"] != channels:
        raise CaptureError(
            f"source channel count {info['channels']} does not match expected {channels}: {source_path}"
        )
    required_samples = start_sample + samples
    if info["samples"] < required_samples:
        raise CaptureError(
            f"source is too short for exact crop: {info['samples']} < {required_samples} samples: {source_path}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f"{target_path.stem}.tmp{target_path.suffix}")
    temp_path.unlink(missing_ok=True)
    command = [
        _exe("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source_path), "-map", "0:a:0",
        "-af", f"atrim=start_sample={start_sample}:end_sample={start_sample + samples},asetpts=PTS-STARTPTS",
        "-c:a", "pcm_f32le", "-ar", str(sample_rate), "-ac", str(channels),
        str(temp_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise CaptureError(completed.stderr.strip() or f"ffmpeg crop failed for {source_path}")

    cropped = probe_audio_file(temp_path)
    if cropped["samples"] != samples:
        temp_path.unlink(missing_ok=True)
        raise CaptureError(
            f"exact crop produced {cropped['samples']} samples instead of {samples}: {source_path}"
        )
    if cropped["sample_rate"] != sample_rate or cropped["channels"] != channels:
        temp_path.unlink(missing_ok=True)
        raise CaptureError("cropped artifact format changed unexpectedly")
    if not cropped["sample_fmt"].startswith("flt"):
        temp_path.unlink(missing_ok=True)
        raise CaptureError(f"cropped artifact is not float PCM: {cropped['sample_fmt']}")

    temp_path.replace(target_path)
    return _artifact(target_path)


def finalize_aligned_captures(
    *,
    experiment_id: str,
    inputs: Iterable[TapCaptureInput],
    output_dir: str | Path,
    start_beat: float,
    end_beat: float,
    tempo_bpm: float,
    sample_rate: int = 48000,
    channels: int = 2,
    transport_start_beat: float | None = None,
    transport_stop_beat: float | None = None,
    include_analysis: bool = False,
) -> Path:
    safe_experiment = _safe_id(experiment_id)
    capture_inputs = list(inputs)
    if not capture_inputs:
        raise CaptureError("at least one tap capture input is required")
    tap_ids = [item.tap_id for item in capture_inputs]
    if len(set(tap_ids)) != len(tap_ids):
        raise CaptureError("tap_id values must be unique")

    target_samples = samples_for_beat_range(start_beat, end_beat, tempo_bpm, sample_rate)
    start_offset_samples = 0
    if transport_start_beat is not None:
        transport_start_beat = float(transport_start_beat)
        if transport_start_beat > start_beat:
            raise CaptureError("transport_start_beat cannot be after requested start_beat")
        if transport_start_beat < start_beat:
            start_offset_samples = samples_for_beat_range(
                transport_start_beat, start_beat, tempo_bpm, sample_rate
            )
    raw_items: list[tuple[TapCaptureInput, dict[str, Any], CaptureArtifact]] = []
    raw_counts: list[int] = []
    for item in capture_inputs:
        info = probe_audio_file(item.path)
        if info["sample_rate"] != sample_rate:
            raise CaptureError(f"Tap {item.tap_id} sample rate does not match the experiment")
        if info["channels"] != channels:
            raise CaptureError(f"Tap {item.tap_id} channel count does not match the experiment")
        raw_counts.append(int(info["samples"]))
        raw_items.append((item, info, _artifact(item.path)))

    if len(set(raw_counts)) != 1:
        raise CaptureError(f"raw tap captures are not sample-aligned: {raw_counts}")
    required_samples = start_offset_samples + target_samples
    if raw_counts[0] < required_samples:
        raise CaptureError(
            f"raw capture is shorter than requested range: {raw_counts[0]} < {required_samples}"
        )

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    taps: list[dict[str, Any]] = []

    analyze_audio = None
    if include_analysis:
        from .audio import analyze_audio as _analyze_audio
        analyze_audio = _analyze_audio

    for item, raw_info, raw_artifact in raw_items:
        output_name = f"{safe_experiment}__tap-{item.tap_id}-{item.source_label}.wav"
        output_path = destination / output_name
        cropped_artifact = crop_capture_exact(
            item.path,
            output_path,
            samples=target_samples,
            start_sample=start_offset_samples,
            sample_rate=sample_rate,
            channels=channels,
        )
        cropped_info = probe_audio_file(output_path)
        entry: dict[str, Any] = {
            "tap_id": item.tap_id,
            "source_label": item.source_label,
            "raw": {**raw_info, **raw_artifact.as_dict()},
            "final": {**cropped_info, **cropped_artifact.as_dict()},
        }
        if analyze_audio is not None:
            entry["analysis"] = analyze_audio(output_path, sample_rate=sample_rate)
        taps.append(entry)

    final_counts = [int(item["final"]["samples"]) for item in taps]
    exact = len(set(final_counts)) == 1 and final_counts[0] == target_samples
    if not exact:
        raise CaptureError(f"final tap artifacts failed exact-range finality: {final_counts}")

    manifest = {
        "schema_version": 1,
        "experiment_id": safe_experiment,
        "requested_range": {
            "start_beat": float(start_beat),
            "end_beat": float(end_beat),
            "duration_beats": float(end_beat - start_beat),
            "tempo_bpm": float(tempo_bpm),
            "sample_rate": int(sample_rate),
            "channels": int(channels),
            "target_samples": int(target_samples),
            "target_duration_s": target_samples / float(sample_rate),
            "raw_start_offset_samples": int(start_offset_samples),
            "tempo_model": "constant_bpm",
        },
        "transport": {
            "start_beat": None if transport_start_beat is None else float(transport_start_beat),
            "stop_beat": None if transport_stop_beat is None else float(transport_stop_beat),
        },
        "alignment": {
            "raw_sample_counts_equal": len(set(raw_counts)) == 1,
            "raw_sample_count": raw_counts[0],
            "raw_start_offset_samples": int(start_offset_samples),
            "final_sample_counts_equal": len(set(final_counts)) == 1,
            "final_sample_count": final_counts[0],
            "exact_requested_samples": exact,
        },
        "taps": taps,
    }
    manifest_path = destination / f"{safe_experiment}__manifest.json"
    temp_manifest = manifest_path.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_manifest.replace(manifest_path)
    return manifest_path
