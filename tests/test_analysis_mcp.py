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

    def attribute_capture_master_stress(self, manifest, **kwargs):
        self.calls.append(("stress", manifest, kwargs))
        return {"capture_manifest": manifest, "effect_state": "NOT_STARTED", "sources": []}

    def attribute_capture_bus_contribution(self, manifest, **kwargs):
        self.calls.append(("bus_contribution", manifest, kwargs))
        return {
            "capture_manifest": manifest,
            "effect_state": "NOT_STARTED",
            "reference_bus": {"source_label": kwargs["bus_label"]},
            "sources": [],
            "leaders": {},
        }

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
        "attribute_master_stress",
        "attribute_bus_contribution",
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


def test_master_stress_tool_is_read_only_and_forwards_explicit_labels(tmp_path):
    server, bridge = make_server(tmp_path)
    result = asyncio.run(
        server.call_tool(
            "attribute_master_stress",
            {
                "manifest": "section-captures/drop/manifest.json",
                "premaster_label": "MASTER_PRE",
                "master_label": "MASTER_POST",
                "source_labels": ["BASS", "DRUMS"],
                "window_ms": 80.0,
                "hop_ms": 10.0,
                "max_latency_ms": 250.0,
                "low_band_hz": 180.0,
                "active_threshold_dbfs": -50.0,
                "top_stress_fraction": 0.2,
            },
        )
    )
    assert result.structured_content["effect_state"] == "NOT_STARTED"
    assert bridge.calls[-1] == (
        "stress",
        "section-captures/drop/manifest.json",
        {
            "premaster_label": "MASTER_PRE",
            "master_label": "MASTER_POST",
            "source_labels": ["BASS", "DRUMS"],
            "window_ms": 80.0,
            "hop_ms": 10.0,
            "max_latency_ms": 250.0,
            "low_band_hz": 180.0,
            "active_threshold_dbfs": -50.0,
            "top_stress_fraction": 0.2,
        },
    )



def test_bus_contribution_tool_is_read_only_and_forwards_explicit_scope(tmp_path):
    server, bridge = make_server(tmp_path)
    catalog = tools(server)
    assert catalog["attribute_bus_contribution"].annotations.read_only_hint is True
    assert catalog["attribute_bus_contribution"].annotations.destructive_hint is False

    result = asyncio.run(
        server.call_tool(
            "attribute_bus_contribution",
            {
                "manifest": "section-captures/drop/manifest.json",
                "bus_label": "DRUMS_POST",
                "source_labels": ["KICK", "SNARE"],
                "window_ms": 80.0,
                "hop_ms": 10.0,
                "low_band_hz": 180.0,
                "active_threshold_dbfs": -50.0,
                "top_bus_fraction": 0.2,
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "NOT_STARTED"
    assert bridge.calls[-1] == (
        "bus_contribution",
        "section-captures/drop/manifest.json",
        {
            "bus_label": "DRUMS_POST",
            "source_labels": ["KICK", "SNARE"],
            "window_ms": 80.0,
            "hop_ms": 10.0,
            "low_band_hz": 180.0,
            "active_threshold_dbfs": -50.0,
            "top_bus_fraction": 0.2,
        },
    )


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
    assert "capture_section_bus_contribution" not in catalog


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


def test_capture_section_master_stress_preflights_layout_before_capture(monkeypatch, tmp_path):
    calls = []

    def forbidden_capture(**kwargs):
        calls.append(kwargs)
        raise AssertionError("capture must not start after invalid tap preflight")

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", forbidden_capture)
    server, _bridge = make_server(tmp_path, allow_writes=True)
    with pytest.raises(Exception, match="premaster_label must select a master target captured at pre_fx"):
        asyncio.run(
            server.call_tool(
                "capture_section_master_stress",
                {
                    "name": "Intro",
                    "experiment_id": "bad-stress-layout",
                    "tap_specs": [
                        "211:MASTER_PRE:master",
                        "212:MASTER_POST:master",
                        "213:BASS_POST:BASS",
                    ],
                    "premaster_label": "MASTER_PRE",
                    "master_label": "MASTER_POST",
                    "source_labels": ["BASS_POST"],
                },
            )
        )
    assert calls == []


def test_capture_section_master_stress_runs_managed_capture_then_attribution(monkeypatch, tmp_path):
    events = []
    capture_calls = {}

    class OrderedStressBridge(FakeAnalysisBridge):
        def attribute_capture_master_stress(self, manifest, **kwargs):
            events.append("attribute")
            result = super().attribute_capture_master_stress(manifest, **kwargs)
            result["alignment"] = {"post_delay_ms": 110.0}
            return result

    def fake_run_managed_capture_session(**kwargs):
        events.append("capture")
        capture_calls.update(kwargs)
        target = tmp_path / "section-captures" / "kiss-stress-proof" / "capture-manifest.json"
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
    bridge = OrderedStressBridge()
    server, _bridge = make_server(tmp_path, allow_writes=True, bridge=bridge)
    catalog = tools(server)
    assert catalog["capture_section_master_stress"].annotations.read_only_hint is False
    assert catalog["capture_section_master_stress"].annotations.destructive_hint is True

    result = asyncio.run(
        server.call_tool(
            "capture_section_master_stress",
            {
                "name": "Intro",
                "experiment_id": "kiss-stress-proof",
                "tap_specs": [
                    "211:MASTER_PRE:pre_fx:master",
                    "212:MASTER_POST:post_fx:master",
                    "213:BASS_POST:BASS",
                    "214:DRUMS_POST:DRUMS",
                ],
                "premaster_label": "MASTER_PRE",
                "master_label": "MASTER_POST",
                "source_labels": ["BASS_POST", "DRUMS_POST"],
                "window_ms": 80.0,
                "hop_ms": 10.0,
                "max_latency_ms": 250.0,
                "low_band_hz": 180.0,
                "active_threshold_dbfs": -50.0,
                "top_stress_fraction": 0.2,
            },
        )
    )
    data = result.structured_content
    assert events == ["capture", "attribute"]
    assert capture_calls["expected_set_signature"] == "sig-sections"
    assert capture_calls["include_analysis"] is False
    assert capture_calls["remove_created_after"] is True
    assert [(tap.source_label, tap.signal_point, tap.target) for tap in capture_calls["taps"]] == [
        ("MASTER_PRE", "pre_fx", "master"),
        ("MASTER_POST", "post_fx", "master"),
        ("BASS_POST", "post_fx", "BASS"),
        ("DRUMS_POST", "post_fx", "DRUMS"),
    ]
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "COMPLETED"
    assert data["analysis_error"] is None
    assert data["manifest_artifact"] == "section-captures/kiss-stress-proof/capture-manifest.json"
    assert data["analysis"]["alignment"]["post_delay_ms"] == 110.0
    assert bridge.calls[-1] == (
        "stress",
        data["manifest_artifact"],
        data["attribution_request"],
    )


def test_capture_section_master_stress_preserves_confirmed_capture_when_attribution_fails(monkeypatch, tmp_path):
    class FailingStressBridge(FakeAnalysisBridge):
        def attribute_capture_master_stress(self, manifest, **kwargs):
            raise RuntimeError("private attribution implementation failure")

    def fake_run_managed_capture_session(**kwargs):
        target = tmp_path / "section-captures" / "kiss-stress-fails" / "capture-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(
            manifest_path=target,
            topology=SimpleNamespace(
                final_set_signature="sig-prepared",
                as_dict=lambda: {"initial_set_signature": "sig-sections", "final_set_signature": "sig-prepared", "taps": []},
            ),
            restore={"final_set_signature": "sig-sections", "remove_created": True, "actions": []},
        )

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", fake_run_managed_capture_session)
    server, _bridge = make_server(tmp_path, allow_writes=True, bridge=FailingStressBridge())
    result = asyncio.run(
        server.call_tool(
            "capture_section_master_stress",
            {
                "name": "Intro",
                "experiment_id": "kiss-stress-fails",
                "tap_specs": [
                    "211:MASTER_PRE:pre_fx:master",
                    "212:MASTER_POST:post_fx:master",
                    "213:BASS_POST:BASS",
                ],
                "premaster_label": "MASTER_PRE",
                "master_label": "MASTER_POST",
                "source_labels": ["BASS_POST"],
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "FAILED"
    assert data["analysis"] is None
    assert data["manifest_artifact"] == "section-captures/kiss-stress-fails/capture-manifest.json"
    assert data["analysis_error"] == "Chibi Audio analysis fabric could not safely complete post-capture analysis."
    assert "private attribution implementation failure" not in data["analysis_error"]


def test_capture_section_bus_contribution_preflights_layout_before_capture(monkeypatch, tmp_path):
    calls = []

    def forbidden_capture(**kwargs):
        calls.append(kwargs)
        raise AssertionError("capture must not start after invalid bus-contribution tap preflight")

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", forbidden_capture)
    server, _bridge = make_server(tmp_path, allow_writes=True)

    with pytest.raises(Exception, match="bus_label must select the reference bus captured at post_fx"):
        asyncio.run(
            server.call_tool(
                "capture_section_bus_contribution",
                {
                    "name": "Intro",
                    "experiment_id": "bad-bus-layout",
                    "tap_specs": [
                        "721:DRUMS_POST:pre_fx:DRUMS",
                        "722:DRUMS_CHILD_1:KICK",
                    ],
                    "bus_label": "DRUMS_POST",
                    "source_labels": ["DRUMS_CHILD_1"],
                },
            )
        )
    assert calls == []

    with pytest.raises(Exception, match="bus_label must select a non-master track/group tap"):
        asyncio.run(
            server.call_tool(
                "capture_section_bus_contribution",
                {
                    "name": "Intro",
                    "experiment_id": "bad-main-alias",
                    "tap_specs": [
                        "721:DRUMS_POST:main",
                        "722:DRUMS_CHILD_1:KICK",
                    ],
                    "bus_label": "DRUMS_POST",
                    "source_labels": ["DRUMS_CHILD_1"],
                },
            )
        )
    assert calls == []


def test_capture_section_bus_contribution_rejects_duplicate_physical_source_targets_before_capture(
    monkeypatch,
    tmp_path,
):
    calls = []

    def forbidden_capture(**kwargs):
        calls.append(kwargs)
        raise AssertionError("capture must not start after duplicate source-target preflight")

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(section_server, "run_managed_capture_session", forbidden_capture)
    server, _bridge = make_server(tmp_path, allow_writes=True)

    with pytest.raises(Exception, match="source_labels must select distinct physical track targets"):
        asyncio.run(
            server.call_tool(
                "capture_section_bus_contribution",
                {
                    "name": "Intro",
                    "experiment_id": "duplicate-source-target",
                    "tap_specs": [
                        "721:DRUMS_POST:DRUMS",
                        "722:CHILD_A:KICK",
                        "723:CHILD_B:KICK",
                    ],
                    "bus_label": "DRUMS_POST",
                    "source_labels": ["CHILD_A", "CHILD_B"],
                },
            )
        )
    assert calls == []


def test_capture_section_bus_contribution_runs_managed_capture_then_attribution(
    monkeypatch,
    tmp_path,
):
    events = []
    capture_calls = {}

    class OrderedBusBridge(FakeAnalysisBridge):
        def attribute_capture_bus_contribution(self, manifest, **kwargs):
            events.append("attribute")
            result = super().attribute_capture_bus_contribution(manifest, **kwargs)
            result["leaders"] = {
                "rms_correlation_to_bus": {
                    "source_label": "DRUMS_CHILD_2",
                    "value": 0.93,
                }
            }
            return result

    def fake_run_managed_capture_session(**kwargs):
        events.append("capture")
        capture_calls.update(kwargs)
        target = (
            tmp_path
            / "section-captures"
            / "drums-bus-proof"
            / "capture-manifest.json"
        )
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
            restore={
                "final_set_signature": "sig-sections",
                "remove_created": True,
                "actions": [],
            },
        )

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(
        section_server,
        "run_managed_capture_session",
        fake_run_managed_capture_session,
    )
    bridge = OrderedBusBridge()
    server, _bridge = make_server(
        tmp_path,
        allow_writes=True,
        bridge=bridge,
    )
    catalog = tools(server)
    assert catalog["capture_section_bus_contribution"].annotations.read_only_hint is False
    assert catalog["capture_section_bus_contribution"].annotations.destructive_hint is True

    result = asyncio.run(
        server.call_tool(
            "capture_section_bus_contribution",
            {
                "name": "Intro",
                "experiment_id": "drums-bus-proof",
                "tap_specs": [
                    "721:DRUMS_POST:DRUMS",
                    "722:DRUMS_CHILD_1:KICK",
                    "723:DRUMS_CHILD_2:SNARE",
                ],
                "bus_label": "DRUMS_POST",
                "source_labels": ["DRUMS_CHILD_1", "DRUMS_CHILD_2"],
                "window_ms": 80.0,
                "hop_ms": 10.0,
                "low_band_hz": 180.0,
                "active_threshold_dbfs": -50.0,
                "top_bus_fraction": 0.2,
            },
        )
    )
    data = result.structured_content
    assert events == ["capture", "attribute"]
    assert capture_calls["expected_set_signature"] == "sig-sections"
    assert capture_calls["include_analysis"] is False
    assert capture_calls["remove_created_after"] is True
    assert [
        (tap.source_label, tap.signal_point, tap.target)
        for tap in capture_calls["taps"]
    ] == [
        ("DRUMS_POST", "post_fx", "DRUMS"),
        ("DRUMS_CHILD_1", "post_fx", "KICK"),
        ("DRUMS_CHILD_2", "post_fx", "SNARE"),
    ]
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "COMPLETED"
    assert data["analysis_error"] is None
    assert data["manifest_artifact"] == (
        "section-captures/drums-bus-proof/capture-manifest.json"
    )
    assert data["analysis"]["leaders"]["rms_correlation_to_bus"]["value"] == 0.93
    assert bridge.calls[-1] == (
        "bus_contribution",
        data["manifest_artifact"],
        data["attribution_request"],
    )


def test_capture_section_bus_contribution_preserves_confirmed_capture_when_analysis_fails(
    monkeypatch,
    tmp_path,
):
    class FailingBusBridge(FakeAnalysisBridge):
        def attribute_capture_bus_contribution(self, manifest, **kwargs):
            raise RuntimeError("private bus-contribution implementation failure")

    def fake_run_managed_capture_session(**kwargs):
        target = (
            tmp_path
            / "section-captures"
            / "drums-bus-fails"
            / "capture-manifest.json"
        )
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
            restore={
                "final_set_signature": "sig-sections",
                "remove_created": True,
                "actions": [],
            },
        )

    import chibi_audio.mcp_server_sections as section_server

    monkeypatch.setattr(
        section_server,
        "run_managed_capture_session",
        fake_run_managed_capture_session,
    )
    server, _bridge = make_server(
        tmp_path,
        allow_writes=True,
        bridge=FailingBusBridge(),
    )
    result = asyncio.run(
        server.call_tool(
            "capture_section_bus_contribution",
            {
                "name": "Intro",
                "experiment_id": "drums-bus-fails",
                "tap_specs": [
                    "721:DRUMS_POST:DRUMS",
                    "722:DRUMS_CHILD_1:KICK",
                ],
                "bus_label": "DRUMS_POST",
                "source_labels": ["DRUMS_CHILD_1"],
            },
        )
    )
    data = result.structured_content
    assert data["effect_state"] == "STARTED_CONFIRMED"
    assert data["analysis_state"] == "FAILED"
    assert data["analysis"] is None
    assert data["manifest_artifact"] == (
        "section-captures/drums-bus-fails/capture-manifest.json"
    )
    assert data["analysis_error"] == (
        "Chibi Audio analysis fabric could not safely complete post-capture analysis."
    )
    assert "private bus-contribution implementation failure" not in data["analysis_error"]
