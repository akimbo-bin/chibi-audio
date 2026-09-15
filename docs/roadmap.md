# Roadmap

## P0 — Reality-first inspection (now)

- Parse real `.als` projects read-only.
- Inventory tracks, groups, colors, hierarchy, routing, devices, and plugin references.
- Scan installed VST/VST3/CLAP inventory and classify obvious plugin roles.
- Locate and index project/sample-library roots without moving anything.
- Produce a production report for the real `KISSKISSKISS` project.

**Acceptance:** a CLI can explain the real Set structure from disk with zero Ableton mutation.

## P1 — Live read bridge

- Install/adapt a Live 12 Python Remote Script.
- Localhost-only connectivity and health/capability handshake.
- Read project, arrangement, devices, parameters, routing, locators, automation, and available meters.
- Reconcile live state with the `.als` snapshot.

**Acceptance:** ChatGPT/Chibi can inspect the currently open Set without requiring exported stems just to understand track structure.

## P2 — Safe organization writes

- Snapshot before write batches.
- Rename tracks/groups.
- Apply a deterministic color convention.
- Mute/solo/arm only on explicit request.
- Set bounded gain/pan/device parameters.
- Roll back exact changed values.

**Acceptance:** reorganize a copied/test Set and prove exact changes plus rollback.

## P3 — Plugin and sample intelligence

- Search the local plugin catalog by intent: distortion, transparent clipping, phase/filtering, vocal cleanup, mastering limiter, reverb, etc.
- Search Ableton Browser and load an explicitly selected device/preset when safely supported.
- Index sample-library metadata and derived audio features.
- Recommend from what is actually installed and available.

## P4 — Mix assistant

- Section-aware loudness/spectrum/stereo/transient analysis.
- Kick/bass, vocal/instrument, snare/midrange, and other masking reports.
- Suggested EQ/dynamics ranges tied to exact tracks/devices.
- Generalized sidechain topology instead of kick-only ducking.
- Reversible A/B variants and local renders.
- Track-level contribution analysis: identify which source is forcing a limiter, masking a vocal, widening a section, or dominating a band.

## P5 — Mastering assistant

- Multi-stage clipping/limiting experiments.
- Loudness-versus-clarity optimization rather than one LUFS target.
- True-peak, crest, spectral, transient, and stereo validation.
- Section-specific dynamics preserved through a coherent master.
- "Loudness budget" reports showing which tracks/sections consume headroom and what minimal upstream changes could buy additional clean loudness.

## P6 — Chibi / Ultron integration

- Expose production work as capability-aware Chibi tools.
- Allow planner/workers to inspect, diagnose, and propose changes while artist approval remains the default boundary for subjective material edits.
- Add durable music-production skills and plugin knowledge only after the underlying tool surface is empirically proven.
