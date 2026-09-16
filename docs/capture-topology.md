# Managed ChibiTap capture topology

Chibi Audio can prepare the ChibiTap topology required by a capture request instead of requiring the artist to manually insert and configure every tap first.

This layer sits above the typed ChibiTap bridge operations and below MCP / Locator workflows. It owns capture preparation and restoration only; it does not own song-section resolution or audio analysis.

## Preparation

`prepare_capture_topology(...)` accepts typed `CaptureSessionTap` specs and an optional planned Set signature.

For each requested tap it:

1. reads a fresh Set summary and refuses a stale caller-provided signature before any ChibiTap effect;
2. resolves the exact target track;
3. calls typed `chibitap_setup` for the requested `pre_fx`, `post_instrument`, or `post_fx` signal point using the current Set signature;
4. records whether the exact ChibiTap was newly created or reused, its device identity/index, and its prior Tap ID;
5. refreshes the Set summary after setup because topology may have changed;
6. if needed, changes Tap ID only while Capture is verified Off and under exact expected-before guards;
7. refreshes state again before preparing the next tap;
8. finally resolves the complete session through the normal capture-session resolver and proves every prepared device/index/signal point matches the lease.

The returned `CaptureTopologyLease` contains the initial and final Set signatures plus exact per-tap provenance.

## Unknown-effect reconciliation

A control call can fail at the transport boundary after Live applied the requested effect. Preparation/restore therefore does not equate a call exception with `NOT_STARTED`.

For reused ChibiTaps whose Tap IDs may have been temporarily changed, restore re-reads the exact device:

- if the prior Tap ID is already present, no replay occurs;
- if the requested temporary Tap ID is observed, restore performs one guarded write back to the prior value;
- if any other Tap ID is observed, restore refuses instead of guessing;
- if Capture is On, Tap ID restoration is refused.

Created devices are removed only by exact recorded device ID + signal point and only when Capture is Off.

## Managed capture

`run_managed_capture_session(...)` composes the lifecycle:

```text
planned Set signature
  -> prepare exact ChibiTap topology
  -> obtain final prepared Set signature
  -> run_capture_session(expected_set_signature=prepared signature)
  -> restore reused Tap IDs
  -> optionally remove taps created by this session
```

The capture runner now owns a pre-effect `expected_set_signature` fence, so a Set change between planning/preparation and capture is refused before transport or Capture is touched.

On successful capture, `remove_created_after=False` retains newly created ChibiTaps for future fast captures while still restoring temporarily borrowed Tap IDs on reused devices. Set `remove_created_after=True` for disposable capture topology.

If capture itself fails, managed capture always attempts to remove devices created by that failed preparation, regardless of the success-retention policy.

## Failure reporting

If capture fails but topology restore succeeds, the original capture error is preserved.

If capture and restore both fail, the error explicitly reports incomplete topology restore rather than hiding the second failure.

If capture finalized successfully but restore then fails, the error includes the manifest path so the finalized evidence is not lost while still making the dirty topology state explicit.

## MCP integration boundary

The MCP/control lane should call the capture-owned managed lifecycle rather than reproducing setup/configure/cleanup logic. Locator resolution remains in the control lane; analyzer selection remains in the analysis lane.

This leaves a thin production path:

```text
Locator / section plan
  -> run_managed_capture_session
  -> finalized manifest
  -> requested analyzer capabilities
```

No GUI/CUA fallback is part of this path.