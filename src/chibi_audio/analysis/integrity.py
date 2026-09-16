from __future__ import annotations

import math
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


INTEGRITY_VERSION = "0.1.0"


def _range(context: AnalysisContext) -> dict[str, float]:
    start = context.absolute_start_seconds
    duration = context.decoded_duration_seconds
    return {
        "start_seconds": start,
        "end_seconds": start + duration,
        "duration_seconds": duration,
    }


def _runs(mask, minimum: int, maximum_rows: int, np) -> tuple[int, list[tuple[int, int]]]:
    values = np.asarray(mask, dtype=bool)
    if not values.size:
        return 0, []
    padded = np.concatenate(([False], values, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    runs = [(int(start), int(end)) for start, end in zip(starts, ends, strict=True) if end - start >= minimum]
    return len(runs), runs[:maximum_rows]


class IntegrityAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="numpy_integrity",
        version=INTEGRITY_VERSION,
        capabilities=frozenset({AnalysisCapability.INTEGRITY}),
        cost=AnalysisCost.CHEAP,
        implementation="robust waveform discontinuity / silence-run / full-scale / DC-offset evidence",
        upstream="NumPy",
        license="BSD-3-Clause",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        np = _np()
        audio = context.audio.astype(np.float64, copy=False)
        sr = context.request.sample_rate
        absolute = np.abs(audio)
        frame_peak = np.max(absolute, axis=1)
        peak = float(np.max(frame_peak))

        # Large first differences are discontinuity candidates, not automatic click labels.
        differences = np.max(np.abs(np.diff(audio, axis=0)), axis=1)
        if differences.size:
            median = float(np.median(differences))
            mad = float(np.median(np.abs(differences - median)))
            robust_sigma = 1.4826 * mad
            p999 = float(np.percentile(differences, 99.9))
            threshold = max(median + 12.0 * robust_sigma, p999, 1e-6)
            candidate_indices = np.flatnonzero(differences > threshold)
        else:
            median = mad = robust_sigma = threshold = 0.0
            candidate_indices = np.asarray([], dtype=np.int64)

        max_candidates = 32
        if candidate_indices.size > max_candidates:
            strongest_order = np.argsort(differences[candidate_indices])[-max_candidates:]
            candidate_indices = np.sort(candidate_indices[strongest_order])
        discontinuities = [
            {
                "time_seconds": context.absolute_start_seconds + (int(index) + 1) / float(sr),
                "max_channel_sample_step": float(differences[int(index)]),
            }
            for index in candidate_indices
        ]

        silence_threshold = 10.0 ** (context.request.silence_threshold_dbfs / 20.0)
        silence_mask = frame_peak < silence_threshold
        minimum_silence = max(1, round(0.02 * sr))
        silence_run_count, silence_runs = _runs(silence_mask, minimum_silence, 32, np)
        silence_payload = [
            {
                "start_seconds": context.absolute_start_seconds + start / float(sr),
                "end_seconds": context.absolute_start_seconds + end / float(sr),
                "duration_seconds": (end - start) / float(sr),
            }
            for start, end in silence_runs
        ]
        longest_silence = max((row["duration_seconds"] for row in silence_payload), default=0.0)

        near_full_mask = frame_peak >= 0.999
        minimum_full_scale = max(2, round(0.001 * sr))
        near_full_run_count, near_full_runs = _runs(near_full_mask, minimum_full_scale, 32, np)
        near_full_payload = [
            {
                "start_seconds": context.absolute_start_seconds + start / float(sr),
                "end_seconds": context.absolute_start_seconds + end / float(sr),
                "duration_seconds": (end - start) / float(sr),
            }
            for start, end in near_full_runs
        ]

        dc_offsets = [float(value) for value in np.mean(audio, axis=0)]
        max_abs_dc = max((abs(value) for value in dc_offsets), default=0.0)
        rms = math.sqrt(float(np.mean(audio * audio)))

        return {
            AnalysisCapability.INTEGRITY.value: {
                "max_sample_peak": peak,
                "rms": rms,
                "dc_offset_per_channel": dc_offsets,
                "max_abs_dc_offset": max_abs_dc,
                "near_full_scale_frame_count": int(np.count_nonzero(near_full_mask)),
                "near_full_scale_run_count": near_full_run_count,
                "near_full_scale_runs": near_full_payload,
                "silence_threshold_dbfs": context.request.silence_threshold_dbfs,
                "sustained_silence_run_count": silence_run_count,
                "sustained_silence_runs": silence_payload,
                "longest_sustained_silence_seconds": longest_silence,
                "discontinuity_candidate_count": int(len(discontinuities)),
                "discontinuity_candidates": discontinuities,
                "discontinuity_threshold_sample_step": threshold,
                "sample_step_median": median,
                "sample_step_mad": mad,
                "interpretation_note": (
                    "discontinuities, silence runs, near-full-scale runs and DC offset are waveform-integrity evidence; "
                    "musical transients, intentional silence or saturation can produce the same observations, so these are candidates rather than defect labels"
                ),
                "range": _range(context),
            }
        }


def integrity_analyzers():
    return (IntegrityAnalyzer(),)
