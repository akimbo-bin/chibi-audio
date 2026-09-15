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

## Reversible diagnostic audition

`chibi_audio.control` builds temporary audition plans such as hats-only, bass-only, or explicit mute sets from a fresh project snapshot. Planning itself does not mutate Live.

Each apply operation carries exact expected state. Each restore operation expects the temporary state before restoring the original value. If a human or another worker changes the Set in between, restoration refuses instead of silently clobbering that change.

The future execution coordinator can combine an audition plan with bounded transport and ChibiTap capture while preserving the same effect-certainty rules.

## Parameter snapshots and diffs

Device parameter snapshots record exact track/device identity plus exposed parameter ids, names, raw values and display values. Diffs provide durable experiment provenance for questions such as `what exactly changed?` and support targeted rollback without relying on chat history.

## MCP-facing facade

`chibi_audio.facade.ChibiAudioFacade` is a transport-agnostic model-facing boundary intended to sit behind a secure MCP/connector endpoint. It exposes reviewed production operations and does not expose raw Live JSON-RPC.

The first facade surface covers:
- bridge status;
- project snapshot;
- device parameters;
- track mixer state;
- bounded track volume/pan;
- bounded track properties;
- bounded device parameters and enable state.

Authentication/network exposure is deliberately separate from the Live Remote Script. Port `18765` remains localhost-only.

## Parallel-lane boundary

This lane does not exercise live mutations while another worker owns the active KISSKISSKISS Set. Host-independent tests land first. A coordinated disposable live proof follows only when the active Set is free.

The ChibiTap worker continues to own audio-plane capture, multi-tap identity and sample alignment. This control lane consumes those capabilities but does not take over the VST implementation.
