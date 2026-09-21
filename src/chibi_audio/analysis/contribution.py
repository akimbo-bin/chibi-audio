from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .io import decode_audio_segment, probe_audio
from .models import AnalysisRequest
from .stress import _correlation, _fft_lowpass, _rms_envelope_db


BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION = (
    "chibi-audio-bus-contribution-attribution/v1"
)


class BusContributionAttributionError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BusContributionAttributionError(
            f"could not read capture manifest: {path}"
        ) from exc
    if payload.get("schema_version") != 1:
        raise BusContributionAttributionError(
            "bus contribution attribution requires capture manifest schema_version=1"
        )
    taps = payload.get("taps")
    if not isinstance(taps, list) or not taps:
        raise BusContributionAttributionError(
            "capture manifest does not contain finalized taps"
        )
    return payload


def _tap_by_label(
    manifest_path: Path,
    manifest: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    wanted = label.strip()
    if not wanted:
        raise BusContributionAttributionError("tap labels must not be empty")
    matches = [
        item
        for item in manifest["taps"]
        if isinstance(item, dict)
        and str(item.get("source_label") or "") == wanted
    ]
    if len(matches) != 1:
        raise BusContributionAttributionError(
            f"capture manifest must contain exactly one tap with source_label={wanted!r}; "
            f"found {len(matches)}"
        )
    item = matches[0]
    final = item.get("final")
    if not isinstance(final, dict):
        raise BusContributionAttributionError(
            f"tap {wanted!r} has no finalized artifact"
        )
    raw_path = final.get("path")
    expected_sha = final.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise BusContributionAttributionError(
            f"tap {wanted!r} finalized artifact has no path"
        )
    if (
        not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_sha)
    ):
        raise BusContributionAttributionError(
            f"tap {wanted!r} finalized artifact has no valid SHA-256"
        )
    artifact = Path(raw_path)
    if not artifact.is_absolute():
        artifact = manifest_path.parent / artifact
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise BusContributionAttributionError(
            f"tap {wanted!r} finalized artifact is missing: {artifact}"
        )
    observed_sha = _sha256(artifact)
    if observed_sha.lower() != expected_sha.lower():
        raise BusContributionAttributionError(
            f"tap {wanted!r} finalized artifact SHA-256 changed"
        )
    try:
        tap_id = int(item["tap_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BusContributionAttributionError(
            f"tap {wanted!r} has no readable tap_id"
        ) from exc
    return {
        "tap_id": tap_id,
        "source_label": wanted,
        "artifact": artifact,
        "content_sha256": observed_sha.lower(),
    }


def _target_metadata(
    manifest: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    live_session = manifest.get("live_session")
    if not isinstance(live_session, dict):
        return {}
    mixer_state = live_session.get("mixer_state")
    rows = mixer_state.get("tap_targets") if isinstance(mixer_state, dict) else None
    if not isinstance(rows, list):
        rows = live_session.get("tap_mapping")
    if not isinstance(rows, list):
        return {}
    matches = [
        item
        for item in rows
        if isinstance(item, dict)
        and str(item.get("source_label") or "") == label
    ]
    if len(matches) != 1:
        return {}
    row = matches[0]
    result: dict[str, Any] = {}
    for key in ("track_name", "track_index", "track_id", "mute", "solo"):
        if key in row:
            result[key] = row[key]
    return result


def _median_uplift(values: Any, top_mask: Any, other_mask: Any) -> float | None:
    import numpy as np

    top = np.asarray(values)[top_mask]
    other = np.asarray(values)[other_mask]
    if top.size < 3 or other.size < 3:
        return None
    value = float(np.median(top) - np.median(other))
    return value if math.isfinite(value) else None


def _positive_leader(
    rows: list[dict[str, Any]],
    metric: str,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if isinstance(row.get(metric), (int, float))
        and not isinstance(row.get(metric), bool)
        and math.isfinite(float(row[metric]))
        and float(row[metric]) > 0.0
    ]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: float(item[metric]))
    return {
        "source_label": row["source_label"],
        "value": float(row[metric]),
    }


def attribute_capture_bus_contribution(
    manifest_path: str | Path,
    *,
    bus_label: str,
    source_labels: Iterable[str],
    window_ms: float = 100.0,
    hop_ms: float = 10.0,
    low_band_hz: float = 250.0,
    active_threshold_dbfs: float = -45.0,
    top_bus_fraction: float = 0.10,
) -> dict[str, Any]:
    """Associate child-source activity with one captured bus output.

    This is same-capture diagnostic evidence. It deliberately reports separate
    full-band, low-band, uplift and activity dimensions and never infers one
    causal winner or authorizes a Live mutation.
    """
    import numpy as np

    for name, value in (
        ("window_ms", window_ms),
        ("hop_ms", hop_ms),
        ("low_band_hz", low_band_hz),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            raise BusContributionAttributionError(f"{name} must be finite and > 0")
    if hop_ms > window_ms:
        raise BusContributionAttributionError("hop_ms must be <= window_ms")
    if not -160.0 <= active_threshold_dbfs <= 0.0:
        raise BusContributionAttributionError(
            "active_threshold_dbfs must be between -160 and 0"
        )
    if not 0.01 <= top_bus_fraction <= 0.5:
        raise BusContributionAttributionError(
            "top_bus_fraction must be between 0.01 and 0.5"
        )

    bus_name = str(bus_label).strip()
    source_names = [str(value).strip() for value in source_labels]
    if not bus_name:
        raise BusContributionAttributionError("bus_label must not be empty")
    if not source_names or any(not value for value in source_names):
        raise BusContributionAttributionError(
            "source_labels must contain at least one non-empty label"
        )
    if len(set(source_names)) != len(source_names):
        raise BusContributionAttributionError("source_labels must be unique")
    if bus_name in source_names:
        raise BusContributionAttributionError(
            "bus_label and source_labels must be distinct"
        )

    manifest_source = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_source)
    labels = [bus_name, *source_names]
    taps = {
        label: _tap_by_label(manifest_source, manifest, label)
        for label in labels
    }

    probes = {
        label: probe_audio(item["artifact"])
        for label, item in taps.items()
    }
    sample_rates = {int(probe["sample_rate"]) for probe in probes.values()}
    channels = {int(probe["channels"]) for probe in probes.values()}
    raw_sample_counts = [probe.get("samples") for probe in probes.values()]
    if any(value is None for value in raw_sample_counts):
        raise BusContributionAttributionError(
            "selected capture taps must expose exact sample counts"
        )
    sample_counts = {int(value) for value in raw_sample_counts}
    if len(sample_rates) != 1 or len(channels) != 1 or len(sample_counts) != 1:
        raise BusContributionAttributionError(
            "selected capture taps must have identical sample rate, channels and sample count"
        )
    sample_rate = sample_rates.pop()
    channel_count = channels.pop()
    sample_count = sample_counts.pop()
    if not 20.0 <= low_band_hz < sample_rate * 0.5:
        raise BusContributionAttributionError(
            "low_band_hz must be >= 20 Hz and below Nyquist"
        )

    request = AnalysisRequest(sample_rate=sample_rate)
    audio = {
        label: decode_audio_segment(
            item["artifact"],
            request,
            sample_rate=sample_rate,
            channels=channel_count,
        )
        for label, item in taps.items()
    }
    window_frames = max(1, int(round(window_ms * sample_rate / 1000.0)))
    hop_frames = max(1, int(round(hop_ms * sample_rate / 1000.0)))
    envelopes = {
        label: _rms_envelope_db(
            values,
            window_frames=window_frames,
            hop_frames=hop_frames,
        )
        for label, values in audio.items()
    }
    low_envelopes = {
        label: _rms_envelope_db(
            _fft_lowpass(
                values,
                sample_rate=sample_rate,
                cutoff_hz=low_band_hz,
            ),
            window_frames=window_frames,
            hop_frames=hop_frames,
        )
        for label, values in audio.items()
    }

    lengths = {len(values) for values in envelopes.values()} | {
        len(values) for values in low_envelopes.values()
    }
    if len(lengths) != 1:
        raise BusContributionAttributionError(
            "selected capture taps produced inconsistent analysis window counts"
        )
    window_count = lengths.pop()
    bus = envelopes[bus_name]
    bus_low = low_envelopes[bus_name]
    bus_active = np.isfinite(bus) & (bus > active_threshold_dbfs)
    active_bus_count = int(np.count_nonzero(bus_active))
    if active_bus_count < 20:
        raise BusContributionAttributionError(
            "too few active bus windows for contribution attribution"
        )
    top_quantile = 100.0 * (1.0 - top_bus_fraction)
    top_threshold = float(np.percentile(bus[bus_active], top_quantile))
    top_bus = bus_active & (bus >= top_threshold)
    other_bus = bus_active & ~top_bus

    top_indices = np.flatnonzero(top_bus)
    ranked_indices = sorted(
        (int(index) for index in top_indices),
        key=lambda index: float(bus[index]),
        reverse=True,
    )
    hop_seconds = float(hop_frames) / float(sample_rate)
    minimum_event_separation_s = 0.25
    minimum_event_separation_windows = max(
        1,
        int(round(minimum_event_separation_s / hop_seconds)),
    )
    selected_event_indices: list[int] = []
    for index in ranked_indices:
        if any(
            abs(index - previous) < minimum_event_separation_windows
            for previous in selected_event_indices
        ):
            continue
        selected_event_indices.append(index)
        if len(selected_event_indices) >= 8:
            break
    bus_events = [
        {
            "rank": rank,
            "center_time_s": (
                float(index * hop_frames) + float(window_frames) / 2.0
            )
            / float(sample_rate),
            "bus_rms_dbfs": float(bus[index]),
            "bus_low_band_rms_dbfs": float(bus_low[index]),
        }
        for rank, index in enumerate(selected_event_indices, start=1)
    ]

    source_rows: list[dict[str, Any]] = []
    for label in source_names:
        full = envelopes[label]
        low = low_envelopes[label]
        source_active = np.isfinite(full) & (full > active_threshold_dbfs)
        robust = bus_active & source_active
        top_source = top_bus & source_active
        other_source = other_bus & source_active

        active_fraction = float(np.mean(source_active))
        top_active_fraction = (
            float(np.mean(source_active[top_bus]))
            if int(np.count_nonzero(top_bus))
            else None
        )
        other_active_fraction = (
            float(np.mean(source_active[other_bus]))
            if int(np.count_nonzero(other_bus))
            else None
        )
        row: dict[str, Any] = {
            "source_label": label,
            "tap_id": taps[label]["tap_id"],
            "content_sha256": taps[label]["content_sha256"],
            **_target_metadata(manifest, label),
            "active_window_fraction": active_fraction,
            "active_fraction_within_top_bus": top_active_fraction,
            "top_bus_active_fraction_delta": (
                top_active_fraction - other_active_fraction
                if top_active_fraction is not None
                and other_active_fraction is not None
                else None
            ),
            "rms_correlation_to_bus": _correlation(full, bus, robust),
            "low_band_correlation_to_bus": _correlation(low, bus_low, robust),
            "top_bus_rms_uplift_db": _median_uplift(
                full,
                top_source,
                other_source,
            ),
            "top_bus_low_band_uplift_db": _median_uplift(
                low,
                top_source,
                other_source,
            ),
            "median_rms_dbfs": (
                float(np.median(full[source_active]))
                if int(np.count_nonzero(source_active))
                else None
            ),
            "median_low_band_rms_dbfs": (
                float(np.median(low[source_active]))
                if int(np.count_nonzero(source_active))
                else None
            ),
        }
        source_rows.append(row)

    leader_metrics = (
        "rms_correlation_to_bus",
        "low_band_correlation_to_bus",
        "top_bus_rms_uplift_db",
        "top_bus_low_band_uplift_db",
        "top_bus_active_fraction_delta",
    )
    leaders = {
        metric: _positive_leader(source_rows, metric)
        for metric in leader_metrics
    }

    return {
        "schema_version": BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION,
        "capture_manifest": str(manifest_source),
        "experiment_id": manifest.get("experiment_id"),
        "effect_state": "NOT_STARTED",
        "reference_bus": {
            "source_label": bus_name,
            "tap_id": taps[bus_name]["tap_id"],
            "content_sha256": taps[bus_name]["content_sha256"],
            **_target_metadata(manifest, bus_name),
        },
        "windowing": {
            "window_ms": float(window_frames) * 1000.0 / float(sample_rate),
            "hop_ms": float(hop_frames) * 1000.0 / float(sample_rate),
            "active_threshold_dbfs": float(active_threshold_dbfs),
            "top_bus_fraction": float(top_bus_fraction),
            "low_band_hz": float(low_band_hz),
            "window_count": int(window_count),
            "active_bus_window_count": active_bus_count,
            "top_bus_threshold_dbfs": top_threshold,
        },
        "bus_events": {
            "time_reference": "capture_start",
            "minimum_separation_ms": minimum_event_separation_s * 1000.0,
            "events": bus_events,
        },
        "sources": source_rows,
        "leaders": leaders,
        "format": {
            "sample_rate": sample_rate,
            "channels": channel_count,
            "samples": sample_count,
        },
        "no_overall_winner": True,
        "interpretation_note": (
            "Child-source activity is associated with the reference bus output "
            "within the same finalized capture. Full-band, low-band, uplift and "
            "activity evidence are reported separately; no overall winner is "
            "inferred. These associations do not prove causality or subjective "
            "quality and do not authorize a mutation."
        ),
    }
