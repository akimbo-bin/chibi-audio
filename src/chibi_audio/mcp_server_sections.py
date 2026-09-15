from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .facade import ChibiAudioFacade
from .locator_client import LocatorBridgeClient
from .mcp_server import (
    AudioMcpSettings,
    ObjectName,
    _safe_tool_error,
    build_mcp_server as build_base_mcp_server,
    build_parser,
)
from .sections import build_section_map, position_context, resolve_section as resolve_named_section

SectionOccurrence = Annotated[int, Field(ge=1, le=100, strict=True)]
LocatorLimit = Annotated[int, Field(ge=1, le=4096, strict=True)]


def build_mcp_server(
    settings: AudioMcpSettings,
    *,
    facade: ChibiAudioFacade | None = None,
    locator_client: LocatorBridgeClient | None = None,
):
    server = build_base_mcp_server(settings, facade=facade)
    locator = locator_client or LocatorBridgeClient(host="127.0.0.1", port=settings.live_port)
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
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
