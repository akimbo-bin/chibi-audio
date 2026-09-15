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
- `audio.mir.onsets` (optional librosa adapter)
- `audio.mir.tonal` (optional librosa adapter)

Each analyzer declares:

- exact name/version;
- capability set;
- CHEAP / MODERATE / EXPENSIVE cost class;
- implementation/upstream provenance;
- license signal;
- current runtime availability.

The planner refuses a request when the capability is unavailable or exceeds the caller's cost ceiling. There is no implicit `analyze everything` path.

## Capture integration

ChibiTap capture finalization already emits exact SHA-256 artifact identities. `AudioAnalysisService.analyze(..., content_sha256=...)` accepts that existing digest, so a caller does not need to hash a large capture again merely to obtain a stable analysis/cache key.

Analysis can be bounded by exact `start_seconds` / `end_seconds`. PR #7 can later resolve an Ableton locator or named section to a time/beat range and pass only the desired audio window to this layer. This layer does not read or mutate the Live Set itself.

## Compute behavior

Cheap signal capabilities share one decoded NumPy pass. Metadata uses `ffprobe` without decoding the payload. Spectral analysis is MODERATE and samples a bounded number of Hann-window FFT windows rather than building a full spectrogram.

Stereo spectrum is calculated by averaging channel power after FFT. It does not mono-sum first, because polarity-opposed stereo can cancel in a mono waveform while still containing real spectral energy.

The decode context is lazy and shared. A metadata-only request never decodes audio; multiple selected core analyzers reuse the same bounded decoded segment.

## Evidence semantics

The core intentionally separates observations from subjective conclusions:

- sample peak is not true peak;
- `true_peak_dbtp` stays null in the NumPy signal analyzer;
- stereo correlation / side energy are evidence, not a width-quality score;
- broad spectral bands are evidence, not an EQ prescription;
- librosa dominant pitch-class evidence is not a key claim;
- librosa tempo evidence is not authoritative Live Set tempo.

Float ChibiTap captures can exceed normalized magnitude 1.0. The levels report therefore includes sample-over count/fraction instead of silently clipping the evidence.

## Optional repository adapters

### librosa — adopted selectively

The existing ecosystem decision marks `librosa/librosa` (ISC) as suitable for adoption. The first adapter is lazy: Chibi Audio advertises its capabilities even when librosa is not installed, but the planner will not select it until the runtime can actually provide it.

The first MIR capabilities are intentionally narrow:

- onset count/timing/density plus tempo evidence;
- normalized chroma profile plus dominant pitch-class evidence.

No large model is required.

### Essentia — reference / isolated optional only

`MTG/essentia` remains useful research material but is not a core dependency because the observed checkout is AGPLv3. Do not silently pull it into the distributed base package.

### Demucs — later EXPENSIVE tier

`facebookresearch/demucs` remains an optional source-separation backend for reference-track diagnostics when source tracks do not exist. It should not run for normal mix questions and should never replace real track-level ChibiTap evidence.

## Next adapters

1. standards-oriented loudness capability with integrated/short-term LUFS, LRA and a clearly proven true-peak implementation;
2. section/change novelty evidence using librosa primitives;
3. reference comparison using identical capability/range requests against target and reference artifacts;
4. event-aligned cross-track evidence once ChibiTap multi-tap capture manifests are available to the caller;
5. optional Demucs-backed reference decomposition behind EXPENSIVE cost and explicit request.

## Intended MCP seam

The MCP/control lane should eventually need only a thin call resembling:

```text
list_audio_analyzers()
analyze_audio(artifact_ref, capabilities, max_cost, start_seconds?, end_seconds?)
```

It should not expose analyzer implementation details as workflow authority. Chibi/Core/ChatGPT decides what evidence is needed; this package computes the requested evidence and returns provenance.