from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ORGANIZATION_CONTEXT_SCHEMA_VERSION = "chibi-audio-project-context/v1"
_SCHEMA_START = "<!-- chibi-audio:organization-schema:start -->"
_SCHEMA_END = "<!-- chibi-audio:organization-schema:end -->"


class OrganizationError(ValueError):
    pass


def load_organization_schema(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    text = source.read_text(encoding="utf-8-sig")
    if _SCHEMA_START not in text or _SCHEMA_END not in text:
        raise OrganizationError("organization schema markers are missing")
    block = text.split(_SCHEMA_START, 1)[1].split(_SCHEMA_END, 1)[0]
    start = block.find("{")
    end = block.rfind("}")
    if start < 0 or end <= start:
        raise OrganizationError("organization schema JSON is missing")
    try:
        schema = json.loads(block[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OrganizationError("organization schema JSON is invalid") from exc
    if schema.get("schema_version") != 1:
        raise OrganizationError("organization schema_version must be 1")
    if not isinstance(schema.get("top_level"), list) or not schema["top_level"]:
        raise OrganizationError("organization schema requires top_level rules")
    if not isinstance(schema.get("drums"), list) or not schema["drums"]:
        raise OrganizationError("organization schema requires drums rules")
    schema["_source_path"] = str(source)
    schema["_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return schema


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", " ").split())


def _matches(name: str, tokens: list[str]) -> bool:
    normalized = _normalized(name)
    return any(_normalized(token) in normalized for token in tokens if str(token).strip())


def _activity(track: dict[str, Any]) -> dict[str, Any]:
    spans = []
    for clip in track.get("arrangement_clips") or []:
        if clip.get("disabled"):
            continue
        start = float(clip["start_beat"])
        end = float(clip["end_beat"])
        if end > start:
            spans.append({"start_beat": start, "end_beat": end})
    spans.sort(key=lambda item: (item["start_beat"], item["end_beat"]))
    return {
        "span_count": len(spans),
        "first_active_beat": spans[0]["start_beat"] if spans else None,
        "last_active_beat": max((item["end_beat"] for item in spans), default=None),
        "active_duration_beats": sum(item["end_beat"] - item["start_beat"] for item in spans),
        "spans": spans,
    }

def _root_track(track: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    current = track
    visited: set[str] = set()
    while True:
        group_id = current.get("group_id")
        if group_id in (None, "", "-1", -1):
            return current if current.get("type") == "GroupTrack" else None
        key = str(group_id)
        if key in visited:
            return None
        visited.add(key)
        parent = by_id.get(key)
        if parent is None:
            return None
        current = parent


def _top_rule(name: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    for rule in sorted(schema["top_level"], key=lambda item: int(item["order"])):
        if _matches(name, list(rule.get("labels") or [])):
            return rule
    return None


def _drum_rule(name: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    matches = []
    for rule in schema["drums"]:
        tokens = list(rule.get("tokens") or [])
        if _matches(name, tokens):
            specificity = max((len(_normalized(token)) for token in tokens if _normalized(token)), default=0)
            matches.append((specificity, -int(rule["order"]), rule))
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[2]


def _height_class(track: dict[str, Any], root_role: str | None, semantic_role: str, schema: dict[str, Any]) -> str:
    defaults = schema.get("height_defaults") or {}
    if track.get("type") == "GroupTrack":
        return str(defaults.get("group") or "tall")
    if root_role == "drums":
        return str(defaults.get("simple_drums") or "compact")
    if root_role == "fx":
        return str(defaults.get("simple_fx") or "compact")
    if len(track.get("devices") or []) >= 6:
        return "tall"
    return str(defaults.get("source") or "medium")

def build_project_context(set_report: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    tracks = list(set_report.get("tracks") or [])
    by_id = {str(item["id"]): item for item in tracks if item.get("id") is not None}
    rows = []
    unresolved = []
    for fallback_index, track in enumerate(tracks):
        index = int(track.get("index", fallback_index))
        root = _root_track(track, by_id)
        root_name = str((root or track).get("name") or "")
        top_rule = _top_rule(root_name, schema)
        root_role = str(top_rule["role"]) if top_rule else None
        semantic_role = root_role or "unclassified"
        role_order = 999
        confidence = 0.98 if top_rule else 0.35
        reason = "top-level family matched schema" if top_rule else "no top-level schema match"
        color_role = str(top_rule.get("color_role")) if top_rule else None
        if root_role == "drums" and track is not root:
            drum_rule = _drum_rule(str(track.get("name") or ""), schema)
            if drum_rule:
                semantic_role = "drums.%s" % drum_rule["role"]
                role_order = int(drum_rule["order"])
                color_role = str(drum_rule.get("color_role") or semantic_role)
                confidence = 0.90
                reason = "drum-family token matched schema"
            else:
                semantic_role = "drums.misc"
                role_order = 999
                color_role = "drums.misc"
                confidence = 0.40
                reason = "drum bus known; child role unresolved"
        activity = _activity(track)
        first = activity["first_active_beat"]
        rows.append({
            "track_id": track.get("id"),
            "index": index,
            "type": track.get("type"),
            "name": track.get("name"),
            "group_id": track.get("group_id"),
            "root_group_id": None if root is None else root.get("id"),
            "root_group_name": None if root is None else root.get("name"),
            "root_role": root_role,
            "semantic_role": semantic_role,
            "role_confidence": confidence,
            "role_reason": reason,
            "activity": activity,
            "device_count": len(track.get("devices") or []),
            "current_color_index": track.get("color"),
            "color_role": color_role,
            "height_class": _height_class(track, root_role, semantic_role, schema),
            "order_key": [
                int(top_rule["order"]) if top_rule else 999,
                role_order,
                float(first) if first is not None else 1.0e12,
                index,
            ],
        })
        if confidence < 0.70 and track.get("type") != "ReturnTrack":
            unresolved.append(
                {
                    "track_id": track.get("id"),
                    "name": track.get("name"),
                    "reason": reason,
                    "confidence": confidence,
                }
            )

    top_level = [
        row
        for row in rows
        if str(row.get("group_id")) in {"-1", "None", ""}
        and row.get("type") != "ReturnTrack"
    ]
    desired_top = sorted(top_level, key=lambda item: tuple(item["order_key"]))
    drum_rows = [row for row in rows if row.get("root_role") == "drums" and row.get("root_group_id") != row.get("track_id")]
    desired_drums = sorted(drum_rows, key=lambda item: tuple(item["order_key"]))

    color_indices = schema.get("color_indices") or {}
    concrete_edits = []
    for row in rows:
        role = row.get("color_role")
        if role in color_indices and color_indices[role] is not None:
            wanted = int(color_indices[role])
            if row.get("current_color_index") != wanted:
                concrete_edits.append(
                    {
                        "track_id": row["track_id"],
                        "track_name": row["name"],
                        "property": "color_index",
                        "expected_current_value": row.get("current_color_index"),
                        "value": wanted,
                        "reason": "schema color role %s" % role,
                    }
                )

    return {
        "schema_version": ORGANIZATION_CONTEXT_SCHEMA_VERSION,
        "effect_state": "NOT_STARTED",
        "mode": "plan",
        "source_set": {
            "path": set_report.get("path"),
            "track_count": set_report.get("track_count"),
        },
        "organization_schema": {
            "path": schema.get("_source_path"),
            "sha256": schema.get("_sha256"),
            "version": schema.get("schema_version"),
        },
        "tracks": rows,
        "unresolved": unresolved,
        "presentation_plan": {
            "concrete_edits": concrete_edits,
            "color_intents": [{"track_id": row["track_id"], "role": row.get("color_role")} for row in rows if row.get("color_role")],
            "height_intents": [{"track_id": row["track_id"], "height_class": row["height_class"]} for row in rows],
        },
        "structural_plan": {
            "top_level_order": [{"track_id": row["track_id"], "name": row["name"], "role": row["semantic_role"]} for row in desired_top],
            "drum_order": [{"track_id": row["track_id"], "name": row["name"], "role": row["semantic_role"], "first_active_beat": row["activity"]["first_active_beat"]} for row in desired_drums],
            "execution_state": "PLAN_ONLY_NO_ROUTING_SAFE_REORDER_EXECUTOR",
        },
    }


def write_project_context(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(target)
    return target
