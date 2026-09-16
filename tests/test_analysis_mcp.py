import asyncio
from types import SimpleNamespace

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

    def plan_request(self, capabilities, **kwargs):
        self.calls.append(("plan", tuple(capabilities), kwargs))
        return {
            "available": True,
            "requested_capabilities": list(capabilities),
            "max_cost": kwargs.get("max_cost", "CHEAP"),
            "selected_analyzers": [{"name": "fake"}],
        }

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


def make_server(tmp_path, *, allow_writes=False, bridge=None):
    bridge = bridge or FakeAnalysisBridge()
    server = build_mcp_server(
        AudioMcpSettings(artifact_root=tmp_path, allow_writes=allow_writes),
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
        "plan_section_evidence",
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
    catalog = tools(server)
    assert "capture_section" not in catalog
    assert "capture_section_evidence" not in catalog


def test_plan_section_evidence_combines_locator_capture_and_analysis_without_effects(tmp_path):
    server, bridge = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool(
            "plan_section_evidence",
            {
                "name": "Intro",
                "tap_specs": ["1:Main:master", "2:BASS:BASS"],
                "capabilities": ["audio.levels", "audio.spectrum"],
                "max_cost": "MODERATE",
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "NOT_STARTED"
    assert data["section"]["name"] == "Intro"
    assert data["capture_request"]["start_beat"] == 0.0
    assert data["capture_request"]["end_beat"] == 64.0
    assert data["ready_to_execute"] is True
    assert data["analysis_plan"]["selected_analyzers"][0]["name"] == "fake"
    assert bridge.calls[-1] == (
        "plan",
        ("audio.levels", "audio.spectrum"),
        {"max_cost": "MODERATE"},
    )


def test_capture_section_evidence_preflights_before_capture_and_returns_analysis(monkeypatch, tmp_path):
    events = []
    capture_calls = {}

    class OrderedAnalysisBridge(FakeAnalysisBridge):
        def plan_request(self, capabilities, **kwargs):
            events.append("plan")
            return super().plan_request(capabilities, **kwargs)

        def analyze_capture_manifest(self, manifest, capabilities, **kwargs):
            events.append("analyze")
            return super().analyze_capture_manifest(manifest, capabilities, **kwargs)

    def fake_run_managed_capture_session(**kwargs):
        events.append("capture")
        capture_calls.update(kwargs)
        assert events == ["plan", "capture"]
        target = tmp_path / "section-captures" / "kiss-intro-evidence" / "capture-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            manifest_path=target,
            topology=SimpleNamespace(
                final_set_signature="sig-prepared",
                as_dict=lambda: {
                    "initial_set_signature": "sig-sections",
                    "final_set_signature": "sig-prepared",
                    "taps": [],
                },
            ),
            restore={"final_set_signature": "sig-sections", "remove_created": True, "actions": []},
        )

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", fake_run_managed_capture_session)
    bridge = OrderedAnalysisBridge()
    server, _bridge = make_server(tmp_path, allow_writes=True, bridge=bridge)
    catalog = tools(server)
    assert catalog["capture_section_evidence"].annotations.read_only_hint is False
    assert catalog["capture_section_evidence"].annotations.destructive_hint is True

    result = asyncio.run(
        server.call_tool(
            "capture_section_evidence",
            {
                "name": "Intro",
                "experiment_id": "kiss-intro-evidence",
                "tap_specs": ["1:Main:master", "2:BASS:BASS"],
                "capabilities": ["audio.levels", "audio.spectrum"],
                "max_cost": "MODERATE",
            },
        )
    )
    data = result.structured_content
    assert events == ["plan", "capture", "analyze"]
    assert capture_calls["expected_set_signature"] == "sig-sections"
    assert capture_calls["include_analysis"] is False
    assert capture_calls["remove_created_after"] is True
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "COMPLETED"
    assert data["analysis_error"] is None
    assert data["prepared_set_signature"] == "sig-prepared"
    assert data["manifest_artifact"] == "section-captures/kiss-intro-evidence/capture-manifest.json"
    assert data["analysis_plan"]["selected_analyzers"][0]["name"] == "fake"
    assert data["analysis"]["capture_manifest"] == data["manifest_artifact"]


def test_capture_section_evidence_preserves_confirmed_effect_when_analysis_fails(monkeypatch, tmp_path):
    class FailingAnalysisBridge(FakeAnalysisBridge):
        def analyze_capture_manifest(self, manifest, capabilities, **kwargs):
            self.calls.append(("manifest", manifest, tuple(capabilities), kwargs))
            raise RuntimeError("internal analysis failure detail")

    def fake_run_managed_capture_session(**kwargs):
        target = tmp_path / "section-captures" / "kiss-intro-analysis-fails" / "capture-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            manifest_path=target,
            topology=SimpleNamespace(
                final_set_signature="sig-prepared",
                as_dict=lambda: {
                    "initial_set_signature": "sig-sections",
                    "final_set_signature": "sig-prepared",
                    "taps": [],
                },
            ),
            restore={"final_set_signature": "sig-sections", "remove_created": True, "actions": []},
        )

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", fake_run_managed_capture_session)
    server, _bridge = make_server(tmp_path, allow_writes=True, bridge=FailingAnalysisBridge())
    result = asyncio.run(
        server.call_tool(
            "capture_section_evidence",
            {
                "name": "Intro",
                "experiment_id": "kiss-intro-analysis-fails",
                "tap_specs": ["1:Main:master"],
                "capabilities": ["audio.levels"],
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "FAILED"
    assert data["analysis"] is None
    assert data["manifest_artifact"] == "section-captures/kiss-intro-analysis-fails/capture-manifest.json"
    assert data["analysis_error"] == "Chibi Audio analysis fabric could not safely complete post-capture analysis."
    assert "internal analysis failure detail" not in data["analysis_error"]
