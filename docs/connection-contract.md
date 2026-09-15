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
- `chibitap_capture(enabled, expected_current_value, expected_device_id, expected_set_signature)`;
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
6. Gate capture against the host timeline/range; until range gating lands, record lead/tail and trim only with explicit timing evidence.
7. Stop transport and disarm capture.
8. Wait until each WAV is stable on disk.
9. Fingerprint each artifact with SHA-256 and verify format/sample rate/channel count plus non-zero/silence expectations.
10. Analyze immutable captures and attach results to the experiment manifest.

The single-Main ChibiTap path is already proven. The next coordinator must make steps 4-8 one typed, sample-aligned operation across multiple taps. Until then, the model must not substitute CUA for missing range/alignment semantics.
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
