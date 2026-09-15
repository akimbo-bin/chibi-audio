# Roadmap
The roadmap is deliberately pilot-first. New platform work is allowed only when the current acceptance boundary needs it.
## R0 - Establish reality and a safe playground - DONE / final reconciliation pending
Completed:
- read real `.als` files without mutation;
- map the real KISSKISSKISS track/group/device structure;
- inventory installed VST2/VST3/CLAP files;
- discover Ableton Places/sample-library roots;
- survey and clone a focused upstream component shortlist;
- create a separate `KISSKISSKISS Chibi Lab` project folder from the last saved project state.
Remaining before writes:
- capture/reconcile the currently open Set's unsaved state into the lab lineage;
- record a clean baseline snapshot and baseline render.
**Acceptance:** the original Set is untouched and we can identify exactly which project lineage is safe to edit.
## R1 - Read the currently open Set deeply - ACTIVE
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
## R2 - First reversible organization edit
On the lab Set only:
- checkpoint current state;
- choose a few unambiguous naming/color-hygiene improvements;
- apply exact rename/recolor operations through the typed bridge;
- re-read and verify every changed value;
- prove rollback;
- save a lab variant, never overwrite the original project.
**Acceptance:** one coherent organization batch is applied and reversed/reapplied reliably with an exact audit trail.
## R3 - First meaningful sonic A/B
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
## R4 - Reference-track comparison
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
- generalized sidechain relationships (kick, snare, vocal, FX, etc.);
- per-section automation;
- optional offline plugin-chain experiments;
- optional audio-rate telemetry via a small Max for Live tap.
## R9 - Chibi / Ultron integration
Expose proven capabilities to Chibi Core as a specialist production executor. Preserve Core as the only workflow authority and preserve artist approval for subjective material changes by default.
## Scope guard
Before adding a new subsystem, ask:
**Does the next KISSKISSKISS acceptance boundary require it?**
If not, defer it.
