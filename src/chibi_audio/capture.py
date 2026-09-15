from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
class CaptureError(RuntimeError):
    """Raised when a capture request or artifact cannot be trusted."""
def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    text = re.sub(r"-+", "-", text).strip(".-")
    if not text:
        raise CaptureError("capture identifier must contain at least one safe character")
    return text[:96]
@dataclass(frozen=True, slots=True)
class CapturePlan:
    experiment_id: str
    source_label: str
    output_path: Path
    start_beat: float
    duration_beats: float
    sample_rate: int = 48000
    channels: int = 2
    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_id", _safe_id(self.experiment_id))
        object.__setattr__(self, "source_label", _safe_id(self.source_label))
        object.__setattr__(self, "output_path", Path(self.output_path))
        if self.start_beat < 0:
            raise CaptureError("start_beat must be >= 0")
        if self.duration_beats <= 0:
            raise CaptureError("duration_beats must be > 0")
        if self.sample_rate < 8000 or self.sample_rate > 384000:
            raise CaptureError("sample_rate is outside the supported range")
        if self.channels not in (1, 2):
            raise CaptureError("channels must be 1 or 2")
    @property
    def end_beat(self) -> float:
        return self.start_beat + self.duration_beats
    def manifest_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output_path"] = str(self.output_path)
        data["end_beat"] = self.end_beat
        return data
@dataclass(frozen=True, slots=True)
class CaptureArtifact:
    path: Path
    bytes: int
    sha256: str
    modified_ns: int
    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "bytes": self.bytes,
            "sha256": self.sha256,
            "modified_ns": self.modified_ns,
        }
def default_capture_filename(experiment_id: str, source_label: str, suffix: str = ".wav") -> str:
    if not suffix.startswith("."):
        suffix = "." + suffix
    return f"{_safe_id(experiment_id)}__{_safe_id(source_label)}{suffix.lower()}"
def write_capture_manifest(plan: CapturePlan, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan.manifest_dict(), indent=2, sort_keys=True) + "\n"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target
def wait_for_stable_capture(
    path: str | Path,
    *,
    timeout: float = 120.0,
    stable_for: float = 0.5,
    poll_interval: float = 0.1,
    minimum_bytes: int = 44,
) -> CaptureArtifact:
    target = Path(path)
    deadline = time.monotonic() + timeout
    last_size: int | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        try:
            stat = target.stat()
        except FileNotFoundError:
            time.sleep(poll_interval)
            continue
        size = stat.st_size
        if size >= minimum_bytes and size == last_size:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_for:
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                final_stat = target.stat()
                return CaptureArtifact(target, final_stat.st_size, digest, final_stat.st_mtime_ns)
        else:
            stable_since = None
        last_size = size
        time.sleep(poll_interval)
    raise CaptureError(f"capture did not become stable before timeout: {target}")
