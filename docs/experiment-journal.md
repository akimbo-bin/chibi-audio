# Experiment journal

The experiment journal is the durable decision/provenance layer around finalized ChibiTap capture manifests.

It does **not** run Live, mutate the Set, decode audio, score mix quality, or decide taste. Capture execution remains owned by the capture/session layer. Measurements remain owned by the analysis fabric. The artist remains final authority on keep/reject/refine decisions.

## Why it exists

A finalized capture manifest already answers:

- what exact musical range was captured;
- which taps and Live identities produced the audio;
- sample counts, hashes and timing provenance;
- Set signature, transport state and mixer-state warnings.

That is necessary but insufficient for an iterative mix/master loop. The optimizer also needs a durable record of:

- what hypothesis was being tested;
- whether this artifact is a baseline or candidate;
- what exact change was declared between variants;
- which earlier experiment it descends from;
- what the artist decided after listening;
- the complete keep/reject/refine history.

## Binding to capture evidence

`create_experiment_journal(...)` binds one journal to one finalized capture manifest with:

- capture `experiment_id`;
- relative manifest path where possible;
- SHA-256 of the exact manifest bytes;
- requested musical range;
- Live Set signature when present;
- song identity/path when present.

`verify_experiment_journal(...)` re-hashes the bound manifest and refuses the journal if the manifest bytes or experiment identity changed. The journal therefore cannot silently drift away from the audio evidence it describes.

## Variant contract

A journal has one `comparison_id` and one role:

- `baseline` — may contain no declared changes;
- `candidate` — must contain at least one declared change.

A candidate may reference a `parent_experiment_id` so an optimization wave can preserve lineage without relying on chat history.

Each declared change records:

- target;
- parameter/property;
- before value;
- after value;
- optional unit.

These are provenance claims, not proof that a Live mutation succeeded. Higher-level control code should populate them from read-back-verified parameter snapshots when available.

## Decision contract

New journals begin with `decision.status = pending` and an empty history.

`append_experiment_decision(...)` accepts only:

- `keep`;
- `reject`;
- `refine`.

Every decision appends a timestamped history event and updates the current status. Previous events remain in the journal, so a later refinement cannot erase an earlier listening decision.

A decision note is optional but, when supplied, must be non-empty.

## Separation from analysis

The journal intentionally contains no `better`, `worse`, quality score, LUFS target verdict, or autonomous winner selection.

Analysis reports may later be referenced by a higher-level optimizer, but they remain evidence. The experiment journal exists to make the full loop reproducible:

`baseline -> hypothesis -> bounded change -> capture -> analysis -> artist decision -> keep/rollback/refine`

## Current boundary

This first slice is a pure library module and unit-test fixture. It does not modify `cli.py`, the MCP surface, `capture_session.py`, or `src/chibi_audio/analysis/**`, avoiding collision with the active #6 and #8 lanes.

The next integration step is to have the optimizer/control layer create journals from verified before/after snapshots and finalized capture manifests, then attach analysis-report references without weakening the capture-manifest integrity binding.
