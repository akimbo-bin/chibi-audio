from __future__ import absolute_import, print_function

BOUNDED_CONTROL_METHODS = (
    "track_mixer_parameter_set",
    "track_set",
    "track_presentation_batch_set",
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


PRESENTATION_TRACK_PROPERTIES = ("name", "color_index", "fold_state", "is_collapsed")
TRACK_SET_PROPERTIES = ("mute", "solo") + PRESENTATION_TRACK_PROPERTIES


def _track_property_value(track, prop):
    if prop == "is_collapsed":
        return bool(getattr(track.view, "is_collapsed"))
    return getattr(track, prop)


def _validate_track_property(track, prop, expected, value):
    if prop not in TRACK_SET_PROPERTIES:
        raise ValueError("track property must be mute, solo, name, color_index, fold_state, or is_collapsed")
    if prop in ("mute", "solo", "is_collapsed") and (type(value) is not bool or type(expected) is not bool):
        raise ValueError("mute/solo/is_collapsed values must be booleans")
    if prop == "name" and (not isinstance(value, str) or not value.strip()):
        raise ValueError("track name must be non-empty")
    if prop == "color_index" and (type(value) is not int or value < 0):
        raise ValueError("color_index must be a non-negative integer")
    if prop == "fold_state":
        if type(value) is not int or value not in (0, 1) or type(expected) is not int:
            raise ValueError("fold_state values must be integer 0 or 1")
        if not bool(getattr(track, "is_foldable", False)):
            raise ValueError("fold_state is only valid for foldable group tracks")


def _write_track_property(track, prop, value):
    target = track.view if prop == "is_collapsed" else track
    setattr(target, prop, value)
    after = _track_property_value(track, prop)
    if after != value:
        raise RuntimeError("Track property write did not read back as requested")
    return after


def rpc_track_set(self, params):
    track_index, track, track_id = _track(self, params)
    prop = params.get("property")
    if "expected_current_value" not in params:
        raise ValueError("expected_current_value is required")
    expected = params.get("expected_current_value")
    value = params.get("value")
    _validate_track_property(track, prop, expected, value)
    before = _track_property_value(track, prop)
    if before != expected:
        raise RuntimeError("Track property changed since inspection; refusing write")
    after = _write_track_property(track, prop, value)
    return {
        "track": {"index": track_index, "id": track_id, "name": getattr(track, "name", "")},
        "property": prop,
        "before": before,
        "requested_value": value,
        "applied_value": after,
        "changed": after != before,
        "read_back_verified": True,
    }


def rpc_track_presentation_batch_set(self, params):
    edits = params.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must be a non-empty list")
    if len(edits) > 256:
        raise ValueError("presentation batch is limited to 256 edits")

    resolved = []
    seen = set()
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError("each presentation edit must be an object")
        track_index, track, track_id = _track(self, edit)
        prop = edit.get("property")
        if prop not in PRESENTATION_TRACK_PROPERTIES:
            raise ValueError("presentation batch only supports name, color_index, fold_state, or is_collapsed")
        key = (track_id, prop)
        if key in seen:
            raise ValueError("presentation batch contains duplicate track/property edits")
        seen.add(key)
        if "expected_current_value" not in edit:
            raise ValueError("expected_current_value is required for every presentation edit")
        expected = edit.get("expected_current_value")
        value = edit.get("value")
        _validate_track_property(track, prop, expected, value)
        before = _track_property_value(track, prop)
        if before != expected:
            raise RuntimeError("Track property changed since inspection; refusing presentation batch")
        resolved.append({
            "track_index": track_index,
            "track": track,
            "track_id": track_id,
            "property": prop,
            "before": before,
            "value": value,
        })

    ordered = [item for item in resolved if item["property"] != "name"]
    ordered.extend(item for item in resolved if item["property"] == "name")
    attempted = []
    operations = []
    try:
        for item in ordered:
            attempted.append(item)
            after = _write_track_property(item["track"], item["property"], item["value"])
            operations.append({
                "track": {
                    "index": item["track_index"],
                    "id": item["track_id"],
                    "name": getattr(item["track"], "name", ""),
                },
                "property": item["property"],
                "before": item["before"],
                "requested_value": item["value"],
                "applied_value": after,
                "changed": after != item["before"],
                "read_back_verified": True,
            })
    except Exception as exc:
        rollback_errors = []
        for item in reversed(attempted):
            try:
                restored = _write_track_property(item["track"], item["property"], item["before"])
                if restored != item["before"]:
                    raise RuntimeError("rollback read-back mismatch")
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise RuntimeError(
                "Presentation batch failed and rollback was incomplete; effect state is UNKNOWN: %s; rollback errors: %s"
                % (exc, "; ".join(rollback_errors))
            )
        raise RuntimeError("Presentation batch failed and was rolled back exactly: %s" % exc)

    return {
        "effect_state": "STARTED_CONFIRMED",
        "rollback_performed": False,
        "operation_count": len(operations),
        "changed_count": sum(1 for item in operations if item["changed"]),
        "operations": operations,
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
    cls._rpc_track_presentation_batch_set = rpc_track_presentation_batch_set
    cls._rpc_device_parameter_set = rpc_device_parameter_set
    cls._rpc_device_enabled_set = rpc_device_enabled_set
    return cls
