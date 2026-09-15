from __future__ import annotations

from importlib import metadata, util
from typing import Any

from .io import AnalysisContext, _np
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


_PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def librosa_descriptor() -> AnalyzerDescriptor:
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
        name="librosa_mir",
        version=version,
        capabilities=frozenset({AnalysisCapability.MIR_ONSETS, AnalysisCapability.MIR_TONAL}),
        cost=AnalysisCost.MODERATE,
        implementation="librosa onset envelope / tempo / chroma-STFT evidence",
        upstream="librosa/librosa",
        license="ISC",
        available=available,
        unavailable_reason=reason,
    )


class LibrosaMirAnalyzer:
    @property
    def descriptor(self) -> AnalyzerDescriptor:
        return librosa_descriptor()

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        if not self.descriptor.available:
            raise RuntimeError(self.descriptor.unavailable_reason or "librosa is unavailable")
        import librosa

        np = _np()
        audio = context.audio.astype(np.float32, copy=False)
        mono = np.mean(audio, axis=1)
        sr = context.request.sample_rate
        requested = context.request.capabilities
        result: dict[str, Any] = {}

        onset_envelope = None
        if AnalysisCapability.MIR_ONSETS in requested:
            onset_envelope = librosa.onset.onset_strength(y=mono, sr=sr)
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=onset_envelope,
                sr=sr,
                units="frames",
                backtrack=False,
            )
            onset_times = librosa.frames_to_time(onset_frames, sr=sr)
            absolute = [context.absolute_start_seconds + float(value) for value in onset_times]
            duration = max(context.decoded_duration_seconds, 1e-12)
            tempo_values = librosa.feature.tempo(onset_envelope=onset_envelope, sr=sr)
            tempo_bpm = float(np.median(tempo_values)) if len(tempo_values) else None
            result[AnalysisCapability.MIR_ONSETS.value] = {
                "onset_count": int(len(onset_frames)),
                "onset_density_per_second": float(len(onset_frames) / duration),
                "onset_times_seconds": absolute,
                "tempo_bpm_evidence": tempo_bpm,
                "tempo_note": "tempo is signal-derived evidence, not authoritative Live Set tempo",
            }

        if AnalysisCapability.MIR_TONAL in requested:
            chroma = librosa.feature.chroma_stft(y=mono, sr=sr)
            profile = np.mean(chroma, axis=1) if chroma.size else np.zeros(12, dtype=np.float64)
            total = float(np.sum(profile))
            normalized = profile / total if total > 0 else profile
            dominant_index = int(np.argmax(normalized)) if total > 0 else None
            result[AnalysisCapability.MIR_TONAL.value] = {
                "chroma_profile": {
                    name: float(normalized[index])
                    for index, name in enumerate(_PITCH_CLASSES)
                },
                "dominant_pitch_class_evidence": (
                    _PITCH_CLASSES[dominant_index] if dominant_index is not None else None
                ),
                "tonal_concentration": float(np.max(normalized)) if total > 0 else None,
                "interpretation_note": "dominant pitch class is evidence only; this analyzer does not claim musical key",
            }

        return result
