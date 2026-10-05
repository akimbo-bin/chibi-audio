# Architecture
## Authority model
Chibi Core is the durable workflow authority for resumable work. Chibi Audio supplies typed production capabilities; it must not create a parallel scheduler, task database, or autonomous authority.
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
The public capability set is deliberately reviewed and narrow. Proven/current classes include:
- health/version/capability handshake;
- song/arrangement/locator reads;
- tracks/groups/routing plus device and parameter metadata;
- mixer/device reads;
- exact bounded parameter and presentation writes with before-state / Set-signature guards;
- typed ChibiTap setup/configuration/capture and bounded transport;
- narrowly scoped plugin/device experiment operations only when separately proven.

Read reconciliation remains a precondition for mutation. New write classes are added only after their exact targeting, read-back and rollback/effect-certainty semantics are proven on the lab lineage.
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
- Chibi Core remains the durable workflow authority.

The model-facing bridge exposes dedicated `chibitap_setup`, `chibitap_configure`, `chibitap_capture`, and bounded transport capabilities rather than a generic plugin setter. Placement/configuration is fenced by exact track name/index, final-device identity, expected Tap ID / Capture state, and Set signature; capture toggles likewise require fresh before-state guards.

The packaged Max for Live AgentAudioTap implementation remains available as an experimental/fallback adapter for Live-specific cases where Max provides unique value. It is not the primary capture foundation.

### Current proof and next boundary

ChibiTap 0.2.0 multi-tap capture and deterministic requested-range finalization are proven in the real KISSKISSKISS lab Set with no Export Audio/Video dialog and no CUA. Main, BASS and DRUMS taps use durable Tap IDs and host-play gating; finalized artifacts carry exact musical range, sample count, content hashes and Live identity provenance. The next audio-plane problem is throughput and experiment packaging, not basic capture correctness.

See [connection-contract.md](connection-contract.md), [capture-probe.md](capture-probe.md), and `native/ChibiTap/README.md`.
## 5. Execution backends and the stem boundary

Ableton Live remains the **source-project authority**. It owns the real arrangement, saved/unsaved state, track/group/routing topology, sidechains, automation, device chains and any edit that must remain in the project.

REAPER is an optional **downstream stem mixdown/master execution backend**. Chibi does not convert an `.als` project into REAPER. Instead, Live exports an explicit package of aligned audio stems/parts at a chosen signal boundary; REAPER operates only on those rendered signals plus any deliberately reconstructed downstream routing/processing.

A stem package must record at least:
- source Set identity/signature and source project reference;
- export range and common start position;
- sample rate, channel count and bit depth;
- stem/part name plus originating Live track/group identity when available;
- whether each file is pre/post fader and what Live processing is already baked in;
- explicit return-effect and Main/master-effect policy;
- any dedicated sidechain/trigger stems needed downstream;
- hashes and exact sample counts for every exported file;
- the reference Live render(s) used for baseline validation.

Default mixdown export posture is loss-preserving floating-point PCM, no normalization, one common range, and no implicit warping. Shared returns and nonlinear bus/master processing must be represented deliberately rather than accidentally printed multiple times.

### Baseline fidelity gate

Before REAPER candidates become trustworthy, render an **unchanged** REAPER baseline and compare it with the corresponding declared Live stem baseline. A mismatch is evidence that the handoff boundary or reconstruction is wrong.

If a musical interaction depends on processing upstream of the export boundary (for example source envelopes, a Live-only instrument, group compression, external sidechain behavior, feedback routing, or a nonlinear shared bus that was baked inconsistently), do not approximate it by manipulating already-printed stems. Move the export boundary earlier, export the required trigger/context signals, or return the experiment to Live.

REAPER is attractive for this plane because ReaScript exposes project/FX/routing/render controls and REAPER supports full-speed offline rendering, stem rendering, render queues and render-matrix/batch workflows. Offline rendering is still plugin-dependent: candidates that rely on a plugin whose offline behavior differs must either use a safer render mode or fail the fidelity gate.

See [stem-mixdown-reaper.md](stem-mixdown-reaper.md).

## 6. Plugin knowledge base
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
## 7. Sample library index
Start read-only. Index metadata without reorganizing files. Later derive duration, sample rate, channels, BPM/key estimates, transient/spectral features and semantic embeddings where useful.
Moving, renaming or deduplicating samples is a separate opt-in capability because existing Live Sets may reference exact paths.
## 8. Audio evidence and synthetic hearing layer
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
## 9. Experiment engine
A material subjective change is an experiment, not an opaque edit.
Each experiment records:
- baseline snapshot identifier;
- exact project/section/targets;
- hypothesis;
- exact change set and ranges;
- observed post-write values;
- A/B render identifiers;
- execution backend (`live`, `reaper_stem`, or other reviewed backend);
- stem-package/baseline-fidelity identity when a downstream backend is used;
- wall-clock timing breakdown for setup, render/capture, finalization, analysis and controller overhead;
- level-matched metrics;
- perceptual/translation predictions when relevant;
- user verdict: keep, refine, reject, rollback;
- later real-playback validation where available.
The experiment engine is the basis for later automated EQ, dynamics, sidechain and mastering exploration.
## 10. Mutation/effect certainty
Every Live write batch follows:
`REFRESH -> RESOLVE -> CHECKPOINT -> MUTATE -> VERIFY -> MEASURE -> ACCEPT/ROLLBACK`
If the observed effect cannot be confirmed, effect state is UNKNOWN and the mutation must be reconciled before any replay.

REAPER/stem candidates use the same experiment semantics but do **not** masquerade as Live mutations. Their provenance must identify the immutable stem package and REAPER project/candidate state. A REAPER winner changes the Live project only if a separate Live mutation is later authorized and verified.
## 11. Chibi integration
The stable workflow commands are designed for Chibi Core now. Core remains the durable planner/task authority; Chibi Audio is a specialized executor + evidence system, and execution-backend choice is part of the workflow plan rather than a second authority.
See [ecosystem-research.md](ecosystem-research.md) for upstream component decisions and [pilot-kisskisskiss.md](pilot-kisskisskiss.md) for the first proof.
