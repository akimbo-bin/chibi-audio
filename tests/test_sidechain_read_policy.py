from pathlib import Path


def test_sidechain_read_is_registered_as_read_only_bridge_capability():
    init_source = Path("bridge/ChibiAudioBridge/__init__.py").read_text(encoding="utf-8")
    source = Path("bridge/ChibiAudioBridge/sidechain_read.py").read_text(encoding="utf-8")
    assert "install_sidechain_read(AbletonLiveMCP)" in init_source
    assert "SIDECHAIN_READ_METHODS" in init_source
    assert "sidechain_graph" in source
    assert "effect_state" in source and "NOT_STARTED" in source
    assert "third_party_plugin_sidechain_routing" in source
    for forbidden in ("delete_device", "insert_device", "setattr(", "_rpc_set(", "_rpc_call(", "_rpc_eval", "_rpc_exec"):
        assert forbidden not in source
