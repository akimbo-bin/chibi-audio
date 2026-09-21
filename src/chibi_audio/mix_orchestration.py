from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

from .analysis.contribution import BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION
from .analysis.stress import MASTER_STRESS_ATTRIBUTION_SCHEMA_VERSION


MIX_WAVE_PLAN_SCHEMA_VERSION = "chibi-audio-mix-wave-plan/v1"
MASTER_STRESS_WAVE_DERIVATION_SCHEMA_VERSION = (
    "chibi-audio-master-stress-wave-derivation/v1"
)
BUS_CONTRIBUTION_WAVE_DERIVATION_SCHEMA_VERSION = (
    "chibi-audio-bus-contribution-wave-derivation/v1"
)

_MASTER_STRESS_LEADER_METRICS = (
    ("rms_correlation_to_stress", "full_band_stress_correlation"),
    ("top_stress_rms_uplift_db", "full_band_top_stress_uplift"),
    ("low_band_correlation_to_stress", "low_band_stress_correlation"),
    ("top_stress_low_band_uplift_db", "low_band_top_stress_uplift"),
    ("top_stress_active_fraction_delta", "top_stress_activity_delta"),
)

_BUS_CONTRIBUTION_LEADER_METRICS = (
    ("rms_correlation_to_bus", "full_band_bus_correlation"),
    ("low_band_correlation_to_bus", "low_band_bus_correlation"),
    ("top_bus_rms_uplift_db", "top_bus_full_band_uplift"),
    ("top_bus_low_band_uplift_db", "top_bus_low_band_uplift"),
    ("top_bus_active_fraction_delta", "top_bus_activity_delta"),
)


class MixWavePlanError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MixHypothesis:
    hypothesis_id: str
    scope: str
    target_names: tuple[str, ...]
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    priority: int = 100

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip():
            raise MixWavePlanError("hypothesis_id must not be empty")
        if self.scope not in {"bus", "source", "cross_bus", "master"}:
            raise MixWavePlanError("scope must be bus, source, cross_bus, or master")
        if not self.target_names:
            raise MixWavePlanError("hypothesis requires at least one target name")
        if not self.rationale.strip():
            raise MixWavePlanError("hypothesis rationale must not be empty")


def _track_identity(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(track["id"]),
        "index": int(track["index"]),
        "name": str(track["name"]),
        "is_foldable": bool(track.get("is_foldable", False)),
    }


def _tracks_by_name(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for track in snapshot.get("tracks") or []:
        name = str(track.get("name") or "")
        if name:
            result.setdefault(name.casefold(), []).append(track)
    return result


def _children_by_parent(snapshot: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for track in snapshot.get("tracks") or []:
        group = track.get("group_track")
        if isinstance(group, dict) and group.get("id") is not None:
            result.setdefault(int(group["id"]), []).append(track)
    for children in result.values():
        children.sort(key=lambda item: int(item.get("index", 0)))
    return result


def _resolve_unique_track(
    by_name: dict[str, list[dict[str, Any]]], name: str
) -> dict[str, Any] | None:
    matches = by_name.get(name.casefold(), [])
    if len(matches) == 1:
        return matches[0]
    return None


def _active_in_range(track: dict[str, Any], start_beat: float, end_beat: float) -> bool:
    clips = track.get("arrangement_clips")
    if not isinstance(clips, list):
        return True
    for clip in clips:
        if not isinstance(clip, dict) or bool(clip.get("disabled", False)):
            continue
        try:
            start = float(clip["start_beat"])
            end = float(clip["end_beat"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < end_beat and end > start_beat:
            return True
    return False


def _diagnostic_range(
    section: dict[str, Any],
    *,
    tempo_bpm: float,
    event_beats: Iterable[float],
    diagnostic_seconds: float,
) -> dict[str, Any]:
    start = float(section["start_beat"])
    end = float(section["end_beat"])
    events = [float(value) for value in event_beats if start <= float(value) <= end]
    if not events:
        return {
            "start_beat": start,
            "end_beat": end,
            "fast_path": False,
            "window_reason": "section_fallback_no_event_beats",
        }
    if tempo_bpm <= 0 or diagnostic_seconds <= 0:
        raise MixWavePlanError("tempo_bpm and diagnostic_seconds must be > 0")
    width_beats = diagnostic_seconds * tempo_bpm / 60.0
    center = events[0]
    half = width_beats / 2.0
    window_start = max(start, center - half)
    window_end = min(end, window_start + width_beats)
    if window_end - window_start < width_beats and window_end == end:
        window_start = max(start, end - width_beats)
    return {
        "start_beat": window_start,
        "end_beat": window_end,
        "fast_path": True,
        "window_reason": "stress_event",
        "anchor_beat": center,
    }


def _major_bus_targets(
    snapshot: dict[str, Any],
    *,
    preferred_names: tuple[str, ...],
    max_bus_taps: int,
) -> list[dict[str, Any]]:
    by_name = _tracks_by_name(snapshot)
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for name in preferred_names:
        track = _resolve_unique_track(by_name, name)
        if track is None:
            continue
        track_id = int(track["id"])
        if track_id not in seen:
            selected.append(_track_identity(track))
            seen.add(track_id)
    for track in snapshot.get("tracks") or []:
        if len(selected) >= max_bus_taps:
            break
        if not bool(track.get("is_foldable", False)):
            continue
        if isinstance(track.get("group_track"), dict):
            continue
        track_id = int(track["id"])
        if track_id not in seen:
            selected.append(_track_identity(track))
            seen.add(track_id)
    return selected[:max_bus_taps]


def _worker_assignment(
    hypothesis: MixHypothesis,
    *,
    by_name: dict[str, list[dict[str, Any]]],
    children: dict[int, list[dict[str, Any]]],
    active_range: tuple[float, float],
) -> tuple[dict[str, Any], list[str]]:
    targets: list[dict[str, Any]] = []
    blockers: list[str] = []
    child_targets: list[dict[str, Any]] = []
    for name in hypothesis.target_names:
        track = _resolve_unique_track(by_name, name)
        if track is None:
            blockers.append(f"target_not_unique_or_missing:{name}")
            continue
        identity = _track_identity(track)
        targets.append(identity)
        if hypothesis.scope == "bus":
            child_targets.extend(
                _track_identity(item)
                for item in children.get(int(track["id"]), [])
                if _active_in_range(item, *active_range)
            )
    return (
        {
            "worker_id": f"worker-{hypothesis.hypothesis_id}",
            "role": f"{hypothesis.scope}_investigator",
            "hypothesis_id": hypothesis.hypothesis_id,
            "priority": int(hypothesis.priority),
            "rationale": hypothesis.rationale,
            "evidence_refs": list(hypothesis.evidence_refs),
            "targets": targets,
            "child_targets": child_targets,
            "live_mutation_authorized": False,
            "deliverable": "ranked causal findings and bounded experiment proposals",
        },
        blockers,
    )


def build_mix_wave_plan(
    project_snapshot: dict[str, Any],
    *,
    section: dict[str, Any],
    hypotheses: Iterable[MixHypothesis],
    event_beats: Iterable[float] = (),
    diagnostic_seconds: float = 4.0,
    max_parallel_workers: int = 4,
    max_bus_taps: int = 12,
    preferred_bus_names: tuple[str, ...] = ("DRUMS", "BASS", "VOX", "FX"),
) -> dict[str, Any]:
    """Build a Core-ready hierarchical mix wave without causing any Live effect."""
    signature = str(project_snapshot.get("set_signature") or "")
    if not signature:
        raise MixWavePlanError("project snapshot requires set_signature")
    tempo = float(project_snapshot.get("tempo") or 0.0)
    if max_parallel_workers < 1 or max_bus_taps < 1:
        raise MixWavePlanError("worker and tap limits must be positive")
    hypothesis_list = sorted(
        list(hypotheses), key=lambda item: (int(item.priority), item.hypothesis_id)
    )
    diagnostic_range = _diagnostic_range(
        section,
        tempo_bpm=tempo,
        event_beats=event_beats,
        diagnostic_seconds=diagnostic_seconds,
    )
    active_range = (float(diagnostic_range["start_beat"]), float(diagnostic_range["end_beat"]))
    by_name = _tracks_by_name(project_snapshot)
    children = _children_by_parent(project_snapshot)
    blockers: list[str] = []
    workers: list[dict[str, Any]] = []
    for hypothesis in hypothesis_list[:max_parallel_workers]:
        worker, worker_blockers = _worker_assignment(
            hypothesis,
            by_name=by_name,
            children=children,
            active_range=active_range,
        )
        workers.append(worker)
        blockers.extend(worker_blockers)

    major_buses = _major_bus_targets(
        project_snapshot,
        preferred_names=preferred_bus_names,
        max_bus_taps=max_bus_taps,
    )
    master = project_snapshot.get("master_track") or {}
    if not master.get("id"):
        blockers.append("missing_master_track_identity")
    bus_targets = []
    if master.get("id"):
        bus_targets.append(
            {"placement": "master", "id": int(master["id"]), "name": str(master.get("name") or "Main")}
        )
    bus_targets.extend({"placement": "track", **item} for item in major_buses)

    suspect_stages = []
    for worker in workers:
        if worker["role"] != "bus_investigator" or not worker["child_targets"]:
            continue
        suspect_stages.append(
            {
                "stage": "suspect_bus_census",
                "worker_id": worker["worker_id"],
                "targets": worker["targets"] + worker["child_targets"],
            }
        )
    return {
        "schema_version": MIX_WAVE_PLAN_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "set_signature": signature,
        "section": dict(section),
        "diagnostic_range": diagnostic_range,
        "orchestrator": {
            "authority": "chibi_core",
            "best_state_owner": True,
            "serialized_live_executor": True,
        },
        "workers": workers,
        "parallel_worker_limit": int(max_parallel_workers),
        "capture_stages": [
            {
                "stage": "bus_census",
                "targets": bus_targets,
                "range": diagnostic_range,
            },
            *suspect_stages,
        ],
        "execution_policy": {
            "parallel_analysis_allowed": True,
            "parallel_live_mutation_allowed": False,
            "one_coherent_candidate_per_wave": True,
            "full_section_acceptance_after_fast_win": True,
        },
        "blockers": sorted(set(blockers)),
        "ready_for_parallel_analysis": bool(workers) and not blockers,
    }



def _load_master_stress_capture_manifest(
    attribution: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if attribution.get("schema_version") != MASTER_STRESS_ATTRIBUTION_SCHEMA_VERSION:
        raise MixWavePlanError(
            "master stress attribution schema_version is unsupported"
        )
    reference = attribution.get("capture_manifest")
    if not isinstance(reference, str) or not reference.strip():
        raise MixWavePlanError("master stress attribution has no capture_manifest")
    path = Path(reference).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MixWavePlanError(f"could not read capture manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise MixWavePlanError("master stress capture manifest must use schema_version=1")
    return path, manifest


def _capture_source_target_map(manifest: dict[str, Any]) -> dict[str, str]:
    live_session = manifest.get("live_session")
    if not isinstance(live_session, dict):
        raise MixWavePlanError("capture manifest has no live_session provenance")
    mixer_state = live_session.get("mixer_state")
    rows = None
    if isinstance(mixer_state, dict):
        rows = mixer_state.get("tap_targets")
    if not isinstance(rows, list):
        rows = live_session.get("tap_mapping")
    if not isinstance(rows, list):
        raise MixWavePlanError("capture manifest has no tap target mapping")

    result: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        source_label = str(item.get("source_label") or "").strip()
        track_name = str(item.get("track_name") or "").strip()
        if not source_label or not track_name:
            continue
        previous = result.get(source_label)
        if previous is not None and previous != track_name:
            raise MixWavePlanError(
                f"capture source label maps to multiple tracks: {source_label}"
            )
        result[source_label] = track_name
    return result


def _master_stress_metric_groups(
    attribution: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    leaders = attribution.get("leaders")
    sources = attribution.get("sources")
    if not isinstance(leaders, dict) or not isinstance(sources, list):
        raise MixWavePlanError(
            "master stress attribution requires leaders and sources"
        )
    source_rows = {
        str(row.get("source_label") or ""): row
        for row in sources
        if isinstance(row, dict) and str(row.get("source_label") or "")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for metric, dimension in _MASTER_STRESS_LEADER_METRICS:
        leader = leaders.get(metric)
        if leader is None:
            continue
        if not isinstance(leader, dict):
            raise MixWavePlanError(f"master stress leader is invalid: {metric}")
        source_label = str(leader.get("source_label") or "").strip()
        raw_value = leader.get("value")
        if (
            not source_label
            or isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
            or float(raw_value) <= 0.0
        ):
            raise MixWavePlanError(
                f"master stress leader must have a positive finite value: {metric}"
            )
        source_row = source_rows.get(source_label)
        if source_row is None:
            raise MixWavePlanError(
                f"master stress leader source is missing from sources: {source_label}"
            )
        source_value = source_row.get(metric)
        if (
            isinstance(source_value, bool)
            or not isinstance(source_value, (int, float))
            or not math.isfinite(float(source_value))
            or not math.isclose(
                float(source_value),
                float(raw_value),
                rel_tol=1.0e-9,
                abs_tol=1.0e-12,
            )
        ):
            raise MixWavePlanError(
                f"master stress leader value disagrees with source row: {metric}"
            )
        grouped.setdefault(source_label, []).append(
            {
                "metric": metric,
                "dimension": dimension,
                "value": float(raw_value),
            }
        )
    return grouped


def _hypothesis_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "target"


def _stress_event_beats(
    attribution: dict[str, Any],
    *,
    capture_start_beat: float,
    capture_tempo_bpm: float,
    section_start_beat: float,
    section_end_beat: float,
) -> list[float]:
    block = attribution.get("stress_events")
    if not isinstance(block, dict):
        return []
    events = block.get("events")
    if not isinstance(events, list):
        return []
    result: list[float] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_time = event.get("center_time_s")
        if (
            isinstance(raw_time, bool)
            or not isinstance(raw_time, (int, float))
            or not math.isfinite(float(raw_time))
            or float(raw_time) < 0.0
        ):
            continue
        beat = capture_start_beat + float(raw_time) * capture_tempo_bpm / 60.0
        if section_start_beat <= beat <= section_end_beat:
            result.append(beat)
    return result


def build_mix_wave_from_master_stress(
    project_snapshot: dict[str, Any],
    attribution: dict[str, Any],
    *,
    section: dict[str, Any] | None = None,
    evidence_ref: str | None = None,
    diagnostic_seconds: float = 4.0,
    max_parallel_workers: int = 4,
    max_bus_taps: int = 12,
) -> dict[str, Any]:
    """Derive one Core-ready hierarchical mix wave from master-stress evidence.

    Metric-specific leaders remain separate evidence dimensions. The planner does
    not compute an overall winner, authorize mutation, or silently fuzzy-match
    capture labels to tracks.
    """

    manifest_path, manifest = _load_master_stress_capture_manifest(attribution)
    source_targets = _capture_source_target_map(manifest)
    metric_groups = _master_stress_metric_groups(attribution)
    if not metric_groups:
        raise MixWavePlanError(
            "master stress attribution has no positive leader evidence"
        )

    requested = manifest.get("requested_range")
    if not isinstance(requested, dict):
        raise MixWavePlanError("capture manifest has no requested_range")
    try:
        capture_start = float(requested["start_beat"])
        capture_end = float(requested["end_beat"])
        capture_tempo = float(requested["tempo_bpm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MixWavePlanError(
            "capture manifest requested_range is incomplete"
        ) from exc
    if capture_end <= capture_start or capture_tempo <= 0.0:
        raise MixWavePlanError("capture requested range/tempo is invalid")

    selected_section = (
        dict(section)
        if section is not None
        else {
            "name": str(
                attribution.get("experiment_id")
                or manifest.get("experiment_id")
                or "master-stress-section"
            ),
            "start_beat": capture_start,
            "end_beat": capture_end,
        }
    )
    try:
        section_start = float(selected_section["start_beat"])
        section_end = float(selected_section["end_beat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MixWavePlanError("section requires numeric start_beat/end_beat") from exc
    if section_end <= section_start:
        raise MixWavePlanError("section end_beat must be greater than start_beat")

    by_name = _tracks_by_name(project_snapshot)
    base_ref = (
        str(evidence_ref).strip()
        if evidence_ref is not None and str(evidence_ref).strip()
        else (
            "master-stress:"
            + str(
                attribution.get("experiment_id")
                or manifest.get("experiment_id")
                or manifest_path.stem
            )
        )
    )
    hypotheses: list[MixHypothesis] = []
    derivation_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    grouped_by_target: dict[str, list[dict[str, Any]]] = {}

    for source_label, metric_rows in metric_groups.items():
        target_name = source_targets.get(source_label)
        if not target_name:
            blockers.append(f"capture_source_target_missing:{source_label}")
            continue
        grouped_by_target.setdefault(target_name, []).extend(
            [
                {"source_label": source_label, **row}
                for row in metric_rows
            ]
        )

    for target_name in sorted(grouped_by_target, key=str.casefold):
        metric_rows = grouped_by_target[target_name]
        track = _resolve_unique_track(by_name, target_name)
        scope = (
            "bus"
            if track is not None and bool(track.get("is_foldable", False))
            else "source"
        )
        evidence_refs = tuple(
            f"{base_ref}#leaders/{row['metric']}"
            for row in metric_rows
        )
        evidence_text = ", ".join(
            f"{row['dimension']}={row['value']:.4g}"
            for row in metric_rows
        )
        hypotheses.append(
            MixHypothesis(
                hypothesis_id=f"master-stress-{_hypothesis_slug(target_name)}",
                scope=scope,
                target_names=(target_name,),
                rationale=(
                    f"{target_name} leads distinct master-stress evidence dimensions "
                    f"({evidence_text}); investigate this target and its active children "
                    "before authorizing any mutation."
                ),
                evidence_refs=evidence_refs,
                priority=100,
            )
        )
        derivation_rows.append(
            {
                "target_name": target_name,
                "scope": scope,
                "metrics": metric_rows,
                "evidence_refs": list(evidence_refs),
            }
        )

    if not hypotheses:
        raise MixWavePlanError(
            "master stress leaders could not be mapped to captured track targets"
        )

    snapshot_tempo = float(project_snapshot.get("tempo") or 0.0)
    tempo_matches = (
        snapshot_tempo > 0.0
        and math.isclose(
            snapshot_tempo,
            capture_tempo,
            rel_tol=0.0,
            abs_tol=1.0e-6,
        )
    )
    event_beats = (
        _stress_event_beats(
            attribution,
            capture_start_beat=capture_start,
            capture_tempo_bpm=capture_tempo,
            section_start_beat=section_start,
            section_end_beat=section_end,
        )
        if tempo_matches
        else []
    )
    if not tempo_matches:
        blockers.append(
            f"capture_tempo_mismatch:{capture_tempo:g}->{snapshot_tempo:g}"
        )

    plan = build_mix_wave_plan(
        project_snapshot,
        section=selected_section,
        hypotheses=hypotheses,
        event_beats=event_beats,
        diagnostic_seconds=diagnostic_seconds,
        max_parallel_workers=max_parallel_workers,
        max_bus_taps=max_bus_taps,
    )
    combined_blockers = sorted(set([*plan["blockers"], *blockers]))
    plan["blockers"] = combined_blockers
    plan["ready_for_parallel_analysis"] = bool(plan["workers"]) and not combined_blockers
    plan["evidence_derivation"] = {
        "schema_version": MASTER_STRESS_WAVE_DERIVATION_SCHEMA_VERSION,
        "source": "master_stress_attribution",
        "attribution_schema_version": attribution["schema_version"],
        "capture_manifest": str(manifest_path),
        "evidence_ref": base_ref,
        "capture_tempo_bpm": capture_tempo,
        "source_target_map": {
            source_label: source_targets[source_label]
            for source_label in metric_groups
            if source_label in source_targets
        },
        "hypothesis_evidence": derivation_rows,
        "stress_event_beats": event_beats,
        "no_overall_winner": True,
        "effect_state": "NOT_STARTED",
    }
    return plan



def _load_bus_contribution_capture_manifest(
    attribution: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if attribution.get("schema_version") != BUS_CONTRIBUTION_ATTRIBUTION_SCHEMA_VERSION:
        raise MixWavePlanError(
            "bus contribution attribution schema_version is unsupported"
        )
    reference = attribution.get("capture_manifest")
    if not isinstance(reference, str) or not reference.strip():
        raise MixWavePlanError(
            "bus contribution attribution has no capture_manifest"
        )
    path = Path(reference).expanduser().resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MixWavePlanError(f"could not read capture manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise MixWavePlanError(
            "bus contribution capture manifest must use schema_version=1"
        )
    return path, manifest


def _bus_contribution_metric_groups(
    attribution: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    leaders = attribution.get("leaders")
    sources = attribution.get("sources")
    if not isinstance(leaders, dict) or not isinstance(sources, list):
        raise MixWavePlanError(
            "bus contribution attribution requires leaders and sources"
        )
    source_rows = {
        str(row.get("source_label") or ""): row
        for row in sources
        if isinstance(row, dict) and str(row.get("source_label") or "")
    }
    grouped: dict[str, dict[str, Any]] = {}
    for metric, dimension in _BUS_CONTRIBUTION_LEADER_METRICS:
        leader = leaders.get(metric)
        if leader is None:
            continue
        if not isinstance(leader, dict):
            raise MixWavePlanError(
                f"bus contribution leader is invalid: {metric}"
            )
        source_label = str(leader.get("source_label") or "").strip()
        raw_value = leader.get("value")
        if (
            not source_label
            or isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
            or float(raw_value) <= 0.0
        ):
            raise MixWavePlanError(
                f"bus contribution leader must have a positive finite value: {metric}"
            )
        source_row = source_rows.get(source_label)
        if source_row is None:
            raise MixWavePlanError(
                "bus contribution leader source is missing from sources: "
                + source_label
            )
        source_value = source_row.get(metric)
        if (
            isinstance(source_value, bool)
            or not isinstance(source_value, (int, float))
            or not math.isfinite(float(source_value))
            or not math.isclose(
                float(source_value),
                float(raw_value),
                rel_tol=1.0e-9,
                abs_tol=1.0e-12,
            )
        ):
            raise MixWavePlanError(
                f"bus contribution leader value disagrees with source row: {metric}"
            )
        item = grouped.setdefault(
            source_label,
            {
                "source_row": source_row,
                "metrics": [],
            },
        )
        item["metrics"].append(
            {
                "metric": metric,
                "dimension": dimension,
                "value": float(raw_value),
            }
        )
    return grouped


def _bus_event_beats(
    attribution: dict[str, Any],
    *,
    capture_start_beat: float,
    capture_tempo_bpm: float,
    section_start_beat: float,
    section_end_beat: float,
) -> list[float]:
    block = attribution.get("bus_events")
    if not isinstance(block, dict):
        return []
    events = block.get("events")
    if not isinstance(events, list):
        return []
    result: list[float] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_time = event.get("center_time_s")
        if (
            isinstance(raw_time, bool)
            or not isinstance(raw_time, (int, float))
            or not math.isfinite(float(raw_time))
            or float(raw_time) < 0.0
        ):
            continue
        beat = (
            capture_start_beat
            + float(raw_time) * capture_tempo_bpm / 60.0
        )
        if section_start_beat <= beat <= section_end_beat:
            result.append(beat)
    return result


def _activity_context(source_row: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key in (
        "active_window_fraction",
        "active_fraction_within_top_bus",
        "top_bus_active_fraction_delta",
    ):
        raw = source_row.get(key)
        if (
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(float(raw))
        ):
            result[key] = float(raw)
        else:
            result[key] = None
    return result


def build_source_wave_from_bus_contribution(
    project_snapshot: dict[str, Any],
    attribution: dict[str, Any],
    *,
    section: dict[str, Any] | None = None,
    evidence_ref: str | None = None,
    diagnostic_seconds: float = 4.0,
    max_parallel_workers: int = 4,
) -> dict[str, Any]:
    """Derive source follow-up investigators from a completed bus census.

    The reference-bus census is already evidence at this point, so this
    downstream plan does not schedule another bus census. Metric-specific source
    evidence remains separate and no Live mutation is authorized.
    """

    manifest_path, manifest = _load_bus_contribution_capture_manifest(
        attribution
    )
    source_targets = _capture_source_target_map(manifest)
    metric_groups = _bus_contribution_metric_groups(attribution)
    if not metric_groups:
        raise MixWavePlanError(
            "bus contribution attribution has no positive leader evidence"
        )

    requested = manifest.get("requested_range")
    if not isinstance(requested, dict):
        raise MixWavePlanError("capture manifest has no requested_range")
    try:
        capture_start = float(requested["start_beat"])
        capture_end = float(requested["end_beat"])
        capture_tempo = float(requested["tempo_bpm"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MixWavePlanError(
            "capture manifest requested_range is incomplete"
        ) from exc
    if capture_end <= capture_start or capture_tempo <= 0.0:
        raise MixWavePlanError("capture requested range/tempo is invalid")

    selected_section = (
        dict(section)
        if section is not None
        else {
            "name": str(
                attribution.get("experiment_id")
                or manifest.get("experiment_id")
                or "bus-contribution-section"
            ),
            "start_beat": capture_start,
            "end_beat": capture_end,
        }
    )
    try:
        section_start = float(selected_section["start_beat"])
        section_end = float(selected_section["end_beat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MixWavePlanError(
            "section requires numeric start_beat/end_beat"
        ) from exc
    if section_end <= section_start:
        raise MixWavePlanError(
            "section end_beat must be greater than start_beat"
        )

    base_ref = (
        str(evidence_ref).strip()
        if evidence_ref is not None and str(evidence_ref).strip()
        else (
            "bus-contribution:"
            + str(
                attribution.get("experiment_id")
                or manifest.get("experiment_id")
                or manifest_path.stem
            )
        )
    )
    hypotheses: list[MixHypothesis] = []
    derivation_rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for source_label in sorted(metric_groups):
        item = metric_groups[source_label]
        target_name = source_targets.get(source_label)
        if not target_name:
            blockers.append(
                f"capture_source_target_missing:{source_label}"
            )
            continue
        metric_rows = item["metrics"]
        context = _activity_context(item["source_row"])
        evidence_refs = tuple(
            f"{base_ref}#leaders/{row['metric']}"
            for row in metric_rows
        )
        evidence_text = ", ".join(
            f"{row['dimension']}={row['value']:.4g}"
            for row in metric_rows
        )
        context_text = ", ".join(
            f"{key}={value:.4g}"
            for key, value in context.items()
            if value is not None
        )
        rationale = (
            f"{target_name} leads distinct reference-bus evidence dimensions "
            f"({evidence_text})"
        )
        if context_text:
            rationale += f"; activity context: {context_text}"
        rationale += (
            "; investigate this exact source before authorizing any mutation."
        )
        hypotheses.append(
            MixHypothesis(
                hypothesis_id=(
                    "bus-contribution-"
                    + _hypothesis_slug(target_name)
                ),
                scope="source",
                target_names=(target_name,),
                rationale=rationale,
                evidence_refs=evidence_refs,
                priority=100,
            )
        )
        derivation_rows.append(
            {
                "source_label": source_label,
                "target_name": target_name,
                "scope": "source",
                "metrics": metric_rows,
                "activity_context": context,
                "evidence_refs": list(evidence_refs),
            }
        )

    if not hypotheses:
        raise MixWavePlanError(
            "bus contribution leaders could not be mapped to captured track targets"
        )

    snapshot_tempo = float(project_snapshot.get("tempo") or 0.0)
    tempo_matches = (
        snapshot_tempo > 0.0
        and math.isclose(
            snapshot_tempo,
            capture_tempo,
            rel_tol=0.0,
            abs_tol=1.0e-6,
        )
    )
    event_beats = (
        _bus_event_beats(
            attribution,
            capture_start_beat=capture_start,
            capture_tempo_bpm=capture_tempo,
            section_start_beat=section_start,
            section_end_beat=section_end,
        )
        if tempo_matches
        else []
    )
    if not tempo_matches:
        blockers.append(
            f"capture_tempo_mismatch:{capture_tempo:g}->{snapshot_tempo:g}"
        )

    plan = build_mix_wave_plan(
        project_snapshot,
        section=selected_section,
        hypotheses=hypotheses,
        event_beats=event_beats,
        diagnostic_seconds=diagnostic_seconds,
        max_parallel_workers=max_parallel_workers,
    )
    combined_blockers = sorted(set([*plan["blockers"], *blockers]))
    plan["blockers"] = combined_blockers
    plan["ready_for_parallel_analysis"] = (
        bool(plan["workers"]) and not combined_blockers
    )

    source_targets_for_follow_up = [
        target
        for worker in plan["workers"]
        for target in worker["targets"]
    ]
    plan["capture_stages"] = [
        {
            "stage": "source_follow_up",
            "reuse_reference_bus_evidence": True,
            "worker_ids": [
                worker["worker_id"]
                for worker in plan["workers"]
            ],
            "targets": source_targets_for_follow_up,
            "range": plan["diagnostic_range"],
        }
    ]
    plan["evidence_derivation"] = {
        "schema_version": BUS_CONTRIBUTION_WAVE_DERIVATION_SCHEMA_VERSION,
        "source": "bus_contribution_attribution",
        "attribution_schema_version": attribution["schema_version"],
        "capture_manifest": str(manifest_path),
        "evidence_ref": base_ref,
        "capture_tempo_bpm": capture_tempo,
        "reference_bus": attribution.get("reference_bus"),
        "source_target_map": {
            source_label: source_targets[source_label]
            for source_label in metric_groups
            if source_label in source_targets
        },
        "hypothesis_evidence": derivation_rows,
        "bus_event_beats": event_beats,
        "reuse_reference_bus_evidence": True,
        "no_overall_winner": True,
        "effect_state": "NOT_STARTED",
    }
    return plan


def project_snapshot_from_saved_set(
    report: dict[str, Any],
    *,
    set_signature: str,
    tempo_bpm: float,
    master_track: dict[str, Any],
) -> dict[str, Any]:
    """Adapt read-only .als inspection into the planner's stable hierarchy schema."""
    if not set_signature:
        raise MixWavePlanError("set_signature is required for saved-set adaptation")
    raw_tracks = list(report.get("tracks") or [])
    names_by_id = {
        str(item.get("id")): str(item.get("name") or "")
        for item in raw_tracks
        if item.get("id") is not None
    }
    tracks: list[dict[str, Any]] = []
    for index, item in enumerate(raw_tracks):
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            track_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise MixWavePlanError(f"saved track has non-numeric id: {raw_id!r}") from exc
        track = {
            "index": index,
            "id": track_id,
            "name": str(item.get("name") or ""),
            "is_foldable": item.get("type") == "GroupTrack",
            "arrangement_clips": list(item.get("arrangement_clips") or []),
        }
        group_id = item.get("group_id")
        if group_id not in {None, "", "-1", -1}:
            group_key = str(group_id)
            try:
                parent_id = int(group_key)
            except ValueError as exc:
                raise MixWavePlanError(f"saved track has non-numeric group id: {group_id!r}") from exc
            track["is_grouped"] = True
            track["group_track"] = {
                "id": parent_id,
                "name": names_by_id.get(group_key, ""),
            }
        tracks.append(track)
    return {
        "set_signature": set_signature,
        "tempo": float(tempo_bpm),
        "master_track": dict(master_track),
        "tracks": tracks,
        "saved_set_path": report.get("path"),
        "saved_set_track_count": report.get("track_count"),
    }
