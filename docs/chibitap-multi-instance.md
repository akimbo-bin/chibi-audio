# Simultaneous same-track ChibiTap capture

Chibi Audio can use more than one ChibiTap on the same Live track when each instance occupies a distinct reviewed signal point.

This extends the signal-point-aware capture-session contract without introducing a generic device selector or arbitrary Live Object Model mutation.

## Intended topology

A typical verification chain can contain:

```text
ChibiTap (Tap ID 2, pre_fx)
-> compressor / sidechain / saturation / other audio effects
-> ChibiTap (Tap ID 3, post_fx)
```

One aligned session can then request:

```text
2:BASS_PRE:pre_fx:BASS
3:BASS_POST:post_fx:BASS
```

The finalized manifest records the exact Live device identity and signal-point index for both captures so downstream analysis can compare actual pre/post audio rather than infer success from plugin state.

## Exact-instance safety

The typed bridge still never accepts a generic device index mutation.

`chibitap_setup` is idempotent per signal point:

- if exactly one ChibiTap already occupies the requested signal point, that exact instance is returned;
- if none occupies the point, one fresh ChibiTap is loaded and only that newly reconciled device is moved to the reviewed point;
- if more than one ChibiTap occupies the same point, setup refuses the ambiguous state.

`chibitap_configure` and `chibitap_remove` require `expected_device_id`. They first locate that exact ChibiTap, then independently verify that it still occupies the requested signal point before changing Capture, Tap ID, or deleting the device.

Removing one ChibiTap verifies that exact device disappeared and leaves other ChibiTap instances intact.

## Capture-session resolution

The session runner does not choose a ChibiTap by name count. For each requested tap it:

1. recomputes the expected signal-point index from the fresh Live device topology;
2. requires the device physically occupying that index to be ChibiTap;
3. records its exact object ID and index;
4. verifies Capture is Off and Tap ID matches the requested ID;
5. refuses if another session spec already resolved to the same physical ChibiTap.

The last rule matters because two semantic labels can be topologically equivalent. For example, on a simple instrument track `post_instrument` and `pre_fx` can identify the same position. Chibi must use one physical tap for that position instead of pretending one device is two independent evidence sources.

## Existing maintenance paths

The aligned session path arms/disarms through `chibitap_configure`, which is multi-instance aware.

The legacy `chibitap_capture` helper remains a final-Main convenience path, and `chibitap_refresh` remains a conservative single-final-Main maintenance operation. They are not used to select arbitrary same-track instances. If Main eventually needs multiple persistent ChibiTap maintenance, that should receive its own typed extension rather than weakening these guards.

## Live proof boundary

Deterministic tests cover exact-device setup/configure/remove and same-track pre/post session resolution. A real Ableton proof still requires an available AKIMB0-PC execution tunnel and a safe lab Set. No GUI/CUA substitute should be used for that proof.