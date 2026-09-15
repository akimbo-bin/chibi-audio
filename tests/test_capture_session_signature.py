import pytest

import chibi_audio.capture_session as capture_session
from chibi_audio.capture import CaptureError
from chibi_audio.capture_session import CaptureSessionTap


class FakeReadClient:
    def __init__(self, **_kwargs):
        self.calls = []

    def set_summary(self, **kwargs):
        self.calls.append(("set_summary", kwargs))
        return {"set_signature": "sig-new", "tempo": 135.0}

    def call(self, *_args, **_kwargs):
        raise AssertionError("capture session must fail before further Live reads on stale signature")


class FakeCaptureClient:
    instances = []

    def __init__(self, **_kwargs):
        self.calls = []
        type(self).instances.append(self)

    def transport(self, *_args, **_kwargs):
        self.calls.append(("transport", _args, _kwargs))
        raise AssertionError("transport must not be touched on stale Set signature")

    def configure_chibitap(self, *_args, **_kwargs):
        self.calls.append(("configure_chibitap", _args, _kwargs))
        raise AssertionError("ChibiTap must not be touched on stale Set signature")


def test_expected_set_signature_refuses_before_any_capture_effect(monkeypatch, tmp_path):
    FakeCaptureClient.instances.clear()
    monkeypatch.setattr(capture_session, "LiveBridgeClient", FakeReadClient)
    monkeypatch.setattr(capture_session, "LiveCaptureClient", FakeCaptureClient)

    with pytest.raises(CaptureError, match="changed since capture planning"):
        capture_session.run_capture_session(
            experiment_id="stale-plan",
            taps=[CaptureSessionTap(1, "Main", "master")],
            output_dir=tmp_path,
            start_beat=32.0,
            end_beat=48.0,
            expected_set_signature="sig-old",
        )

    assert len(FakeCaptureClient.instances) == 1
    assert FakeCaptureClient.instances[0].calls == []
