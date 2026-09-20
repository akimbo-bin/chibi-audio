from __future__ import annotations

import pytest

from chibi_audio.sidechain_configure import (
    SIDECHAIN_CONFIGURATION_SCHEMA_VERSION,
    SidechainConfigurationError,
    configure_sidechain_targets,
)


class FakeRead:
    def __init__(self, states):
        self.states = states
        self.calls = []

    def sidechain_graph(self, **kwargs):
        self.calls.append(("sidechain_graph", kwargs))
        consumers = []
        for index, (name, state) in enumerate(self.states.items()):
            if name.startswith("_"):
                continue
            consumers.append(
                {
                    "routing_state": state.get("routing_state", "RESOLVED" if float(state["value"]) >= 0.5 else "DISABLED"),
                    "target": {"placement": "track", "index": index, "id": 1000 + index, "name": name},
                    "device": {"id": 2000 + index, "name": "Live 8 Compressor", "class_name": "Compressor2"},
                    "source": {
                        "track": {"placement": "track", "index": 52, "id": 1052, "name": state.get("source", "SIDECHAIN")},
                        "routing_type": state.get("source", "SIDECHAIN"),
                    },
                }
            )
        consumers.append(
            {
                "routing_state": "SELF_SOURCE",
                "target": {"placement": "track", "index": 52, "id": 1052, "name": "SIDECHAIN"},
                "device": {"id": 2999, "name": "Live 8 Compressor", "class_name": "Compressor2"},
                "source": {"track": {"name": "SIDECHAIN", "id": 1052}},
            }
        )
        return {"set_signature": "sig-sidechain", "consumers": consumers}

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        assert method == "device_parameters"
        device_id = int(params["ref"]["id"])
        index = device_id - 2000
        name = [name for name in self.states if not name.startswith("_")][index]
        state = self.states[name]
        return {
            "parameters": [
                {"id": 3000 + index, "name": "Device On", "value": 1.0, "display": "On"},
                {
                    "id": 4000 + index,
                    "name": "S/C On",
                    "value": float(state["value"]),
                    "display": "On" if float(state["value"]) >= 0.5 else "Off",
                },
            ]
        }


class FakeWrite:
    def __init__(self, read, failures=None):
        self.read = read
        self.calls = []
        self.failures = list(failures or [])

    def set_device_parameter_ref(self, **kwargs):
        self.calls.append(kwargs)
        target = kwargs["expected_track_name"]
        state = self.read.states[target]
        assert float(state["value"]) == pytest.approx(kwargs["expected_current_value"])
        failure = self.failures.pop(0) if self.failures else None
        if failure == "reject":
            raise RuntimeError("rejected before write")
        if failure == "rollback_timeout":
            raise RuntimeError("rollback response lost before confirmed effect")
        before = float(state["value"])
        state["value"] = float(kwargs["value"])
        if failure == "landed_timeout":
            raise RuntimeError("response lost after write")
        return {
            "before": {"value": before},
            "applied_value": float(state["value"]),
            "changed": before != float(state["value"]),
            "read_back_verified": True,
        }


def test_one_intent_discovers_and_configures_multiple_targets_without_plugin_ids():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}, "BASS": {"value": 1.0}}
    read = FakeRead(states)
    write = FakeWrite(read)
    result = configure_sidechain_targets(
        read,
        write,
        source_track_name="SIDECHAIN",
        target_track_names=["VOX", "FX", "BASS"],
        intent="ensure_active",
    )
    assert result["schema_version"] == SIDECHAIN_CONFIGURATION_SCHEMA_VERSION
    assert result["effect_state"] == "STARTED_CONFIRMED"
    assert result["status"] == "CONFIGURED"
    assert result["selected_target_count"] == 3
    assert result["changed_target_count"] == 2
    assert states["VOX"]["value"] == 1.0
    assert states["FX"]["value"] == 1.0
    assert states["BASS"]["value"] == 1.0
    assert len(write.calls) == 2
    assert all("expected_device_id" in call for call in write.calls)
    assert all("device_index" not in call for call in write.calls)


def test_idempotent_multi_target_intent_is_not_started():
    states = {"VOX": {"value": 1.0}, "FX": {"value": 1.0}, "BASS": {"value": 1.0}}
    read = FakeRead(states)
    write = FakeWrite(read)
    result = configure_sidechain_targets(read, write, source_track_name="SIDECHAIN", intent="ensure_active")
    assert result["effect_state"] == "NOT_STARTED"
    assert result["changed_target_count"] == 0
    assert result["selected_target_count"] == 3
    assert write.calls == []


def test_preflight_missing_target_fails_before_any_write():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}}
    read = FakeRead(states)
    write = FakeWrite(read)
    with pytest.raises(SidechainConfigurationError, match="exactly one"):
        configure_sidechain_targets(
            read,
            write,
            source_track_name="SIDECHAIN",
            target_track_names=["VOX", "MISSING"],
            intent="ensure_active",
        )
    assert write.calls == []


def test_known_failure_rolls_back_confirmed_prior_target():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}}
    read = FakeRead(states)
    write = FakeWrite(read, failures=[None, "reject", None])
    result = configure_sidechain_targets(
        read,
        write,
        source_track_name="SIDECHAIN",
        target_track_names=["VOX", "FX"],
        intent="ensure_active",
    )
    assert result["status"] == "FAILED_RESTORED"
    assert result["effect_state"] == "STARTED_CONFIRMED"
    assert result["restored"] is True
    assert states["VOX"]["value"] == 0.0
    assert states["FX"]["value"] == 0.0


def test_landed_write_with_lost_response_is_reconciled_then_rolled_back():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}}
    read = FakeRead(states)
    write = FakeWrite(read, failures=["landed_timeout", None])
    result = configure_sidechain_targets(
        read,
        write,
        source_track_name="SIDECHAIN",
        target_track_names=["VOX", "FX"],
        intent="ensure_active",
    )
    assert result["status"] == "FAILED_RESTORED"
    assert result["effect_state"] == "STARTED_CONFIRMED"
    assert states["VOX"]["value"] == 0.0
    assert states["FX"]["value"] == 0.0


def test_uncertain_rollback_returns_unknown_final_effect_state():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}}
    read = FakeRead(states)
    write = FakeWrite(read, failures=[None, "reject", "rollback_timeout"])
    result = configure_sidechain_targets(
        read,
        write,
        source_track_name="SIDECHAIN",
        target_track_names=["VOX", "FX"],
        intent="ensure_active",
    )
    assert result["status"] == "FAILED_UNKNOWN"
    assert result["effect_state"] == "UNKNOWN"
    assert result["restored"] is False
    assert states["VOX"]["value"] == 1.0


def test_non_resolved_consumers_are_not_eligible_targets():
    states = {"VOX": {"value": 1.0}, "ORPHAN": {"value": 0.0, "routing_state": "NO_INPUT"}}
    read = FakeRead(states)
    write = FakeWrite(read)
    result = configure_sidechain_targets(read, write, source_track_name="SIDECHAIN", intent="ensure_active")
    assert result["selected_target_count"] == 1
    assert result["targets"][0]["target_track_name"] == "VOX"


def test_disabled_existing_route_is_eligible_for_ensure_active_restore():
    states = {"VOX": {"value": 0.0}, "FX": {"value": 0.0}}
    read = FakeRead(states)
    write = FakeWrite(read)
    result = configure_sidechain_targets(
        read,
        write,
        source_track_name="SIDECHAIN",
        target_track_names=["VOX", "FX"],
        intent="ensure_active",
    )
    assert result["changed_target_count"] == 2
    assert states["VOX"]["value"] == 1.0
    assert states["FX"]["value"] == 1.0
