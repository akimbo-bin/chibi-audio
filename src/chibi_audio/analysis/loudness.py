from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from .io import AnalysisContext, _exe
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


class FfmpegLoudnessAnalyzer:
    descriptor = AnalyzerDescriptor(
        name="ffmpeg_loudnorm",
        version="1",
        capabilities=frozenset({AnalysisCapability.LOUDNESS}),
        cost=AnalysisCost.MODERATE,
        implementation="FFmpeg loudnorm measurement pass",
        upstream="FFmpeg loudnorm / EBU R128 / ITU-R BS.1770 family",
        license="LGPL/GPL build-dependent",
    )

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        request = context.request
        command = [_exe("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "info"]
        if request.start_seconds is not None:
            command.extend(["-ss", f"{request.start_seconds:.9f}"])
        command.extend(["-i", str(context.path)])
        if request.end_seconds is not None:
            start = request.start_seconds or 0.0
            command.extend(["-t", f"{request.end_seconds - start:.9f}"])
        command.extend(
            [
                "-map",
                "0:a:0",
                "-af",
                "loudnorm=I=-23:TP=-2:LRA=7:print_format=json",
                "-f",
                "null",
                "-",
            ]
        )
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "FFmpeg loudnorm measurement failed")
        blocks = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, flags=re.S)
        if not blocks:
            raise RuntimeError("FFmpeg loudnorm did not emit measurement JSON")
        raw = json.loads(blocks[-1])

        def number(key: str) -> float | None:
            value = raw.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        start_seconds = request.start_seconds or 0.0
        if request.end_seconds is not None:
            end_seconds = request.end_seconds
        else:
            end_seconds = float(context.probe.get("duration_s") or 0.0)
        return {
            AnalysisCapability.LOUDNESS.value: {
                "integrated_lufs": number("input_i"),
                "true_peak_dbtp": number("input_tp"),
                "loudness_range_lu": number("input_lra"),
                "threshold_lufs": number("input_thresh"),
                "method": "ffmpeg_loudnorm_measurement",
                "range": {
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "duration_seconds": max(0.0, end_seconds - start_seconds),
                },
                "interpretation_note": (
                    "values are measurements from the installed FFmpeg loudnorm implementation; "
                    "they are evidence, not mastering targets"
                ),
            }
        }
