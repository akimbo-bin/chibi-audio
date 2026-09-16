from __future__ import annotations

from collections import defaultdict
import contextlib
import io
from importlib import metadata, util
from pathlib import Path
from typing import Any

from .io import AnalysisContext, materialize_audio_segment
from .models import AnalysisCapability, AnalysisCost, AnalyzerDescriptor


_PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def basic_pitch_descriptor() -> AnalyzerDescriptor:
    available = util.find_spec("basic_pitch") is not None
    version = "unavailable"
    reason = None
    if available:
        try:
            version = metadata.version("basic-pitch")
        except metadata.PackageNotFoundError:
            available = False
            reason = "basic-pitch import spec exists but package metadata is unavailable"
    else:
        reason = "basic-pitch is not installed"
    return AnalyzerDescriptor(
        name="basic_pitch_transcription",
        version=version,
        capabilities=frozenset({AnalysisCapability.MIR_TRANSCRIPTION}),
        cost=AnalysisCost.EXPENSIVE,
        implementation="Spotify Basic Pitch bounded polyphonic note-event evidence",
        upstream="spotify/basic-pitch",
        license="Apache-2.0",
        available=available,
        unavailable_reason=reason,
    )


def _polyphony_peak(note_events) -> int:
    sweep: list[tuple[float, int]] = []
    for start, end, *_ in note_events:
        sweep.append((float(start), 1))
        sweep.append((float(end), -1))
    sweep.sort(key=lambda value: (value[0], value[1]))
    active = 0
    peak = 0
    for _, delta in sweep:
        active += delta
        peak = max(peak, active)
    return peak


def _pitch_class_profile(note_events) -> dict[str, float]:
    totals = defaultdict(float)
    total_weight = 0.0
    for start, end, pitch, amplitude, _ in note_events:
        weight = max(0.0, float(end) - float(start)) * max(0.0, float(amplitude))
        totals[_PITCH_CLASSES[int(pitch) % 12]] += weight
        total_weight += weight
    if total_weight <= 0.0:
        return {name: 0.0 for name in _PITCH_CLASSES}
    return {name: totals[name] / total_weight for name in _PITCH_CLASSES}


class BasicPitchTranscriptionAnalyzer:
    @property
    def descriptor(self) -> AnalyzerDescriptor:
        return basic_pitch_descriptor()

    def analyze(self, context: AnalysisContext) -> dict[str, Any]:
        descriptor = self.descriptor
        if not descriptor.available:
            raise RuntimeError(descriptor.unavailable_reason or "Basic Pitch is unavailable")

        import basic_pitch
        from basic_pitch.inference import predict

        model_path = Path(basic_pitch.ICASSP_2022_MODEL_PATH)
        if not model_path.exists():
            raise RuntimeError(f"Basic Pitch packaged model is unavailable: {model_path}")

        with materialize_audio_segment(
            context.path,
            context.request,
            sample_rate=22050,
            channels=1,
        ) as segment:
            with contextlib.redirect_stdout(io.StringIO()):
                _, _, note_events = predict(segment, model_path)

        ordered = sorted(note_events, key=lambda value: (float(value[0]), int(value[2]), float(value[1])))
        absolute_start = context.absolute_start_seconds
        note_limit = context.request.transcription_max_notes
        returned = []
        for start, end, pitch, amplitude, pitch_bends in ordered[:note_limit]:
            bends = [int(value) for value in pitch_bends] if pitch_bends else []
            returned.append(
                {
                    "start_seconds": absolute_start + float(start),
                    "end_seconds": absolute_start + float(end),
                    "duration_seconds": max(0.0, float(end) - float(start)),
                    "midi_note": int(pitch),
                    "pitch_class": _PITCH_CLASSES[int(pitch) % 12],
                    "amplitude": float(amplitude),
                    "pitch_bend_sample_count": len(bends),
                    "pitch_bend_min_third_semitones": min(bends) if bends else None,
                    "pitch_bend_max_third_semitones": max(bends) if bends else None,
                }
            )

        pitches = [int(value[2]) for value in ordered]
        return {
            AnalysisCapability.MIR_TRANSCRIPTION.value: {
                "note_count": len(ordered),
                "returned_note_count": len(returned),
                "notes_truncated": len(ordered) > note_limit,
                "note_events": returned,
                "pitch_midi_min": min(pitches) if pitches else None,
                "pitch_midi_max": max(pitches) if pitches else None,
                "peak_estimated_polyphony": _polyphony_peak(ordered),
                "duration_amplitude_weighted_pitch_class_profile": _pitch_class_profile(ordered),
                "model_runtime": descriptor.version,
                "input_materialization": "exact requested range, mono PCM16 WAV at 22050 Hz",
                "interpretation_note": (
                    "Basic Pitch note events are model estimates, not authoritative source MIDI; "
                    "use them as evidence for played pitches, melody and polyphonic content"
                ),
            }
        }
