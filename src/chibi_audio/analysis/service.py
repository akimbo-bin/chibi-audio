from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Protocol

from .core import default_core_analyzers
from .io import AnalysisContext
from .librosa_adapter import LibrosaMirAnalyzer
from .loudness import FfmpegLoudnessAnalyzer
from .models import SCHEMA_VERSION, AnalysisReport, AnalysisRequest, AnalyzerDescriptor


class AnalysisUnavailable(ValueError):
    pass


class Analyzer(Protocol):
    @property
    def descriptor(self) -> AnalyzerDescriptor: ...

    def analyze(self, context: AnalysisContext) -> dict[str, object]: ...


class AnalyzerRegistry:
    def __init__(self, analyzers: Iterable[Analyzer] = ()) -> None:
        self._analyzers: list[Analyzer] = []
        for analyzer in analyzers:
            self.register(analyzer)

    @classmethod
    def default(cls) -> "AnalyzerRegistry":
        return cls(
            (
                *default_core_analyzers(),
                FfmpegLoudnessAnalyzer(),
                LibrosaMirAnalyzer(),
            )
        )

    def register(self, analyzer: Analyzer) -> None:
        name = analyzer.descriptor.name
        if any(existing.descriptor.name == name for existing in self._analyzers):
            raise ValueError(f"analyzer name already registered: {name}")
        self._analyzers.append(analyzer)

    def descriptors(self) -> tuple[AnalyzerDescriptor, ...]:
        return tuple(analyzer.descriptor for analyzer in self._analyzers)

    def plan(self, request: AnalysisRequest) -> tuple[Analyzer, ...]:
        remaining = set(request.capabilities)
        selected: list[Analyzer] = []
        ordered = sorted(
            enumerate(self._analyzers),
            key=lambda item: (item[1].descriptor.cost.rank, item[0]),
        )
        for _, analyzer in ordered:
            descriptor = analyzer.descriptor
            if not descriptor.available or descriptor.cost.rank > request.max_cost.rank:
                continue
            covered = remaining.intersection(descriptor.capabilities)
            if not covered:
                continue
            selected.append(analyzer)
            remaining.difference_update(covered)
            if not remaining:
                break
        if remaining:
            detail = {}
            for capability in sorted(remaining, key=lambda value: value.value):
                candidates = [
                    analyzer.descriptor
                    for analyzer in self._analyzers
                    if capability in analyzer.descriptor.capabilities
                ]
                detail[capability.value] = [candidate.to_dict() for candidate in candidates]
            raise AnalysisUnavailable(
                "requested analysis capabilities cannot be satisfied under the current "
                f"runtime/cost budget: {json.dumps(detail, sort_keys=True)}"
            )
        return tuple(selected)


class AudioAnalysisService:
    """Explicit on-demand analysis. It never scans or schedules audio by itself."""

    def __init__(self, registry: AnalyzerRegistry | None = None) -> None:
        self.registry = registry or AnalyzerRegistry.default()

    def capability_report(self) -> list[dict[str, object]]:
        return [descriptor.to_dict() for descriptor in self.registry.descriptors()]

    def analyze(
        self,
        path: str | Path,
        request: AnalysisRequest | None = None,
        *,
        cache_dir: str | Path | None = None,
        content_sha256: str | None = None,
    ) -> AnalysisReport:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        request = request or AnalysisRequest()
        analyzers = self.registry.plan(request)
        descriptors = [analyzer.descriptor for analyzer in analyzers]
        stat = source.stat()

        digest = self._normalize_hash(content_sha256)
        analysis_key = None
        cache_path = None
        if cache_dir is not None:
            digest = digest or self._sha256(source)
            analysis_key = self._analysis_key(digest, request, descriptors)
            cache_path = Path(cache_dir) / f"{analysis_key}.json"
            cached = self._read_cache(cache_path)
            if cached is not None and cached.analysis_key == analysis_key and cached.content_sha256 == digest:
                cached.source_name = source.name
                cached.source_size_bytes = stat.st_size
                cached.cache_hit = True
                return cached
        elif digest is not None:
            analysis_key = self._analysis_key(digest, request, descriptors)

        context = AnalysisContext(source, request)
        measurements: dict[str, object] = {}
        for analyzer in analyzers:
            produced = analyzer.analyze(context)
            duplicates = measurements.keys() & produced.keys()
            if duplicates:
                raise RuntimeError(
                    f"analyzer {analyzer.descriptor.name} produced duplicate capabilities: {sorted(duplicates)}"
                )
            measurements.update(produced)

        report = AnalysisReport(
            source_name=source.name,
            source_size_bytes=stat.st_size,
            requested_capabilities=sorted(value.value for value in request.capabilities),
            executed_analyzers=[descriptor.to_dict() for descriptor in descriptors],
            measurements=measurements,
            content_sha256=digest,
            analysis_key=analysis_key,
            cache_hit=False,
        )
        if cache_path is not None:
            self._write_cache(cache_path, report)
        return report

    @staticmethod
    def _normalize_hash(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256 digest")
        return normalized

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _analysis_key(
        digest: str,
        request: AnalysisRequest,
        descriptors: list[AnalyzerDescriptor],
    ) -> str:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "content_sha256": digest,
            "request": request.cache_payload(),
            "analyzers": [descriptor.to_dict() for descriptor in descriptors],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read_cache(path: Path) -> AnalysisReport | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if value.get("schema_version") != SCHEMA_VERSION:
                return None
            return AnalysisReport.from_dict(value)
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, AttributeError):
            return None

    @staticmethod
    def _write_cache(path: Path, report: AnalysisReport) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = None
        temp_name = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(report.to_dict(), handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)
