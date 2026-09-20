from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .io import decode_audio_segment, probe_audio
from .models import AnalysisRequest


MASTER_STRESS_ATTRIBUTION_SCHEMA_VERSION = "chibi-audio-master-stress-attribution/v1"


class MasterStressAttributionError(ValueError):
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
        raise MasterStressAttributionError(f"could not read capture manifest: {path}") from exc
    if payload.get("schema_version") != 1:
        raise MasterStressAttributionError("master stress attribution requires capture manifest schema_version=1")
    taps = payload.get("taps")
    if not isinstance(taps, list) or not taps:
        raise MasterStressAttributionError("capture manifest does not contain finalized taps")
    return payload


def _tap_by_label(manifest_path: Path, manifest: dict[str, Any], label: str) -> dict[str, Any]:
    wanted = label.strip()
    if not wanted:
        raise MasterStressAttributionError("tap labels must not be empty")
    matches = [
        item for item in manifest["taps"]
        if isinstance(item, dict) and str(item.get("source_label") or "") == wanted
    ]
    if len(matches) != 1:
        raise MasterStressAttributionError(
            f"capture manifest must contain exactly one tap with source_label={wanted!r}; found {len(matches)}"
        )
    item = matches[0]
    final = item.get("final")
    if not isinstance(final, dict):
        raise MasterStressAttributionError(f"tap {wanted!r} has no finalized artifact")
    raw_path = final.get("path")
    expected_sha = final.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        raise MasterStressAttributionError(f"tap {wanted!r} finalized artifact has no path")
    if (
        not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_sha)
    ):
        raise MasterStressAttributionError(f"tap {wanted!r} finalized artifact has no valid SHA-256")
    artifact = Path(raw_path)
    if not artifact.is_absolute():
        artifact = manifest_path.parent / artifact
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise MasterStressAttributionError(f"tap {wanted!r} finalized artifact is missing: {artifact}")
    observed_sha = _sha256(artifact)
    if observed_sha.lower() != expected_sha.lower():
        raise MasterStressAttributionError(f"tap {wanted!r} finalized artifact SHA-256 changed")
    return {
        "tap_id": int(item["tap_id"]),
        "source_label": wanted,
        "artifact": artifact,
        "content_sha256": observed_sha.lower(),
    }


def _rms_envelope_db(audio: Any, *, window_frames: int, hop_frames: int) -> Any:
    import numpy as np

    values = np.asarray(audio, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < window_frames:
        raise MasterStressAttributionError("audio is too short for the requested stress window")
    power = np.mean(values * values, axis=1)
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(power)))
    starts = np.arange(0, len(power) - window_frames + 1, hop_frames, dtype=np.int64)
    mean_power = (cumulative[starts + window_frames] - cumulative[starts]) / float(window_frames)
    return 10.0 * np.log10(np.maximum(mean_power, 1.0e-24))


def _fft_lowpass(audio: Any, *, sample_rate: int, cutoff_hz: float) -> Any:
    import numpy as np

    values = np.asarray(audio, dtype=np.float64)
    padding = min(sample_rate, max(0, values.shape[0] // 4))
    if padding:
        padded = np.pad(values, ((padding, padding), (0, 0)), mode="reflect")
    else:
        padded = values
    spectrum = np.fft.rfft(padded, axis=0)
    frequencies = np.fft.rfftfreq(padded.shape[0], d=1.0 / float(sample_rate))
    spectrum[frequencies > cutoff_hz, :] = 0.0
    filtered = np.fft.irfft(spectrum, n=padded.shape[0], axis=0)
    if padding:
        filtered = filtered[padding:-padding]
    return filtered


def _correlation(left: Any, right: Any, mask: Any) -> float | None:
    import numpy as np

    left_values = np.asarray(left)[mask]
    right_values = np.asarray(right)[mask]
    if left_values.size < 20:
        return None
    if float(np.std(left_values)) <= 1.0e-12 or float(np.std(right_values)) <= 1.0e-12:
        return None
    value = float(np.corrcoef(left_values, right_values)[0, 1])
    return value if math.isfinite(value) else None


def _lagged_pair(first: Any, second: Any, lag: int) -> tuple[Any, Any]:
    if lag < 0:
        return first[-lag:], second[:lag]
    if lag > 0:
        return first[:-lag], second[lag:]
    return first, second


def _estimate_post_delay(
    premaster: Any,
    master: Any,
    *,
    max_lag_frames: int,
    active_threshold_dbfs: float,
) -> tuple[int, float]:
    import numpy as np

    best_lag: int | None = None
    best_corr: float | None = None
    for lag in range(-max_lag_frames, max_lag_frames + 1):
        left, right = _lagged_pair(premaster, master, lag)
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
        raise MasterStressAttributionError("could not estimate master-chain latency from active RMS envelopes")
    return best_lag, best_corr


def _trim_for_post_delay(values: Any, lag: int) -> Any:
    if lag < 0:
        return values[-lag:]
    if lag > 0:
        return values[:-lag]
    return values


def attribute_capture_master_stress(
    manifest_path: str | Path,
    *,
    premaster_label: str,
    master_label: str,
    source_labels: Iterable[str],
    window_ms: float = 100.0,
    hop_ms: float = 10.0,
    max_latency_ms: float = 500.0,
    low_band_hz: float = 250.0,
    active_threshold_dbfs: float = -45.0,
    top_stress_fraction: float = 0.10,
) -> dict[str, Any]:
    """Attribute relative master-chain gain suppression to aligned source/group evidence.

    Positive post_delay_ms means the master output lags the premaster input. Stress is
    defined as the median active master-chain RMS gain minus instantaneous aligned RMS
    gain, so larger positive values mean more relative gain suppression. Correlations
    are diagnostic evidence only and do not prove causality or subjective quality.
    """
    import numpy as np

    for name, value in (("window_ms", window_ms), ("hop_ms", hop_ms), ("max_latency_ms", max_latency_ms), ("low_band_hz", low_band_hz)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise MasterStressAttributionError(f"{name} must be finite and > 0")
    if hop_ms > window_ms:
        raise MasterStressAttributionError("hop_ms must be <= window_ms")
    if not -160.0 <= active_threshold_dbfs <= 0.0:
        raise MasterStressAttributionError("active_threshold_dbfs must be between -160 and 0")
    if not 0.01 <= top_stress_fraction <= 0.5:
        raise MasterStressAttributionError("top_stress_fraction must be between 0.01 and 0.5")

    source_names = [str(value).strip() for value in source_labels]
    if not source_names or any(not value for value in source_names):
        raise MasterStressAttributionError("source_labels must contain at least one non-empty label")
    if len(set(source_names)) != len(source_names):
        raise MasterStressAttributionError("source_labels must be unique")

    manifest_source = Path(manifest_path).resolve()
    manifest = _load_manifest(manifest_source)
    selected = [premaster_label, master_label, *source_names]
    if len(set(selected)) != len(selected):
        raise MasterStressAttributionError("premaster, master and source labels must be distinct")
    taps = {label: _tap_by_label(manifest_source, manifest, label) for label in selected}

    probes = {label: probe_audio(item["artifact"]) for label, item in taps.items()}
    sample_rates = {int(probe["sample_rate"]) for probe in probes.values()}
    channels = {int(probe["channels"]) for probe in probes.values()}
    raw_sample_counts = [probe.get("samples") for probe in probes.values()]
    if any(value is None for value in raw_sample_counts):
        raise MasterStressAttributionError("selected capture taps must expose exact sample counts")
    sample_counts = {int(value) for value in raw_sample_counts}
    if len(sample_rates) != 1 or len(channels) != 1 or len(sample_counts) != 1:
        raise MasterStressAttributionError(
            "selected capture taps must have identical sample rate, channels and sample count"
        )
    sample_rate = sample_rates.pop()
    channel_count = channels.pop()
    sample_count = sample_counts.pop()
    if not 20.0 <= low_band_hz < sample_rate * 0.5:
        raise MasterStressAttributionError("low_band_hz must be >= 20 Hz and below Nyquist")

    request = AnalysisRequest(sample_rate=sample_rate)
    audio = {
        label: decode_audio_segment(item["artifact"], request, sample_rate=sample_rate, channels=channel_count)
        for label, item in taps.items()
    }
    window_frames = max(1, int(round(window_ms * sample_rate / 1000.0)))
    hop_frames = max(1, int(round(hop_ms * sample_rate / 1000.0)))
    envelopes = {
        label: _rms_envelope_db(values, window_frames=window_frames, hop_frames=hop_frames)
        for label, values in audio.items()
    }
    low_envelopes = {
        label: _rms_envelope_db(
            _fft_lowpass(values, sample_rate=sample_rate, cutoff_hz=low_band_hz),
            window_frames=window_frames,
            hop_frames=hop_frames,
        )
        for label, values in audio.items()
        if label in source_names
    }

    max_lag_frames = max(1, int(round(max_latency_ms / hop_ms)))
    lag, alignment_corr = _estimate_post_delay(
        envelopes[premaster_label],
        envelopes[master_label],
        max_lag_frames=max_lag_frames,
        active_threshold_dbfs=active_threshold_dbfs,
    )
    premaster, master = _lagged_pair(envelopes[premaster_label], envelopes[master_label], lag)
    aligned_sources = {label: _trim_for_post_delay(envelopes[label], lag) for label in source_names}
    aligned_low = {label: _trim_for_post_delay(low_envelopes[label], lag) for label in source_names}

    lengths = [len(premaster), len(master), *(len(value) for value in aligned_sources.values()), *(len(value) for value in aligned_low.values())]
    length = min(lengths)
    premaster = premaster[:length]
    master = master[:length]
    aligned_sources = {key: value[:length] for key, value in aligned_sources.items()}
    aligned_low = {key: value[:length] for key, value in aligned_low.items()}

    active = (
        np.isfinite(premaster)
        & np.isfinite(master)
        & (premaster > active_threshold_dbfs)
        & (master > active_threshold_dbfs)
    )
    if int(np.count_nonzero(active)) < 20:
        raise MasterStressAttributionError("too few active aligned windows for master stress attribution")
    chain_gain = master - premaster
    median_gain = float(np.median(chain_gain[active]))
    stress = median_gain - chain_gain
    lower, upper = np.percentile(stress[active], [1.0, 99.0])
    robust = active & (stress >= lower) & (stress <= upper)
    if int(np.count_nonzero(robust)) < 20:
        raise MasterStressAttributionError("too few robust active windows for master stress attribution")
    stress_values = stress[robust]
    top_quantile = 100.0 * (1.0 - top_stress_fraction)
    top_threshold = float(np.percentile(stress_values, top_quantile))
    top_stress = robust & (stress >= top_threshold)

    # Preserve a small set of time-localized anchors so downstream orchestration
    # can inspect a 2-8 second window around actual stress events instead of
    # rescanning the entire section. Events are ranked by stress magnitude and
    # separated to avoid returning adjacent windows from the same excursion.
    top_indices = np.flatnonzero(top_stress)
    ranked_indices = sorted(
        (int(index) for index in top_indices),
        key=lambda index: float(stress[index]),
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
    premaster_offset_windows = max(0, -lag)
    stress_events = [
        {
            "rank": rank,
            "center_time_s": (
                (
                    float(premaster_offset_windows + index) * float(hop_frames)
                    + float(window_frames) / 2.0
                )
                / float(sample_rate)
            ),
            "stress_db": float(stress[index]),
            "chain_gain_db": float(chain_gain[index]),
            "premaster_rms_dbfs": float(premaster[index]),
            "master_rms_dbfs": float(master[index]),
        }
        for rank, index in enumerate(selected_event_indices, start=1)
    ]

    premaster_corr = _correlation(premaster, stress, robust)
    source_rows: list[dict[str, Any]] = []
    for label in source_names:
        full = aligned_sources[label]
        low = aligned_low[label]
        source_active = robust & np.isfinite(full) & (full > -100.0)
        low_active = robust & np.isfinite(low) & (low > -100.0)
        top_source = top_stress & source_active
        top_low = top_stress & low_active
        full_uplift = None
        low_uplift = None
        if int(np.count_nonzero(source_active)) and int(np.count_nonzero(top_source)):
            full_uplift = float(np.mean(full[top_source]) - np.mean(full[source_active]))
        if int(np.count_nonzero(low_active)) and int(np.count_nonzero(top_low)):
            low_uplift = float(np.mean(low[top_low]) - np.mean(low[low_active]))
        active_fraction = float(np.count_nonzero(source_active)) / float(np.count_nonzero(robust))
        top_active_fraction = (
            float(np.count_nonzero(top_source)) / float(np.count_nonzero(top_stress))
            if int(np.count_nonzero(top_stress))
            else None
        )
        source_rows.append(
            {
                "source_label": label,
                "tap_id": taps[label]["tap_id"],
                "content_sha256": taps[label]["content_sha256"],
                "rms_correlation_to_stress": _correlation(full, stress, source_active),
                "low_band_correlation_to_stress": _correlation(low, stress, low_active),
                "top_stress_rms_uplift_db": full_uplift,
                "top_stress_low_band_uplift_db": low_uplift,
                "active_window_fraction": active_fraction,
                "active_fraction_within_top_stress": top_active_fraction,
                "top_stress_active_fraction_delta": (
                    top_active_fraction - active_fraction
                    if top_active_fraction is not None
                    else None
                ),
            }
        )

    def positive_leader(metric: str) -> dict[str, Any] | None:
        candidates = [
            row for row in source_rows
            if isinstance(row.get(metric), (int, float))
            and math.isfinite(float(row[metric]))
            and float(row[metric]) > 0.0
        ]
        if not candidates:
            return None
        row = max(candidates, key=lambda item: float(item[metric]))
        return {"source_label": row["source_label"], "value": float(row[metric])}

    return {
        "schema_version": MASTER_STRESS_ATTRIBUTION_SCHEMA_VERSION,
        "capture_manifest": str(manifest_source),
        "experiment_id": manifest.get("experiment_id"),
        "effect_state": "NOT_STARTED",
        "premaster": {
            "source_label": premaster_label,
            "tap_id": taps[premaster_label]["tap_id"],
            "content_sha256": taps[premaster_label]["content_sha256"],
        },
        "master": {
            "source_label": master_label,
            "tap_id": taps[master_label]["tap_id"],
            "content_sha256": taps[master_label]["content_sha256"],
        },
        "alignment": {
            "post_delay_ms": float(lag) * float(hop_frames) * 1000.0 / float(sample_rate),
            "envelope_correlation": alignment_corr,
            "max_latency_ms": float(max_latency_ms),
        },
        "windowing": {
            "window_ms": float(window_frames) * 1000.0 / float(sample_rate),
            "hop_ms": float(hop_frames) * 1000.0 / float(sample_rate),
            "active_threshold_dbfs": float(active_threshold_dbfs),
            "top_stress_fraction": float(top_stress_fraction),
            "low_band_hz": float(low_band_hz),
            "aligned_window_count": int(length),
            "robust_active_window_count": int(np.count_nonzero(robust)),
        },
        "master_chain": {
            "median_rms_gain_db": median_gain,
            "stress_p90_db": float(np.percentile(stress_values, 90.0)),
            "stress_p99_db": float(np.percentile(stress_values, 99.0)),
            "premaster_rms_correlation_to_stress": premaster_corr,
        },
        "stress_events": {
            "time_reference": "premaster_capture_start",
            "minimum_separation_ms": minimum_event_separation_s * 1000.0,
            "events": stress_events,
        },
        "sources": source_rows,
        "leaders": {
            "rms_correlation_to_stress": positive_leader("rms_correlation_to_stress"),
            "low_band_correlation_to_stress": positive_leader("low_band_correlation_to_stress"),
            "top_stress_rms_uplift_db": positive_leader("top_stress_rms_uplift_db"),
            "top_stress_low_band_uplift_db": positive_leader("top_stress_low_band_uplift_db"),
            "top_stress_active_fraction_delta": positive_leader("top_stress_active_fraction_delta"),
        },
        "format": {
            "sample_rate": sample_rate,
            "channels": channel_count,
            "samples": sample_count,
        },
        "interpretation_note": (
            "Stress is relative RMS gain suppression after latency alignment. Full-band, low-band, level-uplift and activity evidence are reported separately; no overall winner is inferred. These associations do not prove causality or subjective quality and do not authorize a mutation."
        ),
    }
