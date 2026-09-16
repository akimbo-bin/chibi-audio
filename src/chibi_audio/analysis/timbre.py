from __future__ import annotations

import math
from importlib import metadata, util
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


TIMBRE_VERSION = "0.1.0"


def timbre_descriptor() -> AnalyzerDescriptor:
    available = util.find_spec("librosa") is not None
    version = "unavailable"
    reason = None
    if available:
        try:
            version = metadata.version("librosa")
        except metadata.PackageNotFoundError:
            available = False
            reason = "librosa import spec exists but package metadata is unavailable"
    else:
        reason = "librosa is not installed"
    return AnalyzerDescriptor(
        name="librosa_timbre",
        version=f"{TIMBRE_VERSION}+librosa-{version}",
        capabilities=frozenset({AnalysisCapability.MIR_TIMBRE}),
        cost=AnalysisCost.MODERATE,
        implementation="MFCC shape / spectral contrast-bandwidth / HPSS energy evidence",
        upstream="librosa/librosa",
        license="ISC",
        available=available,
        unavailable_reason=reason,
    )


def _safe_fft_size(frame_count: int) -> int:
    if frame_count <= 0:
        return 256
    target = min(2048, max(256, frame_count))
    return 1 << max(8, int(math.floor(math.log2(target))))


def _contrast_bands(sample_rate: int, fmin: float = 50.0) -> int:
    nyquist = sample_rate * 0.5
    if nyquist <= fmin * 2.0:
        return 1
    maximum = int(math.floor(math.log2(nyquist / fmin))) - 1
    return max(1, min(6, maximum))


class LibrosaTimbreAnalyzer:
    @property
    def descriptor(self) -> AnalyzerDescriptor:
        return timbre_descriptor()

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        descriptor = self.descriptor
        if not descriptor.available:
            raise RuntimeError(descriptor.unavailable_reason or "librosa is unavailable")

        import librosa

        np = _np()
        audio = context.audio.astype(np.float32, copy=False)
        mono = np.mean(audio, axis=1)
        sr = context.request.sample_rate
        n_fft = _safe_fft_size(len(mono))
        hop_length = min(512, max(64, n_fft // 4))

        mfcc = librosa.feature.mfcc(
            y=mono,
            sr=sr,
            n_mfcc=13,
            n_fft=n_fft,
            hop_length=hop_length,
        )
        # C0 carries substantial overall spectral-energy information. Excluding it
        # makes this vector more useful as a shape descriptor across level changes.
        shape = np.asarray(mfcc[1:13], dtype=np.float64)
        shape_mean = np.mean(shape, axis=1) if shape.size else np.zeros(12, dtype=np.float64)
        shape_std = np.std(shape, axis=1) if shape.size else np.zeros(12, dtype=np.float64)

        contrast_band_count = _contrast_bands(sr)
        contrast = librosa.feature.spectral_contrast(
            y=mono,
            sr=sr,
            n_fft=n_fft,
            hop_length=hop_length,
            fmin=50.0,
            n_bands=contrast_band_count,
        )
        contrast = np.asarray(contrast, dtype=np.float64)
        contrast_mean = np.mean(contrast, axis=1) if contrast.size else np.zeros(0, dtype=np.float64)
        contrast_std = np.std(contrast, axis=1) if contrast.size else np.zeros(0, dtype=np.float64)

        bandwidth = librosa.feature.spectral_bandwidth(
            y=mono,
            sr=sr,
            n_fft=n_fft,
            hop_length=hop_length,
        )
        bandwidth = np.asarray(bandwidth, dtype=np.float64).reshape(-1)
        finite_bandwidth = bandwidth[np.isfinite(bandwidth)]

        harmonic, percussive = librosa.effects.hpss(mono)
        harmonic_energy = float(np.mean(np.asarray(harmonic, dtype=np.float64) ** 2))
        percussive_energy = float(np.mean(np.asarray(percussive, dtype=np.float64) ** 2))
        separated_total = harmonic_energy + percussive_energy

        if finite_bandwidth.size:
            bandwidth_summary = {
                "p10_hz": float(np.percentile(finite_bandwidth, 10)),
                "median_hz": float(np.median(finite_bandwidth)),
                "p90_hz": float(np.percentile(finite_bandwidth, 90)),
            }
        else:
            bandwidth_summary = {"p10_hz": None, "median_hz": None, "p90_hz": None}

        start = context.absolute_start_seconds
        duration = context.decoded_duration_seconds
        return {
            AnalysisCapability.MIR_TIMBRE.value: {
                "mfcc_shape_mean": {
                    f"c{index + 1}": float(value)
                    for index, value in enumerate(shape_mean)
                },
                "mfcc_shape_std": {
                    f"c{index + 1}": float(value)
                    for index, value in enumerate(shape_std)
                },
                "spectral_contrast_mean_db": {
                    f"band{index}": float(value)
                    for index, value in enumerate(contrast_mean)
                },
                "spectral_contrast_std_db": {
                    f"band{index}": float(value)
                    for index, value in enumerate(contrast_std)
                },
                "spectral_bandwidth": bandwidth_summary,
                "harmonic_energy_fraction": (
                    harmonic_energy / separated_total if separated_total > 0.0 else None
                ),
                "percussive_energy_fraction": (
                    percussive_energy / separated_total if separated_total > 0.0 else None
                ),
                "hpss_energy_ratio_note": (
                    "HPSS fractions summarize separated signal energy and do not prove instrument identity"
                ),
                "n_fft": n_fft,
                "hop_length_samples": hop_length,
                "spectral_contrast_band_count": int(len(contrast_mean)),
                "range": {
                    "start_seconds": start,
                    "end_seconds": start + duration,
                    "duration_seconds": duration,
                },
                "interpretation_note": (
                    "MFCC, contrast, bandwidth and HPSS are timbre descriptors for relative comparison; "
                    "they are not semantic labels or a perceptual quality score"
                ),
            }
        }
