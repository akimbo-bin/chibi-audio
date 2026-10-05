# Ecosystem research - October 2026
This document converts the ecosystem survey into build decisions. It is deliberately not a link dump: every upstream project has a role, a boundary, and a reason we are or are not depending on it.
## Decision summary
The commodity layer is already well explored: Python Remote Scripts, Live Object Model wrappers, OSC bridges, MCP transport, device/parameter enumeration, browser search, and basic track/clip operations all exist in open-source projects.
**Chibi Audio should not differentiate itself by becoming another giant Ableton MCP.**
Our differentiating layer is:
- reconciled saved + live project state;
- safe exact-target mutations with effect certainty;
- snapshots and rollback;
- plugin/sample knowledge grounded in what is actually installed;
- section-aware audio evidence;
- reference-aware comparison;
- track-level contribution and loudness-stress analysis;
- reproducible A/B experiments with artist acceptance;
- a measured fast-path from project diagnosis to candidate comparison;
- backend-neutral experiment provenance so Live and a validated stem backend can be compared without confusing their authority.
## Local research shortlist
The following repositories are checked out separately for source-level study. They are not vendored into this repository.
| Upstream | Local research role | License observed in checkout | Checkout freshness | Decision |
| --- | --- | --- | --- | --- |
| `bschoepke/ableton-live-mcp` | Broad Live/MCP implementation with arrangement, devices, automation, browser, routing and audio-tap ideas | MIT | last checked commit dated 2026-07-24 | **FORK/ADAPT selectively** |
| `ahujasid/ableton-mcp` | Remote Script + MCP design, arrangement APIs, installer/version-handshake patterns | MIT | last checked commit dated 2026-08-30 | **USE AS REFERENCE / selectively adapt** |
| `ideoforms/AbletonOSC` | Mature OSC/Remote-Script control pattern | MIT | last checked commit dated 2025-11-19 | **REFERENCE / fallback seam** |
| `nozomi-koborinai/ableton-osc-mcp` | OSC-to-MCP composition pattern | MIT | last checked commit dated 2026-07-25 | **REFERENCE** |
| `spotify/pedalboard` | Offline audio/plugin-processing experiments | GPLv3 | last checked commit dated 2026-09-09 | **PROTOTYPE/REFERENCE pending license decision** |
| `MTG/essentia` | Rich audio feature extraction | AGPLv3 | last checked commit dated 2026-08-27 | **REFERENCE or isolated optional tool pending license decision** |
| `librosa/librosa` | Python feature-analysis baseline and rapid prototypes | ISC | last checked commit dated 2026-08-22 | **ADOPT where useful** |
| `facebookresearch/demucs` | Analytical source separation | MIT | last checked commit dated 2023-11-16 | **OPTIONAL/REFERENCE; not core** |
| `adamjmurray/producer-pal` | Serious Ableton MCP/REST product benchmark: project editing, compact context and client-agnostic control | GPL-3.0 | reviewed October 2026 | **BENCHMARK; borrow interaction/context ideas selectively** |
| `DBraun/DawDreamer` | Programmable offline VST/audio graph and automation research | GPL-3.0 | reviewed October 2026 | **SECONDARY PROTOTYPE/REFERENCE** |
| REAPER / ReaScript | Scriptable DAW backend for aligned stem mixdown/master experiments, render queues and full-speed offline rendering | commercial application/API, not vendored | reviewed October 2026 | **PREFERRED FIRST STEM BACKEND TO PROTOTYPE** |
The license column is an engineering planning signal, not legal advice. Copyleft candidates stay outside the core dependency set until we make an explicit distribution/compliance decision.
## Ableton bridge findings
### What existing projects already solve
Existing implementations demonstrate that a Live 12 Remote Script can expose useful structured control for:
- song/tempo/transport state;
- Arrangement and Session tracks/clips;
- group hierarchy and mixer state;
- device chains and parameter metadata;
- automation and routing;
- browser/device/preset search;
- plugin loading where Live exposes it;
- health/version handshakes.
That means we should reuse proven patterns instead of spending months on generic transport plumbing.
### What we must not inherit blindly
A broad MCP surface is not automatically a safe production surface. In particular:
- do not expose arbitrary Python/eval-style execution to the model;
- do not expose every mutation simply because the underlying API can perform it;
- do not add analytics/telemetry without explicit user consent;
- do not silently fall back to mouse/keyboard automation when a typed capability fails;
- do not let the bridge own project planning, durable workflow state, or autonomous authority;
- do not assume a command succeeded until its effect is reconciled.
### Primary path
**Keep the Python Remote Script + localhost bridge as the primary Live-control path.**
Rather than shipping an upstream MCP unchanged, create a thin Chibi-specific facade over a small, reviewed subset of proven bridge code. The public surface should start read-only and expand only as each write class is proven on a copied Set.
OSC remains useful as a compatibility/reference path, but it is not the preferred primary seam because the Live Object Model provides richer typed object/parameter access.
## Max for Live decision
Max for Live is not the workflow authority and is not the primary networking layer.
Use it only for capabilities that materially benefit from living in Live's audio/control graph, especially:
- PCM/audio-rate taps for per-track analysis;
- sample-accurate envelope or meter telemetry unavailable through the Remote Script;
- purpose-built measurement devices.
Keep those devices small and replaceable. Analysis, storage, orchestration and AI reasoning remain outside Live.
## Offline project model
The `.als` parser remains valuable even after the live bridge exists. Saved and live state answer different questions:
- `.als` = durable last-saved project snapshot;
- Live Object Model = currently open mutable state, including unsaved edits.
Chibi Audio should build both snapshots and reconcile them. A mismatch is evidence, not an error to paper over.
Do not assume raw `.als` numeric IDs are identical to live object identities. Reconciliation should use a stable fingerprint composed from available object identity plus group lineage, track order/name, device chain position/type, clip/sample references and other corroborating fields. Ambiguous matches must stay ambiguous rather than being guessed.
## Safe mutation model
Every material write batch should be represented as a transaction-like experiment:
1. refresh current live state;
2. resolve exact target identities;
3. record preconditions and the values that will change;
4. ensure the project is a lab/copy target;
5. create a checkpoint/snapshot;
6. perform a bounded typed mutation;
7. re-read the targets and confirm the observed effect;
8. render or measure if the change is sonic;
9. keep, refine or roll back.
No write should be replayed when the effect is unknown.
## Audio-analysis stack
Start simple and inspectable rather than assembling a huge ML/DSP stack immediately.
Near-term core measurements:
- sample/true peak;
- LUFS momentary, short-term and integrated;
- RMS/crest factor;
- spectral-band energy and spectral tilt;
- stereo correlation and Mid/Side balance;
- transient/onset density;
- section-to-section contrast;
- level-matched difference/comparison measurements.
`librosa` is suitable for rapid feature work. More specialized native libraries can be added only when a concrete pilot requirement justifies them. `Essentia` is useful research material, but its AGPL license means it should not quietly become a core public dependency.
## Downstream stem mixdown / offline experiments

The first offline acceleration target is **not** Ableton-project conversion.

Live already exports aligned individual tracks/selected tracks suitable for transfer to another multitrack program. Chibi should use that explicit audio boundary: export the stems/parts needed for the current mixdown/master question, preserve exact provenance, then let a scripted REAPER project test downstream candidates quickly.

REAPER is the preferred first prototype because:
- ReaScript can control project, track, FX, routing and render state;
- render settings expose stems/master selection, time bounds, tails and other deterministic controls;
- full-speed offline rendering is the normal fast mode;
- render queues and render-matrix/batch workflows fit candidate search;
- the project can remain much smaller than the original instrument/arrangement-heavy Live Set.

This is valid only after a baseline-fidelity gate. Some plug-ins can behave differently when rendered offline, and a stem export may have already baked away the interaction Chibi wants to change. If the unchanged REAPER baseline does not reproduce the declared Live stem baseline closely enough, the backend is not authoritative for that experiment.

`spotify/pedalboard` and `DBraun/DawDreamer` remain useful alternatives for narrower programmable plugin-graph experiments. Both are GPLv3 today, so distribution/licensing implications must be reviewed before either becomes a bundled dependency. They are not needed to validate the REAPER stem path.

See [stem-mixdown-reaper.md](stem-mixdown-reaper.md).
## Source separation
Demucs can be useful for analysis or when only a mixed reference/source is available. It should not be a mandatory runtime dependency and should never replace access to the real individual tracks when those tracks already exist in the Live Set.
## Reference tracks
A user-provided reference track can be analyzed locally for:
- section loudness and crest factor;
- low/mid/high spectral distribution;
- transient density;
- stereo width/correlation;
- macro-dynamics across sections;
- relative bass/kick/vocal placement where analysis can support it.
Reference comparison must be level matched. The goal is to understand transferable properties, not blindly EQ-match or loudness-match another master.
## High-value idea: loudness stress map
Instead of treating the final limiter as the only loudness control, build a report that attributes headroom consumption to upstream sources.
An MVP should answer questions such as:
- which tracks create the largest summed peaks at the limiter input;
- which events repeatedly coincide with high limiter gain reduction;
- which frequency bands dominate those events;
- whether the problem is level, envelope length, phase/summation, overlap, or missing harmonic audibility;
- how much clean loudness a small upstream change buys.
Example output should look like a testable hypothesis, not an automatic command:
> Kick layer X and bass layer Y coincide around 55-70 Hz on 63% of the highest master peaks. Variant B clips the kick by 1 dB and shortens the bass release slightly; this reduces peak demand by N dB while preserving level-matched tonal balance.
This is a Chibi Audio differentiator and should be built from real pilot evidence rather than abstract DSP assumptions.
## Product benchmark posture

The ecosystem already contains credible Ableton controllers. `ahujasid/ableton-mcp`, `Producer Pal`, `bschoepke/ableton-live-mcp`, and AbletonOSC demonstrate that generic control, project inspection, broad MCP surfaces and even audio-tap feedback loops are not sufficient novelty by themselves.

Chibi should periodically run a copied-Set capability/latency comparison against serious upstreams. Custom code earns its place when it provides materially better safety, project reconciliation, causal audio evidence, experiment reproducibility, throughput, or artist usefulness. Do not preserve bespoke plumbing merely because it already exists.

Commercial mix-assistant products are also useful product benchmarks for editable assistant-generated processing and masking/unmasking workflows. Chibi's distinct target remains project-aware causal investigation plus reversible evidence, not a one-click quality score.

## Anti-patterns to avoid
- giant all-powerful MCP with arbitrary code execution;
- giant Max device containing state, networking, DSP and agent logic;
- direct `.als` XML mutation as an editing method;
- mouse automation as a hidden fallback for missing typed operations;
- one-click "AI mastering" judged only by LUFS;
- destructive sample-library organization before project-reference safety exists;
- thousands of plugin categories/manuals before the pilot proves they help;
- autonomous subjective changes without A/B evidence and artist acceptance.
