from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path("bridge/ChibiAudioBridge/sidechain_read.py")
SPEC = importlib.util.spec_from_file_location("chibi_sidechain_read_test", MODULE_PATH)
sidechain_read = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sidechain_read)


class Obj:
    def __init__(self, oid, **values):
        self.oid = oid
        self.__dict__.update(values)


class Param(Obj):
    def str_for_value(self, value):
        return getattr(self, "display", str(value))


def parameter(oid, name, value, display):
    return Param(oid, name=name, value=value, display=display, min=0.0, max=1.0)


def compressor(oid=500, *, source="SIDECHAIN", channel="Pre FX", enabled=1.0, class_name="Compressor2"):
    return Obj(
        oid,
        name="Live 8 Compressor",
        class_name=class_name,
        input_routing_type=Obj(oid + 1, display_name=source),
        input_routing_channel=Obj(oid + 2, display_name=channel),
        parameters=[
            parameter(oid + 10, "S/C On", enabled, "On" if enabled else "Off"),
            parameter(oid + 11, "S/C Listen", 0.0, "Off"),
            parameter(oid + 12, "S/C Gain", 0.4, "0.00 dB"),
            parameter(oid + 13, "S/C Mix", 1.0, "100 %"),
            parameter(oid + 14, "S/C EQ On", 0.0, "Off"),
        ],
    )


def rack(oid, child):
    chain = Obj(oid + 1, name="Live 8 Compressor", devices=[child])
    return Obj(oid, name="SIDE CHAIN 8", class_name="AudioEffectGroupDevice", chains=[chain], return_chains=[])


class FakeBridge:
    def __init__(self, tracks, *, returns=None, master=None):
        self._song = Obj(1, tracks=tracks, return_tracks=returns or [], master_track=master or Obj(999, name="Main", devices=[]))
        self.remembered = {}

    def song(self):
        return self._song

    def _object_id(self, obj):
        return obj.oid

    def _remember_object(self, oid, obj):
        self.remembered[oid] = obj

    def _parameter_summary(self, param):
        return {"id": param.oid, "name": param.name, "value": param.value, "display": param.display}

    def _set_signature(self):
        return "sig-sidechain"


def graph(bridge, **params):
    return sidechain_read._rpc_sidechain_graph(bridge, params)


def test_nested_native_compressor_resolves_exact_source_track():
    source = Obj(100, name="SIDECHAIN", devices=[])
    comp = compressor()
    bass = Obj(200, name="BASS", devices=[rack(300, comp)])
    result = graph(FakeBridge([source, bass]))

    assert result["effect_state"] == "NOT_STARTED"
    assert result["set_signature"] == "sig-sidechain"
    assert result["consumer_count"] == 1
    assert result["resolved_consumer_count"] == 1
    row = result["consumers"][0]
    assert row["target"] == {"placement": "track", "id": 200, "name": "BASS", "index": 1}
    assert row["routing_state"] == "RESOLVED"
    assert row["source"]["track"] == {"placement": "track", "id": 100, "name": "SIDECHAIN", "index": 0}
    assert row["source"]["routing_channel"] == "Pre FX"
    assert row["sidechain"]["enabled"] is True
    assert row["sidechain"]["mix"]["display"] == "100 %"
    assert [item["kind"] for item in row["device"]["path"]] == ["device", "chain", "device"]


def test_duplicate_source_name_fails_closed_as_ambiguous():
    first = Obj(100, name="SIDECHAIN", devices=[])
    second = Obj(101, name="SIDECHAIN", devices=[])
    bass = Obj(200, name="BASS", devices=[compressor(source="SIDECHAIN")])
    row = graph(FakeBridge([first, second, bass]))["consumers"][0]
    assert row["routing_state"] == "AMBIGUOUS_SOURCE"
    assert row["source"]["track"] is None
    assert [item["id"] for item in row["source"]["candidates"]] == [100, 101]


def test_disabled_native_sidechain_is_reported_not_erased():
    source = Obj(100, name="SIDECHAIN", devices=[])
    bass = Obj(200, name="BASS", devices=[compressor(enabled=0.0)])
    row = graph(FakeBridge([source, bass]))["consumers"][0]
    assert row["routing_state"] == "DISABLED"
    assert row["sidechain"]["enabled"] is False
    assert row["source"]["track"]["id"] == 100


def test_plugin_device_is_not_guessed_as_supported_sidechain():
    source = Obj(100, name="SIDECHAIN", devices=[])
    plugin = compressor(class_name="PluginDevice")
    bass = Obj(200, name="BASS", devices=[plugin])
    result = graph(FakeBridge([source, bass]))
    assert result["consumers"] == []
    assert result["coverage"]["third_party_plugin_sidechain_routing"] == "UNSUPPORTED"



def test_enabled_sidechain_with_no_input_is_explicit_health_finding():
    bass = Obj(200, name="BASS", devices=[compressor(source="No Input", channel="")])
    result = graph(FakeBridge([bass]))
    row = result["consumers"][0]
    assert row["routing_state"] == "NO_INPUT"
    assert result["routing_state_counts"]["NO_INPUT"] == 1
    assert result["attention_finding_count"] == 1
    assert result["findings"][0]["code"] == "NO_INPUT"


def test_exact_self_source_is_reported_separately_from_normal_route():
    self_track = Obj(100, name="SIDECHAIN", devices=[compressor(source="SIDECHAIN")])
    result = graph(FakeBridge([self_track]))
    row = result["consumers"][0]
    assert row["routing_state"] == "SELF_SOURCE"
    assert row["source"]["track"]["id"] == row["target"]["id"] == 100
    assert result["resolved_consumer_count"] == 1
    assert result["findings"][0]["code"] == "SELF_SOURCE"

def test_device_budget_truncates_before_unbounded_rack_descent():
    source = Obj(100, name="SIDECHAIN", devices=[])
    bass = Obj(200, name="BASS", devices=[rack(300, compressor())])
    result = graph(FakeBridge([source, bass]), max_devices=1)
    assert result["truncated"] is True
    assert result["devices_scanned"] == 1
    assert result["consumers"] == []


def test_installer_only_adds_reviewed_read_method():
    class Target:
        pass

    sidechain_read.install_sidechain_read(Target)
    assert sidechain_read.SIDECHAIN_READ_METHODS == ("sidechain_graph",)
    assert Target._rpc_sidechain_graph is sidechain_read._rpc_sidechain_graph
