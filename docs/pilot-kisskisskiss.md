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
## Phase B - organization proof
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
