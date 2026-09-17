# Project Organization Schema

This file is the user-editable default organization contract for Chibi Audio projects. It is a preference system, not a destructive template: preserve musical intent, existing routing and useful human names when evidence is uncertain.

## Plane order

`organize` normally runs before `mix`. Its job is both presentation and project understanding: classify the Set, normalize obvious organization, and persist reusable context for later mix/sidechain/master workers.

Default top-level order:

1. VOX
2. MUSIC / HARMONIC / MELODIC
3. BASS
4. SIDECHAIN / TRIGGERS
5. DRUMS
6. FX

Omit categories that do not exist. Preserve exceptional routing or creative structure when moving a track would be unsafe.
## Drum-family order

Within DRUMS, prefer functional order first and arrangement chronology second:

1. Kick / main kick
2. Secondary, top, half or layered kick
3. Snare / clap
4. Hi-hat
5. Ride / cymbals
6. High/top percussion
7. Low/bottom percussion
8. Breaks / loops
9. Fills / transitions
10. Miscellaneous percussion

When the same role appears in several song sections, pair related tracks and sort them by musical chronology such as intro -> build -> drop 1 -> bridge -> drop 2 -> outro.
## Grouping

Use groups when they improve navigation or encode a real musical/functional relationship. Avoid creating a group solely to satisfy a rigid taxonomy.

Nested drum groups may represent a section, a source family, or a production layer when that grouping makes the Set easier to read. Prefer adjacency and naming over unnecessary nesting.

Creating/reparenting groups is **structural**, not cosmetic. Before any structural organization change, snapshot input/output routing, parent/group relationships, sends, sidechain sources/targets and relevant device state. Execute only when Chibi can prove the resulting signal-flow contract is equivalent or the requested routing change is explicit.

## Naming

Preserve useful source identity. Prefer adding concise semantic role/section information over replacing recognizable names with generic labels. Low-confidence classifications stay unchanged and are reported for review.
## Color system

Use related color families for major buses, with meaningful variation inside each family rather than painting every child identically. Distinguish important subroles such as kick, snare/clap, hats/cymbals, percussion, breaks/fills, lead vocal, doubles, chops and vocal FX.

Exact palette choices may be updated in this file as preferences evolve. Chibi should preserve deliberate existing colors unless the organization pass has enough confidence to improve consistency.

## Track heights

- Tall: major buses and tracks with dense or important automation.
- Medium: important musical sources or tracks frequently inspected during production.
- Short/compact: simple one-shots, straightforward drum layers and simple FX sources.

Height decisions are presentation metadata and should be derived from automation density, clip/device complexity and role, not only track type.
## Persistent project context

An organization run should persist a structured project knowledge graph that later workers can reuse. At minimum it should capture:

- track/group hierarchy and routing identity;
- semantic role and confidence;
- arrangement/section activity;
- functional family and related tracks;
- devices and automation complexity;
- sidechain relationships;
- presentation state such as name, color, order, height and fold state;
- unresolved classifications and structural safety blockers.

A later `mix`, `sidechain` or `master` command should refresh this context incrementally rather than rediscovering the whole Set from scratch.