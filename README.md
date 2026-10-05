# Chibi Audio
AI-assisted music production around real Ableton Live projects without generative-music slop.
Chibi Audio helps a ChatGPT/Chibi worker understand a real Live Set, diagnose production problems from structured project state plus audio evidence, make bounded and reversible changes, and prove those changes through measurable and listenable A/B experiments. Ableton remains the source-project authority; a validated stem package may be handed to REAPER for faster downstream mixdown/master experiments when the problem is truly downstream of that export boundary.
## Prime directive
**Preserve the artist's intent. Observe first. Suggest ranges. Make reversible changes. A/B the result.**
The system is not a song generator. It is a production assistant for project organization, sound selection, mixing, mastering, arrangement hygiene, plugin/sample discovery, and repetitive DAW work.
## Current focus: prove usefulness on one real song
The immediate project is the `KISSKISSKISS` pilot. We are intentionally not building the entire platform first.
The pilot sequence is now product-gated:
1. reconcile the saved `.als` snapshot with the currently open Live Set and reuse the persisted organization context;
2. prove one sonic change that the artist actually prefers, not merely one that improves a metric;
3. profile the full experiment loop and remove repeated setup / capture / analysis work;
4. keep source-, routing-, sidechain- and processor-forensics in Live with ChibiTap where that context matters;
5. export aligned stems/parts and test a scripted REAPER mixdown/master backend where a downstream audio boundary is musically valid;
6. run unattended multi-wave work only after baseline fidelity, rollback/recovery and effect-certainty behavior are proven.
A user-supplied reference track can be analyzed locally as another evidence source. Reference matching is a guide, not a mandate to flatten the song into someone else's spectral curve.
## Target architecture
- Read-only `.als` inspector for durable saved-state snapshots.
- Thin Live 12 Python Remote Script bridge for the Live Object Model.
- Localhost-only Chibi Audio adapter outside the DAW process.
- Reconciled saved-state + live-state project model.
- Machine-local plugin and sample indexes.
- Section-aware audio analysis and a reversible A/B experiment engine.
- ChibiTap JUCE/VST3 audio plane for deterministic float32 capture without repetitive Export-dialog automation; Max for Live remains an experimental/fallback adapter.
- Chibi Core as the durable workflow authority for resumable multi-wave work.
- Optional stem mixdown package -> scripted REAPER execution plane for fast downstream mix/master candidates; this is not an `.als` conversion path and never replaces Live for upstream project/routing questions.
Existing Ableton MCP/OSC projects are treated as upstream components and references, not as a second authority. See [docs/ecosystem-research.md](docs/ecosystem-research.md).
## Status
Already proven on the real pilot project:
- read-only `.als` inspection across 97 tracks;
- hierarchy/group/device/plugin discovery;
- installed plugin inventory across VST2/VST3/CLAP roots;
- Ableton Places/sample-library root discovery;
- a separate `KISSKISSKISS Chibi Lab` disk copy for experiments;
- an initial upstream research checkout for bridge and analysis candidates;
- structured Live bridge reads proven against the real Set;
- saved/live track reconciliation proven;
- one bounded source-level write + same-session A/B proof;
- packaged bridge + AgentAudioTap fallback probe with a reproducible installer;
- ChibiTap VST3 core and real-wrapper host tests proving transparent pass-through and non-zero float32 capture;
- real Ableton ChibiTap capture through typed control with no Export dialog or CUA;
- ChibiTap 0.2.0 Main/BASS/DRUMS multi-tap proof with Tap IDs 1/2/3, host-play gating, and identical sample counts across all three artifacts.
The capture foundation is proven, and the active working branch adds project organization/context, workflow contracts, automation/locator context, signal-point-aware capture/topology work, and Core handoff scaffolding. The next acceptance boundary is no longer "add more plumbing": **prove a repeatable artist-preferred KISS improvement and make the loop fast enough to search useful alternatives.** The first performance experiment is a bounded Ableton-stem -> REAPER mixdown/master backend with an unchanged-baseline fidelity gate. See [docs/stem-mixdown-reaper.md](docs/stem-mixdown-reaper.md).
See [VISION.md](VISION.md), [docs/architecture.md](docs/architecture.md), [docs/roadmap.md](docs/roadmap.md), [docs/pilot-kisskisskiss.md](docs/pilot-kisskisskiss.md), [docs/connection-contract.md](docs/connection-contract.md), [docs/capture-probe.md](docs/capture-probe.md), and [AGENTS.md](AGENTS.md).
