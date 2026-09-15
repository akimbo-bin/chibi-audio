from pathlib import Path


def test_capture_seek_sets_absolute_song_time():
    source = Path("bridge/ChibiAudioBridge/bridge.py").read_text(encoding="utf-8")
    assert "song.current_song_time = time_value" in source
    assert "song.jump_by(time_value - current)" not in source


def test_audio_tap_requests_float32_recording():
    source = Path("bridge/m4l/agent_audio_tap.js").read_text(encoding="utf-8")
    assert 'outlet(0, "samptype", "float32")' in source



def test_chibitap_surface_is_typed_and_does_not_expose_generic_loading():
    source = Path("bridge/ChibiAudioBridge/bridge.py").read_text(encoding="utf-8")
    assert "def _rpc_chibitap_setup" in source
    assert "def _rpc_chibitap_configure" in source
    capture_line = next(line for line in source.splitlines() if line.startswith("MODEL_CAPTURE_METHODS"))
    assert "chibitap_setup" in capture_line
    assert "chibitap_configure" in capture_line
    assert "load_device" not in capture_line
    assert "track_insert_device" not in capture_line
