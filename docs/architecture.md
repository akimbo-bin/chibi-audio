# Architecture
## Authority model
Chibi Core is the eventual workflow authority. Chibi Audio supplies typed production capabilities; it must not create a parallel scheduler, task database, or autonomous authority.
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
Initial public capability set is deliberately small:
- health/version/capability handshake;
- get song/arrangement metadata;
- list tracks/groups and routing;
- list devices and parameter metadata;
- read mixer/device values;
- read locators and relevant automation metadata.
Only after read reconciliation is proven do we add bounded writes such as rename, recolor and exact parameter changes.
### Explicit exclusions
- no arbitrary Python/eval capability;
- no remote network listener beyond localhost;
- no hidden telemetry;
- no silent GUI fallback;
- no autonomous save/overwrite of the artist's only Set.
## 3. UI accessibility is bootstrap observability, not steady-state authority
Windows accessibility can currently expose a surprising amount of Live state and is useful for prototyping/verification. It is not the desired primary mutation path because UI layout and focus are less stable than typed Live objects.
Use UI automation only for operations that genuinely lack a structured seam, and make that fallback explicit.
## 4. Optional Max for Live audio tap
Use a small Max for Live device only if we need audio-rate PCM or meter telemetry unavailable through the Remote Script.
The Max device should stream/measure; it should not own project state, MCP orchestration, planning or durable history.
## 5. Plugin knowledge base
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
## 6. Sample library index
Start read-only. Index metadata without reorganizing files. Later derive duration, sample rate, channels, BPM/key estimates, transient/spectral features and semantic embeddings where useful.
Moving, renaming or deduplicating samples is a separate opt-in capability because existing Live Sets may reference exact paths.
## 7. Audio evidence layer
Analyze real renders by musical section, not only whole-song averages.
Near-term evidence:
- LUFS and true/sample peak;
- RMS and crest factor;
- band energy/spectral balance;
- transient density;
- stereo width/correlation and Mid/Side balance;
- low-end overlap;
- level-matched A/B deltas.
A user-supplied reference can be analyzed through the same measurements.
Metrics are evidence, not musical truth.
## 8. Experiment engine
A material subjective change is an experiment, not an opaque edit.
Each experiment records:
- baseline snapshot identifier;
- exact project/section/targets;
- hypothesis;
- exact change set and ranges;
- observed post-write values;
- A/B render identifiers;
- level-matched metrics;
- user verdict: keep, refine, reject, rollback.
The experiment engine is the basis for later automated EQ, dynamics, sidechain and mastering exploration.
## 9. Mutation/effect certainty
Every write batch follows:
`REFRESH -> RESOLVE -> CHECKPOINT -> MUTATE -> VERIFY -> MEASURE -> ACCEPT/ROLLBACK`
If the observed effect cannot be confirmed, effect state is UNKNOWN and the mutation must be reconciled before any replay.
## 10. Chibi integration
Once the pilot surface is stable, expose these capabilities through Chibi Core. Core remains the durable planner/task authority; Chibi Audio is a specialized executor + evidence system.
See [ecosystem-research.md](ecosystem-research.md) for upstream component decisions and [pilot-kisskisskiss.md](pilot-kisskisskiss.md) for the first proof.
