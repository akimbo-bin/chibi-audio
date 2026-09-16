import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path("bridge/ChibiAudioBridge/chibitap_multi.py")
spec = importlib.util.spec_from_file_location("chibitap_multi_test_module", MODULE_PATH)
multi = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(multi)


class FakeParameter:
    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.min = 0.0
        self.max = 1.0
        self.default_value = 0.0
        self.display_value = str(value)
        self.is_quantized = False

    def str_for_value(self, value):
        if self.name == "Capture":
            return "On" if float(value) >= 0.5 else "Off"
        if self.name == "Tap ID":
            return str(int(round(float(value) * 9999.0)))
        return str(value)


class FakeDevice:
    def __init__(self, device_id, name, device_type, tap_id=0):
        self.device_id = device_id
        self.name = name
        self.type = device_type
        self.parameters = []
        if name == "ChibiTap":
            self.parameters = [
                FakeParameter("Capture", 0.0),
                FakeParameter("Tap ID", float(tap_id) / 9999.0),
            ]


class FakeTrack:
    def __init__(self, devices):
        self.name = "BASS"
        self.devices = list(devices)
        self.device_id = 200

    def delete_device(self, index):
        del self.devices[index]


class FakeSong:
    def __init__(self, track):
        self.track = track

    def move_device(self, device, track, index):
        old_index = track.devices.index(device)
        track.devices.pop(old_index)
        if index < 0 or index >= len(track.devices):
            track.devices.append(device)
        else:
            track.devices.insert(index, device)


class FakeBridge:
    def __init__(self, track):
        self.track = track
        self._song = FakeSong(track)
        self.next_device_id = 1000

    def song(self):
        return self._song

    def _object_id(self, obj):
        return obj.device_id

    def _same_live_object(self, left, right):
        return left is right or left.device_id == right.device_id

    def _chibitap_target_track(self, params):
        assert params.get("placement") == "track"
        assert params.get("track_index") == 34
        assert params.get("expected_track_name") == "BASS"
        return self.track, {"path": "song tracks 34"}

    def _chibitap_parameter_map(self, device):
        return {parameter.name: parameter for parameter in device.parameters}

    def _parameter_summary(self, parameter):
        return {
            "name": parameter.name,
            "value": parameter.value,
            "display": parameter.str_for_value(parameter.value),
        }

    def _chibitap_signal_point_insert_index(self, track, signal_point):
        if signal_point == "post_fx":
            return -1
        if signal_point == "pre_fx":
            for index, device in enumerate(track.devices):
                if device.type == 2:
                    return index
            return -1
        if signal_point == "post_instrument":
            instruments = [index for index, device in enumerate(track.devices) if device.type == 1]
            if len(instruments) != 1:
                raise RuntimeError(
                    "post_instrument requires exactly one instrument device; found %s" % len(instruments)
                )
            return instruments[0] + 1
        raise ValueError("signal_point must be post_fx, pre_fx, or post_instrument")

    def _chibitap_signal_point_index(self, track, device, signal_point):
        actual = track.devices.index(device)
        if signal_point == "post_fx":
            expected = len(track.devices) - 1
        elif signal_point == "pre_fx":
            expected = next(
                (index for index, candidate in enumerate(track.devices) if candidate.type == 2),
                len(track.devices) - 1,
            )
        elif signal_point == "post_instrument":
            instruments = [index for index, candidate in enumerate(track.devices) if candidate.type == 1]
            if len(instruments) != 1:
                raise RuntimeError(
                    "post_instrument requires exactly one instrument device; found %s" % len(instruments)
                )
            expected = instruments[0] + 1
        else:
            raise ValueError("signal_point must be post_fx, pre_fx, or post_instrument")
        if actual != expected:
            raise RuntimeError(
                "ChibiTap signal-point mismatch: %s expected index %s, found %s"
                % (signal_point, expected, actual)
            )
        return actual

    def _rpc_load_device(self, _params):
        device = FakeDevice(self.next_device_id, "ChibiTap", 2, tap_id=0)
        self.next_device_id += 1
        self.track.devices.append(device)
        return {
            "loaded": True,
            "device": {"id": device.device_id, "name": "ChibiTap"},
        }

    def _find_new_track_device(self, track, before_ids):
        for device in track.devices:
            if device.device_id not in before_ids:
                return device
        return None


def _params(signal_point, expected_device_id=None):
    result = {
        "placement": "track",
        "signal_point": signal_point,
        "track_index": 34,
        "expected_track_name": "BASS",
    }
    if expected_device_id is not None:
        result["expected_device_id"] = expected_device_id
    return result


def test_setup_configure_and_remove_exact_multi_instance_chibitaps():
    compressor = FakeDevice(10, "Compressor", 2)
    post = FakeDevice(20, "ChibiTap", 2, tap_id=3)
    track = FakeTrack([compressor, post])
    bridge = FakeBridge(track)

    pre_setup = multi._rpc_chibitap_setup(bridge, _params("pre_fx"))
    pre_id = pre_setup["device"]["id"]
    assert pre_setup["loaded"] is True
    assert pre_setup["reused"] is False
    assert pre_setup["signal_point"] == "pre_fx"
    assert pre_setup["device_index"] == 0
    assert pre_setup["chibitap_count"] == 2
    assert [device.device_id for device in track.devices] == [pre_id, 10, 20]

    post_setup = multi._rpc_chibitap_setup(bridge, _params("post_fx"))
    assert post_setup["loaded"] is False
    assert post_setup["reused"] is True
    assert post_setup["device"]["id"] == 20
    assert post_setup["device_index"] == 2
    assert post_setup["chibitap_count"] == 2

    configure_pre = _params("pre_fx", pre_id)
    configure_pre.update({
        "tap_id": 2,
        "expected_tap_id": 0,
        "expected_capture_enabled": False,
    })
    pre_result = multi._rpc_chibitap_configure(bridge, configure_pre)
    assert pre_result["device"]["id"] == pre_id
    assert pre_result["parameters"]["tap_id_integer"] == 2
    assert pre_result["chibitap_count"] == 2

    configure_post = _params("post_fx", 20)
    configure_post.update({
        "capture_enabled": True,
        "expected_capture_enabled": False,
    })
    post_result = multi._rpc_chibitap_configure(bridge, configure_post)
    assert post_result["device"]["id"] == 20
    assert post_result["parameters"]["Capture"]["value"] == 1.0
    assert post_result["chibitap_count"] == 2

    remove_pre = _params("pre_fx", pre_id)
    remove_pre["expected_capture_enabled"] = False
    removed = multi._rpc_chibitap_remove(bridge, remove_pre)
    assert removed["removed"] is True
    assert removed["remaining_chibitap_count"] == 1
    assert removed["remaining_chibitap_device_ids"] == [20]
    assert [device.device_id for device in track.devices] == [10, 20]
    assert track.devices[-1].parameters[0].value == 1.0


def test_configure_refuses_wrong_instance_or_wrong_signal_point():
    pre = FakeDevice(30, "ChibiTap", 2, tap_id=2)
    compressor = FakeDevice(10, "Compressor", 2)
    post = FakeDevice(20, "ChibiTap", 2, tap_id=3)
    bridge = FakeBridge(FakeTrack([pre, compressor, post]))

    with pytest.raises(RuntimeError, match="no longer present exactly once"):
        multi._rpc_chibitap_configure(
            bridge,
            {
                **_params("pre_fx", 999),
                "capture_enabled": True,
                "expected_capture_enabled": False,
            },
        )

    with pytest.raises(RuntimeError, match="signal-point mismatch"):
        multi._rpc_chibitap_configure(
            bridge,
            {
                **_params("pre_fx", 20),
                "capture_enabled": True,
                "expected_capture_enabled": False,
            },
        )


def test_installer_overrides_only_reviewed_chibitap_methods():
    class Dummy:
        pass

    multi.install_chibitap_multi_instance(Dummy)
    assert Dummy._rpc_chibitap_setup is multi._rpc_chibitap_setup
    assert Dummy._rpc_chibitap_configure is multi._rpc_chibitap_configure
    assert Dummy._rpc_chibitap_remove is multi._rpc_chibitap_remove
    assert not hasattr(Dummy, "_rpc_load_device")
