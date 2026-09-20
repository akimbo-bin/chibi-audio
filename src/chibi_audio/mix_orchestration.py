from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


MIX_WAVE_PLAN_SCHEMA_VERSION = "chibi-audio-mix-wave-plan/v1"


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
