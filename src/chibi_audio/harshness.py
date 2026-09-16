from __future__ import annotations

from pathlib import Path
from typing import Any

from .audio import AudioAnalysisError, _db, _np, decode_audio


def _scale(values):
    np = _np()
    values = np.asarray(values, dtype=np.float64)
    lo = float(np.percentile(values, 10.0))
    hi = float(np.percentile(values, 95.0))
    if hi <= lo + 1e-12:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def analyze_harshness_array(
    audio,
    sample_rate: int,
    *,
    frame_ms: float = 50.0,
    hop_ms: float = 10.0,
    top_events: int = 12,
    min_event_gap_ms: float = 80.0,
) -> dict[str, Any]:
    """Rank bright/attack-heavy moments.

    The score is deliberately a within-file diagnostic proxy, not a standardized
    psychoacoustic harshness metric and not a claim that an event sounds bad.
    """
    np = _np()
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 2:
        mono = np.mean(data, axis=1)
    elif data.ndim == 1:
        mono = data
    else:
        raise AudioAnalysisError("harshness analysis expects mono or stereo audio")
    if len(mono) < 8:
        raise AudioAnalysisError("audio is too short for harshness analysis")

    frame = min(len(mono), max(64, int(round(frame_ms * sample_rate / 1000.0))))
    hop = max(1, int(round(hop_ms * sample_rate / 1000.0)))
    starts = np.arange(0, max(1, len(mono) - frame + 1), hop, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)

    window = np.hanning(frame).astype(np.float64)
    freqs = np.fft.rfftfreq(frame, d=1.0 / float(sample_rate))
    audible = (freqs >= 20.0) & (freqs < min(20000.0, sample_rate / 2.0))
    high = (freqs >= 6000.0) & (freqs < min(20000.0, sample_rate / 2.0))
    air = (freqs >= 12000.0) & (freqs < min(20000.0, sample_rate / 2.0))
    perceptual_weight = np.zeros_like(freqs)
    weight_mask = freqs >= 1000.0
    perceptual_weight[weight_mask] = np.sqrt(freqs[weight_mask] / 1000.0)

    rms: list[float] = []
    crest: list[float] = []
    centroid: list[float] = []
    high_pct: list[float] = []
    air_pct: list[float] = []
    sharpness_proxy: list[float] = []

    for start in starts:
        chunk = mono[int(start): int(start) + frame]
        if len(chunk) < frame:
            chunk = np.pad(chunk, (0, frame - len(chunk)))
        chunk_rms = float(np.sqrt(np.mean(chunk * chunk)))
        chunk_peak = float(np.max(np.abs(chunk)))
        power = np.abs(np.fft.rfft(chunk * window)) ** 2
        total = float(power[audible].sum())
        if total > 1e-24:
            centroid_value = float((freqs[audible] * power[audible]).sum() / total)
            high_value = 100.0 * float(power[high].sum() / total)
            air_value = 100.0 * float(power[air].sum() / total)
            sharp_value = float((power[audible] * perceptual_weight[audible]).sum() / total)
        else:
            centroid_value = high_value = air_value = sharp_value = 0.0
        rms.append(chunk_rms)
        crest.append(_db(chunk_peak) - _db(chunk_rms))
        centroid.append(centroid_value)
        high_pct.append(high_value)
        air_pct.append(air_value)
        sharpness_proxy.append(sharp_value)

    rms_db = np.asarray([_db(float(value)) for value in rms])
    crest_values = np.asarray(crest)
    centroid_values = np.asarray(centroid)
    high_values = np.asarray(high_pct)
    air_values = np.asarray(air_pct)
    sharp_values = np.asarray(sharpness_proxy)
    attack_db = np.maximum(0.0, np.diff(rms_db, prepend=rms_db[0]))

    activity = _scale(rms_db)
    score = activity * (
        0.30 * _scale(high_values)
        + 0.25 * _scale(centroid_values)
        + 0.20 * _scale(sharp_values)
        + 0.15 * _scale(attack_db)
        + 0.10 * _scale(crest_values)
    )

    min_gap_frames = max(1, int(round(min_event_gap_ms / hop_ms)))
    selected: list[int] = []
    for raw_index in np.argsort(score)[::-1]:
        index = int(raw_index)
        if float(score[index]) <= 0.0:
            break
        if any(abs(index - other) < min_gap_frames for other in selected):
            continue
        selected.append(index)
        if len(selected) >= top_events:
            break

    events = []
    for index in selected:
        events.append(
            {
                "start_s": float(starts[index]) / sample_rate,
                "end_s": min(len(mono), int(starts[index]) + frame) / sample_rate,
                "score": float(score[index]),
                "rms_dbfs": float(rms_db[index]),
                "crest_db": float(crest_values[index]),
                "spectral_centroid_hz": float(centroid_values[index]),
                "high_6_20k_pct": float(high_values[index]),
                "air_12_20k_pct": float(air_values[index]),
                "attack_db": float(attack_db[index]),
                "sharpness_proxy": float(sharp_values[index]),
            }
        )

    active = rms_db > max(-80.0, float(np.percentile(rms_db, 20.0)))

    def stat(values, percentile: float) -> float:
        return float(np.percentile(values[active], percentile)) if np.any(active) else 0.0

    return {
        "sample_rate": int(sample_rate),
        "duration_s": len(mono) / float(sample_rate),
        "frame_ms": float(frame_ms),
        "hop_ms": float(hop_ms),
        "metric_status": "relative_diagnostic_proxy_not_standardized_harshness",
        "summary": {
            "median_centroid_hz": stat(centroid_values, 50.0),
            "p95_centroid_hz": stat(centroid_values, 95.0),
            "median_high_6_20k_pct": stat(high_values, 50.0),
            "p95_high_6_20k_pct": stat(high_values, 95.0),
            "median_sharpness_proxy": stat(sharp_values, 50.0),
            "p95_sharpness_proxy": stat(sharp_values, 95.0),
        },
        "events": events,
    }


def analyze_harshness(path: str | Path, sample_rate: int = 48000, **kwargs) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise AudioAnalysisError(f"Audio file does not exist: {source}")
    result = analyze_harshness_array(
        decode_audio(source, sample_rate=sample_rate),
        sample_rate,
        **kwargs,
    )
    result["path"] = str(source)
    return result


def compare_harshness_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for label, report in reports.items():
        summary = report.get("summary") or {}
        top = (report.get("events") or [{}])[0]
        rows.append(
            {
                "label": label,
                "p95_high_6_20k_pct": float(summary.get("p95_high_6_20k_pct", 0.0)),
                "p95_centroid_hz": float(summary.get("p95_centroid_hz", 0.0)),
                "p95_sharpness_proxy": float(summary.get("p95_sharpness_proxy", 0.0)),
                "top_event_score": float(top.get("score", 0.0)),
                "top_event_start_s": top.get("start_s"),
            }
        )
    rows.sort(
        key=lambda row: (
            row["top_event_score"],
            row["p95_sharpness_proxy"],
            row["p95_high_6_20k_pct"],
        ),
        reverse=True,
    )
    return {
        "ranking": rows,
        "warning": "Relative diagnostic evidence only; artist listening remains authoritative.",
    }
