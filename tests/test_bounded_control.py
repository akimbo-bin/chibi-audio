import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "bridge"
    / "ChibiAudioBridge"
    / "bounded_control.py"
)
spec = importlib.util.spec_from_file_location("chibi_audio_bounded_control", MODULE_PATH)
bounded_control = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bounded_control)


class Parameter:
    def __init__(self, name, value, minimum=0.0, maximum=1.0):
        self.name = name
        self.value = value
        self.min = minimum
        self.max = maximum
        self.is_quantized = False


class Mixer:
    def __init__(self):
        self.volume = Parameter("Volume", 0.8)
        self.panning = Parameter("Pan", 0.0, -1.0, 1.0)


class Device:
    def __init__(self):
        self.name = "soothe2"
        self.class_name = "PluginDevice"
        self.parameters = [
            Parameter("Device On", 1.0),
            Parameter("Depth", 0.25),
        ]


class TrackView:
    def __init__(self):
        self.is_collapsed = False


class Track:
    def __init__(self):
        self.name = "Hats"
        self.mute = False
        self.solo = False
        self.color_index = 3
        self.is_foldable = True
        self.fold_state = 0
        self.view = TrackView()
        self.mixer_device = Mixer()
        self.devices = [Device()]


class Song:
    def __init__(self):
        self.tracks = [Track()]
        self.master_track = Track()
        self.master_track.name = "Main"


class FakeBridge:
    def __init__(self):
        self._song = Song()

    def song(self):
        return self._song

    def _object_id(self, obj):
        return id(obj)

    def _parameter_summary(self, parameter):
        return {
            "id": id(parameter),
            "name": parameter.name,
            "value": parameter.value,
            "min": parameter.min,
            "max": parameter.max,
            "is_quantized": parameter.is_quantized,
        }


def test_mixer_write_checks_before_state_and_reads_back():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    result = bounded_control.rpc_track_mixer_parameter_set(
        bridge,
        {
            "track_index": 0,
            "expected_track_name": "Hats",
            "expected_track_id": id(track),
            "parameter": "panning",
            "expected_current_value": 0.0,
            "value": -0.1,
        },
    )
    assert result["read_back_verified"] is True
    assert track.mixer_device.panning.value == -0.1


def test_mixer_write_refuses_stale_before_state():
    bridge = FakeBridge()
    with pytest.raises(RuntimeError, match="changed since inspection"):
        bounded_control.rpc_track_mixer_parameter_set(
            bridge,
            {
                "track_index": 0,
                "expected_track_name": "Hats",
                "parameter": "volume",
                "expected_current_value": 0.7,
                "value": 0.75,
            },
        )


def test_track_write_refuses_stale_identity():
    bridge = FakeBridge()
    with pytest.raises(RuntimeError, match="Track identity mismatch"):
        bounded_control.rpc_track_set(
            bridge,
            {
                "track_index": 0,
                "expected_track_name": "Wrong Hats",
                "property": "solo",
                "expected_current_value": False,
                "value": True,
            },
        )


def test_device_parameter_write_uses_exact_identities():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    device = track.devices[0]
    parameter = device.parameters[1]
    result = bounded_control.rpc_device_parameter_set(
        bridge,
        {
            "track_index": 0,
            "expected_track_name": "Hats",
            "expected_track_id": id(track),
            "device_index": 0,
            "expected_device_name": "soothe2",
            "expected_device_id": id(device),
            "parameter_index": 1,
            "expected_parameter_name": "Depth",
            "expected_parameter_id": id(parameter),
            "expected_current_value": 0.25,
            "value": 0.30,
        },
    )
    assert result["applied_value"] == 0.30
    assert result["read_back_verified"] is True


def test_device_parameter_write_refuses_stale_parameter_id():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    device = track.devices[0]
    with pytest.raises(RuntimeError, match="Parameter object identity changed"):
        bounded_control.rpc_device_parameter_set(
            bridge,
            {
                "track_index": 0,
                "expected_track_name": "Hats",
                "device_index": 0,
                "expected_device_name": "soothe2",
                "parameter_index": 1,
                "expected_parameter_name": "Depth",
                "expected_parameter_id": 123,
                "expected_current_value": 0.25,
                "value": 0.30,
            },
        )


def test_device_parameter_write_supports_exact_master_identity():
    bridge = FakeBridge()
    master = bridge.song().master_track
    device = master.devices[0]
    parameter = device.parameters[1]
    result = bounded_control.rpc_device_parameter_set(
        bridge,
        {
            "placement": "master",
            "expected_track_name": "Main",
            "expected_track_id": id(master),
            "device_index": 0,
            "expected_device_name": "soothe2",
            "expected_device_id": id(device),
            "parameter_index": 1,
            "expected_parameter_name": "Depth",
            "expected_parameter_id": id(parameter),
            "expected_current_value": 0.25,
            "value": 0.30,
        },
    )
    assert result["track"] == {
        "placement": "master",
        "index": None,
        "id": id(master),
        "name": "Main",
    }
    assert result["applied_value"] == 0.30
    assert result["read_back_verified"] is True


def test_master_device_write_refuses_track_index_and_stale_identity():
    bridge = FakeBridge()
    master = bridge.song().master_track
    with pytest.raises(ValueError, match="track_index must be omitted"):
        bounded_control.rpc_device_parameter_set(
            bridge,
            {
                "placement": "master",
                "track_index": 0,
                "expected_track_name": "Main",
                "device_index": 0,
                "expected_device_name": "soothe2",
                "parameter_index": 1,
                "expected_parameter_name": "Depth",
                "expected_current_value": 0.25,
                "value": 0.30,
            },
        )
    with pytest.raises(RuntimeError, match="Track object identity changed"):
        bounded_control.rpc_device_parameter_set(
            bridge,
            {
                "placement": "master",
                "expected_track_name": "Main",
                "expected_track_id": id(master) + 1,
                "device_index": 0,
                "expected_device_name": "soothe2",
                "parameter_index": 1,
                "expected_parameter_name": "Depth",
                "expected_current_value": 0.25,
                "value": 0.30,
            },
        )


class Chain:
    def __init__(self, name, devices):
        self.name = name
        self.devices = list(devices)


class Rack:
    def __init__(self, nested):
        self.name = "SIDE CHAIN 8"
        self.class_name = "AudioEffectGroupDevice"
        self.parameters = [Parameter("Device On", 1.0)]
        self.chains = [Chain("Live 8 Compressor", [nested])]


def _nested_compressor(track):
    compressor = Device()
    compressor.name = "Live 8 Compressor"
    compressor.class_name = "Compressor2"
    compressor.parameters = [
        Parameter("Device On", 1.0),
        Parameter("Threshold", 0.0),
    ]
    track.devices.append(Rack(compressor))
    return compressor


def test_device_parameter_ref_write_finds_nested_device_by_exact_identity():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    device = _nested_compressor(track)
    parameter = device.parameters[1]
    result = bounded_control.rpc_device_parameter_ref_set(
        bridge,
        {
            "track_index": 0,
            "expected_track_name": "Hats",
            "expected_track_id": id(track),
            "expected_device_name": "Live 8 Compressor",
            "expected_device_class_name": "Compressor2",
            "expected_device_id": id(device),
            "parameter_index": 1,
            "expected_parameter_name": "Threshold",
            "expected_parameter_id": id(parameter),
            "expected_current_value": 0.0,
            "value": 0.2,
        },
    )
    assert result["applied_value"] == 0.2
    assert result["read_back_verified"] is True
    assert [item["kind"] for item in result["device"]["path"]] == ["device", "chain", "device"]
    assert result["device"]["path"][-1]["id"] == id(device)


def test_device_parameter_ref_write_refuses_device_from_other_track():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    foreign = _nested_compressor(bridge.song().master_track)
    parameter = foreign.parameters[1]
    with pytest.raises(RuntimeError, match="not uniquely contained"):
        bounded_control.rpc_device_parameter_ref_set(
            bridge,
            {
                "track_index": 0,
                "expected_track_name": track.name,
                "expected_track_id": id(track),
                "expected_device_name": foreign.name,
                "expected_device_id": id(foreign),
                "parameter_index": 1,
                "expected_parameter_name": parameter.name,
                "expected_parameter_id": id(parameter),
                "expected_current_value": 0.0,
                "value": 0.2,
            },
        )


def test_device_parameter_ref_write_refuses_class_or_parameter_identity_change():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    device = _nested_compressor(track)
    parameter = device.parameters[1]
    base = {
        "track_index": 0,
        "expected_track_name": track.name,
        "expected_track_id": id(track),
        "expected_device_name": device.name,
        "expected_device_id": id(device),
        "parameter_index": 1,
        "expected_parameter_name": parameter.name,
        "expected_current_value": 0.0,
        "value": 0.2,
    }
    with pytest.raises(RuntimeError, match="Device class identity mismatch"):
        bounded_control.rpc_device_parameter_ref_set(
            bridge, dict(base, expected_device_class_name="WrongClass")
        )
    with pytest.raises(RuntimeError, match="Parameter object identity changed"):
        bounded_control.rpc_device_parameter_ref_set(
            bridge, dict(base, expected_parameter_id=id(parameter) + 1)
        )


def test_track_presentation_properties_are_typed_and_read_back():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    fold = bounded_control.rpc_track_set(
        bridge,
        {
            "track_index": 0,
            "expected_track_name": "Hats",
            "expected_track_id": id(track),
            "property": "fold_state",
            "expected_current_value": 0,
            "value": 1,
        },
    )
    assert fold["read_back_verified"] is True
    assert track.fold_state == 1

    collapsed = bounded_control.rpc_track_set(
        bridge,
        {
            "track_index": 0,
            "expected_track_name": "Hats",
            "expected_track_id": id(track),
            "property": "is_collapsed",
            "expected_current_value": False,
            "value": True,
        },
    )
    assert collapsed["read_back_verified"] is True
    assert track.view.is_collapsed is True


def test_presentation_batch_validates_then_applies_name_last():
    bridge = FakeBridge()
    track = bridge.song().tracks[0]
    result = bounded_control.rpc_track_presentation_batch_set(
        bridge,
        {
            "edits": [
                {
                    "track_index": 0,
                    "expected_track_name": "Hats",
                    "expected_track_id": id(track),
                    "property": "name",
                    "expected_current_value": "Hats",
                    "value": "Hat Loop",
                },
                {
                    "track_index": 0,
                    "expected_track_name": "Hats",
                    "expected_track_id": id(track),
                    "property": "color_index",
                    "expected_current_value": 3,
                    "value": 7,
                },
            ]
        },
    )
    assert result["operation_count"] == 2
    assert [item["property"] for item in result["operations"]] == ["color_index", "name"]
    assert track.color_index == 7
    assert track.name == "Hat Loop"


def test_presentation_batch_rolls_back_all_attempted_edits(monkeypatch):
    bridge = FakeBridge()
    first = bridge.song().tracks[0]
    second = Track()
    second.name = "Perc"
    bridge.song().tracks.append(second)
    original = bounded_control._write_track_property

    def fail_second(track, prop, value):
        if track is second and prop == "is_collapsed" and value is True:
            raise RuntimeError("synthetic write failure")
        return original(track, prop, value)

    monkeypatch.setattr(bounded_control, "_write_track_property", fail_second)
    with pytest.raises(RuntimeError, match="rolled back exactly"):
        bounded_control.rpc_track_presentation_batch_set(
            bridge,
            {
                "edits": [
                    {
                        "track_index": 0,
                        "expected_track_name": "Hats",
                        "expected_track_id": id(first),
                        "property": "color_index",
                        "expected_current_value": 3,
                        "value": 7,
                    },
                    {
                        "track_index": 1,
                        "expected_track_name": "Perc",
                        "expected_track_id": id(second),
                        "property": "is_collapsed",
                        "expected_current_value": False,
                        "value": True,
                    },
                ]
            },
        )
    assert first.color_index == 3
    assert second.view.is_collapsed is False
