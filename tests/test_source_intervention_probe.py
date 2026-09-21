from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from chibi_audio.analysis import intervention
from chibi_audio.analysis.intervention import (
    SOURCE_INTERVENTION_PROBE_SCHEMA_VERSION,
    SourceInterventionProbeError,
    evaluate_source_intervention_probe,
)


def _audio(sample_rate: int = 8000, seconds: float = 4.0) -> np.ndarray:
    frames = int(sample_rate * seconds)
    time = np.arange(frames, dtype=np.float64) / float(sample_rate)
    envelope = 0.08 + 0.04 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 1.7 * time))
    for center in (0.45, 1.35, 2.25, 3.15):
        envelope += 0.16 * np.exp(
            -0.5 * np.square((time - center) / 0.055)
        )
    mono = envelope * np.sin(2.0 * np.pi * 90.0 * time)
    return np.column_stack((mono, mono)).astype(np.float32)


def _write_manifest(
    root: Path,
    name: str,
    audio: np.ndarray,
    *,
    track_id: int = 200,
    start_beat: float = 96.0,
    end_beat: float = 105.0,
    tempo_bpm: float = 135.0,
) -> Path:
    folder = root / name
    folder.mkdir()
    artifact = folder / "DRUMS_POST.wav"
    artifact.write_bytes((name + "-fixture").encode("ascii"))
    manifest = folder / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_id": name,
                "requested_range": {
                    "start_beat": start_beat,
                    "end_beat": end_beat,
                    "tempo_bpm": tempo_bpm,
                    "sample_rate": 8000,
                    "channels": 2,
                    "target_samples": int(audio.shape[0]),
                },
                "taps": [
                    {
                        "tap_id": 3,
                        "source_label": "DRUMS_POST",
                        "final": {
                            "path": artifact.name,
                            "sha256": hashlib.sha256(
                                artifact.read_bytes()
                            ).hexdigest(),
                        },
                    }
                ],
                "live_session": {
                    "mixer_state": {
                        "tap_targets": [
                            {
                                "tap_id": 3,
                                "source_label": "DRUMS_POST",
                                "placement": "track",
                                "signal_point": "post_fx",
                                "track_name": "DRUMS",
                                "track_index": 53,
                                "track_id": track_id,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _patch_audio_io(
    monkeypatch,
    arrays: dict[Path, np.ndarray],
    *,
    sample_rate: int = 8000,
) -> None:
    normalized = {
        path.resolve(): values
        for path, values in arrays.items()
    }

    def fake_probe(path):
        values = normalized[Path(path).resolve()]
        return {
            "path": str(path),
            "sample_rate": sample_rate,
            "channels": values.shape[1],
            "samples": values.shape[0],
            "duration_s": values.shape[0] / float(sample_rate),
        }

    def fake_decode(
        path,
        _request,
        *,
        sample_rate=None,
        channels=2,
    ):
        assert sample_rate == 8000
        values = normalized[Path(path).resolve()]
        assert channels == values.shape[1]
        return values

    monkeypatch.setattr(intervention, "probe_audio", fake_probe)
    monkeypatch.setattr(
        intervention,
        "decode_audio_segment",
        fake_decode,
    )


def test_probe_measures_one_db_bus_response_from_one_db_declared_trim(
    monkeypatch,
    tmp_path,
):
    baseline = _audio()
    candidate = baseline * np.float32(10.0 ** (-1.0 / 20.0))
    baseline_manifest = _write_manifest(
        tmp_path,
        "baseline",
        baseline,
    )
    candidate_manifest = _write_manifest(
        tmp_path,
        "candidate",
        candidate,
    )
    _patch_audio_io(
        monkeypatch,
        {
            baseline_manifest.parent / "DRUMS_POST.wav": baseline,
            candidate_manifest.parent / "DRUMS_POST.wav": candidate,
        },
    )

    result = evaluate_source_intervention_probe(
        baseline_manifest,
        candidate_manifest,
        bus_label="DRUMS_POST",
        source_target="61-demucs-drums",
        source_parameter="track_volume",
        declared_change_db=-1.0,
    )

    assert (
        result["schema_version"]
        == SOURCE_INTERVENTION_PROBE_SCHEMA_VERSION
    )
    assert result["effect_state"] == "NOT_STARTED"
    assert result["declared_intervention"] == {
        "source_target": "61-demucs-drums",
        "source_parameter": "track_volume",
        "change_db": -1.0,
        "mutation_provenance_verified": False,
    }
    response = result["response"]
    assert response["median_active_bus_delta_db"] == pytest.approx(
        -1.0,
        abs=1.0e-5,
    )
    assert response["top_bus_median_delta_db"] == pytest.approx(
        -1.0,
        abs=1.0e-5,
    )
    assert response["top_bus_response_per_declared_db"] == pytest.approx(
        1.0,
        abs=1.0e-5,
    )
    assert response["top_bus_same_direction_fraction"] == 1.0
    assert 1 <= len(result["events"]["events"]) <= 8
    assert "caller-supplied" in result["interpretation_note"]


def test_probe_exposes_negligible_bus_response_for_correlated_but_tiny_effect(
    monkeypatch,
    tmp_path,
):
    baseline = _audio()
    candidate = baseline * np.float32(10.0 ** (-0.002 / 20.0))
    baseline_manifest = _write_manifest(
        tmp_path,
        "baseline",
        baseline,
    )
    candidate_manifest = _write_manifest(
        tmp_path,
        "candidate",
        candidate,
    )
    _patch_audio_io(
        monkeypatch,
        {
            baseline_manifest.parent / "DRUMS_POST.wav": baseline,
            candidate_manifest.parent / "DRUMS_POST.wav": candidate,
        },
    )

    result = evaluate_source_intervention_probe(
        baseline_manifest,
        candidate_manifest,
        bus_label="DRUMS_POST",
        source_target="69-percussion",
        source_parameter="track_volume",
        declared_change_db=-1.0,
    )

    response = result["response"]
    assert response["top_bus_median_delta_db"] == pytest.approx(
        -0.002,
        abs=1.0e-5,
    )
    assert response["top_bus_response_per_declared_db"] == pytest.approx(
        0.002,
        abs=1.0e-5,
    )


def test_probe_rejects_mismatched_section_or_bus_identity(
    monkeypatch,
    tmp_path,
):
    baseline = _audio()
    candidate = baseline.copy()
    baseline_manifest = _write_manifest(
        tmp_path,
        "baseline",
        baseline,
    )
    range_mismatch = _write_manifest(
        tmp_path,
        "range-mismatch",
        candidate,
        end_beat=106.0,
    )
    identity_mismatch = _write_manifest(
        tmp_path,
        "identity-mismatch",
        candidate,
        track_id=201,
    )
    _patch_audio_io(
        monkeypatch,
        {
            baseline_manifest.parent / "DRUMS_POST.wav": baseline,
            range_mismatch.parent / "DRUMS_POST.wav": candidate,
            identity_mismatch.parent / "DRUMS_POST.wav": candidate,
        },
    )

    with pytest.raises(
        SourceInterventionProbeError,
        match="ranges/formats do not match",
    ):
        evaluate_source_intervention_probe(
            baseline_manifest,
            range_mismatch,
            bus_label="DRUMS_POST",
            source_target="source",
            source_parameter="track_volume",
            declared_change_db=-1.0,
        )

    with pytest.raises(
        SourceInterventionProbeError,
        match="bus target identity does not match",
    ):
        evaluate_source_intervention_probe(
            baseline_manifest,
            identity_mismatch,
            bus_label="DRUMS_POST",
            source_target="source",
            source_parameter="track_volume",
            declared_change_db=-1.0,
        )


def test_probe_rejects_invalid_declared_change(monkeypatch, tmp_path):
    baseline = _audio()
    candidate = baseline.copy()
    baseline_manifest = _write_manifest(
        tmp_path,
        "baseline",
        baseline,
    )
    candidate_manifest = _write_manifest(
        tmp_path,
        "candidate",
        candidate,
    )
    _patch_audio_io(
        monkeypatch,
        {
            baseline_manifest.parent / "DRUMS_POST.wav": baseline,
            candidate_manifest.parent / "DRUMS_POST.wav": candidate,
        },
    )

    with pytest.raises(
        SourceInterventionProbeError,
        match="must be non-zero",
    ):
        evaluate_source_intervention_probe(
            baseline_manifest,
            candidate_manifest,
            bus_label="DRUMS_POST",
            source_target="source",
            source_parameter="track_volume",
            declared_change_db=0.0,
        )
