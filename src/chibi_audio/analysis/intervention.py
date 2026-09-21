from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .contribution import _load_manifest, _tap_by_label
from .io import decode_audio_segment, probe_audio
from .models import AnalysisRequest
from .stress import _fft_lowpass, _rms_envelope_db


SOURCE_INTERVENTION_PROBE_SCHEMA_VERSION = (
    "chibi-audio-source-intervention-probe/v1"
)


class SourceInterventionProbeError(ValueError):
    pass


def _requested_range(manifest: dict[str, Any]) -> dict[str, float | int]:
    requested = manifest.get("requested_range")
    if not isinstance(requested, dict):
        raise SourceInterventionProbeError(
            "capture manifest has no requested_range"
        )
    required = (
        "start_beat",
        "end_beat",
        "tempo_bpm",
        "sample_rate",
        "channels",
        "target_samples",
    )
    result: dict[str, float | int] = {}
    for key in required:
        value = requested.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SourceInterventionProbeError(
                f"capture requested_range has no numeric {key}"
            )
        if not math.isfinite(float(value)):
            raise SourceInterventionProbeError(
                f"capture requested_range {key} must be finite"
            )
        result[key] = int(value) if key in {"sample_rate", "channels", "target_samples"} else float(value)
    if float(result["end_beat"]) <= float(result["start_beat"]):
        raise SourceInterventionProbeError(
            "capture requested_range end_beat must be greater than start_beat"
        )
    if float(result["tempo_bpm"]) <= 0.0:
        raise SourceInterventionProbeError(
            "capture requested_range tempo_bpm must be > 0"
        )
    return result


def _same_requested_range(
    baseline: dict[str, float | int],
    candidate: dict[str, float | int],
) -> bool:
    for key in ("sample_rate", "channels", "target_samples"):
        if int(baseline[key]) != int(candidate[key]):
            return False
    for key in ("start_beat", "end_beat", "tempo_bpm"):
        if not math.isclose(
            float(baseline[key]),
            float(candidate[key]),
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            return False
    return True


def _tap_provenance(
    manifest: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    live_session = manifest.get("live_session")
    if not isinstance(live_session, dict):
        raise SourceInterventionProbeError(
            "capture manifest has no live_session provenance"
        )
    mixer_state = live_session.get("mixer_state")
    rows = (
        mixer_state.get("tap_targets")
        if isinstance(mixer_state, dict)
        else None
    )
    if not isinstance(rows, list):
        rows = live_session.get("tap_mapping")
    if not isinstance(rows, list):
        raise SourceInterventionProbeError(
            "capture manifest has no tap target mapping"
        )
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("source_label") or "") == label
    ]
    if len(matches) != 1:
        raise SourceInterventionProbeError(
            f"capture manifest must contain exactly one target mapping for {label!r}"
        )
    row = matches[0]
    result = {
        "source_label": label,
        "placement": str(row.get("placement") or ""),
        "signal_point": str(row.get("signal_point") or ""),
        "track_name": str(row.get("track_name") or ""),
        "track_index": row.get("track_index"),
        "track_id": row.get("track_id"),
    }
    if not result["placement"] or not result["signal_point"] or not result["track_name"]:
        raise SourceInterventionProbeError(
            f"capture target mapping is incomplete for {label!r}"
        )
    if result["track_id"] is None:
        raise SourceInterventionProbeError(
            f"capture target mapping has no track_id for {label!r}"
        )
    return result


def _matching_bus_identity(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    keys = (
        "placement",
        "signal_point",
        "track_name",
        "track_index",
        "track_id",
    )
    return all(baseline.get(key) == candidate.get(key) for key in keys)


def _probe_format(path: Path) -> dict[str, int]:
    probe = probe_audio(path)
    raw_samples = probe.get("samples")
    if raw_samples is None:
        raise SourceInterventionProbeError(
            "finalized bus artifact must expose exact sample count"
        )
    return {
        "sample_rate": int(probe["sample_rate"]),
        "channels": int(probe["channels"]),
        "samples": int(raw_samples),
    }


def _finite_percentile(values: Any, percentile: float) -> float:
    selected = np.asarray(values, dtype=np.float64)
    selected = selected[np.isfinite(selected)]
    if selected.size == 0:
        raise SourceInterventionProbeError(
            "intervention probe produced no finite response windows"
        )
    return float(np.percentile(selected, percentile))


def _event_indices(
    baseline_bus: Any,
    top_bus: Any,
    *,
    hop_frames: int,
    sample_rate: int,
    limit: int = 8,
) -> list[int]:
    ranked = sorted(
        (int(index) for index in np.flatnonzero(top_bus)),
        key=lambda index: float(baseline_bus[index]),
        reverse=True,
    )
    minimum_separation_windows = max(
        1,
        int(round(0.25 / (float(hop_frames) / float(sample_rate)))),
    )
    selected: list[int] = []
    for index in ranked:
        if any(
            abs(index - previous) < minimum_separation_windows
            for previous in selected
        ):
            continue
        selected.append(index)
        if len(selected) >= limit:
            break
    return selected


def evaluate_source_intervention_probe(
    baseline_manifest_path: str | Path,
    candidate_manifest_path: str | Path,
    *,
    bus_label: str,
    source_target: str,
    source_parameter: str,
    declared_change_db: float,
    window_ms: float = 100.0,
    hop_ms: float = 10.0,
    low_band_hz: float = 250.0,
    active_threshold_dbfs: float = -45.0,
    top_bus_fraction: float = 0.10,
) -> dict[str, Any]:
    """Measure how one declared source intervention moved a captured bus.

    The two captures must cover the exact same requested musical range and exact
    same bus target. The capture manifests prove the audio identity; the source
    mutation declaration is caller-supplied metadata and is intentionally
    reported as unverified unless later bound to an experiment journal.
    """

    for name, value in (
        ("declared_change_db", declared_change_db),
        ("window_ms", window_ms),
        ("hop_ms", hop_ms),
        ("low_band_hz", low_band_hz),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise SourceInterventionProbeError(
                f"{name} must be finite"
            )
    if declared_change_db == 0.0:
        raise SourceInterventionProbeError(
            "declared_change_db must be non-zero"
        )
    if abs(float(declared_change_db)) > 24.0:
        raise SourceInterventionProbeError(
            "declared_change_db must be within +/-24 dB"
        )
    if window_ms <= 0.0 or hop_ms <= 0.0 or low_band_hz <= 0.0:
        raise SourceInterventionProbeError(
            "window_ms, hop_ms and low_band_hz must be > 0"
        )
    if hop_ms > window_ms:
        raise SourceInterventionProbeError(
            "hop_ms must be <= window_ms"
        )
    if not -160.0 <= active_threshold_dbfs <= 0.0:
        raise SourceInterventionProbeError(
            "active_threshold_dbfs must be between -160 and 0"
        )
    if not 0.01 <= top_bus_fraction <= 0.5:
        raise SourceInterventionProbeError(
            "top_bus_fraction must be between 0.01 and 0.5"
        )

    bus_name = str(bus_label).strip()
    target_name = str(source_target).strip()
    parameter_name = str(source_parameter).strip()
    if not bus_name or not target_name or not parameter_name:
        raise SourceInterventionProbeError(
            "bus_label, source_target and source_parameter must not be empty"
        )

    baseline_path = Path(baseline_manifest_path).resolve()
    candidate_path = Path(candidate_manifest_path).resolve()
    baseline_manifest = _load_manifest(baseline_path)
    candidate_manifest = _load_manifest(candidate_path)

    baseline_range = _requested_range(baseline_manifest)
    candidate_range = _requested_range(candidate_manifest)
    if not _same_requested_range(baseline_range, candidate_range):
        raise SourceInterventionProbeError(
            "baseline and candidate capture ranges/formats do not match"
        )

    baseline_tap = _tap_by_label(
        baseline_path,
        baseline_manifest,
        bus_name,
    )
    candidate_tap = _tap_by_label(
        candidate_path,
        candidate_manifest,
        bus_name,
    )
    baseline_bus = _tap_provenance(baseline_manifest, bus_name)
    candidate_bus = _tap_provenance(candidate_manifest, bus_name)
    if not _matching_bus_identity(baseline_bus, candidate_bus):
        raise SourceInterventionProbeError(
            "baseline and candidate bus target identity does not match"
        )

    baseline_format = _probe_format(baseline_tap["artifact"])
    candidate_format = _probe_format(candidate_tap["artifact"])
    if baseline_format != candidate_format:
        raise SourceInterventionProbeError(
            "baseline and candidate bus artifacts must have identical sample rate, channels and sample count"
        )
    sample_rate = baseline_format["sample_rate"]
    if not 20.0 <= low_band_hz < sample_rate * 0.5:
        raise SourceInterventionProbeError(
            "low_band_hz must be >= 20 Hz and below Nyquist"
        )

    request = AnalysisRequest(sample_rate=sample_rate)
    baseline_audio = decode_audio_segment(
        baseline_tap["artifact"],
        request,
        sample_rate=sample_rate,
        channels=baseline_format["channels"],
    )
    candidate_audio = decode_audio_segment(
        candidate_tap["artifact"],
        request,
        sample_rate=sample_rate,
        channels=baseline_format["channels"],
    )

    window_frames = max(
        1,
        int(round(float(window_ms) * sample_rate / 1000.0)),
    )
    hop_frames = max(
        1,
        int(round(float(hop_ms) * sample_rate / 1000.0)),
    )
    baseline_env = _rms_envelope_db(
        baseline_audio,
        window_frames=window_frames,
        hop_frames=hop_frames,
    )
    candidate_env = _rms_envelope_db(
        candidate_audio,
        window_frames=window_frames,
        hop_frames=hop_frames,
    )
    baseline_low = _rms_envelope_db(
        _fft_lowpass(
            baseline_audio,
            sample_rate=sample_rate,
            cutoff_hz=low_band_hz,
        ),
        window_frames=window_frames,
        hop_frames=hop_frames,
    )
    candidate_low = _rms_envelope_db(
        _fft_lowpass(
            candidate_audio,
            sample_rate=sample_rate,
            cutoff_hz=low_band_hz,
        ),
        window_frames=window_frames,
        hop_frames=hop_frames,
    )
    lengths = {
        len(baseline_env),
        len(candidate_env),
        len(baseline_low),
        len(candidate_low),
    }
    if len(lengths) != 1:
        raise SourceInterventionProbeError(
            "baseline and candidate produced inconsistent analysis window counts"
        )

    baseline_active = (
        np.isfinite(baseline_env)
        & np.isfinite(candidate_env)
        & (baseline_env > active_threshold_dbfs)
    )
    active_count = int(np.count_nonzero(baseline_active))
    if active_count < 20:
        raise SourceInterventionProbeError(
            "too few active baseline bus windows for intervention evaluation"
        )
    top_threshold = float(
        np.percentile(
            baseline_env[baseline_active],
            100.0 * (1.0 - float(top_bus_fraction)),
        )
    )
    top_bus = baseline_active & (baseline_env >= top_threshold)
    top_count = int(np.count_nonzero(top_bus))
    if top_count < 3:
        raise SourceInterventionProbeError(
            "too few top-bus windows for intervention evaluation"
        )

    full_delta = candidate_env - baseline_env
    low_delta = candidate_low - baseline_low
    active_delta = full_delta[baseline_active]
    top_delta = full_delta[top_bus]
    active_low_delta = low_delta[baseline_active]
    top_low_delta = low_delta[top_bus]

    direction = -1.0 if declared_change_db < 0.0 else 1.0
    same_direction_fraction = float(
        np.mean(direction * top_delta > 0.0)
    )
    top_median_delta = float(np.median(top_delta))
    active_median_delta = float(np.median(active_delta))

    selected_events = _event_indices(
        baseline_env,
        top_bus,
        hop_frames=hop_frames,
        sample_rate=sample_rate,
    )
    events = [
        {
            "rank": rank,
            "center_time_s": (
                float(index * hop_frames)
                + float(window_frames) / 2.0
            )
            / float(sample_rate),
            "baseline_bus_rms_dbfs": float(baseline_env[index]),
            "candidate_bus_rms_dbfs": float(candidate_env[index]),
            "bus_delta_db": float(full_delta[index]),
            "baseline_low_band_rms_dbfs": float(baseline_low[index]),
            "candidate_low_band_rms_dbfs": float(candidate_low[index]),
            "low_band_delta_db": float(low_delta[index]),
        }
        for rank, index in enumerate(selected_events, start=1)
    ]

    return {
        "schema_version": SOURCE_INTERVENTION_PROBE_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "baseline_capture": {
            "manifest": str(baseline_path),
            "experiment_id": baseline_manifest.get("experiment_id"),
            "bus_content_sha256": baseline_tap["content_sha256"],
        },
        "candidate_capture": {
            "manifest": str(candidate_path),
            "experiment_id": candidate_manifest.get("experiment_id"),
            "bus_content_sha256": candidate_tap["content_sha256"],
        },
        "bus": baseline_bus,
        "requested_range": baseline_range,
        "declared_intervention": {
            "source_target": target_name,
            "source_parameter": parameter_name,
            "change_db": float(declared_change_db),
            "mutation_provenance_verified": False,
        },
        "windowing": {
            "window_ms": float(window_frames) * 1000.0 / float(sample_rate),
            "hop_ms": float(hop_frames) * 1000.0 / float(sample_rate),
            "active_threshold_dbfs": float(active_threshold_dbfs),
            "top_bus_fraction": float(top_bus_fraction),
            "low_band_hz": float(low_band_hz),
            "window_count": int(len(baseline_env)),
            "active_bus_window_count": active_count,
            "top_bus_window_count": top_count,
            "top_bus_threshold_dbfs": top_threshold,
        },
        "response": {
            "median_active_bus_delta_db": active_median_delta,
            "top_bus_median_delta_db": top_median_delta,
            "top_bus_p10_delta_db": _finite_percentile(top_delta, 10.0),
            "top_bus_p90_delta_db": _finite_percentile(top_delta, 90.0),
            "top_bus_min_delta_db": float(np.min(top_delta)),
            "top_bus_max_delta_db": float(np.max(top_delta)),
            "median_active_low_band_delta_db": float(
                np.median(active_low_delta)
            ),
            "top_bus_median_low_band_delta_db": float(
                np.median(top_low_delta)
            ),
            "active_bus_response_per_declared_db": (
                active_median_delta / float(declared_change_db)
            ),
            "top_bus_response_per_declared_db": (
                top_median_delta / float(declared_change_db)
            ),
            "top_bus_same_direction_fraction": same_direction_fraction,
        },
        "events": {
            "time_reference": "capture_start",
            "minimum_separation_ms": 250.0,
            "events": events,
        },
        "format": baseline_format,
        "interpretation_note": (
            "This artifact measures the observed response of the same captured "
            "bus across a baseline and candidate section. A strong response is "
            "causal evidence for the complete candidate state, but the declared "
            "source mutation is caller-supplied and is not independently proven "
            "by capture manifests. Bind the declaration to experiment-journal "
            "mutation provenance before treating the response as isolated to "
            "that source change. No subjective quality judgment or mutation "
            "authority is inferred."
        ),
    }
