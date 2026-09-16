import pytest

from chibi_audio.live import CAPTURE_METHODS, LiveBridgeError, LiveCaptureClient


class FakeCaptureClient(LiveCaptureClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def status(self):
        return {"capabilities": {"capture": list(CAPTURE_METHODS)}}

    def _request(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"ok": True, "method": method, "params": params or {}}


def test_chibitap_configure_tap_only_preserves_capture_off_guard():
    client = FakeCaptureClient()
    result = client.configure_chibitap(
        placement="track",
        track_index=34,
        expected_track_name="BASS",
        expected_device_id=2468,
        tap_id=102,
        expected_tap_id=2,
        expected_capture_enabled=False,
        expected_set_signature="sig-tap-only",
    )
    assert result["method"] == "chibitap_configure"
    assert client.calls[-1][1] == {
        "placement": "track",
        "signal_point": "post_fx",
        "expected_device_id": 2468,
        "track_index": 34,
        "expected_track_name": "BASS",
        "tap_id": 102,
        "expected_tap_id": 2,
        "expected_capture_enabled": False,
        "expected_set_signature": "sig-tap-only",
    }

    with pytest.raises(LiveBridgeError, match="expected_capture_enabled=False"):
        client.configure_chibitap(
            expected_device_id=1,
            tap_id=1,
            expected_tap_id=0,
        )
