# Chibi Audio
AI-assisted music production for Ableton Live without generative-music slop.
Chibi Audio helps a ChatGPT/Chibi worker understand a real Ableton Live Set, the user's installed plugins and sample library, make bounded and reversible production changes, and prove those changes through measurable and listenable A/B experiments.
## Prime directive
**Preserve the artist's intent. Observe first. Suggest ranges. Make reversible changes. A/B the result.**
The system is not a song generator. It is a production assistant for project organization, sound selection, mixing, mastering, arrangement hygiene, plugin/sample discovery, and repetitive DAW work.
## Current focus: prove usefulness on one real song
The immediate project is the `KISSKISSKISS` pilot. We are intentionally not building the entire platform first.
The pilot sequence is:
1. reconcile the saved `.als` snapshot with the currently open Live Set;
2. work only on a separate lab copy;
3. perform safe organization changes and prove rollback;
4. make one evidence-backed sonic change;
5. render level-matched A/B variants and measure the result;
6. repeat only if the loop is actually useful to the artist.
A user-supplied reference track can be analyzed locally as another evidence source. Reference matching is a guide, not a mandate to flatten the song into someone else's spectral curve.
## Target architecture
- Read-only `.als` inspector for durable saved-state snapshots.
- Thin Live 12 Python Remote Script bridge for the Live Object Model.
- Localhost-only Chibi Audio adapter outside the DAW process.
- Reconciled saved-state + live-state project model.
- Machine-local plugin and sample indexes.
- Section-aware audio analysis and a reversible A/B experiment engine.
- ChibiTap JUCE/VST3 audio plane for deterministic float32 capture without repetitive Export-dialog automation; Max for Live remains an experimental/fallback adapter.
- Eventual Chibi Core / Ultron integration, with Chibi Core remaining the workflow authority.
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
- real Ableton ChibiTap capture through typed `chibitap_capture` + `capture_transport`, with no Export dialog or CUA.
Next acceptance boundary: **make ChibiTap captures range-exact and sample-aligned across multiple instances, then use Main/BASS/DRUMS/source taps for one-command A/B and loudness-stress experiments.**
See [VISION.md](VISION.md), [docs/architecture.md](docs/architecture.md), [docs/roadmap.md](docs/roadmap.md), [docs/pilot-kisskisskiss.md](docs/pilot-kisskisskiss.md), [docs/connection-contract.md](docs/connection-contract.md), [docs/capture-probe.md](docs/capture-probe.md), and [AGENTS.md](AGENTS.md).
