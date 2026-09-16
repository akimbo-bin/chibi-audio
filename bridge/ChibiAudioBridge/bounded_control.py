from __future__ import absolute_import, print_function

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


def _device_target(self, params):
    placement = params.get("placement", "track")
    if placement == "track":
        index, track, track_id = _track(self, params)
        return {
            "placement": "track",
            "index": index,
            "id": track_id,
            "name": getattr(track, "name", ""),
        }, track
    if placement != "master":
        raise ValueError("placement must be track or master")
    if params.get("track_index") is not None:
        raise ValueError("track_index must be omitted for placement=master")
    track = self.song().master_track
    expected_name = params.get("expected_track_name")
    if not expected_name or getattr(track, "name", "") != expected_name:
        raise RuntimeError("Track identity mismatch for bounded write")
    track_id = self._object_id(track)
    expected_id = params.get("expected_track_id")
    if expected_id is not None and int(expected_id) != track_id:
        raise RuntimeError("Track object identity changed since inspection; refusing write")
    return {
        "placement": "master",
        "index": None,
        "id": track_id,
        "name": getattr(track, "name", ""),
    }, track


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
    track_summary, track = _device_target(self, params)
    device_index, device, device_id = _device(self, track, params)
    parameter_index, parameter, parameter_id = _parameter(self, device, params)
    result = _write_parameter(self, parameter, params)
    result["track"] = track_summary
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
