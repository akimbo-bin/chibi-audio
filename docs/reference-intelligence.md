# Reference intelligence

Reference audio stays local. Chibi Audio stores paths, SHA-256 identities, derived analysis, and named project-set membership; it never copies reference audio into the repository.

## Local registry

```powershell
chibi-audio reference-register "D:\References\track.wav" `
  --library-root "$HOME\.chibi-audio\reference-library" `
  --name "Track" --project KISSKISSKISS --set-name main
```

Registration is content-addressed. The same audio at a second path reuses the logical reference and adds the new local location/name. `reference-verify` re-hashes registered locations before they are trusted again.

`reference-compare` compares a candidate against every member of a named set using whole-track measurements plus an independently selected loudest window. The result is descriptive evidence, not a quality score or an instruction to clone the reference.

## Stem separation

`reference-separator-status` reports whether a local Demucs backend is available. When present, `reference-separate` writes a SHA-keyed local separation cache and a manifest containing exact source/stem hashes. The source file is never modified.

`reference-analyze-stems` verifies every stem hash before analysis. Separated stems are explicitly treated as model estimates that can contain bleed or artifacts; they are not authoritative source stems.

If Demucs is absent, Chibi Audio reports that capability as unavailable. There is no GUI or silent substitute backend.
