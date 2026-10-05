# Stem mixdown / REAPER experiment backend

Status: product-direction contract, October 2026. Tracked by [#43](https://github.com/akimbo-bin/chibi-audio/issues/43).

## Purpose

This backend exists to make downstream mixing and mastering experiments materially faster after the production has reached a sensible audio boundary.

It does **not** convert an Ableton Live Set into a REAPER project.

Ableton remains authoritative for arrangement, instruments, clip state, source tracks, routing, sidechains, automation, device-chain forensics and any edit that must remain in the Live project. REAPER receives only an explicitly exported audio package plus the downstream routing/processing Chibi deliberately constructs for the experiment.

The expected interaction remains chat-first:

> "The production is done enough. Export the useful stems, mix/master them, try a few approaches, and bring me the best comparisons."

Core can own that long-running job while the inner candidate loop runs locally and deterministically.

## Why this path

Live can export aligned individual tracks or selected tracks, with a common start/length suitable for another multitrack program. REAPER exposes a mature script/API surface for tracks, FX, routing and rendering, including stems, render bounds, render queues, render matrices and full-speed offline rendering.

That gives Chibi a useful separation:

- use Live + ChibiTap when Chibi needs to understand or change the real project;
- use REAPER when Chibi already has the audio it needs and wants to search downstream balance/bus/master alternatives quickly.

The speed claim must be measured on KISSKISSKISS. It is an experiment hypothesis, not an assumed fact.

## Stem package contract

A package is immutable evidence. It should contain:

- package schema/version and stable package ID;
- source project ref and Live Set signature;
- export timestamp and exact musical/time range;
- tempo where relevant;
- sample rate, bit depth, channel count and exact sample count;
- one common zero/start alignment for all files;
- per-file SHA-256;
- source Live track/group identity and semantic role where available;
- whether the file is pre/post fader;
- what source/group processing is already baked into the file;
- explicit send/return policy;
- explicit Main/master processing policy;
- optional sidechain/trigger-only files;
- a full Live reference render corresponding to the declared baseline;
- organization-context hash / evidence refs useful for interpreting the package.

Default KISS transport is 48 kHz. Prefer 32-bit float WAV for handoff so Chibi does not introduce unnecessary integer quantization or dither before final delivery. Do not normalize stem exports.

## Export resolution

Choose the smallest resolution that preserves the decision Chibi needs to make.

### Group stems

Use major groups such as VOX, BASS, DRUMS and FX for broad mixdown/master balance and bus-processing experiments.

Advantages:
- small REAPER project;
- faster candidate setup;
- existing upstream sound design remains committed.

Limitation:
- Chibi cannot later fix an interaction already baked inside one group.

### Individual tracks / parts

Use selected individual tracks when the experiment needs source balance or downstream per-source processing but no longer needs the original instrument/clip/automation state.

### Pre-interaction exports

If the question concerns a shared nonlinear bus, sidechain or return interaction, export before that interaction and include every signal needed to reconstruct it. If faithful reconstruction is impractical, keep that experiment in Live.

## Sends, returns and Main effects

Do not blindly enable "include return and Main effects" for a remixable package. Printing shared processing into every stem can make summation or further processing misleading.

Use one of these explicit policies:

- `clean_downstream`: export source/group outputs without duplicating shared return/Main processing; export required return contributions separately.
- `printed_final_stems`: intentionally print downstream processing because Chibi will not attempt to reconstruct or modify it.
- `pre_shared_bus`: export signals immediately before the shared processing Chibi intends to rebuild in REAPER.
- `reference_only`: full Main render from Live, used for baseline/acceptance comparison and not as an editable stem.

The package manifest records which policy was used.

## Deterministic REAPER project

Build the project from the package rather than by UI improvisation.

The first implementation should prefer ReaScript/Lua or another small reviewed control surface that can:

- create/load a project template;
- import each stem at the exact common start;
- disable accidental time stretching/tempo reinterpretation;
- set track names and stable IDs in Chibi metadata;
- configure track/bus routing;
- insert reviewed FX by exact identity;
- read/write exact FX parameters;
- render explicit ranges;
- choose render mode;
- generate candidate and baseline manifests;
- close/reopen or rebuild from package deterministically.

Do not expose arbitrary unrestricted script execution to the model merely because REAPER's API is broad. Chibi should expose typed experiment capabilities over the script layer.

## Baseline-fidelity gate

Every stem package must pass a null/unchanged baseline before optimization.

1. Build the REAPER project from the immutable package.
2. Apply no intended sonic changes.
3. Render the declared baseline.
4. Align it with the corresponding Live stem baseline/reference.
5. Compare exact sample/range identity plus relevant level, spectrum, dynamics, stereo and difference evidence.
6. Refuse candidate authority if the mismatch exceeds the experiment's declared tolerance.

This gate catches:
- wrong alignment;
- missing/duplicated returns;
- gain-law mistakes;
- missing sidechain/control signals;
- plugin-state reconstruction errors;
- plugins that behave materially differently offline;
- an export boundary that already destroyed the interaction being tested.

A failed gate does not mean REAPER is unusable globally. It means this package/experiment must be repaired or returned to Live.

## Candidate search

The model should not manually turn one knob, wait for a render, inspect it, and repeat through chat.

A bounded candidate job receives:
- immutable stem-package ref;
- exact baseline project state;
- one hypothesis;
- allowed targets/parameters;
- parameter bounds or a small discrete candidate set;
- render range(s);
- evidence capabilities;
- acceptance guardrails;
- candidate budget.

The local runner can render multiple candidates, analyze them, reject obvious losers, and return a small finalist set to the reasoning model / artist.

Use short diagnostic ranges for screening and independent passages for validation. Full-song renders are finalist/acceptance evidence, not the default inner-loop cost.

## What can run well here

Good first candidates:
- stem/group balance;
- post-stem EQ/dynamic EQ;
- bus compression/clipper/limiter alternatives;
- downstream sidechain when the trigger and pre-duck target are included explicitly;
- master-chain experiments;
- reference/translation comparisons;
- bounded parameter sweeps chosen by a model-generated hypothesis.

Poor candidates:
- arrangement changes;
- instrument/sample editing;
- pre-export automation decisions;
- fixing an individual source hidden inside a printed stem;
- changing a Live group compressor that is already baked into the stem;
- any routing/feedback interaction that the package does not reconstruct.

## Accepted result semantics

A winning REAPER candidate can mean one of two things:

1. **Final external mix/master** - the artist chooses the stem-based REAPER result as the deliverable.
2. **Proposal for Live** - the result demonstrates a useful direction, but Chibi must separately reproduce/verify the relevant change in Live before claiming the Ableton project improved.

The workflow must record which interpretation applies.

## Performance telemetry

Every representative job records:
- Live export/preparation time;
- REAPER project-build time;
- candidate render time;
- analysis time;
- model/controller time;
- final full-range render time;
- candidate count and finalist count;
- total wall-clock time.

Compare this with the same bounded experiment in the normal Live path. The backend earns permanent complexity only if it materially improves useful candidate throughput or reliability.

## First KISS proof

1. Reconcile bridge/project state and freeze an authorized lab baseline.
2. Choose one downstream problem that does not require changing arrangement/instruments.
3. Export a compact major-group stem package plus a Live reference.
4. Reconstruct the unchanged baseline in REAPER and pass the fidelity gate.
5. Run a small candidate family using a scriptable downstream control (for example stem balance or master/bus processing).
6. Produce as-produced and level-matched finalist A/Bs.
7. Ask for artist preference, including "baseline wins."
8. Measure the complete Live vs REAPER experiment timing.
9. Decide whether the backend materially helps before expanding it.

## External references

- Ableton Live 12 manual: Export Audio/Video / All Individual Tracks / Selected Tracks Only.
- Ableton support: Importing and exporting stems.
- REAPER ReaScript API and project/render settings.
- REAPER render queues, stem rendering and Region Render Matrix.

These references justify the feasibility of the workflow. They do not replace the KISS fidelity/performance proof.
