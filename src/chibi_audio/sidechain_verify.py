from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .analysis.io import decode_audio_segment, probe_audio
from .analysis.manifest import (
    CaptureManifestAnalysisError,
    _reconcile_artifact_identity,
    _resolve_artifact_path,
    _validate_digest,
)
from .analysis.models import AnalysisRequest


SIDECHAIN_VERIFICATION_SCHEMA_VERSION = "chibi-audio-sidechain-verification/v1"


class SidechainVerificationError(ValueError):
    pass


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SidechainVerificationError(f"could not read capture manifest: {path}") from exc
    if payload.get("schema_version") != 1:
        raise SidechainVerificationError("sidechain verification requires capture manifest schema_version=1")
    taps = payload.get("taps")
    if not isinstance(taps, list) or not taps:
        raise SidechainVerificationError("capture manifest does not contain finalized taps")
    return payload


def _tap_by_label(manifest_path: Path, manifest: dict[str, Any], label: str) -> dict[str, Any]:
    wanted = label.strip()
    if not wanted:
        raise SidechainVerificationError("tap labels must not be empty")
    matches = [
        item for item in manifest["taps"]
        if isinstance(item, dict) and str(item.get("source_label") or "") == wanted
    ]
    if len(matches) != 1:
        raise SidechainVerificationError(
            f"capture manifest must contain exactly one tap with source_label={wanted!r}; found {len(matches)}"
        )
    item = matches[0]
    final = item.get("final")
    if not isinstance(final, dict):
        raise SidechainVerificationError(f"tap {wanted!r} has no finalized artifact")
    try:
        tap_id = int(item["tap_id"])
        digest = _validate_digest(final.get("sha256"), tap_id)
        raw_path = final.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise SidechainVerificationError(f"tap {wanted!r} finalized artifact has no path")
        artifact = _resolve_artifact_path(manifest_path, raw_path).resolve()
        _reconcile_artifact_identity(artifact, final, tap_id)
    except CaptureManifestAnalysisError as exc:
        raise SidechainVerificationError(str(exc)) from exc
    return {
        "tap_id": tap_id,
        "source_label": wanted,
        "artifact": artifact,
        "content_sha256": digest,
    }


def _rms_envelope_db(audio: Any, *, window_frames: int, hop_frames: int) -> Any:
    import numpy as np

    values = np.asarray(audio, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < window_frames:
        raise SidechainVerificationError("audio is too short for the requested RMS window")
    power = np.mean(values * values, axis=1)
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(power)))
    starts = np.arange(0, len(power) - window_frames + 1, hop_frames, dtype=np.int64)
    mean_power = (cumulative[starts + window_frames] - cumulative[starts]) / float(window_frames)
    return 10.0 * np.log10(np.maximum(mean_power, 1.0e-24))


def _trigger_events(
    audio: Any,
    *,
    sample_rate: int,
    threshold_dbfs: float,
    block_ms: float,
    min_event_gap_ms: float,
) -> list[dict[str, float]]:
    import numpy as np

    values = np.asarray(audio, dtype=np.float64)
    block_frames = max(1, int(round(block_ms * sample_rate / 1000.0)))
    block_count = values.shape[0] // block_frames
    if block_count < 1:
        return []
    peak = np.max(np.abs(values[: block_count * block_frames]), axis=1)
    peak = np.max(peak.reshape(block_count, block_frames), axis=1)
    peak_db = 20.0 * np.log10(np.maximum(peak, 1.0e-12))
    active = np.flatnonzero(peak_db >= threshold_dbfs)
    if active.size == 0:
        return []
    gap_blocks = max(1, int(round(min_event_gap_ms / block_ms)))
    groups = np.split(active, np.flatnonzero(np.diff(active) > gap_blocks) + 1)
    result: list[dict[str, float]] = []
    for group in groups:
        if group.size == 0:
            continue
        peak_index = int(group[int(np.argmax(peak_db[group]))])
        onset_index = int(group[0])
        end_index = int(group[-1])
        result.append(
            {
                "onset_seconds": onset_index * block_frames / float(sample_rate),
                "peak_seconds": peak_index * block_frames / float(sample_rate),
                "end_seconds": (end_index + 1) * block_frames / float(sample_rate),
                "peak_dbfs": float(peak_db[peak_index]),
            }
        )
    return result


def _correlation(left: Any, right: Any, mask: Any) -> float | None:
    import numpy as np

    a = np.asarray(left)[mask]
    b = np.asarray(right)[mask]
    if a.size < 20 or float(np.std(a)) <= 1.0e-12 or float(np.std(b)) <= 1.0e-12:
        return None
    value = float(np.corrcoef(a, b)[0, 1])
    return value if math.isfinite(value) else None


def _lagged_pair(first: Any, second: Any, lag: int) -> tuple[Any, Any]:
    if lag < 0:
        return first[-lag:], second[:lag]
    if lag > 0:
        return first[:-lag], second[lag:]
    return first, second


def _estimate_post_delay(
    pre: Any,
    post: Any,
    *,
    max_lag_frames: int,
    active_threshold_dbfs: float,
) -> tuple[int, float]:
    import numpy as np

    best_lag: int | None = None
    best_corr: float | None = None
    for lag in range(-max_lag_frames, max_lag_frames + 1):
        left, right = _lagged_pair(pre, post, lag)
        mask = (
            np.isfinite(left)
            & np.isfinite(right)
            & (left > active_threshold_dbfs)
            & (right > active_threshold_dbfs)
        )
        corr = _correlation(left, right, mask)
        if corr is not None and (best_corr is None or corr > best_corr):
            best_lag = lag
            best_corr = corr
    if best_lag is None or best_corr is None:
        raise SidechainVerificationError("could not estimate target pre/post latency from active RMS envelopes")
    return best_lag, best_corr


def _smooth_masked(values: Any, valid: Any, frames: int) -> Any:
    import numpy as np

    width = max(1, int(frames))
    kernel = np.ones(width, dtype=np.float64)
    weighted = np.convolve(np.where(valid, values, 0.0), kernel, mode="same")
    counts = np.convolve(valid.astype(np.float64), kernel, mode="same")
    return np.where(counts >= max(1.0, width * 0.6), weighted / np.maximum(counts, 1.0), np.nan)


def _first_sustained(mask: Any, frames: int, *, start: int = 0) -> int | None:
    import numpy as np

    width = max(1, int(frames))
    values = np.asarray(mask, dtype=bool)
    for index in range(max(0, start), max(0, len(values) - width + 1)):
        if bool(np.all(values[index : index + width])):
            return index
    return None


def _median(values: list[float | None]) -> float | None:
    import numpy as np

    present = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return None if not present else float(np.median(present))


def verify_sidechain_capture(
    manifest_path: str | Path,
    *,
    trigger_label: str,
    target_pre_label: str,
    target_post_label: str,
    trigger_threshold_dbfs: float = -30.0,
    trigger_block_ms: float = 1.0,
    min_event_gap_ms: float = 80.0,
    envelope_window_ms: float = 8.0,
    envelope_hop_ms: float = 1.0,
    max_target_latency_ms: float = 200.0,
    alignment_active_threshold_dbfs: float = -50.0,
    target_active_floor_dbfs: float = -60.0,
    target_activity_margin_db: float = 20.0,
    reference_start_ms: float = -200.0,
    reference_end_ms: float = -70.0,
    effect_start_ms: float = -20.0,
    effect_end_ms: float = 300.0,
    min_target_active_fraction: float = 0.60,
    depth_threshold_db: float = 3.0,
    onset_threshold_db: float = 1.0,
    timing_smooth_ms: float = 7.0,
    timing_sustain_ms: float = 8.0,
) -> dict[str, Any]:
    """Measure event-correlated target-chain attenuation from aligned ChibiTap evidence.

    This is rendered-audio evidence, not a plugin gain-reduction meter. The measured
    reduction includes every time-varying process between target_pre and target_post,
    so correlation to the trigger is evidence of ducking but is not causal isolation
    when other dynamics processors are present in the same signal span.
    """
    import numpy as np

    labels = [trigger_label.strip(), target_pre_label.strip(), target_post_label.strip()]
    if any(not label for label in labels) or len(set(labels)) != 3:
        raise SidechainVerificationError("trigger, target-pre and target-post labels must be non-empty and distinct")
    positive = {
        "trigger_block_ms": trigger_block_ms,
        "min_event_gap_ms": min_event_gap_ms,
        "envelope_window_ms": envelope_window_ms,
        "envelope_hop_ms": envelope_hop_ms,
        "max_target_latency_ms": max_target_latency_ms,
        "target_activity_margin_db": target_activity_margin_db,
        "effect_end_ms": effect_end_ms,
        "depth_threshold_db": depth_threshold_db,
        "onset_threshold_db": onset_threshold_db,
        "timing_smooth_ms": timing_smooth_ms,
        "timing_sustain_ms": timing_sustain_ms,
    }
    for name, value in positive.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise SidechainVerificationError(f"{name} must be finite and > 0")
    if envelope_hop_ms > envelope_window_ms:
        raise SidechainVerificationError("envelope_hop_ms must be <= envelope_window_ms")
    if not -160.0 <= trigger_threshold_dbfs <= 0.0:
        raise SidechainVerificationError("trigger_threshold_dbfs must be between -160 and 0")
    if not -160.0 <= alignment_active_threshold_dbfs <= 0.0:
        raise SidechainVerificationError("alignment_active_threshold_dbfs must be between -160 and 0")
    if not -160.0 <= target_active_floor_dbfs <= 0.0:
        raise SidechainVerificationError("target_active_floor_dbfs must be between -160 and 0")
    if not reference_start_ms < reference_end_ms < effect_start_ms + 1.0e-9:
        raise SidechainVerificationError("reference window must end no later than the effect window begins")
    if effect_start_ms >= effect_end_ms:
        raise SidechainVerificationError("effect_start_ms must be less than effect_end_ms")
    if not 0.0 < min_target_active_fraction <= 1.0:
        raise SidechainVerificationError("min_target_active_fraction must be in (0, 1]")

    source = Path(manifest_path).resolve()
    manifest = _load_manifest(source)
    taps = {label: _tap_by_label(source, manifest, label) for label in labels}
    probes = {label: probe_audio(item["artifact"]) for label, item in taps.items()}
    sample_rates = {int(item["sample_rate"]) for item in probes.values()}
    channels = {int(item["channels"]) for item in probes.values()}
    counts = [item.get("samples") for item in probes.values()]
    if any(value is None for value in counts):
        raise SidechainVerificationError("selected capture taps must expose exact sample counts")
    sample_counts = {int(value) for value in counts}
    if len(sample_rates) != 1 or len(channels) != 1 or len(sample_counts) != 1:
        raise SidechainVerificationError("selected capture taps must have identical sample rate, channels and sample count")
    sample_rate = sample_rates.pop()
    channel_count = channels.pop()
    sample_count = sample_counts.pop()
    request = AnalysisRequest(sample_rate=sample_rate)
    audio = {
        label: decode_audio_segment(item["artifact"], request, sample_rate=sample_rate, channels=channel_count)
        for label, item in taps.items()
    }

    events = _trigger_events(
        audio[labels[0]],
        sample_rate=sample_rate,
        threshold_dbfs=float(trigger_threshold_dbfs),
        block_ms=float(trigger_block_ms),
        min_event_gap_ms=float(min_event_gap_ms),
    )
    if not events:
        raise SidechainVerificationError("trigger tap contains no events above the configured threshold")

    window_frames = max(1, int(round(envelope_window_ms * sample_rate / 1000.0)))
    hop_frames = max(1, int(round(envelope_hop_ms * sample_rate / 1000.0)))
    pre_env = _rms_envelope_db(audio[labels[1]], window_frames=window_frames, hop_frames=hop_frames)
    post_env = _rms_envelope_db(audio[labels[2]], window_frames=window_frames, hop_frames=hop_frames)
    max_lag = max(1, int(round(max_target_latency_ms / envelope_hop_ms)))
    lag, alignment_corr = _estimate_post_delay(
        pre_env,
        post_env,
        max_lag_frames=max_lag,
        active_threshold_dbfs=float(alignment_active_threshold_dbfs),
    )
    if lag < 0:
        aligned_pre = pre_env[-lag:]
        aligned_post = post_env[:lag]
        timeline_offset_frames = -lag
    elif lag > 0:
        aligned_pre = pre_env[:-lag]
        aligned_post = post_env[lag:]
        timeline_offset_frames = 0
    else:
        aligned_pre = pre_env
        aligned_post = post_env
        timeline_offset_frames = 0
    times = (np.arange(len(aligned_pre), dtype=np.float64) + timeline_offset_frames) * hop_frames / float(sample_rate)
    chain_gain_db = aligned_post - aligned_pre

    finite_pre = aligned_pre[np.isfinite(aligned_pre)]
    if finite_pre.size == 0:
        raise SidechainVerificationError("target pre tap has no finite RMS evidence")
    target_active_threshold = max(
        float(target_active_floor_dbfs),
        float(np.percentile(finite_pre, 75.0)) - float(target_activity_margin_db),
    )
    smooth_frames = max(1, int(round(timing_smooth_ms / envelope_hop_ms)))
    sustain_frames = max(1, int(round(timing_sustain_ms / envelope_hop_ms)))

    event_rows: list[dict[str, Any]] = []
    skip_reasons: dict[str, int] = {}
    for event_index, event in enumerate(events):
        onset = float(event["onset_seconds"])
        next_onset = float(events[event_index + 1]["onset_seconds"]) if event_index + 1 < len(events) else None
        reference = (
            (times >= onset + reference_start_ms / 1000.0)
            & (times <= onset + reference_end_ms / 1000.0)
            & (aligned_pre > target_active_threshold)
            & np.isfinite(chain_gain_db)
        )
        effect_stop = onset + effect_end_ms / 1000.0
        if next_onset is not None:
            effect_stop = min(effect_stop, next_onset - max(0.002, envelope_hop_ms / 1000.0))
        effect = (
            (times >= onset + effect_start_ms / 1000.0)
            & (times <= effect_stop)
            & np.isfinite(chain_gain_db)
        )
        if int(np.sum(reference)) < max(3, int(round(30.0 / envelope_hop_ms))):
            skip_reasons["insufficient_reference_activity"] = skip_reasons.get("insufficient_reference_activity", 0) + 1
            continue
        if int(np.sum(effect)) < sustain_frames:
            skip_reasons["effect_window_too_short"] = skip_reasons.get("effect_window_too_short", 0) + 1
            continue
        effect_pre = aligned_pre[effect]
        valid = effect_pre > target_active_threshold
        active_fraction = float(np.mean(valid))
        if active_fraction < min_target_active_fraction:
            skip_reasons["target_inactive"] = skip_reasons.get("target_inactive", 0) + 1
            continue

        baseline_gain = float(np.median(chain_gain_db[reference]))
        reduction = baseline_gain - chain_gain_db[effect]
        rel_ms = (times[effect] - onset) * 1000.0
        valid_reduction = reduction[valid]
        valid_rel_ms = rel_ms[valid]
        if valid_reduction.size < sustain_frames:
            skip_reasons["insufficient_active_effect_frames"] = skip_reasons.get("insufficient_active_effect_frames", 0) + 1
            continue

        smoothed = _smooth_masked(reduction, valid, smooth_frames)
        onset_index = _first_sustained(np.isfinite(smoothed) & (smoothed >= onset_threshold_db), sustain_frames)
        effective_onset_ms = None if onset_index is None else float(rel_ms[onset_index])
        valid_smoothed = np.where(valid & np.isfinite(smoothed), smoothed, -np.inf)
        peak_index = int(np.argmax(valid_smoothed))
        peak_reduction_db = float(valid_smoothed[peak_index]) if math.isfinite(float(valid_smoothed[peak_index])) else None
        peak_time_ms = None if peak_reduction_db is None else float(rel_ms[peak_index])
        recovery_index = None
        if peak_reduction_db is not None:
            recovery_index = _first_sustained(
                np.isfinite(smoothed) & valid & (smoothed <= onset_threshold_db),
                sustain_frames,
                start=peak_index + 1,
            )
        recovery_complete_ms = None if recovery_index is None else float(rel_ms[recovery_index])
        recovery_from_peak_ms = (
            None
            if recovery_complete_ms is None or peak_time_ms is None
            else float(recovery_complete_ms - peak_time_ms)
        )

        above_depth = valid_reduction >= depth_threshold_db
        event_rows.append(
            {
                "trigger_onset_seconds": onset,
                "trigger_peak_seconds": float(event["peak_seconds"]),
                "trigger_peak_dbfs": float(event["peak_dbfs"]),
                "target_active_fraction": active_fraction,
                "reference_chain_gain_db": baseline_gain,
                "reduction_db": {
                    "p95": float(np.percentile(valid_reduction, 95.0)),
                    "p90": float(np.percentile(valid_reduction, 90.0)),
                    "median": float(np.median(valid_reduction)),
                    "peak_smoothed": peak_reduction_db,
                },
                "effective_timing_ms": {
                    "onset": effective_onset_ms,
                    "peak": peak_time_ms,
                    "recovery_complete": recovery_complete_ms,
                    "recovery_from_peak": recovery_from_peak_ms,
                },
                "duration_above_depth_ms": float(np.sum(above_depth) * envelope_hop_ms),
                "positive_reduction_db_ms": float(np.sum(np.maximum(valid_reduction, 0.0)) * envelope_hop_ms),
                "analysis_window_end_ms": float((effect_stop - onset) * 1000.0),
            }
        )

    eligible = len(event_rows)
    if event_rows:
        median_p90 = _median([row["reduction_db"]["p90"] for row in event_rows])
        observed = bool(median_p90 is not None and median_p90 >= onset_threshold_db)
        status = "MEASURED"
    else:
        median_p90 = None
        observed = False
        status = "INCONCLUSIVE"

    aggregate = {
        "reduction_p95_db_median": _median([row["reduction_db"]["p95"] for row in event_rows]),
        "reduction_p90_db_median": median_p90,
        "reduction_median_db_median": _median([row["reduction_db"]["median"] for row in event_rows]),
        "peak_smoothed_reduction_db_median": _median([row["reduction_db"]["peak_smoothed"] for row in event_rows]),
        "effective_onset_ms_median": _median([row["effective_timing_ms"]["onset"] for row in event_rows]),
        "peak_time_ms_median": _median([row["effective_timing_ms"]["peak"] for row in event_rows]),
        "recovery_complete_ms_median": _median([row["effective_timing_ms"]["recovery_complete"] for row in event_rows]),
        "recovery_from_peak_ms_median": _median([row["effective_timing_ms"]["recovery_from_peak"] for row in event_rows]),
        "duration_above_depth_ms_median": _median([row["duration_above_depth_ms"] for row in event_rows]),
        "positive_reduction_db_ms_median": _median([row["positive_reduction_db_ms"] for row in event_rows]),
    }
    return {
        "schema_version": SIDECHAIN_VERIFICATION_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "status": status,
        "capture_manifest": str(source),
        "experiment_id": manifest.get("experiment_id"),
        "labels": {
            "trigger": labels[0],
            "target_pre": labels[1],
            "target_post": labels[2],
        },
        "artifacts": {
            label: {
                "tap_id": taps[label]["tap_id"],
                "content_sha256": taps[label]["content_sha256"],
            }
            for label in labels
        },
        "sample_rate": sample_rate,
        "channels": channel_count,
        "samples": sample_count,
        "trigger": {
            "threshold_dbfs": float(trigger_threshold_dbfs),
            "event_count": len(events),
        },
        "target_alignment": {
            "post_delay_ms": float(lag * envelope_hop_ms),
            "envelope_correlation": float(alignment_corr),
            "active_threshold_dbfs": float(target_active_threshold),
        },
        "eligible_event_count": eligible,
        "skipped_event_count": len(events) - eligible,
        "skip_reasons": skip_reasons,
        "observed_event_correlated_ducking": observed,
        "aggregate": aggregate,
        "events": event_rows,
        "measurement_scope": (
            "Rendered event-correlated attenuation across the complete target_pre -> target_post signal span. "
            "Other time-varying processors in that span can contribute; plugin gain-reduction meters are not used."
        ),
    }
