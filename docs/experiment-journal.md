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

Creation also requires a genuinely finalized capture manifest: every tap must have a unique integer Tap ID plus a finalized artifact path and valid SHA-256. The journal output path is refused if it resolves to the capture manifest itself, so provenance creation cannot overwrite the evidence it is binding.

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

Declared before/after values must be strict JSON values; non-finite numeric values such as `NaN` or infinity are refused rather than emitting implementation-specific JSON.

## Analysis evidence binding

`attach_capture_analysis_report(...)` binds a persisted `chibi-audio-capture-analysis/v1` result to the journal without running DSP. The report must match the already-bound capture by:

- capture `experiment_id`;
- Tap ID;
- each finalized tap's exact audio `content_sha256`;
- the inner `chibi-audio-analysis/v1` report's matching content hash.

The journal records a stable label, relative report path where possible, SHA-256 of the exact report file, requested capabilities, and per-tap content/analysis identities. An unrelated capture, wrong Tap ID/hash, wrong schema, or duplicate label is refused.

`verify_experiment_journal(...)` re-hashes every attached analysis report and revalidates it against the bound capture manifest. Editing a report after attachment therefore invalidates the journal instead of silently changing the evidence behind a later keep/reject/refine decision.

This is provenance only: the journal does not execute analyzers or interpret the measurements as a musical verdict.

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

Attached analysis reports remain evidence rather than authority. The experiment journal exists to make the full loop reproducible:

`baseline -> hypothesis -> bounded change -> capture -> analysis -> artist decision -> keep/rollback/refine`

## Current boundary

This first slice is a pure library module and unit-test fixture. It does not modify `cli.py`, the MCP surface, `capture_session.py`, or `src/chibi_audio/analysis/**`, avoiding collision with the active #6 and #8 lanes.

The next integration step is to have the optimizer/control layer create these journals automatically from read-back-verified before/after snapshots plus finalized `capture_section_evidence` results, while preserving this module as a pure provenance layer rather than a second execution authority.
