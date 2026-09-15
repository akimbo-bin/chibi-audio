from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .capture import CaptureError, _safe_id, wait_for_stable_capture
from .capture_finalize import TapCaptureInput, finalize_aligned_captures, samples_for_beat_range
from .live import LiveBridgeClient, LiveBridgeError, LiveCaptureClient


@dataclass(frozen=True, slots=True)
class CaptureSessionTap:
    tap_id: int
    source_label: str
    target: str

    def __post_init__(self) -> None:
        if self.tap_id < 1 or self.tap_id > 9999:
            raise CaptureError("tap_id must be between 1 and 9999")
        object.__setattr__(self, "source_label", _safe_id(self.source_label))
        target = self.target.strip()
        if not target:
            raise CaptureError("target must not be empty")
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True)
class ResolvedSessionTap:
    tap_id: int
    source_label: str
    placement: str
    track_name: str
    track_index: int | None
    track_id: int
    device_id: int

    def configure_kwargs(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "placement": self.placement,
            "expected_device_id": self.device_id,
        }
        if self.placement == "track":
            result["track_index"] = self.track_index
            result["expected_track_name"] = self.track_name
        return result


def parse_session_tap(value: str) -> CaptureSessionTap:
    try:
        tap_text, label, target = value.split(":", 2)
        return CaptureSessionTap(int(tap_text), label, target)
    except (ValueError, CaptureError) as exc:
        raise CaptureError(
            "session tap must use TAP_ID:LABEL:TARGET, for example 2:BASS:BASS or 1:Main:master"
        ) from exc


def default_capture_root() -> Path:
    return Path.home() / ".chibi-audio" / "chibitap" / "captures"


def _parameters_by_name(read_client: LiveBridgeClient, device_id: int) -> dict[str, dict[str, Any]]:
    params = read_client.call("device_parameters", {"ref": {"id": int(device_id)}, "limit": 16})
    return {str(item.get("name")): item for item in params}


def resolve_session_taps(
    read_client: LiveBridgeClient,
    summary: dict[str, Any],
    specs: Iterable[CaptureSessionTap],
) -> list[ResolvedSessionTap]:
    resolved: list[ResolvedSessionTap] = []
    used_ids: set[int] = set()
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
        matches = [device for device in devices if device.get("name") == "ChibiTap"]
        if len(matches) != 1:
            raise CaptureError(
                f"{track.get('name')!r} must contain exactly one ChibiTap; found {len(matches)}"
            )
        tap = matches[0]
        if devices[-1].get("id") != tap.get("id"):
            raise CaptureError(f"ChibiTap must be the final device on {track.get('name')!r}")

        params = _parameters_by_name(read_client, int(tap["id"]))
        capture = params.get("Capture")
        tap_id_param = params.get("Tap ID")
        if capture is None or tap_id_param is None:
            raise CaptureError(f"ChibiTap on {track.get('name')!r} does not expose Capture + Tap ID")
        if float(capture.get("value", 0.0)) >= 0.5:
            # Live can briefly report the previous host-parameter value immediately
            # after a prior session disarms a tap. Re-read once before refusing the
            # next session; never mutate an unexpectedly armed tap automatically.
            time.sleep(0.2)
            params = _parameters_by_name(read_client, int(tap["id"]))
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
                f"ChibiTap Tap ID mismatch on {track.get('name')!r}: {observed_tap_id} != {spec.tap_id}"
            )

        resolved.append(
            ResolvedSessionTap(
                tap_id=spec.tap_id,
                source_label=spec.source_label,
                placement=placement,
                track_name=str(track.get("name") or ""),
                track_index=track_index,
                track_id=int(track["id"]),
                device_id=int(tap["id"]),
            )
        )

    if not resolved:
        raise CaptureError("capture session requires at least one tap")
    return resolved


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
    tempo = float(summary.get("tempo") or 0.0)
    target_samples = samples_for_beat_range(start_beat, end_beat, tempo, 48000)
    expected_seconds = target_samples / 48000.0

    song = read_client.call(
        "get",
        {"ref": {"path": "song"}, "properties": ["name", "file_path", "current_song_time"]},
    )
    song_properties = song.get("properties") or {}
    resolved = resolve_session_taps(read_client, summary, taps)

    root = Path(capture_root) if capture_root is not None else default_capture_root()
    root.mkdir(parents=True, exist_ok=True)
    before = {tap.tap_id: _files_for_tap(root, tap.tap_id) for tap in resolved}
    armed: list[ResolvedSessionTap] = []
    play_started = False
    transport_start: float | None = None
    transport_stop: float | None = None

    try:
        capture_client.transport("stop", expected_set_signature=set_signature)
        for tap in resolved:
            kwargs = tap.configure_kwargs()
            capture_client.configure_chibitap(
                **kwargs,
                capture_enabled=True,
                expected_capture_enabled=False,
                expected_set_signature=set_signature,
            )
            armed.append(tap)

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

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["live_session"] = {
        "set_signature": set_signature,
        "song": {
            "name": song_properties.get("name"),
            "file_path": song_properties.get("file_path"),
        },
        "transport_start_beat": transport_start,
        "transport_stop_beat": transport_stop,
        "tap_mapping": [asdict(tap) for tap in resolved],
        "raw_stable_artifacts": {str(key): value for key, value in raw_artifacts.items()},
    }
    _atomic_write_json(manifest_path, manifest)
    return manifest_path
