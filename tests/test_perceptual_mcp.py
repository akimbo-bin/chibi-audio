import asyncio
from pathlib import Path
import numpy as np
import pytest
pytest.importorskip("mcp")
import chibi_audio.mcp_server_perception as perception_server
from chibi_audio.mcp_server import AudioMcpSettings
from chibi_audio.mcp_server_perception import build_mcp_server
class FakeFacade:
    def call(self, name, arguments=None):
        if name == "status":
            return {"capabilities": {"read": []}}
        return {"tool": name, "arguments": arguments or {}}
def tool_map(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}
def make_server(tmp_path):
    return build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=False),
        facade=FakeFacade(),
    )
def test_perceptual_mcp_tools_are_read_only_and_present(tmp_path):
    server = make_server(tmp_path)
    tools = tool_map(server)
    for name in (
        "get_translation_profiles",
        "analyze_translation_artifact",
        "analyze_perceptual_bands_artifact",
        "analyze_bass_survivability",
    ):
        assert name in tools
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].annotations.destructive_hint is False
def test_translation_tool_resolves_confined_artifact_and_profiles(tmp_path, monkeypatch):
    capture = tmp_path / "drop.wav"
    capture.write_bytes(b"fixture")
    seen = {}
    def fake_report(path, *, profiles=None, **_kwargs):
        seen["path"] = Path(path)
        seen["profiles"] = profiles
        return {"kind": "translation"}
    monkeypatch.setattr(perception_server, "translation_report", fake_report)
    server = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool(
            "analyze_translation_artifact",
            {"artifact": "drop.wav", "profiles": ["phone_like", "mono"]},
        )
    )
    assert result.structured_content == {"kind": "translation"}
    assert seen == {"path": capture.resolve(), "profiles": ["phone_like", "mono"]}
def test_erb_tool_uses_fixed_decode_rate_and_bounded_band_count(tmp_path, monkeypatch):
    capture = tmp_path / "drop.wav"
    capture.write_bytes(b"fixture")
    seen = {}
    def fake_decode(path, sample_rate=48000):
        seen["decode"] = (Path(path), sample_rate)
        return np.zeros((64, 2), dtype=np.float64)
    def fake_erb(audio, sample_rate, *, band_count=24, **_kwargs):
        seen["erb"] = (audio.shape, sample_rate, band_count)
        return {"kind": "erb"}
    monkeypatch.setattr(perception_server, "decode_audio", fake_decode)
    monkeypatch.setattr(perception_server, "erb_band_profile_array", fake_erb)
    server = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool("analyze_perceptual_bands_artifact", {"artifact": "drop.wav", "band_count": 32})
    )
    assert result.structured_content == {"kind": "erb"}
    assert seen["decode"] == (capture.resolve(), 48000)
    assert seen["erb"] == ((64, 2), 48000, 32)
def test_bass_tool_resolves_source_and_optional_masker(tmp_path, monkeypatch):
    source = tmp_path / "bass.wav"
    masker = tmp_path / "minus-bass.wav"
    source.write_bytes(b"source")
    masker.write_bytes(b"masker")
    seen = {}
    def fake_bass(source_path, **kwargs):
        seen["source"] = Path(source_path)
        seen.update(kwargs)
        return {"kind": "bass"}
    monkeypatch.setattr(perception_server, "analyze_bass_harmonic_survivability", fake_bass)
    server = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool(
            "analyze_bass_survivability",
            {
                "source_artifact": "bass.wav",
                "masker_artifact": "minus-bass.wav",
                "fundamental_hz": 50.0,
                "profile": "phone_like",
                "harmonics": 6,
            },
        )
    )
    assert result.structured_content == {"kind": "bass"}
    assert seen["source"] == source.resolve()
    assert seen["masker_path"] == masker.resolve()
    assert seen["fundamental_hz"] == 50.0
    assert seen["profile"] == "phone_like"
    assert seen["harmonics"] == 6
