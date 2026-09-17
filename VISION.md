# Chibi Audio Vision

## What we are building

Chibi Audio is a dedicated music-production system analogous in spirit to Vision for video editing: Chibi Core remains the eventual workflow authority, while Ableton Live, local analysis tools, and workstation automation are execution surfaces.

The objective is to make an AI worker useful inside an existing human-made production workflow. It should understand the project deeply enough to help with:

- inventorying, categorizing, and searching a large plugin collection;
- indexing and organizing sample libraries;
- naming, grouping, and color-coding tracks consistently;
- mapping tracks, groups, routing, sidechains, devices, and automation;
- auditing sidechain relationships as explicit source -> target edges, estimating appropriate frequency/depth/timing behavior, routing them consistently across tracks and buses, and verifying from captured audio that the intended ducking actually occurred;
- finding masking, resonances, harshness, low-end collisions, and stereo problems;
- distinguishing source problems from artifacts introduced later by track, bus or master processing;
- reasoning about perceptual audibility rather than relying only on spectrum and loudness numbers;
- predicting whether important bass harmonics, vocals, hats and other elements survive phone-like, mono, low-volume and other playback conditions;
- proposing section-aware EQ, compression, sidechain, transient, saturation and automation changes;
- inserting and configuring effects when explicitly authorized;
- producing reversible A/B variants so the artist can choose by ear;
- measuring LUFS, true peak, crest factor, spectral balance, stereo width, psychoacoustic descriptors and other evidence before and after changes;
- helping with mastering while preserving intentional section-to-section dynamics;
- running explicitly authorized, bounded iterative mix/master optimization loops that modify the Live Set, render, analyze, keep or roll back, and adapt the next experiment toward a user-defined goal;
- learning durable production conventions and plugin knowledge rather than guessing from generic advice.

The long-term analysis goal is a **synthetic hearing stack**: structured Ableton state, aligned source/track/bus/master captures, deterministic DSP measurements, psychoacoustic and masking evidence, playback-translation profiles, reference tracks, semantic audio features and real listening validation. No individual sensor is treated as musical truth. The reasoning model integrates these senses into testable production hypotheses.

Sidechain analysis is one important example of why the stack needs both project state and audio evidence. Knowing that a compressor, Trackspacer-like spectral processor or volume shaper is routed to a kick/snare/vocal is not enough: Chibi should be able to measure the real gain or spectral-reduction envelope, its timing relative to the trigger, the residual collision after processing, any recovered downstream headroom, and whether the routing still matches the producer's intent.

## What it is not

Chibi Audio is not Suno and is not intended to replace composition or generate generic finished songs. It is not a second workflow authority beside Chibi Core. It must not flatten, destructively rewrite, or silently reorganize a Live Set. It is also not intended to become one giant Max for Live patch responsible for networking, persistence, orchestration, analysis, and editing.

It is also not an autonomous declaration engine for whether music objectively `sounds good`. Technical and perceptual evidence can reveal likely problems and predict translation failures, but artistic acceptance remains with the artist.

An iterative optimization mode may decide that one measured candidate is better than another **within an explicit goal contract and guardrails**. It still must not confuse that bounded production judgment with universal musical taste. "Keep optimizing until happy" means until the requested measurable goal is satisfied, progress stalls, a guardrail is hit, or the next decision is subjective enough to require the artist.

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

For goal-level requests where the artist explicitly authorizes iteration, Chibi may repeat that loop in bounded waves without requiring approval after every low-risk step:

1. establish a baseline, references, target bundle and experiment budget;
2. choose the highest-value evidence-backed hypothesis;
3. checkpoint and apply one coherent reversible change;
4. render through the authoritative Live path;
5. analyze level-matched and as-produced results;
6. keep the candidate only if it improves the best-so-far result without violating guardrails;
7. roll back losing variants exactly;
8. update the hypothesis from the new evidence and continue;
9. stop when the target is satisfied, no useful improvement remains, quality regresses, confidence becomes insufficient, the budget is exhausted, or artist judgment is required.

### Hierarchical mix orchestration

For real mix work, Chibi should reason hierarchically rather than brute-force one parameter at a time. Chibi Core moves forward into the active mix loop as the durable workflow authority: one **Mix Orchestrator** owns the best-so-far Set, section goal, evidence graph and experiment budget, while specialist workers investigate buses, sources, sidechains, references and translation in parallel. Workers may propose experiments, but they do not become independent workflow authorities.

The execution model is deliberately asymmetric:

- **one serialized Ableton executor** owns all Live mutations, checkpoints and restores;
- **bus workers** investigate DRUMS, BASS, VOX, FX and other major groups against the orchestrator's current hypothesis;
- **source workers** descend only into suspicious children rather than scanning every track after every wave;
- **cross-bus workers** own relationships such as kick -> bass or vocal -> competing music;
- all workers share durable artifact/hash/section evidence through Core rather than copying raw audio into model context.

The audio plane should also be hierarchical. Use a short synchronized **bus census** first, then a **suspect-bus census** with that bus's children, then **surgical pre/post captures** only for implicated processors. Diagnostic windows should normally be a few seconds around known stress events; full-drop/full-song captures are acceptance checks for candidates that already won the fast diagnostic round. ChibiTap remains the authoritative surgical evidence path while a faster native/offline render executor is investigated for bulk work.

For loudness work in particular, Chibi should reason about a **clean-loudness knee** rather than maximizing LUFS blindly: the point where more master drive increasingly produces crest collapse, bass flattening, pumping, harshness, clipping or cross-band distortion instead of useful perceived loudness. Sidechain changes are a first-class upstream strategy in that search when time-frequency collisions are creating the loudness bottleneck.

The artist remains the authority on whether a subjective change actually sounds better.

## Long-term goal

A user should eventually be able to say things like:

- "Clean up and color-code this Set without changing how it sounds."
- "Show me every plugin I own that can do transparent clipping, and which ones I actually use."
- "Why does Drop 2 feel smaller than Drop 1?"
- "Find where the vocal and synth are masking and create two reversible fixes for me to audition."
- "These hats get crispy in my car. Tell me which exact layers or processors are causing it and make two bounded fixes."
- "Will this bass still be obvious on a phone? Show me which harmonics survive and what masks them."
- "Audit all my sidechains. Tell me which buses are ducking from the wrong source, which ones are doing nothing, and whether anything is being over-ducked twice."
- "Set the kick/bass sidechain so the kick gets clean low-end space without unnecessarily chopping the bass, and prove how much headroom it recovered."
- "Add snare clearance to the groups that actually mask it, but don't touch groups that already leave enough room."
- "Make room for the vocal globally using Trackspacer or dynamic EQ where that is more transparent than full-band ducking, then verify the actual reduction on every target."
- "Make an A/B where the snare also ducks the competing midrange for 80 ms, but leave the bass alone."
- "Try three ways of getting this drop 2 dB louder and tell me which one preserves the most crest factor and stereo width."
- "I want to mix and master this track to be loud. Work in reversible waves: change the Live Set, render, analyze against these references, keep the best version, and stop when more loudness would cost too much clarity or punch."

That is the product: deep production assistance around the artist's own material, not generated replacement material.
