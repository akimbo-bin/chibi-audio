from __future__ import annotations

import copy

import pytest

from chibi_audio.capture import CaptureError
from chibi_audio.capture_session import CaptureSessionTap
from chibi_audio.capture_topology import prepare_capture_topology, restore_capture_topology


class FakeWorld:
    def __init__(self):
        self.version = 0
        self.next_device_id = 1000
        self.track = {
            "id": 200,
            "index": 34,
            "name": "BASS",
            "mute": False,
            "solo": False,
            "devices": [10, 20],
        }
        self.devices = {
            10: {"id": 10, "name": "Compressor", "type": 2},
            20: {"id": 20, "name": "ChibiTap", "type": 2, "tap_id": 99, "capture": False},
        }

    @property
    def signature(self):
        return f"sig-{self.version}"

    def summary(self):
        track = copy.deepcopy(self.track)
        track["devices"] = [
            {"id": device_id, "name": self.devices[device_id]["name"]}
            for device_id in self.track["devices"]
        ]
        return {
            "tempo": 120.0,
            "set_signature": self.signature,
            "tracks": [track],
            "master_track": {"id": 100, "name": "Main", "devices": []},
        }

    def expected_index(self, signal_point):
        ids = self.track["devices"]
        if signal_point == "post_fx":
            return len(ids) - 1
        if signal_point == "pre_fx":
            for index, device_id in enumerate(ids):
                if self.devices[device_id]["type"] == 2:
                    return index
            return len(ids)
        raise AssertionError(signal_point)


class FakeReadClient:
    def __init__(self, world):
        self.world = world
        self.summary_calls = []

    def set_summary(self, **_kwargs):
        self.summary_calls.append(self.world.signature)
        return self.world.summary()

    def call(self, method, params):
        device_id = int((params.get("ref") or {}).get("id", 0))
        if method == "device_parameters":
            device = self.world.devices[device_id]
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
        if method == "get":
            return {
                "id": device_id,
                "properties": {"type": self.world.devices[device_id]["type"]},
            }
        raise AssertionError(method)


class FakeCaptureClient:
    def __init__(self, world):
        self.world = world
        self.setup_calls = []
        self.configure_calls = []
        self.remove_calls = []
        self.operation_timeouts = []
        self.fail_after_config_once = False

    def _guard(self, expected_set_signature):
        if expected_set_signature != self.world.signature:
            raise RuntimeError(
                f"stale signature {expected_set_signature!r}; current {self.world.signature!r}"
            )

    def _target(self, kwargs):
        assert kwargs["placement"] == "track"
        assert kwargs["track_index"] == 34
        assert kwargs["expected_track_name"] == "BASS"
        return self.world.track

    def _setup_result(self, device_id, signal_point, loaded):
        device = self.world.devices[device_id]
        index = self.world.track["devices"].index(device_id)
        return {
            "loaded": loaded,
            "reused": not loaded,
            "signal_point": signal_point,
            "device_index": index,
            "track": {"id": 200, "name": "BASS"},
            "device": {"id": device_id, "name": "ChibiTap"},
            "parameters": {
                "Capture": {
                    "value": 1.0 if device.get("capture") else 0.0,
                    "display": "On" if device.get("capture") else "Off",
                },
                "Tap ID": {"display": str(device.get("tap_id", 0))},
                "tap_id_integer": int(device.get("tap_id", 0)),
            },
        }

    def setup_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        self._target(kwargs)
        signal_point = kwargs["signal_point"]
        self.setup_calls.append((signal_point, kwargs["expected_set_signature"]))
        self.operation_timeouts.append(("setup", kwargs.get("operation_timeout")))
        index = self.world.expected_index(signal_point)
        ids = self.world.track["devices"]
        if 0 <= index < len(ids):
            device_id = ids[index]
            if self.world.devices[device_id]["name"] == "ChibiTap":
                return self._setup_result(device_id, signal_point, False)

        device_id = self.world.next_device_id
        self.world.next_device_id += 1
        self.world.devices[device_id] = {
            "id": device_id,
            "name": "ChibiTap",
            "type": 2,
            "tap_id": 0,
            "capture": False,
        }
        if signal_point == "post_fx":
            self.world.track["devices"].append(device_id)
        else:
            self.world.track["devices"].insert(index, device_id)
        self.world.version += 1
        return self._setup_result(device_id, signal_point, True)

    def configure_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        self._target(kwargs)
        device_id = int(kwargs["expected_device_id"])
        signal_point = kwargs["signal_point"]
        index = self.world.expected_index(signal_point)
        if self.world.track["devices"][index] != device_id:
            raise RuntimeError("wrong exact ChibiTap device for signal point")
        device = self.world.devices[device_id]
        if device.get("capture"):
            raise RuntimeError("Capture is On")
        if int(device.get("tap_id", 0)) != int(kwargs["expected_tap_id"]):
            raise RuntimeError("Tap ID changed since inspection")
        self.operation_timeouts.append(("configure", kwargs.get("operation_timeout")))
        self.configure_calls.append(
            (
                device_id,
                int(kwargs["expected_tap_id"]),
                int(kwargs["tap_id"]),
                kwargs["expected_set_signature"],
            )
        )
        device["tap_id"] = int(kwargs["tap_id"])
        if self.fail_after_config_once:
            self.fail_after_config_once = False
            raise RuntimeError("simulated response loss after Live applied Tap ID")
        return {
            "signal_point": signal_point,
            "device_index": index,
            "device": {"id": device_id, "name": "ChibiTap"},
        }

    def remove_chibitap(self, **kwargs):
        self._guard(kwargs["expected_set_signature"])
        self._target(kwargs)
        device_id = int(kwargs["expected_device_id"])
        signal_point = kwargs["signal_point"]
        index = self.world.expected_index(signal_point)
        if self.world.track["devices"][index] != device_id:
            raise RuntimeError("wrong exact ChibiTap device for removal")
        device = self.world.devices[device_id]
        if device.get("capture"):
            raise RuntimeError("Capture is On")
        self.operation_timeouts.append(("remove", kwargs.get("operation_timeout")))
        self.remove_calls.append((device_id, signal_point, kwargs["expected_set_signature"]))
        del self.world.track["devices"][index]
        del self.world.devices[device_id]
        self.world.version += 1
        return {"removed": True, "device": {"id": device_id}}


def test_prepare_same_track_pre_post_refreshes_signatures_and_restore_is_exact():
    world = FakeWorld()
    reader = FakeReadClient(world)
    capture = FakeCaptureClient(world)

    lease = prepare_capture_topology(
        [
            CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx"),
            CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx"),
        ],
        expected_set_signature="sig-0",
        read_client=reader,
        capture_client=capture,
    )

    assert lease.initial_set_signature == "sig-0"
    assert lease.final_set_signature == "sig-1"
    assert [(tap.tap_id, tap.created, tap.prior_tap_id) for tap in lease.taps] == [
        (2, True, 0),
        (3, False, 99),
    ]
    assert [(tap.device_id, tap.device_index) for tap in lease.taps] == [(1000, 0), (20, 2)]
    assert capture.setup_calls == [("pre_fx", "sig-0"), ("post_fx", "sig-1")]
    assert capture.configure_calls == [
        (1000, 0, 2, "sig-1"),
        (20, 99, 3, "sig-1"),
    ]
    assert [world.devices[device_id]["tap_id"] for device_id in world.track["devices"] if world.devices[device_id]["name"] == "ChibiTap"] == [2, 3]

    restored = restore_capture_topology(
        lease,
        read_client=reader,
        capture_client=capture,
    )

    assert [action["action"] for action in restored["actions"]] == [
        "restore_tap_id",
        "remove_created",
    ]
    assert restored["final_set_signature"] == "sig-2"
    assert world.track["devices"] == [10, 20]
    assert world.devices[20]["tap_id"] == 99
    assert capture.remove_calls == [(1000, "pre_fx", "sig-1")]
    assert all(timeout == 90.0 for _operation, timeout in capture.operation_timeouts)


def test_stale_planned_signature_refuses_before_any_effect():
    world = FakeWorld()
    reader = FakeReadClient(world)
    capture = FakeCaptureClient(world)

    with pytest.raises(CaptureError, match="before any ChibiTap effect"):
        prepare_capture_topology(
            [CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx")],
            expected_set_signature="sig-stale",
            read_client=reader,
            capture_client=capture,
        )

    assert capture.setup_calls == []
    assert capture.configure_calls == []
    assert capture.remove_calls == []
    assert world.signature == "sig-0"


def test_prepare_reconciles_unknown_configure_effect_before_rollback():
    world = FakeWorld()
    reader = FakeReadClient(world)
    capture = FakeCaptureClient(world)
    capture.fail_after_config_once = True

    with pytest.raises(RuntimeError, match="simulated response loss"):
        prepare_capture_topology(
            [CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx")],
            expected_set_signature="sig-0",
            read_client=reader,
            capture_client=capture,
        )

    assert world.devices[20]["tap_id"] == 99
    assert capture.configure_calls == [
        (20, 99, 3, "sig-0"),
        (20, 3, 99, "sig-0"),
    ]
    assert capture.remove_calls == []


def test_restore_can_retain_created_taps_while_restoring_reused_ids():
    world = FakeWorld()
    reader = FakeReadClient(world)
    capture = FakeCaptureClient(world)
    lease = prepare_capture_topology(
        [
            CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx"),
            CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx"),
        ],
        expected_set_signature="sig-0",
        read_client=reader,
        capture_client=capture,
    )

    restored = restore_capture_topology(
        lease,
        remove_created=False,
        read_client=reader,
        capture_client=capture,
    )

    assert [action["action"] for action in restored["actions"]] == ["restore_tap_id"]
    assert world.track["devices"] == [1000, 10, 20]
    assert world.devices[1000]["tap_id"] == 2
    assert world.devices[20]["tap_id"] == 99
