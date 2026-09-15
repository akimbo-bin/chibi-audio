import math
import numpy as np
import pytest
from chibi_audio.translation import (
    TranslationError,
    apply_translation_array,
    get_translation_profile,
    translation_profile_catalog,
    translation_report_array,
)
def sine(frequency, seconds=2.0, sample_rate=48000, amplitude=0.25):
    t = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    mono = amplitude * np.sin(2.0 * math.pi * frequency * t)
    return np.column_stack((mono, mono))
def rms(audio):
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
def test_phone_like_profile_attenuates_sub_much_more_than_midbass():
    low = sine(50.0)
    upper = sine(300.0)
    low_delta = 20.0 * math.log10(rms(apply_translation_array(low, 48000, "phone_like")) / rms(low))
    upper_delta = 20.0 * math.log10(rms(apply_translation_array(upper, 48000, "phone_like")) / rms(upper))
    assert low_delta < -35.0
    assert upper_delta > -3.0
    assert upper_delta - low_delta > 30.0
def test_mono_profile_exposes_antiphase_cancellation():
    t = np.arange(48000, dtype=np.float64) / 48000.0
    wave = 0.25 * np.sin(2.0 * math.pi * 440.0 * t)
    stereo = np.column_stack((wave, -wave))
    translated = apply_translation_array(stereo, 48000, "mono")
    assert rms(translated) < 1.0e-10
def test_translation_report_keeps_profile_provenance_and_band_evidence():
    report = translation_report_array(sine(80.0) + sine(1000.0), 48000, ["phone_like", "mono"])
    assert report["sample_rate"] == 48000
    assert [item["profile"] for item in report["profiles"]] == ["phone_like", "mono"]
    phone = report["profiles"][0]
    assert phone["band_retention_db"]["20-80_db"] < phone["band_retention_db"]["500-2000_db"]
    assert "not predict an exact commercial device" in report["interpretation"]
    assert "heuristic" in phone["provenance"]
def test_catalog_and_unknown_profile_are_bounded():
    names = {item["name"] for item in translation_profile_catalog()}
    assert {"full_range", "phone_like", "laptop_like", "mono", "low_level"} <= names
    with pytest.raises(TranslationError, match="unknown translation profile"):
        get_translation_profile("magic-speaker")
