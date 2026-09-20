from __future__ import absolute_import, print_function

SIDECHAIN_READ_METHODS = ("sidechain_graph",)


def install_sidechain_read(cls):
    cls._rpc_sidechain_graph = _rpc_sidechain_graph


def _display_name(value):
    if value is None:
        return None
    try:
        return str(value.display_name)
    except Exception:
        return None


def _parameter_map(device):
    result = {}
    try:
        values = list(device.parameters)
    except Exception:
        return result
    for parameter in values:
        try:
            name = str(getattr(parameter, "name", ""))
        except Exception:
            continue
        if name:
            result[name] = parameter
    return result


def _track_record(self, track, placement, index):
    record = {
        "placement": placement,
        "id": self._object_id(track),
        "name": str(getattr(track, "name", "")),
    }
    self._remember_object(record["id"], track)
    if index is not None:
        record["index"] = int(index)
    return record


def _source_index(self, song):
    rows = []
    for index, track in enumerate(list(getattr(song, "tracks", []))):
        rows.append((_track_record(self, track, "track", index), track))
    for index, track in enumerate(list(getattr(song, "return_tracks", []))):
        rows.append((_track_record(self, track, "return", index), track))
    master = getattr(song, "master_track", None)
    if master is not None:
        rows.append((_track_record(self, master, "master", None), master))
    by_name = {}
    for record, track in rows:
        by_name.setdefault(record["name"], []).append((record, track))
    return rows, by_name


def _source_binding(routing_type, by_name):
    matches = by_name.get(routing_type, []) if routing_type else []
    if len(matches) == 1:
        return "RESOLVED", dict(matches[0][0]), []
    if len(matches) > 1:
        return "AMBIGUOUS_SOURCE", None, [dict(item[0]) for item in matches]
    return "UNRESOLVED_SOURCE", None, []


def _sidechain_parameter(self, parameters, name):
    parameter = parameters.get(name)
    return self._parameter_summary(parameter) if parameter is not None else None


def _native_compressor_row(self, target, device, path, by_name):
    try:
        class_name = str(getattr(device, "class_name", ""))
    except Exception:
        class_name = ""
    if class_name != "Compressor2":
        return None

    try:
        routing_type = _display_name(device.input_routing_type)
        routing_channel = _display_name(device.input_routing_channel)
    except Exception:
        return None

    parameters = _parameter_map(device)
    enabled_parameter = parameters.get("S/C On")
    enabled = None
    if enabled_parameter is not None:
        try:
            enabled = float(enabled_parameter.value) >= 0.5
        except Exception:
            enabled = None

    source_state, source_track, source_candidates = _source_binding(routing_type, by_name)
    if enabled is False:
        routing_state = "DISABLED"
    elif enabled is None:
        routing_state = "UNKNOWN_ENABLE_STATE"
    elif not routing_type or routing_type == "No Input":
        routing_state = "NO_INPUT"
    elif source_state == "RESOLVED" and source_track is not None and source_track.get("id") == target.get("id"):
        routing_state = "SELF_SOURCE"
    else:
        routing_state = source_state

    device_id = self._object_id(device)
    self._remember_object(device_id, device)
    row = {
        "target": dict(target),
        "device": {
            "id": device_id,
            "name": str(getattr(device, "name", "")),
            "class_name": class_name,
            "path": list(path),
        },
        "method": "native_compressor",
        "routing_state": routing_state,
        "source": {
            "routing_type": routing_type,
            "routing_channel": routing_channel,
            "track": source_track,
            "candidates": source_candidates,
        },
        "sidechain": {
            "enabled": enabled,
            "on": _sidechain_parameter(self, parameters, "S/C On"),
            "listen": _sidechain_parameter(self, parameters, "S/C Listen"),
            "gain": _sidechain_parameter(self, parameters, "S/C Gain"),
            "mix": _sidechain_parameter(self, parameters, "S/C Mix"),
            "eq_enabled": _sidechain_parameter(self, parameters, "S/C EQ On"),
            "eq_type": _sidechain_parameter(self, parameters, "S/C EQ Type"),
            "eq_frequency": _sidechain_parameter(self, parameters, "S/C EQ Freq"),
        },
    }
    return row


def _walk_devices(self, target, devices, by_name, state, path, depth, max_depth, max_devices):
    if depth > max_depth:
        state["truncated"] = True
        return
    for device_index, device in enumerate(list(devices)):
        if state["devices_scanned"] >= max_devices:
            state["truncated"] = True
            return
        state["devices_scanned"] += 1
        device_id = self._object_id(device)
        self._remember_object(device_id, device)
        try:
            class_name = str(getattr(device, "class_name", ""))
        except Exception:
            class_name = ""
        device_path = list(path) + [{
            "kind": "device",
            "index": int(device_index),
            "id": device_id,
            "name": str(getattr(device, "name", "")),
            "class_name": class_name,
        }]
        row = _native_compressor_row(self, target, device, device_path, by_name)
        if row is not None:
            state["consumers"].append(row)

        for child_name, child_kind in (("chains", "chain"), ("return_chains", "return_chain")):
            try:
                chains = list(getattr(device, child_name))
            except Exception:
                continue
            for chain_index, chain in enumerate(chains):
                chain_id = self._object_id(chain)
                self._remember_object(chain_id, chain)
                chain_path = device_path + [{
                    "kind": child_kind,
                    "index": int(chain_index),
                    "id": chain_id,
                    "name": str(getattr(chain, "name", "")),
                }]
                try:
                    child_devices = list(chain.devices)
                except Exception:
                    child_devices = []
                _walk_devices(
                    self, target, child_devices, by_name, state, chain_path,
                    depth + 1, max_depth, max_devices,
                )
                if state["devices_scanned"] >= max_devices:
                    return


def _rpc_sidechain_graph(self, params):
    song = self.song()
    track_limit = int(params.get("track_limit") if params.get("track_limit") is not None else 256)
    max_devices = int(params.get("max_devices") if params.get("max_devices") is not None else 4096)
    max_depth = int(params.get("max_depth") if params.get("max_depth") is not None else 8)
    if track_limit < -1:
        raise ValueError("track_limit must be -1 or >= 0")
    if max_devices < 1 or max_devices > 20000:
        raise ValueError("max_devices must be between 1 and 20000")
    if max_depth < 0 or max_depth > 32:
        raise ValueError("max_depth must be between 0 and 32")

    source_rows, by_name = _source_index(self, song)
    regular = list(getattr(song, "tracks", []))
    selected = regular if track_limit < 0 else regular[:track_limit]
    targets = [(_track_record(self, track, "track", index), track) for index, track in enumerate(selected)]
    if bool(params.get("include_return_tracks", True)):
        targets.extend(
            (_track_record(self, track, "return", index), track)
            for index, track in enumerate(list(getattr(song, "return_tracks", [])))
        )
    if bool(params.get("include_master_track", True)):
        master = getattr(song, "master_track", None)
        if master is not None:
            targets.append((_track_record(self, master, "master", None), master))

    state = {"consumers": [], "devices_scanned": 0, "truncated": False}
    for target, track in targets:
        try:
            devices = list(track.devices)
        except Exception:
            devices = []
        _walk_devices(self, target, devices, by_name, state, [], 0, max_depth, max_devices)
        if state["devices_scanned"] >= max_devices:
            break

    consumers = state["consumers"]
    consumers.sort(key=lambda row: (
        str(row["target"].get("placement")),
        int(row["target"].get("index", -1)),
        str(row["target"].get("name", "")),
        str(row["device"].get("name", "")),
    ))
    state_counts = {}
    for row in consumers:
        key = row["routing_state"]
        state_counts[key] = state_counts.get(key, 0) + 1
    resolved = sum(state_counts.get(key, 0) for key in ("RESOLVED", "SELF_SOURCE"))
    attention_states = ("NO_INPUT", "SELF_SOURCE", "AMBIGUOUS_SOURCE", "UNRESOLVED_SOURCE", "UNKNOWN_ENABLE_STATE")
    findings = []
    for row in consumers:
        state_name = row["routing_state"]
        if state_name not in attention_states:
            continue
        findings.append({
            "code": state_name,
            "target": dict(row["target"]),
            "device": dict(row["device"]),
            "source": dict(row["source"]),
        })
    return {
        "schema_version": 1,
        "effect_state": "NOT_STARTED",
        "set_signature": self._set_signature(),
        "coverage": {
            "native_compressor_routing": "SUPPORTED",
            "third_party_plugin_sidechain_routing": "UNSUPPORTED",
            "note": "Only native Compressor2 routing is audited exactly in this version; plugin sidechain routes are not inferred.",
        },
        "tracks_available_as_sources": len(source_rows),
        "tracks_scanned": len(targets),
        "devices_scanned": state["devices_scanned"],
        "truncated": bool(state["truncated"] or (track_limit >= 0 and len(regular) > track_limit)),
        "consumer_count": len(consumers),
        "resolved_consumer_count": resolved,
        "routing_state_counts": state_counts,
        "attention_finding_count": len(findings),
        "findings": findings,
        "consumers": consumers,
    }
