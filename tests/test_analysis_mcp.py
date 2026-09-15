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
    def __init__(self):
        self.calls = []

    def capability_report(self):
        self.calls.append(("list",))
        return {"available": True, "analyzers": [{"name": "fake"}]}

    def analyze_audio(self, artifact, capabilities, **kwargs):
        self.calls.append(("audio", artifact, tuple(capabilities), kwargs))
        return {"artifact": artifact, "requested_capabilities": list(capabilities)}

    def analyze_capture_manifest(self, manifest, capabilities, **kwargs):
        self.calls.append(("manifest", manifest, tuple(capabilities), kwargs))
        return {"capture_manifest": manifest, "requested_capabilities": list(capabilities)}

    def compare_reports(self, left, right, **kwargs):
        self.calls.append(("compare", left, right, kwargs))
        return {"direction": "right_minus_left", **kwargs}


def tools(server):
    return {item.name: item for item in asyncio.run(server.list_tools())}


def make_server(tmp_path):
    bridge = FakeAnalysisBridge()
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=False),
        facade=FakeFacade(),
        locator_client=FakeLocatorClient(),
        analysis_bridge=bridge,
    )
    return server, bridge


def test_analysis_tools_are_present_and_read_only(tmp_path):
    server, _bridge = make_server(tmp_path)
    catalog = tools(server)
    for name in (
        "list_audio_analyzers",
        "analyze_audio",
        "analyze_capture_manifest",
        "compare_analysis_reports",
    ):
        assert name in catalog
        assert catalog[name].annotations.read_only_hint is True
        assert catalog[name].annotations.destructive_hint is False


def test_analysis_tools_forward_explicit_scope_and_cost(tmp_path):
    server, bridge = make_server(tmp_path)

    result = asyncio.run(
        server.call_tool(
            "analyze_audio",
            {
                "artifact": "captures/drop.wav",
                "capabilities": ["audio.levels", "audio.spectrum"],
                "max_cost": "MODERATE",
                "start_seconds": 1.25,
                "end_seconds": 2.5,
            },
        )
    )
    assert result.structured_content["artifact"] == "captures/drop.wav"
    assert bridge.calls[-1] == (
        "audio",
        "captures/drop.wav",
        ("audio.levels", "audio.spectrum"),
        {"max_cost": "MODERATE", "start_seconds": 1.25, "end_seconds": 2.5},
    )

    result = asyncio.run(
        server.call_tool(
            "analyze_capture_manifest",
            {
                "manifest": "section-captures/drop/manifest.json",
                "capabilities": ["audio.levels"],
                "tap_ids": [1, 3],
                "max_cost": "CHEAP",
            },
        )
    )
    assert result.structured_content["capture_manifest"].endswith("manifest.json")
    assert bridge.calls[-1][0:3] == (
        "manifest",
        "section-captures/drop/manifest.json",
        ("audio.levels",),
    )
    assert bridge.calls[-1][3] == {"tap_ids": [1, 3], "max_cost": "CHEAP"}


def test_compare_reports_does_not_reopen_audio(tmp_path):
    server, bridge = make_server(tmp_path)
    left = {"schema_version": "fake/v1", "measurements": {"audio.levels": {"rms_dbfs": -12.0}}}
    right = {"schema_version": "fake/v1", "measurements": {"audio.levels": {"rms_dbfs": -11.0}}}
    result = asyncio.run(
        server.call_tool(
            "compare_analysis_reports",
            {"left": left, "right": right, "left_label": "A", "right_label": "B"},
        )
    )
    assert result.structured_content["direction"] == "right_minus_left"
    assert bridge.calls[-1] == (
        "compare",
        left,
        right,
        {"left_label": "A", "right_label": "B"},
    )


def test_read_only_server_still_omits_capture_section(tmp_path):
    server, _bridge = make_server(tmp_path)
    assert "capture_section" not in tools(server)
