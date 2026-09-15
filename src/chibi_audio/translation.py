from __future__ import annotations
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from .audio import _np, decode_audio
class TranslationError(ValueError):
    """Raised when a playback-translation request is invalid."""
@dataclass(frozen=True, slots=True)
class TranslationProfile:
    name: str
    description: str
    response_points_db: tuple[tuple[float, float], ...]
    mono_blend: float = 0.0
    provenance: str = "heuristic diagnostic approximation; not measured hardware emulation"
    def __post_init__(self) -> None:
        if not self.name:
            raise TranslationError("translation profile name must not be empty")
        if not 0.0 <= self.mono_blend <= 1.0:
            raise TranslationError("mono_blend must be between 0 and 1")
        if len(self.response_points_db) < 2:
            raise TranslationError("translation profile needs at least two response points")
        last = -1.0
        for frequency, gain_db in self.response_points_db:
            if not math.isfinite(float(frequency)) or not math.isfinite(float(gain_db)):
                raise TranslationError("translation response points must be finite")
            if float(frequency) <= last:
                raise TranslationError("translation response frequencies must increase strictly")
            last = float(frequency)
_PROFILES: dict[str, TranslationProfile] = {
    "full_range": TranslationProfile(
        name="full_range",
        description="Near-flat reference bandwidth used as a neutral diagnostic control.",
        response_points_db=((0.0, -0.5), (20.0, -0.25), (30.0, 0.0), (18000.0, 0.0), (24000.0, -0.5)),
    ),
    "phone_like": TranslationProfile(
        name="phone_like",
        description="Small-device approximation with severe sub loss, reduced deep bass and partial mono collapse.",
        response_points_db=(
            (0.0, -80.0),
            (30.0, -60.0),
            (50.0, -42.0),
            (80.0, -28.0),
            (120.0, -16.0),
            (180.0, -8.0),
            (250.0, -3.0),
            (400.0, 0.0),
            (3500.0, 0.0),
            (7000.0, -2.0),
            (12000.0, -10.0),
            (20000.0, -35.0),
            (24000.0, -50.0),
        ),
        mono_blend=0.65,
    ),
    "laptop_like": TranslationProfile(
        name="laptop_like",
        description="Small stereo-speaker approximation with weak low bass and limited top octave.",
        response_points_db=(
            (0.0, -80.0),
            (40.0, -58.0),
            (70.0, -42.0),
            (100.0, -28.0),
            (150.0, -16.0),
            (220.0, -8.0),
            (350.0, -2.0),
            (500.0, 0.0),
            (5000.0, 0.0),
            (10000.0, -6.0),
            (16000.0, -18.0),
            (24000.0, -45.0),
        ),
        mono_blend=0.2,
    ),
    "mono": TranslationProfile(
        name="mono",
        description="Flat-bandwidth mono fold-down used to expose cancellation and stereo-dependent balance.",
        response_points_db=((0.0, 0.0), (24000.0, 0.0)),
        mono_blend=1.0,
    ),
    "low_level": TranslationProfile(
        name="low_level",
        description="Coarse low-listening-level perceptual weighting; not an SPL-calibrated equal-loudness model.",
        response_points_db=(
            (0.0, -16.0),
            (30.0, -12.0),
            (60.0, -8.0),
            (100.0, -5.0),
            (200.0, -2.0),
            (1000.0, 0.0),
            (4000.0, -1.0),
            (10000.0, -3.0),
            (20000.0, -5.0),
            (24000.0, -6.0),
        ),
        provenance="heuristic low-level perceptual weighting; not SPL calibrated and not an ISO equal-loudness implementation",
    ),
}
_TRANSLATION_BANDS = (
    (20.0, 80.0),
    (80.0, 150.0),
    (150.0, 500.0),
    (500.0, 2000.0),
    (2000.0, 6000.0),
    (6000.0, 12000.0),
    (12000.0, 20000.0),
)
def translation_profile_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": profile.name,
            "description": profile.description,
            "mono_blend": profile.mono_blend,
            "provenance": profile.provenance,
            "response_points_db": [
                {"frequency_hz": frequency, "gain_db": gain_db}
                for frequency, gain_db in profile.response_points_db
            ],
        }
        for profile in _PROFILES.values()
    ]
def get_translation_profile(name: str | TranslationProfile) -> TranslationProfile:
    if isinstance(name, TranslationProfile):
        return name
    key = str(name).strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise TranslationError(
            f"unknown translation profile {name!r}; expected one of {', '.join(_PROFILES)}"
        ) from exc
def response_db_for_frequencies(profile: str | TranslationProfile, frequencies):
    np = _np()
    item = get_translation_profile(profile)
    points = np.asarray(item.response_points_db, dtype=np.float64)
    return np.interp(
        np.asarray(frequencies, dtype=np.float64),
        points[:, 0],
        points[:, 1],
        left=points[0, 1],
        right=points[-1, 1],
    )
def apply_translation_array(audio, sample_rate: int, profile: str | TranslationProfile):
    np = _np()
    item = get_translation_profile(profile)
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] not in (1, 2):
        raise TranslationError("audio must contain at least two mono or stereo samples")
    if sample_rate < 8000:
        raise TranslationError("sample_rate must be at least 8000 Hz")
    pad = min(max(0, data.shape[0] // 4), int(round(0.25 * sample_rate)))
    padded = np.pad(data, ((pad, pad), (0, 0)), mode="reflect") if pad else data
    spectrum = np.fft.rfft(padded, axis=0)
    frequencies = np.fft.rfftfreq(padded.shape[0], d=1.0 / float(sample_rate))
    gains = np.power(10.0, response_db_for_frequencies(item, frequencies) / 20.0)
    filtered = np.fft.irfft(spectrum * gains[:, None], n=padded.shape[0], axis=0)
    if pad:
        filtered = filtered[pad:-pad]
    if filtered.shape[1] == 2 and item.mono_blend > 0.0:
        mono = np.mean(filtered, axis=1, keepdims=True)
        filtered = (1.0 - item.mono_blend) * filtered + item.mono_blend * mono
    return filtered.astype(np.float64, copy=False)
def _power_spectrum(audio, sample_rate: int):
    np = _np()
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    window = np.hanning(data.shape[0]).astype(np.float64)
    spectrum = np.fft.rfft(data * window[:, None], axis=0)
    power = np.mean(np.abs(spectrum) ** 2, axis=1)
    frequencies = np.fft.rfftfreq(data.shape[0], d=1.0 / float(sample_rate))
    return frequencies, power
def _band_power(audio, sample_rate: int, low_hz: float, high_hz: float) -> float:
    np = _np()
    frequencies, power = _power_spectrum(audio, sample_rate)
    mask = (frequencies >= low_hz) & (frequencies < min(high_hz, sample_rate / 2.0))
    return float(np.sum(power[mask]))
def _ratio_db(numerator: float, denominator: float, floor_db: float = -120.0) -> float:
    if numerator <= 0.0 and denominator <= 0.0:
        return 0.0
    if numerator <= 0.0:
        return floor_db
    if denominator <= 0.0:
        return -floor_db
    return 10.0 * math.log10(numerator / denominator)
def translation_report_array(
    audio,
    sample_rate: int,
    profiles: Iterable[str] | None = None,
) -> dict[str, Any]:
    np = _np()
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    names = tuple(profiles) if profiles is not None else tuple(_PROFILES)
    if not names:
        raise TranslationError("at least one translation profile is required")
    original_rms = float(np.sqrt(np.mean(data * data)))
    results: list[dict[str, Any]] = []
    for name in names:
        item = get_translation_profile(name)
        translated = apply_translation_array(data, sample_rate, item)
        translated_rms = float(np.sqrt(np.mean(translated * translated)))
        band_retention: dict[str, float] = {}
        for low_hz, high_hz in _TRANSLATION_BANDS:
            before = _band_power(data, sample_rate, low_hz, high_hz)
            after = _band_power(translated, sample_rate, low_hz, high_hz)
            band_retention[f"{int(low_hz)}-{int(high_hz)}_db"] = _ratio_db(after, before)
        results.append(
            {
                "profile": item.name,
                "description": item.description,
                "provenance": item.provenance,
                "mono_blend": item.mono_blend,
                "rms_delta_db": 20.0 * math.log10(max(translated_rms, 1.0e-12) / max(original_rms, 1.0e-12)),
                "band_retention_db": band_retention,
            }
        )
    return {
        "sample_rate": int(sample_rate),
        "profiles": results,
        "interpretation": (
            "Diagnostic translation evidence only. Profiles approximate bandwidth/stereo/perceptual constraints and "
            "do not predict an exact commercial device, listening SPL, room, codec or listener."
        ),
    }
def translation_report(
    path: str | Path,
    *,
    sample_rate: int = 48000,
    profiles: Iterable[str] | None = None,
) -> dict[str, Any]:
    return translation_report_array(decode_audio(path, sample_rate=sample_rate), sample_rate, profiles)
