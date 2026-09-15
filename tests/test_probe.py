from pathlib import Path

from chibi_audio.probe import render_agent_audio_tap

ROOT = Path(__file__).resolve().parents[1]

def test_probe_is_rendered_for_target_state_path():
    data = render_agent_audio_tap(
        ROOT / "bridge" / "m4l" / "AgentAudioTap.template.amxd",
        ROOT / "bridge" / "m4l" / "AgentAudioTap.maxpat",
        "C:/Users/test/.chibi-audio/agent_audio_tap_command.json",
    )
    assert b"C:/Users/test/.chibi-audio/agent_audio_tap_command.json" in data
    assert b".ableton-live-mcp" not in data
    assert b"ptch" in data
