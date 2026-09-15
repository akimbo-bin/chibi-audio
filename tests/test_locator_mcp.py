import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import chibi_audio.mcp_server_sections as section_server
from chibi_audio.mcp_server import AudioMcpSettings


class FakeFacade:
    def call(self, name, arguments=None):
        if name == "status":
            return {"capabilities": {"read": ["set_summary"]}}
        return {"tool": name, "arguments": arguments or {}}


class FakeLocatorClient:
    def __init__(self):
        self.calls = []

    def locators(self, *, limit=256):
        self.calls.append(limit)
        return {
            "set_signature": "sig-locators",
            "current_song_time": 20.0,
            "last_event_time": 64.0,
            "song_length": 65.0,
            "locator_count": 4,
            "truncated": False,
            "locators": [
                {"index": 0, "id": 201, "name": "Intro", "time": 0.0},
                {"index": 1, "id": 202, "name": "Build", "time": 16.0},
                {"index": 2, "id": 203, "name": "Drop 1", "time": 32.0},
                {"index": 3, "id": 204, "name": "Bridge", "time": 48.0},
            ],
        }


def tool_map(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def make_server(tmp_path, *, allow_writes=False):
    locator = FakeLocatorClient()
    server = section_server.build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=allow_writes),
        facade=FakeFacade(),
        locator_client=locator,
    )
    return server, locator


def test_locator_tools_are_read_only_and_present(tmp_path):
    server, _locator = make_server(tmp_path)
    tools = tool_map(server)
    for name in (
        "get_locators",
        "get_sections",
        "resolve_section",
        "get_song_position",
        "plan_section_capture",
    ):
        assert name in tools
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].annotations.destructive_hint is False
    assert "capture_section" not in tools


def test_resolve_section_returns_exact_named_beat_range(tmp_path):
    server, locator = make_server(tmp_path)
    result = asyncio.run(server.call_tool("resolve_section", {"name": "drop 1"}))
    assert result.structured_content["name"] == "Drop 1"
    assert result.structured_content["start_beat"] == 32.0
    assert result.structured_content["end_beat"] == 48.0
    assert result.structured_content["set_signature"] == "sig-locators"
    assert locator.calls[-1] == 256


def test_song_position_reports_active_and_adjacent_sections(tmp_path):
    server, _locator = make_server(tmp_path)
    result = asyncio.run(server.call_tool("get_song_position", {}))
    data = result.structured_content
    assert data["beat"] == 20.0
    assert data["active_section"]["name"] == "Build"
    assert data["previous_section"]["name"] == "Intro"
    assert data["next_section"]["name"] == "Drop 1"


def test_plan_section_capture_is_read_only_and_returns_capture_session_payload(tmp_path):
    server, _locator = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool(
            "plan_section_capture",
            {
                "name": "Drop 1",
                "tap_specs": ["1:Main:master", "2:BASS:BASS", "3:DRUMS:DRUMS"],
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "NOT_STARTED"
    assert data["section"]["name"] == "Drop 1"
    assert data["capture_request"]["start_beat"] == 32.0
    assert data["capture_request"]["end_beat"] == 48.0
    assert data["capture_request"]["taps"][0]["target"] == "master"
    assert data["ready_to_execute"] is True


def test_capture_section_is_write_gated_and_forwards_planned_signature(monkeypatch, tmp_path):
    calls = {}

    def fake_run_capture_session(**kwargs):
        calls.update(kwargs)
        target = Path(kwargs["output_dir"]) / "capture-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        return target

    monkeypatch.setattr(section_server, "run_capture_session", fake_run_capture_session)
    server, _locator = make_server(tmp_path, allow_writes=True)
    tools = tool_map(server)
    assert "capture_section" in tools
    assert tools["capture_section"].annotations.read_only_hint is False
    assert tools["capture_section"].annotations.destructive_hint is True

    result = asyncio.run(
        server.call_tool(
            "capture_section",
            {
                "name": "Drop 1",
                "experiment_id": "kiss-drop-1",
                "tap_specs": ["1:Main:master", "2:BASS:BASS", "3:DRUMS:DRUMS"],
            },
        )
    )
    data = result.structured_content
    assert calls["expected_set_signature"] == "sig-locators"
    assert calls["start_beat"] == 32.0
    assert calls["end_beat"] == 48.0
    assert [tap.target for tap in calls["taps"]] == ["master", "BASS", "DRUMS"]
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["manifest_artifact"] == "section-captures/kiss-drop-1/capture-manifest.json"
