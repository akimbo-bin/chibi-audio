from __future__ import annotations

import copy

from chibi_audio.capture_session import CaptureSessionTap
from chibi_audio.capture_topology import prepare_capture_topology, restore_capture_topology


class World:
    def __init__(self):
        self.version = 0
        self.next_device_id = 1000
        self.track = {"id": 200, "index": 34, "name": "BASS", "devices": [10, 20]}
        self.devices = {
            10: {"name": "Compressor", "type": 2},
            20: {"name": "ChibiTap", "type": 2, "tap_id": 99, "capture": False},
        }

    @property
    def signature(self):
        return f"sig-{self.version}"

    def index_for(self, signal_point):
        if signal_point == "post_fx":
            return len(self.track["devices"]) - 1
        if signal_point == "pre_fx":
            for index, device_id in enumerate(self.track["devices"]):
                if self.devices[device_id]["type"] == 2:
                    return index
        raise AssertionError(signal_point)

    def summary(self):
        track = copy.deepcopy(self.track)
        track["devices"] = [
            {"id": device_id, "name": self.devices[device_id]["name"]}
            for device_id in self.track["devices"]
        ]
        return {
            "set_signature": self.signature,
            "tempo": 120.0,
            "tracks": [track],
            "master_track": {"id": 100, "name": "Main", "devices": []},
        }


class Reader:
    def __init__(self, world):
        self.world = world

    def set_summary(self, **_kwargs):
        return self.world.summary()

    def call(self, method, params):
        device_id = int(params["ref"]["id"])
        device = self.world.devices[device_id]
        if method == "get":
            return {"properties": {"type": device["type"]}}
        if method == "device_parameters":
            return [
                {
                    "name": "Capture",
                    "value": 1.0 if device.get("capture") else 0.0,
                    "display": "On" if device.get("capture") else "Off",
                },
                {
                    "name": "Tap ID",
                    "value": float(device.get("tap_id", 0)) / 9999.0,
                    "display": str(device.get("tap_id", 0)),
                },
            ]
        raise AssertionError(method)


class Capture:
    def __init__(self, world):
        self.world = world
        self.calls = []

    def _guard(self, signature):
        assert signature == self.world.signature

    def _result(self, device_id, signal_point, loaded):
        device = self.world.devices[device_id]
        return {
            "loaded": loaded,
            "signal_point": signal_point,
            "device_index": self.world.track["devices"].index(device_id),
            "track": {"id": 200, "name": "BASS"},
            "device": {"id": device_id, "name": "ChibiTap"},
            "parameters": {
                "Capture": {"value": 1.0 if device.get("capture") else 0.0},
                "tap_id_integer": int(device.get("tap_id", 0)),
            },
        }

    def setup_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        signal_point = kwargs["signal_point"]
        index = self.world.index_for(signal_point)
        device_id = self.world.track["devices"][index]
        if self.world.devices[device_id]["name"] == "ChibiTap":
            self.calls.append(("setup_reuse", signal_point, self.world.signature))
            return self._result(device_id, signal_point, False)

        device_id = self.world.next_device_id
        self.world.next_device_id += 1
        self.world.devices[device_id] = {
            "name": "ChibiTap",
            "type": 2,
            "tap_id": 0,
            "capture": False,
        }
        self.world.track["devices"].insert(index, device_id)
        self.world.version += 1
        self.calls.append(("setup_create", signal_point, kwargs["expected_set_signature"]))
        return self._result(device_id, signal_point, True)

    def configure_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        device_id = int(kwargs["expected_device_id"])
        index = self.world.index_for(kwargs["signal_point"])
        assert self.world.track["devices"][index] == device_id
        device = self.world.devices[device_id]
        assert int(device.get("tap_id", 0)) == int(kwargs["expected_tap_id"])
        device["tap_id"] = int(kwargs["tap_id"])
        self.calls.append(
            (
                "configure",
                device_id,
                int(kwargs["expected_tap_id"]),
                int(kwargs["tap_id"]),
                kwargs["expected_set_signature"],
            )
        )
        return {"device": {"id": device_id}}

    def remove_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        device_id = int(kwargs["expected_device_id"])
        index = self.world.index_for(kwargs["signal_point"])
        assert self.world.track["devices"][index] == device_id
        del self.world.track["devices"][index]
        del self.world.devices[device_id]
        self.world.version += 1
        self.calls.append(("remove", device_id, kwargs["expected_set_signature"]))
        return {"removed": True}


def test_post_then_pre_reconciles_final_indexes_and_restores_in_reverse():
    world = World()
    reader = Reader(world)
    capture = Capture(world)

    lease = prepare_capture_topology(
        [
            CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx"),
            CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx"),
        ],
        expected_set_signature="sig-0",
        read_client=reader,
        capture_client=capture,
    )

    assert [(tap.tap_id, tap.device_id, tap.device_index) for tap in lease.taps] == [
        (3, 20, 2),
        (2, 1000, 0),
    ]
    assert lease.final_set_signature == "sig-1"

    restore = restore_capture_topology(
        lease,
        read_client=reader,
        capture_client=capture,
    )

    assert world.track["devices"] == [10, 20]
    assert world.devices[20]["tap_id"] == 99
    assert restore["final_set_signature"] == "sig-2"
    assert capture.calls[-2:] == [
        ("remove", 1000, "sig-1"),
        ("configure", 20, 3, 99, "sig-2"),
    ]
