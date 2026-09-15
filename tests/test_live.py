from pathlib import Path
import pytest
from chibi_audio.live import (
    BOUNDED_WRITE_METHODS,
    CAPTURE_METHODS,
    READ_ONLY_METHODS,
    LiveBridgeClient,
    LiveBridgeError,
    LiveCaptureClient,
    LivePilotWriteClient,
)
def test_read_only_surface_excludes_mutation_and_capture():
    assert "parameter_set" not in READ_ONLY_METHODS
    assert "agent_audio_tap" not in READ_ONLY_METHODS
    assert "parameter_set" in BOUNDED_WRITE_METHODS
    assert "agent_audio_tap" in CAPTURE_METHODS
def test_client_refuses_unknown_method_before_network():
    client = LiveBridgeClient(port=1)
    with pytest.raises(LiveBridgeError, match="read-only client"):
        client.call("set", {"property": "mute", "value": True})
class FakeCaptureClient(LiveCaptureClient):
    def __init__(self):
        super().__init__()
        self.calls = []
    def status(self):
        return {
            "capabilities": {
                "capture": list(CAPTURE_METHODS),
                "bounded_write": ["parameter_set"],
                "read": list(READ_ONLY_METHODS),
            }
        }
    def _request(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"ok": True, "method": method, "params": params or {}}
class FakeWriteClient(LivePilotWriteClient):
    def __init__(self):
        super().__init__()
        self.calls = []
    def status(self):
        return {"capabilities": {"bounded_write": ["parameter_set"]}}
    def _request(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"ok": True, "method": method, "params": params or {}}
def test_capture_open_is_explicit_and_path_bound():
    client = FakeCaptureClient()
    result = client.capture("open", path=Path("C:/tmp/test.wav"), command_id="exp-1")
    assert result["method"] == "agent_audio_tap"
    assert client.calls[-1][1]["command"] == "open"
    assert client.calls[-1][1]["path"].endswith("test.wav")
    assert client.calls[-1][1]["command_id"] == "exp-1"
    assert client.calls[-1][1]["udp"] is False
def test_capture_open_requires_path():
    with pytest.raises(LiveBridgeError, match="requires an output path"):
        FakeCaptureClient().capture("open")
def test_capture_rejects_unadvertised_capability():
    client = FakeCaptureClient()
    client.status = lambda: {"capabilities": {"capture": []}}
    with pytest.raises(LiveBridgeError, match="does not advertise"):
        client.capture("status")
def test_pilot_write_targets_only_exact_track_volume_path():
    client = FakeWriteClient()
    result = client.set_track_volume(
        track_index=60,
        expected_track_name="61-something",
        expected_current_value=0.85,
        value=0.82,
    )
    assert result["method"] == "parameter_set"
    params = client.calls[-1][1]
    assert params["ref"]["path"] == "song tracks 60 mixer_device volume"
    assert params["expected_track_name"] == "61-something"
    assert params["expected_current_value"] == pytest.approx(0.85)


def test_capture_surface_includes_probe_setup_and_transport():
    assert "capture_probe_setup" in CAPTURE_METHODS
    assert "capture_transport" in CAPTURE_METHODS


def test_capture_probe_setup_is_master_only():
    client = FakeCaptureClient()
    result = client.setup_probe(expected_set_signature="sig-1")
    assert result["method"] == "capture_probe_setup"
    params = client.calls[-1][1]
    assert params["placement"] == "master"
    assert params["expected_set_signature"] == "sig-1"

def test_chibitap_capture_is_explicit_and_guarded():
    assert "chibitap_capture" in CAPTURE_METHODS
    client = FakeCaptureClient()
    result = client.set_chibitap_capture(
        True,
        expected_current_value=0.0,
        expected_set_signature="sig-3",
        expected_device_id=1234,
    )
    assert result["method"] == "chibitap_capture"
    params = client.calls[-1][1]
    assert params == {
        "enabled": True,
        "expected_current_value": 0.0,
        "expected_set_signature": "sig-3",
        "expected_device_id": 1234,
    }
    with pytest.raises(LiveBridgeError, match="enabled must be a boolean"):
        client.set_chibitap_capture(1, expected_current_value=0.0)


def test_capture_transport_seek_and_guards():
    client = FakeCaptureClient()
    result = client.transport("seek", time=68.0, expected_set_signature="sig-2")
    assert result["method"] == "capture_transport"
    params = client.calls[-1][1]
    assert params == {"action": "seek", "time": 68.0, "expected_set_signature": "sig-2"}
    with pytest.raises(LiveBridgeError, match="seek requires time"):
        client.transport("seek")
    with pytest.raises(LiveBridgeError, match="must be status, seek, play, or stop"):
        client.transport("continue")
    with pytest.raises(LiveBridgeError, match="time must be >= 0"):
        client.transport("status", time=-1)



def test_chibitap_setup_targets_exact_track_identity():
    assert "chibitap_setup" in CAPTURE_METHODS
    client = FakeCaptureClient()
    result = client.setup_chibitap(
        placement="track",
        track_index=34,
        expected_track_name="BASS",
        expected_set_signature="sig-setup",
    )
    assert result["method"] == "chibitap_setup"
    assert client.calls[-1][1] == {
        "placement": "track",
        "track_index": 34,
        "expected_track_name": "BASS",
        "expected_set_signature": "sig-setup",
    }


def test_chibitap_configure_guards_tap_id_and_capture():
    assert "chibitap_configure" in CAPTURE_METHODS
    client = FakeCaptureClient()
    result = client.configure_chibitap(
        placement="track",
        track_index=53,
        expected_track_name="DRUMS",
        expected_device_id=9876,
        tap_id=3,
        expected_tap_id=0,
        capture_enabled=True,
        expected_capture_enabled=False,
        expected_set_signature="sig-config",
    )
    assert result["method"] == "chibitap_configure"
    assert client.calls[-1][1] == {
        "placement": "track",
        "expected_device_id": 9876,
        "track_index": 53,
        "expected_track_name": "DRUMS",
        "tap_id": 3,
        "expected_tap_id": 0,
        "capture_enabled": True,
        "expected_capture_enabled": False,
        "expected_set_signature": "sig-config",
    }
    with pytest.raises(LiveBridgeError, match="expected_tap_id"):
        client.configure_chibitap(expected_device_id=1, tap_id=1)
