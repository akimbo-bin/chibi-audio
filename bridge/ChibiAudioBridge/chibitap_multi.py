from __future__ import absolute_import, print_function


_SIGNAL_POINT_MISMATCH_PREFIX = "ChibiTap signal-point mismatch:"


def _named_chibitaps(self, track):
    return [
        (index, device)
        for index, device in enumerate(list(getattr(track, "devices", [])))
        if getattr(device, "name", "") == "ChibiTap"
    ]


def _chibitaps_at_signal_point(self, track, signal_point):
    matches = []
    for _index, device in _named_chibitaps(self, track):
        try:
            verified_index = self._chibitap_signal_point_index(track, device, signal_point)
        except RuntimeError as exc:
            if str(exc).startswith(_SIGNAL_POINT_MISMATCH_PREFIX):
                continue
            raise
        matches.append((verified_index, device))
    return matches


def _chibitap_by_expected_id(self, track, expected_device_id, signal_point, operation):
    if expected_device_id is None:
        raise ValueError("expected_device_id is required for ChibiTap %s" % operation)
    expected_device_id = int(expected_device_id)
    matches = [
        (index, device)
        for index, device in _named_chibitaps(self, track)
        if self._object_id(device) == expected_device_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Expected ChibiTap device %s is no longer present exactly once; refusing %s"
            % (expected_device_id, operation)
        )
    _observed_index, device = matches[0]
    verified_index = self._chibitap_signal_point_index(track, device, signal_point)
    return verified_index, device


def _delete_exact_device(self, track, device):
    devices = list(getattr(track, "devices", []))
    matches = [
        index
        for index, candidate in enumerate(devices)
        if self._same_live_object(candidate, device)
    ]
    if len(matches) != 1:
        raise RuntimeError("ChibiTap device could not be reconciled for rollback/removal")
    if not hasattr(track, "delete_device"):
        raise RuntimeError("Target track does not expose delete_device")
    track.delete_device(matches[0])


def _rpc_chibitap_setup(self, params):
    track, track_ref = self._chibitap_target_track(params)
    signal_point = str(params.get("signal_point") or "post_fx")

    at_point = _chibitaps_at_signal_point(self, track, signal_point)
    if len(at_point) > 1:
        raise RuntimeError(
            "Multiple ChibiTap instances occupy signal point %s on %s; refusing ambiguous setup"
            % (signal_point, getattr(track, "name", ""))
        )

    loaded = False
    if at_point:
        device_index, device = at_point[0]
    else:
        insert_index = self._chibitap_signal_point_insert_index(track, signal_point)
        before_ids = set(
            self._object_id(device)
            for device in getattr(track, "devices", [])
        )
        result = self._rpc_load_device({
            "name": "ChibiTap",
            "name_exact": True,
            "roots": ["plugins"],
            "target_track": track_ref,
            "max_depth": 12,
            "max_visited": 20000,
        })
        if result.get("ambiguous"):
            raise RuntimeError("ChibiTap browser lookup was ambiguous")
        if not result.get("loaded"):
            raise RuntimeError("ChibiTap browser load did not report a loaded device")
        loaded = True

        new_id = (result.get("device") or {}).get("id")
        device = None
        if new_id is not None:
            new_id = int(new_id)
            candidates = [
                candidate
                for candidate in getattr(track, "devices", [])
                if self._object_id(candidate) == new_id
            ]
            if len(candidates) == 1:
                device = candidates[0]
        if device is None:
            device = self._find_new_track_device(track, before_ids)
        if device is None or getattr(device, "name", "") != "ChibiTap":
            raise RuntimeError("Fresh ChibiTap load could not be reconciled by device identity")

        try:
            if signal_point != "post_fx":
                self.song().move_device(device, track, insert_index)
            device_index = self._chibitap_signal_point_index(track, device, signal_point)
        except Exception:
            try:
                _delete_exact_device(self, track, device)
            except Exception:
                pass
            raise

    pmap = self._chibitap_parameter_map(device)
    if "Capture" not in pmap or "Tap ID" not in pmap:
        if loaded:
            _delete_exact_device(self, track, device)
        raise RuntimeError("ChibiTap does not expose the required 0.2.0 Capture + Tap ID layout")
    capture_summary = self._parameter_summary(pmap["Capture"])
    if abs(float(capture_summary.get("value"))) > 1e-6:
        if loaded:
            _delete_exact_device(self, track, device)
        raise RuntimeError("ChibiTap Capture must be Off after setup")

    all_taps = _named_chibitaps(self, track)
    return {
        "loaded": loaded,
        "reused": not loaded,
        "signal_point": signal_point,
        "device_index": device_index,
        "chibitap_count": len(all_taps),
        "track": {
            "id": self._object_id(track),
            "name": getattr(track, "name", ""),
        },
        "device": {
            "id": self._object_id(device),
            "name": "ChibiTap",
        },
        "parameters": {
            "Capture": capture_summary,
            "Tap ID": self._parameter_summary(pmap["Tap ID"]),
            "tap_id_integer": int(round(float(getattr(pmap["Tap ID"], "value", 0.0)) * 9999.0)),
        },
    }


def _rpc_chibitap_configure(self, params):
    track, _track_ref = self._chibitap_target_track(params)
    signal_point = str(params.get("signal_point") or "post_fx")
    device_index, device = _chibitap_by_expected_id(
        self,
        track,
        params.get("expected_device_id"),
        signal_point,
        "configure",
    )
    device_id = self._object_id(device)

    pmap = self._chibitap_parameter_map(device)
    if "Capture" not in pmap or "Tap ID" not in pmap:
        raise RuntimeError("ChibiTap does not expose the required 0.2.0 Capture + Tap ID layout")
    capture = pmap["Capture"]
    tap = pmap["Tap ID"]
    before_capture = self._parameter_summary(capture)
    before_tap = self._parameter_summary(tap)
    changed = False

    if params.get("tap_id") is not None:
        requested = int(params.get("tap_id"))
        expected = params.get("expected_tap_id")
        expected_capture_enabled = params.get("expected_capture_enabled")
        if expected is None:
            raise ValueError("expected_tap_id is required when changing tap_id")
        if expected_capture_enabled is not False:
            raise ValueError("changing tap_id requires expected_capture_enabled=false")
        if float(before_capture.get("value")) >= 0.5:
            raise RuntimeError("ChibiTap Capture must be Off before changing Tap ID")
        if requested < 0 or requested > 9999:
            raise ValueError("tap_id must be between 0 and 9999")
        current = int(round(float(before_tap.get("value")) * 9999.0))
        if current != int(expected):
            raise RuntimeError("ChibiTap Tap ID changed since inspection; refusing configure")
        tap.value = float(requested) / 9999.0
        applied = int(round(float(getattr(tap, "value", 0.0)) * 9999.0))
        if applied != requested:
            raise RuntimeError("ChibiTap Tap ID did not settle on the requested integer")
        changed = changed or requested != current

    if params.get("capture_enabled") is not None:
        enabled = params.get("capture_enabled")
        expected_enabled = params.get("expected_capture_enabled")
        if type(enabled) is not bool or type(expected_enabled) is not bool:
            raise ValueError("capture_enabled and expected_capture_enabled must be booleans")
        current_enabled = float(before_capture.get("value")) >= 0.5
        if current_enabled != expected_enabled:
            raise RuntimeError("ChibiTap Capture changed since inspection; refusing configure")
        capture.value = 1.0 if enabled else 0.0
        changed = changed or enabled != current_enabled

    after_capture = self._parameter_summary(capture)
    after_tap = self._parameter_summary(tap)
    return {
        "signal_point": signal_point,
        "device_index": device_index,
        "chibitap_count": len(_named_chibitaps(self, track)),
        "track": {
            "id": self._object_id(track),
            "name": getattr(track, "name", ""),
        },
        "device": {
            "id": device_id,
            "name": "ChibiTap",
        },
        "before": {
            "Capture": before_capture,
            "Tap ID": before_tap,
        },
        "parameters": {
            "Capture": after_capture,
            "Tap ID": after_tap,
            "tap_id_integer": int(round(float(after_tap.get("value")) * 9999.0)),
        },
        "changed": changed,
    }


def _rpc_chibitap_remove(self, params):
    track, _track_ref = self._chibitap_target_track(params)
    signal_point = str(params.get("signal_point") or "post_fx")
    device_index, device = _chibitap_by_expected_id(
        self,
        track,
        params.get("expected_device_id"),
        signal_point,
        "remove",
    )
    device_id = self._object_id(device)

    if params.get("expected_capture_enabled") is not False:
        raise ValueError("chibitap_remove requires expected_capture_enabled=false")
    pmap = self._chibitap_parameter_map(device)
    capture = pmap.get("Capture")
    if capture is None:
        raise RuntimeError("ChibiTap Capture parameter is unavailable")
    capture_summary = self._parameter_summary(capture)
    if float(capture_summary.get("value", 0.0)) >= 0.5:
        raise RuntimeError("ChibiTap Capture must be Off before remove")
    if not hasattr(track, "delete_device"):
        raise RuntimeError("Target track does not expose delete_device")

    track.delete_device(device_index)
    remaining = _named_chibitaps(self, track)
    if any(self._object_id(candidate) == device_id for _index, candidate in remaining):
        raise RuntimeError("ChibiTap removal did not remove the exact requested device")

    return {
        "removed": True,
        "signal_point": signal_point,
        "device_index": device_index,
        "remaining_chibitap_count": len(remaining),
        "remaining_chibitap_device_ids": [
            self._object_id(candidate)
            for _index, candidate in remaining
        ],
        "device": {
            "id": device_id,
            "name": "ChibiTap",
        },
        "track": {
            "id": self._object_id(track),
            "name": getattr(track, "name", ""),
        },
    }


def install_chibitap_multi_instance(cls):
    """Install the reviewed multi-instance ChibiTap behavior on the bridge class."""
    cls._chibitap_named_devices = _named_chibitaps
    cls._chibitap_devices_at_signal_point = _chibitaps_at_signal_point
    cls._chibitap_by_expected_id = _chibitap_by_expected_id
    cls._rpc_chibitap_setup = _rpc_chibitap_setup
    cls._rpc_chibitap_configure = _rpc_chibitap_configure
    cls._rpc_chibitap_remove = _rpc_chibitap_remove
