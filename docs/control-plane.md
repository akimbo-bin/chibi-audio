# Typed Ableton control plane

Tracked by [#6](https://github.com/akimbo-bin/chibi-audio/issues/6).

Chibi Audio should make normal production work through explicit structured capabilities rather than mouse/keyboard automation. The Live Remote Script remains localhost-only; a separate facade exposes only reviewed tools to an MCP/connector transport.

## Write contract

Every mutation follows:

`fresh observation -> exact identity -> expected before-state -> bounded mutation -> read-back verification`

A missing capability is an engineering task, never permission for silent CUA fallback.

The initial generalized surface includes:
- exact track volume and pan;
- exact mute/solo state;
- rename/recolor;
- exact exposed device-parameter changes;
- guarded device enable/bypass only when the exact host-exposed on/off parameter is identified.

Track/device/parameter IDs can supplement names and indices so stale references fail closed. Generic setters, arbitrary Live Object Model calls, and Python/eval remain unexposed.

## Locator-defined song sections

Ableton Arrangement **Locators** are exposed by the Live Object Model as `cue_points`. Chibi Audio treats them as first-class artist-authored song structure rather than trying to infer every section from audio.

The section-aware MCP adds six read-only tools:
- `get_locators` returns exact locator names and beat positions plus current/end-of-arrangement timing;
- `get_sections` treats each locator as the start of a named section and the next locator (or `last_event_time`) as its end;
- `resolve_section` turns a name such as `Drop 1` into an exact beat range and refuses ambiguous duplicate names unless an occurrence is supplied;
- `get_song_position` reports the current Arrangement beat plus active/previous/next section context;
- `plan_section_capture` resolves a named section and returns an exact capture-session-compatible beat range plus optional validated ChibiTap target specs while explicitly remaining `effect_state: NOT_STARTED`.
- `plan_section_evidence` adds an explicit reusable-analysis capability/cost plan to that same fresh section/tap plan, still with `effect_state: NOT_STARTED`; it validates analyzer selection without decoding audio or causing any Live effect.

This is intentionally beat-based. Beat boundaries remain valid under tempo automation and can feed typed ChibiTap capture/finalization without premature conversion to wall-clock seconds. The artist's locator names are metadata/evidence, not instructions to the model.

A section-capture plan does not arm ChibiTap, seek transport, start playback or write the Set. It carries the fresh locator Set signature so execution can be fenced to the exact observed Arrangement state.

When MCP writes are explicitly enabled, `capture_section` is also registered. It resolves the named section fresh, validates the requested ChibiTap target specs, then calls the existing typed capture-session executor with the exact `start_beat`, `end_beat` and `expected_set_signature`. The executor rereads the Set and refuses **before any transport or ChibiTap effect** if that signature no longer matches. Only after the finalized manifest exists below the configured artifact root does the MCP call return `effect_state: STARTED_CONFIRMED`.

The resulting downstream command path is straightforward: a worker can resolve or plan `Drop 1`, choose Main/BASS/DRUMS taps and, only with explicit write authority, capture that exact artist-authored section without guessing boundaries from the waveform or hard-coding bar numbers in chat history.

The `capture_section` path is host-independent-test proven but has not yet been exercised against the active KISSKISSKISS Live Set while another worker owns that session.

## Reversible diagnostic audition

`chibi_audio.control` builds temporary audition plans such as hats-only, bass-only, or explicit mute sets from a fresh project snapshot. Planning itself does not mutate Live.

Each apply operation carries exact expected state. Each restore operation expects the temporary state before restoring the original value. If a human or another worker changes the Set in between, restoration refuses instead of silently clobbering that change.

The execution coordinator can combine an audition plan with bounded transport and ChibiTap capture while preserving the same effect-certainty rules.

## Parameter snapshots and diffs

Device parameter snapshots record exact track/device identity plus exposed parameter ids, names, raw values and display values. Diffs provide durable experiment provenance for questions such as `what exactly changed?` and support targeted rollback without relying on chat history.

## Reusable analysis-fabric seam

Issue #8 separately owns reusable on-demand analyzers. This control lane exposes only a thin optional model-facing seam: `list_audio_analyzers`, `analyze_audio`, `analyze_capture_manifest`, and `compare_analysis_reports`. It does not copy analyzer implementations into #6.

Analysis requests explicitly name the capabilities required and a `CHEAP`, `MODERATE`, or `EXPENSIVE` ceiling. If the #8 package is absent, analyzer discovery reports unavailable and execution fails closed. If it is present, `plan_section_evidence` can validate the registry plan before any capture effect, and finalized manifests can then be analyzed read-only.

The analysis adapter confines direct artifacts and manifests to `CHIBI_AUDIO_ARTIFACT_ROOT`, preflights every finalized tap path referenced by a manifest, and rewrites returned artifact references relative to that root. Comparison operates on completed reports and does not reopen audio.

## MCP-facing facade

`chibi_audio.facade.ChibiAudioFacade` is a transport-agnostic model-facing boundary intended to sit behind a secure MCP/connector endpoint. It exposes reviewed production operations and does not expose raw Live JSON-RPC.

The base facade publishes explicit JSON-schema-shaped tool definitions rather than asking a transport to infer capabilities from Python internals. Its current surface includes 14 tools across:
- bridge/project/device/mixer reads;
- reversible audition planning;
- parameter snapshots and diffs;
- deterministic audio analysis and time-localized high-end diagnostics;
- bounded track volume/pan/properties;
- bounded device parameters and enable state.

`chibi_audio.mcp_server_sections` wraps that existing server and adds six locator/section reads/planners plus the optional four-tool reusable-analysis seam. When and only when `CHIBI_AUDIO_MCP_ALLOW_WRITES` is explicitly enabled, it also adds `capture_section` on top of the existing bounded mutation surface. The installed `chibi-audio-mcp` command routes through this section-aware server.

There is deliberately no `eval`, arbitrary Python, raw Live call, raw JSON-RPC, or click/mouse compatibility tool.

### Artifact confinement

Model-facing audio analysis does not accept arbitrary absolute filesystem paths. An adapter configures one artifact root and callers provide paths relative to that root. The facade resolves the path, refuses absolute paths and `..`/symlink escapes, and verifies the target is a real file before analysis.

This lets a secure MCP adapter expose analysis of known ChibiTap/experiment artifacts without turning the audio tool into a general filesystem-reading capability.

A read-only KISS smoke test used the facade itself against the local artifact root and reproduced the high-end diagnostic result for `D64_HOUSE.wav` without contacting Ableton.

Authentication/network exposure is deliberately separate from the Live Remote Script. Port `18765` remains localhost-only. The intended deployment is the OpenAI Secure MCP Tunnel running on AKIMB0-PC and launching `chibi-audio-mcp` over stdio, so the tunnel and MCP process share the same Windows trust boundary as Ableton without exposing Live's loopback bridge. See `deploy/CHATGPT_AUDIO_MCP.md`.

## Parallel-lane boundary

This lane does not exercise live mutations while another worker owns the active KISSKISSKISS Set. Host-independent tests land first. A coordinated disposable live proof follows only when the active Set is free.

The ChibiTap worker continues to own audio-plane capture, multi-tap identity and sample alignment. This control lane consumes those capabilities but does not take over the VST implementation.
