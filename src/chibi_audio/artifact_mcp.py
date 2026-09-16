from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .ab_compare import LevelMatchedAbError
from .artifact_workflows import ArtifactWorkflowBridge, ArtifactWorkflowError

ArtifactPath = Annotated[str, Field(min_length=1, max_length=2000)]
ComparisonId = Annotated[str, Field(min_length=1, max_length=200)]
VariantLabel = Annotated[str, Field(min_length=1, max_length=200)]
LoudnessTolerance = Annotated[float, Field(gt=0.0, le=1.0, allow_inf_nan=False)]


def _safe_artifact_error(exc: Exception) -> ToolError:
    if isinstance(
        exc,
        (ArtifactWorkflowError, LevelMatchedAbError, ValueError, FileNotFoundError, TypeError, KeyError),
    ):
        return ToolError(str(exc))
    return ToolError("Chibi Audio could not safely complete the requested artifact workflow.")


def register_artifact_write_tools(
    server: Any,
    workflows: ArtifactWorkflowBridge,
    annotations: ToolAnnotations,
) -> tuple[str, ...]:
    """Register bounded artifact-producing tools. These never mutate Ableton Live."""

    @server.tool(
        title="Create a level-matched A/B listening pair",
        description=(
            "Create new downward-only integrated-loudness-matched float WAVs from two already-aligned audio artifacts "
            "below the configured Chibi Audio artifact root. Source files are never modified. The operation refuses "
            "unaligned inputs and existing output packages, then returns confined artifact references plus exact "
            "gain/loudness/fingerprint provenance. This is a listening aid, not a better/worse judgment."
        ),
        annotations=annotations,
        structured_output=True,
    )
    def create_level_matched_ab(
        left_artifact: ArtifactPath,
        right_artifact: ArtifactPath,
        comparison_id: ComparisonId,
        left_label: VariantLabel = "A",
        right_label: VariantLabel = "B",
        verification_tolerance_lu: LoudnessTolerance = 0.15,
    ) -> dict[str, Any]:
        try:
            return workflows.create_level_matched_ab(
                left_artifact=left_artifact,
                right_artifact=right_artifact,
                comparison_id=comparison_id,
                left_label=left_label,
                right_label=right_label,
                verification_tolerance_lu=verification_tolerance_lu,
            )
        except Exception as exc:  # noqa: BLE001 - sanitize MCP trust boundary.
            raise _safe_artifact_error(exc) from None

    return ("create_level_matched_ab",)
