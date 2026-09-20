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
    assert "track_set" not in READ_ONLY_METHODS
    assert "agent_audio_tap" not in READ_ONLY_METHODS
    assert "track_mixer_parameter_set" in BOUNDED_WRITE_METHODS
    assert "device_parameter_set" in BOUNDED_WRITE_METHODS
    assert "device_parameter_ref_set" in BOUNDED_WRITE_METHODS
    assert "track_presentation_batch_set" in BOUNDED_WRITE_METHODS
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
                "bounded_write": list(BOUNDED_WRITE_METHODS),
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
        return {"capabilities": {"bounded_write": list(BOUNDED_WRITE_METHODS)}}

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


def test_typed_track_volume_and_pan_requests_include_guards():
    client = FakeWriteClient()
    result = client.set_track_volume(
        track_index=60,
        expected_track_name="61-something",
        expected_track_id=6060,
        expected_current_value=0.85,
        value=0.82,
        expected_set_signature="sig-volume",
    )
    assert result["method"] == "track_mixer_parameter_set"
    params = client.calls[-1][1]
    assert params["parameter"] == "volume"
    assert params["expected_track_name"] == "61-something"
    assert params["expected_track_id"] == 6060
    assert params["expected_current_value"] == pytest.approx(0.85)
    assert params["expected_set_signature"] == "sig-volume"

    pan = client.set_track_pan(
        track_index=4,
        expected_track_name="Hats",
        expected_current_value=0.0,
        value=-0.1,
    )
    assert pan["method"] == "track_mixer_parameter_set"
    assert client.calls[-1][1]["parameter"] == "panning"


def test_typed_track_property_request_is_narrow():
    client = FakeWriteClient()
    result = client.set_track_property(
        track_index=4,
        expected_track_name="Hats",
        property="solo",
        expected_current_value=False,
        value=True,
    )
    assert result["method"] == "track_set"
    assert client.calls[-1][1]["property"] == "solo"
    with pytest.raises(LiveBridgeError, match="fold_state"):
        client.set_track_property(
            track_index=4,
            expected_track_name="Hats",
            property="delete_device",
            expected_current_value=False,
            value=True,
        )


def test_typed_device_parameter_request_carries_exact_ids():
    client = FakeWriteClient()
    result = client.set_device_parameter(
        track_index=4,
        expected_track_name="Hats",
        expected_track_id=444,
        device_index=2,
        expected_device_name="soothe2",
        expected_device_id=222,
        parameter_index=5,
        expected_parameter_name="Depth",
        expected_parameter_id=555,
        expected_current_value=0.25,
        value=0.30,
        expected_set_signature="sig-param",
    )
    assert result["method"] == "device_parameter_set"
    params = client.calls[-1][1]
    assert params["expected_track_id"] == 444
    assert params["expected_device_id"] == 222
    assert params["expected_parameter_id"] == 555
    assert params["expected_set_signature"] == "sig-param"


def test_typed_master_device_parameter_request_omits_track_index():
    client = FakeWriteClient()
    result = client.set_device_parameter(
        placement="master",
        expected_track_name="Main",
        expected_track_id=1700,
        device_index=6,
        expected_device_name="Pro-L 2",
        expected_device_id=2600,
        parameter_index=4,
        expected_parameter_name="Gain",
        expected_parameter_id=4600,
        expected_current_value=0.41,
        value=0.42,
        expected_set_signature="sig-master",
    )
    assert result["method"] == "device_parameter_set"
    params = client.calls[-1][1]
    assert params["placement"] == "master"
    assert "track_index" not in params
    assert params["expected_track_name"] == "Main"
    assert params["expected_track_id"] == 1700
    assert params["expected_set_signature"] == "sig-master"

    with pytest.raises(LiveBridgeError, match="track_index must be omitted"):
        client.set_device_parameter(
            placement="master",
            track_index=0,
            expected_track_name="Main",
            device_index=6,
            expected_device_name="Pro-L 2",
            parameter_index=4,
            expected_parameter_name="Gain",
            expected_current_value=0.41,
            value=0.42,
        )


def test_device_enabled_requires_boolean():
    client = FakeWriteClient()
    with pytest.raises(LiveBridgeError, match="enabled must be a boolean"):
        client.set_device_enabled(
            1,
            track_index=4,
            expected_track_name="Hats",
            device_index=2,
            expected_device_name="soothe2",
            parameter_index=0,
            expected_parameter_name="Device On",
            expected_current_value=1.0,
        )


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

    scheduled = client.transport(
        "play_until",
        time=64.0,
        end_time=68.0,
        expected_set_signature="sig-range",
    )
    assert scheduled["method"] == "capture_transport"
    assert client.calls[-1][1] == {
        "action": "play_until",
        "time": 64.0,
        "end_time": 68.0,
        "expected_set_signature": "sig-range",
    }

    with pytest.raises(LiveBridgeError, match="seek requires time"):
        client.transport("seek")
    with pytest.raises(LiveBridgeError, match="play_until requires time"):
        client.transport("play_until", end_time=68.0)
    with pytest.raises(LiveBridgeError, match="play_until requires end_time"):
        client.transport("play_until", time=64.0)
    with pytest.raises(LiveBridgeError, match="greater than time"):
        client.transport("play_until", time=68.0, end_time=68.0)
    with pytest.raises(LiveBridgeError, match="only valid for play_until"):
        client.transport("status", end_time=68.0)
    with pytest.raises(LiveBridgeError, match="must be status"):
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
        operation_timeout=90.0,
    )
    assert result["method"] == "chibitap_setup"
    assert client.calls[-1][1] == {
        "placement": "track",
        "signal_point": "post_fx",
        "track_index": 34,
        "expected_track_name": "BASS",
        "expected_set_signature": "sig-setup",
        "timeout": 90.0,
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
        operation_timeout=90.0,
    )
    assert result["method"] == "chibitap_configure"
    assert client.calls[-1][1] == {
        "placement": "track",
        "signal_point": "post_fx",
        "expected_device_id": 9876,
        "track_index": 53,
        "expected_track_name": "DRUMS",
        "tap_id": 3,
        "expected_tap_id": 0,
        "capture_enabled": True,
        "expected_capture_enabled": False,
        "expected_set_signature": "sig-config",
        "timeout": 90.0,
    }
    with pytest.raises(LiveBridgeError, match="expected_tap_id"):
        client.configure_chibitap(expected_device_id=1, tap_id=1)


def test_chibitap_refresh_is_explicit_and_guarded():
    assert "chibitap_refresh" in CAPTURE_METHODS
    client = FakeCaptureClient()
    result = client.refresh_chibitap(
        expected_device_id=1234,
        expected_capture_value=0.0,
        expected_set_signature="sig-refresh",
    )
    assert result["method"] == "chibitap_refresh"
    assert client.calls[-1][1] == {
        "expected_device_id": 1234,
        "expected_capture_value": 0.0,
        "expected_set_signature": "sig-refresh",
    }


def test_chibitap_signal_point_validation_and_remove():
    client = FakeCaptureClient()
    with pytest.raises(LiveBridgeError, match="signal_point"):
        client.setup_chibitap(signal_point="middle")
    result = client.remove_chibitap(
        placement="track",
        signal_point="pre_fx",
        track_index=23,
        expected_track_name="24-Audio",
        expected_device_id=4321,
        expected_capture_enabled=False,
        expected_set_signature="sig-remove",
        operation_timeout=90.0,
    )
    assert result["method"] == "chibitap_remove"
    assert client.calls[-1][1] == {
        "placement": "track",
        "signal_point": "pre_fx",
        "expected_device_id": 4321,
        "expected_capture_enabled": False,
        "track_index": 23,
        "expected_track_name": "24-Audio",
        "expected_set_signature": "sig-remove",
        "timeout": 90.0,
    }
    with pytest.raises(LiveBridgeError, match="expected_capture_enabled=False"):
        client.remove_chibitap(expected_device_id=1, expected_capture_enabled=True)

    with pytest.raises(LiveBridgeError, match="operation_timeout"):
        client.setup_chibitap(operation_timeout=0)

def test_typed_device_parameter_ref_request_carries_exact_nested_identity():
    client = FakeWriteClient()
    result = client.set_device_parameter_ref(
        track_index=34,
        expected_track_name="BASS",
        expected_track_id=3400,
        expected_device_name="Live 8 Compressor",
        expected_device_class_name="Compressor2",
        expected_device_id=7777,
        parameter_index=1,
        expected_parameter_name="Threshold",
        expected_parameter_id=8888,
        expected_current_value=0.0,
        value=0.1,
        expected_set_signature="sig-sidechain",
    )
    assert result["method"] == "device_parameter_ref_set"
    params = client.calls[-1][1]
    assert params["track_index"] == 34
    assert params["expected_track_id"] == 3400
    assert params["expected_device_id"] == 7777
    assert params["expected_device_class_name"] == "Compressor2"
    assert params["expected_parameter_id"] == 8888
    assert params["expected_set_signature"] == "sig-sidechain"
    assert "device_index" not in params


def test_device_parameter_ref_requires_exact_device_id():
    client = FakeWriteClient()
    with pytest.raises(TypeError):
        client.set_device_parameter_ref(
            track_index=34,
            expected_track_name="BASS",
            expected_device_name="Live 8 Compressor",
            parameter_index=1,
            expected_parameter_name="Threshold",
            expected_current_value=0.0,
            value=0.1,
        )


def test_typed_presentation_batch_is_signature_fenced():
    client = FakeWriteClient()
    edits = [
        {
            "track_index": 4,
            "expected_track_name": "Hats",
            "expected_track_id": 444,
            "property": "color_index",
            "expected_current_value": 3,
            "value": 7,
        }
    ]
    result = client.set_track_presentation_batch(
        edits,
        expected_set_signature="sig-organize",
    )
    assert result["method"] == "track_presentation_batch_set"
    params = client.calls[-1][1]
    assert params["expected_set_signature"] == "sig-organize"
    assert params["edits"] == edits
    with pytest.raises(LiveBridgeError, match="presentation edits only support"):
        client.set_track_presentation_batch(
            [{**edits[0], "property": "volume"}],
            expected_set_signature="sig-organize",
        )
