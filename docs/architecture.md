# Architecture
## Authority model
Chibi Core is the eventual workflow authority. Chibi Audio supplies typed production capabilities; it must not create a parallel scheduler, task database, or autonomous authority.
The DAW bridge is an executor. The analysis stack is evidence. The artist remains the acceptance authority for subjective musical choices.
## 1. Two project snapshots, one reconciled model
### Saved snapshot
Read Ableton `.als` files as read-only durable project snapshots. Extract structure such as track/group hierarchy, device chains, routing data, automation metadata, samples/files, locators and tempo where represented.
Normal operation never writes `.als` XML directly.
### Live snapshot
Read the currently open Set through a small Live 12 Python Remote Script using the Live Object Model. The live snapshot can include unsaved edits that are absent from disk.
### Reconciliation
Build a reconciled project graph that records:
- saved-only state;
- live-only/unsaved state;
- confidently matched objects;
- ambiguous/unresolved matches.
Do not guess ambiguous object identity. An operation may target only a freshly reconciled exact object.
## 2. Thin Live bridge
Use a small Python Remote Script inside Live 12 with a localhost-only transport. Keep networking, persistence, analysis, A/B state and AI reasoning outside the DAW process.
Research shows that existing Ableton MCP projects already implement much of the commodity bridge surface. We should adapt reviewed patterns rather than adopt an all-powerful upstream server unchanged.
Initial public capability set is deliberately small:
- health/version/capability handshake;
- get song/arrangement metadata;
- list tracks/groups and routing;
- list devices and parameter metadata;
- read mixer/device values;
- read locators and relevant automation metadata.
Only after read reconciliation is proven do we add bounded writes such as rename, recolor and exact parameter changes.
### Explicit exclusions
- no arbitrary Python/eval capability;
- no remote network listener beyond localhost;
- no hidden telemetry;
- no silent GUI fallback;
- no autonomous save/overwrite of the artist's only Set.
## 3. UI accessibility is bootstrap observability, not steady-state authority
Windows accessibility can currently expose a surprising amount of Live state and is useful for prototyping/verification. It is not the desired primary mutation path because UI layout and focus are less stable than typed Live objects.
Use UI automation only for operations that genuinely lack a structured seam, and make that fallback explicit.
## 4. Audio capture plane: ChibiTap VST3

ChibiTap is the primary audio-rate evidence path. It is a deliberately small JUCE/VST3 effect that receives the real host audio buffer, leaves that buffer unchanged, and writes IEEE float32 capture evidence through JUCE `AudioFormatWriter::ThreadedWriter`.

Responsibilities stay separated:
- the Live Remote Script owns structured Ableton state, browser access, transport and narrowly authorized parameter control;
- ChibiTap owns transparent audio observation only;
- local Chibi Audio services own capture manifests, artifact hashing, analysis and experiment comparison;
- Chibi Core remains the eventual workflow authority.

The model-facing bridge exposes dedicated `chibitap_setup`, `chibitap_configure`, `chibitap_capture`, and bounded transport capabilities rather than a generic plugin setter. Placement/configuration is fenced by exact track name/index, final-device identity, expected Tap ID / Capture state, and Set signature; capture toggles likewise require fresh before-state guards.

The packaged Max for Live AgentAudioTap implementation remains available as an experimental/fallback adapter for Live-specific cases where Max provides unique value. It is not the primary capture foundation.

### Current proof and next boundary

ChibiTap 0.2.0 multi-tap capture is proven in the real KISSKISSKISS lab Set with no Export Audio/Video dialog and no CUA. Main, BASS and DRUMS taps use durable Tap IDs and host-play gating and produced equal-length sample-aligned float32 artifacts in one playback pass. The remaining audio-plane boundary is deterministic requested-range finality: end/crop on the exact host musical/sample boundary rather than after an externally polled transport stop.

See [connection-contract.md](connection-contract.md), [capture-probe.md](capture-probe.md), and `native/ChibiTap/README.md`.
## 5. Plugin knowledge base
Build a machine-local logical-product catalog from the user's actual plugin installation and Live-visible devices.
Useful fields:
- vendor/product/version;
- formats and paths/fingerprints;
- normalized logical product across VST2/VST3/CLAP duplicates;
- categories and intended roles;
- parameter metadata exposed by Live;
- grounded manuals/documentation when useful;
- user-specific favorites and proven use cases.
Machine-specific paths and private inventory dumps stay local by default.
## 6. Sample library index
Start read-only. Index metadata without reorganizing files. Later derive duration, sample rate, channels, BPM/key estimates, transient/spectral features and semantic embeddings where useful.
Moving, renaming or deduplicating samples is a separate opt-in capability because existing Live Sets may reference exact paths.
## 7. Audio evidence and synthetic hearing layer
Analyze real renders and typed captures by musical section and event, not only whole-song averages. The goal is not to make one metric decide whether audio `sounds good`; it is to give the reasoning worker enough independent senses to form better, testable hypotheses.

### Deterministic signal evidence
Near-term core measurements include:
- LUFS and true/sample peak;
- RMS and crest factor;
- band energy/spectral balance;
- transient density and envelope behavior;
- stereo width/correlation and Mid/Side balance;
- low-end overlap;
- level-matched A/B deltas.
A user-supplied reference can be analyzed through the same measurements.

### Psychoacoustic evidence
Add perceptually motivated measurements where they improve diagnosis:
- critical-band / Bark / ERB-domain energy;
- specific loudness and loudness by perceptual band;
- sharpness, roughness, tonality and related descriptors;
- masking and source-audibility estimates;
- perceptual distinctions between brightness, sharpness, sibilance, transient hardness, resonant whistles and distortion/fizz.
These measurements remain evidence, not musical truth.

### Harmonic survivability and source audibility
For tonal sources such as bass, estimate fundamental/harmonic trajectories and which partials remain perceptible when low-frequency reproduction disappears or competing sources mask them. This supports questions such as `will the bass still read on a phone?` without reducing the answer to total low-frequency energy.

### Playback translation profiles
Support explicit diagnostic playback profiles such as full-range reference monitoring, phone-like bandwidth, laptop/small speaker, mono, low-volume listening and optional user-calibrated devices such as a specific car or speaker.
Profiles are approximations. Their purpose is to test whether important source relationships, harmonics and perceptual cues survive translation, not to claim exact hardware emulation.

### Aligned signal-point forensics
When capture support allows it, compare bounded aligned windows across useful signal points:
- source / track pre-FX;
- track post-FX;
- group pre/post processing;
- premaster;
- mastered output.
This lets Chibi distinguish a harsh source from harshness introduced by saturation, compression, limiting or other downstream processing. Small controlled bypass or parameter perturbations may be used to build causal sensitivity maps when authorized.

### Event-level analysis
Average track statistics can hide isolated problems. Detect and rank musically meaningful events such as hats, sibilants, kicks, bass notes or limiter-driving transients by salience, overlap, sharpness/roughness, masking and downstream stress. Report the exact events/sections responsible whenever possible.

### Semantic audio evidence
Audio embeddings or audio-language models may be used as weak semantic sensors for descriptors such as `bright`, `metallic`, `punchy`, `muffled` or `harsh`. They must not be treated as authoritative mastering judges and should be paired with inspectable signal evidence.

### Sensor calibration
When the system predicts a translation or perceptual outcome and the artist later checks it on real playback (phone, car, headphones, etc.), record prediction versus outcome. Use those observations to calibrate, down-weight or retire sensors that do not predict useful outcomes. This does not require model fine-tuning; calibration and retrieval of relevant prior evidence are sufficient first steps.

The reasoning model integrates these sensors; it is not itself assumed to possess mastering-grade hearing.
## 8. Experiment engine
A material subjective change is an experiment, not an opaque edit.
Each experiment records:
- baseline snapshot identifier;
- exact project/section/targets;
- hypothesis;
- exact change set and ranges;
- observed post-write values;
- A/B render identifiers;
- level-matched metrics;
- perceptual/translation predictions when relevant;
- user verdict: keep, refine, reject, rollback;
- later real-playback validation where available.
The experiment engine is the basis for later automated EQ, dynamics, sidechain and mastering exploration.
## 9. Mutation/effect certainty
Every write batch follows:
`REFRESH -> RESOLVE -> CHECKPOINT -> MUTATE -> VERIFY -> MEASURE -> ACCEPT/ROLLBACK`
If the observed effect cannot be confirmed, effect state is UNKNOWN and the mutation must be reconciled before any replay.
## 10. Chibi integration
Once the pilot surface is stable, expose these capabilities through Chibi Core. Core remains the durable planner/task authority; Chibi Audio is a specialized executor + evidence system.
See [ecosystem-research.md](ecosystem-research.md) for upstream component decisions and [pilot-kisskisskiss.md](pilot-kisskisskiss.md) for the first proof.
