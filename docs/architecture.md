# Architecture

## Authority model

Chibi Core is the long-term workflow authority. Chibi Audio supplies typed production capabilities; it must not create a parallel scheduler, task database, or autonomous authority.

## 1. Offline Set Inspector

Read Ableton `.als` files as read-only project snapshots. Live Sets are gzip-compressed XML, which gives us useful durable structure without requiring GUI automation or a running MCP bridge.

Initial data to extract:

- track/group identity, name, color, and hierarchy;
- routing and sidechain relationships where represented;
- native devices and third-party plugin references;
- device-chain order and enabled state;
- sample/file references;
- locators, tempo, and arrangement metadata where available.

Normal operation must never write `.als` XML directly. Editing should happen through supported Live control surfaces so Live itself owns serialization and project validity.

## 2. Live Bridge

Use a small Python MIDI Remote Script inside Live 12 to expose the Live Object Model to a localhost-only bridge. Live-facing code stays deliberately small; networking, orchestration, persistence, audio analysis, and AI logic stay outside the DAW process.

We should evaluate and adapt the existing MIT-licensed `jterratsdev/ableton-live-mcp` implementation rather than rebuilding commodity MCP/Remote-Script plumbing from scratch. Chibi-specific safety, project intelligence, plugin/sample knowledge, analysis, and A/B workflows live above that seam.

Max for Live can later provide capabilities that genuinely require Live's audio/control environment, but it should not become the main networking or workflow authority.

## 3. Local MCP / Chibi Adapter

Expose typed, capability-advertised operations such as:

- get project/arrangement/routing/device state;
- list/search installed devices and Ableton Browser items;
- read device parameters and automation state;
- rename and recolor exact tracks/groups;
- set bounded mixer/device parameters;
- add/reorder devices where the Live API safely supports it;
- create or modify automation;
- create snapshots and restore changed values.

The adapter must fail closed when the Live bridge is unavailable or an operation is unsupported. It must not silently fall back to mouse/keyboard automation.

## 4. Plugin Knowledge Base

Build a machine-local catalog from the user's actual plugin installation and Live-visible devices. Useful fields include:

- vendor, product name, format, version, and path/fingerprint;
- categories such as EQ, compressor, clipper, distortion, saturation, reverb, delay, modulation, imaging, metering, restoration, synth, sampler, and utility;
- parameter metadata exposed by Live;
- grounded manuals/documentation when available;
- user-specific favorites, conventions, and proven use cases.

This should let the assistant answer "what do I own for X?" from reality rather than generic plugin lists.

## 5. Sample Library Index

Start read-only. Index paths and metadata without reorganizing files. Later derive features such as duration, sample rate, channels, BPM estimate, musical key estimate, onset/transient character, spectral profile, and embeddings for semantic similarity/search.

Any future move/rename/deduplication operation must be opt-in, exact-targeted, and reversible where practical because Ableton projects may reference those paths.

## 6. Audio Analysis / Evidence

Analyze the full mix, buses, stems, or local renders by musical section rather than treating an entire song as one average. Useful evidence includes loudness, peak/true peak, crest factor, spectral balance, transient density, stereo width/correlation, masking, and low-end interaction.

Metrics are evidence, not musical truth.

## 7. A/B Experiment Engine

Material subjective changes should be expressed as experiments:

- checkpoint state;
- exact proposed change set;
- variant A/B identifiers;
- matched-level comparison when appropriate;
- metrics before/after;
- resulting render or playback route;
- keep, refine, reject, or rollback decision.

This is critical for mixing/mastering because the model should propose useful ranges and testable hypotheses rather than pretend one numerical setting is objectively correct.

## Safety model

Read-only inspection is the default. Before a mutation batch, refresh project state and resolve exact track/device identities. Broad changes require a snapshot. Never delete source material, flatten tracks, overwrite the only copy of a Set, or save over an unknown state automatically. Prefer structured Live/MCP operations over UI automation; UI automation is a last-resort surface for genuinely UI-only actions.
