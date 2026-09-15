# Capture probe

Chibi Audio packages a small Max for Live capture probe derived from the MIT-licensed AgentAudioTap upstream implementation.

## Purpose

Replace repetitive Export Audio/Video UI work with typed, deterministic capture at a known signal point. The device is transparent stereo pass-through and records WAV evidence with `sfrecord~ 2`.

## Portable build

The repository stores:
- `AgentAudioTap.template.amxd` as an AMXD container template;
- `AgentAudioTap.maxpat` as source;
- `agent_audio_tap.js` as the controller.

The installer generates `AgentAudioTap.amxd` for the target machine and embeds the command file under `~/.chibi-audio/agent_audio_tap_command.json` (or the chosen `--state-dir`). No user-specific path is committed.

## Current typed control

- `open(path)`
- `start`
- `stop`
- `status`

Capture control does not imply probe placement, soloing, seeking, transport control, or destructive Set edits. Those remain separate capabilities.

## Next proof

When Ableton is free, install/activate the packaged bridge and probe, then prove one capture from a known signal point with no CUA or Export dialog. After that, add a typed range/transport coordinator and only then aligned multi-probe capture.
