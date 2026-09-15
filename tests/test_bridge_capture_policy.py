from pathlib import Path


def test_capture_seek_sets_absolute_song_time():
    source = Path("bridge/ChibiAudioBridge/bridge.py").read_text(encoding="utf-8")
    assert "song.current_song_time = time_value" in source
    assert "song.jump_by(time_value - current)" not in source


def test_audio_tap_requests_float32_recording():
    source = Path("bridge/m4l/agent_audio_tap.js").read_text(encoding="utf-8")
    assert 'outlet(0, "samptype", "float32")' in source
