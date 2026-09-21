from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .analysis_bridge import AnalysisFabricBridge, AnalysisFabricUnavailable

AnalysisCapabilityName = Annotated[str, Field(min_length=1, max_length=100)]
AnalysisCapabilityList = Annotated[list[AnalysisCapabilityName], Field(min_length=1, max_length=16)]
AnalysisCostName = Annotated[str, Field(pattern="^(CHEAP|MODERATE|EXPENSIVE)$")]
AnalysisTapId = Annotated[int, Field(ge=1, le=9999, strict=True)]
AnalysisTapIdList = Annotated[list[AnalysisTapId], Field(max_length=32)]
AnalysisSeconds = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
AnalysisLabel = Annotated[str, Field(min_length=1, max_length=200)]
AnalysisSourceLabelList = Annotated[list[AnalysisLabel], Field(min_length=1, max_length=16)]
AnalysisPositiveMs = Annotated[float, Field(gt=0.0, le=5000.0, allow_inf_nan=False)]
AnalysisLowBandHz = Annotated[float, Field(ge=20.0, le=20000.0, allow_inf_nan=False)]
AnalysisDbfsThreshold = Annotated[float, Field(ge=-160.0, le=0.0, allow_inf_nan=False)]
AnalysisFraction = Annotated[float, Field(ge=0.01, le=0.5, allow_inf_nan=False)]
AnalysisChangeDb = Annotated[float, Field(ge=-24.0, le=24.0, allow_inf_nan=False)]
AnalysisArtifact = Annotated[str, Field(min_length=1, max_length=2000)]
AnalysisReportPayload = dict[str, Any]


def _safe_analysis_error(exc: Exception) -> ToolError:
    if isinstance(exc, (AnalysisFabricUnavailable, ValueError, FileNotFoundError, TypeError, KeyError)):
        return ToolError(str(exc))
    return ToolError("Chibi Audio analysis fabric could not safely complete the requested operation.")


def register_analysis_tools(
    server: Any,
    analysis: AnalysisFabricBridge,
    read_annotations: ToolAnnotations,
) -> tuple[str, ...]:
    """Register the narrow #8 analysis-fabric seam on an existing MCP server."""

    @server.tool(
        title="List available audio analyzers",
        description=(
            "List reusable analysis capabilities, cost classes, provenance and runtime availability. "
            "This does not decode audio or contact Ableton."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def list_audio_analyzers() -> dict[str, Any]:
        try:
            return analysis.capability_report()
        except Exception as exc:  # noqa: BLE001 - sanitize MCP trust boundary.
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Analyze one confined audio artifact",
        description=(
            "Request only the named reusable analysis capabilities for one file below the configured artifact root. "
            "The explicit cost ceiling fails closed when a capability is unavailable or over budget."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def analyze_audio(
        artifact: AnalysisArtifact,
        capabilities: AnalysisCapabilityList,
        max_cost: AnalysisCostName = "CHEAP",
        start_seconds: AnalysisSeconds | None = None,
        end_seconds: AnalysisSeconds | None = None,
    ) -> dict[str, Any]:
        try:
            return analysis.analyze_audio(
                artifact,
                capabilities,
                max_cost=max_cost,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Analyze finalized ChibiTap capture artifacts",
        description=(
            "Analyze selected finalized taps from a capture manifest below the configured artifact root. "
            "Every finalized artifact path is checked for root confinement before analysis."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def analyze_capture_manifest(
        manifest: AnalysisArtifact,
        capabilities: AnalysisCapabilityList,
        tap_ids: AnalysisTapIdList | None = None,
        max_cost: AnalysisCostName = "CHEAP",
    ) -> dict[str, Any]:
        try:
            return analysis.analyze_capture_manifest(
                manifest,
                capabilities,
                tap_ids=tap_ids,
                max_cost=max_cost,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Attribute master-chain stress to captured sources",
        description=(
            "Use one finalized aligned capture manifest containing premaster, master and source/group taps "
            "to estimate master-chain latency, relative RMS gain suppression, and which captured sources "
            "co-vary with high-stress windows. This is read-only attribution evidence, not proof of causality "
            "and never authorizes an Ableton mutation."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def attribute_master_stress(
        manifest: AnalysisArtifact,
        premaster_label: AnalysisLabel,
        master_label: AnalysisLabel,
        source_labels: AnalysisSourceLabelList,
        window_ms: AnalysisPositiveMs = 100.0,
        hop_ms: AnalysisPositiveMs = 10.0,
        max_latency_ms: AnalysisPositiveMs = 500.0,
        low_band_hz: AnalysisLowBandHz = 250.0,
        active_threshold_dbfs: AnalysisDbfsThreshold = -45.0,
        top_stress_fraction: AnalysisFraction = 0.10,
    ) -> dict[str, Any]:
        try:
            return analysis.attribute_capture_master_stress(
                manifest,
                premaster_label=premaster_label,
                master_label=master_label,
                source_labels=source_labels,
                window_ms=window_ms,
                hop_ms=hop_ms,
                max_latency_ms=max_latency_ms,
                low_band_hz=low_band_hz,
                active_threshold_dbfs=active_threshold_dbfs,
                top_stress_fraction=top_stress_fraction,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Attribute captured source contribution to one bus",
        description=(
            "Use one finalized same-capture reference-bus tap plus explicit source/child taps to report "
            "full-band and low-band correlation, top-bus uplift, activity deltas, and localized bus events. "
            "This is read-only association evidence, not proof of causality or subjective quality, and never "
            "authorizes an Ableton mutation."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def attribute_bus_contribution(
        manifest: AnalysisArtifact,
        bus_label: AnalysisLabel,
        source_labels: AnalysisSourceLabelList,
        window_ms: AnalysisPositiveMs = 100.0,
        hop_ms: AnalysisPositiveMs = 10.0,
        low_band_hz: AnalysisLowBandHz = 250.0,
        active_threshold_dbfs: AnalysisDbfsThreshold = -45.0,
        top_bus_fraction: AnalysisFraction = 0.10,
    ) -> dict[str, Any]:
        try:
            return analysis.attribute_capture_bus_contribution(
                manifest,
                bus_label=bus_label,
                source_labels=source_labels,
                window_ms=window_ms,
                hop_ms=hop_ms,
                low_band_hz=low_band_hz,
                active_threshold_dbfs=active_threshold_dbfs,
                top_bus_fraction=top_bus_fraction,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Evaluate one source intervention against a reference bus",
        description=(
            "Compare the same finalized bus capture range before and after one declared source intervention. "
            "Returns baseline-defined active/top-bus response, event-local deltas and response per declared dB. "
            "The capture evidence is verified and confined, while the source mutation declaration remains "
            "caller-supplied until separately bound to experiment-journal provenance. This is read-only evidence "
            "and never authorizes an Ableton mutation."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def evaluate_source_intervention_probe(
        baseline_manifest: AnalysisArtifact,
        candidate_manifest: AnalysisArtifact,
        bus_label: AnalysisLabel,
        source_target: AnalysisLabel,
        source_parameter: AnalysisLabel,
        declared_change_db: AnalysisChangeDb,
        window_ms: AnalysisPositiveMs = 100.0,
        hop_ms: AnalysisPositiveMs = 10.0,
        low_band_hz: AnalysisLowBandHz = 250.0,
        active_threshold_dbfs: AnalysisDbfsThreshold = -45.0,
        top_bus_fraction: AnalysisFraction = 0.10,
    ) -> dict[str, Any]:
        try:
            return analysis.evaluate_source_intervention_probe(
                baseline_manifest,
                candidate_manifest,
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
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    @server.tool(
        title="Compare two completed analysis reports",
        description=(
            "Compare already-computed reusable analysis reports without reopening audio. Numeric deltas are "
            "right-minus-left evidence only and never imply better/worse."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def compare_analysis_reports(
        left: AnalysisReportPayload,
        right: AnalysisReportPayload,
        left_label: AnalysisLabel = "left",
        right_label: AnalysisLabel = "right",
    ) -> dict[str, Any]:
        try:
            return analysis.compare_reports(
                left,
                right,
                left_label=left_label,
                right_label=right_label,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_analysis_error(exc) from None

    return (
        "list_audio_analyzers",
        "analyze_audio",
        "analyze_capture_manifest",
        "attribute_master_stress",
        "attribute_bus_contribution",
        "evaluate_source_intervention_probe",
        "compare_analysis_reports",
    )
