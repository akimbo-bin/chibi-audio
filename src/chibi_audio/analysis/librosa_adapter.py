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
        capabilities=frozenset(
            {
                AnalysisCapability.MIR_ONSETS,
                AnalysisCapability.MIR_TONAL,
                AnalysisCapability.MIR_STRUCTURE,
                AnalysisCapability.MIR_PITCH,
            }
        ),
        cost=AnalysisCost.MODERATE,
        implementation="librosa onset / tempo / chroma / pYIN pitch / bounded novelty evidence",
        upstream="librosa/librosa",
        license="ISC",
        available=available,
        unavailable_reason=reason,
    )


def _structure_boundaries(librosa, np, mono, sr: int, absolute_start: float) -> dict[str, Any]:
    hop_length = 512
    mel = librosa.feature.melspectrogram(
        y=mono,
        sr=sr,
        n_fft=2048,
        hop_length=hop_length,
        n_mels=48,
        power=2.0,
    )
    if mel.size == 0 or mel.shape[1] < 2:
        return {
            "boundary_candidates_seconds": [],
            "boundary_candidate_strength": [],
            "novelty_median": 0.0,
            "novelty_p95": 0.0,
            "method": "log-mel frame-difference novelty",
        }

    log_mel = librosa.power_to_db(mel, ref=np.max)
    novelty = np.linalg.norm(np.diff(log_mel, axis=1), axis=0)
    if novelty.size >= 5:
        novelty = np.convolve(novelty, np.ones(5, dtype=np.float64) / 5.0, mode="same")

    median = float(np.median(novelty))
    p95 = float(np.percentile(novelty, 95))
    if not np.any(novelty > 0.0):
        candidate_indices: list[int] = []
    else:
        local_maxima = []
        for index in range(1, max(1, len(novelty) - 1)):
            if novelty[index] >= novelty[index - 1] and novelty[index] > novelty[index + 1]:
                local_maxima.append(index)
        threshold = max(p95, median)
        local_maxima = [index for index in local_maxima if float(novelty[index]) >= threshold]
        minimum_gap_frames = max(1, round(1.5 * sr / hop_length))
        chosen: list[int] = []
        for index in sorted(local_maxima, key=lambda value: float(novelty[value]), reverse=True):
            if all(abs(index - existing) >= minimum_gap_frames for existing in chosen):
                chosen.append(index)
            if len(chosen) >= 12:
                break
        candidate_indices = sorted(chosen)

    frame_numbers = np.asarray([index + 1 for index in candidate_indices], dtype=np.int64)
    times = librosa.frames_to_time(frame_numbers, sr=sr, hop_length=hop_length)
    strengths = [float(novelty[index]) for index in candidate_indices]
    return {
        "boundary_candidates_seconds": [absolute_start + float(value) for value in times],
        "boundary_candidate_strength": strengths,
        "novelty_median": median,
        "novelty_p95": p95,
        "method": "log-mel frame-difference novelty",
    }


def _pitch_evidence(librosa, np, mono, sr: int) -> dict[str, Any]:
    hop_length = 512
    nyquist_guard = sr * 0.49
    fmin = float(librosa.note_to_hz("C1"))
    fmax = min(float(librosa.note_to_hz("C8")), nyquist_guard)
    if fmax <= fmin:
        return {
            "voiced_frame_fraction": 0.0,
            "median_hz": None,
            "p10_hz": None,
            "p90_hz": None,
            "median_midi": None,
            "pitch_range_p10_to_p90_semitones": None,
            "median_pitch_class_evidence": None,
            "median_voicing_probability": None,
            "hop_length_samples": hop_length,
            "interpretation_note": "pYIN evidence is for predominantly monophonic material; it does not transcribe chords",
        }

    f0, voiced_flag, voiced_probability = librosa.pyin(
        mono,
        fmin=fmin,
        fmax=fmax,
        sr=sr,
        frame_length=2048,
        hop_length=hop_length,
    )
    finite = np.isfinite(f0)
    total_frames = max(1, len(f0))
    voiced_hz = np.asarray(f0[finite], dtype=np.float64)
    if not voiced_hz.size:
        return {
            "voiced_frame_fraction": 0.0,
            "median_hz": None,
            "p10_hz": None,
            "p90_hz": None,
            "median_midi": None,
            "pitch_range_p10_to_p90_semitones": None,
            "median_pitch_class_evidence": None,
            "median_voicing_probability": None,
            "hop_length_samples": hop_length,
            "interpretation_note": "pYIN evidence is for predominantly monophonic material; it does not transcribe chords",
        }

    midi = np.asarray(librosa.hz_to_midi(voiced_hz), dtype=np.float64)
    median_midi = float(np.median(midi))
    p10_midi = float(np.percentile(midi, 10))
    p90_midi = float(np.percentile(midi, 90))
    median_pitch_class = _PITCH_CLASSES[int(round(median_midi)) % 12]
    probability = np.asarray(voiced_probability, dtype=np.float64)
    finite_probability = probability[finite & np.isfinite(probability)]

    return {
        "voiced_frame_fraction": float(np.count_nonzero(finite) / total_frames),
        "median_hz": float(np.median(voiced_hz)),
        "p10_hz": float(np.percentile(voiced_hz, 10)),
        "p90_hz": float(np.percentile(voiced_hz, 90)),
        "median_midi": median_midi,
        "pitch_range_p10_to_p90_semitones": p90_midi - p10_midi,
        "median_pitch_class_evidence": median_pitch_class,
        "median_voicing_probability": (
            float(np.median(finite_probability)) if finite_probability.size else None
        ),
        "hop_length_samples": hop_length,
        "interpretation_note": "pYIN evidence is for predominantly monophonic material; it does not transcribe chords",
    }


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
        if AnalysisCapability.MIR_ONSETS in requested or AnalysisCapability.MIR_STRUCTURE in requested:
            onset_envelope = librosa.onset.onset_strength(y=mono, sr=sr)

        if AnalysisCapability.MIR_ONSETS in requested:
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

        if AnalysisCapability.MIR_PITCH in requested:
            result[AnalysisCapability.MIR_PITCH.value] = _pitch_evidence(librosa, np, mono, sr)

        if AnalysisCapability.MIR_STRUCTURE in requested:
            novelty = _structure_boundaries(
                librosa,
                np,
                mono,
                sr,
                context.absolute_start_seconds,
            )
            local_tempo = librosa.feature.tempo(
                onset_envelope=onset_envelope,
                sr=sr,
                aggregate=None,
            )
            local_tempo = np.asarray(local_tempo, dtype=np.float64)
            finite_tempo = local_tempo[np.isfinite(local_tempo) & (local_tempo > 0.0)]
            if finite_tempo.size:
                tempo_summary = {
                    "median_bpm": float(np.median(finite_tempo)),
                    "p10_bpm": float(np.percentile(finite_tempo, 10)),
                    "p90_bpm": float(np.percentile(finite_tempo, 90)),
                }
            else:
                tempo_summary = {"median_bpm": None, "p10_bpm": None, "p90_bpm": None}
            result[AnalysisCapability.MIR_STRUCTURE.value] = {
                **novelty,
                "local_tempo_evidence": tempo_summary,
                "interpretation_note": (
                    "boundary candidates are signal-derived change points, not functional labels; "
                    "artist-authored Ableton Locators remain authoritative song structure metadata"
                ),
            }

        return result
