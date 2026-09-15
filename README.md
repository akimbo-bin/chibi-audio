# Chibi Audio

AI-assisted music production for Ableton Live without generative-music slop.

Chibi Audio is intended to let a ChatGPT/Chibi worker understand a real Ableton Live Set, the user's installed plugins and sample library, make bounded and reversible production changes, and prove those changes through measurable A/B renders.

## Prime directive

**Preserve the artist's intent. Observe first. Suggest ranges. Make reversible changes. A/B the result.**

The system is not a song generator. It is a production assistant for project organization, sound selection, mixing, mastering, arrangement hygiene, plugin/sample discovery, and repetitive DAW work.

## Initial architecture

- A read-only Ableton `.als` inspector for durable project snapshots.
- A small Live 12 Python Remote Script as the in-Ableton control bridge.
- A localhost MCP/Chibi adapter outside the DAW process.
- A plugin knowledge base built from what is actually installed.
- A sample-library index that starts read-only.
- Section-aware audio analysis and reversible A/B experiments.
- Eventual Chibi Core / Ultron integration, with Chibi Core remaining the workflow authority.

## Current milestone

P0 is reality-first inspection. The first test target is the real `KISSKISSKISS` Ableton Live 12 project on AKIMB0-PC. We have already proved that the Set can be inspected read-only from its `.als` file and that third-party plugin references can be recovered from the project structure.

See [VISION.md](VISION.md), [docs/architecture.md](docs/architecture.md), [docs/roadmap.md](docs/roadmap.md), and [AGENTS.md](AGENTS.md).
