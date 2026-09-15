from __future__ import annotations

import math
from typing import Any

from .models import AnalysisCapability


ALIGNMENT_SCHEMA_VERSION = "chibi-audio-capture-event-alignment/v1"


class CaptureEventAlignmentError(ValueError):
    pass


_SUPPORTED = frozenset(
    {
        AnalysisCapability.MIR_ONSETS,
        AnalysisCapability.MIR_STRUCTURE,
        AnalysisCapability.TRANSIENTS,
        AnalysisCapability.MIR_TRANSCRIPTION,
    }
)


def _event_time(value: object, *, tap_id: int, capability: AnalysisCapability) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureEventAlignmentError(
            f"tap {tap_id} contains a non-numeric {capability.value} event time"
        )
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CaptureEventAlignmentError(
            f"tap {tap_id} contains an invalid {capability.value} event time: {value!r}"
        )
    return result


def _extract_events(
    measurement: dict[str, Any],
    capability: AnalysisCapability,
    *,
    tap_id: int,
) -> tuple[list[tuple[float, dict[str, Any]]], bool]:
    if capability is AnalysisCapability.MIR_ONSETS:
        values = measurement.get("onset_times_seconds")
        if not isinstance(values, list):
            raise CaptureEventAlignmentError(f"tap {tap_id} has no onset_times_seconds list")
        return [
            (_event_time(value, tap_id=tap_id, capability=capability), {"event_kind": "onset"})
            for value in values
        ], False

    if capability is AnalysisCapability.MIR_STRUCTURE:
        values = measurement.get("boundary_candidates_seconds")
        if not isinstance(values, list):
            raise CaptureEventAlignmentError(
                f"tap {tap_id} has no boundary_candidates_seconds list"
            )
        strengths = measurement.get("boundary_candidate_strength")
        strength_values = strengths if isinstance(strengths, list) else []
        events: list[tuple[float, dict[str, Any]]] = []
        for index, value in enumerate(values):
            payload: dict[str, Any] = {"event_kind": "structure_boundary"}
            if index < len(strength_values):
                strength = strength_values[index]
                if isinstance(strength, (int, float)) and not isinstance(strength, bool) and math.isfinite(float(strength)):
                    payload["strength"] = float(strength)
            events.append((_event_time(value, tap_id=tap_id, capability=capability), payload))
        return events, False

    if capability is AnalysisCapability.TRANSIENTS:
        value = measurement.get("strongest_event_time_seconds")
        return [
            (
                _event_time(value, tap_id=tap_id, capability=capability),
                {
                    "event_kind": "strongest_transient",
                    "transient_to_body_db": measurement.get("transient_to_body_db"),
                    "strongest_frame_rms_dbfs": measurement.get("strongest_frame_rms_dbfs"),
                },
            )
        ], False

    if capability is AnalysisCapability.MIR_TRANSCRIPTION:
        values = measurement.get("note_events")
        if not isinstance(values, list):
            raise CaptureEventAlignmentError(f"tap {tap_id} has no note_events list")
        events = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise CaptureEventAlignmentError(
                    f"tap {tap_id} transcription event {index} is not an object"
                )
            payload = {
                "event_kind": "note_start",
                "midi_note": value.get("midi_note"),
                "pitch_class": value.get("pitch_class"),
                "amplitude": value.get("amplitude"),
            }
            events.append(
                (
                    _event_time(value.get("start_seconds"), tap_id=tap_id, capability=capability),
                    payload,
                )
            )
        return events, bool(measurement.get("notes_truncated"))

    raise CaptureEventAlignmentError(f"unsupported event capability: {capability.value}")


def align_capture_events(
    capture_analysis: dict[str, Any],
    *,
    capability: AnalysisCapability | str = AnalysisCapability.MIR_ONSETS,
    tolerance_seconds: float = 0.05,
) -> dict[str, Any]:
    """Cluster already-computed event evidence across aligned capture taps.

    This performs no DSP and never reopens capture artifacts. A cluster's full
    time span is bounded by ``tolerance_seconds`` so chained nearby events cannot
    bridge into an arbitrarily wide coincidence group.
    """

    capability = AnalysisCapability(capability)
    if capability not in _SUPPORTED:
        supported = ", ".join(sorted(value.value for value in _SUPPORTED))
        raise CaptureEventAlignmentError(
            f"{capability.value} is not event-alignable; supported capabilities: {supported}"
        )
    if isinstance(tolerance_seconds, bool) or not isinstance(tolerance_seconds, (int, float)):
        raise CaptureEventAlignmentError("tolerance_seconds must be numeric")
    tolerance = float(tolerance_seconds)
    if not math.isfinite(tolerance) or tolerance < 0.0 or tolerance > 5.0:
        raise CaptureEventAlignmentError("tolerance_seconds must be finite and between 0 and 5")

    if capture_analysis.get("schema_version") != "chibi-audio-capture-analysis/v1":
        raise CaptureEventAlignmentError(
            f"unsupported capture-analysis schema: {capture_analysis.get('schema_version')!r}"
        )
    taps = capture_analysis.get("taps")
    if not isinstance(taps, list) or not taps:
        raise CaptureEventAlignmentError("capture analysis contains no taps")

    flattened: list[dict[str, Any]] = []
    per_tap: list[dict[str, Any]] = []
    truncated_tap_ids: list[int] = []
    seen: set[int] = set()

    for tap in taps:
        if not isinstance(tap, dict):
            raise CaptureEventAlignmentError("capture-analysis tap entry must be an object")
        try:
            tap_id = int(tap.get("tap_id"))
        except (TypeError, ValueError) as exc:
            raise CaptureEventAlignmentError("capture-analysis tap_id must be an integer") from exc
        if tap_id in seen:
            raise CaptureEventAlignmentError(f"duplicate tap_id in capture analysis: {tap_id}")
        seen.add(tap_id)
        source_label = str(tap.get("source_label") or "")
        analysis = tap.get("analysis")
        if not isinstance(analysis, dict):
            raise CaptureEventAlignmentError(f"tap {tap_id} has no analysis report")
        measurements = analysis.get("measurements")
        if not isinstance(measurements, dict):
            raise CaptureEventAlignmentError(f"tap {tap_id} analysis has no measurements")
        measurement = measurements.get(capability.value)
        if not isinstance(measurement, dict):
            raise CaptureEventAlignmentError(
                f"tap {tap_id} analysis does not contain requested capability {capability.value}"
            )
        events, truncated = _extract_events(measurement, capability, tap_id=tap_id)
        if truncated:
            truncated_tap_ids.append(tap_id)
        per_tap.append(
            {
                "tap_id": tap_id,
                "source_label": source_label,
                "event_count": len(events),
            }
        )
        for event_index, (time_seconds, payload) in enumerate(events):
            flattened.append(
                {
                    "time_seconds": time_seconds,
                    "tap_id": tap_id,
                    "source_label": source_label,
                    "event_index": event_index,
                    **payload,
                }
            )

    flattened.sort(key=lambda value: (value["time_seconds"], value["tap_id"], value["event_index"]))
    raw_clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    cluster_start = 0.0
    for event in flattened:
        event_time = float(event["time_seconds"])
        if not current:
            current = [event]
            cluster_start = event_time
            continue
        if event_time - cluster_start <= tolerance:
            current.append(event)
        else:
            raw_clusters.append(current)
            current = [event]
            cluster_start = event_time
    if current:
        raw_clusters.append(current)

    clusters: list[dict[str, Any]] = []
    for index, group in enumerate(raw_clusters):
        times = [float(value["time_seconds"]) for value in group]
        center = sum(times) / len(times)
        tap_ids = sorted({int(value["tap_id"]) for value in group})
        source_labels = sorted({str(value["source_label"]) for value in group if value["source_label"]})
        members = []
        for value in group:
            member = dict(value)
            member["offset_from_cluster_seconds"] = float(value["time_seconds"]) - center
            members.append(member)
        clusters.append(
            {
                "cluster_index": index,
                "time_seconds": center,
                "span_seconds": max(times) - min(times),
                "event_count": len(group),
                "tap_count": len(tap_ids),
                "tap_ids": tap_ids,
                "source_labels": source_labels,
                "cross_tap": len(tap_ids) > 1,
                "members": members,
            }
        )

    return {
        "schema_version": ALIGNMENT_SCHEMA_VERSION,
        "capture_manifest": capture_analysis.get("capture_manifest"),
        "experiment_id": capture_analysis.get("experiment_id"),
        "capability": capability.value,
        "tolerance_seconds": tolerance,
        "event_count": len(flattened),
        "cluster_count": len(clusters),
        "cross_tap_cluster_count": sum(1 for value in clusters if value["cross_tap"]),
        "per_tap": per_tap,
        "truncated_tap_ids": sorted(truncated_tap_ids),
        "clusters": clusters,
        "interpretation_note": (
            "clusters are timing coincidences in already-computed evidence; they do not prove causal source contribution"
        ),
    }
