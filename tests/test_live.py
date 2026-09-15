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
                "capture": ["agent_audio_tap"],
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
