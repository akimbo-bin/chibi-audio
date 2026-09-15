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
- Optional Max for Live audio tap only where audio-rate PCM/telemetry is genuinely required.
- Eventual Chibi Core / Ultron integration, with Chibi Core remaining the workflow authority.
Existing Ableton MCP/OSC projects are treated as upstream components and references, not as a second authority. See [docs/ecosystem-research.md](docs/ecosystem-research.md).
## Status
Already proven on the real pilot project:
- read-only `.als` inspection across 97 tracks;
- hierarchy/group/device/plugin discovery;
- installed plugin inventory across VST2/VST3/CLAP roots;
- Ableton Places/sample-library root discovery;
- a separate `KISSKISSKISS Chibi Lab` disk copy for experiments;
- an initial upstream research checkout for bridge and analysis candidates.
Next acceptance boundary: **inspect the current Live Set through a structured read bridge, reconcile it with the saved snapshot, and then perform the first reversible edit on the lab Set.**
See [VISION.md](VISION.md), [docs/architecture.md](docs/architecture.md), [docs/roadmap.md](docs/roadmap.md), [docs/pilot-kisskisskiss.md](docs/pilot-kisskisskiss.md), and [AGENTS.md](AGENTS.md).
