from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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


def _source_family_key(name: Any) -> str:
    """Return a conservative source identity key without the track-order prefix."""
    stripped = re.sub(r"^\s*\d+\s*-\s*", "", str(name or "").strip(), count=1)
    return _normalized(stripped)


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


def _section_key(name: str, locator_id: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", _normalized(name)).strip("_")
    if normalized and not normalized.isdigit():
        return normalized
    if normalized:
        return "locator_%s" % normalized
    return "locator_%s" % str(locator_id or "unnamed")


def _section_segments(set_report: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    locators = sorted(
        [
            item
            for item in (set_report.get("locators") or [])
            if isinstance(item, dict) and item.get("time_beat") is not None
        ],
        key=lambda item: (
            float(item["time_beat"]),
            str(item.get("name") or ""),
            str(item.get("id") or ""),
        ),
    )
    if not locators:
        return []
    preferred = {
        _normalized(value): str(value)
        for value in (schema.get("section_order") or [])
        if str(value).strip()
    }
    aliases = {
        str(key).strip(): str(value).strip()
        for key, value in (schema.get("section_aliases") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    segments: list[dict[str, Any]] = []
    first_time = float(locators[0]["time_beat"])
    if first_time > 0:
        segments.append(
            {
                "sequence": 0,
                "key": "pre_locator",
                "name": "Pre-locator",
                "start_beat": 0.0,
                "end_beat": first_time,
                "semantic": False,
                "source": "synthetic",
            }
        )
    sequence = len(segments)
    for index, locator in enumerate(locators):
        start = float(locator["time_beat"])
        end = float(locators[index + 1]["time_beat"]) if index + 1 < len(locators) else None
        raw_name = str(locator.get("name") or "").strip()
        aliased_name = aliases.get(raw_name)
        effective_name = aliased_name or raw_name
        canonical = preferred.get(_normalized(effective_name))
        display_name = canonical or effective_name or ("Locator %s" % locator.get("id"))
        segments.append(
            {
                "sequence": sequence,
                "key": canonical or _section_key(effective_name, locator.get("id")),
                "name": display_name,
                "locator_id": locator.get("id"),
                "locator_name": raw_name,
                "start_beat": start,
                "end_beat": end,
                "semantic": aliased_name is not None or canonical is not None or bool(raw_name and not raw_name.isdigit()),
                "source": "locator_alias" if aliased_name is not None else "locator",
            }
        )
        sequence += 1
    return segments


def _activity_sections(activity: dict[str, Any], sections: list[dict[str, Any]]) -> dict[str, Any]:
    active: list[dict[str, Any]] = []
    for section in sections:
        start = float(section["start_beat"])
        end = section.get("end_beat")
        for span in activity.get("spans") or []:
            span_start = float(span["start_beat"])
            span_end = float(span["end_beat"])
            if span_end <= start:
                continue
            if end is not None and span_start >= float(end):
                continue
            active.append(section)
            break
    return {
        "first_section_key": active[0]["key"] if active else None,
        "first_section_name": active[0]["name"] if active else None,
        "first_section_sequence": active[0]["sequence"] if active else None,
        "active_section_keys": [item["key"] for item in active],
        "active_section_names": [item["name"] for item in active],
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
    thresholds = schema.get("height_thresholds") or {}
    envelopes = int(track.get("automation_envelope_count") or 0)
    events = int(track.get("automation_event_count") or 0)
    tall_envelopes = int(thresholds.get("tall_automation_envelopes") or 3)
    tall_events = int(thresholds.get("tall_automation_events") or 8)
    if track.get("type") == "GroupTrack":
        return str(defaults.get("group") or "tall")
    if envelopes >= tall_envelopes or events >= tall_events:
        return "tall"
    if envelopes or events:
        return "medium"
    if root_role == "drums":
        return str(defaults.get("simple_drums") or "compact")
    if root_role == "fx":
        return str(defaults.get("simple_fx") or "compact")
    if len(track.get("devices") or []) >= 6:
        return "tall"
    return str(defaults.get("source") or "medium")


def _source_family_color_consensus(
    rows: list[dict[str, Any]],
    *,
    minimum_family_size: int = 3,
    minimum_dominance: float = 0.80,
    minimum_role_confidence: float = 0.80,
) -> dict[Any, dict[str, Any]]:
    families: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        role = str(row.get("color_role") or "")
        family = _source_family_key(row.get("name"))
        color = row.get("current_color_index")
        if (
            role
            and family
            and color is not None
            and float(row.get("role_confidence") or 0.0) >= minimum_role_confidence
        ):
            families[(role, family)].append(row)

    proposals: dict[Any, dict[str, Any]] = {}
    for (role, family), members in families.items():
        if len(members) < minimum_family_size:
            continue
        counts = Counter(int(item["current_color_index"]) for item in members)
        ranked = counts.most_common()
        if not ranked:
            continue
        winner, winner_count = ranked[0]
        if len(ranked) > 1 and ranked[1][1] == winner_count:
            continue
        dominance = winner_count / len(members)
        if dominance < minimum_dominance:
            continue
        for row in members:
            if int(row["current_color_index"]) == winner:
                continue
            proposals[row["track_id"]] = {
                "value": winner,
                "role": role,
                "source_family": family,
                "family_size": len(members),
                "support_count": winner_count,
                "dominance": dominance,
            }
    return proposals


def _presentation_color_plan(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    explicit = {
        str(role): int(value)
        for role, value in (schema.get("color_indices") or {}).items()
        if value is not None
    }
    consensus = _source_family_color_consensus(rows)
    intents: list[dict[str, Any]] = []
    concrete_edits: list[dict[str, Any]] = []

    for row in rows:
        role = row.get("color_role")
        if not role:
            continue
        current = row.get("current_color_index")
        proposed = current
        basis = "preserve_existing"
        confidence = float(row.get("role_confidence") or 0.0)
        reason = "preserve existing color; no explicit or strong same-source consensus override"

        if str(role) in explicit:
            proposed = explicit[str(role)]
            basis = "schema"
            confidence = 1.0
            reason = "schema color role %s" % role
        elif row.get("track_id") in consensus:
            evidence = consensus[row["track_id"]]
            proposed = evidence["value"]
            basis = "source_family_consensus"
            confidence = float(evidence["dominance"])
            reason = (
                "same-source color consensus for %s: %d/%d tracks use color %d"
                % (
                    evidence["source_family"],
                    evidence["support_count"],
                    evidence["family_size"],
                    evidence["value"],
                )
            )

        intent = {
            "track_id": row["track_id"],
            "track_name": row["name"],
            "role": role,
            "current_color_index": current,
            "proposed_color_index": proposed,
            "basis": basis,
            "confidence": confidence,
            "reason": reason,
        }
        intents.append(intent)
        if proposed is not None and current != proposed:
            concrete_edits.append(
                {
                    "track_id": row["track_id"],
                    "track_name": row["name"],
                    "property": "color_index",
                    "expected_current_value": current,
                    "value": proposed,
                    "reason": reason,
                    "confidence": confidence,
                    "basis": basis,
                }
            )
    return intents, concrete_edits


def build_project_context(set_report: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    tracks = list(set_report.get("tracks") or [])
    by_id = {str(item["id"]): item for item in tracks if item.get("id") is not None}
    sections = _section_segments(set_report, schema)
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
            if track.get("type") == "GroupTrack":
                semantic_role = "drums.subgroup"
                role_order = 5
                color_role = "drums.subgroup"
                confidence = 0.92
                reason = "nested group inside DRUMS"
            else:
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
        section_activity = _activity_sections(activity, sections)
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
            "section_activity": section_activity,
            "device_count": len(track.get("devices") or []),
            "automation": {
                "envelope_count": int(track.get("automation_envelope_count") or 0),
                "event_count": int(track.get("automation_event_count") or 0),
            },
            "current_color_index": track.get("color"),
            "color_role": color_role,
            "height_class": _height_class(track, root_role, semantic_role, schema),
            "order_key": [
                int(top_rule["order"]) if top_rule else 999,
                role_order,
                int(section_activity["first_section_sequence"])
                if section_activity["first_section_sequence"] is not None
                else 1_000_000,
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

    current_top_ids = [row["track_id"] for row in top_level]
    desired_top_ids = [row["track_id"] for row in desired_top]
    reorder_required = current_top_ids != desired_top_ids
    structural_blockers = []
    if reorder_required:
        structural_blockers.extend(
            [
                {
                    "code": "BOUNDED_REORDER_CAPABILITY_MISSING",
                    "reason": (
                        "Live bridge exposes no typed track reorder/group mutation primitive; "
                        "GUI fallback is disabled by policy."
                    ),
                },
                {
                    "code": "ROUTING_EQUIVALENCE_PROOF_MISSING",
                    "reason": (
                        "Top-level reorder is structural and cannot execute until input/output, "
                        "parent/group, send, sidechain, and device-state equivalence can be "
                        "captured and compared transactionally."
                    ),
                },
            ]
        )

    color_intents, concrete_edits = _presentation_color_plan(rows, schema)
    naming_intents = [
        {
            "track_id": row["track_id"],
            "current_name": row["name"],
            "proposed_name": row["name"],
            "action": "preserve",
            "confidence": row["role_confidence"],
            "reason": (
                "preserve source identity; no explicit high-confidence rename rule"
                if row["role_confidence"] >= 0.70
                else "low-confidence classification; preserve name"
            ),
        }
        for row in rows
    ]
    height_intents = [
        {
            "track_id": row["track_id"],
            "track_name": row["name"],
            "height_class": row["height_class"],
            "confidence": row["role_confidence"],
            "reason": (
                "derived from group/role/device complexity policy; presentation only"
            ),
        }
        for row in rows
    ]

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
        "sections": sections,
        "tracks": rows,
        "unresolved": unresolved,
        "presentation_plan": {
            "concrete_edits": concrete_edits,
            "naming_intents": naming_intents,
            "color_intents": color_intents,
            "height_intents": height_intents,
        },
        "structural_plan": {
            "current_top_level_order": [
                {"track_id": row["track_id"], "name": row["name"], "role": row["semantic_role"]}
                for row in top_level
            ],
            "top_level_order": [{"track_id": row["track_id"], "name": row["name"], "role": row["semantic_role"]} for row in desired_top],
            "drum_order": [{"track_id": row["track_id"], "name": row["name"], "role": row["semantic_role"], "first_active_beat": row["activity"]["first_active_beat"]} for row in desired_drums],
            "reorder_required": reorder_required,
            "routing_equivalence_required": reorder_required,
            "blockers": structural_blockers,
            "execution_state": (
                "REFUSED_ROUTING_EQUIVALENCE_NOT_PROVEN"
                if reorder_required
                else "NO_STRUCTURAL_CHANGE_NEEDED"
            ),
        },
    }


def write_project_context(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(target)
    return target
