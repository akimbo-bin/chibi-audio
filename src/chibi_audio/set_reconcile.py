"""Conservative saved/live Ableton Set reconciliation.

This module compares a read-only .als report with one fresh Live set_summary.
It never mutates Live. Matches are intentionally sparse: exact names bind only
when structural placement/type does not contradict them; duplicate names require
an exact, non-empty device fingerprint that uniquely identifies both sides.

Temporary ChibiTap devices are excluded from device fingerprints so capture
topology does not break durable Set identity.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


TEMPORARY_DEVICE_NAMES = {"chibitap"}


def _clean_name(value: Any) -> str:
    return str(value or "").strip()


def _device_token_saved(device: dict[str, Any]) -> str | None:
    plugin = _clean_name(device.get("plugin"))
    dtype = _clean_name(device.get("type"))
    identity = plugin or dtype
    if not identity:
        return None
    if identity.casefold() in TEMPORARY_DEVICE_NAMES:
        return None
    prefix = "plugin" if plugin else "native"
    return f"{prefix}:{identity.casefold()}"


def _device_token_live(device: dict[str, Any]) -> str | None:
    name = _clean_name(device.get("name"))
    class_name = _clean_name(device.get("class_name"))
    class_kind = _clean_name(device.get("class"))
    if any(value.casefold() in TEMPORARY_DEVICE_NAMES for value in (name, class_name, class_kind) if value):
        return None
    is_plugin = class_kind == "PluginDevice" or class_name == "PluginDevice"
    identity = name if is_plugin and name else class_name or class_kind or name
    if not identity:
        return None
    prefix = "plugin" if is_plugin else "native"
    return f"{prefix}:{identity.casefold()}"


def _fingerprint_saved(track: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        token
        for device in track.get("devices") or []
        if (token := _device_token_saved(device)) is not None
    )


def _fingerprint_live(track: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        token
        for device in track.get("devices") or []
        if (token := _device_token_live(device)) is not None
    )


def _saved_kind(track: dict[str, Any]) -> str:
    value = _clean_name(track.get("type"))
    if value == "GroupTrack":
        return "group"
    if value == "ReturnTrack":
        return "return"
    if value in {"AudioTrack", "MidiTrack"}:
        return "regular"
    return "unknown"


def _live_kind(track: dict[str, Any], *, collection: str) -> str:
    if collection == "return_tracks":
        return "return"
    if bool(track.get("is_foldable")):
        return "group"
    return "regular"


def _compatible(saved: dict[str, Any], live: dict[str, Any]) -> bool:
    saved_kind = saved["_reconcile_kind"]
    live_kind = live["_reconcile_kind"]
    if saved_kind == "unknown":
        return True
    return saved_kind == live_kind


def _unwrap_live_summary(live_summary: dict[str, Any]) -> dict[str, Any]:
    if "result" in live_summary and isinstance(live_summary["result"], dict):
        return live_summary["result"]
    return live_summary


def _prepare_saved(saved_report: dict[str, Any]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, raw in enumerate(saved_report.get("tracks") or []):
        track = dict(raw)
        track["_reconcile_index"] = index
        track["_reconcile_kind"] = _saved_kind(track)
        track["_reconcile_fingerprint"] = _fingerprint_saved(track)
        prepared.append(track)
    return prepared


def _prepare_live(live_summary: dict[str, Any]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for collection in ("tracks", "return_tracks"):
        for fallback_index, raw in enumerate(live_summary.get(collection) or []):
            track = dict(raw)
            track["_reconcile_collection"] = collection
            track["_reconcile_index"] = track.get("index", fallback_index)
            track["_reconcile_kind"] = _live_kind(track, collection=collection)
            track["_reconcile_fingerprint"] = _fingerprint_live(track)
            prepared.append(track)
    return prepared


def _saved_ref(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "saved_index": track["_reconcile_index"],
        "saved_id": track.get("id"),
        "saved_name": _clean_name(track.get("name")),
        "saved_type": track.get("type"),
        "saved_kind": track["_reconcile_kind"],
        "device_fingerprint": list(track["_reconcile_fingerprint"]),
    }


def _live_ref(track: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_index": track["_reconcile_index"],
        "live_id": track.get("id"),
        "live_name": _clean_name(track.get("name")),
        "live_class": track.get("class"),
        "live_kind": track["_reconcile_kind"],
        "live_collection": track["_reconcile_collection"],
        "device_fingerprint": list(track["_reconcile_fingerprint"]),
    }


def reconcile_saved_live(
    saved_report: dict[str, Any],
    live_summary: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile a saved .als inspection report against one fresh Live summary.

    The function is read-only and deterministic. It does not infer renamed tracks
    or guess through duplicate names. Uncertain cases remain explicit.
    """

    live_payload = _unwrap_live_summary(live_summary)
    saved = _prepare_saved(saved_report)
    live = _prepare_live(live_payload)

    saved_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    live_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for track in saved:
        saved_by_name[_clean_name(track.get("name"))].append(track)
    for track in live:
        live_by_name[_clean_name(track.get("name"))].append(track)

    matches: list[dict[str, Any]] = []
    matched_saved: set[int] = set()
    matched_live: set[int] = set()
    ambiguous: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []

    shared_names = sorted(set(saved_by_name) & set(live_by_name), key=str.casefold)
    for name in shared_names:
        if not name:
            continue
        s_group = saved_by_name[name]
        l_group = live_by_name[name]

        if len(s_group) == 1 and len(l_group) == 1:
            s_track, l_track = s_group[0], l_group[0]
            if _compatible(s_track, l_track):
                matches.append(
                    {
                        **_saved_ref(s_track),
                        **_live_ref(l_track),
                        "basis": "UNIQUE_NAME",
                    }
                )
                matched_saved.add(s_track["_reconcile_index"])
                matched_live.add(id(l_track))
            else:
                contradictions.append(
                    {
                        "name": name,
                        "reason": "TYPE_OR_PLACEMENT_CONTRADICTION",
                        "saved": _saved_ref(s_track),
                        "live": _live_ref(l_track),
                    }
                )
            continue

        saved_fp_counts = Counter(
            track["_reconcile_fingerprint"]
            for track in s_group
            if track["_reconcile_fingerprint"]
        )
        live_fp_counts = Counter(
            track["_reconcile_fingerprint"]
            for track in l_group
            if track["_reconcile_fingerprint"]
        )
        paired_saved: set[int] = set()
        paired_live: set[int] = set()

        for s_track in s_group:
            fp = s_track["_reconcile_fingerprint"]
            if not fp or saved_fp_counts[fp] != 1 or live_fp_counts[fp] != 1:
                continue
            compatible_candidates = [
                track
                for track in l_group
                if track["_reconcile_fingerprint"] == fp and _compatible(s_track, track)
            ]
            if len(compatible_candidates) != 1:
                continue
            l_track = compatible_candidates[0]
            matches.append(
                {
                    **_saved_ref(s_track),
                    **_live_ref(l_track),
                    "basis": "DEVICE_FINGERPRINT",
                }
            )
            matched_saved.add(s_track["_reconcile_index"])
            matched_live.add(id(l_track))
            paired_saved.add(s_track["_reconcile_index"])
            paired_live.add(id(l_track))

        unresolved_saved = [
            _saved_ref(track)
            for track in s_group
            if track["_reconcile_index"] not in paired_saved
        ]
        unresolved_live = [
            _live_ref(track)
            for track in l_group
            if id(track) not in paired_live
        ]
        if unresolved_saved or unresolved_live:
            ambiguous.append(
                {
                    "name": name,
                    "reason": "DUPLICATE_NAME_NOT_UNIQUELY_DISAMBIGUATED",
                    "saved_candidates": unresolved_saved,
                    "live_candidates": unresolved_live,
                }
            )

    saved_only = [
        _saved_ref(track)
        for track in saved
        if track["_reconcile_index"] not in matched_saved
        and (
            not _clean_name(track.get("name"))
            or _clean_name(track.get("name")) not in live_by_name
        )
    ]
    live_only = [
        _live_ref(track)
        for track in live
        if id(track) not in matched_live
        and (
            not _clean_name(track.get("name"))
            or _clean_name(track.get("name")) not in saved_by_name
        )
    ]

    status = "RECONCILED"
    if ambiguous or contradictions or saved_only or live_only:
        status = "PARTIAL"

    return {
        "effect_state": "NOT_STARTED",
        "status": status,
        "set_signature": live_payload.get("set_signature"),
        "saved_path": saved_report.get("path"),
        "saved_track_count": len(saved),
        "live_track_count": len(live),
        "matched_count": len(matches),
        "ambiguous_count": len(ambiguous),
        "contradiction_count": len(contradictions),
        "saved_only_count": len(saved_only),
        "live_only_count": len(live_only),
        "matches": sorted(matches, key=lambda item: item["saved_index"]),
        "ambiguous": ambiguous,
        "contradictions": contradictions,
        "saved_only": saved_only,
        "live_only": live_only,
    }
