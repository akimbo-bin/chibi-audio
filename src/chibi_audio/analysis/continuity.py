from __future__ import annotations

import math
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


CONTINUITY_VERSION = "0.1.0"


def _range(context: AnalysisContext) -> dict[str, float]:
    start = context.absolute_start_seconds
    duration = context.decoded_duration_seconds
    return {
        "start_seconds": start,
        "end_seconds": start + duration,
        "duration_seconds": duration,
    }


def _db_ratio(numerator: float, denominator: float) -> float | None:
    if numerator <= 0.0 or denominator <= 0.0:
        return None
    return 20.0 * math.log10(numerator / denominator)


def _even_starts(frame_count: int, window_size: int, maximum: int, np) -> list[int]:
    if frame_count <= window_size:
        return [0]
    count = min(maximum, max(2, math.ceil(frame_count / window_size)))
    last = frame_count - window_size
    return sorted({int(round(value)) for value in np.linspace(0, last, count)})


class StereoTimelineAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_stereo_timeline",
        version=CONTINUITY_VERSION,
        capabilities=frozenset({AnalysisCapability.STEREO_TIMELINE}),
        cost=AnalysisCost.CHEAP,
        implementation="bounded 400 ms stereo correlation / mid-side timeline",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        source_channels = int(context.probe["channels"])
        range_payload = _range(context)
        if source_channels != 2:
            return {
                AnalysisCapability.STEREO_TIMELINE.value: {
                    "available": False,
                    "source_channels": source_channels,
                    "reason": "time-varying stereo evidence requires an original two-channel source",
                    "range": range_payload,
                }
            }

        audio = context.audio.astype(np.float64, copy=False)
        sr = context.request.sample_rate
        window_size = min(len(audio), max(64, round(0.4 * sr)))
        starts = _even_starts(len(audio), window_size, context.request.timeline_max_points, np)
        rows: list[dict[str, Any]] = []

        for start in starts:
            segment = audio[start : start + window_size]
            left = segment[:, 0]
            right = segment[:, 1]
            left_std = float(np.std(left))
            right_std = float(np.std(right))
            correlation = (
                float(np.corrcoef(left, right)[0, 1])
                if left_std > 0.0 and right_std > 0.0
                else None
            )
            mid = (left + right) * 0.5
            side = (left - right) * 0.5
            mid_energy = float(np.mean(mid * mid))
            side_energy = float(np.mean(side * side))
            ms_total = mid_energy + side_energy
            mid_rms = math.sqrt(mid_energy)
            side_rms = math.sqrt(side_energy)
            left_rms = math.sqrt(float(np.mean(left * left)))
            right_rms = math.sqrt(float(np.mean(right * right)))
            rows.append(
                {
                    "time_seconds": context.absolute_start_seconds
                    + (start + len(segment) * 0.5) / float(sr),
                    "correlation": correlation,
                    "side_energy_fraction": side_energy / ms_total if ms_total > 0.0 else None,
                    "side_to_mid_db": _db_ratio(side_rms, mid_rms),
                    "left_minus_right_rms_db": _db_ratio(left_rms, right_rms),
                }
            )

        correlations = [float(row["correlation"]) for row in rows if row["correlation"] is not None]
        side_fractions = [
            float(row["side_energy_fraction"])
            for row in rows
            if row["side_energy_fraction"] is not None
        ]
        balances = [
            float(row["left_minus_right_rms_db"])
            for row in rows
            if row["left_minus_right_rms_db"] is not None
        ]

        widest = max(
            (row for row in rows if row["side_energy_fraction"] is not None),
            key=lambda row: float(row["side_energy_fraction"]),
            default=None,
        )
        most_negative = min(
            (row for row in rows if row["correlation"] is not None),
            key=lambda row: float(row["correlation"]),
            default=None,
        )

        def _summary(values: list[float]) -> dict[str, float | None]:
            if not values:
                return {"p10": None, "median": None, "p90": None}
            array = np.asarray(values, dtype=np.float64)
            return {
                "p10": float(np.percentile(array, 10)),
                "median": float(np.median(array)),
                "p90": float(np.percentile(array, 90)),
            }

        return {
            AnalysisCapability.STEREO_TIMELINE.value: {
                "available": True,
                "source_channels": source_channels,
                "correlation": _summary(correlations),
                "side_energy_fraction": _summary(side_fractions),
                "left_minus_right_rms_db": _summary(balances),
                "widest_sampled_window": widest,
                "most_negative_correlation_window": most_negative,
                "timeline": rows,
                "timeline_points": len(rows),
                "window_size_seconds": window_size / float(sr),
                "interpretation_note": (
                    "time-varying correlation, mid/side energy and channel balance are diagnostic evidence; "
                    "they do not imply a preferred stereo width or automatic narrowing"
                ),
                "range": range_payload,
            }
        }


class LoopSeamAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_loop_seam",
        version=CONTINUITY_VERSION,
        capabilities=frozenset({AnalysisCapability.LOOP_SEAM}),
        cost=AnalysisCost.CHEAP,
        implementation="requested-range endpoint / derivative / head-tail continuity evidence",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        range_payload = _range(context)
        sr = context.request.sample_rate
        if len(audio) < 4:
            return {
                AnalysisCapability.LOOP_SEAM.value: {
                    "available": False,
                    "reason": "loop seam evidence requires at least four decoded frames",
                    "range": range_payload,
                }
            }

        first = audio[0]
        second = audio[1]
        penultimate = audio[-2]
        last = audio[-1]
        seam_derivative = first - last
        tail_derivative = last - penultimate
        head_derivative = second - first
        endpoint_jump = seam_derivative
        derivative_entry_delta = seam_derivative - tail_derivative
        derivative_exit_delta = head_derivative - seam_derivative

        edge_frames = min(len(audio) // 2, max(8, round(0.02 * sr)))
        head = audio[:edge_frames]
        tail = audio[-edge_frames:]
        head_rms = math.sqrt(float(np.mean(head * head)))
        tail_rms = math.sqrt(float(np.mean(tail * tail)))
        peak = float(np.max(np.abs(audio)))
        waveform_rmse = math.sqrt(float(np.mean((head - tail) ** 2)))

        head_flat = head.reshape(-1)
        tail_flat = tail.reshape(-1)
        head_std = float(np.std(head_flat))
        tail_std = float(np.std(tail_flat))
        head_tail_correlation = (
            float(np.corrcoef(head_flat, tail_flat)[0, 1])
            if head_std > 0.0 and tail_std > 0.0
            else None
        )

        max_jump = float(np.max(np.abs(endpoint_jump)))
        max_derivative_discontinuity = float(
            max(np.max(np.abs(derivative_entry_delta)), np.max(np.abs(derivative_exit_delta)))
        )
        per_channel = []
        for index in range(audio.shape[1]):
            per_channel.append(
                {
                    "channel_index": index,
                    "endpoint_jump": float(endpoint_jump[index]),
                    "tail_derivative": float(tail_derivative[index]),
                    "seam_derivative": float(seam_derivative[index]),
                    "head_derivative": float(head_derivative[index]),
                    "derivative_entry_discontinuity": float(derivative_entry_delta[index]),
                    "derivative_exit_discontinuity": float(derivative_exit_delta[index]),
                }
            )

        return {
            AnalysisCapability.LOOP_SEAM.value: {
                "available": True,
                "source_channels": int(context.probe["channels"]),
                "max_abs_endpoint_jump": max_jump,
                "endpoint_jump_relative_to_peak": max_jump / peak if peak > 0.0 else None,
                "max_abs_derivative_discontinuity": max_derivative_discontinuity,
                "derivative_discontinuity_relative_to_peak": (
                    max_derivative_discontinuity / peak if peak > 0.0 else None
                ),
                "head_rms": head_rms,
                "tail_rms": tail_rms,
                "head_minus_tail_rms_db": _db_ratio(head_rms, tail_rms),
                "head_tail_waveform_rmse": waveform_rmse,
                "head_tail_waveform_rmse_relative_to_peak": waveform_rmse / peak if peak > 0.0 else None,
                "head_tail_waveform_correlation": head_tail_correlation,
                "edge_window_seconds": edge_frames / float(sr),
                "per_channel": per_channel,
                "interpretation_note": (
                    "endpoint, derivative and head/tail continuity describe the requested range boundary; "
                    "they are click/seam evidence rather than a binary judgement that a loop is good or bad"
                ),
                "range": range_payload,
            }
        }


def continuity_analyzers():
    return StereoTimelineAnalyzer(), LoopSeamAnalyzer()
