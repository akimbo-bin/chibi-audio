# Level-matched A/B artifacts

`chibi_audio.ab_compare.create_level_matched_ab(...)` creates a listening pair for two already-aligned audio variants without modifying either source file.

The default contract is deliberately conservative:

- both inputs must have the same sample rate, channel count and exact sample count;
- integrated loudness is measured through the existing capability-driven analysis fabric;
- the quieter measured variant becomes the target;
- gain is only reduced, never increased;
- both outputs are rendered as floating-point WAV so existing over/under-zero float behavior is preserved rather than clipped by integer export;
- output sample count must remain identical to the inputs;
- the rendered pair is measured again and refused if the integrated-loudness mismatch exceeds the verification tolerance;
- source and output SHA-256 fingerprints, probes, loudness evidence and applied gain are written to one portable manifest;
- an existing output package is never silently overwritten.

This produces two views of an experiment:

1. **as produced** — the original variant captures, which preserve the real production-level difference;
2. **level matched** — the derived listening pair, which removes the simplest loudness-bias confound when judging tone, punch, stereo, harshness or other subjective differences.

Neither view is a musical verdict. A louder render is not automatically better, and a level-matched render is not a mastering target.

## CLI

```powershell
chibi-audio level-match-ab `
  baseline.wav candidate.wav `
  --output-dir .\artifacts\drop-1-ab `
  --comparison-id drop-1 `
  --left-label baseline `
  --right-label candidate
```

The command prints the resulting JSON manifest. The two WAV paths recorded inside the manifest are relative to the manifest directory.

## Real pilot proof

The first real proof used the already-finalized, sample-aligned KISS lab Locator `3` BASS pre/post captures (beats 96-160, 1,365,333 samples each). The pre capture measured about -12.91 LUFS and the post capture about -14.11 LUFS. The utility applied -1.20 dB only to the louder pre capture and 0 dB to the quieter post capture. Both derived WAVs remained 1,365,333 samples, and the verification pass measured both at -14.11 LUFS with 0.0 LU observed mismatch.

That pre/post pair is a technical proof of the artifact workflow, not the final artistic A/B use case. The intended production use is baseline-versus-candidate captures from a bounded reversible experiment.
