# Live connection contract
This document defines the model-facing boundary between Chibi Audio and Ableton Live.
## Goals
- Every worker gets the same typed capability surface.
- A worker can determine capability availability before attempting work.
- Unsupported structured operations fail explicitly; they never silently fall back to GUI automation.
- Reads, bounded mutations, and audio capture are separate authority classes.
- Capture files are deterministic experiment artifacts, not ad-hoc exports with manually chosen names.
## Handshake
`bridge_status` returns:
- `protocol_version`
- `policy_version`
- `capabilities.read`
- `capabilities.bounded_write`
- `capabilities.capture`
- `capabilities.gui_fallback` (must be false)
- `capabilities.arbitrary_code` (must be false)
- main-thread health/in-flight timeout information
A client must not infer a capability from code that happens to exist inside the Remote Script. It may call only an advertised model-facing method.
## Capability classes
### Read
Project/set metadata, tracks, routing, devices, parameters, clips, locators and browser search. Read operations are the default surface.
### Bounded write
Pilot writes must have exact identity and before-state preconditions. The bounded pilot surface now covers exact track volume/pan, mute/solo/name/color, and exact exposed device parameters.

Writes require freshly observed identity plus expected before-state and verify the value after mutation. Optional Set-signature and object-id guards make stale indices fail closed. Device enable/bypass is a named bounded operation only when the exact host-exposed on/off parameter is identified.

Generic setters, arbitrary calls and arbitrary Python execution are not exposed. See [control-plane.md](control-plane.md) for the model-facing facade, reversible audition-plan and parameter snapshot/diff contract.
### Capture
The primary capture surface is ChibiTap plus bounded transport:
- `chibitap_setup(placement, exact track identity, expected_set_signature)`;
- `chibitap_configure(placement, expected_device_id, expected Tap ID/Capture state, requested Tap ID/Capture state, expected_set_signature)`;
- `chibitap_capture(...)` as the narrow Main-only compatibility toggle;
- `chibitap_refresh(...)` for guarded replacement of one stale final Main instance after plugin layout upgrades;
- `capture_transport(status|seek|play|stop)`.

`chibitap_capture` is intentionally not a generic plugin-parameter setter. It refuses to act unless the final Main device is exactly `ChibiTap`, the device identity matches when supplied, the observed `Capture` value matches `expected_current_value`, and any supplied Set signature still matches.

The legacy `agent_audio_tap` Max-for-Live command path (`open/start/stop/status`) remains advertised only as an experimental/fallback capture implementation.

Capture authority does not imply arbitrary device insertion, soloing, routing edits, broad parameter writes, or GUI control. Those remain separate typed capabilities.
## Capture artifact lifecycle
1. Observe fresh Set signature, target device identity, and current ChibiTap Capture value.
2. Create an experiment/capture plan with source identity and musical range.
3. Ensure trusted ChibiTap instances are already present at the desired signal points.
4. Pre-arm the capture writer(s) without changing the audio path.
5. Seek/play the requested musical range through typed transport control.
6. ChibiTap gates writes on host playback. A shared raw overrun is allowed only when all taps remain sample-aligned and requested/actual host timing is recorded.
7. Stop transport and disarm capture.
8. Wait until each WAV is stable on disk and verify the raw tap sample counts are equal.
9. Finalize the requested musical range deterministically: translate the requested beat interval and transport-start offset to sample indices, crop every aligned tap to that exact interval, and verify equal exact final sample counts.
10. Fingerprint raw and final artifacts with SHA-256, verify format/sample rate/channel count plus non-zero/silence expectations, run requested analysis, and write one experiment manifest.

The Main/BASS/DRUMS multi-tap path and exact-range finalizer are proven. Tap IDs map artifacts to exact Live signal points; raw playback captures are sample-aligned; and `finalize-capture` turns any documented shared overrun into the same authoritative requested sample interval across all taps. The current exact beat conversion is valid for constant-BPM ranges; tempo automation requires a tempo-map-aware extension. CUA is not a substitute for any missing timing/capture semantic.
## Effect certainty
Mutations and capture control use the same certainty principle as Chibi Core:
- `NOT_STARTED`: no command/effect was issued.
- `STARTED_CONFIRMED`: the command was accepted and the resulting state/artifact was verified.
- `UNKNOWN`: command delivery/effect cannot be reconciled.
`UNKNOWN` must reconcile before replay.
## Installation
`scripts/install_live_bridge.py` copies packaged bridge/probe files into an Ableton User Library. It does not launch Ableton, change a Live Set or select a Control Surface. Use `--dry-run` first; replacement of different existing files requires explicit `--replace`.
## GUI policy
UI automation can remain a diagnostic/bootstrap escape hatch for genuinely UI-only operations, but it is not a hidden compatibility layer. A typed operation that is absent or unhealthy returns unavailable/unsupported and becomes an engineering task.
