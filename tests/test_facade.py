from pathlib import Path

import pytest

from chibi_audio.facade import ChibiAudioFacade, FacadeError, TOOL_SCHEMAS


class FakeRead:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"capabilities": {"read": ["set_summary"]}}

    def set_summary(self, **kwargs):
        self.calls.append(("set_summary", kwargs))
        return {
            "set_signature": "sig-fresh",
            "tracks": [
                {"index": 0, "id": 10, "name": "Kick", "mute": False, "solo": False},
                {"index": 1, "id": 11, "name": "Hats", "mute": False, "solo": False},
            ],
        }

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == "sidechain_graph":
            return {
                "effect_state": "NOT_STARTED",
                "consumer_count": 1,
                "consumers": [{"target": {"name": "BASS"}, "source": {"routing_type": "SIDECHAIN"}}],
            }
        if method == "device_parameters":
            return {
                "parameters": [
                    {"id": 101, "name": "Device On", "value": 1.0, "display": "On"},
                    {"id": 102, "name": "Depth", "value": 0.25, "display": "25%"},
                ]
            }
        if method == "get":
            return {"name": "parameter", "value": 0.5, "min": 0.0, "max": 1.0}
        raise AssertionError(f"unexpected read method: {method}")


class FakeWrite:
    def __init__(self):
        self.calls = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return {"method": name, "params": kwargs}

    def set_track_volume(self, **kwargs):
        return self._record("set_track_volume", **kwargs)

    def set_track_pan(self, **kwargs):
        return self._record("set_track_pan", **kwargs)

    def set_track_property(self, **kwargs):
        return self._record("set_track_property", **kwargs)

    def set_device_parameter(self, **kwargs):
        return self._record("set_device_parameter", **kwargs)

    def set_device_enabled(self, **kwargs):
        return self._record("set_device_enabled", **kwargs)


def make_facade(artifact_root: Path | None = None):
    return ChibiAudioFacade(FakeRead(), FakeWrite(), artifact_root)


def test_tool_surface_is_explicit_and_has_no_raw_execution():
    facade = make_facade()
    names = set(facade.tool_names())
    assert names == set(TOOL_SCHEMAS)
    assert "plan_audition" in names
    assert "analyze_harshness_artifact" in names
    assert "set_device_parameter" in names
    assert not names.intersection({"eval", "execute_python", "raw_live_call", "raw_jsonrpc", "click"})
    assert all("description" in item and "inputSchema" in item for item in facade.tools())


def test_plan_audition_refreshes_set_before_planning():
    facade = make_facade()
    result = facade.call("plan_audition", {"solo_track_indices": [1]})
    assert result["set_signature"] == "sig-fresh"
    assert any(
        op["track_index"] == 1 and op["property"] == "solo" and op["value"] is True
        for op in result["apply"]
    )
    assert facade.read.calls[0][0] == "set_summary"


def test_parameter_snapshot_uses_exact_device_id():
    facade = make_facade()
    result = facade.call(
        "parameter_snapshot",
        {
            "track_index": 1,
            "track_name": "Hats",
            "device_index": 2,
            "device_name": "soothe2",
            "device_id": 777,
            "set_signature": "sig-device",
        },
    )
    assert result["device"] == {"index": 2, "name": "soothe2", "id": 777}
    assert result["parameters"][1]["name"] == "Depth"
    method, params = facade.read.calls[-1]
    assert method == "device_parameters"
    assert params["ref"]["id"] == 777


def test_artifact_root_allows_only_descendants(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    inside = root / "capture.wav"
    inside.write_bytes(b"fixture")
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"fixture")

    facade = make_facade(root)
    assert facade._resolve_artifact("capture.wav") == inside.resolve()
    with pytest.raises(FacadeError, match="relative"):
        facade._resolve_artifact(str(outside.resolve()))
    with pytest.raises(FacadeError, match="escapes"):
        facade._resolve_artifact("../outside.wav")


def test_artifact_analysis_requires_configured_root():
    facade = make_facade()
    with pytest.raises(FacadeError, match="artifact_root is not configured"):
        facade._resolve_artifact("capture.wav")


def test_typed_write_routes_without_generic_fallback():
    facade = make_facade()
    result = facade.call(
        "set_track_pan",
        {
            "track_index": 1,
            "expected_track_name": "Hats",
            "expected_current_value": 0.0,
            "value": -0.1,
        },
    )
    assert result["method"] == "set_track_pan"
    assert facade.write.calls[-1][1]["expected_track_name"] == "Hats"


def test_track_mixer_state_avoids_optional_live_display_value_property():
    facade = make_facade()
    result = facade.call("track_mixer_state", {"track_index": 1})
    assert result["track_index"] == 1
    get_calls = [params for method, params in facade.read.calls if method == "get"]
    assert len(get_calls) == 2
    assert all(params["properties"] == ["name", "value", "min", "max"] for params in get_calls)


def test_master_parameter_snapshot_routes_without_track_index():
    facade = make_facade()
    result = facade.call(
        "parameter_snapshot",
        {
            "placement": "master",
            "track_name": "Main",
            "device_index": 6,
            "device_name": "Pro-L 2",
            "device_id": 777,
            "set_signature": "sig-master",
        },
    )
    assert result["track"] == {"placement": "master", "index": None, "name": "Main"}
    schema = TOOL_SCHEMAS["set_device_parameter"]["inputSchema"]
    assert "track_index" not in schema["required"]
    assert schema["properties"]["placement"]["enum"] == ["track", "master"]


def test_sidechain_audit_is_explicit_read_only_facade_call():
    facade = make_facade()
    assert "sidechain_audit" in facade.tool_names()
    result = facade.call(
        "sidechain_audit",
        {
            "track_limit": 87,
            "max_devices": 2048,
            "max_depth": 7,
            "include_return_tracks": False,
            "include_master_track": True,
        },
    )
    assert result["effect_state"] == "NOT_STARTED"
    assert result["consumers"][0]["target"]["name"] == "BASS"
    assert facade.read.calls[-1] == (
        "sidechain_graph",
        {
            "track_limit": 87,
            "max_devices": 2048,
            "max_depth": 7,
            "include_return_tracks": False,
            "include_master_track": True,
        },
    )


def test_sidechain_capture_verifier_is_artifact_confined_and_analysis_only(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    root.mkdir()
    manifest = root / "capture-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    observed = {}

    def fake_verify(path, **kwargs):
        observed["path"] = path
        observed["kwargs"] = kwargs
        return {"effect_state": "NOT_STARTED", "status": "MEASURED"}

    monkeypatch.setattr("chibi_audio.facade.verify_sidechain_capture", fake_verify)
    facade = make_facade(root)
    result = facade.call(
        "verify_sidechain_capture",
        {
            "manifest": "capture-manifest.json",
            "trigger_label": "TRIGGER",
            "target_pre_label": "BASS_PRE",
            "target_post_label": "BASS_POST",
            "trigger_threshold_dbfs": -24.0,
        },
    )
    assert result == {"effect_state": "NOT_STARTED", "status": "MEASURED"}
    assert observed["path"] == manifest.resolve()
    assert observed["kwargs"]["trigger_label"] == "TRIGGER"
    assert observed["kwargs"]["trigger_threshold_dbfs"] == -24.0
    assert "verify_sidechain_capture" in facade.tool_names()
    assert facade.write.calls == []
