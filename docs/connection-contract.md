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
Pilot writes must have exact identity and before-state preconditions. The first implemented write is exact track-volume mutation using:
- track index;
- expected current track name;
- expected current raw value;
- requested new value.
A mismatch refuses the operation. Generic setters, arbitrary calls and arbitrary Python execution are not exposed.
### Capture
The capture controller exposes only `agent_audio_tap` commands:
- `open(path)`
- `start`
- `stop`
- `status`
The capture command path does not install devices, solo tracks, seek transport or manipulate the arrangement. Those are separate capabilities and must be designed/authorized independently.
## Capture artifact lifecycle
1. Create a `CapturePlan` with experiment/source identity and musical range.
2. Write an atomic experiment manifest.
3. Ensure a trusted AgentAudioTap is already present at the desired signal point.
4. Send `open` with a unique output path.
5. Start capture.
6. Run/play the musical range through Live.
7. Stop capture.
8. Wait until the WAV becomes stable on disk.
9. Fingerprint it with SHA-256.
10. Analyze the immutable capture and attach results to the experiment.
The planned next coordinator will make steps 4-8 a single typed operation after transport/range control is proven safe. Until then, the model must not substitute CUA for a missing coordinator.
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
