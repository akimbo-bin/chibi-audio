# Chibi Audio Live bridge
This directory makes the Live connection reproducible instead of depending on a one-off Remote Script installed on one workstation.
## Boundary
The bridge is an executor, not a workflow authority. The model-facing capability surface is intentionally much smaller than the implementation inherited from the upstream MIT project.
Exposed capability classes:
- read-only project/device/clip/browser inspection;
- one bounded track-volume write used by the pilot experiment engine;
- `agent_audio_tap` commands (`open`, `start`, `stop`, `status`) for a pre-installed capture probe.
Not exposed:
- arbitrary Python `eval` / `exec`;
- generic property setters or generic method calls;
- device insertion/loading through the model-facing bridge;
- automatic soloing, seeking or transport control for capture;
- hidden GUI/CUA fallback.
If a structured capability is unavailable, callers must receive an explicit unsupported/unavailable error rather than silently clicking through Live.
## Capture probe
Chibi Audio vendors an MIT-licensed AgentAudioTap template container, source `.maxpat`, and JavaScript companion. `scripts/install_live_bridge.py` generates the target machine's `AgentAudioTap.amxd` with the correct `~/.chibi-audio` command-file path, avoiding baked-in user paths. The effect records transparent stereo pass-through audio with `sfrecord~ 2`.
The first capture milestone deliberately supports a probe that is already installed/placed by an explicit setup step. Loading/removing devices and controlling Live transport are separate capabilities and are not bundled into capture start/stop.
## Attribution
The bridge and AgentAudioTap are adapted from `bschoepke/ableton-live-mcp` under the MIT license preserved in `LICENSE.upstream`. Chibi-specific policy, client wrappers, experiment state and analysis live outside the DAW process.
