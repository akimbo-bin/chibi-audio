import json
from types import SimpleNamespace

import pytest

from chibi_audio.analysis_bridge import AnalysisFabricBridge, AnalysisFabricUnavailable


class FakeRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.capabilities = kwargs.get("capabilities", frozenset())
        self.max_cost = kwargs.get("max_cost", "CHEAP")


class FakeReport:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class FakeDescriptor:
    def to_dict(self):
        return {"name": "fake", "capabilities": ["audio.levels"], "cost": "CHEAP"}


class FakeAnalyzer:
    descriptor = FakeDescriptor()


class FakeRegistry:
    def plan(self, request):
        return (FakeAnalyzer(),)


class FakeService:
    last_request = None

    def __init__(self):
        self.registry = FakeRegistry()

    def capability_report(self):
        return [{"name": "fake", "capabilities": ["audio.levels"], "cost": "CHEAP"}]

    def analyze(self, path, request):
        type(self).last_request = (path, request)
        return FakeReport({"schema_version": "fake/v1", "source_name": path.name})


class FakeAnalysisReport:
    @classmethod
    def from_dict(cls, value):
        return dict(value)


def make_module():
    calls = {"manifest": [], "compare": [], "stress": []}

    def analyze_capture_manifest(path, request, *, tap_ids=None):
        calls["manifest"].append((path, request, tap_ids))
        return {
            "schema_version": "capture-analysis/v1",
            "taps": [
                {
                    "tap_id": 1,
                    "artifact_path": str(path.parent / "tap.wav"),
                    "analysis": {"schema_version": "fake/v1"},
                }
            ],
        }

    def attribute_capture_master_stress(path, **kwargs):
        calls["stress"].append((path, kwargs))
        return {
            "schema_version": "stress/v1",
            "capture_manifest": str(path),
            "effect_state": "NOT_STARTED",
            "sources": [{"source_label": label} for label in kwargs["source_labels"]],
        }

    def compare_reports(left, right, *, left_label, right_label):
        calls["compare"].append((left, right, left_label, right_label))
        return {"direction": "right_minus_left", "left": left_label, "right": right_label}

    module = SimpleNamespace(
        SCHEMA_VERSION="fake/v1",
        AnalysisCapability=lambda value: value,
        AnalysisCost=lambda value: value,
        AnalysisRequest=FakeRequest,
        AnalysisReport=FakeAnalysisReport,
        AudioAnalysisService=FakeService,
        analyze_capture_manifest=analyze_capture_manifest,
        attribute_capture_master_stress=attribute_capture_master_stress,
        compare_reports=compare_reports,
    )
    return module, calls


def test_capability_report_and_audio_request_are_explicit(tmp_path):
    module, _calls = make_module()
    artifact = tmp_path / "audio.wav"
    artifact.write_bytes(b"fake")
    bridge = AnalysisFabricBridge(tmp_path, module=module)

    catalog = bridge.capability_report()
    assert catalog["available"] is True
    assert catalog["schema_version"] == "fake/v1"
    assert catalog["analyzers"][0]["name"] == "fake"

    result = bridge.analyze_audio(
        "audio.wav",
        ["audio.levels", "audio.stereo"],
        max_cost="moderate",
        start_seconds=1.0,
        end_seconds=2.5,
    )
    assert result["artifact"] == "audio.wav"
    _path, request = FakeService.last_request
    assert request.kwargs["capabilities"] == frozenset({"audio.levels", "audio.stereo"})
    assert request.kwargs["max_cost"] == "MODERATE"
    assert request.kwargs["start_seconds"] == 1.0
    assert request.kwargs["end_seconds"] == 2.5


def test_audio_artifact_cannot_escape_root(tmp_path):
    module, _calls = make_module()
    bridge = AnalysisFabricBridge(tmp_path, module=module)
    with pytest.raises(ValueError, match="escapes"):
        bridge.analyze_audio("../outside.wav", ["audio.levels"])
    with pytest.raises(ValueError, match="relative"):
        bridge.analyze_audio(str((tmp_path / "absolute.wav").resolve()), ["audio.levels"])


def test_manifest_analysis_confines_every_final_artifact(tmp_path):
    module, calls = make_module()
    tap = tmp_path / "tap.wav"
    tap.write_bytes(b"tap")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"taps": [{"tap_id": 1, "final": {"path": str(tap)}}]}),
        encoding="utf-8",
    )
    bridge = AnalysisFabricBridge(tmp_path, module=module)

    result = bridge.analyze_capture_manifest(
        "manifest.json",
        ["audio.levels"],
        tap_ids=[1],
        max_cost="CHEAP",
    )
    assert result["capture_manifest"] == "manifest.json"
    assert result["taps"][0]["artifact_path"] == "tap.wav"
    assert calls["manifest"][0][2] == (1,)

    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"outside")
    manifest.write_text(
        json.dumps({"taps": [{"tap_id": 1, "final": {"path": str(outside)}}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outside"):
        bridge.analyze_capture_manifest("manifest.json", ["audio.levels"])


def test_master_stress_bridge_confines_manifest_and_forwards_scope(tmp_path):
    module, calls = make_module()
    taps = []
    for tap_id, label in enumerate(("MASTER_PRE", "MASTER_POST", "BASS", "DRUMS"), start=1):
        artifact = tmp_path / f"{label}.wav"
        artifact.write_bytes(label.encode("ascii"))
        taps.append({"tap_id": tap_id, "final": {"path": artifact.name}})
    manifest = tmp_path / "stress.capture.json"
    manifest.write_text(json.dumps({"taps": taps}), encoding="utf-8")
    bridge = AnalysisFabricBridge(tmp_path, module=module)

    result = bridge.attribute_capture_master_stress(
        "stress.capture.json",
        premaster_label="MASTER_PRE",
        master_label="MASTER_POST",
        source_labels=["BASS", "DRUMS"],
        window_ms=80.0,
        hop_ms=10.0,
        max_latency_ms=250.0,
        low_band_hz=180.0,
        active_threshold_dbfs=-50.0,
        top_stress_fraction=0.2,
    )

    assert result["capture_manifest"] == "stress.capture.json"
    path, kwargs = calls["stress"][0]
    assert path == manifest
    assert kwargs == {
        "premaster_label": "MASTER_PRE",
        "master_label": "MASTER_POST",
        "source_labels": ("BASS", "DRUMS"),
        "window_ms": 80.0,
        "hop_ms": 10.0,
        "max_latency_ms": 250.0,
        "low_band_hz": 180.0,
        "active_threshold_dbfs": -50.0,
        "top_stress_fraction": 0.2,
    }


def test_compare_reports_uses_completed_evidence_only(tmp_path):
    module, calls = make_module()
    bridge = AnalysisFabricBridge(tmp_path, module=module)
    result = bridge.compare_reports(
        {"schema_version": "fake/v1", "measurements": {}},
        {"schema_version": "fake/v1", "measurements": {}},
        left_label="before",
        right_label="after",
    )
    assert result["direction"] == "right_minus_left"
    assert calls["compare"][0][2:] == ("before", "after")


def test_missing_analysis_fabric_fails_closed(monkeypatch, tmp_path):
    def missing(_name):
        error = ImportError("missing")
        error.name = "chibi_audio.analysis"
        raise error

    monkeypatch.setattr("chibi_audio.analysis_bridge.importlib.import_module", missing)
    bridge = AnalysisFabricBridge(tmp_path)
    catalog = bridge.capability_report()
    assert catalog["available"] is False
    assert catalog["analyzers"] == []
    with pytest.raises(AnalysisFabricUnavailable, match="unavailable"):
        bridge.analyze_audio("anything.wav", ["audio.levels"])


def test_plan_request_validates_analyzers_without_opening_audio(tmp_path):
    module, _calls = make_module()
    bridge = AnalysisFabricBridge(tmp_path, module=module)
    FakeService.last_request = None
    result = bridge.plan_request(["audio.levels"], max_cost="moderate")
    assert result["available"] is True
    assert result["requested_capabilities"] == ["audio.levels"]
    assert result["max_cost"] == "MODERATE"
    assert result["selected_analyzers"][0]["name"] == "fake"
    assert FakeService.last_request is None
