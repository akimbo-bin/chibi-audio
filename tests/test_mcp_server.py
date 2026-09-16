import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from chibi_audio.mcp_server import AudioMcpSettings, build_mcp_server


class FakeFacade:
    def __init__(self):
        self.calls = []

    def call(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "status":
            return {"capabilities": {"read": ["set_summary"]}}
        return {"tool": name, "arguments": arguments or {}}


def _tool_map(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_settings_default_to_read_only_and_standard_artifact_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = AudioMcpSettings.from_env({})
    assert settings.live_port == 18765
    assert settings.allow_writes is False
    assert settings.artifact_root.name == ".chibi-audio"


def test_settings_parse_write_opt_in_and_artifact_root(tmp_path):
    settings = AudioMcpSettings.from_env(
        {
            "CHIBI_AUDIO_LIVE_PORT": "19001",
            "CHIBI_AUDIO_ARTIFACT_ROOT": str(tmp_path),
            "CHIBI_AUDIO_MCP_ALLOW_WRITES": "true",
        }
    )
    assert settings.live_port == 19001
    assert settings.allow_writes is True
    assert settings.artifact_root == tmp_path.resolve()


def test_invalid_live_port_fails_closed():
    with pytest.raises(ValueError, match="between 1 and 65535"):
        AudioMcpSettings.from_env({"CHIBI_AUDIO_LIVE_PORT": "70000"})


def test_read_only_server_omits_all_mutation_tools(tmp_path):
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=False),
        facade=FakeFacade(),
    )
    tools = _tool_map(server)
    assert {
        "status",
        "project_snapshot",
        "device_parameters",
        "track_mixer_state",
        "plan_audition",
        "parameter_snapshot",
        "diff_parameter_snapshots",
        "analyze_artifact",
        "analyze_harshness_artifact",
    }.issubset(tools)
    assert not {
        "set_track_volume",
        "set_track_pan",
        "set_track_mute",
        "set_track_solo",
        "rename_track",
        "set_track_color",
        "set_device_parameter",
        "set_device_enabled",
    }.intersection(tools)
    assert all(tool.annotations.read_only_hint is True for tool in tools.values())


def test_write_enabled_server_exposes_only_named_bounded_mutations(tmp_path):
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=True),
        facade=FakeFacade(),
    )
    tools = _tool_map(server)
    expected_writes = {
        "set_track_volume",
        "set_track_pan",
        "set_track_mute",
        "set_track_solo",
        "rename_track",
        "set_track_color",
        "set_device_parameter",
        "set_device_enabled",
    }
    assert expected_writes.issubset(tools)
    assert not {"eval", "execute_python", "raw_live_call", "raw_jsonrpc", "click"}.intersection(tools)
    for name in expected_writes:
        assert tools[name].annotations.read_only_hint is False
        assert tools[name].annotations.destructive_hint is True


def test_status_reports_write_policy_without_mutating(tmp_path):
    facade = FakeFacade()
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=False),
        facade=facade,
    )
    result = asyncio.run(server.call_tool("status", {}))
    assert facade.calls == [("status", {})]
    assert result.structured_content["mcp_writes_enabled"] is False


def test_write_enabled_master_device_parameter_routes_without_track_index(tmp_path):
    facade = FakeFacade()
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=True),
        facade=facade,
    )
    result = asyncio.run(
        server.call_tool(
            "set_device_parameter",
            {
                "placement": "master",
                "expected_track_name": "Main",
                "device_index": 6,
                "expected_device_name": "Pro-L 2",
                "parameter_index": 4,
                "expected_parameter_name": "Gain",
                "expected_current_value": 0.41,
                "value": 0.42,
            },
        )
    )
    assert result.structured_content["tool"] == "set_device_parameter"
    name, args = facade.calls[-1]
    assert name == "set_device_parameter"
    assert args["placement"] == "master"
    assert "track_index" not in args
