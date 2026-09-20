# KISSKISSKISS pilot
This song is the proving ground for Chibi Audio. The goal is not to perfect the entire system before touching music; the goal is to prove a safe, repeatable loop that can improve a real human-made track.
## Safety boundary
- The artist's original project is read-only for Chibi Audio experiments.
- All edits occur on a separate lab lineage.
- A disk copy of the last-saved project state already exists as `KISSKISSKISS Chibi Lab`.
- The currently open Live Set has unsaved changes, so the lab lineage must capture/reconcile that state before sonic edits begin.
- No destructive flatten/delete/consolidate operation in the pilot.
- No sample-library moves.
- No direct `.als` XML writes.
## Known project facts
- Ableton Live 12, 48 kHz.
- 135 BPM, D#/Eb minor as currently configured in Live.
- Roughly 97 saved-set tracks in the offline parser.
- Major top-level groups include VOX, FX, BASS and DRUMS, plus a SIDECHAIN track.
- The master currently includes FabFilter Pro-L 2.
- The Set contains many individual drum layers and nested drum subgroups, making it a useful test for per-track analysis rather than bus-only advice.
## Arrangement map
Working map from prior analysis:
- bars 1-8: distorted buildup;
- bars 9-16: quieter/spacey buildup;
- bars 17-32: house-style first drop;
- bars 33-40: bridge/ramp;
- bars 41-48: second build/tension;
- bars 49-64: trap-style second drop;
- bar 65 onward: release/tail.
The live Set contains additional locators/markers; the structured bridge should read and reconcile those instead of hard-coding this map forever.
## Baseline audio target
The existing loud master is already approximately in a useful commercial-loudness region for the drops, so the pilot should not begin by adding more master gain.
The first useful question is upstream:
**Can we make the mix clearer or reduce peak stress at the individual-track level, then retain that improvement at equal perceived loudness?**
## Phase A - capture baseline
Before any sonic write:
- capture current live state;
- reconcile unsaved vs saved state;
- establish the lab Set as the active editable lineage;
- render a current full-length baseline/premaster as needed;
- measure section-level loudness, true peak, crest, spectrum and stereo behavior;
- ingest one user-selected reference track if available.
## Phase B - organize and persist project context
Run the `organize` plane before substantive mix work. Use `PROJECT_ORGANIZATION.md` to classify the Set and persist the hierarchy/routing/role/arrangement/automation/sidechain context later workers will share. Produce a complete organization proposal (names, colors, order, heights, fold state and useful groups), with confidence and unresolved items.

Apply cosmetic organization as a reversible batch only where the classification is confident. Treat group creation/reparenting and other routing-sensitive moves as structural: prove routing equivalence before execution or leave them as proposals. The resulting project-context graph becomes input to the KISS mix orchestrator and specialist workers.

## Phase B.1 - original organization proof notes
Find only unambiguous hygiene changes first. Examples:
- generic group names whose purpose can be established from their children;
- duplicate source names that can be given an audible/functional role without losing the original source name;
- consistent color families for major groups.
Do not rename something based on a guess. If the role is unclear, leave it alone until listening or project evidence resolves it.
## Phase C - first sonic experiment
Choose one problem after track-level inspection. Preferred first experiment should be narrow enough that we can explain causality.
Candidate selection criteria:
- source is identifiable;
- issue occurs in a known section;
- proposed change is small and reversible;
- output can be rendered A/B quickly;
- success can be partly measured and finally judged by the user.
## Phase D - reference-aware refinement
When the user supplies a reference, compare equivalent high-energy sections at matched loudness. Extract useful differences, then propose at most a few hypotheses. Do not chase a reference curve mechanically.
## Experiment record template
Every sonic experiment should capture:
- `experiment_id`
- baseline snapshot/ref
- song section/bars
- exact track/device targets
- hypothesis
- change A / change B
- parameter values before/after
- render file refs
- LUFS/peak/crest/spectral/stereo deltas
- subjective user verdict
- final state: kept / refined / rolled back
## Definition of pilot success
Chibi Audio has proven itself when all of these are true:
1. it can understand the current Set more deeply than exported buses alone;
2. it can make an exact edit on a copy without endangering the original;
3. it can verify and roll back that edit;
4. it can create a meaningful level-matched A/B of a sonic change;
5. the artist prefers at least one change and understands why it helped;
6. the workflow is fast enough to be useful during real production.

## Empirical pilot findings - 2026-09-14

A fresh 49-bar render was captured from the current Chibi Lab Set, covering the first drop through the second drop and tail. This replaces the older pre-change stems for current mix decisions.

### Current mastered drops

- House drop: approximately **-9.10 LUFS**, **-1.0 dBTP**, **7.72 dB crest**, Side/Mid approximately **-17.47 dB**.
- Trap drop: approximately **-9.31 LUFS**, **-1.0 dBTP**, **8.95 dB crest**, Side/Mid approximately **-18.73 dB**.
- The trap retains more transient crest than the house; both are narrower than the current reference set.

### Whole-master reference context

Local user-owned copies currently measure approximately:

- Petit Biscuit - `All Over`: **-8.11 LUFS-I**.
- Skrillex - `Rumble`: **-8.34 LUFS-I**.
- local `Push` release: **-6.85 LUFS-I**.

Decoded true-peak values from the lossy reference files are not mastering-ceiling evidence; use their spectral, dynamic and relative section characteristics instead.

### First reference-stem proof

Existing local `htdemucs_ft` separated stems for `All Over` were found and analyzed over its loud 42-54 s section. They are diagnostic estimates, not ground truth.

- Separated `All Over` bass: about **-9.30 LUFS**, extremely mono-focused, with roughly **72%** of analyzed band energy at 20-50 Hz.
- Separated `All Over` drums: about **-10.06 LUFS**, around **12.8 dB crest**.
- Within that reference separation, bass is about **0.8 LU louder than drums** while the drums are much peakier.

Fresh KISSKISSKISS group renders were then exported from Live with Return/Main effects excluded:

- House: DRUMS are about **3.9 LU louder than BASS**.
- Trap: DRUMS are about **1.6 LU louder than BASS**.
- House BASS is even more sub-concentrated than the separated `All Over` bass: roughly **78%** of analyzed energy at 20-50 Hz versus about **72%** in the reference stem.

### Current hypothesis

The first-drop loudness ceiling does **not** look like a simple lack-of-bass problem. The house drop already has reference-like or greater deep-sub concentration, while its drum-to-bass relationship is substantially more drum-forward than `All Over` and its mastered crest is lower. The next useful work is source attribution: find which exact drum/bass layers create the largest peak demand, then test distributed peak/envelope control at equal perceived loudness instead of adding more sub or more final limiting.

The reference also suggests that apparent width should be investigated in VOX/FX/`other` material rather than widening low-end sources blindly. `All Over` obtains substantial width outside its separated bass/drums.

These findings are hypotheses to A/B, not automatic mix instructions.

## Mix-engineering workflow pivot - 2026-09-17

The pilot is moving away from one-parameter/full-section brute-force experiments. A real mix engineer would first listen/measure the whole relationship, rank the largest musical bottlenecks, inspect the responsible bus, and only then descend into individual channels. Chibi should do the same.

Current KISS evidence already narrows the first house-drop investigation: DRUMS lead the full-band master-stress evidence, BASS leads the sub-250 Hz stress evidence, the existing bass ducking is very deep, and a real Pro-L 2 experiment (+12.40 -> +12.90 dB Gain) moved Locator 3 only from **-8.53 to -8.45 LUFS** while true peak stayed at **-1.00 dBTP**. That is only **0.16 LU gained per dB of added limiter drive**, below the current clean-loudness efficiency threshold, so harder final limiting is not the next strategy.

The new KISS loop is hierarchical: short master/premaster/major-bus census -> suspect-bus child census -> surgical pre/post evidence -> one serialized reversible candidate -> short re-capture -> full-drop acceptance only for winners. Chibi Core should own this workflow now, with parallel bus/source/sidechain/reference workers sharing structured evidence while one executor owns Ableton effects.

## Typed ChibiTap capture proof - 2026-09-15

The primary audio-plane path is now proven end-to-end in the real Chibi Lab Set. ChibiTap is the final device on Main and its host-visible `Capture` parameter is controlled only through the guarded `chibitap_capture` bridge capability plus bounded `capture_transport`. No Export Audio/Video dialog or CUA was used for the capture sequence.

### Control capture

The first typed capture targeted a musical range where the currently soloed `52-Serum 2` track had no arrangement clips. The resulting WAV was a valid 48 kHz stereo IEEE-float file containing silence. Re-reading the Set proved that silence was the actual Main output for that range, so the control demonstrated that ChibiTap records the host signal rather than fabricating activity.

### Active-signal capture

The same typed sequence was repeated over an active range of the soloed Serum track. The resulting capture was a real non-zero stereo float32 WAV. Measured evidence from that artifact included approximately:

- **-1.02 dBTP** true peak;
- **-12.51 LUFS** integrated over the captured window;
- **13.7 dB crest**;
- stereo correlation approximately **0.935**;
- Side/Mid approximately **-14.7 dB**.

This is not a new mix verdict because the Set was intentionally left in its existing solo state. It is infrastructure proof that real Ableton audio can be captured and analyzed without the Export dialog.

### ChibiTap 0.2.0 multi-tap proof

The next proof moved to the active `KISSKISSKISS Mix - Chibi.als` lab lineage. Typed `chibitap_setup` / `chibitap_configure` placed final transparent taps at Main, BASS and DRUMS and assigned durable Tap IDs **1 / 2 / 3**. ChibiTap 0.2.0 may be armed while stopped but writes only while the host playhead reports playback.

An initial three-tap pass over beats 68-84 produced equal-length files but BASS/DRUMS silence. Structured Arrangement inspection showed the important house bass/drum layers do not begin until about beat 96, so this was a window-selection control rather than a capture failure.

Repeating the same typed three-tap operation over an active house-drop window beginning at beat 100 produced three real 48 kHz stereo IEEE-float WAVs. All three were exactly **249,856 samples / 5.205333 s**, proving block/sample-count alignment across independent plugin instances during one Live playback pass. Measured evidence from that pass included approximately:

- Main / Tap 1: **-8.34 LUFS**, **-1.0 dBTP**;
- BASS / Tap 2: **-14.97 LUFS**, **+0.88 dBTP** pre-master;
- DRUMS / Tap 3: **-10.76 LUFS**, **+3.24 dBTP** pre-master.

The requested window was beats 100-108, but the external coordinator did not issue transport stop until about beat **111.63**. The three files stayed perfectly equal in sample count, so multi-tap alignment is proven; exact requested **end-boundary finality** is not.

### Remaining boundary

Host-play gating now excludes stopped-state buffers and Tap IDs provide durable source identity. The remaining audio-plane milestone is exact requested-range finality: terminate or crop capture on the requested host beat/sample boundary rather than after an externally polled transport stop, then package the aligned artifacts, timing evidence, fingerprints and analysis into one experiment manifest.

### Exact requested-range finality proof

The raw multi-tap capture no longer needs to stop on the exact requested beat to become authoritative evidence. `capture_finalize.py` validates that raw Tap ID artifacts are sample-aligned, converts the requested constant-BPM beat interval (and any transport-start pre-roll) to exact sample indices, writes IEEE-float crops, verifies the final sample counts, fingerprints both raw and final artifacts, and writes one JSON experiment manifest. The same path is exposed as `chibi-audio finalize-capture`.

A fresh live proof used the active `KISSKISSKISS Mix - Chibi.als` Main/BASS/DRUMS topology (Tap IDs 1/2/3). The raw playback began at beat 128 and stopped at about beat 139.064 after an external coordinator overrun. All three raw files were exactly **236,032 samples**. The requested authoritative range was beats **128-136 at 135 BPM**, which resolves to **170,667 samples / 3.5555625 s** at 48 kHz.

The exact finalizer produced three 48 kHz stereo float32 artifacts, each exactly **170,667 samples**, with distinct SHA-256 fingerprints. Analysis of that exact common range measured approximately:

- Main / Tap 1: **-8.04 LUFS**, **-1.0 dBTP**;
- BASS / Tap 2: **-13.01 LUFS**, **+1.9 dBTP** in the floating-point pre-master bus capture;
- DRUMS / Tap 3: **-10.87 LUFS**, **+3.3 dBTP** in the floating-point pre-master bus capture.

The positive pre-master bus peaks are preserved float-domain evidence, not proof of integer clipping. The manifest records requested beats/tempo, actual transport timing, raw and final format/sample counts, hashes, alignment assertions and optional analysis.

A synthetic regression test also proves non-zero pre-roll handling: when raw capture begins half a beat before the requested range, the finalizer computes a **12,000-sample** offset at 120 BPM / 48 kHz and still returns the exact requested 12,000-sample final interval.

This closes the R1.5 range-finality boundary for constant-tempo sections. Tempo-automated material still needs a tempo-map-aware beat-to-sample model before claiming exact beat finality.

### One-command capture-session proof

The final coordinator now exposes the whole constant-tempo evidence loop as `chibi-audio capture-session`. It resolves each requested Tap ID to an exact Live track/device, verifies the Set signature and Capture-Off state, arms all taps while stopped, runs one bounded typed transport pass, disarms them, waits for stable WAVs, requires equal raw sample counts, then invokes the exact-range finalizer automatically. The same manifest is augmented with the Set signature, song identity/path, actual transport timing, Tap-ID-to-track/device mapping, stable raw artifact hashes and optional analysis.

A live CLI proof used Main/BASS/DRUMS Tap IDs **1 / 2 / 3** over beats **64-68 @ 135 BPM**. The transport-stop RPC overran the requested boundary to about beat **74.845**, but all three raw taps remained exactly aligned at **232,960 samples**. The coordinator then produced three exact **85,333-sample / 1.777770833 s** float32 artifacts for the requested four-beat interval, with distinct SHA-256 fingerprints and one shared experiment manifest. This closes the one-command constant-tempo capture-session boundary; transport overrun remains diagnostic evidence rather than part of the authoritative comparison range.

### In-Live bounded transport proof

The capture-session coordinator now uses typed `capture_transport play_until` so Live owns the requested transport end instead of an external sleep/poll stop command. The exact-range finalizer remains authoritative for the final sample interval.

A fresh four-tap proof used Main/BASS/DRUMS/`38-Serum 2` (Tap IDs **1 / 2 / 3 / 4**) over beats **96-104 @ 135 BPM**. All four raw captures were exactly **175,104 samples / 3.648 s**. Live stopped at about beat **104.179**, reducing the raw overrun to about **0.18 beat**.

The finalizer produced four 48 kHz stereo float32 artifacts at exactly **170,667 samples / 3.5555625 s**, with equal final sample counts, zero raw start offset and distinct SHA-256 fingerprints. Approximate exact-range measurements were Main **-8.13 LUFS / -1.0 dBTP**, BASS **-15.21 LUFS / -2.81 dBTP**, DRUMS **-10.44 LUFS / +3.24 dBTP**, and track 38 **-10.14 LUFS / -0.60 dBTP**.

After the proof, transport was stopped and all four Capture parameters were verified Off. This closes the practical constant-tempo one-command capture loop without Export Audio/Video or steady-state CUA.

### Poll-safe synchronized three-tap proof

A real `capture-session` run exposed an important scheduling interaction: polling `capture_transport status` every 50-200 ms can starve the same Live ControlSurface scheduler responsible for the bounded `play_until` stop. In one diagnostic pass, the requested beats 128-144 did not stop until about beat **155.48**. Repeating the same pass with no in-play bridge polling stopped at about **144.10**, isolating the problem to coordinator polling rather than ChibiTap host-play gating.

The session runner now watches ChibiTap WAV growth on disk while transport is active and performs only one final bridge-status reconciliation after capture growth becomes quiescent. This keeps steady-state monitoring off Live's main-thread scheduler.

A fresh Main/BASS/DRUMS proof used Tap IDs **1 / 2 / 3** over beats **128-144 @ 135 BPM** with no active solos or mutes. All three raw captures were exactly **343,040 samples / 7.146667 s**, and Live reported the scheduled stop at about beat **144.036**. The exact-range finalizer then produced three authoritative stereo float32 files at exactly **341,333 samples / 7.111104 s** each. The manifest records equal raw sample counts, equal final sample counts, zero raw start offset, exact requested sample finality, Tap-ID-to-track/device provenance and distinct SHA-256 fingerprints.

This closes the practical scheduler-starvation bug in the one-command multi-tap path: the coordinator no longer needs repeated main-thread status calls while Live owns the requested transport end.
