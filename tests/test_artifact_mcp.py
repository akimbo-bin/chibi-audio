from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from chibi_audio.mcp_server import AudioMcpSettings
from chibi_audio.mcp_server_sections import build_mcp_server


class FakeFacade:
    def call(self, name, arguments=None):
        if name == "status":
            return {"capabilities": {"read": ["set_summary"]}}
        return {"tool": name, "arguments": arguments or {}}


class FakeLocatorClient:
    def locators(self, *, limit=256):
        return {
            "set_signature": "sig-sections",
            "current_song_time": 0.0,
            "last_event_time": 64.0,
            "song_length": 64.0,
            "locator_count": 1,
            "truncated": False,
            "locators": [{"index": 0, "id": 1, "name": "Intro", "time": 0.0}],
        }


class FakeAnalysisBridge:
    def capability_report(self):
        return {"available": True, "analyzers": []}

    def plan_request(self, capabilities, **kwargs):
        return {"requested_capabilities": list(capabilities), **kwargs}


class FakeArtifactWorkflows:
    def __init__(self):
        self.calls = []

    def create_level_matched_ab(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "effect_state": "STARTED_CONFIRMED",
            "effect_type": "artifact_creation",
            "comparison_id": kwargs["comparison_id"],
            "manifest_artifact": f"ab-comparisons/{kwargs['comparison_id']}/manifest.json",
            "variants": [],
        }


def tool_map(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def make_server(tmp_path, *, allow_writes: bool):
    artifacts = FakeArtifactWorkflows()
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=allow_writes),
        facade=FakeFacade(),
        locator_client=FakeLocatorClient(),
        analysis_bridge=FakeAnalysisBridge(),
        artifact_workflows=artifacts,
    )
    return server, artifacts


def test_read_only_app_omits_level_match_artifact_writer(tmp_path):
    server, _artifacts = make_server(tmp_path, allow_writes=False)
    assert "create_level_matched_ab" not in tool_map(server)


def test_write_enabled_app_exposes_non_destructive_level_match_writer(tmp_path):
    server, artifacts = make_server(tmp_path, allow_writes=True)
    tools = tool_map(server)
    tool = tools["create_level_matched_ab"]
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is False

    result = asyncio.run(
        server.call_tool(
            "create_level_matched_ab",
            {
                "left_artifact": "section-captures/baseline/main.wav",
                "right_artifact": "section-captures/candidate/main.wav",
                "comparison_id": "drop-1-ab",
                "left_label": "baseline",
                "right_label": "candidate",
                "verification_tolerance_lu": 0.2,
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["effect_type"] == "artifact_creation"
    assert data["manifest_artifact"] == "ab-comparisons/drop-1-ab/manifest.json"
    assert artifacts.calls == [
        {
            "left_artifact": "section-captures/baseline/main.wav",
            "right_artifact": "section-captures/candidate/main.wav",
            "comparison_id": "drop-1-ab",
            "left_label": "baseline",
            "right_label": "candidate",
            "verification_tolerance_lu": 0.2,
        }
    ]
