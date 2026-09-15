from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .capture import CaptureError
from .capture_session import CaptureSessionTap, resolve_session_taps
from .live import LiveBridgeClient, LiveCaptureClient


@dataclass(slots=True)
class PreparedTopologyTap:
    tap_id: int
    source_label: str
    target: str
    placement: str
    signal_point: str
    track_name: str
    track_index: int | None
    track_id: int
    device_id: int
    device_index: int
    created: bool
    prior_tap_id: int
    tap_id_changed: bool = False

    def session_spec(self) -> CaptureSessionTap:
        return CaptureSessionTap(
            self.tap_id,
            self.source_label,
            self.target,
            self.signal_point,
        )


@dataclass(frozen=True, slots=True)
class CaptureTopologyLease:
    initial_set_signature: str
    final_set_signature: str
    taps: tuple[PreparedTopologyTap, ...]

    def session_specs(self) -> list[CaptureSessionTap]:
        return [tap.session_spec() for tap in self.taps]

    def as_dict(self) -> dict[str, Any]:
        return {
            "initial_set_signature": self.initial_set_signature,
            "final_set_signature": self.final_set_signature,
            "taps": [asdict(tap) for tap in self.taps],
        }


def _fresh_summary(read_client: LiveBridgeClient) -> dict[str, Any]:
    return read_client.set_summary(
        track_limit=240,
        device_limit=96,
        arrangement_clip_limit=0,
        include_return_tracks=False,
        include_master_track=True,
    )


def _set_signature(summary: dict[str, Any]) -> str:
    value = str(summary.get("set_signature") or "")
    if not value:
        raise CaptureError("Live summary did not contain a Set signature")
    return value


def _target_context(summary: dict[str, Any], spec: CaptureSessionTap) -> dict[str, Any]:
    if spec.target.lower() in {"master", "main"}:
        track = summary.get("master_track") or {}
        placement = "master"
        track_index = None
    else:
        matches = [track for track in (summary.get("tracks") or []) if track.get("name") == spec.target]
        if len(matches) != 1:
            raise CaptureError(
                f"expected exactly one Live track named {spec.target!r}; found {len(matches)}"
            )
        track = matches[0]
        placement = "track"
        track_index = int(track["index"])
    if track.get("id") is None:
        raise CaptureError(f"Live target {spec.target!r} did not expose an object id")
    return {
        "placement": placement,
        "track_index": track_index,
        "track_name": str(track.get("name") or ""),
        "track_id": int(track["id"]),
    }


def _target_kwargs(context: dict[str, Any], signal_point: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "placement": context["placement"],
        "signal_point": signal_point,
    }
    if context["placement"] == "track":
        result["track_index"] = context["track_index"]
        result["expected_track_name"] = context["track_name"]
    return result


def _verify_setup_result(
    spec: CaptureSessionTap,
    context: dict[str, Any],
    result: dict[str, Any],
) -> tuple[int, int, int, bool]:
    if str(result.get("signal_point") or "") != spec.signal_point:
        raise CaptureError(
            f"ChibiTap setup returned the wrong signal point for {spec.target!r}: "
            f"{result.get('signal_point')!r} != {spec.signal_point!r}"
        )
    device = result.get("device") or {}
    track = result.get("track") or {}
    try:
        device_id = int(device["id"])
        device_index = int(result["device_index"])
        track_id = int(track["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureError(f"ChibiTap setup did not return exact device provenance for {spec.target!r}") from exc
    if track_id != context["track_id"] or str(track.get("name") or "") != context["track_name"]:
        raise CaptureError(f"ChibiTap setup target identity changed for {spec.target!r}")
    parameters = result.get("parameters") or {}
    capture = parameters.get("Capture") or {}
    if float(capture.get("value", 1.0)) >= 0.5:
        raise CaptureError(f"ChibiTap Capture is On after setup for {spec.target!r}")
    try:
        prior_tap_id = int(parameters["tap_id_integer"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CaptureError(f"ChibiTap setup did not return a readable Tap ID for {spec.target!r}") from exc
    return device_id, device_index, prior_tap_id, bool(result.get("loaded"))


def _current_signature(read_client: LiveBridgeClient) -> tuple[dict[str, Any], str]:
    summary = _fresh_summary(read_client)
    return summary, _set_signature(summary)


def _observed_tap_id(read_client: LiveBridgeClient, device_id: int) -> tuple[int, bool]:
    parameters = read_client.call(
        "device_parameters",
        {"ref": {"id": int(device_id)}, "limit": 16},
    )
    by_name = {str(item.get("name")): item for item in parameters}
    capture = by_name.get("Capture")
    tap_id = by_name.get("Tap ID")
    if capture is None or tap_id is None:
        raise CaptureError(f"ChibiTap device {device_id} no longer exposes Capture + Tap ID")
    if float(capture.get("value", 0.0)) >= 0.5:
        return -1, True
    try:
        return int(str(tap_id.get("display", "")).strip()), False
    except ValueError as exc:
        raise CaptureError(f"ChibiTap device {device_id} Tap ID is unreadable during restore") from exc


def prepare_capture_topology(
    taps: Iterable[CaptureSessionTap],
    *,
    expected_set_signature: str | None = None,
    host: str = "127.0.0.1",
    port: int = 18765,
    read_client: LiveBridgeClient | None = None,
    capture_client: LiveCaptureClient | None = None,
) -> CaptureTopologyLease:
    specs = list(taps)
    if not specs:
        raise CaptureError("capture topology requires at least one tap")
    tap_ids = [spec.tap_id for spec in specs]
    if len(set(tap_ids)) != len(tap_ids):
        raise CaptureError("capture topology requires unique Tap IDs")

    reader = read_client or LiveBridgeClient(host=host, port=port, timeout=30.0)
    capture = capture_client or LiveCaptureClient(host=host, port=port, timeout=30.0)
    summary, current_signature = _current_signature(reader)
    initial_signature = current_signature
    if expected_set_signature is not None and current_signature != expected_set_signature:
        raise CaptureError(
            "Live Set changed since capture planning; refusing topology preparation before any ChibiTap effect"
        )

    prepared: list[PreparedTopologyTap] = []
    used_device_ids: set[int] = set()
    try:
        for spec in specs:
            context = _target_context(summary, spec)
            target_kwargs = _target_kwargs(context, spec.signal_point)
            setup = capture.setup_chibitap(
                **target_kwargs,
                expected_set_signature=current_signature,
            )
            device_id, device_index, prior_tap_id, created = _verify_setup_result(spec, context, setup)
            provisional = PreparedTopologyTap(
                tap_id=spec.tap_id,
                source_label=spec.source_label,
                target=spec.target,
                placement=context["placement"],
                signal_point=spec.signal_point,
                track_name=context["track_name"],
                track_index=context["track_index"],
                track_id=context["track_id"],
                device_id=device_id,
                device_index=device_index,
                created=created,
                prior_tap_id=prior_tap_id,
            )
            prepared.append(provisional)
            if device_id in used_device_ids:
                raise CaptureError(
                    f"capture topology signal points resolve to the same ChibiTap device on {context['track_name']!r}"
                )
            used_device_ids.add(device_id)

            summary, current_signature = _current_signature(reader)
            if prior_tap_id != spec.tap_id:
                capture.configure_chibitap(
                    **target_kwargs,
                    expected_device_id=device_id,
                    tap_id=spec.tap_id,
                    expected_tap_id=prior_tap_id,
                    expected_capture_enabled=False,
                    expected_set_signature=current_signature,
                )
                provisional.tap_id_changed = True
                summary, current_signature = _current_signature(reader)

        resolved = resolve_session_taps(reader, summary, specs)
        by_tap_id = {tap.tap_id: tap for tap in resolved}
        for prepared_tap in prepared:
            resolved_tap = by_tap_id.get(prepared_tap.tap_id)
            if resolved_tap is None:
                raise CaptureError(f"prepared Tap ID {prepared_tap.tap_id} disappeared before capture")
            if (
                resolved_tap.device_id != prepared_tap.device_id
                or resolved_tap.device_index != prepared_tap.device_index
                or resolved_tap.signal_point != prepared_tap.signal_point
            ):
                raise CaptureError(
                    f"prepared ChibiTap identity changed before capture for Tap ID {prepared_tap.tap_id}"
                )

        return CaptureTopologyLease(
            initial_set_signature=initial_signature,
            final_set_signature=current_signature,
            taps=tuple(prepared),
        )
    except Exception as exc:
        rollback_error: Exception | None = None
        if prepared:
            try:
                _restore_prepared_taps(
                    reader,
                    capture,
                    prepared,
                    remove_created=True,
                    expected_initial_signature=None,
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve both failures.
                rollback_error = cleanup_exc
        if rollback_error is not None:
            raise CaptureError(
                f"capture topology preparation failed and rollback was incomplete: {rollback_error}"
            ) from exc
        raise


def _restore_prepared_taps(
    read_client: LiveBridgeClient,
    capture_client: LiveCaptureClient,
    taps: Iterable[PreparedTopologyTap],
    *,
    remove_created: bool,
    expected_initial_signature: str | None,
) -> dict[str, Any]:
    _summary, current_signature = _current_signature(read_client)
    if expected_initial_signature is not None and current_signature != expected_initial_signature:
        raise CaptureError(
            "Live Set changed since topology preparation; refusing restore before any ChibiTap cleanup effect"
        )

    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for tap in reversed(list(taps)):
        target_kwargs = _target_kwargs(
            {
                "placement": tap.placement,
                "track_index": tap.track_index,
                "track_name": tap.track_name,
                "track_id": tap.track_id,
            },
            tap.signal_point,
        )
        try:
            if tap.created and remove_created:
                capture_client.remove_chibitap(
                    **target_kwargs,
                    expected_device_id=tap.device_id,
                    expected_capture_enabled=False,
                    expected_set_signature=current_signature,
                )
                actions.append({
                    "action": "remove_created",
                    "tap_id": tap.tap_id,
                    "device_id": tap.device_id,
                    "signal_point": tap.signal_point,
                })
                _summary, current_signature = _current_signature(read_client)
                continue
            if not tap.created and tap.prior_tap_id != tap.tap_id:
                observed_tap_id, capture_on = _observed_tap_id(read_client, tap.device_id)
                if capture_on:
                    raise CaptureError(
                        f"ChibiTap device {tap.device_id} Capture is On; refusing Tap ID restore"
                    )
                if observed_tap_id == tap.prior_tap_id:
                    actions.append({
                        "action": "already_restored_tap_id",
                        "tap_id": tap.tap_id,
                        "restored_tap_id": tap.prior_tap_id,
                        "device_id": tap.device_id,
                        "signal_point": tap.signal_point,
                    })
                    continue
                if observed_tap_id != tap.tap_id:
                    raise CaptureError(
                        f"ChibiTap device {tap.device_id} Tap ID changed unexpectedly during restore: "
                        f"observed {observed_tap_id}, expected {tap.tap_id} or {tap.prior_tap_id}"
                    )
                capture_client.configure_chibitap(
                    **target_kwargs,
                    expected_device_id=tap.device_id,
                    tap_id=tap.prior_tap_id,
                    expected_tap_id=observed_tap_id,
                    expected_capture_enabled=False,
                    expected_set_signature=current_signature,
                )
                actions.append({
                    "action": "restore_tap_id",
                    "tap_id": tap.tap_id,
                    "restored_tap_id": tap.prior_tap_id,
                    "device_id": tap.device_id,
                    "signal_point": tap.signal_point,
                })
                _summary, current_signature = _current_signature(read_client)
        except Exception as exc:  # noqa: BLE001 - attempt remaining exact cleanup steps.
            errors.append(f"Tap {tap.tap_id} / device {tap.device_id}: {exc}")
            _summary, current_signature = _current_signature(read_client)

    if errors:
        raise CaptureError("capture topology restore was incomplete: " + "; ".join(errors))
    return {
        "final_set_signature": current_signature,
        "remove_created": remove_created,
        "actions": actions,
    }


def restore_capture_topology(
    lease: CaptureTopologyLease,
    *,
    remove_created: bool = True,
    expected_set_signature: str | None = None,
    host: str = "127.0.0.1",
    port: int = 18765,
    read_client: LiveBridgeClient | None = None,
    capture_client: LiveCaptureClient | None = None,
) -> dict[str, Any]:
    reader = read_client or LiveBridgeClient(host=host, port=port, timeout=30.0)
    capture = capture_client or LiveCaptureClient(host=host, port=port, timeout=30.0)
    expected = lease.final_set_signature if expected_set_signature is None else expected_set_signature
    return _restore_prepared_taps(
        reader,
        capture,
        lease.taps,
        remove_created=remove_created,
        expected_initial_signature=expected,
    )
