# Chibi Audio Vision

## What we are building

Chibi Audio is a dedicated music-production system analogous in spirit to Vision for video editing: Chibi Core remains the eventual workflow authority, while Ableton Live, local analysis tools, and workstation automation are execution surfaces.

The objective is to make an AI worker useful inside an existing human-made production workflow. It should understand the project deeply enough to help with:

- inventorying, categorizing, and searching a large plugin collection;
- indexing and organizing sample libraries;
- naming, grouping, and color-coding tracks consistently;
- mapping tracks, groups, routing, sidechains, devices, and automation;
- finding masking, resonances, harshness, low-end collisions, and stereo problems;
- distinguishing source problems from artifacts introduced later by track, bus or master processing;
- reasoning about perceptual audibility rather than relying only on spectrum and loudness numbers;
- predicting whether important bass harmonics, vocals, hats and other elements survive phone-like, mono, low-volume and other playback conditions;
- proposing section-aware EQ, compression, sidechain, transient, saturation and automation changes;
- inserting and configuring effects when explicitly authorized;
- producing reversible A/B variants so the artist can choose by ear;
- measuring LUFS, true peak, crest factor, spectral balance, stereo width, psychoacoustic descriptors and other evidence before and after changes;
- helping with mastering while preserving intentional section-to-section dynamics;
- learning durable production conventions and plugin knowledge rather than guessing from generic advice.

The long-term analysis goal is a **synthetic hearing stack**: structured Ableton state, aligned source/track/bus/master captures, deterministic DSP measurements, psychoacoustic and masking evidence, playback-translation profiles, reference tracks, semantic audio features and real listening validation. No individual sensor is treated as musical truth. The reasoning model integrates these senses into testable production hypotheses.

## What it is not

Chibi Audio is not Suno and is not intended to replace composition or generate generic finished songs. It is not a second workflow authority beside Chibi Core. It must not flatten, destructively rewrite, or silently reorganize a Live Set. It is also not intended to become one giant Max for Live patch responsible for networking, persistence, orchestration, analysis, and editing.

It is also not an autonomous declaration engine for whether music objectively `sounds good`. Technical and perceptual evidence can reveal likely problems and predict translation failures, but artistic acceptance remains with the artist.

## Interaction model

The default production loop is:

1. Observe fresh project state and musical section structure.
2. Diagnose one specific production question.
3. Explain the evidence and propose a bounded change or useful test range.
4. Create a checkpoint/snapshot when a material edit is involved.
5. Apply one coherent change.
6. Render, meter, capture or otherwise gather A/B evidence.
7. Let the artist judge the musical result and, where useful, validate translation on real playback.
8. Keep, refine, or roll back.

The artist remains the authority on whether a subjective change actually sounds better.

## Long-term goal

A user should eventually be able to say things like:

- "Clean up and color-code this Set without changing how it sounds."
- "Show me every plugin I own that can do transparent clipping, and which ones I actually use."
- "Why does Drop 2 feel smaller than Drop 1?"
- "Find where the vocal and synth are masking and create two reversible fixes for me to audition."
- "These hats get crispy in my car. Tell me which exact layers or processors are causing it and make two bounded fixes."
- "Will this bass still be obvious on a phone? Show me which harmonics survive and what masks them."
- "Make an A/B where the snare also ducks the competing midrange for 80 ms, but leave the bass alone."
- "Try three ways of getting this drop 2 dB louder and tell me which one preserves the most crest factor and stereo width."

That is the product: deep production assistance around the artist's own material, not generated replacement material.
