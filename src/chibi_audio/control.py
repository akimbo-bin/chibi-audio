from __future__ import annotations

from typing import Any, Iterable


class ControlPlanError(ValueError):
    """Raised when a deterministic control/audition plan cannot be built safely."""


def snapshot_track_controls(set_summary: dict[str, Any]) -> dict[str, Any]:
    tracks: list[dict[str, Any]] = []
    for position, raw in enumerate(set_summary.get("tracks") or []):
        if raw.get("truncated"):
            continue
        index = int(raw.get("index", position))
        name = str(raw.get("name") or "")
        if not name or "mute" not in raw or "solo" not in raw:
            raise ControlPlanError(f"track {index} lacks stable identity or mute/solo state")
        tracks.append(
            {
                "index": index,
                "name": name,
                "id": raw.get("id"),
                "mute": bool(raw["mute"]),
                "solo": bool(raw["solo"]),
            }
        )
    if not tracks:
        raise ControlPlanError("set summary contains no usable tracks")
    return {"set_signature": set_summary.get("set_signature"), "tracks": tracks}


def build_audition_plan(
    snapshot: dict[str, Any],
    *,
    solo_track_indices: Iterable[int] = (),
    mute_track_indices: Iterable[int] = (),
) -> dict[str, Any]:
    tracks = snapshot.get("tracks") or []
    by_index = {int(item["index"]): item for item in tracks}
    solo = {int(value) for value in solo_track_indices}
    mute = {int(value) for value in mute_track_indices}
    unknown = (solo | mute) - set(by_index)
    if unknown:
        raise ControlPlanError(f"unknown track indices in audition request: {sorted(unknown)}")

    apply: list[dict[str, Any]] = []
    restore: list[dict[str, Any]] = []
    for index in sorted(by_index):
        track = by_index[index]
        desired_solo = index in solo if solo else bool(track["solo"])
        desired_mute = True if index in mute else bool(track["mute"])
        for prop, desired in (("solo", desired_solo), ("mute", desired_mute)):
            before = bool(track[prop])
            if before == desired:
                continue
            common = {"track_index": index, "expected_track_name": track["name"]}
            if track.get("id") is not None:
                common["expected_track_id"] = track["id"]
            apply.append(
                {
                    **common,
                    "property": prop,
                    "expected_current_value": before,
                    "value": desired,
                }
            )
            restore.append(
                {
                    **common,
                    "property": prop,
                    "expected_current_value": desired,
                    "value": before,
                }
            )
    return {
        "set_signature": snapshot.get("set_signature"),
        "apply": apply,
        "restore": list(reversed(restore)),
        "requested": {
            "solo_track_indices": sorted(solo),
            "mute_track_indices": sorted(mute),
        },
    }


def parameter_snapshot(
    *,
    track_index: int | None,
    track_name: str,
    placement: str = "track",
    device_index: int,
    device_name: str,
    device_id: int | None,
    parameters: list[dict[str, Any]],
    set_signature: str | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, parameter in enumerate(parameters):
        if parameter.get("truncated"):
            continue
        items.append(
            {
                "index": index,
                "id": parameter.get("id"),
                "name": parameter.get("name", ""),
                "value": parameter.get("value"),
                "display": parameter.get("display", parameter.get("display_value")),
            }
        )
    if placement not in {"track", "master"}:
        raise ControlPlanError("placement must be track or master")
    if placement == "track" and track_index is None:
        raise ControlPlanError("track placement requires track_index")
    if placement == "master" and track_index is not None:
        raise ControlPlanError("track_index must be omitted for placement=master")
    return {
        "set_signature": set_signature,
        "track": {
            "placement": placement,
            "index": int(track_index) if track_index is not None else None,
            "name": track_name,
        },
        "device": {"index": int(device_index), "name": device_name, "id": device_id},
        "parameters": items,
    }


def diff_parameter_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    if before.get("track") != after.get("track") or before.get("device") != after.get("device"):
        raise ControlPlanError("cannot diff snapshots from different track/device identities")

    def key(item: dict[str, Any]):
        if item.get("id") is not None:
            return ("id", int(item["id"]))
        return ("index_name", int(item.get("index", -1)), str(item.get("name") or ""))

    left = {key(item): item for item in before.get("parameters") or []}
    right = {key(item): item for item in after.get("parameters") or []}
    changes: list[dict[str, Any]] = []
    for item_key in sorted(set(left) | set(right), key=str):
        a = left.get(item_key)
        b = right.get(item_key)
        if a is None or b is None:
            changes.append({"key": item_key, "before": a, "after": b})
        elif a.get("value") != b.get("value") or a.get("display") != b.get("display"):
            changes.append(
                {
                    "key": item_key,
                    "name": b.get("name") or a.get("name"),
                    "before_value": a.get("value"),
                    "after_value": b.get("value"),
                    "before_display": a.get("display"),
                    "after_display": b.get("display"),
                }
            )
    return changes
