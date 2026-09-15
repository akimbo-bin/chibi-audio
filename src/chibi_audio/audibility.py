from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from .audio import _np, decode_audio
from .translation import apply_translation_array, get_translation_profile
class AudibilityError(ValueError):
    """Raised when perceptual-audibility evidence cannot be calculated safely."""
def erb_number(frequency_hz: float) -> float:
    if frequency_hz < 0.0 or not math.isfinite(float(frequency_hz)):
        raise AudibilityError("frequency_hz must be finite and >= 0")
    return 21.4 * math.log10(1.0 + 0.00437 * float(frequency_hz))
def hz_from_erb(erb: float) -> float:
    if not math.isfinite(float(erb)):
        raise AudibilityError("ERB value must be finite")
    return (10.0 ** (float(erb) / 21.4) - 1.0) / 0.00437
def erb_bandwidth_hz(frequency_hz: float) -> float:
    if frequency_hz < 0.0:
        raise AudibilityError("frequency_hz must be >= 0")
    return 24.7 * (1.0 + 0.00437 * float(frequency_hz))
def _spectrum(audio, sample_rate: int):
    np = _np()
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = data[:, None]
    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] not in (1, 2):
        raise AudibilityError("audio must contain at least two mono or stereo samples")
    window = np.hanning(data.shape[0]).astype(np.float64)
    transformed = np.fft.rfft(data * window[:, None], axis=0)
    power = np.mean(np.abs(transformed) ** 2, axis=1)
    frequencies = np.fft.rfftfreq(data.shape[0], d=1.0 / float(sample_rate))
    return frequencies, power
def _band_power_from_spectrum(frequencies, power, low_hz: float, high_hz: float) -> float:
    np = _np()
    mask = (frequencies >= low_hz) & (frequencies < high_hz)
    return float(np.sum(power[mask]))
def _ratio_db(numerator: float, denominator: float, floor_db: float = -120.0) -> float:
    if numerator <= 0.0 and denominator <= 0.0:
        return 0.0
    if numerator <= 0.0:
        return floor_db
    if denominator <= 0.0:
        return -floor_db
    return 10.0 * math.log10(numerator / denominator)
def erb_band_profile_array(
    audio,
    sample_rate: int,
    *,
    band_count: int = 24,
    low_hz: float = 20.0,
    high_hz: float = 20000.0,
) -> dict[str, Any]:
    np = _np()
    if not 6 <= int(band_count) <= 96:
        raise AudibilityError("band_count must be between 6 and 96")
    nyquist = sample_rate / 2.0
    high = min(float(high_hz), nyquist)
    if low_hz <= 0.0 or high <= low_hz:
        raise AudibilityError("ERB analysis requires 0 < low_hz < high_hz <= Nyquist")
    frequencies, power = _spectrum(audio, sample_rate)
    edges_erb = np.linspace(erb_number(low_hz), erb_number(high), int(band_count) + 1)
    edges_hz = np.asarray([hz_from_erb(float(value)) for value in edges_erb])
    raw: list[tuple[float, float, float, float]] = []
    total = 0.0
    for index in range(int(band_count)):
        low = float(edges_hz[index])
        upper = float(edges_hz[index + 1])
        value = _band_power_from_spectrum(frequencies, power, low, upper)
        center = hz_from_erb(float((edges_erb[index] + edges_erb[index + 1]) * 0.5))
        raw.append((low, upper, center, value))
        total += value
    return {
        "scale": "ERB-rate",
        "band_count": int(band_count),
        "bands": [
            {
                "low_hz": low,
                "high_hz": upper,
                "center_hz": center,
                "energy_pct": 100.0 * value / total if total > 0.0 else 0.0,
            }
            for low, upper, center, value in raw
        ],
        "interpretation": "ERB-spaced spectral evidence; not a standardized specific-loudness result.",
    }
def bass_harmonic_survivability_array(
    source,
    sample_rate: int,
    *,
    fundamental_hz: float,
    masker=None,
    profile: str = "phone_like",
    harmonics: int = 8,
) -> dict[str, Any]:
    np = _np()
    source_data = np.asarray(source, dtype=np.float64)
    if source_data.ndim == 1:
        source_data = source_data[:, None]
    if not 20.0 <= float(fundamental_hz) <= 500.0:
        raise AudibilityError("fundamental_hz must be between 20 and 500 Hz")
    if not 1 <= int(harmonics) <= 24:
        raise AudibilityError("harmonics must be between 1 and 24")
    masker_data = None
    if masker is not None:
        masker_data = np.asarray(masker, dtype=np.float64)
        if masker_data.ndim == 1:
            masker_data = masker_data[:, None]
        if masker_data.shape != source_data.shape:
            raise AudibilityError("source and masker must have identical sample/channel shape")
    item = get_translation_profile(profile)
    translated_source = apply_translation_array(source_data, sample_rate, item)
    translated_masker = (
        apply_translation_array(masker_data, sample_rate, item) if masker_data is not None else None
    )
    original_freqs, original_power = _spectrum(source_data, sample_rate)
    translated_freqs, translated_power = _spectrum(translated_source, sample_rate)
    masker_freqs = masker_power = None
    if translated_masker is not None:
        masker_freqs, masker_power = _spectrum(translated_masker, sample_rate)
    rows: list[dict[str, Any]] = []
    raw_translated_powers: list[float] = []
    for harmonic_index in range(1, int(harmonics) + 1):
        frequency = float(fundamental_hz) * harmonic_index
        if frequency >= sample_rate / 2.0 or frequency > 20000.0:
            break
        half_width = max(6.0, min(80.0, 0.175 * erb_bandwidth_hz(frequency)))
        low = max(0.0, frequency - half_width)
        high = min(sample_rate / 2.0, frequency + half_width)
        before = _band_power_from_spectrum(original_freqs, original_power, low, high)
        after = _band_power_from_spectrum(translated_freqs, translated_power, low, high)
        masker_value = (
            _band_power_from_spectrum(masker_freqs, masker_power, low, high)
            if masker_freqs is not None and masker_power is not None
            else None
        )
        raw_translated_powers.append(after)
        rows.append(
            {
                "harmonic": harmonic_index,
                "frequency_hz": frequency,
                "analysis_band_hz": [low, high],
                "translation_retention_db": _ratio_db(after, before),
                "masking_margin_estimate_db": (
                    _ratio_db(after, masker_value) if masker_value is not None else None
                ),
                "translated_power": after,
            }
        )
    peak_harmonic_power = max(raw_translated_powers, default=0.0)
    surviving: list[int] = []
    identity_candidates: list[int] = []
    for row in rows:
        relative_db = _ratio_db(float(row["translated_power"]), peak_harmonic_power)
        row["relative_to_strongest_harmonic_db"] = relative_db
        margin = row["masking_margin_estimate_db"]
        if margin is None:
            classification = "retained" if row["translation_retention_db"] >= -12.0 and relative_db >= -24.0 else "attenuated"
        elif relative_db < -24.0:
            classification = "weak_source_component"
        elif margin >= 6.0:
            classification = "clear_margin"
        elif margin >= 0.0:
            classification = "positive_margin"
        elif margin >= -6.0:
            classification = "contested"
        else:
            classification = "masked"
        row["evidence_class"] = classification
        if classification in {"retained", "clear_margin", "positive_margin", "contested"}:
            surviving.append(int(row["harmonic"]))
        if int(row["harmonic"]) > 1 and classification in {"clear_margin", "positive_margin", "contested"} and relative_db >= -18.0:
            identity_candidates.append(int(row["harmonic"]))
        row.pop("translated_power", None)
    return {
        "sample_rate": int(sample_rate),
        "profile": item.name,
        "profile_provenance": item.provenance,
        "fundamental_hz": float(fundamental_hz),
        "harmonics": rows,
        "surviving_harmonic_candidates": surviving,
        "upper_harmonic_identity_candidates": identity_candidates,
        "interpretation": (
            "Relative translation and masker evidence only. Masking margins are spectral power comparisons, not "
            "absolute human audibility thresholds; playback SPL, device nonlinearities, room noise and listener variation are not modeled."
        ),
    }
def analyze_bass_harmonic_survivability(
    source_path: str | Path,
    *,
    fundamental_hz: float,
    masker_path: str | Path | None = None,
    profile: str = "phone_like",
    harmonics: int = 8,
    sample_rate: int = 48000,
) -> dict[str, Any]:
    source = decode_audio(source_path, sample_rate=sample_rate)
    masker = decode_audio(masker_path, sample_rate=sample_rate) if masker_path is not None else None
    return bass_harmonic_survivability_array(
        source,
        sample_rate,
        fundamental_hz=fundamental_hz,
        masker=masker,
        profile=profile,
        harmonics=harmonics,
    )
