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
        self.device_types = {101: 2, 201: 2, 203: 2}
        self.tap_ids = {101: 1, 201: 2, 203: 3}

    def set_summary(self, **_kwargs):
        return self.summary

    def call(self, method, params):
        if method == "device_parameters":
            device_id = int(params["ref"]["id"])
            tap_id = self.tap_ids[device_id]
            return [
                {"name": "Capture", "value": 0.0, "display": "Off"},
                {"name": "Tap ID", "value": tap_id / 9999.0, "display": str(tap_id)},
            ]
        if method == "get":
            ref = params.get("ref") or {}
            if ref.get("id") is not None:
                device_id = int(ref["id"])
                return {
                    "id": device_id,
                    "properties": {"type": self.device_types[device_id]},
                }
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
    device_indices = {101: 0, 201: 0, 203: 2}

    def __init__(self, **_kwargs):
        self.init_kwargs = dict(_kwargs)
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
        device_id = kwargs["expected_device_id"]
        return {
            "changed": True,
            "signal_point": kwargs["signal_point"],
            "device_index": self.device_indices[device_id],
            "device": {"id": device_id, "name": "ChibiTap"},
        }


def test_parse_and_resolve_session_taps():
    spec = parse_session_tap("2:BASS:BASS")
    assert spec == CaptureSessionTap(2, "BASS", "BASS")
    assert spec.signal_point == "post_fx"

    pre = parse_session_tap("2:BASS_PRE:pre_fx:BUS:BASS")
    assert pre == CaptureSessionTap(2, "BASS_PRE", "BUS:BASS", "pre_fx")

    legacy_colon = parse_session_tap("2:BASS:BUS:BASS")
    assert legacy_colon == CaptureSessionTap(2, "BASS", "BUS:BASS", "post_fx")

    with pytest.raises(CaptureError, match="signal_point"):
        CaptureSessionTap(2, "BASS", "BASS", "middle")

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
    assert resolved[0].signal_point == "post_fx"
    assert resolved[0].device_index == 0
    assert resolved[1].track_index == 34

    with pytest.raises(CaptureError, match="duplicate tap_id"):
        resolve_session_taps(
            reader,
            reader.summary,
            [CaptureSessionTap(1, "Main", "master"), CaptureSessionTap(1, "Bass", "BASS")],
        )


def test_resolve_session_taps_verifies_pre_fx_and_post_instrument_signal_points():
    reader = FakeReadClient()
    track = reader.summary["tracks"][0]

    track["devices"] = [
        {"id": 201, "name": "ChibiTap"},
        {"id": 202, "name": "Compressor"},
    ]
    reader.device_types[202] = 2
    pre_fx = resolve_session_taps(
        reader,
        reader.summary,
        [CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx")],
    )[0]
    assert pre_fx.signal_point == "pre_fx"
    assert pre_fx.device_index == 0
    assert pre_fx.configure_kwargs()["signal_point"] == "pre_fx"

    track["devices"] = [
        {"id": 301, "name": "Serum"},
        {"id": 201, "name": "ChibiTap"},
        {"id": 202, "name": "Compressor"},
    ]
    reader.device_types[301] = 1
    post_instrument = resolve_session_taps(
        reader,
        reader.summary,
        [CaptureSessionTap(2, "BASS_INST", "BASS", "post_instrument")],
    )[0]
    assert post_instrument.signal_point == "post_instrument"
    assert post_instrument.device_index == 1


def test_resolve_session_taps_selects_multiple_same_track_instances():
    reader = FakeReadClient()
    reader.summary["tracks"][0]["devices"] = [
        {"id": 201, "name": "ChibiTap"},
        {"id": 202, "name": "Compressor"},
        {"id": 203, "name": "ChibiTap"},
    ]
    reader.device_types[202] = 2

    resolved = resolve_session_taps(
        reader,
        reader.summary,
        [
            CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx"),
            CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx"),
        ],
    )

    assert [(tap.tap_id, tap.device_id, tap.device_index, tap.signal_point) for tap in resolved] == [
        (2, 201, 0, "pre_fx"),
        (3, 203, 2, "post_fx"),
    ]


def test_resolve_session_taps_refuses_missing_signal_point_before_capture():
    reader = FakeReadClient()
    reader.summary["tracks"][0]["devices"] = [
        {"id": 202, "name": "Compressor"},
        {"id": 201, "name": "ChibiTap"},
    ]
    reader.device_types[202] = 2

    with pytest.raises(CaptureError, match="is not installed at pre_fx"):
        resolve_session_taps(
            reader,
            reader.summary,
            [CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx")],
        )


def test_resolve_session_taps_refuses_equivalent_points_reusing_same_device():
    reader = FakeReadClient()
    reader.summary["tracks"][0]["devices"] = [
        {"id": 301, "name": "Serum"},
        {"id": 201, "name": "ChibiTap"},
        {"id": 202, "name": "Compressor"},
    ]
    reader.device_types[301] = 1
    reader.device_types[202] = 2

    with pytest.raises(CaptureError, match="same ChibiTap device"):
        resolve_session_taps(
            reader,
            reader.summary,
            [
                CaptureSessionTap(2, "BASS_INST", "BASS", "post_instrument"),
                CaptureSessionTap(3, "BASS_PRE", "BASS", "pre_fx"),
            ],
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


def test_wait_for_capture_quiescence_uses_file_growth(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    tap = CaptureSessionTap(1, "Main", "master")
    path = tmp_path / "chibitap-tap-1-proof.wav"
    snapshots = iter([
        {1: (path, 44)},
        {1: (path, 1024)},
        {1: (path, 1024)},
        {1: (path, 1024)},
    ])
    times = iter([0.0, 0.0, 0.0, 0.0, 0.1, 0.1, 0.2, 0.2, 0.5, 0.5])
    monkeypatch.setattr(session, "_new_capture_snapshot", lambda *_args, **_kwargs: next(snapshots))
    monkeypatch.setattr(session.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(session.time, "sleep", lambda _seconds: None)

    result = session._wait_for_capture_quiescence(
        tmp_path,
        [tap],
        {1: set()},
        timeout=1.0,
        poll_interval=0.01,
        quiet_seconds=0.35,
    )
    assert result[1][1] == 1024


def test_run_capture_session_coordinates_same_track_pre_post_and_records_provenance(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    FakeCaptureClient.instances.clear()
    reader = FakeReadClient()
    reader.summary["tracks"][0]["devices"] = [
        {"id": 201, "name": "ChibiTap"},
        {"id": 202, "name": "Compressor"},
        {"id": 203, "name": "ChibiTap"},
    ]
    reader.device_types[202] = 2
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
    quiescence_capture_states = []

    def fake_wait_for_quiescence(*_args, **_kwargs):
        client = FakeCaptureClient.instances[-1]
        states = [
            call[1]["capture_enabled"]
            for call in client.calls
            if call[0] == "configure"
        ]
        quiescence_capture_states.append(states)
        return {}

    monkeypatch.setattr(session, "_wait_for_capture_quiescence", fake_wait_for_quiescence)

    raw_paths = {
        1: tmp_path / "raw-main.wav",
        2: tmp_path / "raw-bass-pre.wav",
        3: tmp_path / "raw-bass-post.wav",
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
        taps=[
            CaptureSessionTap(1, "Main", "master"),
            CaptureSessionTap(2, "BASS_PRE", "BASS", "pre_fx"),
            CaptureSessionTap(3, "BASS_POST", "BASS", "post_fx"),
        ],
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
    tap_mapping = manifest["live_session"]["tap_mapping"]
    assert [item["tap_id"] for item in tap_mapping] == [1, 2, 3]
    assert [item["device_id"] for item in tap_mapping] == [101, 201, 203]
    assert [item["signal_point"] for item in tap_mapping] == ["post_fx", "pre_fx", "post_fx"]
    assert [item["device_index"] for item in tap_mapping] == [0, 0, 2]
    assert [item["arm_verification"]["device_index"] for item in tap_mapping] == [0, 0, 2]
    assert [item["arm_verification"]["signal_point"] for item in tap_mapping] == [
        "post_fx",
        "pre_fx",
        "post_fx",
    ]
    assert manifest["live_session"]["song"]["file_path"] == "C:/test/Test Set.als"
    mixer_state = manifest["live_session"]["mixer_state"]
    assert [item["name"] for item in mixer_state["active_solos"]] == ["52-Serum 2"]
    assert mixer_state["active_solo_count"] == 1
    assert mixer_state["tap_targets"][0]["solo_suppression_risk"] is False
    assert mixer_state["tap_targets"][1]["solo_suppression_risk"] is True
    assert mixer_state["tap_targets"][2]["solo_suppression_risk"] is True
    assert [item["track_name"] for item in mixer_state["tap_targets"]] == ["Main", "BASS", "BASS"]
    assert [item["signal_point"] for item in mixer_state["tap_targets"]] == [
        "post_fx",
        "pre_fx",
        "post_fx",
    ]
    assert mixer_state["tap_targets"][1]["mute"] is False
    assert mixer_state["tap_targets"][1]["solo"] is False
    assert any("active solo" in warning.lower() for warning in mixer_state["warnings"])
    assert any("BASS" in warning and "suppressed" in warning for warning in mixer_state["warnings"])
    assert finalized["transport_start_beat"] == 0.0
    assert finalized["transport_stop_beat"] == 1.0
    assert [item.tap_id for item in finalized["inputs"]] == [1, 2, 3]

    client = FakeCaptureClient.instances[-1]
    configure_calls = [call[1] for call in client.calls if call[0] == "configure"]
    assert [call["capture_enabled"] for call in configure_calls] == [
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert quiescence_capture_states == [[True, True, True, False, False, False]]
    assert all(call["expected_set_signature"] == "sig-1" for call in configure_calls)
    assert [call["expected_device_id"] for call in configure_calls] == [101, 201, 203, 203, 201, 101]
    assert [call["signal_point"] for call in configure_calls] == [
        "post_fx",
        "pre_fx",
        "post_fx",
        "post_fx",
        "pre_fx",
        "post_fx",
    ]
    transport_actions = [call[1] for call in client.calls if call[0] == "transport"]
    assert transport_actions == ["stop", "play_until", "status"]



def test_run_capture_session_budgets_long_play_and_stops_after_lost_response(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    class ResponseLossCaptureClient(FakeCaptureClient):
        def transport(self, action="status", *, time=None, end_time=None, **kwargs):
            result = super().transport(action, time=time, end_time=end_time, **kwargs)
            if action == "play_until":
                raise TimeoutError("simulated lost play_until response")
            return result

    FakeCaptureClient.instances.clear()
    reader = FakeReadClient()
    monkeypatch.setattr(session, "LiveBridgeClient", lambda **_kwargs: reader)
    monkeypatch.setattr(session, "LiveCaptureClient", ResponseLossCaptureClient)
    monkeypatch.setattr(session.time, "sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="lost play_until response"):
        run_capture_session(
            experiment_id="long-response-loss",
            taps=[CaptureSessionTap(1, "Main", "master")],
            output_dir=tmp_path / "final",
            start_beat=0.0,
            end_beat=64.0,
            capture_root=tmp_path / "captures",
            include_analysis=False,
            settle_seconds=0.0,
            timeout_margin=8.0,
        )

    client = ResponseLossCaptureClient.instances[-1]
    # 64 beats at 120 BPM is 32 s; transport gets 32 + 8 margin + 5 grace.
    assert client.init_kwargs["timeout"] == pytest.approx(45.0)
    transport_actions = [call[1] for call in client.calls if call[0] == "transport"]
    assert transport_actions == ["stop", "play_until", "stop"]
    configure_calls = [call[1] for call in client.calls if call[0] == "configure"]
    assert [call["capture_enabled"] for call in configure_calls] == [True, False]

def test_wait_for_transport_completion_uses_guarded_stop_after_end_beat():
    import chibi_audio.capture_session as session

    class MissedScheduledStopClient:
        def __init__(self):
            self.calls = []

        def transport(self, action="status", **kwargs):
            self.calls.append((action, kwargs))
            if action == "status":
                return {"playing": True, "time": 160.25}
            if action == "stop":
                return {"playing": False, "time": 160.25}
            raise AssertionError(action)

    client = MissedScheduledStopClient()
    result = session._wait_for_transport_completion(
        client,
        expected_set_signature="sig-1",
        end_beat=160.0,
        timeout=1.0,
        poll_interval=0.05,
    )

    assert result == {"playing": False, "time": 160.25}
    assert [call[0] for call in client.calls] == ["status", "stop"]
    assert all(call[1]["expected_set_signature"] == "sig-1" for call in client.calls)


def test_wait_for_capture_quiescence_accepts_file_complete_before_first_poll(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    tap = CaptureSessionTap(1, "Main", "master")
    path = tmp_path / "chibitap-tap-1-short.wav"
    clock = {"now": 0.0}
    snapshot = {1: (path, 1024)}
    monkeypatch.setattr(session, "_new_capture_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(session.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        session.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    result = session._wait_for_capture_quiescence(
        tmp_path,
        [tap],
        {1: set()},
        timeout=1.0,
        poll_interval=0.1,
        minimum_bytes=1024,
        quiet_seconds=0.3,
    )

    assert result == snapshot


def test_wait_for_capture_quiescence_requires_requested_payload_before_quiet(monkeypatch, tmp_path):
    import chibi_audio.capture_session as session

    tap = CaptureSessionTap(1, "Main", "master")
    path = tmp_path / "chibitap-tap-1-partial.wav"
    clock = {"now": 0.0}
    snapshot = {1: (path, 1024)}
    monkeypatch.setattr(session, "_new_capture_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(session.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        session.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )

    with pytest.raises(CaptureError, match="did not become quiescent"):
        session._wait_for_capture_quiescence(
            tmp_path,
            [tap],
            {1: set()},
            timeout=0.5,
            poll_interval=0.1,
            minimum_bytes=2048,
            quiet_seconds=0.2,
        )
