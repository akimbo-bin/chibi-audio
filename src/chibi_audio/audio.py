from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class AudioAnalysisError(RuntimeError):
    """Raised when deterministic local audio analysis cannot be completed."""


BANDS_HZ = (
    (20, 50),
    (50, 80),
    (80, 150),
    (150, 500),
    (500, 2000),
    (2000, 6000),
    (6000, 12000),
    (12000, 20000),
)


def _np():
    try:
        import numpy as np
    except ImportError as exc:
        raise AudioAnalysisError(
            "Audio analysis requires NumPy; install chibi-audio[analysis]"
        ) from exc
    return np


def _exe(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise AudioAnalysisError(f"Required executable is not available on PATH: {name}")
    return value


def _db(value: float, floor: float = -160.0) -> float:
    if value <= 0:
        return floor
    return 20.0 * math.log10(value)


def decode_audio(path: str | Path, sample_rate: int = 48000):
    np = _np()
    source = str(Path(path))
    command = [
        _exe("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source,
        "-map",
        "0:a:0",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        "2",
        "-ar",
        str(sample_rate),
        "-",
    ]
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise AudioAnalysisError(completed.stderr.decode("utf-8", "replace").strip())
    data = np.frombuffer(completed.stdout, dtype="<f4")
    if data.size == 0 or data.size % 2:
        raise AudioAnalysisError("Decoded audio was empty or not stereo-interleaved")
    return data.reshape((-1, 2))


def measure_loudness(path: str | Path) -> dict[str, float | str]:
    command = [
        _exe("ffmpeg"),
        "-hide_banner",
        "-nostats",
        "-i",
        str(Path(path)),
        "-map",
        "0:a:0",
        "-af",
        "loudnorm=I=-23:TP=-2:LRA=7:print_format=json",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise AudioAnalysisError(completed.stderr.strip())
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, flags=re.S)
    if not blocks:
        raise AudioAnalysisError("FFmpeg loudnorm did not emit measurement JSON")
    raw = json.loads(blocks[-1])
    result: dict[str, float | str] = {}
    for key, value in raw.items():
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            result[key] = value
    return result


def loudest_window(audio, sample_rate: int, window_seconds: float = 12.0, hop_seconds: float = 0.25):
    np = _np()
    power = np.mean(np.square(audio, dtype=np.float64), axis=1)
    window = min(len(power), max(1, int(round(window_seconds * sample_rate))))
    hop = max(1, int(round(hop_seconds * sample_rate)))
    if window >= len(power):
        return 0, len(power)
    starts = np.arange(0, len(power) - window + 1, hop, dtype=np.int64)
    cumulative = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(power)))
    energies = (cumulative[starts + window] - cumulative[starts]) / window
    best = int(starts[int(np.argmax(energies))])
    return best, best + window


def _band_profile(segment, sample_rate: int) -> dict[str, float]:
    np = _np()
    if len(segment) < 2:
        return {}
    window = np.hanning(len(segment)).astype(np.float64)
    spectrum = np.fft.rfft(segment.astype(np.float64) * window[:, None], axis=0)
    power = np.mean(np.abs(spectrum) ** 2, axis=1)
    freqs = np.fft.rfftfreq(len(segment), d=1.0 / sample_rate)
    audible = (freqs >= 20.0) & (freqs < min(20000.0, sample_rate / 2.0))
    total = float(power[audible].sum())
    result: dict[str, float] = {}
    for low, high in BANDS_HZ:
        mask = (freqs >= low) & (freqs < min(float(high), sample_rate / 2.0))
        value = float(power[mask].sum())
        pct = 100.0 * value / total if total > 0 else 0.0
        result[f"{low}-{high}_pct"] = pct
    return result


def analyze_audio(path: str | Path, sample_rate: int = 48000, window_seconds: float = 12.0) -> dict[str, Any]:
    np = _np()
    source = Path(path)
    if not source.is_file():
        raise AudioAnalysisError(f"Audio file does not exist: {source}")
    audio = decode_audio(source, sample_rate=sample_rate)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    start, end = loudest_window(audio, sample_rate, window_seconds=window_seconds)
    segment = audio[start:end]
    left = audio[:, 0].astype(np.float64)
    right = audio[:, 1].astype(np.float64)
    if float(np.std(left)) > 0 and float(np.std(right)) > 0:
        correlation = float(np.corrcoef(left, right)[0, 1])
    else:
        correlation = 0.0
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    mid_rms = float(np.sqrt(np.mean(mid * mid)))
    side_rms = float(np.sqrt(np.mean(side * side)))
    loudness = measure_loudness(source)
    return {
        "path": str(source),
        "sample_rate": sample_rate,
        "duration_s": len(audio) / float(sample_rate),
        "sample_peak_dbfs": _db(peak),
        "rms_dbfs": _db(rms),
        "crest_db": _db(peak) - _db(rms),
        "integrated_lufs": loudness.get("input_i"),
        "true_peak_dbtp": loudness.get("input_tp"),
        "lra_lu": loudness.get("input_lra"),
        "stereo_correlation": correlation,
        "side_to_mid_db": _db(side_rms) - _db(mid_rms),
        "loudest_window": {
            "start_s": start / float(sample_rate),
            "end_s": end / float(sample_rate),
            "rms_dbfs": _db(float(np.sqrt(np.mean(np.square(segment, dtype=np.float64))))),
            "bands": _band_profile(segment, sample_rate),
        },
    }
