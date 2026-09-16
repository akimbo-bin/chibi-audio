from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .analysis.io import probe_audio
from .analysis.models import AnalysisCapability, AnalysisCost, AnalysisRequest
from .analysis.service import AudioAnalysisService
from .capture import _safe_id


AB_SCHEMA_VERSION = "chibi-audio-level-matched-ab/v1"


class LevelMatchedAbError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _loudness_measurement(path: Path, service: AudioAnalysisService) -> dict[str, Any]:
    request = AnalysisRequest(
        capabilities=frozenset({AnalysisCapability.LOUDNESS}),
        max_cost=AnalysisCost.MODERATE,
    )
    report = service.analyze(path, request)
    value = report.measurements.get(AnalysisCapability.LOUDNESS.value)
    if not isinstance(value, dict):
        raise LevelMatchedAbError(f"loudness analyzer returned no measurement for {path}")
    integrated = value.get("integrated_lufs")
    if not isinstance(integrated, (int, float)) or not math.isfinite(float(integrated)):
        raise LevelMatchedAbError(f"integrated loudness is unavailable for {path}")
    return {
        "integrated_lufs": float(integrated),
        "true_peak_dbtp": value.get("true_peak_dbtp"),
        "loudness_range_lu": value.get("loudness_range_lu"),
        "method": value.get("method"),
        "executed_analyzers": report.executed_analyzers,
    }


def _sample_count(probe: dict[str, Any]) -> int:
    samples = probe.get("samples")
    if isinstance(samples, int) and samples > 0:
        return samples
    sample_rate = int(probe.get("sample_rate") or 0)
    duration = float(probe.get("duration_s") or 0.0)
    derived = int(round(sample_rate * duration))
    if derived <= 0:
        raise LevelMatchedAbError("audio probe did not provide a usable sample count")
    return derived


def _validate_aligned_pair(left: Path, right: Path) -> tuple[dict[str, Any], dict[str, Any], int]:
    if left.resolve() == right.resolve():
        raise LevelMatchedAbError("A/B inputs must be two distinct audio files")
    left_probe = probe_audio(left)
    right_probe = probe_audio(right)
    if int(left_probe["sample_rate"]) != int(right_probe["sample_rate"]):
        raise LevelMatchedAbError("A/B inputs must have the same sample rate")
    if int(left_probe["channels"]) != int(right_probe["channels"]):
        raise LevelMatchedAbError("A/B inputs must have the same channel count")
    left_samples = _sample_count(left_probe)
    right_samples = _sample_count(right_probe)
    if left_samples != right_samples:
        raise LevelMatchedAbError(
            f"A/B inputs must have identical sample counts: {left_samples} != {right_samples}"
        )
    return left_probe, right_probe, left_samples


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise LevelMatchedAbError("ffmpeg is required to create level-matched A/B artifacts")
    return executable


def _render_gain(
    source: Path,
    target: Path,
    *,
    gain_db: float,
    sample_rate: int,
    channels: int,
) -> None:
    command = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-af",
        f"volume={gain_db:.9f}dB:precision=double",
        "-c:a",
        "pcm_f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-y",
        str(target),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise LevelMatchedAbError(completed.stderr.strip() or f"ffmpeg failed while rendering {target.name}")
    if not target.is_file() or target.stat().st_size <= 44:
        raise LevelMatchedAbError(f"level-matched render was empty: {target}")


def _verify_render_shape(path: Path, reference_probe: dict[str, Any], expected_samples: int) -> dict[str, Any]:
    probe = probe_audio(path)
    if int(probe["sample_rate"]) != int(reference_probe["sample_rate"]):
        raise LevelMatchedAbError("level-matched render changed sample rate")
    if int(probe["channels"]) != int(reference_probe["channels"]):
        raise LevelMatchedAbError("level-matched render changed channel count")
    actual_samples = _sample_count(probe)
    if actual_samples != expected_samples:
        raise LevelMatchedAbError(
            f"level-matched render changed sample count: {actual_samples} != {expected_samples}"
        )
    if "flt" not in str(probe.get("sample_fmt") or ""):
        raise LevelMatchedAbError("level-matched render must remain floating-point PCM")
    return probe


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_level_matched_ab(
    *,
    left: str | Path,
    right: str | Path,
    output_dir: str | Path,
    comparison_id: str,
    left_label: str = "A",
    right_label: str = "B",
    verification_tolerance_lu: float = 0.15,
    analysis_service: AudioAnalysisService | None = None,
) -> Path:
    """Create non-destructive, downward-only loudness-matched A/B WAVs plus provenance."""

    if verification_tolerance_lu <= 0 or verification_tolerance_lu > 1.0:
        raise LevelMatchedAbError("verification_tolerance_lu must be > 0 and <= 1.0")

    left_path = Path(left).resolve()
    right_path = Path(right).resolve()
    if not left_path.is_file():
        raise FileNotFoundError(left_path)
    if not right_path.is_file():
        raise FileNotFoundError(right_path)

    left_probe, right_probe, sample_count = _validate_aligned_pair(left_path, right_path)
    sample_rate = int(left_probe["sample_rate"])
    channels = int(left_probe["channels"])

    safe_id = _safe_id(comparison_id)
    safe_left = _safe_id(left_label)
    safe_right = _safe_id(right_label)
    if safe_left == safe_right:
        raise LevelMatchedAbError("A/B labels must remain distinct after sanitization")

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    left_output = destination / f"{safe_id}__{safe_left}-level-matched.wav"
    right_output = destination / f"{safe_id}__{safe_right}-level-matched.wav"
    manifest_path = destination / f"{safe_id}__level-matched-ab.json"
    reserved = (left_output, right_output, manifest_path)
    existing = [path for path in reserved if path.exists()]
    if existing:
        raise LevelMatchedAbError(f"refusing to overwrite existing A/B artifacts: {existing[0]}")

    service = analysis_service or AudioAnalysisService()
    left_before = _loudness_measurement(left_path, service)
    right_before = _loudness_measurement(right_path, service)
    target_lufs = min(left_before["integrated_lufs"], right_before["integrated_lufs"])
    left_gain_db = target_lufs - left_before["integrated_lufs"]
    right_gain_db = target_lufs - right_before["integrated_lufs"]
    if left_gain_db > 1.0e-9 or right_gain_db > 1.0e-9:
        raise LevelMatchedAbError("downward-only A/B matching would require positive gain")

    left_temp = destination / f".{left_output.name}.tmp.wav"
    right_temp = destination / f".{right_output.name}.tmp.wav"
    for temp in (left_temp, right_temp):
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

    try:
        _render_gain(
            left_path,
            left_temp,
            gain_db=left_gain_db,
            sample_rate=sample_rate,
            channels=channels,
        )
        _render_gain(
            right_path,
            right_temp,
            gain_db=right_gain_db,
            sample_rate=sample_rate,
            channels=channels,
        )
        left_output_probe = _verify_render_shape(left_temp, left_probe, sample_count)
        right_output_probe = _verify_render_shape(right_temp, right_probe, sample_count)
        left_after = _loudness_measurement(left_temp, service)
        left_output_probe = {
            **left_output_probe,
            "path": left_output.relative_to(destination).as_posix(),
        }
        right_output_probe = {
            **right_output_probe,
            "path": right_output.relative_to(destination).as_posix(),
        }
        right_after = _loudness_measurement(right_temp, service)
        mismatch_lu = abs(left_after["integrated_lufs"] - right_after["integrated_lufs"])
        if mismatch_lu > verification_tolerance_lu:
            raise LevelMatchedAbError(
                f"level-matched outputs differ by {mismatch_lu:.3f} LU, above tolerance {verification_tolerance_lu:.3f}"
            )

        left_temp.replace(left_output)
        right_temp.replace(right_output)

        payload = {
            "schema_version": AB_SCHEMA_VERSION,
            "comparison_id": safe_id,
            "mode": "downward_to_quieter_integrated_loudness",
            "no_upward_gain": True,
            "target_lufs": target_lufs,
            "verification": {
                "tolerance_lu": verification_tolerance_lu,
                "observed_difference_lu": mismatch_lu,
            },
            "alignment": {
                "sample_rate": sample_rate,
                "channels": channels,
                "samples": sample_count,
            },
            "variants": [
                {
                    "label": safe_left,
                    "source": {
                        "path": str(left_path),
                        "sha256": _sha256(left_path),
                        "probe": left_probe,
                        "loudness": left_before,
                    },
                    "gain_db": left_gain_db,
                    "level_matched": {
                        "path": left_output.relative_to(destination).as_posix(),
                        "sha256": _sha256(left_output),
                        "probe": left_output_probe,
                        "loudness": left_after,
                    },
                },
                {
                    "label": safe_right,
                    "source": {
                        "path": str(right_path),
                        "sha256": _sha256(right_path),
                        "probe": right_probe,
                        "loudness": right_before,
                    },
                    "gain_db": right_gain_db,
                    "level_matched": {
                        "path": right_output.relative_to(destination).as_posix(),
                        "sha256": _sha256(right_output),
                        "probe": right_output_probe,
                        "loudness": right_after,
                    },
                },
            ],
            "interpretation_note": (
                "The level-matched pair is a listening/comparison aid. Loudness matching does not imply that either variant is better. "
                "The original as-produced files remain unchanged and authoritative for production-level differences."
            ),
        }
        _atomic_write_json(manifest_path, payload)
        return manifest_path
    except Exception:
        cleanup = (
            left_temp,
            right_temp,
            left_output,
            right_output,
            manifest_path,
            manifest_path.with_suffix(manifest_path.suffix + ".tmp"),
        )
        for artifact in cleanup:
            try:
                artifact.unlink()
            except FileNotFoundError:
                pass
        raise
