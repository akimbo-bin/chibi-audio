from pathlib import Path


def test_locator_read_is_registered_without_generic_call_surface():
    init_source = Path("bridge/ChibiAudioBridge/__init__.py").read_text(encoding="utf-8")
    locator_source = Path("bridge/ChibiAudioBridge/locator_read.py").read_text(encoding="utf-8")
    assert "LOCATOR_READ_METHODS" in init_source
    assert "install_locator_read" in init_source
    assert 'LOCATOR_READ_METHODS = ("locators",)' in locator_source
    assert "cue_points" in locator_source
    assert '"name"' in locator_source
    assert '"time"' in locator_source
    assert "_rpc_call" not in locator_source
    assert "_rpc_set" not in locator_source
