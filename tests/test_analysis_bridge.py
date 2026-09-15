import json
from types import SimpleNamespace

import pytest

from chibi_audio.analysis_bridge import AnalysisFabricBridge, AnalysisFabricUnavailable


class FakeRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeReport:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return dict(self.payload)


class FakeService:
    last_request = None

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
    calls = {"manifest": [], "compare": []}

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
