# Chibi Audio operator rules

- Preserve artist intent. Do not generate or replace musical material unless explicitly asked.
- Observe fresh project state before every mutation batch.
- Prefer typed Live/bridge operations over GUI automation.
- Never silently fall back to mouse/keyboard automation when a structured operation fails.
- Never write `.als` XML directly as a normal editing method.
- Snapshot/copy before broad or destructive changes.
- Make subjective production changes as bounded A/B experiments.
- Numerical targets are evidence, not authority; user listening decides subjective acceptance.
- Exact track/device identity matters. Do not mutate an object selected only by a stale positional index.
- Sample-library organization begins read-only; moving or renaming source files requires explicit authorization.
- Chibi Core is the eventual workflow authority. This repository supplies production capabilities, not a second scheduler or task database.
