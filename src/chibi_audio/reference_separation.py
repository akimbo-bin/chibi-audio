from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from .analysis import AnalysisRequest, AudioAnalysisService
from .reference_library import DEFAULT_REFERENCE_REQUEST


SEPARATION_MANIFEST_SCHEMA_VERSION = "chibi-audio-reference-separation/v1"
STEM_ANALYSIS_SCHEMA_VERSION = "chibi-audio-reference-stem-analysis/v1"
EXPECTED_STEMS = ("drums", "bass", "vocals", "other")


class StemSeparationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def demucs_capability() -> dict[str, Any]:
    module_available = importlib.util.find_spec("demucs") is not None
    executable = shutil.which("demucs")
    available = module_available or executable is not None
    return {
        "backend": "demucs",
        "available": available,
        "python_module_available": module_available,
        "executable": executable,
        "reason": None if available else "Demucs is not installed in the current runtime.",
    }


class DemucsSeparatorBackend:
    def __init__(self, *, model: str = "htdemucs", device: str | None = None) -> None:
        self.model = str(model).strip() or "htdemucs"
        self.device = None if device is None else str(device).strip() or None

    def capability(self) -> dict[str, Any]:
        return {**demucs_capability(), "model": self.model, "device": self.device}

    def _command(self, source: Path, destination: Path) -> list[str]:
        capability = self.capability()
        if not capability["available"]:
            raise StemSeparationError(str(capability["reason"]))
        executable = capability.get("executable")
        command = [str(executable)] if executable else [sys.executable, "-m", "demucs"]
        command.extend(["-n", self.model, "-o", str(destination)])
        if self.device:
            command.extend(["-d", self.device])
        command.append(str(source))
        return command

    @staticmethod
    def _discover_stems(destination: Path) -> dict[str, Path]:
        candidates: dict[str, list[Path]] = {name: [] for name in EXPECTED_STEMS}
        for name in EXPECTED_STEMS:
            candidates[name] = sorted(path for path in destination.rglob(f"{name}.wav") if path.is_file())
        parents = None
        for values in candidates.values():
            current = {path.parent for path in values}
            parents = current if parents is None else parents & current
        common = sorted(parents or [])
        if len(common) != 1:
            raise StemSeparationError(
                "Demucs output did not contain exactly one complete drums/bass/vocals/other stem bundle"
            )
        parent = common[0]
        return {name: parent / f"{name}.wav" for name in EXPECTED_STEMS}

    def separate(self, source: str | Path, *, output_root: str | Path) -> dict[str, Any]:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        source_sha = _sha256(source_path)
        destination = Path(output_root).resolve() / source_sha
        manifest_path = destination / "manifest.json"

        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != SEPARATION_MANIFEST_SCHEMA_VERSION:
                raise StemSeparationError("cached separation manifest uses an unsupported schema")
            if payload.get("source", {}).get("sha256") != source_sha:
                raise StemSeparationError("cached separation source identity does not match current audio")
            for stem in payload.get("stems") or []:
                path = destination / str(stem.get("path") or "")
                if not path.is_file() or _sha256(path) != stem.get("sha256"):
                    raise StemSeparationError("cached separation stem identity no longer verifies")
            return {**payload, "cache_hit": True, "manifest": str(manifest_path)}

        destination.mkdir(parents=True, exist_ok=True)
        command = self._command(source_path, destination)
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise StemSeparationError(completed.stderr.strip() or "Demucs separation failed")
        stems = self._discover_stems(destination)
        stem_rows = []
        for name in EXPECTED_STEMS:
            path = stems[name]
            stem_rows.append(
                {
                    "role": name,
                    "path": path.relative_to(destination).as_posix(),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
        payload = {
            "schema_version": SEPARATION_MANIFEST_SCHEMA_VERSION,
            "backend": {"name": "demucs", "model": self.model, "device": self.device},
            "source": {"path": str(source_path), "sha256": source_sha, "bytes": source_path.stat().st_size},
            "stems": stem_rows,
            "interpretation_note": (
                "Separated stems are model estimates and may contain bleed or artifacts. They are diagnostic evidence, not authoritative source stems."
            ),
        }
        _atomic_json(manifest_path, payload)
        return {**payload, "cache_hit": False, "manifest": str(manifest_path)}


def analyze_separated_stems(
    manifest: str | Path,
    *,
    service: AudioAnalysisService | None = None,
    request: AnalysisRequest = DEFAULT_REFERENCE_REQUEST,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SEPARATION_MANIFEST_SCHEMA_VERSION:
        raise StemSeparationError("unsupported separation manifest schema")
    engine = service or AudioAnalysisService()
    rows = []
    for stem in payload.get("stems") or []:
        role = str(stem.get("role") or "")
        relative = str(stem.get("path") or "")
        digest = str(stem.get("sha256") or "")
        path = (manifest_path.parent / relative).resolve()
        try:
            path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise StemSeparationError("stem path escapes separation root") from exc
        if role not in EXPECTED_STEMS or not path.is_file() or _sha256(path) != digest:
            raise StemSeparationError(f"stem identity does not verify: {role or relative}")
        report = engine.analyze(path, request, cache_dir=cache_dir, content_sha256=digest)
        rows.append({"role": role, "path": str(path), "sha256": digest, "analysis": report.to_dict()})
    if {row["role"] for row in rows} != set(EXPECTED_STEMS):
        raise StemSeparationError("separation manifest does not contain exactly the expected four stems")
    return {
        "schema_version": STEM_ANALYSIS_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "source": payload.get("source"),
        "backend": payload.get("backend"),
        "stems": sorted(rows, key=lambda row: EXPECTED_STEMS.index(row["role"])),
        "interpretation_note": payload.get("interpretation_note"),
    }
