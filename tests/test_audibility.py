import math
import numpy as np
import pytest
from chibi_audio.audibility import (
    AudibilityError,
    bass_harmonic_survivability_array,
    erb_band_profile_array,
    erb_number,
    hz_from_erb,
)
def stereo_sum(components, seconds=3.0, sample_rate=48000):
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    mono = np.zeros_like(t)
    for frequency, amplitude in components:
        mono += amplitude * np.sin(2.0 * math.pi * frequency * t)
    return np.column_stack((mono, mono))
def row(report, harmonic):
    return next(item for item in report["harmonics"] if item["harmonic"] == harmonic)
def test_erb_conversion_round_trips_frequency():
    for frequency in (20.0, 50.0, 100.0, 1000.0, 10000.0):
        assert hz_from_erb(erb_number(frequency)) == pytest.approx(frequency, rel=1.0e-9)
def test_erb_band_profile_energy_is_normalized():
    profile = erb_band_profile_array(stereo_sum([(100.0, 0.2), (1000.0, 0.1)]), 48000, band_count=24)
    assert profile["scale"] == "ERB-rate"
    assert len(profile["bands"]) == 24
    assert sum(item["energy_pct"] for item in profile["bands"]) == pytest.approx(100.0, abs=1.0e-6)
    assert "not a standardized specific-loudness" in profile["interpretation"]
def test_phone_translation_can_separate_sub_loss_from_upper_harmonic_masking():
    source = stereo_sum([(50.0, 0.5), (100.0, 0.22), (200.0, 0.12), (300.0, 0.10)])
    masker = stereo_sum([(200.0, 0.45), (900.0, 0.15)])
    report = bass_harmonic_survivability_array(
        source,
        48000,
        fundamental_hz=50.0,
        masker=masker,
        profile="phone_like",
        harmonics=6,
    )
    fundamental = row(report, 1)
    fourth = row(report, 4)
    sixth = row(report, 6)
    assert fundamental["translation_retention_db"] < -35.0
    assert sixth["translation_retention_db"] > fundamental["translation_retention_db"] + 25.0
    assert fourth["masking_margin_estimate_db"] < -6.0
    assert fourth["evidence_class"] == "masked"
    assert sixth["masking_margin_estimate_db"] > 0.0
    assert sixth["evidence_class"] in {"positive_margin", "clear_margin"}
    assert 6 in report["upper_harmonic_identity_candidates"]
    assert "not absolute human audibility thresholds" in report["interpretation"]
def test_masker_must_be_sample_aligned():
    source = stereo_sum([(60.0, 0.3)], seconds=1.0)
    masker = stereo_sum([(120.0, 0.2)], seconds=0.5)
    with pytest.raises(AudibilityError, match="identical sample/channel shape"):
        bass_harmonic_survivability_array(
            source,
            48000,
            fundamental_hz=60.0,
            masker=masker,
        )
