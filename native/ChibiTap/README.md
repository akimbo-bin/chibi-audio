# ChibiTap VST3

ChibiTap is the compiled audio plane for Chibi Audio. Ableton project intelligence and bounded DAW control remain the job of the Chibi Audio Remote Script; ChibiTap is an ear, not a second workflow authority.

## Current milestone

Proven on AKIMB0-PC with JUCE 9.0.2 and Ableton Live 12:

- transparent mono/stereo pass-through;
- host-visible `Capture` parameter;
- `juce::AudioFormatWriter::ThreadedWriter` for background recording;
- IEEE float32 WAV capture under `~/.chibi-audio/chibitap/captures`;
- no file I/O or analysis on the audio thread;
- headless processor test proving sample-for-sample transparency plus non-zero float32 capture;
- host-side VST3 smoke test that discovers and instantiates the actual built bundle;
- real Ableton capture through the typed `chibitap_capture` + `capture_transport` bridge path.

The first real Live proof produced a 48 kHz stereo `pcm_f32le` file with non-zero mastered audio and no Export Audio/Video dialog or CUA.

## Build

The project is CMake-based. JUCE is pinned to `9.0.2`; pass a local checkout with `CHIBITAP_JUCE_DIR` or allow CMake FetchContent to retrieve the pinned release.

Build targets:

- `ChibiTap` - VST3 bundle;
- `ChibiTapCoreTests` - direct processor transparency/capture test;
- `ChibiTapVst3SmokeTest` - loads the actual VST3 through JUCE hosting APIs and repeats the transparency/capture proof.

The build intentionally does not copy the plugin into a system VST3 directory automatically. Installation remains an explicit step.

## Safety / realtime rules

The audio callback must stay boring: read the host buffer, hand it to the pre-created threaded writer when capture is active, and leave the host buffer unchanged. Networking, filesystem discovery, analysis, orchestration, and model reasoning stay outside the realtime path.

## Next milestone

Current capture is trustworthy but not yet sample-range exact: arming before playback and disarming after stop creates lead/tail around the requested transport window. The next milestone is a capture-session contract with host-timeline gating so multiple ChibiTap instances can produce sample-aligned Main/BASS/DRUMS/source captures from the same musical range.
