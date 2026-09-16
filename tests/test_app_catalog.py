from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from chibi_audio.mcp_server import AudioMcpSettings
from chibi_audio.mcp_server_sections import build_mcp_server


READ_ONLY_TOOLS = {
    "analyze_artifact",
    "analyze_audio",
    "analyze_capture_manifest",
    "analyze_harshness_artifact",
    "attribute_master_stress",
    "compare_analysis_reports",
    "device_parameters",
    "diff_parameter_snapshots",
    "get_locators",
    "get_sections",
    "get_song_position",
    "list_audio_analyzers",
    "parameter_snapshot",
    "plan_audition",
    "plan_section_capture",
    "plan_section_evidence",
    "project_snapshot",
    "resolve_section",
    "status",
    "track_mixer_state",
}

WRITE_ADDITIONS = {
    "capture_section",
    "capture_section_evidence",
    "capture_section_master_stress",
    "create_level_matched_ab",
    "rename_track",
    "set_device_enabled",
    "set_device_parameter",
    "set_track_color",
    "set_track_mute",
    "set_track_pan",
    "set_track_solo",
    "set_track_volume",
}


class FakeFacade:
    def call(self, name, arguments=None):
        if name == "status":
            return {"capabilities": {"read": ["set_summary"]}}
        return {"tool": name, "arguments": arguments or {}}


class FakeLocatorClient:
    def locators(self, *, limit=256):
        return {
            "set_signature": "sig-catalog",
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


class FakeArtifactWorkflows:
    pass


def names(server):
    return {tool.name for tool in asyncio.run(server.list_tools())}


def make_server(tmp_path, *, allow_writes: bool):
    return build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=allow_writes),
        facade=FakeFacade(),
        locator_client=FakeLocatorClient(),
        analysis_bridge=FakeAnalysisBridge(),
        artifact_workflows=FakeArtifactWorkflows(),
    )


def test_read_only_chatgpt_app_catalog_is_exact(tmp_path):
    assert names(make_server(tmp_path, allow_writes=False)) == READ_ONLY_TOOLS


def test_write_enabled_chatgpt_app_catalog_only_adds_reviewed_effects(tmp_path):
    write_names = names(make_server(tmp_path, allow_writes=True))
    assert write_names == READ_ONLY_TOOLS | WRITE_ADDITIONS
    assert write_names - READ_ONLY_TOOLS == WRITE_ADDITIONS
