from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .capture import CaptureError, _safe_id, wait_for_stable_capture
from .capture_finalize import TapCaptureInput, finalize_aligned_captures, samples_for_beat_range
from .live import LiveBridgeClient, LiveBridgeError, LiveCaptureClient


SIGNAL_POINTS = frozenset({"post_fx", "pre_fx", "post_instrument"})


@dataclass(frozen=True, slots=True)
class CaptureSessionTap:
    tap_id: int
    source_label: str
    target: str
    signal_point: str = "post_fx"

    def __post_init__(self) -> None:
        if self.tap_id < 1 or self.tap_id > 9999:
            raise CaptureError("tap_id must be between 1 and 9999")
        object.__setattr__(self, "source_label", _safe_id(self.source_label))
        target = self.target.strip()
        if not target:
            raise CaptureError("target must not be empty")
        object.__setattr__(self, "target", target)
        signal_point = self.signal_point.strip().lower()
        if signal_point not in SIGNAL_POINTS:
            raise CaptureError("signal_point must be post_fx, pre_fx, or post_instrument")
        object.__setattr__(self, "signal_point", signal_point)


@dataclass(frozen=True, slots=True)
class ResolvedSessionTap:
    tap_id: int
    source_label: str
    placement: str
    signal_point: str
    track_name: str
    track_index: int | None
    track_id: int
    device_id: int
    device_index: int

    def configure_kwargs(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "placement": self.placement,
            "signal_point": self.signal_point,
            "expected_device_id": self.device_id,
        }
        if self.placement == "track":
            result["track_index"] = self.track_index
            result["expected_track_name"] = self.track_name
        return result


def parse_session_tap(value: str) -> CaptureSessionTap:
    try:
        parts = value.split(":", 3)
        if len(parts) == 3:
            tap_text, label, target = parts
            signal_point = "post_fx"
        elif len(parts) == 4:
            tap_text, label, maybe_signal_point, remainder = parts
            normalized = maybe_signal_point.strip().lower()
            if normalized in SIGNAL_POINTS:
                signal_point = normalized
                target = remainder
            else:
                # Preserve legacy target names containing ':' exactly. A four-part
                # form is interpreted as signal-point syntax only when the third
                # field is one of the three reviewed signal-point identifiers.
                signal_point = "post_fx"
                target = maybe_signal_point + ":" + remainder
        else:
            raise ValueError
        return CaptureSessionTap(int(tap_text), label, target, signal_point)
    except (ValueError, CaptureError) as exc:
        raise CaptureError(
            "session tap must use TAP_ID:LABEL:TARGET or TAP_ID:LABEL:SIGNAL_POINT:TARGET; "
            "for example 2:BASS:BASS or 2:BASS_PRE:pre_fx:BASS"
        ) from exc


def default_capture_root() -> Path:
    return Path.home() / ".chibi-audio" / "chibitap" / "captures"


def _parameters_by_name(read_client: LiveBridgeClient, device_id: int) -> dict[str, dict[str, Any]]:
    params = read_client.call("device_parameters", {"ref": {"id": int(device_id)}, "limit": 16})
    return {str(item.get("name")): item for item in params}


def _device_type(
    read_client: LiveBridgeClient,
    device: dict[str, Any],
    cache: dict[int, int],
) -> int:
    device_id = device.get("id")
    if device_id is None:
        raise CaptureError("Live device summary is missing an object id; cannot verify ChibiTap signal point")
    device_id = int(device_id)
    if device_id in cache:
        return cache[device_id]
    try:
        details = read_client.call(
            "get",
            {"ref": {"id": device_id}, "properties": ["type"]},
        )
        value = (details.get("properties") or {}).get("type")
        if value is None:
            raise ValueError("missing type")
        device_type = int(value)
    except (KeyError, TypeError, ValueError, LiveBridgeError) as exc:
        raise CaptureError(
            f"Live device {device.get('name')!r} ({device_id}) did not expose a usable type; "
            "cannot verify ChibiTap signal point"
        ) from exc
    cache[device_id] = device_type
    return device_type


def _expected_signal_point_index(
    read_client: LiveBridgeClient,
    devices: list[dict[str, Any]],
    signal_point: str,
    type_cache: dict[int, int],
) -> int:
    if not devices:
        raise CaptureError("target track has no devices; cannot verify ChibiTap signal point")
    if any(bool(device.get("truncated")) for device in devices):
        raise CaptureError("Live device summary was truncated; refusing to guess ChibiTap signal point")
    if signal_point == "post_fx":
        return len(devices) - 1
    if signal_point == "pre_fx":
        for index, device in enumerate(devices):
            if _device_type(read_client, device, type_cache) == 2:
                return index
        # A valid ChibiTap is itself an audio effect, so reaching this boundary
        # means the Live type information did not describe the observed chain.
        raise CaptureError("target track exposes no audio-effect device; cannot verify pre_fx ChibiTap")
    if signal_point == "post_instrument":
        instruments = [
            index
            for index, device in enumerate(devices)
            if _device_type(read_client, device, type_cache) == 1
        ]
        if len(instruments) != 1:
            raise CaptureError(
                f"post_instrument requires exactly one instrument device; found {len(instruments)}"
            )
        return instruments[0] + 1
    raise CaptureError("signal_point must be post_fx, pre_fx, or post_instrument")


def resolve_session_taps(
    read_client: LiveBridgeClient,
    summary: dict[str, Any],
    specs: Iterable[CaptureSessionTap],
) -> list[ResolvedSessionTap]:
    resolved: list[ResolvedSessionTap] = []
    used_ids: set[int] = set()
    used_device_ids: set[int] = set()
    type_cache: dict[int, int] = {}
    tracks = list(summary.get("tracks") or [])
    master = summary.get("master_track") or {}

    for spec in specs:
        if spec.tap_id in used_ids:
            raise CaptureError(f"duplicate tap_id in session: {spec.tap_id}")
        used_ids.add(spec.tap_id)

        if spec.target.lower() in {"master", "main"}:
            track = master
            placement = "master"
            track_index = None
        else:
            matches = [track for track in tracks if track.get("name") == spec.target]
            if len(matches) != 1:
                raise CaptureError(
                    f"expected exactly one Live track named {spec.target!r}; found {len(matches)}"
                )
            track = matches[0]
            placement = "track"
            track_index = int(track["index"])

        devices = list(track.get("devices") or [])
        expected_index = _expected_signal_point_index(
            read_client,
            devices,
            spec.signal_point,
            type_cache,
        )
        if expected_index < 0 or expected_index >= len(devices):
            raise CaptureError(
                f"ChibiTap signal point {spec.signal_point!r} resolved outside the device chain "
                f"on {track.get('name')!r}"
            )
        tap = devices[expected_index]
        if tap.get("name") != "ChibiTap":
            raise CaptureError(
                f"ChibiTap is not installed at {spec.signal_point} on {track.get('name')!r}; "
                f"expected index {expected_index}, found {tap.get('name')!r}"
            )
        if tap.get("id") is None:
            raise CaptureError(
                f"ChibiTap at {spec.signal_point} on {track.get('name')!r} is missing an object id"
            )
        device_id = int(tap["id"])
        if device_id in used_device_ids:
            raise CaptureError(
                f"session signal points resolve to the same ChibiTap device on {track.get('name')!r}; "
                "use one tap for topologically equivalent signal points"
            )
        used_device_ids.add(device_id)

        params = _parameters_by_name(read_client, device_id)
        capture = params.get("Capture")
        tap_id_param = params.get("Tap ID")
        if capture is None or tap_id_param is None:
            raise CaptureError(f"ChibiTap on {track.get('name')!r} does not expose Capture + Tap ID")
        if float(capture.get("value", 0.0)) >= 0.5:
            # Live can briefly report the previous host-parameter value immediately
            # after a prior session disarms a tap. Re-read once before refusing the
            # next session; never mutate an unexpectedly armed tap automatically.
            time.sleep(0.2)
            params = _parameters_by_name(read_client, device_id)
            capture = params.get("Capture")
            tap_id_param = params.get("Tap ID")
            if capture is None or tap_id_param is None:
                raise CaptureError(f"ChibiTap on {track.get('name')!r} does not expose Capture + Tap ID")
            if float(capture.get("value", 0.0)) >= 0.5:
                raise CaptureError(f"ChibiTap Capture is already On for {track.get('name')!r}")
        try:
            observed_tap_id = int(str(tap_id_param.get("display", "")).strip())
        except ValueError as exc:
            raise CaptureError(f"ChibiTap Tap ID is unreadable for {track.get('name')!r}") from exc
        if observed_tap_id != spec.tap_id:
            raise CaptureError(
                f"ChibiTap Tap ID mismatch on {track.get('name')!r} at {spec.signal_point}: "
                f"{observed_tap_id} != {spec.tap_id}"
            )

        resolved.append(
            ResolvedSessionTap(
                tap_id=spec.tap_id,
                source_label=spec.source_label,
                placement=placement,
                signal_point=spec.signal_point,
                track_name=str(track.get("name") or ""),
                track_index=track_index,
                track_id=int(track["id"]),
                device_id=device_id,
                device_index=expected_index,
            )
        )

    if not resolved:
        raise CaptureError("capture session requires at least one tap")
    return resolved


def _capture_mixer_state(summary: dict[str, Any], taps: Iterable[ResolvedSessionTap]) -> dict[str, Any]:
    tracks = list(summary.get("tracks") or [])
    by_id = {
        int(track["id"]): track
        for track in tracks
        if track.get("id") is not None
    }
    active_solos = [
        {
            "id": int(track["id"]),
            "index": int(track["index"]) if track.get("index") is not None else None,
            "name": str(track.get("name") or ""),
        }
        for track in tracks
        if bool(track.get("solo")) and track.get("id") is not None
    ]
    targets: list[dict[str, Any]] = []
    warnings: list[str] = []

    for tap in taps:
        track = (summary.get("master_track") or {}) if tap.placement == "master" else by_id.get(tap.track_id, {})
        target = {
            "tap_id": tap.tap_id,
            "source_label": tap.source_label,
            "placement": tap.placement,
            "signal_point": tap.signal_point,
            "device_index": tap.device_index,
            "track_id": tap.track_id,
            "track_index": tap.track_index,
            "track_name": tap.track_name,
            "mute": bool(track.get("mute", False)),
            "solo": bool(track.get("solo", False)),
            "solo_suppression_risk": bool(active_solos and tap.placement != "master" and not bool(track.get("solo", False))),
        }
        targets.append(target)
        if target["mute"]:
            warnings.append(
                f"Tap {tap.tap_id} target {tap.track_name!r} is muted; its capture may be silent."
            )
        if target["solo_suppression_risk"]:
            warnings.append(
                f"Tap {tap.tap_id} target {tap.track_name!r} is not soloed while Live has active solos; its capture may be suppressed."
            )

    if active_solos:
        warnings.insert(
            0,
            "Live has active solo tracks; non-soloed tap targets may capture silence or a partial bus.",
        )

    return {
        "active_solos": active_solos,
        "active_solo_count": len(active_solos),
        "tap_targets": targets,
        "warnings": warnings,
    }


def _verified_arm_proof(tap: ResolvedSessionTap, result: dict[str, Any]) -> dict[str, Any]:
    signal_point = str(result.get("signal_point") or "")
    if signal_point != tap.signal_point:
        raise CaptureError(
            f"ChibiTap arm response signal point changed for {tap.track_name!r}: "
            f"{signal_point!r} != {tap.signal_point!r}"
        )
    device = result.get("device") or {}
    try:
        device_id = int(device.get("id"))
        device_index = int(result.get("device_index"))
    except (TypeError, ValueError) as exc:
        raise CaptureError(f"ChibiTap arm response was missing device provenance for {tap.track_name!r}") from exc
    if device_id != tap.device_id:
        raise CaptureError(
            f"ChibiTap device identity changed while arming {tap.track_name!r}: {device_id} != {tap.device_id}"
        )
    if device_index != tap.device_index:
        raise CaptureError(
            f"ChibiTap device index changed while arming {tap.track_name!r}: "
            f"{device_index} != {tap.device_index}"
        )
    return {
        "signal_point": signal_point,
        "device_id": device_id,
        "device_index": device_index,
    }


def _files_for_tap(root: Path, tap_id: int) -> set[Path]:
    if not root.exists():
        return set()
    return set(root.glob(f"chibitap-tap-{tap_id}-*.wav"))


def _newest_new_file(root: Path, tap_id: int, before: set[Path]) -> Path:
    candidates = [path for path in _files_for_tap(root, tap_id) if path not in before]
    if not candidates:
        raise CaptureError(f"no new ChibiTap artifact appeared for Tap ID {tap_id}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def run_capture_session(
    *,
    experiment_id: str,
    taps: Iterable[CaptureSessionTap],
    output_dir: str | Path,
    start_beat: float,
    end_beat: float,
    host: str = "127.0.0.1",
    port: int = 18765,
    capture_root: str | Path | None = None,
    include_analysis: bool = True,
    poll_interval: float = 0.05,
    settle_seconds: float = 0.6,
    timeout_margin: float = 8.0,
    expected_set_signature: str | None = None,
) -> Path:
    if poll_interval <= 0:
        raise CaptureError("poll_interval must be > 0")
    if settle_seconds < 0 or timeout_margin <= 0:
        raise CaptureError("settle_seconds must be >= 0 and timeout_margin must be > 0")

    read_client = LiveBridgeClient(host=host, port=port, timeout=30.0)
    capture_client = LiveCaptureClient(host=host, port=port, timeout=30.0)
    summary = read_client.set_summary(
        track_limit=240,
        device_limit=96,
        arrangement_clip_limit=0,
        include_return_tracks=False,
        include_master_track=True,
    )
    set_signature = str(summary.get("set_signature") or "")
    if not set_signature:
        raise CaptureError("Live summary did not contain a Set signature")
    if expected_set_signature is not None and set_signature != expected_set_signature:
        raise CaptureError(
            "Live Set changed since capture planning; refusing capture before any transport or ChibiTap effect"
        )
    tempo = float(summary.get("tempo") or 0.0)
    target_samples = samples_for_beat_range(start_beat, end_beat, tempo, 48000)
    expected_seconds = target_samples / 48000.0

    song = read_client.call(
        "get",
        {"ref": {"path": "song"}, "properties": ["name", "file_path", "current_song_time"]},
    )
    song_properties = song.get("properties") or {}
    resolved = resolve_session_taps(read_client, summary, taps)
    mixer_state = _capture_mixer_state(summary, resolved)

    root = Path(capture_root) if capture_root is not None else default_capture_root()
    root.mkdir(parents=True, exist_ok=True)
    before = {tap.tap_id: _files_for_tap(root, tap.tap_id) for tap in resolved}
    armed: list[ResolvedSessionTap] = []
    arm_verification: dict[int, dict[str, Any]] = {}
    play_started = False
    transport_start: float | None = None
    transport_stop: float | None = None

    try:
        capture_client.transport("stop", expected_set_signature=set_signature)
        for tap in resolved:
            kwargs = tap.configure_kwargs()
            result = capture_client.configure_chibitap(
                **kwargs,
                capture_enabled=True,
                expected_capture_enabled=False,
                expected_set_signature=set_signature,
            )
            # configure_chibitap can have changed Capture before its response is
            # validated below, so register the tap for guaranteed cleanup first.
            armed.append(tap)
            arm_verification[tap.tap_id] = _verified_arm_proof(tap, result)

        if settle_seconds:
            time.sleep(settle_seconds)
        play = capture_client.transport(
            "play_until",
            time=float(start_beat),
            end_time=float(end_beat),
            expected_set_signature=set_signature,
        )
        play_started = True
        transport_start = float(play.get("scheduled_start_time", start_beat))

        deadline = time.monotonic() + expected_seconds + timeout_margin
        while True:
            if time.monotonic() > deadline:
                raise CaptureError("Live transport did not stop at the requested end beat before timeout")
            time.sleep(poll_interval)
            status = capture_client.transport("status", expected_set_signature=set_signature)
            if bool(status.get("playing")):
                continue
            observed_stop = status.get("last_scheduled_stop_time")
            if observed_stop is None:
                observed_stop = status.get("time", end_beat)
            transport_stop = float(observed_stop)
            play_started = False
            if transport_stop + 1.0e-6 < float(end_beat):
                raise CaptureError("Live transport stopped before requested end beat")
            break
    finally:
        if play_started:
            try:
                stopped = capture_client.transport("stop", expected_set_signature=set_signature)
                transport_stop = float(stopped.get("time", end_beat))
            except Exception:
                pass
        cleanup_errors: list[str] = []
        for tap in reversed(armed):
            try:
                kwargs = tap.configure_kwargs()
                capture_client.configure_chibitap(
                    **kwargs,
                    capture_enabled=False,
                    expected_capture_enabled=True,
                    expected_set_signature=set_signature,
                )
            except Exception as exc:
                cleanup_errors.append(f"{tap.track_name}: {exc}")
        if cleanup_errors:
            raise CaptureError("failed to disarm ChibiTap instances: " + "; ".join(cleanup_errors))

    raw_inputs: list[TapCaptureInput] = []
    raw_artifacts: dict[int, dict[str, Any]] = {}
    for tap in resolved:
        path = _newest_new_file(root, tap.tap_id, before[tap.tap_id])
        stable = wait_for_stable_capture(path, timeout=30.0, stable_for=0.3, poll_interval=0.1)
        raw_inputs.append(TapCaptureInput(tap.tap_id, tap.source_label, path))
        raw_artifacts[tap.tap_id] = stable.as_dict()

    manifest_path = finalize_aligned_captures(
        experiment_id=experiment_id,
        inputs=raw_inputs,
        output_dir=output_dir,
        start_beat=start_beat,
        end_beat=end_beat,
        tempo_bpm=tempo,
        sample_rate=48000,
        channels=2,
        transport_start_beat=transport_start,
        transport_stop_beat=transport_stop,
        include_analysis=include_analysis,
    )

    tap_mapping: list[dict[str, Any]] = []
    for tap in resolved:
        item = asdict(tap)
        item["arm_verification"] = arm_verification[tap.tap_id]
        tap_mapping.append(item)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["live_session"] = {
        "set_signature": set_signature,
        "song": {
            "name": song_properties.get("name"),
            "file_path": song_properties.get("file_path"),
        },
        "transport_start_beat": transport_start,
        "transport_stop_beat": transport_stop,
        "tap_mapping": tap_mapping,
        "mixer_state": mixer_state,
        "raw_stable_artifacts": {str(key): value for key, value in raw_artifacts.items()},
    }
    _atomic_write_json(manifest_path, manifest)
    return manifest_path
