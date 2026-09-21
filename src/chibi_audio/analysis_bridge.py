from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


class AnalysisFabricUnavailable(ValueError):
    """Raised when the optional reusable analysis fabric is not present."""


class AnalysisFabricBridge:
    """Thin, confined adapter from the MCP/control lane to the optional #8 analysis fabric."""

    def __init__(self, artifact_root: str | Path, *, module: ModuleType | Any | None = None) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._module = module
        self._load_error: str | None = None
        if module is None:
            try:
                self._module = importlib.import_module("chibi_audio.analysis")
            except ImportError as exc:
                self._load_error = f"analysis fabric is unavailable in this checkout/runtime: {exc.name or 'import failed'}"

    @property
    def available(self) -> bool:
        return self._module is not None

    def capability_report(self) -> dict[str, Any]:
        if self._module is None:
            return {
                "available": False,
                "reason": self._load_error or "analysis fabric is unavailable",
                "analyzers": [],
            }
        service = self._module.AudioAnalysisService()
        return {
            "available": True,
            "schema_version": getattr(self._module, "SCHEMA_VERSION", None),
            "analyzers": service.capability_report(),
        }

    def plan_request(
        self,
        capabilities: Iterable[str],
        *,
        max_cost: str = "CHEAP",
    ) -> dict[str, Any]:
        """Validate one analysis request without opening or decoding audio."""
        module = self._require_module()
        request = self._request(module, capabilities, max_cost=max_cost)
        service = module.AudioAnalysisService()
        selected = service.registry.plan(request)
        requested = sorted(getattr(value, "value", str(value)) for value in request.capabilities)
        cost = getattr(request.max_cost, "value", str(request.max_cost))
        return {
            "available": True,
            "schema_version": getattr(module, "SCHEMA_VERSION", None),
            "requested_capabilities": requested,
            "max_cost": cost,
            "selected_analyzers": [analyzer.descriptor.to_dict() for analyzer in selected],
        }

    def analyze_audio(
        self,
        artifact: str,
        capabilities: Iterable[str],
        *,
        max_cost: str = "CHEAP",
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> dict[str, Any]:
        module = self._require_module()
        source = self._resolve_artifact(artifact)
        request = self._request(
            module,
            capabilities,
            max_cost=max_cost,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        report = module.AudioAnalysisService().analyze(source, request)
        result = report.to_dict()
        result["artifact"] = source.relative_to(self.artifact_root).as_posix()
        return result

    def analyze_capture_manifest(
        self,
        manifest: str,
        capabilities: Iterable[str],
        *,
        tap_ids: Iterable[int] | None = None,
        max_cost: str = "CHEAP",
    ) -> dict[str, Any]:
        module = self._require_module()
        source = self._resolve_artifact(manifest)
        self._validate_manifest_artifacts(source)
        request = self._request(module, capabilities, max_cost=max_cost)
        result = module.analyze_capture_manifest(
            source,
            request,
            tap_ids=None if tap_ids is None else tuple(int(value) for value in tap_ids),
        )
        result["capture_manifest"] = source.relative_to(self.artifact_root).as_posix()
        for tap in result.get("taps", []):
            if isinstance(tap, dict) and isinstance(tap.get("artifact_path"), str):
                tap_path = Path(tap["artifact_path"]).resolve()
                tap["artifact_path"] = tap_path.relative_to(self.artifact_root).as_posix()
        return result

    def attribute_capture_master_stress(
        self,
        manifest: str,
        *,
        premaster_label: str,
        master_label: str,
        source_labels: Iterable[str],
        window_ms: float = 100.0,
        hop_ms: float = 10.0,
        max_latency_ms: float = 500.0,
        low_band_hz: float = 250.0,
        active_threshold_dbfs: float = -45.0,
        top_stress_fraction: float = 0.10,
    ) -> dict[str, Any]:
        module = self._require_module()
        source = self._resolve_artifact(manifest)
        self._validate_manifest_artifacts(source)
        result = module.attribute_capture_master_stress(
            source,
            premaster_label=premaster_label,
            master_label=master_label,
            source_labels=tuple(source_labels),
            window_ms=window_ms,
            hop_ms=hop_ms,
            max_latency_ms=max_latency_ms,
            low_band_hz=low_band_hz,
            active_threshold_dbfs=active_threshold_dbfs,
            top_stress_fraction=top_stress_fraction,
        )
        result["capture_manifest"] = source.relative_to(self.artifact_root).as_posix()
        return result

    def attribute_capture_bus_contribution(
        self,
        manifest: str,
        *,
        bus_label: str,
        source_labels: Iterable[str],
        window_ms: float = 100.0,
        hop_ms: float = 10.0,
        low_band_hz: float = 250.0,
        active_threshold_dbfs: float = -45.0,
        top_bus_fraction: float = 0.10,
    ) -> dict[str, Any]:
        module = self._require_module()
        source = self._resolve_artifact(manifest)
        self._validate_manifest_artifacts(source)
        result = module.attribute_capture_bus_contribution(
            source,
            bus_label=bus_label,
            source_labels=tuple(source_labels),
            window_ms=window_ms,
            hop_ms=hop_ms,
            low_band_hz=low_band_hz,
            active_threshold_dbfs=active_threshold_dbfs,
            top_bus_fraction=top_bus_fraction,
        )
        result["capture_manifest"] = source.relative_to(self.artifact_root).as_posix()
        return result

    def evaluate_source_intervention_probe(
        self,
        baseline_manifest: str,
        candidate_manifest: str,
        *,
        bus_label: str,
        source_target: str,
        source_parameter: str,
        declared_change_db: float,
        window_ms: float = 100.0,
        hop_ms: float = 10.0,
        low_band_hz: float = 250.0,
        active_threshold_dbfs: float = -45.0,
        top_bus_fraction: float = 0.10,
    ) -> dict[str, Any]:
        module = self._require_module()
        baseline = self._resolve_artifact(baseline_manifest)
        candidate = self._resolve_artifact(candidate_manifest)
        self._validate_manifest_artifacts(baseline)
        self._validate_manifest_artifacts(candidate)
        result = module.evaluate_source_intervention_probe(
            baseline,
            candidate,
            bus_label=bus_label,
            source_target=source_target,
            source_parameter=source_parameter,
            declared_change_db=declared_change_db,
            window_ms=window_ms,
            hop_ms=hop_ms,
            low_band_hz=low_band_hz,
            active_threshold_dbfs=active_threshold_dbfs,
            top_bus_fraction=top_bus_fraction,
        )
        baseline_capture = result.get("baseline_capture")
        if isinstance(baseline_capture, dict):
            baseline_capture["manifest"] = baseline.relative_to(
                self.artifact_root
            ).as_posix()
        candidate_capture = result.get("candidate_capture")
        if isinstance(candidate_capture, dict):
            candidate_capture["manifest"] = candidate.relative_to(
                self.artifact_root
            ).as_posix()
        return result

    def compare_reports(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        left_label: str = "left",
        right_label: str = "right",
    ) -> dict[str, Any]:
        module = self._require_module()
        left_report = module.AnalysisReport.from_dict(dict(left))
        right_report = module.AnalysisReport.from_dict(dict(right))
        return module.compare_reports(
            left_report,
            right_report,
            left_label=left_label,
            right_label=right_label,
        )

    def _require_module(self) -> Any:
        if self._module is None:
            raise AnalysisFabricUnavailable(self._load_error or "analysis fabric is unavailable")
        return self._module

    def _resolve_artifact(self, artifact: str) -> Path:
        relative = Path(artifact)
        if relative.is_absolute():
            raise ValueError("analysis artifact must be relative to the configured artifact root")
        candidate = (self.artifact_root / relative).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ValueError("analysis artifact path escapes the configured artifact root") from exc
        if not candidate.is_file():
            raise ValueError(f"analysis artifact does not exist: {artifact}")
        return candidate

    def _validate_manifest_artifacts(self, manifest_path: Path) -> None:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("capture manifest is not valid JSON") from exc
        taps = payload.get("taps")
        if not isinstance(taps, list) or not taps:
            raise ValueError("capture manifest does not contain finalized taps")
        for entry in taps:
            if not isinstance(entry, dict):
                raise ValueError("capture manifest tap entry must be an object")
            final = entry.get("final")
            if not isinstance(final, dict) or not isinstance(final.get("path"), str):
                raise ValueError("capture manifest tap has no finalized artifact path")
            raw = Path(final["path"])
            candidate = raw.resolve() if raw.is_absolute() else (manifest_path.parent / raw).resolve()
            try:
                candidate.relative_to(self.artifact_root)
            except ValueError as exc:
                raise ValueError("capture manifest references an artifact outside the configured artifact root") from exc

    @staticmethod
    def _request(
        module: Any,
        capabilities: Iterable[str],
        *,
        max_cost: str,
        start_seconds: float | None = None,
        end_seconds: float | None = None,
    ) -> Any:
        values = tuple(str(value) for value in capabilities)
        if not values:
            raise ValueError("at least one analysis capability is required")
        return module.AnalysisRequest(
            capabilities=frozenset(module.AnalysisCapability(value) for value in values),
            max_cost=module.AnalysisCost(str(max_cost).upper()),
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
