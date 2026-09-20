from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .capture_session import CaptureSessionTap
from .live import LiveBridgeClient, LivePilotWriteClient
from .locator_client import LocatorBridgeClient
from .managed_capture import ManagedCaptureResult, run_managed_capture_session
from .sections import build_section_map, resolve_section


class LiveLoudnessExperimentError(RuntimeError):
    """Raised when a bounded live loudness experiment cannot remain effect-certain."""


@dataclass(frozen=True, slots=True)
class ResolvedMasterParameter:
    set_signature: str
    track_id: int
    track_name: str
    device_index: int
    device_id: int
    device_name: str
    parameter_index: int
    parameter_id: int
    parameter_name: str
    value: float
    display: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_master_parameter(
    read: LiveBridgeClient,
    *,
    device_name: str,
    parameter_name: str,
    device_limit: int = 64,
    parameter_limit: int = 512,
) -> ResolvedMasterParameter:
    summary = read.set_summary(track_limit=1, device_limit=device_limit)
    signature = str(summary.get("set_signature") or "")
    if not signature:
        raise LiveLoudnessExperimentError("Live Set summary has no Set signature")
    master = summary.get("master_track") or {}
    devices = list(master.get("devices") or [])
    matches = [(index, item) for index, item in enumerate(devices) if item.get("name") == device_name]
    if len(matches) != 1:
        raise LiveLoudnessExperimentError(
            f"expected exactly one master device named {device_name!r}; found {len(matches)}"
        )
    device_index, device = matches[0]
    params = read.call(
        "device_parameters",
        {"ref": {"id": int(device["id"])}, "limit": int(parameter_limit)},
    )
    if not isinstance(params, list):
        raise LiveLoudnessExperimentError("device_parameters returned an unsupported payload")
    matches = [(index, item) for index, item in enumerate(params) if item.get("name") == parameter_name]
    if len(matches) != 1:
        raise LiveLoudnessExperimentError(
            f"expected exactly one parameter named {parameter_name!r}; found {len(matches)}"
        )
    parameter_index, parameter = matches[0]
    return ResolvedMasterParameter(
        set_signature=signature,
        track_id=int(master["id"]),
        track_name=str(master["name"]),
        device_index=int(device_index),
        device_id=int(device["id"]),
        device_name=device_name,
        parameter_index=int(parameter_index),
        parameter_id=int(parameter["id"]),
        parameter_name=parameter_name,
        value=float(parameter["value"]),
        display=None if parameter.get("display") is None else str(parameter["display"]),
    )


def _same_value(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1.0e-6


def _same_identity(left: ResolvedMasterParameter, right: ResolvedMasterParameter) -> bool:
    return (
        left.track_id == right.track_id
        and left.device_id == right.device_id
        and left.parameter_id == right.parameter_id
        and left.device_index == right.device_index
        and left.parameter_index == right.parameter_index
    )


def _write_master_parameter(
    write: LivePilotWriteClient,
    state: ResolvedMasterParameter,
    value: float,
) -> dict[str, Any]:
    return write.set_device_parameter(
        placement="master",
        expected_track_name=state.track_name,
        device_index=state.device_index,
        expected_device_name=state.device_name,
        parameter_index=state.parameter_index,
        expected_parameter_name=state.parameter_name,
        expected_current_value=state.value,
        value=float(value),
        expected_track_id=state.track_id,
        expected_device_id=state.device_id,
        expected_parameter_id=state.parameter_id,
        expected_set_signature=state.set_signature,
    )


def _resolve_named_range(
    locator: LocatorBridgeClient,
    *,
    section_name: str,
    expected_set_signature: str,
) -> dict[str, Any]:
    section_map = build_section_map(locator.locators(limit=256))
    signature = str(section_map.get("set_signature") or "")
    if signature != expected_set_signature:
        raise LiveLoudnessExperimentError(
            "Live Set changed between parameter inspection and section resolution"
        )
    return resolve_section(section_map, section_name)


def run_master_parameter_capture(
    *,
    experiment_id: str,
    source_label: str,
    section_name: str,
    output_dir: str | Path,
    device_name: str,
    parameter_name: str,
    expected_before_value: float,
    candidate_value: float,
    expected_before_display: str | None = None,
    expected_candidate_display: str | None = None,
    tap_id: int = 201,
    read: LiveBridgeClient | None = None,
    write: LivePilotWriteClient | None = None,
    locator: LocatorBridgeClient | None = None,
    capture_runner: Callable[..., ManagedCaptureResult] = run_managed_capture_session,
) -> dict[str, Any]:
    """Apply one exact master parameter candidate, capture it, then restore exactly."""
    read_client = read or LiveBridgeClient()
    write_client = write or LivePilotWriteClient()
    locator_client = locator or LocatorBridgeClient()
    before = resolve_master_parameter(
        read_client,
        device_name=device_name,
        parameter_name=parameter_name,
    )
    if not _same_value(before.value, expected_before_value):
        raise LiveLoudnessExperimentError(
            "master parameter changed since planning; refusing before any write"
        )
    if expected_before_display is not None and before.display != expected_before_display:
        raise LiveLoudnessExperimentError(
            "master parameter display changed since planning; refusing before any write"
        )
    _resolve_named_range(
        locator_client,
        section_name=section_name,
        expected_set_signature=before.set_signature,
    )

    write_attempted = False
    candidate: ResolvedMasterParameter | None = None
    capture_result: ManagedCaptureResult | None = None
    write_result: dict[str, Any] | None = None
    restore_result: dict[str, Any] | None = None
    restored: ResolvedMasterParameter | None = None
    try:
        write_attempted = True
        write_result = _write_master_parameter(write_client, before, candidate_value)
        candidate = resolve_master_parameter(
            read_client,
            device_name=device_name,
            parameter_name=parameter_name,
        )
        if not _same_identity(before, candidate):
            raise LiveLoudnessExperimentError(
                "master parameter identity changed after candidate write; effect state is UNKNOWN"
            )
        applied_value = float((write_result.get("parameter") or {}).get("value", candidate_value))
        if not _same_value(candidate.value, applied_value):
            raise LiveLoudnessExperimentError(
                "candidate parameter read-back does not match the typed write result"
            )
        if expected_candidate_display is not None and candidate.display != expected_candidate_display:
            raise LiveLoudnessExperimentError(
                "candidate parameter display did not match the planned bounded value"
            )
        section = _resolve_named_range(
            locator_client,
            section_name=section_name,
            expected_set_signature=candidate.set_signature,
        )
        capture_result = capture_runner(
            experiment_id=experiment_id,
            taps=[CaptureSessionTap(tap_id, source_label, "master", "post_fx")],
            output_dir=output_dir,
            start_beat=float(section["start_beat"]),
            end_beat=float(section["end_beat"]),
            expected_set_signature=candidate.set_signature,
            remove_created_after=True,
            include_analysis=False,
        )
    finally:
        if write_attempted:
            current = resolve_master_parameter(
                read_client,
                device_name=device_name,
                parameter_name=parameter_name,
            )
            if not _same_identity(before, current):
                raise LiveLoudnessExperimentError(
                    "master parameter identity changed before restore; effect state is UNKNOWN"
                )
            if _same_value(current.value, before.value):
                restored = current
            else:
                expected_candidate = candidate.value if candidate is not None else float(candidate_value)
                if not _same_value(current.value, expected_candidate):
                    raise LiveLoudnessExperimentError(
                        "master parameter changed unexpectedly during experiment; refusing blind restore; effect state is UNKNOWN"
                    )
                restore_result = _write_master_parameter(write_client, current, before.value)
                restored = resolve_master_parameter(
                    read_client,
                    device_name=device_name,
                    parameter_name=parameter_name,
                )
                if not _same_identity(before, restored) or not _same_value(restored.value, before.value):
                    raise LiveLoudnessExperimentError(
                        "master parameter did not restore exactly; effect state is UNKNOWN"
                    )
                if expected_before_display is not None and restored.display != expected_before_display:
                    raise LiveLoudnessExperimentError(
                        "master parameter display did not restore exactly; effect state is UNKNOWN"
                    )

    if capture_result is None or candidate is None or restored is None or write_result is None:
        raise LiveLoudnessExperimentError("bounded master candidate did not complete")
    return {
        "effect_state": "STARTED_CONFIRMED",
        "restored": True,
        "parameter_before": before.as_dict(),
        "candidate_write": write_result,
        "parameter_candidate": candidate.as_dict(),
        "restore_write": restore_result,
        "parameter_restored": restored.as_dict(),
        "manifest_path": str(capture_result.manifest_path),
        "topology": capture_result.topology.as_dict(),
        "capture_restore": capture_result.restore,
    }
