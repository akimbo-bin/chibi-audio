from __future__ import annotations
from pathlib import Path
from typing import Annotated, Any
from mcp.types import ToolAnnotations
from pydantic import Field
from .audibility import analyze_bass_harmonic_survivability, erb_band_profile_array
from .audio import decode_audio
from .facade import ChibiAudioFacade
from .locator_client import LocatorBridgeClient
from .mcp_server import AudioMcpSettings, ArtifactPath, _safe_tool_error, build_parser
from .mcp_server_sections import build_mcp_server as build_section_mcp_server
from .translation import translation_profile_catalog, translation_report
TranslationProfileName = Annotated[str, Field(min_length=1, max_length=64)]
TranslationProfileList = Annotated[list[TranslationProfileName], Field(min_length=1, max_length=8)]
def _resolve_artifact(root: Path, artifact: str) -> Path:
    relative = Path(artifact)
    if relative.is_absolute():
        raise ValueError("artifact must be relative to the configured artifact root")
    base = root.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("artifact path escapes the configured artifact root") from exc
    if not candidate.is_file():
        raise ValueError("artifact does not exist below the configured artifact root")
    return candidate
def build_mcp_server(
    settings: AudioMcpSettings,
    *,
    facade: ChibiAudioFacade | None = None,
    locator_client: LocatorBridgeClient | None = None,
):
    server = build_section_mcp_server(
        settings,
        facade=facade,
        locator_client=locator_client,
    )
    read_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    @server.tool(
        title="List playback translation profiles",
        description="List bounded diagnostic playback profiles and their explicit approximation provenance.",
        annotations=read_annotations,
        structured_output=True,
    )
    def get_translation_profiles() -> dict[str, Any]:
        try:
            return {
                "profiles": translation_profile_catalog(),
                "interpretation": "Diagnostic profiles are approximations, not exact hardware emulations.",
            }
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None
    @server.tool(
        title="Analyze playback translation",
        description=(
            "Compare one configured artifact through bounded phone/laptop/mono/low-level playback profiles. "
            "Results are diagnostic evidence, not exact commercial-device emulation."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def analyze_translation_artifact(
        artifact: ArtifactPath,
        profiles: TranslationProfileList | None = None,
    ) -> dict[str, Any]:
        try:
            return translation_report(
                _resolve_artifact(settings.artifact_root, artifact),
                profiles=profiles,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None
    @server.tool(
        title="Analyze ERB perceptual bands",
        description=(
            "Summarize one configured artifact in ERB-spaced frequency bands. This is perceptually motivated spectral "
            "evidence, not a standardized specific-loudness measurement."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def analyze_perceptual_bands_artifact(
        artifact: ArtifactPath,
        band_count: Annotated[int, Field(ge=6, le=96, strict=True)] = 24,
    ) -> dict[str, Any]:
        try:
            path = _resolve_artifact(settings.artifact_root, artifact)
            return erb_band_profile_array(
                decode_audio(path, sample_rate=48000),
                48000,
                band_count=band_count,
            )
        except Exception as exc:  # noqa: BLE001
            raise _safe_tool_error(exc) from None
    @server.tool(
        title="Analyze bass harmonic survivability",
        description=(
            "Estimate how a tonal bass source's fundamental and harmonics survive one playback profile and, when an "
            "aligned masker artifact is supplied, their relative spectral masking margins. No absolute audibility threshold is claimed."
        ),
        annotations=read_annotations,
        structured_output=True,
    )
    def analyze_bass_survivability(
        source_artifact: ArtifactPath,
        fundamental_hz: Annotated[float, Field(ge=20.0, le=500.0, allow_inf_nan=False)],
        masker_artifact: ArtifactPath | None = None,
        profile: TranslationProfileName = "phone_like",
        harmonics: Annotated[int, Field(ge=1, le=24, strict=True)] = 8,
    ) -> dict[str, Any]:
        try:
            source = _resolve_artifact(settings.artifact_root, source_artifact)
            masker = (
                _resolve_artifact(settings.artifact_root, masker_artifact)
                if masker_artifact is not None
                else None
            )
            return analyze_bass_harmonic_survivability(
                source,
                fundamental_hz=fundamental_hz,
                masker_path=masker,
                profile=profile,
                harmonics=harmonics,
            )
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
