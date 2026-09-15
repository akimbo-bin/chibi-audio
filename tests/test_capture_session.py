import json
from pathlib import Path

import pytest

from chibi_audio.capture import CaptureArtifact, CaptureError
from chibi_audio.capture_session import (
    CaptureSessionTap,
    parse_session_tap,
    resolve_session_taps,
    run_capture_session,
)


class FakeReadClient:
    def __init__(self):
        self.summary = {
            "tempo": 120.0,
            "set_signature": "sig-1",
            "tracks": [
                {
                    "id": 200,
                    "index": 34,
                    "name": "BASS",
                    "devices": [{"id": 201, "name": "ChibiTap"}],
                },
            ],
            "master_track": {
                "id": 100,
                "name": "Main",
                "devices": [{"id": 101, "name": "ChibiTap"}],
            },
        }

    def set_summary(self, **_kwargs):
        return self.summary

    def call(self, method, params):
        if method == "device_parameters":
            device_id = int(params["ref"]["id"])
            tap_id = 1 if device_id == 101 else 2
            return [
                {"name": "Capture", "value": 0.0, "display": "Off"},
                {"name": "Tap ID", "value": tap_id / 9999.0, "display": str(tap_id)},
            ]
        if method == "get":
            return {
                "properties": {
                    "name": "Test Set",
                    "file_path": "C:/test/Test Set.als",
                    "current_song_time": 0.0,
                }
            }
        raise AssertionError(method)


class StaleCaptureReadClient(FakeReadClient):
    def __init__(self):
        super().__init__()
        self.main_capture_reads = 0

    def call(self, method, params):
        if method == "device_parameters" and int(params["ref"]["id"]) == 101:
            self.main_capture_reads += 1
            if self.main_capture_reads == 1:
                return [
                    {"name": "Capture", "value": 1.0, "display": "On"},
                    {"name": "Tap ID", "value": 1 / 9999.0, "display": "1"},
                ]
        return super().call(method, params)


class FakeCaptureClient:
    instances = []

    def __init__(self, **_kwargs):
        self.calls = []
        self.time = 0.0
        self.playing = False
        type(self).instances.append(self)

    def transport(self, action="status", *, time=None, end_time=None, **kwargs):
        self.calls.append(("transport", action, time, end_time, kwargs))
        result = {"playing": self.playing, "time": self.time}
        if action == "play_until":
            self.time = float(time)
            self.end_time = float(end_time)
            self.playing = True
            result = {
                "playing": True,
                "time": self.time,
                "scheduled_start_time": self.time,
                "scheduled_end_time": self.end_time,
            }
        elif action == "status" and self.playing:
            self.time = self.end_time
            self.playing = False
            result = {
                "playing": False,
                "time": self.time,
                "last_scheduled_stop_time": self.time,
            }
        elif action == "stop":
            self.playing = False
            result = {"playing": False, "time": self.time}
        return result

    def configure_chibitap(self, **kwargs):
        self.calls.append(("configure", kwargs))
        return {"changed": True}


def test_parse_and_resolve_session_taps():
    spec = parse_session_tap("2:BASS:BASS")
    assert spec == CaptureSessionTap(2, "BASS", "BASS")

    reader = FakeReadClient()
    resolved = resolve_session_taps(
        reader,
        reader.summary,
        [CaptureSessionTap(1, "Main", "master"), spec],
    )
    assert [(tap.tap_id, tap.track_name, tap.device_id) for tap in resolved] == [
        (1, "Main", 101),
        (2, "BASS", 201),
    ]
    assert resolved[0].placement == "master"
    assert resolved[1].track_index == 34

    with pytest.raises(CaptureError, match="duplicate tap_id"):
        resolve_session_taps(
            reader,
            reader.summary,
            [CaptureSessionTap(1, "Main", "master"), CaptureSessionTap(1, "Bass", "BASS")],
        )


def test_resolve_session_taps_rechecks_transient_stale_capture_state(monkeypatch):
    import chibi_audio.capture_session as session

    reader = StaleCaptureReadClient()
    monkeypatch.setattr(session.time, "sleep", lambda _seconds: None)
    resolved = resolve_session_taps(
        reader,
        reader.summary,
        [CaptureSessionTap(1, "Main", "master")],
    )
    assert resolved[0].tap_id == 1
    assert reader.main_capture_reads == 2


def test_run_capture_session_coordinates_and_records_provenance(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    FakeCaptureClient.instances.clear()
    reader = FakeReadClient()
    reader.summary["tracks"][0]["mute"] = False
    reader.summary["tracks"][0]["solo"] = False
    reader.summary["tracks"].append(
        {
            "id": 300,
            "index": 51,
            "name": "52-Serum 2",
            "mute": False,
            "solo": True,
            "devices": [],
        }
    )
    monkeypatch.setattr(session, "LiveBridgeClient", lambda **_kwargs: reader)
    monkeypatch.setattr(session, "LiveCaptureClient", FakeCaptureClient)
    monkeypatch.setattr(session.time, "sleep", lambda _seconds: None)

    raw_paths = {
        1: tmp_path / "raw-main.wav",
        2: tmp_path / "raw-bass.wav",
    }
    for path in raw_paths.values():
        path.write_bytes(b"raw")

    monkeypatch.setattr(session, "_newest_new_file", lambda _root, tap_id, _before: raw_paths[tap_id])
    monkeypatch.setattr(
        session,
        "wait_for_stable_capture",
        lambda path, **_kwargs: CaptureArtifact(Path(path), 3, f"sha-{Path(path).stem}", 123),
    )

    finalized = {}

    def fake_finalize(**kwargs):
        finalized.update(kwargs)
        out = Path(kwargs["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        manifest = out / "proof__manifest.json"
        manifest.write_text(
            json.dumps({"schema_version": 1, "experiment_id": kwargs["experiment_id"], "taps": []}),
            encoding="utf-8",
        )
        return manifest

    monkeypatch.setattr(session, "finalize_aligned_captures", fake_finalize)

    manifest_path = run_capture_session(
        experiment_id="proof",
        taps=[CaptureSessionTap(1, "Main", "master"), CaptureSessionTap(2, "BASS", "BASS")],
        output_dir=tmp_path / "final",
        start_beat=0.0,
        end_beat=1.0,
        capture_root=tmp_path / "captures",
        include_analysis=False,
        poll_interval=0.01,
        settle_seconds=0.0,
        timeout_margin=2.0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["live_session"]["set_signature"] == "sig-1"
    assert [item["tap_id"] for item in manifest["live_session"]["tap_mapping"]] == [1, 2]
    assert manifest["live_session"]["song"]["file_path"] == "C:/test/Test Set.als"
    mixer_state = manifest["live_session"]["mixer_state"]
    assert [item["name"] for item in mixer_state["active_solos"]] == ["52-Serum 2"]
    assert mixer_state["active_solo_count"] == 1
    assert mixer_state["tap_targets"][0]["solo_suppression_risk"] is False
    assert mixer_state["tap_targets"][1]["solo_suppression_risk"] is True
    assert [item["track_name"] for item in mixer_state["tap_targets"]] == ["Main", "BASS"]
    assert mixer_state["tap_targets"][1]["mute"] is False
    assert mixer_state["tap_targets"][1]["solo"] is False
    assert any("active solo" in warning.lower() for warning in mixer_state["warnings"])
    assert any("BASS" in warning and "suppressed" in warning for warning in mixer_state["warnings"])
    assert finalized["transport_start_beat"] == 0.0
    assert finalized["transport_stop_beat"] == 1.0
    assert [item.tap_id for item in finalized["inputs"]] == [1, 2]

    client = FakeCaptureClient.instances[-1]
    configure_calls = [call[1] for call in client.calls if call[0] == "configure"]
    assert [call["capture_enabled"] for call in configure_calls] == [True, True, False, False]
    assert all(call["expected_set_signature"] == "sig-1" for call in configure_calls)
    transport_actions = [call[1] for call in client.calls if call[0] == "transport"]
    assert transport_actions == ["stop", "play_until", "status"]
