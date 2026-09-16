from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ab_compare import create_level_matched_ab
from .capture import _safe_id


class ArtifactWorkflowError(ValueError):
    pass


class ArtifactWorkflowBridge:
    """Confined artifact-producing workflows for the ChatGPT/MCP boundary."""

    def __init__(self, artifact_root: str | Path) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()

    def _resolve_existing(self, artifact: str) -> Path:
        relative = Path(artifact)
        if relative.is_absolute():
            raise ArtifactWorkflowError("artifact path must be relative to the configured artifact root")
        candidate = (self.artifact_root / relative).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ArtifactWorkflowError("artifact path escapes the configured artifact root") from exc
        if not candidate.is_file():
            raise ArtifactWorkflowError(f"artifact does not exist: {artifact}")
        return candidate

    def _relative(self, path: str | Path) -> str:
        candidate = Path(path).resolve()
        try:
            return candidate.relative_to(self.artifact_root).as_posix()
        except ValueError as exc:
            raise ArtifactWorkflowError("workflow produced an artifact outside the configured artifact root") from exc

    def create_level_matched_ab(
        self,
        *,
        left_artifact: str,
        right_artifact: str,
        comparison_id: str,
        left_label: str = "A",
        right_label: str = "B",
        verification_tolerance_lu: float = 0.15,
    ) -> dict[str, Any]:
        left = self._resolve_existing(left_artifact)
        right = self._resolve_existing(right_artifact)
        safe_comparison = _safe_id(comparison_id)
        output_dir = self.artifact_root / "ab-comparisons" / safe_comparison
        manifest_path = create_level_matched_ab(
            left=left,
            right=right,
            output_dir=output_dir,
            comparison_id=safe_comparison,
            left_label=left_label,
            right_label=right_label,
            verification_tolerance_lu=verification_tolerance_lu,
        ).resolve()
        self._relative(manifest_path)

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactWorkflowError("level-matched A/B manifest could not be read after creation") from exc
        variants = payload.get("variants")
        if not isinstance(variants, list) or len(variants) != 2:
            raise ArtifactWorkflowError("level-matched A/B manifest did not contain exactly two variants")

        source_by_label = {
            str(variants[0].get("label")): left_artifact,
            str(variants[1].get("label")): right_artifact,
        }
        response_variants: list[dict[str, Any]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                raise ArtifactWorkflowError("level-matched A/B manifest variant was invalid")
            label = str(variant.get("label") or "")
            level_matched = variant.get("level_matched")
            if not isinstance(level_matched, dict):
                raise ArtifactWorkflowError("level-matched A/B manifest was missing output provenance")
            raw_output = level_matched.get("path")
            if not isinstance(raw_output, str) or not raw_output:
                raise ArtifactWorkflowError("level-matched A/B manifest was missing an output path")
            output = (manifest_path.parent / raw_output).resolve()
            output_relative = self._relative(output)
            response_variants.append(
                {
                    "label": label,
                    "source_artifact": source_by_label.get(label),
                    "gain_db": variant.get("gain_db"),
                    "source_loudness": (variant.get("source") or {}).get("loudness"),
                    "level_matched_artifact": output_relative,
                    "level_matched_sha256": level_matched.get("sha256"),
                    "level_matched_probe": level_matched.get("probe"),
                    "level_matched_loudness": level_matched.get("loudness"),
                }
            )

        return {
            "effect_state": "STARTED_CONFIRMED",
            "effect_type": "artifact_creation",
            "comparison_id": payload.get("comparison_id"),
            "mode": payload.get("mode"),
            "no_upward_gain": payload.get("no_upward_gain"),
            "target_lufs": payload.get("target_lufs"),
            "alignment": payload.get("alignment"),
            "verification": payload.get("verification"),
            "manifest_artifact": self._relative(manifest_path),
            "variants": response_variants,
            "interpretation_note": payload.get("interpretation_note"),
        }
