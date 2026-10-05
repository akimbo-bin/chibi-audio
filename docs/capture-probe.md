# Audio capture implementations

## Primary path: ChibiTap VST3

ChibiTap is the primary Chibi Audio capture implementation. It is a small JUCE/VST3 effect whose audio path is deliberately transparent. Capture writes are handed to JUCE `AudioFormatWriter::ThreadedWriter`, producing stereo IEEE float32 WAV evidence under `~/.chibi-audio/chibitap/captures`.

Typed Live control is split into two narrow capabilities:

- `chibitap_setup` - ensures exactly one final ChibiTap at an exact Main/track target;
- `chibitap_configure` - guarded Tap ID and Capture configuration for that exact device;
- `chibitap_capture` - narrow Main-only Capture toggle retained for compatibility;
- `capture_transport` - bounded `status`, `seek`, `play`, and `stop` control.

The first end-to-end Live proof captured real non-zero 48 kHz stereo float32 audio with no Export Audio/Video dialog and no CUA. A control capture over a silent musical range produced an all-zero file exactly as expected.

### Current boundary

ChibiTap 0.2.0 may be armed while stopped but writes only while the host playhead reports playback. Main/BASS/DRUMS produce aligned raw captures in one Live pass, and the capture-session/finalizer now turns any documented shared transport overrun into the exact requested common sample interval with hashes and manifest provenance.

The remaining capture-plane constraints are different:
- Live/ChibiTap evidence is still fundamentally a realtime host-play path, so use short synchronized diagnostic windows and multi-tap passes rather than repeated long captures;
- exact beat-to-sample conversion is currently authoritative only for constant-BPM requested ranges; tempo automation needs a tempo-map-aware boundary model;
- bulk downstream mix/master candidate search should use the separate fidelity-gated stem backend when the hypothesis no longer requires Live source-project context.

## Experimental/fallback path: AgentAudioTap Max for Live

The repository still packages a small Max for Live capture probe derived from the MIT-licensed AgentAudioTap upstream implementation. It remains useful as an experimental Live-specific adapter, but `sfrecord~` and Max device/runtime behavior were not reliable enough to make this the primary audio plane.

The portable installer keeps the upstream source/template flow and avoids committing user-specific paths. Its command surface remains bounded (`open`, `start`, `stop`, `status`).

## Design rule

Use the Remote Script for Ableton object/state intelligence and bounded project control. Use ChibiTap for audio samples. Use Max only when a genuinely Max/Live-specific capability cannot be expressed reliably through those two surfaces. Never silently fall back to GUI automation when a typed capture capability is missing.
