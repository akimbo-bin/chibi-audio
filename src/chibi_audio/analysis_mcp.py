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
        "compare_analysis_reports",
    )
