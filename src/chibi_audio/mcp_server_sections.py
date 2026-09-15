from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .analysis_bridge import AnalysisFabricBridge
from .analysis_mcp import AnalysisCapabilityList, AnalysisCostName, register_analysis_tools
from .capture import _safe_id
from .capture_session import parse_session_tap, run_capture_session
from .facade import ChibiAudioFacade
from .locator_client import LocatorBridgeClient
from .mcp_server import (
    AudioMcpSettings,
    ObjectName,
    _safe_tool_error,
    build_mcp_server as build_base_mcp_server,
    build_parser,
)
from .section_capture import build_section_capture_plan
from .sections import build_section_map, position_context, resolve_section as resolve_named_section

SectionOccurrence = Annotated[int, Field(ge=1, le=100, strict=True)]
LocatorLimit = Annotated[int, Field(ge=1, le=4096, strict=True)]
TapSpec = Annotated[str, Field(min_length=5, max_length=1000)]
TapSpecList = Annotated[list[TapSpec], Field(max_length=32)]
ExperimentId = Annotated[str, Field(min_length=1, max_length=200)]


def build_mcp_server(
    settings: AudioMcpSettings,
    *,
    facade: ChibiAudioFacade | None = None,
    locator_client: LocatorBridgeClient | None = None,
    analysis_bridge: AnalysisFabricBridge | None = None,
):
    server = build_base_mcp_server(settings, facade=facade)
    locator = locator_client or LocatorBridgeClient(host="127.0.0.1", port=settings.live_port)
    analysis = analysis_bridge or AnalysisFabricBridge(settings.artifact_root)
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    register_analysis_tools(server, analysis, read_annotations)

    write_annotations = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )

    def fresh_sections(limit: int = 256) -> dict[str, Any]:
        return build_section_map(locator.locators(limit=limit))

    @server.tool(
        title="Read Arrangement locators",
        description="Read named Ableton Arrangement locators with exact beat positions.",
        annotations=read_annotations,
        structured_output=True,
    )
    def get_locators(limit: LocatorLimit = 256) -> dict[str, Any]:
        try:
            return locator.locators(limit=limit)
        except Exception as exc:  # noqa: BLE001 - sanitize MCP trust boundary.
            raise _safe_tool_error(exc) from None

    @server.tool(
        title="Read locator-defined song sections",
        description="Derive contiguous named section beat ranges from ordered Ableton locators.",
        annotations=read_annotations,
        structured_output=True,
    )
    def get_sections(limit: LocatorLimit = 256) -> dict[str, Any]:
        try:
            return fresh_sections(limit)
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None

    @server.tool(
        title="Resolve one named song section",
        description=(
            "Resolve a locator name to an exact start/end beat range. "
            "Duplicate names require an explicit occurrence."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def resolve_section(
        name: ObjectName,
        occurrence: SectionOccurrence | None = None,
        limit: LocatorLimit = 256,
    ) -> dict[str, Any]:
        try:
            section_map = fresh_sections(limit)
            result = dict(resolve_named_section(section_map, name, occurrence))
            result["set_signature"] = section_map.get("set_signature")
            return result
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None

    @server.tool(
        title="Read current song position and section",
        description=(
            "Read the current Arrangement beat plus active, previous and next "
            "locator-defined song sections."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def get_song_position(limit: LocatorLimit = 256) -> dict[str, Any]:
        try:
            section_map = fresh_sections(limit)
            result = position_context(section_map)
            result["set_signature"] = section_map.get("set_signature")
            result["last_event_time"] = section_map.get("last_event_time")
            return result
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None

    @server.tool(
        title="Plan capture of one named song section",
        description=(
            "Resolve an artist-authored locator section and build the exact beat-range/tap payload "
            "for the typed ChibiTap capture-session executor. This tool is planning-only and never "
            "arms capture, moves transport, starts playback, or writes the Live Set."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def plan_section_capture(
        name: ObjectName,
        occurrence: SectionOccurrence | None = None,
        tap_specs: TapSpecList = [],
        limit: LocatorLimit = 256,
    ) -> dict[str, Any]:
        try:
            return build_section_capture_plan(
                fresh_sections(limit),
                name,
                occurrence=occurrence,
                tap_specs=tap_specs,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None

    @server.tool(
        title="Plan evidence for one named song section",
        description=(
            "Resolve an artist-authored locator section, validate the requested reusable analyzers/cost ceiling, "
            "and return the exact future capture + analysis plan without causing any Live effects."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def plan_section_evidence(
        name: ObjectName,
        capabilities: AnalysisCapabilityList,
        tap_specs: TapSpecList = [],
        max_cost: AnalysisCostName = "MODERATE",
        occurrence: SectionOccurrence | None = None,
        limit: LocatorLimit = 256,
    ) -> dict[str, Any]:
        try:
            capture_plan = build_section_capture_plan(
                fresh_sections(limit),
                name,
                occurrence=occurrence,
                tap_specs=tap_specs,
            )
            analysis_plan = analysis.plan_request(capabilities, max_cost=max_cost)
            return {
                "effect_state": "NOT_STARTED",
                "set_signature": capture_plan.get("set_signature"),
                "section": capture_plan["section"],
                "capture_request": capture_plan["capture_request"],
                "analysis_plan": analysis_plan,
                "ready_to_execute": bool(capture_plan.get("ready_to_execute")),
                "execution_note": (
                    "Capture remains a separate explicitly authorized effect. After finalization, pass its manifest "
                    "to the read-only analysis fabric with this validated capability/cost plan."
                ),
            }
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None

    if settings.allow_writes:

        @server.tool(
            title="Capture one named song section",
            description=(
                "Resolve an artist-authored locator section and execute the typed ChibiTap capture session for that "
                "exact beat range. The planner Set signature is rechecked inside the capture executor before any "
                "transport or ChibiTap effect. Finalized artifacts are written below the configured artifact root."
            ),
            annotations=write_annotations,
            structured_output=True,
        )
        def capture_section(
            name: ObjectName,
            experiment_id: ExperimentId,
            tap_specs: TapSpecList,
            occurrence: SectionOccurrence | None = None,
            include_analysis: bool = True,
            limit: LocatorLimit = 256,
        ) -> dict[str, Any]:
            try:
                if not tap_specs:
                    raise ValueError("capture_section requires at least one tap spec")
                section_map = fresh_sections(limit)
                plan = build_section_capture_plan(
                    section_map,
                    name,
                    occurrence=occurrence,
                    tap_specs=tap_specs,
                )
                set_signature = str(plan.get("set_signature") or "")
                if not set_signature:
                    raise ValueError("locator read did not return a Set signature")
                safe_experiment = _safe_id(experiment_id)
                output_dir = settings.artifact_root / "section-captures" / safe_experiment
                manifest_path = run_capture_session(
                    experiment_id=safe_experiment,
                    taps=[parse_session_tap(value) for value in tap_specs],
                    output_dir=output_dir,
                    start_beat=float(plan["capture_request"]["start_beat"]),
                    end_beat=float(plan["capture_request"]["end_beat"]),
                    host="127.0.0.1",
                    port=settings.live_port,
                    include_analysis=include_analysis,
                    expected_set_signature=set_signature,
                )
                manifest = manifest_path.resolve()
                root = settings.artifact_root.resolve()
                relative_manifest = manifest.relative_to(root)
                return {
                    "effect_state": "STARTED_CONFIRMED",
                    "set_signature": set_signature,
                    "section": plan["section"],
                    "capture_request": plan["capture_request"],
                    "manifest_artifact": relative_manifest.as_posix(),
                }
            except Exception as exc:  # noqa: BLE001
                raise _safe_tool_error(exc) from None

    return server


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not 1 <= args.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    try:
        settings = AudioMcpSettings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    server = build_mcp_server(settings)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=args.port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
