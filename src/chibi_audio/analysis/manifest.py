from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import AnalysisRequest
from .service import AudioAnalysisService


class CaptureManifestAnalysisError(ValueError):
    pass


def _resolve_artifact_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path


def analyze_capture_manifest(
    manifest_path: str | Path,
    request: AnalysisRequest,
    *,
    tap_ids: Iterable[int] | None = None,
    cache_dir: str | Path | None = None,
    service: AudioAnalysisService | None = None,
) -> dict[str, Any]:
    """Analyze finalized aligned ChibiTap artifacts without mutating capture state."""

    source = Path(manifest_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaptureManifestAnalysisError(f"invalid capture manifest JSON: {source}") from exc
    if manifest.get("schema_version") != 1:
        raise CaptureManifestAnalysisError(
            f"unsupported capture manifest schema_version: {manifest.get('schema_version')!r}"
        )
    taps = manifest.get("taps")
    if not isinstance(taps, list) or not taps:
        raise CaptureManifestAnalysisError("capture manifest does not contain finalized taps")

    selected = None if tap_ids is None else {int(value) for value in tap_ids}
    engine = service or AudioAnalysisService()
    output_taps: list[dict[str, Any]] = []
    seen: set[int] = set()

    for entry in taps:
        if not isinstance(entry, dict):
            raise CaptureManifestAnalysisError("capture manifest tap entry must be an object")
        tap_id = int(entry.get("tap_id"))
        if tap_id in seen:
            raise CaptureManifestAnalysisError(f"duplicate tap_id in capture manifest: {tap_id}")
        seen.add(tap_id)
        if selected is not None and tap_id not in selected:
            continue
        final = entry.get("final")
        if not isinstance(final, dict):
            raise CaptureManifestAnalysisError(f"tap {tap_id} has no finalized artifact")
        raw_path = final.get("path")
        digest = final.get("sha256")
        if not isinstance(raw_path, str) or not raw_path:
            raise CaptureManifestAnalysisError(f"tap {tap_id} final artifact has no path")
        if not isinstance(digest, str) or len(digest) != 64:
            raise CaptureManifestAnalysisError(f"tap {tap_id} final artifact has no valid SHA-256")
        artifact_path = _resolve_artifact_path(source, raw_path)
        report = engine.analyze(
            artifact_path,
            request,
            cache_dir=cache_dir,
            content_sha256=digest,
        )
        output_taps.append(
            {
                "tap_id": tap_id,
                "source_label": str(entry.get("source_label") or ""),
                "artifact_path": str(artifact_path),
                "content_sha256": digest.lower(),
                "analysis": report.to_dict(),
            }
        )

    if selected is not None:
        missing = sorted(selected - seen)
        if missing:
            raise CaptureManifestAnalysisError(f"requested tap_ids are not present: {missing}")
    if not output_taps:
        raise CaptureManifestAnalysisError("no capture taps matched the requested selection")

    return {
        "schema_version": "chibi-audio-capture-analysis/v1",
        "capture_manifest": str(source),
        "experiment_id": manifest.get("experiment_id"),
        "requested_capabilities": sorted(value.value for value in request.capabilities),
        "taps": output_taps,
    }
