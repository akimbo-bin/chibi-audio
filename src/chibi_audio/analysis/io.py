from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterator

from .models import AnalysisRequest


class AnalysisIOError(RuntimeError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:
        raise AnalysisIOError("audio analysis requires NumPy; install chibi-audio[analysis]") from exc
    return np


def _exe(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise AnalysisIOError(f"required executable is not available on PATH: {name}")
    return value


def probe_audio(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise AnalysisIOError(f"audio file does not exist: {source}")
    command = [
        _exe("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,sample_fmt,duration_ts,time_base,duration",
        "-of",
        "json",
        str(source),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AnalysisIOError(completed.stderr.strip() or f"ffprobe failed for {source}")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if len(streams) != 1:
        raise AnalysisIOError(f"expected exactly one audio stream in {source}")
    stream = streams[0]
    return {
        "path": str(source),
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
        "sample_fmt": str(stream.get("sample_fmt") or ""),
        "samples": None if stream.get("duration_ts") is None else int(stream["duration_ts"]),
        "time_base": str(stream.get("time_base") or ""),
        "duration_s": float(stream.get("duration") or 0.0),
    }


def _range_input_args(request: AnalysisRequest) -> list[str]:
    args: list[str] = []
    if request.start_seconds is not None:
        args.extend(["-ss", f"{request.start_seconds:.9f}"])
    return args


def _range_output_args(request: AnalysisRequest) -> list[str]:
    if request.end_seconds is None:
        return []
    start = request.start_seconds or 0.0
    return ["-t", f"{request.end_seconds - start:.9f}"]


def decode_audio_segment(
    path: str | Path,
    request: AnalysisRequest,
    *,
    sample_rate: int | None = None,
    channels: int = 2,
):
    """Decode only the requested time range as float32 PCM."""

    np = _np()
    source = Path(path)
    if not source.is_file():
        raise AnalysisIOError(f"audio file does not exist: {source}")
    if channels < 1 or channels > 8:
        raise ValueError("channels must be between 1 and 8")
    output_rate = sample_rate or request.sample_rate

    command = [
        _exe("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        *_range_input_args(request),
        "-i",
        str(source),
        *_range_output_args(request),
        "-map",
        "0:a:0",
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(channels),
        "-ar",
        str(output_rate),
        "-",
    ]
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise AnalysisIOError(completed.stderr.decode("utf-8", "replace").strip())
    data = np.frombuffer(completed.stdout, dtype="<f4")
    if data.size == 0 or data.size % channels:
        raise AnalysisIOError("decoded audio was empty or not correctly interleaved")
    return data.reshape((-1, channels))


@contextmanager
def materialize_audio_segment(
    path: str | Path,
    request: AnalysisRequest,
    *,
    sample_rate: int,
    channels: int = 1,
) -> Iterator[Path]:
    """Materialize the exact requested range as bounded PCM16 WAV for file-based analyzers."""

    source = Path(path)
    if not source.is_file():
        raise AnalysisIOError(f"audio file does not exist: {source}")
    descriptor, temp_name = tempfile.mkstemp(prefix="chibi-audio-analysis-", suffix=".wav")
    os.close(descriptor)
    target = Path(temp_name)
    command = [
        _exe("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        *_range_input_args(request),
        "-i",
        str(source),
        *_range_output_args(request),
        "-map",
        "0:a:0",
        "-c:a",
        "pcm_s16le",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-y",
        str(target),
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AnalysisIOError(completed.stderr.strip() or "ffmpeg segment materialization failed")
        if not target.is_file() or target.stat().st_size <= 44:
            raise AnalysisIOError("materialized audio segment is empty")
        yield target
    finally:
        try:
            target.unlink()
        except FileNotFoundError:
            pass


class AnalysisContext:
    """Lazily shares probe/decode work across selected analyzers."""

    def __init__(self, path: str | Path, request: AnalysisRequest) -> None:
        self.path = Path(path)
        self.request = request
        self._probe: dict[str, Any] | None = None
        self._audio = None

    @property
    def probe(self) -> dict[str, Any]:
        if self._probe is None:
            self._probe = probe_audio(self.path)
        return self._probe

    @property
    def audio(self):
        if self._audio is None:
            self._audio = decode_audio_segment(self.path, self.request)
        return self._audio

    @property
    def absolute_start_seconds(self) -> float:
        return self.request.start_seconds or 0.0

    @property
    def decoded_duration_seconds(self) -> float:
        return len(self.audio) / float(self.request.sample_rate)
