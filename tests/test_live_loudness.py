from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from chibi_audio.live_loudness import (
    LiveLoudnessExperimentError,
    resolve_master_parameter,
    run_master_parameter_capture,
)

BASE = 0.4133888781070709
CANDIDATE = 0.4300577938556671


class FakeState:
    def __init__(self) -> None:
        self.value = BASE
        self.display = "+12.40 dB"
        self.set_signature = "sig-1"


class FakeRead:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    def set_summary(self, **_kwargs):
        return {
            "set_signature": self.state.set_signature,
            "master_track": {                "id": 10,
                "name": "Main",
                "devices": [{"id": 20, "name": "Pro-L 2"}],
            },
        }

    def call(self, method, params):
        assert method == "device_parameters"
        assert params["ref"] == {"id": 20}
        return [
            {
                "id": 30,
                "name": "Gain",
                "value": self.state.value,
                "display": self.state.display,
            }
        ]


class FakeWrite:
    def __init__(self, state: FakeState) -> None:
        self.state = state
        self.calls: list[dict] = []

    def set_device_parameter(self, **kwargs):
        self.calls.append(dict(kwargs))
        assert kwargs["placement"] == "master"
        assert kwargs["expected_set_signature"] == self.state.set_signature
        assert kwargs["expected_current_value"] == pytest.approx(self.state.value)
        before = self.state.value
        self.state.value = float(kwargs["value"])
        if self.state.value == pytest.approx(BASE):
            self.state.display = "+12.40 dB"
        elif self.state.value == pytest.approx(CANDIDATE):
            self.state.display = "+12.90 dB"
        return {
            "before": {"value": before},
            "parameter": {"value": self.state.value},
            "read_back_verified": True,
        }


class FakeLocator:
    def __init__(self, state: FakeState) -> None:
        self.state = state

    def locators(self, *, limit=256):
        assert limit == 256
        return {
            "set_signature": self.state.set_signature,
            "current_song_time": 0.0,
            "last_event_time": 192.0,
            "song_length": 192.0,
            "locators": [
                {"index": 0, "id": 100, "name": "3", "time": 96.0},
                {"index": 1, "id": 101, "name": "4", "time": 160.0},
            ],
        }


class FakeTopology:
    def as_dict(self):
        return {"initial_set_signature": "sig-1", "final_set_signature": "sig-1"}


def _capture_result(tmp_path: Path):
    manifest = tmp_path / "candidate__manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        manifest_path=manifest,
        topology=FakeTopology(),
        restore={"final_set_signature": "sig-1"},
    )


def test_resolve_master_parameter_returns_exact_identity():
    state = FakeState()
    resolved = resolve_master_parameter(
        FakeRead(state), device_name="Pro-L 2", parameter_name="Gain"
    )
    assert resolved.set_signature == "sig-1"
    assert resolved.track_id == 10
    assert resolved.device_id == 20
    assert resolved.parameter_id == 30
    assert resolved.device_index == 0
    assert resolved.parameter_index == 0
    assert resolved.value == pytest.approx(BASE)
    assert resolved.display == "+12.40 dB"


def test_master_candidate_capture_restores_exactly(tmp_path: Path):
    state = FakeState()
    read = FakeRead(state)
    write = FakeWrite(state)
    locator = FakeLocator(state)
    capture_calls: list[dict] = []
    def capture_runner(**kwargs):
        capture_calls.append(dict(kwargs))
        assert state.value == pytest.approx(CANDIDATE)
        return _capture_result(tmp_path)

    result = run_master_parameter_capture(
        experiment_id="candidate-1",
        source_label="MAIN_PLUS_0P5",
        section_name="3",
        output_dir=tmp_path,
        device_name="Pro-L 2",
        parameter_name="Gain",
        expected_before_value=BASE,
        candidate_value=CANDIDATE,
        expected_before_display="+12.40 dB",
        expected_candidate_display="+12.90 dB",
        read=read,
        write=write,
        locator=locator,
        capture_runner=capture_runner,
    )

    assert result["effect_state"] == "STARTED_CONFIRMED"
    assert result["restored"] is True
    assert state.value == pytest.approx(BASE)
    assert state.display == "+12.40 dB"
    assert len(write.calls) == 2
    assert capture_calls[0]["start_beat"] == 96.0
    assert capture_calls[0]["end_beat"] == 160.0
    assert capture_calls[0]["expected_set_signature"] == "sig-1"


def test_stale_preflight_refuses_before_any_write(tmp_path: Path):
    state = FakeState()
    read = FakeRead(state)
    write = FakeWrite(state)

    with pytest.raises(LiveLoudnessExperimentError, match="changed since planning"):
        run_master_parameter_capture(
            experiment_id="candidate-stale",
            source_label="MAIN_STALE",
            section_name="3",
            output_dir=tmp_path,
            device_name="Pro-L 2",
            parameter_name="Gain",
            expected_before_value=BASE + 0.1,
            candidate_value=CANDIDATE,
            read=read,
            write=write,
            locator=FakeLocator(state),
            capture_runner=lambda **_kwargs: pytest.fail("capture must not run"),
        )

    assert write.calls == []
    assert state.value == pytest.approx(BASE)


def test_capture_failure_restores_master_before_propagating(tmp_path: Path):
    state = FakeState()
    write = FakeWrite(state)

    def fail_capture(**_kwargs):
        assert state.value == pytest.approx(CANDIDATE)
        raise RuntimeError("simulated capture failure")

    with pytest.raises(RuntimeError, match="simulated capture failure"):
        run_master_parameter_capture(
            experiment_id="candidate-fail",
            source_label="MAIN_FAIL",
            section_name="3",
            output_dir=tmp_path,
            device_name="Pro-L 2",
            parameter_name="Gain",
            expected_before_value=BASE,
            candidate_value=CANDIDATE,
            read=FakeRead(state),
            write=write,
            locator=FakeLocator(state),
            capture_runner=fail_capture,
        )

    assert state.value == pytest.approx(BASE)
    assert state.display == "+12.40 dB"
    assert len(write.calls) == 2


def test_unexpected_parameter_drift_refuses_blind_restore(tmp_path: Path):
    state = FakeState()
    write = FakeWrite(state)

    def drift_capture(**_kwargs):
        state.value = 0.5
        state.display = "+15.00 dB"
        raise RuntimeError("capture saw external drift")

    with pytest.raises(LiveLoudnessExperimentError, match="refusing blind restore"):
        run_master_parameter_capture(
            experiment_id="candidate-drift",
            source_label="MAIN_DRIFT",
            section_name="3",
            output_dir=tmp_path,
            device_name="Pro-L 2",
            parameter_name="Gain",            expected_before_value=BASE,
            candidate_value=CANDIDATE,
            read=FakeRead(state),
            write=write,
            locator=FakeLocator(state),
            capture_runner=drift_capture,
        )

    assert state.value == pytest.approx(0.5)
    assert len(write.calls) == 1
