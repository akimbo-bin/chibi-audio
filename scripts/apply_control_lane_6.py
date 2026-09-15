from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# 1. Ableton Remote Script bounded-control module.
write(
    "bridge/ChibiAudioBridge/bounded_control.py",
    '''from __future__ import absolute_import, print_function

BOUNDED_CONTROL_METHODS = (
    "track_mixer_parameter_set",
    "track_set",
    "device_parameter_set",
    "device_enabled_set",
)


def _track(self, params):
    index = params.get("track_index")
    if index is None:
        raise ValueError("track_index is required")
    index = int(index)
    tracks = self.song().tracks
    if index < 0 or index >= len(tracks):
        raise IndexError("track_index out of range")
    track = tracks[index]
    expected_name = params.get("expected_track_name")
    if not expected_name or getattr(track, "name", "") != expected_name:
        raise RuntimeError("Track identity mismatch for bounded write")
    track_id = self._object_id(track)
    expected_id = params.get("expected_track_id")
    if expected_id is not None and int(expected_id) != track_id:
        raise RuntimeError("Track object identity changed since inspection; refusing write")
    return index, track, track_id


def _device(self, track, params):
    index = params.get("device_index")
    if index is None:
        raise ValueError("device_index is required")
    index = int(index)
    devices = list(getattr(track, "devices", []))
    if index < 0 or index >= len(devices):
        raise IndexError("device_index out of range")
    device = devices[index]
    expected_name = params.get("expected_device_name")
    if not expected_name or getattr(device, "name", "") != expected_name:
        raise RuntimeError("Device identity mismatch for bounded write")
    device_id = self._object_id(device)
    expected_id = params.get("expected_device_id")
    if expected_id is not None and int(expected_id) != device_id:
        raise RuntimeError("Device object identity changed since inspection; refusing write")
    return index, device, device_id


def _parameter(self, device, params):
    index = params.get("parameter_index")
    if index is None:
        raise ValueError("parameter_index is required")
    index = int(index)
    parameters = list(getattr(device, "parameters", []))
    if index < 0 or index >= len(parameters):
        raise IndexError("parameter_index out of range")
    parameter = parameters[index]
    expected_name = params.get("expected_parameter_name")
    if not expected_name or getattr(parameter, "name", "") != expected_name:
        raise RuntimeError("Parameter identity mismatch for bounded write")
    parameter_id = self._object_id(parameter)
    expected_id = params.get("expected_parameter_id")
    if expected_id is not None and int(expected_id) != parameter_id:
        raise RuntimeError("Parameter object identity changed since inspection; refusing write")
    return index, parameter, parameter_id


def _write_parameter(self, parameter, params):
    before = self._parameter_summary(parameter)
    expected = params.get("expected_current_value")
    if expected is None or abs(float(before.get("value")) - float(expected)) > 1e-6:
        raise RuntimeError("Parameter changed since inspection; refusing write")
    value = params.get("value")
    if value is None:
        raise ValueError("value is required")
    value = float(value)
    minimum = before.get("min")
    maximum = before.get("max")
    if params.get("coerce"):
        if minimum is not None and value < minimum:
            value = minimum
        if maximum is not None and value > maximum:
            value = maximum
        if before.get("is_quantized"):
            value = int(round(value))
    else:
        if minimum is not None and value < minimum:
            raise ValueError("value is below parameter minimum")
        if maximum is not None and value > maximum:
            raise ValueError("value is above parameter maximum")
        if before.get("is_quantized") and int(value) != value:
            raise ValueError("quantized parameter requires integer value or coerce:true")
    parameter.value = value
    after = self._parameter_summary(parameter)
    if abs(float(after.get("value")) - float(value)) > 1e-6:
        raise RuntimeError("Parameter write did not read back as requested")
    return {
        "before": before,
        "parameter": after,
        "requested_value": params.get("value"),
        "applied_value": after.get("value"),
        "changed": before.get("value") != after.get("value"),
        "read_back_verified": True,
    }


def rpc_track_mixer_parameter_set(self, params):
    track_index, track, track_id = _track(self, params)
    name = params.get("parameter")
    if name not in ("volume", "panning"):
        raise ValueError("track mixer parameter must be volume or panning")
    parameter = getattr(track.mixer_device, name)
    result = _write_parameter(self, parameter, params)
    result["track"] = {"index": track_index, "id": track_id, "name": getattr(track, "name", "")}
    result["mixer_parameter"] = name
    return result


def rpc_track_set(self, params):
    track_index, track, track_id = _track(self, params)
    prop = params.get("property")
    if prop not in ("mute", "solo", "name", "color_index"):
        raise ValueError("track property must be mute, solo, name, or color_index")
    if "expected_current_value" not in params:
        raise ValueError("expected_current_value is required")
    before = getattr(track, prop)
    expected = params.get("expected_current_value")
    if before != expected:
        raise RuntimeError("Track property changed since inspection; refusing write")
    value = params.get("value")
    if prop in ("mute", "solo") and (type(value) is not bool or type(expected) is not bool):
        raise ValueError("mute/solo values must be booleans")
    if prop == "name" and (not isinstance(value, str) or not value.strip()):
        raise ValueError("track name must be non-empty")
    if prop == "color_index" and (type(value) is not int or value < 0):
        raise ValueError("color_index must be a non-negative integer")
    setattr(track, prop, value)
    after = getattr(track, prop)
    if after != value:
        raise RuntimeError("Track property write did not read back as requested")
    return {
        "track": {"index": track_index, "id": track_id, "name": getattr(track, "name", "")},
        "property": prop,
        "before": before,
        "requested_value": value,
        "applied_value": after,
        "changed": after != before,
        "read_back_verified": True,
    }


def rpc_device_parameter_set(self, params):
    track_index, track, track_id = _track(self, params)
    device_index, device, device_id = _device(self, track, params)
    parameter_index, parameter, parameter_id = _parameter(self, device, params)
    result = _write_parameter(self, parameter, params)
    result["track"] = {"index": track_index, "id": track_id, "name": getattr(track, "name", "")}
    result["device"] = {"index": device_index, "id": device_id, "name": getattr(device, "name", "")}
    result["parameter_index"] = parameter_index
    result["parameter_id"] = parameter_id
    return result


def rpc_device_enabled_set(self, params):
    if type(params.get("enabled")) is not bool:
        raise ValueError("enabled must be a boolean")
    forwarded = dict(params)
    forwarded["value"] = 1.0 if params["enabled"] else 0.0
    result = rpc_device_parameter_set(self, forwarded)
    result["enabled"] = params["enabled"]
    return result


def install_bounded_control(cls):
    cls._rpc_track_mixer_parameter_set = rpc_track_mixer_parameter_set
    cls._rpc_track_set = rpc_track_set
    cls._rpc_device_parameter_set = rpc_device_parameter_set
    cls._rpc_device_enabled_set = rpc_device_enabled_set
    return cls
''',
)

# 2. Small bridge registration hook only.
bridge = read("bridge/ChibiAudioBridge/bridge.py")
import_line = "from _Framework.ControlSurface import ControlSurface\n"
if "from .bounded_control import BOUNDED_CONTROL_METHODS, install_bounded_control" not in bridge:
    bridge = bridge.replace(import_line, import_line + "from .bounded_control import BOUNDED_CONTROL_METHODS, install_bounded_control\n")
bridge = bridge.replace(
    'MODEL_BOUNDED_WRITE_METHODS = ("parameter_set",)',
    'MODEL_BOUNDED_WRITE_METHODS = ("parameter_set",) + BOUNDED_CONTROL_METHODS',
)
if "install_bounded_control(AbletonLiveMCP)" not in bridge:
    bridge = bridge.replace("\nAbletonObjectMCP = AbletonLiveMCP\n", "\ninstall_bounded_control(AbletonLiveMCP)\nAbletonObjectMCP = AbletonLiveMCP\n")
write("bridge/ChibiAudioBridge/bridge.py", bridge)

# 3. Python client bounded-write surface.
live = read("src/chibi_audio/live.py")
live = live.replace(
    'BOUNDED_WRITE_METHODS = frozenset({"parameter_set"})',
    'BOUNDED_WRITE_METHODS = frozenset({"parameter_set", "track_mixer_parameter_set", "track_set", "device_parameter_set", "device_enabled_set"})',
)
marker = "@dataclass(slots=True)\nclass LivePilotWriteClient"
idx = live.index(marker)
live_tail = '''@dataclass(slots=True)
class LivePilotWriteClient(_LiveTransport):
    """Narrow, identity-guarded Live mutations. No generic object setter is exposed."""

    def _track_identity(self, *, track_index: int, expected_track_name: str, expected_track_id: int | None = None, expected_set_signature: str | None = None) -> dict[str, Any]:
        if track_index < 0:
            raise LiveBridgeError("track_index must be >= 0")
        if not expected_track_name:
            raise LiveBridgeError("expected_track_name is required")
        params: dict[str, Any] = {"track_index": int(track_index), "expected_track_name": expected_track_name}
        if expected_track_id is not None:
            params["expected_track_id"] = int(expected_track_id)
        if expected_set_signature:
            params["expected_set_signature"] = expected_set_signature
        return params

    def set_track_mixer_parameter(self, parameter: str, *, track_index: int, expected_track_name: str, expected_current_value: float, value: float, expected_track_id: int | None = None, expected_set_signature: str | None = None, verify_capability: bool = True) -> dict[str, Any]:
        if parameter not in {"volume", "panning"}:
            raise LiveBridgeError("track mixer parameter must be volume or panning")
        if verify_capability:
            self._require_method("bounded_write", "track_mixer_parameter_set")
        params = self._track_identity(track_index=track_index, expected_track_name=expected_track_name, expected_track_id=expected_track_id, expected_set_signature=expected_set_signature)
        params.update({"parameter": parameter, "expected_current_value": float(expected_current_value), "value": float(value)})
        return self._request("track_mixer_parameter_set", params)

    def set_track_volume(self, **kwargs) -> dict[str, Any]:
        return self.set_track_mixer_parameter("volume", **kwargs)

    def set_track_pan(self, **kwargs) -> dict[str, Any]:
        return self.set_track_mixer_parameter("panning", **kwargs)

    def set_track_property(self, *, track_index: int, expected_track_name: str, property: str, expected_current_value: Any, value: Any, expected_track_id: int | None = None, expected_set_signature: str | None = None, verify_capability: bool = True) -> dict[str, Any]:
        if property not in {"mute", "solo", "name", "color_index"}:
            raise LiveBridgeError("track property must be mute, solo, name, or color_index")
        if verify_capability:
            self._require_method("bounded_write", "track_set")
        params = self._track_identity(track_index=track_index, expected_track_name=expected_track_name, expected_track_id=expected_track_id, expected_set_signature=expected_set_signature)
        params.update({"property": property, "expected_current_value": expected_current_value, "value": value})
        return self._request("track_set", params)

    def set_device_parameter(self, *, track_index: int, expected_track_name: str, device_index: int, expected_device_name: str, parameter_index: int, expected_parameter_name: str, expected_current_value: float, value: float, expected_track_id: int | None = None, expected_device_id: int | None = None, expected_parameter_id: int | None = None, expected_set_signature: str | None = None, coerce: bool = False, verify_capability: bool = True) -> dict[str, Any]:
        if device_index < 0 or parameter_index < 0:
            raise LiveBridgeError("device_index and parameter_index must be >= 0")
        if not expected_device_name or not expected_parameter_name:
            raise LiveBridgeError("expected device and parameter names are required")
        if verify_capability:
            self._require_method("bounded_write", "device_parameter_set")
        params = self._track_identity(track_index=track_index, expected_track_name=expected_track_name, expected_track_id=expected_track_id, expected_set_signature=expected_set_signature)
        params.update({"device_index": int(device_index), "expected_device_name": expected_device_name, "parameter_index": int(parameter_index), "expected_parameter_name": expected_parameter_name, "expected_current_value": float(expected_current_value), "value": float(value), "coerce": bool(coerce)})
        if expected_device_id is not None:
            params["expected_device_id"] = int(expected_device_id)
        if expected_parameter_id is not None:
            params["expected_parameter_id"] = int(expected_parameter_id)
        return self._request("device_parameter_set", params)

    def set_device_enabled(self, enabled: bool, *, track_index: int, expected_track_name: str, device_index: int, expected_device_name: str, parameter_index: int, expected_parameter_name: str, expected_current_value: float, expected_track_id: int | None = None, expected_device_id: int | None = None, expected_parameter_id: int | None = None, expected_set_signature: str | None = None, verify_capability: bool = True) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise LiveBridgeError("enabled must be a boolean")
        if verify_capability:
            self._require_method("bounded_write", "device_enabled_set")
        params = self._track_identity(track_index=track_index, expected_track_name=expected_track_name, expected_track_id=expected_track_id, expected_set_signature=expected_set_signature)
        params.update({"device_index": int(device_index), "expected_device_name": expected_device_name, "parameter_index": int(parameter_index), "expected_parameter_name": expected_parameter_name, "expected_current_value": float(expected_current_value), "enabled": enabled})
        if expected_device_id is not None:
            params["expected_device_id"] = int(expected_device_id)
        if expected_parameter_id is not None:
            params["expected_parameter_id"] = int(expected_parameter_id)
        return self._request("device_enabled_set", params)
'''
write("src/chibi_audio/live.py", live[:idx] + live_tail)

# 4. Reversible audition + parameter-diff helpers.
write(
    "src/chibi_audio/control.py",
    '''from __future__ import annotations

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
        tracks.append({"index": index, "name": name, "id": raw.get("id"), "mute": bool(raw["mute"]), "solo": bool(raw["solo"])})
    if not tracks:
        raise ControlPlanError("set summary contains no usable tracks")
    return {"set_signature": set_summary.get("set_signature"), "tracks": tracks}


def build_audition_plan(snapshot: dict[str, Any], *, solo_track_indices: Iterable[int] = (), mute_track_indices: Iterable[int] = ()) -> dict[str, Any]:
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
            apply.append({**common, "property": prop, "expected_current_value": before, "value": desired})
            restore.append({**common, "property": prop, "expected_current_value": desired, "value": before})
    return {"set_signature": snapshot.get("set_signature"), "apply": apply, "restore": list(reversed(restore)), "requested": {"solo_track_indices": sorted(solo), "mute_track_indices": sorted(mute)}}


def parameter_snapshot(*, track_index: int, track_name: str, device_index: int, device_name: str, device_id: int | None, parameters: list[dict[str, Any]], set_signature: str | None = None) -> dict[str, Any]:
    items = []
    for index, parameter in enumerate(parameters):
        if parameter.get("truncated"):
            continue
        items.append({"index": index, "id": parameter.get("id"), "name": parameter.get("name", ""), "value": parameter.get("value"), "display": parameter.get("display", parameter.get("display_value"))})
    return {"set_signature": set_signature, "track": {"index": int(track_index), "name": track_name}, "device": {"index": int(device_index), "name": device_name, "id": device_id}, "parameters": items}


def diff_parameter_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    if before.get("track") != after.get("track") or before.get("device") != after.get("device"):
        raise ControlPlanError("cannot diff snapshots from different track/device identities")
    def key(item):
        return ("id", int(item["id"])) if item.get("id") is not None else ("index_name", int(item.get("index", -1)), str(item.get("name") or ""))
    left = {key(item): item for item in before.get("parameters") or []}
    right = {key(item): item for item in after.get("parameters") or []}
    changes = []
    for item_key in sorted(set(left) | set(right), key=str):
        a, b = left.get(item_key), right.get(item_key)
        if a is None or b is None:
            changes.append({"key": item_key, "before": a, "after": b})
        elif a.get("value") != b.get("value") or a.get("display") != b.get("display"):
            changes.append({"key": item_key, "name": b.get("name") or a.get("name"), "before_value": a.get("value"), "after_value": b.get("value"), "before_display": a.get("display"), "after_display": b.get("display")})
    return changes
''',
)

# 5. MCP-ready transport-agnostic facade.
write(
    "src/chibi_audio/facade.py",
    '''from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .live import LiveBridgeClient, LivePilotWriteClient

TOOL_NAMES = (
    "status", "project_snapshot", "device_parameters", "track_mixer_state",
    "set_track_volume", "set_track_pan", "set_track_property", "set_device_parameter", "set_device_enabled",
)


@dataclass(slots=True)
class ChibiAudioFacade:
    """Transport-agnostic tool facade intended to sit behind a secure MCP/connector."""
    read: LiveBridgeClient
    write: LivePilotWriteClient

    @classmethod
    def local(cls, host: str = "127.0.0.1", port: int = 18765) -> "ChibiAudioFacade":
        return cls(LiveBridgeClient(host=host, port=port), LivePilotWriteClient(host=host, port=port))

    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "status": lambda _a: self.read.status(),
            "project_snapshot": lambda a: self.read.set_summary(track_limit=int(a.get("track_limit", 140)), device_limit=int(a.get("device_limit", 24))),
            "device_parameters": lambda a: self.read.call("device_parameters", {"ref": {"id": int(a["device_id"])}, "limit": int(a.get("limit", 256))}),
            "track_mixer_state": self._track_mixer_state,
            "set_track_volume": lambda a: self.write.set_track_volume(**a),
            "set_track_pan": lambda a: self.write.set_track_pan(**a),
            "set_track_property": lambda a: self.write.set_track_property(**a),
            "set_device_parameter": lambda a: self.write.set_device_parameter(**a),
            "set_device_enabled": lambda a: self.write.set_device_enabled(**a),
        }
        if name not in handlers:
            raise KeyError(f"Unknown Chibi Audio facade tool: {name}")
        return handlers[name](args)

    def _track_mixer_state(self, args: dict[str, Any]) -> dict[str, Any]:
        index = int(args["track_index"])
        result = {}
        for name in ("volume", "panning"):
            result[name] = self.read.call("get", {"ref": {"path": f"song tracks {index} mixer_device {name}"}, "properties": ["name", "value", "min", "max", "display_value"]})
        return {"track_index": index, "mixer": result}
''',
)

# 6. Immediate offline high-end event analysis.
write(
    "src/chibi_audio/harshness.py",
    '''from __future__ import annotations

from pathlib import Path
from typing import Any

from .audio import AudioAnalysisError, _db, _np, decode_audio


def _scale(values):
    np = _np()
    values = np.asarray(values, dtype=np.float64)
    lo = float(np.percentile(values, 10.0))
    hi = float(np.percentile(values, 95.0))
    if hi <= lo + 1e-12:
        return np.zeros_like(values)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def analyze_harshness_array(audio, sample_rate: int, *, frame_ms: float = 50.0, hop_ms: float = 10.0, top_events: int = 12, min_event_gap_ms: float = 80.0) -> dict[str, Any]:
    """Rank bright/attack-heavy moments; this is a relative diagnostic proxy, not a quality score."""
    np = _np()
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 2:
        mono = np.mean(data, axis=1)
    elif data.ndim == 1:
        mono = data
    else:
        raise AudioAnalysisError("harshness analysis expects mono or stereo audio")
    if len(mono) < 8:
        raise AudioAnalysisError("audio is too short for harshness analysis")
    frame = min(len(mono), max(64, int(round(frame_ms * sample_rate / 1000.0))))
    hop = max(1, int(round(hop_ms * sample_rate / 1000.0)))
    starts = np.arange(0, max(1, len(mono) - frame + 1), hop, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)
    window = np.hanning(frame).astype(np.float64)
    freqs = np.fft.rfftfreq(frame, d=1.0 / float(sample_rate))
    audible = (freqs >= 20.0) & (freqs < min(20000.0, sample_rate / 2.0))
    high = (freqs >= 6000.0) & (freqs < min(20000.0, sample_rate / 2.0))
    air = (freqs >= 12000.0) & (freqs < min(20000.0, sample_rate / 2.0))
    perceptual_weight = np.zeros_like(freqs)
    mask = freqs >= 1000.0
    perceptual_weight[mask] = np.sqrt(freqs[mask] / 1000.0)
    rms, crest, centroid, high_pct, air_pct, sharp = [], [], [], [], [], []
    for start in starts:
        chunk = mono[int(start):int(start) + frame]
        if len(chunk) < frame:
            chunk = np.pad(chunk, (0, frame - len(chunk)))
        r = float(np.sqrt(np.mean(chunk * chunk)))
        peak = float(np.max(np.abs(chunk)))
        power = np.abs(np.fft.rfft(chunk * window)) ** 2
        total = float(power[audible].sum())
        if total > 1e-24:
            c = float((freqs[audible] * power[audible]).sum() / total)
            hp = 100.0 * float(power[high].sum() / total)
            ap = 100.0 * float(power[air].sum() / total)
            sp = float((power[audible] * perceptual_weight[audible]).sum() / total)
        else:
            c = hp = ap = sp = 0.0
        rms.append(r); crest.append(_db(peak) - _db(r)); centroid.append(c); high_pct.append(hp); air_pct.append(ap); sharp.append(sp)
    rms_db = np.asarray([_db(float(value)) for value in rms])
    crest = np.asarray(crest); centroid = np.asarray(centroid); high_pct = np.asarray(high_pct); air_pct = np.asarray(air_pct); sharp = np.asarray(sharp)
    attack = np.maximum(0.0, np.diff(rms_db, prepend=rms_db[0]))
    activity = _scale(rms_db)
    score = activity * (0.30 * _scale(high_pct) + 0.25 * _scale(centroid) + 0.20 * _scale(sharp) + 0.15 * _scale(attack) + 0.10 * _scale(crest))
    gap = max(1, int(round(min_event_gap_ms / hop_ms)))
    selected = []
    for raw in np.argsort(score)[::-1]:
        idx = int(raw)
        if float(score[idx]) <= 0:
            break
        if any(abs(idx - other) < gap for other in selected):
            continue
        selected.append(idx)
        if len(selected) >= top_events:
            break
    events = [{"start_s": float(starts[i]) / sample_rate, "end_s": min(len(mono), int(starts[i]) + frame) / sample_rate, "score": float(score[i]), "rms_dbfs": float(rms_db[i]), "crest_db": float(crest[i]), "spectral_centroid_hz": float(centroid[i]), "high_6_20k_pct": float(high_pct[i]), "air_12_20k_pct": float(air_pct[i]), "attack_db": float(attack[i]), "sharpness_proxy": float(sharp[i])} for i in selected]
    active = rms_db > max(-80.0, float(np.percentile(rms_db, 20.0)))
    def stat(values, q):
        return float(np.percentile(values[active], q)) if np.any(active) else 0.0
    return {"sample_rate": int(sample_rate), "duration_s": len(mono) / float(sample_rate), "frame_ms": float(frame_ms), "hop_ms": float(hop_ms), "metric_status": "relative_diagnostic_proxy_not_standardized_harshness", "summary": {"median_centroid_hz": stat(centroid, 50), "p95_centroid_hz": stat(centroid, 95), "median_high_6_20k_pct": stat(high_pct, 50), "p95_high_6_20k_pct": stat(high_pct, 95), "median_sharpness_proxy": stat(sharp, 50), "p95_sharpness_proxy": stat(sharp, 95)}, "events": events}


def analyze_harshness(path: str | Path, sample_rate: int = 48000, **kwargs) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise AudioAnalysisError(f"Audio file does not exist: {source}")
    result = analyze_harshness_array(decode_audio(source, sample_rate=sample_rate), sample_rate, **kwargs)
    result["path"] = str(source)
    return result


def compare_harshness_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for label, report in reports.items():
        summary = report.get("summary") or {}
        top = (report.get("events") or [{}])[0]
        rows.append({"label": label, "p95_high_6_20k_pct": float(summary.get("p95_high_6_20k_pct", 0.0)), "p95_centroid_hz": float(summary.get("p95_centroid_hz", 0.0)), "p95_sharpness_proxy": float(summary.get("p95_sharpness_proxy", 0.0)), "top_event_score": float(top.get("score", 0.0)), "top_event_start_s": top.get("start_s")})
    rows.sort(key=lambda row: (row["top_event_score"], row["p95_sharpness_proxy"], row["p95_high_6_20k_pct"]), reverse=True)
    return {"ranking": rows, "warning": "Relative diagnostic evidence only; artist listening remains authoritative."}
''',
)

# 7. CLI.
cli = read("src/chibi_audio/cli.py")
if "from .harshness import analyze_harshness" not in cli:
    cli = cli.replace("from .audio import analyze_audio\n", "from .audio import analyze_audio\nfrom .harshness import analyze_harshness\n")
if "analyze-harshness" not in cli:
    cli = cli.replace('    audio.add_argument("--window-seconds", type=float, default=12.0)\n', '    audio.add_argument("--window-seconds", type=float, default=12.0)\n\n    harshness = sub.add_parser("analyze-harshness", help="Rank time-localized bright/attack-heavy events")\n    harshness.add_argument("path")\n    harshness.add_argument("--top-events", type=int, default=12)\n')
    cli = cli.replace('    elif args.command == "analyze-audio":\n        print(json.dumps(analyze_audio(args.path, window_seconds=args.window_seconds), indent=2, ensure_ascii=False))\n', '    elif args.command == "analyze-audio":\n        print(json.dumps(analyze_audio(args.path, window_seconds=args.window_seconds), indent=2, ensure_ascii=False))\n    elif args.command == "analyze-harshness":\n        print(json.dumps(analyze_harshness(args.path, top_events=args.top_events), indent=2, ensure_ascii=False))\n')
write("src/chibi_audio/cli.py", cli)

# 8. Tests.
write("tests/test_control.py", '''import pytest\n\nfrom chibi_audio.control import ControlPlanError, build_audition_plan, diff_parameter_snapshots, parameter_snapshot, snapshot_track_controls\n\n\ndef _summary():\n    return {"set_signature": "sig-1", "tracks": [{"index": 0, "id": 100, "name": "Kick", "mute": False, "solo": False}, {"index": 1, "id": 101, "name": "Bass", "mute": False, "solo": True}, {"index": 2, "id": 102, "name": "Hats", "mute": True, "solo": False}]}\n\n\ndef test_audition_plan_restores_exact_prior_state():\n    plan = build_audition_plan(snapshot_track_controls(_summary()), solo_track_indices=[2])\n    apply = {(item["track_index"], item["property"]): item for item in plan["apply"]}\n    restore = {(item["track_index"], item["property"]): item for item in plan["restore"]}\n    assert apply[(1, "solo")]["value"] is False\n    assert apply[(2, "solo")]["value"] is True\n    assert restore[(1, "solo")]["expected_current_value"] is False\n    assert restore[(1, "solo")]["value"] is True\n    assert restore[(2, "solo")]["expected_current_value"] is True\n\n\ndef test_audition_plan_rejects_unknown_track():\n    with pytest.raises(ControlPlanError, match="unknown track indices"):\n        build_audition_plan(snapshot_track_controls(_summary()), solo_track_indices=[99])\n\n\ndef test_parameter_diff_reports_only_changes():\n    before = parameter_snapshot(track_index=1, track_name="Bass", device_index=0, device_name="Saturn 2", device_id=200, parameters=[{"id": 1, "name": "Mix", "value": 0.5, "display": "50%"}, {"id": 2, "name": "Drive", "value": 0.2, "display": "20%"}])\n    after = parameter_snapshot(track_index=1, track_name="Bass", device_index=0, device_name="Saturn 2", device_id=200, parameters=[{"id": 1, "name": "Mix", "value": 0.4, "display": "40%"}, {"id": 2, "name": "Drive", "value": 0.2, "display": "20%"}])\n    changes = diff_parameter_snapshots(before, after)\n    assert len(changes) == 1\n    assert changes[0]["name"] == "Mix"\n''')

write("tests/test_harshness.py", '''import numpy as np\n\nfrom chibi_audio.harshness import analyze_harshness_array, compare_harshness_reports\n\n\ndef test_harshness_ranking_finds_bright_transient_burst():\n    sr = 48000\n    t = np.arange(sr * 2) / sr\n    signal = 0.08 * np.sin(2.0 * np.pi * 500.0 * t)\n    start, end = sr, sr + int(0.06 * sr)\n    bt = np.arange(end - start) / sr\n    signal[start:end] += 0.7 * np.sin(2.0 * np.pi * 9000.0 * bt) * np.hanning(end - start)\n    report = analyze_harshness_array(np.column_stack([signal, signal]), sr, top_events=4)\n    assert report["metric_status"].startswith("relative_diagnostic")\n    assert report["events"]\n    assert 0.90 <= report["events"][0]["start_s"] <= 1.08\n    assert report["events"][0]["high_6_20k_pct"] > 10.0\n\n\ndef test_harshness_comparison_is_relative():\n    a = {"summary": {"p95_high_6_20k_pct": 1, "p95_centroid_hz": 1000, "p95_sharpness_proxy": 1}, "events": [{"score": 0.2, "start_s": 0.5}]}\n    b = {"summary": {"p95_high_6_20k_pct": 20, "p95_centroid_hz": 7000, "p95_sharpness_proxy": 3}, "events": [{"score": 0.9, "start_s": 1.0}]}\n    result = compare_harshness_reports({"quiet": a, "bright": b})\n    assert result["ranking"][0]["label"] == "bright"\n    assert "Relative diagnostic" in result["warning"]\n''')

write("tests/test_bounded_control.py", '''from bridge.ChibiAudioBridge import bounded_control\n\n\nclass Parameter:\n    def __init__(self, name, value, minimum=0.0, maximum=1.0):\n        self.name = name; self.value = value; self.min = minimum; self.max = maximum; self.is_quantized = False\n\n\nclass Mixer:\n    def __init__(self):\n        self.volume = Parameter("Volume", 0.8); self.panning = Parameter("Pan", 0.0, -1.0, 1.0)\n\n\nclass Device:\n    def __init__(self):\n        self.name = "soothe2"; self.parameters = [Parameter("Device On", 1.0), Parameter("Depth", 0.25)]\n\n\nclass Track:\n    def __init__(self):\n        self.name = "Hats"; self.mute = False; self.solo = False; self.color_index = 3; self.mixer_device = Mixer(); self.devices = [Device()]\n\n\nclass Song:\n    def __init__(self): self.tracks = [Track()]\n\n\nclass FakeBridge:\n    def __init__(self): self._song = Song()\n    def song(self): return self._song\n    def _object_id(self, obj): return id(obj)\n    def _parameter_summary(self, p): return {"id": id(p), "name": p.name, "value": p.value, "min": p.min, "max": p.max, "is_quantized": p.is_quantized}\n\n\ndef test_mixer_write_checks_before_state_and_reads_back():\n    bridge = FakeBridge(); track = bridge.song().tracks[0]\n    result = bounded_control.rpc_track_mixer_parameter_set(bridge, {"track_index": 0, "expected_track_name": "Hats", "expected_track_id": id(track), "parameter": "panning", "expected_current_value": 0.0, "value": -0.1})\n    assert result["read_back_verified"] is True\n    assert track.mixer_device.panning.value == -0.1\n\n\ndef test_device_parameter_write_uses_exact_identities():\n    bridge = FakeBridge(); track = bridge.song().tracks[0]; device = track.devices[0]; parameter = device.parameters[1]\n    result = bounded_control.rpc_device_parameter_set(bridge, {"track_index": 0, "expected_track_name": "Hats", "expected_track_id": id(track), "device_index": 0, "expected_device_name": "soothe2", "expected_device_id": id(device), "parameter_index": 1, "expected_parameter_name": "Depth", "expected_parameter_id": id(parameter), "expected_current_value": 0.25, "value": 0.30})\n    assert result["applied_value"] == 0.30\n''')

live_tests = read("tests/test_live.py")
live_tests = live_tests.replace('"bounded_write": ["parameter_set"]', '"bounded_write": list(BOUNDED_WRITE_METHODS)')
if "test_extended_bounded_write_requests" not in live_tests:
    live_tests += '''\n\ndef test_extended_bounded_write_requests():\n    client = FakeWriteClient()\n    result = client.set_track_pan(track_index=4, expected_track_name="Hats", expected_track_id=444, expected_current_value=0.0, value=-0.1, expected_set_signature="sig-x")\n    assert result["method"] == "track_mixer_parameter_set"\n    assert client.calls[-1][1]["parameter"] == "panning"\n    prop = client.set_track_property(track_index=4, expected_track_name="Hats", property="solo", expected_current_value=False, value=True)\n    assert prop["method"] == "track_set"\n    parameter = client.set_device_parameter(track_index=4, expected_track_name="Hats", device_index=2, expected_device_name="soothe2", expected_device_id=222, parameter_index=5, expected_parameter_name="Depth", expected_parameter_id=555, expected_current_value=0.25, value=0.30)\n    assert parameter["method"] == "device_parameter_set"\n'''
write("tests/test_live.py", live_tests)

# 9. Docs / roadmap.
write("docs/control-plane.md", '''# Typed Ableton control plane\n\nTracked by issue #6.\n\nChibi Audio should make normal production work through explicit structured capabilities rather than mouse/keyboard automation. The Live Remote Script remains localhost-only; a separate facade exposes only reviewed tools to an MCP/connector transport.\n\nThe write contract is `fresh observation -> exact identity -> expected before-state -> bounded mutation -> read-back verification`. A missing capability is an engineering task, never permission for silent CUA fallback.\n\nThe initial generalized surface includes exact track volume/pan, mute/solo, rename/recolor, exact exposed device parameters, and guarded enable/bypass only when the exact host-exposed on/off parameter is identified. Track/device/parameter IDs can supplement names so stale indices fail closed. Generic setters, arbitrary Live calls and Python/eval remain unexposed.\n\n`chibi_audio.control` builds reversible audition plans such as hats-only or bass-only from a fresh snapshot. Planning itself does not mutate Live. Apply and restore operations each include expected before-state, so restoration refuses if a human or another worker changed the Set in the meantime.\n\nParameter snapshots/diffs provide durable experiment provenance instead of relying on chat history. `chibi_audio.facade.ChibiAudioFacade` is the transport-agnostic model-facing boundary intended to sit behind a secure MCP endpoint; it does not expose raw Live JSON-RPC.\n\nThis lane does not exercise live mutations while another worker owns the active KISS Set. Host-independent tests land first; a coordinated disposable live proof follows.\n''')

contract = read("docs/connection-contract.md")
old = '''Pilot writes must have exact identity and before-state preconditions. The first implemented write is exact track-volume mutation using:\n- track index;\n- expected current track name;\n- expected current raw value;\n- requested new value.\nA mismatch refuses the operation. Generic setters, arbitrary calls and arbitrary Python execution are not exposed.'''
new = '''Pilot writes must have exact identity and before-state preconditions. The bounded pilot surface now covers exact track volume/pan, mute/solo/name/color, and exact exposed device parameters. Writes require freshly observed identity plus expected before-state and verify the value after mutation. Optional Set-signature and object-id guards make stale indices fail closed. Device enable/bypass is a named bounded operation only when the exact host-exposed on/off parameter is identified. Generic setters, arbitrary calls and arbitrary Python execution are not exposed.\n\nSee [control-plane.md](control-plane.md) for the model-facing facade, reversible audition-plan and parameter snapshot/diff contract.'''
contract = contract.replace(old, new)
write("docs/connection-contract.md", contract)

roadmap = read("docs/roadmap.md")
if "## R1.75 - Typed Ableton control" not in roadmap:
    section = '''## R1.75 - Typed Ableton control and diagnostic audition plane - ACTIVE\nTracked by [#6](https://github.com/akimbo-bin/chibi-audio/issues/6).\n\nParallel to ChibiTap audio capture, remove routine CUA by expanding the narrow Live bridge into explicit effect-certain controls for track volume/pan, mute/solo, rename/recolor and exact exposed device parameters. Add parameter snapshots/diffs, reversible audition plans, and a transport-agnostic facade ready for a secure MCP endpoint without exposing raw Live JSON-RPC.\n\nIn the same lane, add an immediately useful offline high-end diagnostic that ranks time-localized bright/attack-heavy events using inspectable spectral/transient evidence. It is a diagnostic proxy, not an autonomous quality score, and can operate on existing KISS renders without touching the live Set.\n\nNo generic Live setter, arbitrary Python/eval, or silent GUI fallback is allowed.\n\n**Acceptance:** common bounded mix adjustments have a typed path; audition/restore and parameter diffs are deterministic; the high-end analyzer localizes synthetic and real events; and the capability surface is ready for an MCP transport. Live mutation proof is coordinated separately so this lane does not collide with an active Set owner.\n\n'''
    roadmap = roadmap.replace("## R2 - First reversible organization edit\n", section + "## R2 - First reversible organization edit\n")
write("docs/roadmap.md", roadmap)

# Remove this staging helper from the real implementation diff.
Path(__file__).unlink()
print("control lane patch applied")
