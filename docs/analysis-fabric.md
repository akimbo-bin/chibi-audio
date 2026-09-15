# Chibi Audio analysis fabric

Issue: #8

This lane owns reusable, on-demand audio evidence. It is deliberately separate from both the ChibiTap capture lane and the typed Ableton/MCP lane in #6 / PR #7.

## Contract

Callers request only the capabilities they need:

- `audio.metadata`
- `audio.levels`
- `audio.activity`
- `audio.stereo`
- `audio.spectrum`
- `audio.transients`
- `audio.texture`
- `audio.stereo.bands`
- `audio.loudness`
- `audio.mir.onsets`
- `audio.mir.tonal`
- `audio.mir.structure`
- `audio.mir.pitch`
- `audio.mir.transcription` (optional Basic Pitch, EXPENSIVE)
- `audio.semantic` (optional local CLAP, EXPENSIVE)

Each analyzer declares exact name/version, capability set, CHEAP / MODERATE / EXPENSIVE cost class, implementation/upstream provenance, license signal, and current runtime availability.

The planner refuses a request when the capability is unavailable or exceeds the caller's cost ceiling. There is no implicit `analyze everything` path.

## Capture integration

ChibiTap capture finalization already emits per-artifact path, byte size, modified timestamp and exact SHA-256. `analyze_capture_manifest(...)` consumes that finalized manifest directly and can analyze every tap or an explicit tap subset.

Before reusing the recorded SHA-256, the manifest adapter reconciles the current file's size and modification timestamp against finalization evidence. If the artifact changed or disappeared, analysis fails closed rather than assigning stale cache identity to different bytes.

`AudioAnalysisService.analyze(..., content_sha256=...)` then accepts the already-proven capture digest, so normal analysis does not need to hash a large finalized capture a second time.

Analysis can also be bounded by exact `start_seconds` / `end_seconds`. PR #7 can later resolve an Ableton locator or named section to a range and pass only the desired audio window to this layer. This layer does not read or mutate the Live Set itself.

## Cheap and moderate production evidence

Cheap signal capabilities share one decoded NumPy pass. Metadata uses `ffprobe` without decoding the payload.

`audio.transients` adds bounded frame-envelope evidence: strongest-event time, attack/decay evidence, transient-to-body ratio, microdynamic range and strong-rise density. These are descriptors, not a "punch" quality score.

`audio.texture` adds bounded spectral flatness, flux, zero-crossing and high-frequency energy evidence.

`audio.stereo.bands` computes frequency-dependent cross-power correlation and Mid/Side energy across sub, low, mid, high and air bands. It can identify band-local polarity/mono-compatibility evidence that a single broadband correlation value hides.

`audio.loudness` is MODERATE and uses an explicit FFmpeg `loudnorm` measurement pass. It reports integrated LUFS, loudness range and FFmpeg's measured true peak for the requested range; those numbers are evidence, not mastering targets.

The decode context is lazy and shared. A metadata-only request never decodes audio.

## MIR evidence

The optional librosa adapter remains MODERATE and currently provides:

- onset count/timing/density plus tempo evidence;
- normalized chroma profile plus dominant pitch-class evidence;
- bounded log-mel novelty/change-point candidates plus local-tempo evidence;
- pYIN monophonic pitch evidence (`audio.mir.pitch`) with voiced fraction, median/range Hz and MIDI evidence, pitch class and voicing confidence.

pYIN is intentionally described as monophonic evidence. It does not claim to transcribe chords or replace source MIDI.

`audio.mir.structure` does not invent authoritative verse/chorus labels. Artist-authored Ableton Locators remain the structure authority when present.

## Polyphonic transcription — Basic Pitch

`audio.mir.transcription` is an EXPENSIVE optional adapter for Spotify Basic Pitch (Apache-2.0).

The adapter materializes only the exact requested range as a temporary mono 22.05 kHz WAV, runs the packaged Basic Pitch model, deletes the temporary file, and returns bounded note-event evidence:

- absolute start/end time;
- MIDI note and pitch class;
- amplitude;
- bounded pitch-bend summary;
- total note count;
- estimated peak polyphony;
- duration/amplitude-weighted pitch-class profile.

`transcription_max_notes` bounds the returned event list (default 512; hard maximum 4096). Summary evidence is computed over the full predicted event set before truncating the returned list.

Basic Pitch estimates are not authoritative MIDI.

## Semantic audio understanding — local CLAP

`audio.semantic` is an EXPENSIVE optional audio/text similarity capability implemented against Hugging Face Transformers CLAP / LAION CLAP (Apache-2.0).

It is deliberately fail-closed and **never downloads a model at analysis time**.

Runtime provisioning requires:

- `torch` and `transformers`;
- `CHIBI_AUDIO_CLAP_MODEL_DIR` pointing to a fully local CLAP model directory;
- an unfused CLAP checkpoint;
- `CHIBI_AUDIO_CLAP_MODEL_SHA256` containing the exact Chibi model-identity digest for the local config/tokenizer/preprocessor/weight files.

The declared model identity becomes part of analyzer provenance and therefore analysis-cache identity. On first use Chibi recomputes the configured local identity before loading the model; a mismatch refuses analysis.

Hugging Face's CLAP feature extractor can use randomized truncation for long inputs. Chibi does not use that behavior. It decodes the exact requested range to mono at the model sampling rate, divides it into deterministic windows no longer than the model's maximum input, chooses at most `semantic_max_windows` evenly across long material, and invokes `rand_trunc` only on windows that are already within the maximum length. This keeps Chibi's evidence/cache contract reproducible.

Callers provide `semantic_queries`, for example:

```text
["dark closed hi-hat", "bright metallic hi-hat", "noisy shaker"]
```

The result ranks those supplied queries by mean cosine similarity and includes min/max window similarity plus the strongest absolute-time window. Raw embedding vectors are intentionally not returned. Similarity is relative evidence, not a calibrated probability or quality score.

## Comparison without more DSP

`compare_reports(left, right, ...)` operates only on already-computed reports. It never reopens audio. This gives Chibi a cheap second-stage primitive for build/drop contrast, pre/post A/B evidence, mix/reference evidence and aligned captured-tap comparisons.

Comparison deltas are explicit `right - left` observations. They never mean better/worse.

## Evidence semantics

The core intentionally separates observations from subjective conclusions:

- sample peak is not true peak;
- true peak is populated only by the separately identified FFmpeg loudness analyzer;
- stereo correlation / side energy are evidence, not a width-quality score;
- broad spectral bands are evidence, not an EQ prescription;
- librosa dominant pitch-class evidence is not a key claim;
- librosa tempo evidence is not authoritative Live Set tempo;
- novelty boundaries are not functional song-section labels;
- pYIN pitch is monophonic evidence, not polyphonic transcription;
- Basic Pitch output is estimated note evidence, not authoritative MIDI;
- CLAP cosine similarity is semantic evidence relative to supplied prompts, not probability.

Float ChibiTap captures can exceed normalized magnitude 1.0. The levels report therefore includes sample-over count/fraction instead of silently clipping the evidence.

## Licensing / dependency posture

- NumPy: core analysis dependency.
- FFmpeg/ffprobe: external runtime tools for decode/probe/loudness.
- librosa (ISC): optional MODERATE MIR adapter; CI-proven on Python 3.11 with 0.11.0.
- Spotify Basic Pitch (Apache-2.0): optional EXPENSIVE transcription adapter with separate real-model CI.
- Hugging Face Transformers + LAION CLAP (Apache-2.0): optional EXPENSIVE semantic adapter; local-model-only and fail-closed until explicitly provisioned.
- Essentia: useful research material, but not a core dependency because of AGPLv3 distribution implications.
- Demucs/source separation: later EXPENSIVE/reference-only work; never a normal default analyzer.

This PR does not add the optional model stacks to `pyproject.toml`; PR #7 currently owns that shared file. Runtime availability is advertised truthfully and the planner refuses unavailable capabilities.

## Intended MCP seam

The MCP/control lane should eventually need only a thin call resembling:

```text
list_audio_analyzers()
analyze_audio(artifact_ref, capabilities, max_cost, start_seconds?, end_seconds?, semantic_queries?)
analyze_capture_manifest(manifest_ref, capabilities, tap_ids?, max_cost)
compare_analysis_reports(left_report_ref, right_report_ref)
```

It should not expose analyzer implementation details as workflow authority. Chibi/Core/ChatGPT decides what evidence is needed; this package computes the requested evidence and returns provenance.
