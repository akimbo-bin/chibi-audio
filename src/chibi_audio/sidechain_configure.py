from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .live import LiveBridgeClient, LiveBridgeError, LivePilotWriteClient


SIDECHAIN_CONFIGURATION_SCHEMA_VERSION = "chibi-audio-sidechain-configuration/v1"


class SidechainConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _TargetState:
    target_name: str
    track_index: int
    track_id: int
    device_id: int
    device_name: str
    device_class_name: str
    parameter_index: int
    parameter_id: int
    before_value: float
    before_display: str | None


def _parameters(read: LiveBridgeClient, device_id: int) -> list[dict[str, Any]]:
    payload = read.call("device_parameters", {"ref": {"id": int(device_id)}, "limit": 256})
    if isinstance(payload, dict):
        values = payload.get("parameters") or payload.get("items")
    else:
        values = payload
    if not isinstance(values, list):
        raise SidechainConfigurationError(f"device {device_id} returned no parameter list")
    return [value for value in values if isinstance(value, dict)]


def _sidechain_on_parameter(read: LiveBridgeClient, device_id: int) -> tuple[int, dict[str, Any]]:
    matches = [
        (index, value)
        for index, value in enumerate(_parameters(read, device_id))
        if str(value.get("name") or "") == "S/C On"
    ]
    if len(matches) != 1:
        raise SidechainConfigurationError(
            f"device {device_id} must expose exactly one native 'S/C On' parameter; found {len(matches)}"
        )
    index, parameter = matches[0]
    raw_id = parameter.get("id")
    raw_value = parameter.get("value")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        raise SidechainConfigurationError(f"device {device_id} S/C On parameter has no stable object id")
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise SidechainConfigurationError(f"device {device_id} S/C On parameter has no numeric value")
    return index, parameter


def _resolved_consumers(
    graph: dict[str, Any],
    *,
    source_track_name: str,
) -> list[dict[str, Any]]:
    rows = []
    for raw in graph.get("consumers", []):
        if not isinstance(raw, dict) or raw.get("routing_state") not in {"RESOLVED", "DISABLED"}:
            continue
        source = ((raw.get("source") or {}).get("track") or {})
        if str(source.get("name") or "") != source_track_name:
            continue
        target = raw.get("target") or {}
        if target.get("placement") != "track":
            continue
        rows.append(raw)
    return rows


def _preflight_targets(
    read: LiveBridgeClient,
    graph: dict[str, Any],
    *,
    source_track_name: str,
    target_track_names: Iterable[str] | None,
) -> list[_TargetState]:
    rows = _resolved_consumers(graph, source_track_name=source_track_name)
    if target_track_names is None:
        selected_names = sorted({str((row.get("target") or {}).get("name") or "") for row in rows})
    else:
        selected_names = [str(value).strip() for value in target_track_names]
        if any(not name for name in selected_names):
            raise SidechainConfigurationError("target_track_names cannot contain empty names")
        if len(set(selected_names)) != len(selected_names):
            raise SidechainConfigurationError("target_track_names must be unique")
    if not selected_names:
        raise SidechainConfigurationError(
            f"no resolved native sidechain targets use source track {source_track_name!r}"
        )

    states: list[_TargetState] = []
    for name in selected_names:
        matches = [row for row in rows if str((row.get("target") or {}).get("name") or "") == name]
        if len(matches) != 1:
            raise SidechainConfigurationError(
                f"target {name!r} must resolve to exactly one native sidechain consumer from {source_track_name!r}; found {len(matches)}"
            )
        row = matches[0]
        target = row.get("target") or {}
        device = row.get("device") or {}
        try:
            track_index = int(target["index"])
            track_id = int(target["id"])
            device_id = int(device["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SidechainConfigurationError(f"target {name!r} has incomplete Live object identity") from exc
        device_name = str(device.get("name") or "")
        device_class = str(device.get("class_name") or "")
        if not device_name or device_class != "Compressor2":
            raise SidechainConfigurationError(
                f"target {name!r} is not backed by an exact native Compressor2 consumer"
            )
        parameter_index, parameter = _sidechain_on_parameter(read, device_id)
        states.append(
            _TargetState(
                target_name=name,
                track_index=track_index,
                track_id=track_id,
                device_id=device_id,
                device_name=device_name,
                device_class_name=device_class,
                parameter_index=parameter_index,
                parameter_id=int(parameter["id"]),
                before_value=float(parameter["value"]),
                before_display=(None if parameter.get("display") is None else str(parameter.get("display"))),
            )
        )
    return states


def _reconcile_parameter(
    read: LiveBridgeClient,
    state: _TargetState,
    *,
    before: float,
    desired: float,
) -> str:
    try:
        index, parameter = _sidechain_on_parameter(read, state.device_id)
    except Exception:
        return "UNKNOWN"
    if index != state.parameter_index or int(parameter.get("id")) != state.parameter_id:
        return "UNKNOWN"
    value = float(parameter["value"])
    if abs(value - before) <= 1.0e-6:
        return "BEFORE"
    if abs(value - desired) <= 1.0e-6:
        return "DESIRED"
    return "UNKNOWN"


def _write_state(
    write: LivePilotWriteClient,
    state: _TargetState,
    *,
    expected_value: float,
    value: float,
    set_signature: str,
) -> dict[str, Any]:
    return write.set_device_parameter_ref(
        track_index=state.track_index,
        expected_track_name=state.target_name,
        expected_track_id=state.track_id,
        expected_device_name=state.device_name,
        expected_device_class_name=state.device_class_name,
        expected_device_id=state.device_id,
        parameter_index=state.parameter_index,
        expected_parameter_name="S/C On",
        expected_parameter_id=state.parameter_id,
        expected_current_value=expected_value,
        value=value,
        expected_set_signature=set_signature,
    )


def _rollback_confirmed(
    read: LiveBridgeClient,
    write: LivePilotWriteClient,
    changed: list[_TargetState],
    *,
    desired: float,
    set_signature: str,
) -> tuple[bool, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    all_restored = True
    for state in reversed(changed):
        try:
            result = _write_state(
                write,
                state,
                expected_value=desired,
                value=state.before_value,
                set_signature=set_signature,
            )
            rows.append(
                {
                    "target_track_name": state.target_name,
                    "restored": True,
                    "read_back_verified": bool(result.get("read_back_verified")),
                    "restored_value": result.get("applied_value"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - effect certainty is reconciled below.
            reconciled = _reconcile_parameter(
                read,
                state,
                before=state.before_value,
                desired=desired,
            )
            restored = reconciled == "BEFORE"
            all_restored = all_restored and restored
            rows.append(
                {
                    "target_track_name": state.target_name,
                    "restored": restored,
                    "reconciliation": reconciled,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return all_restored, rows


def configure_sidechain_targets(
    read: LiveBridgeClient,
    write: LivePilotWriteClient,
    *,
    source_track_name: str,
    intent: str = "ensure_active",
    target_track_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Configure existing native sidechain consumers from one high-level intent.

    The caller supplies track intent only. Exact compressor/parameter identities are
    discovered fresh from the sidechain graph and every target is preflighted before
    the first mutation. No device ids or plugin routing details are caller inputs.
    """
    source = source_track_name.strip()
    if not source:
        raise SidechainConfigurationError("source_track_name must not be empty")
    desired_by_intent = {"ensure_active": 1.0, "ensure_inactive": 0.0}
    if intent not in desired_by_intent:
        raise SidechainConfigurationError("intent must be ensure_active or ensure_inactive")
    desired = desired_by_intent[intent]

    graph = read.sidechain_graph(
        track_limit=-1,
        max_devices=4096,
        max_depth=8,
        include_return_tracks=True,
        include_master_track=True,
    )
    set_signature = str(graph.get("set_signature") or "")
    if not set_signature:
        raise SidechainConfigurationError("sidechain graph did not return a Set signature")
    states = _preflight_targets(
        read,
        graph,
        source_track_name=source,
        target_track_names=target_track_names,
    )

    target_rows: list[dict[str, Any]] = []
    changed: list[_TargetState] = []
    for state in states:
        if abs(state.before_value - desired) <= 1.0e-6:
            target_rows.append(
                {
                    "target_track_name": state.target_name,
                    "track_id": state.track_id,
                    "device_id": state.device_id,
                    "before_value": state.before_value,
                    "requested_value": desired,
                    "changed": False,
                    "read_back_verified": True,
                }
            )
            continue
        try:
            result = _write_state(
                write,
                state,
                expected_value=state.before_value,
                value=desired,
                set_signature=set_signature,
            )
            changed.append(state)
            target_rows.append(
                {
                    "target_track_name": state.target_name,
                    "track_id": state.track_id,
                    "device_id": state.device_id,
                    "before_value": state.before_value,
                    "requested_value": desired,
                    "applied_value": result.get("applied_value"),
                    "changed": bool(result.get("changed")),
                    "read_back_verified": bool(result.get("read_back_verified")),
                }
            )
        except Exception as exc:  # noqa: BLE001 - reconcile uncertain effects before deciding rollback.
            current = _reconcile_parameter(
                read,
                state,
                before=state.before_value,
                desired=desired,
            )
            if current == "DESIRED":
                changed.append(state)
            elif current == "UNKNOWN":
                return {
                    "schema_version": SIDECHAIN_CONFIGURATION_SCHEMA_VERSION,
                    "effect_state": "UNKNOWN",
                    "status": "FAILED_UNKNOWN",
                    "source_track_name": source,
                    "intent": intent,
                    "set_signature": set_signature,
                    "selected_target_count": len(states),
                    "confirmed_changed_target_count": len(changed),
                    "failed_target_track_name": state.target_name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "reconciliation": "current target effect could not be determined; no replay or rollback was attempted",
                    "targets": target_rows,
                }

            restored, rollback = _rollback_confirmed(
                read,
                write,
                changed,
                desired=desired,
                set_signature=set_signature,
            )
            return {
                "schema_version": SIDECHAIN_CONFIGURATION_SCHEMA_VERSION,
                "effect_state": ("STARTED_CONFIRMED" if restored and changed else "NOT_STARTED" if restored else "UNKNOWN"),
                "status": "FAILED_RESTORED" if restored else "FAILED_UNKNOWN",
                "source_track_name": source,
                "intent": intent,
                "set_signature": set_signature,
                "selected_target_count": len(states),
                "confirmed_changed_target_count": len(changed),
                "failed_target_track_name": state.target_name,
                "error": f"{type(exc).__name__}: {exc}",
                "restored": restored,
                "rollback": rollback,
                "targets": target_rows,
            }

    return {
        "schema_version": SIDECHAIN_CONFIGURATION_SCHEMA_VERSION,
        "effect_state": "STARTED_CONFIRMED" if changed else "NOT_STARTED",
        "status": "CONFIGURED",
        "source_track_name": source,
        "intent": intent,
        "set_signature": set_signature,
        "selected_target_count": len(states),
        "changed_target_count": len(changed),
        "targets": target_rows,
        "routing_note": (
            "Targets were discovered from exact resolved native Compressor2 sidechain routes. The caller supplied no device ids, plugin indices or routing objects."
        ),
    }
