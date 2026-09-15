# Roadmap
The roadmap is deliberately pilot-first. New platform work is allowed only when the current acceptance boundary needs it.
## R0 - Establish reality and a safe playground - DONE
Completed:
- read real `.als` files without mutation;
- map the real KISSKISSKISS track/group/device structure;
- inventory installed VST2/VST3/CLAP files;
- discover Ableton Places/sample-library roots;
- survey and clone a focused upstream component shortlist;
- create a separate `KISSKISSKISS Chibi Lab` project folder from the last saved project state.
Additional proof completed:
- current unsaved state preserved into the Chibi Lab lineage;
- live/saved track order reconciled 87/87 before bounded writes;
- original project remained untouched.
**Acceptance:** the original Set is untouched and we can identify exactly which project lineage is safe to edit.
## R1 - Read the currently open Set deeply - PILOT READ PATH PROVEN
Build the minimum read-only Live bridge needed for the pilot.
Scope:
- health/version handshake;
- tempo, arrangement and locator reads;
- tracks/groups/hierarchy/routing;
- mixer values;
- devices and exposed parameters;
- enough automation metadata to avoid overwriting existing automation;
- reconcile Live state against the saved `.als` snapshot.
Do not build broad write APIs yet. Do not expose arbitrary Python.
**Acceptance:** a machine-readable live snapshot explains the open pilot Set and identifies saved-vs-unsaved differences without GUI scraping as the primary source.
## R1.5 - Connection hardening and typed audio capture - PROVEN
Completed:
- package the Remote Script bridge in this repository;
- add an explicit capability handshake with separate read / bounded-write / capture lanes;
- declare no silent GUI fallback and no arbitrary-code capability;
- keep the MIT AgentAudioTap Max for Live implementation as an experimental/fallback capture path;
- add capture plan/manifest/stable-file hashing helpers and a reproducible bridge installer;
- build ChibiTap as a JUCE 9.0.2 VST3 with transparent pass-through and float32 WAV capture;
- replace the prototype custom FIFO/WAV writer with JUCE `AudioFormatWriter::ThreadedWriter`;
- prove ChibiTap directly with a headless processor test and through the actual compiled VST3 wrapper with a host-side smoke test;
- install ChibiTap in Live and expose a narrow guarded `chibitap_capture` method that can only toggle the final Main ChibiTap `Capture` parameter;
- prove real Live capture through typed `chibitap_capture` + `capture_transport` with no Export Audio/Video dialog and no CUA;
- verify the real artifact as 48 kHz stereo IEEE-float audio with non-zero mastered signal;
- upgrade ChibiTap to 0.2.0 with host-play transport gating and persistent host-visible `Tap ID`;
- add guarded typed `chibitap_setup` / `chibitap_configure` operations for exact track placement and identity/configuration;
- prove one-pass Main/BASS/DRUMS capture with Tap IDs 1/2/3: all three artifacts were 48 kHz stereo float32 and exactly 249,856 samples / 5.205333 s on the first active-source proof pass;
- add deterministic exact-range finalization: validate aligned raw taps, translate a constant-BPM requested beat range (including transport pre-roll offset) to sample indices, crop every tap to the same exact float32 sample interval, fingerprint raw/final artifacts, and write one experiment manifest;
- prove exact finality on the live KISSKISSKISS lab capture for beats **128-136 @ 135 BPM**: three aligned raw taps of 236,032 samples became three exact **170,667-sample** artifacts, with matching final sample counts and distinct SHA-256 fingerprints;
- expose the finalizer as `chibi-audio finalize-capture` with repeated `TAP_ID:LABEL:PATH` inputs.

Observed control proof: a first capture over a silent transport region produced a valid all-zero file; inspection showed the only soloed track had no clips in that range. Repeating the same typed capture over an active range produced real audio. This is desirable evidence that ChibiTap records the actual host signal rather than fabricating activity.

Range-finality contract:
- host-play transport gating excludes stopped-state lead/tail and keeps multiple taps sample-count aligned;
- the coordinator may stop after the requested end beat, but that overrun is raw evidence only, never the authoritative comparison range;
- final artifacts are cut to the requested sample interval, with requested beats/tempo, actual transport timing, raw/final hashes, sample counts and optional analysis preserved in the manifest;
- the current pilot uses a `constant_bpm` timing model. Tempo-automated ranges need a tempo-map/sample-boundary model before they may claim the same exact beat semantics.

Coordinator milestone complete:
- `chibi-audio capture-session` now resolves Tap IDs to exact Live track/device identities, arms all requested taps behind the Set-signature fence, runs one typed transport pass, verifies stable aligned raw artifacts, and calls the exact-range finalizer automatically;
- the resulting manifest carries the Tap ID -> Live track/device mapping, Set signature, song identity/path, requested and actual transport timing, raw/final hashes, exact sample counts and optional analysis;
- a live CLI proof over beats 64-68 @ 135 BPM produced three aligned raw files of 232,960 samples and three exact final artifacts of 85,333 samples.

Next:
- use Main/BASS/DRUMS/source taps as the normal evidence plane for A/B, loudness-stress and sidechain experiments;
- add bounded source/pre-FX/post-FX signal-point placement where Live exposes the required topology cleanly;
- carry accepted/rejected change provenance into higher-level experiment manifests so optimization waves can compare variants without ad-hoc exports.

**Acceptance: PROVEN on KISSKISSKISS.** A normal A/B capture requires no CUA or Export Audio/Video dialog, produces fingerprinted float32 artifacts linked to one experiment manifest, and multiple taps produce the same exact requested musical sample range with deterministic alignment.
## R2 - First reversible organization edit
On the lab Set only:
- checkpoint current state;
- choose a few unambiguous naming/color-hygiene improvements;
- apply exact rename/recolor operations through the typed bridge;
- re-read and verify every changed value;
- prove rollback;
- save a lab variant, never overwrite the original project.
**Acceptance:** one coherent organization batch is applied and reversed/reapplied reliably with an exact audit trail.
## R3 - First meaningful sonic A/B - FIRST SOURCE-LEVEL PROOF COMPLETE / GENERAL LOOP PENDING
Pilot proof: the D61 source-level -1.0 dB experiment was verified against a same-session zero-change control. It reduced house/bridge density and increased crest without materially changing later sections. The general A/B loop remains pending the typed capture path.
Pick exactly one evidence-backed mix problem. Candidate classes include:
- a harsh/resonant individual drum layer;
- a kick/bass collision that consumes headroom;
- a vocal/FX masking event;
- master stereo narrowing caused by peak control;
- one source repeatedly causing limiter excursions.
For the selected problem:
1. capture baseline state;
2. define one bounded hypothesis;
3. make one small change set;
4. render A and B;
5. loudness-match the comparison;
6. measure section-level deltas;
7. let the artist choose keep/refine/reject.
**Acceptance:** the user can hear a meaningful A/B, the change is exactly reproducible/reversible, and measurements explain what changed without pretending to decide taste.
## R4 - Reference-track comparison - INITIAL PILOT PROOF COMPLETE / FEATURE GENERALIZATION PENDING
Pilot references already analyzed: Petite Biscuit - All Over, Skrillex - Rumble, and Push. Existing separated All Over stems were also used as an analytical fixture.
Use one or two user-provided references as local evidence.
Compare by equivalent musical section where possible:
- loudness/crest factor;
- spectral-band balance;
- stereo width/correlation;
- transient density;
- macro-dynamic contrast.
Do not blindly EQ-match or force the pilot to the reference's integrated LUFS.
**Acceptance:** reference analysis produces a small number of testable production hypotheses for the pilot.
## R5 - Loudness stress map MVP
Answer: **what exact sources prevent this mix from getting louder cleanly?**
Build a ranked contribution report around the loudest master events:
- source/track coincidence with limiter-driving peaks;
- frequency-band contribution;
- transient/envelope length;
- phase/summation/overlap clues;
- predicted small upstream interventions.
Test distributed peak control (source/track/bus) against final-limiter-only loudness.
**Acceptance:** at least one A/B demonstrates either more clean loudness at comparable character or the same loudness with lower distortion/less pumping.
## R5.25 - Sidechain intelligence, routing and verification - TARGET
Tracked by [#5](https://github.com/akimbo-bin/chibi-audio/issues/5).

Treat sidechaining as a **core mix primitive**, not merely a plugin insertion task. Chibi must understand and verify explicit source -> target relationships such as kick -> bass, snare -> music bus, or vocal -> competing instruments.

Represent each relationship with:
- trigger source and routing point;
- target track/group/bus;
- processing method (full-band duck, volume shape, spectral carve/dynamic EQ, multiband, creative pump);
- relevant frequency range;
- depth;
- lookahead/attack;
- hold/release or explicit gain-reduction curve;
- intended purpose such as low-end headroom, transient clearance, intelligibility or creative pumping.

### Sidechain audit
Given a Live Set, identify:
- every current external-sidechain consumer and its source;
- missing or stale routes;
- devices that are configured but not actually triggering;
- duplicated/contradictory ducking stages;
- inappropriate source/target routing;
- stacked gain reduction that over-ducks the same event.

### Verified ducking
Do not trust device state or a gain-reduction meter alone. Use aligned trigger + target pre-processing + target post-processing captures to measure, per event:
- trigger time and missed/false triggers;
- gain-reduction onset relative to trigger;
- pre-duck/lookahead time;
- maximum and integrated depth;
- hold/recovery time and recovery curve;
- frequency-dependent reduction for selective ducking;
- residual time-frequency overlap after processing;
- recovered bus/master headroom;
- target transient preservation outside the collision window;
- click/discontinuity or modulation artifacts;
- cumulative reduction when multiple stages stack.

### Estimate the smallest sufficient intervention
There is no universal sidechain depth. Optimize according to the purpose:
- **kick -> bass:** clear the kick/sub collision and limiter stress while preserving bass continuity;
- **snare -> music:** create brief transient/body space, often with shorter and more frequency-selective ducking;
- **vocal -> music:** prefer spectral/dynamic space when full-band pumping would be distracting.

Use bounded parameter sweeps and A/B evidence to find the minimum depth/timing that produces useful separation. Prefer source-shape-independent triggers (MIDI or derived transient events) when stable timing matters more than following the source sample's whole envelope.

### Intent-level commands
Support operations such as:
- `sidechain kick to all relevant music buses`;
- `add snare clearance`;
- `make room for the vocal globally`.

For these commands, inspect the project graph, choose appropriate targets, exclude the trigger's own/unsafe routes, choose the processing class per target, set per-target starting values rather than cloning one amount everywhere, verify the actual rendered ducking, and return an auditable relationship map.

### Adaptive relationships
Allow section-aware, note-aware and velocity-aware sidechain behavior where justified. Examples include deeper kick/bass ducking only when fundamentals collide, lighter ducking when they do not, or different envelopes in sparse verses versus dense drops.

Integrate the sidechain evidence with R5 and R5.75 so sidechain changes can be tested as upstream remedies for loudness bottlenecks rather than defaulting to additional master limiting.

**Acceptance:** on KISSKISSKISS, Chibi audits the existing kick/bass sidechain path, measures its real reduction and timing, applies one bounded verified sidechain experiment, demonstrates the resulting overlap/headroom change with a level-matched A/B, proves rollback, and executes at least one intent-level command across more than one appropriate target without manual per-plugin routing.
## R5.5 - Perceptual translation and audibility MVP
Answer questions that ordinary spectrum/loudness meters cannot answer reliably, such as:
- **Which exact sources make this mix feel harsh, crispy or fatiguing?**
- **Will the bass remain perceptually present when sub-bass reproduction disappears?**
- **Does the vocal/hat/bass relationship survive phone-like, mono and low-volume playback?**
- **Is an unpleasant quality coming from the source itself or being created downstream by track, bus or master processing?**

Build a synthetic-hearing evidence stack from inspectable sensors rather than treating any one metric or model as musical truth.

### Psychoacoustic evidence
Add perceptually motivated measurements where they prove useful:
- critical-band / Bark / ERB-domain energy and specific loudness;
- sharpness, roughness, tonality and related perceptual descriptors;
- masking/audibility estimates between competing sources;
- distinguish brightness, sharpness, sibilance, transient hardness, resonant whistles and distortion/fizz instead of collapsing them into one `too much high end` diagnosis.

### Harmonic survivability and bass presence
For tonal low-frequency sources, estimate:
- fundamental and harmonic trajectories;
- which harmonics remain perceptible when low bass is removed or masked;
- whether missing translation is caused by insufficient harmonic audibility versus competing midrange material;
- whether a proposed saturation/EQ/envelope intervention improves audibility without merely raising sub energy.

### Playback translation lab
Evaluate bounded sections through explicit playback profiles such as:
- full-range reference monitoring;
- phone-like bandwidth;
- laptop/small-speaker bandwidth;
- mono;
- low and very-low listening level;
- optional user-calibrated devices such as a specific car or speaker.

Profiles are diagnostic approximations, not claims of exact hardware emulation. Compare perceptual/source relationships after translation, not only the filtered master waveform.

### Causal and event-level forensics
Use aligned typed captures to compare useful signal points when available:
- source / track pre-FX;
- track post-FX;
- group pre/post processing;
- premaster;
- mastered output.

Analyze musical events, not only long averages. Rank individual hats, sibilants, kicks, bass notes or other events by perceptual salience, overlap and contribution to downstream stress. Small controlled bypass/parameter perturbations may be used to attribute a problem to an exact processor when authorized.

### Semantic evidence and calibration
Audio embeddings or audio-language models may be used as weak semantic sensors for concepts such as `bright`, `metallic`, `punchy`, `muffled` or `harsh`, but never as the sole mastering judge.
Record predictions against later real listening checks (phone, car, headphones, etc.) so each sensor can be calibrated. Retire or down-weight sensors that do not predict useful outcomes.

**Acceptance:** on KISSKISSKISS, Chibi can (1) identify which source(s) dominate a known harsh/crispy passage and whether the problem is source or downstream processing, (2) explain which bass harmonics remain audible under a phone-like profile and what masks them, and (3) make at least one playback-translation prediction that is checked against a real listening test. The output must remain an evidence-backed hypothesis for the artist, not an autonomous declaration that a mix `sounds good`.
## R5.75 - Iterative loud mix/master optimizer - TARGET
Tracked by [#4](https://github.com/akimbo-bin/chibi-audio/issues/4).

Support a goal-level request such as:

> "I want to mix and master this track to be loud."

Chibi should be able to pursue that goal through **bounded waves of reversible Live Set changes, authoritative renders, analysis and adaptation** rather than one-shot plugin advice or a scalar LUFS target.

### Goal contract
Before the loop begins, establish a target bundle and constraints from the user, references and current Set. The bundle may include:
- desired competitive loudness range by musical section;
- true-peak/delivery constraints;
- transient/crest preservation;
- low-frequency punch and envelope integrity;
- allowed versus unacceptable clipping/saturation character;
- spectral/harshness/roughness guardrails;
- stereo/mono constraints;
- reference-relative targets;
- playback-translation requirements.

Do **not** collapse the objective into one master quality score. Prefer explicit guardrails plus a best-so-far/Pareto comparison: louder is useful only while the other important dimensions remain acceptable.

### Loudness efficiency / distortion-tax analysis
Add a controlled master-drive sweep over a representative section and measure the **clean-loudness knee**: where another dB of drive stops buying useful loudness and increasingly buys crest collapse, bass flattening, pumping, roughness, clipping or cross-band distortion.

Useful evidence includes:
- marginal LU gained per dB of additional drive;
- full-band and band-limited crest-factor loss;
- transient retention;
- low-frequency waveform/envelope deformation;
- near-clipped/clipped event statistics;
- inferred time-varying master gain from aligned premaster -> master captures;
- sharpness/roughness changes;
- stereo change;
- event-synchronous upper-band fizz/roughness during kick/bass peaks.

Compare the curve and knee with user references by equivalent musical section when possible. A reference is evidence about what is achievable, not a spectral/LUFS target to clone blindly.

### Iteration wave
Each optimization wave should:
1. observe the current best Set/render and fresh evidence;
2. rank a small number of causal hypotheses from R5/R5.25/R5.5;
3. choose one coherent bounded intervention with expected benefit and risk;
4. checkpoint the exact current state;
5. apply the mutation through the typed Live path and read it back;
6. render authoritatively through Live;
7. analyze both **level-matched** and **as-produced** comparisons;
8. keep the candidate only if it improves the goal without violating guardrails; otherwise roll back exactly;
9. update the evidence and choose the next wave rather than blindly repeating the same strategy.

Candidate interventions may include source trims, envelope changes, sidechain depth/timing/routing changes, dynamic low-band space, local transient clipping, track/bus compression, clipper/limiter changes, targeted harshness control or other already-proven bounded operations. Prefer upstream/distributed peak control when it achieves the same loudness with lower full-mix damage.

### Stop conditions
The loop must stop truthfully when any of these becomes true:
- the target bundle is satisfied within tolerance;
- no tested candidate improves the best-so-far result without unacceptable degradation;
- distortion/translation/crest/stereo guardrails regress beyond bounds;
- causal attribution becomes too ambiguous to justify another automatic change;
- the authorized render/mutation budget is exhausted;
- the next useful step is materially subjective or higher-risk and needs artist approval.

"Until happy" therefore means **until the measurable goal contract is satisfied or further automatic optimization is no longer justified**. Final artistic acceptance still belongs to the artist.

### Result package
Return:
- baseline render;
- best-so-far render;
- level-matched A/B;
- as-produced A/B;
- exact accepted changes;
- rejected experiments and why they lost;
- loudness-efficiency curve / clean-loudness knee;
- remaining tradeoffs and confidence;
- full reversible experiment provenance.

**Acceptance:** on KISSKISSKISS, a user can request a loud mix/master goal and Chibi completes at least two autonomous experiment waves on the lab Set with authoritative renders between waves. It identifies a clean-loudness knee and at least one upstream loudness bottleneck, preserves a best-so-far state, and either (a) produces a measurably louder render at comparable or better distortion/translation quality, or (b) stops with concrete evidence that further loudness costs unacceptable quality.
## R6 - Plugin intelligence only as demanded by the pilot
Normalize duplicate plugin formats into logical products and improve intent categories. Add manuals/parameter semantics only for plugins we actually need to operate.
**Acceptance:** requests such as "what transparent clippers do I own?" or "which installed tool can dynamically create space here?" return grounded candidates from the machine inventory.
## R7 - Sample intelligence
Index samples read-only, then add similarity/semantic search only after the production loop is proven useful.
No automatic file moves or deduplication until project-reference safety is solved.
## R8 - Generalized mix assistant
Expand the proven experiment loop to:
- EQ and dynamic-EQ hypotheses;
- compression/clipper experiments;
- generalized sidechain relationships building on the verified R5.25 source-target graph;
- per-section automation;
- optional offline plugin-chain experiments;
- aligned audio-rate evidence through ChibiTap VST3 instances, with Max for Live retained only for specialized/fallback adapters;
- perceptual/audibility/translation evidence proven in R5.5;
- general goal-driven iterative optimization loops derived from the bounded R5.75 loudness workflow.
## R9 - Chibi / Ultron integration
Expose proven capabilities to Chibi Core as a specialist production executor. Preserve Core as the only workflow authority and preserve artist approval for subjective material changes by default.
## Scope guard
Before adding a new subsystem, ask:
**Does the next KISSKISSKISS acceptance boundary require it?**
If not, defer it.
