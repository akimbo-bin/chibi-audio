from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from .analysis import AnalysisCapability, AnalysisCost, AnalysisRequest, AudioAnalysisService
from .audio import analyze_audio


REFERENCE_LIBRARY_SCHEMA_VERSION = "chibi-audio-reference-library/v1"
REFERENCE_COMPARISON_SCHEMA_VERSION = "chibi-audio-reference-comparison/v1"


class ReferenceLibraryError(ValueError):
    pass


DEFAULT_REFERENCE_REQUEST = AnalysisRequest(
    capabilities=frozenset(
        {
            AnalysisCapability.METADATA,
            AnalysisCapability.LEVELS,
            AnalysisCapability.STEREO,
            AnalysisCapability.SPECTRUM,
            AnalysisCapability.DYNAMICS,
            AnalysisCapability.LOUDNESS,
        }
    ),
    max_cost=AnalysisCost.MODERATE,
)


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


def _nonempty(value: str, *, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise ReferenceLibraryError(f"{field} must not be empty")
    return text


def _metric(summary: dict[str, Any], key: str) -> float | None:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _delta(candidate: dict[str, Any], reference: dict[str, Any], key: str) -> float | None:
    left = _metric(candidate, key)
    right = _metric(reference, key)
    if left is None or right is None:
        return None
    return left - right


def compare_reference_summaries(
    candidate: dict[str, Any],
    reference: dict[str, Any],
    *,
    candidate_label: str,
    reference_label: str,
) -> dict[str, Any]:
    candidate_window = candidate.get("loudest_window") if isinstance(candidate.get("loudest_window"), dict) else {}
    reference_window = reference.get("loudest_window") if isinstance(reference.get("loudest_window"), dict) else {}
    candidate_bands = candidate_window.get("bands") if isinstance(candidate_window.get("bands"), dict) else {}
    reference_bands = reference_window.get("bands") if isinstance(reference_window.get("bands"), dict) else {}
    band_delta = {}
    for name in sorted(set(candidate_bands) & set(reference_bands)):
        left = candidate_bands.get(name)
        right = reference_bands.get(name)
        if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
            band_delta[str(name)] = float(left) - float(right)

    return {
        "schema_version": REFERENCE_COMPARISON_SCHEMA_VERSION,
        "candidate_label": _nonempty(candidate_label, field="candidate_label"),
        "reference_label": _nonempty(reference_label, field="reference_label"),
        "whole_track_delta_candidate_minus_reference": {
            key: _delta(candidate, reference, key)
            for key in (
                "integrated_lufs",
                "true_peak_dbtp",
                "rms_dbfs",
                "crest_db",
                "stereo_correlation",
                "side_to_mid_db",
            )
        },
        "loudest_window": {
            "candidate": {
                "start_s": candidate_window.get("start_s"),
                "end_s": candidate_window.get("end_s"),
                "rms_dbfs": candidate_window.get("rms_dbfs"),
            },
            "reference": {
                "start_s": reference_window.get("start_s"),
                "end_s": reference_window.get("end_s"),
                "rms_dbfs": reference_window.get("rms_dbfs"),
            },
            "rms_delta_db": _delta(candidate_window, reference_window, "rms_dbfs"),
            "band_energy_percentage_point_delta": band_delta,
        },
        "interpretation_note": (
            "Deltas are descriptive evidence, not a target or quality score. Loudest windows are independently selected high-energy windows, "
            "so they are useful for coarse section-aware comparison but are not guaranteed to be musically equivalent sections."
        ),
    }


class ReferenceLibrary:
    """Local-only registry for user-supplied reference audio and derived evidence."""

    def __init__(
        self,
        root: str | Path,
        *,
        service: AudioAnalysisService | None = None,
        summary_analyzer: Callable[..., dict[str, Any]] = analyze_audio,
    ) -> None:
        self.root = Path(root).resolve()
        self.registry_path = self.root / "registry.json"
        self.cache_dir = self.root / "analysis-cache"
        self.service = service or AudioAnalysisService()
        self.summary_analyzer = summary_analyzer

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": REFERENCE_LIBRARY_SCHEMA_VERSION, "references": {}, "projects": {}}

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except json.JSONDecodeError as exc:
            raise ReferenceLibraryError(f"invalid reference registry JSON: {self.registry_path}") from exc
        if payload.get("schema_version") != REFERENCE_LIBRARY_SCHEMA_VERSION:
            raise ReferenceLibraryError(f"unsupported reference registry schema: {payload.get('schema_version')!r}")
        if not isinstance(payload.get("references"), dict) or not isinstance(payload.get("projects"), dict):
            raise ReferenceLibraryError("reference registry is structurally invalid")
        return payload

    def register(
        self,
        path: str | Path,
        *,
        display_name: str | None = None,
        project: str | None = None,
        set_name: str | None = None,
        request: AnalysisRequest = DEFAULT_REFERENCE_REQUEST,
        loudest_window_seconds: float = 12.0,
    ) -> dict[str, Any]:
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if loudest_window_seconds <= 0:
            raise ReferenceLibraryError("loudest_window_seconds must be > 0")
        if set_name is not None and project is None:
            raise ReferenceLibraryError("set_name requires project")
        name = _nonempty(display_name or source.stem, field="display_name")
        digest = _sha256(source)
        stat = source.stat()
        report = self.service.analyze(source, request, cache_dir=self.cache_dir, content_sha256=digest).to_dict()
        summary = self.summary_analyzer(source, sample_rate=request.sample_rate, window_seconds=loudest_window_seconds)

        payload = self.load()
        references = payload["references"]
        existing = references.get(digest)
        locations = [] if not isinstance(existing, dict) else list(existing.get("locations") or [])
        resolved_source = str(source)
        if resolved_source not in locations:
            locations.append(resolved_source)
        names = [] if not isinstance(existing, dict) else list(existing.get("names") or [])
        if name not in names:
            names.append(name)
        entry = {
            "content_sha256": digest,
            "names": sorted(set(str(value) for value in names)),
            "locations": sorted(set(str(value) for value in locations)),
            "source_size_bytes": stat.st_size,
            "source_modified_ns": stat.st_mtime_ns,
            "analysis_request": request.cache_payload(),
            "analysis": report,
            "summary": summary,
        }
        references[digest] = entry

        if project is not None:
            project_name = _nonempty(project, field="project")
            bucket_name = _nonempty(set_name or "default", field="set_name")
            projects = payload["projects"]
            project_row = projects.setdefault(project_name, {"sets": {}})
            sets = project_row.setdefault("sets", {})
            members = sets.setdefault(bucket_name, [])
            if digest not in members:
                members.append(digest)

        _atomic_json(self.registry_path, payload)
        return {
            "effect_state": "NOT_STARTED",
            "content_sha256": digest,
            "reused_content": isinstance(existing, dict),
            "reference": entry,
            "registry": str(self.registry_path),
            "project": project,
            "set_name": None if project is None else (set_name or "default"),
        }

    def reference_set(self, project: str, set_name: str = "default") -> list[dict[str, Any]]:
        payload = self.load()
        project_name = _nonempty(project, field="project")
        bucket_name = _nonempty(set_name, field="set_name")
        project_row = payload["projects"].get(project_name)
        if not isinstance(project_row, dict):
            raise ReferenceLibraryError(f"unknown reference project: {project_name}")
        members = (project_row.get("sets") or {}).get(bucket_name)
        if not isinstance(members, list):
            raise ReferenceLibraryError(f"unknown reference set: {project_name}/{bucket_name}")
        rows = []
        for digest in members:
            entry = payload["references"].get(digest)
            if not isinstance(entry, dict):
                raise ReferenceLibraryError(f"reference set contains missing digest: {digest}")
            rows.append(entry)
        return rows

    def verify(self, content_sha256: str) -> dict[str, Any]:
        digest = str(content_sha256).lower()
        payload = self.load()
        entry = payload["references"].get(digest)
        if not isinstance(entry, dict):
            raise ReferenceLibraryError(f"unknown reference digest: {digest}")
        checked = []
        for raw in entry.get("locations") or []:
            path = Path(str(raw))
            if not path.is_file():
                checked.append({"path": str(path), "status": "MISSING"})
                continue
            actual = _sha256(path)
            status = "VERIFIED" if actual == digest else "CONTENT_CHANGED"
            checked.append({"path": str(path), "status": status, "actual_sha256": actual})
        return {
            "effect_state": "NOT_STARTED",
            "content_sha256": digest,
            "verified": any(row["status"] == "VERIFIED" for row in checked),
            "locations": checked,
        }

    def compare_candidate(
        self,
        candidate: str | Path,
        *,
        project: str,
        set_name: str = "default",
        candidate_label: str | None = None,
        loudest_window_seconds: float = 12.0,
    ) -> dict[str, Any]:
        source = Path(candidate).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        candidate_summary = self.summary_analyzer(source, window_seconds=loudest_window_seconds)
        comparisons = []
        for reference in self.reference_set(project, set_name):
            names = reference.get("names") or [reference.get("content_sha256")]
            comparisons.append(
                compare_reference_summaries(
                    candidate_summary,
                    reference.get("summary") or {},
                    candidate_label=candidate_label or source.stem,
                    reference_label=str(names[0]),
                )
            )
        return {
            "schema_version": REFERENCE_COMPARISON_SCHEMA_VERSION,
            "effect_state": "NOT_STARTED",
            "project": project,
            "set_name": set_name,
            "candidate_path": str(source),
            "candidate_summary": candidate_summary,
            "comparison_count": len(comparisons),
            "comparisons": comparisons,
        }
