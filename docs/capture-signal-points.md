# ChibiTap capture-session signal points

ChibiTap capture sessions consume the same reviewed signal-point contract as the typed Live capture surface.

## Session tap syntax

Existing callers remain valid:

```text
TAP_ID:LABEL:TARGET
```

The three-field form defaults to `post_fx`.

A session can request an explicit signal point with:

```text
TAP_ID:LABEL:SIGNAL_POINT:TARGET
```

Supported signal points are:

- `post_fx` — ChibiTap is the final device on the target track.
- `pre_fx` — ChibiTap is the first audio-effect device on the target track.
- `post_instrument` — ChibiTap is immediately after the track's single instrument device.

Examples:

```text
1:MAIN:master
2:BASS_PRE:pre_fx:BASS
3:SYNTH_POST_INST:post_instrument:52-Serum 2
```

Track names may contain `:`. Parsing splits at most three separators and treats the third field as a signal point only when it is exactly one of the reviewed identifiers, so a legacy value such as `2:BUS:DRUMS:PARALLEL` continues to mean target `DRUMS:PARALLEL` with `post_fx` capture.

## Effect certainty

Before any capture arm or transport effect, the session runner:

1. reads a fresh Set summary and Set signature;
2. resolves the exact target track and exactly one ChibiTap instance;
3. reads Live device `type` through the existing typed `get` capability when topology is required;
4. verifies the requested signal-point index from that read snapshot;
5. verifies ChibiTap `Capture` is Off and `Tap ID` matches the requested tap.

When arming, `chibitap_configure` receives the same explicit `signal_point`, exact device identity, target identity, expected Capture state, and Set signature. The bridge independently re-verifies the signal point immediately before changing Capture. If any guard fails, the session does not start transport and already-armed taps are disarmed through the same guarded path.

## Provenance

Finalized manifests record signal-point provenance under `live_session.tap_mapping`:

- requested/verified `signal_point`;
- target track identity and placement;
- ChibiTap device identity;
- snapshot `device_index`;
- arm-time verification containing the bridge-observed device identity and index.

`live_session.mixer_state.tap_targets` also records each tap's signal point and device index alongside mute/solo context.

## Current boundary

The typed ChibiTap management surface intentionally requires exactly one ChibiTap on a target track. This milestone therefore supports one explicit signal point per track per aligned session.

Simultaneous `pre_fx` + `post_fx` capture on the same track is a follow-on change: it requires a deliberate instance selector in the bridge rather than weakening the current exactly-one-instance guard. Until that selector exists, use different target tracks or separate bounded sessions rather than generic device mutation or GUI fallback.
