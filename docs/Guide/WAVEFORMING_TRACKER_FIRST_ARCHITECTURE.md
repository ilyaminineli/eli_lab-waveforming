# WAVEFORMING — Tracker-first visual instrument architecture

**Design basis:** [IDM Visual Instrument / Visual Composition / Generative Art and Live Concert Architecture](IDM_Visual_Instrument_Visual_Composition_Generative_Art_and_Live_Concert_Architecture.md)

**Status:** First tracker-first implementation in progress. This document distinguishes what is working in the current application from the larger architecture that should guide subsequent reinvention.

---

## 1. Product principle

WAVEFORMING is a **musical-structure-driven visual instrument**.

An XM module is not merely an optional source of timing markers for an audio visualizer. It is already a structured score containing:

- ordered patterns and row timing;
- persistent tracker channels;
- note-on, note-off, pitch and instrument assignments;
- volume-column data;
- effect-column commands;
- pattern repetition and arrangement structure;
- instrument and sample identities.

Those structures should be enough to preview and export a visual performance. Audio is an optional parallel source: it can provide playback, a reference mix, external timbral analysis or synchronization, but it must not be a prerequisite for visual composition.

The guide's distinction between structured musical input and audio analysis is authoritative here. Audio features are modulators; they do not replace musical semantics.

## 2. Current XM profile: `total fvckery.xm`

The uploaded module is a useful first reference case:

| Property | Value |
|---|---:|
| Tracker | MilkyTracker 1.05.01 |
| Channels | 14 |
| Active channels | 10 |
| Silent channels | 4 |
| Patterns | 17 |
| Pattern rows | 64 |
| Orders | 24 |
| Instruments | 10 |
| Initial tempo | 173 BPM |
| Initial speed | 6 |
| Effect-column commands | 0 |
| Estimated duration | 133.18 seconds |

The order list is:

`0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 7, 7, 5, 5, 14, 15, 16`

At the initial tempo and speed, one tracker row lasts `speed × 2.5 / BPM`; 64 rows therefore take approximately 5.55 seconds. The complete 24-order arrangement takes approximately 133.18 seconds. This module contains no effect-column commands, so the current visual behaviour is driven by its actual note events, channel identities, instrument/sample changes, pattern boundaries, repetitions and tempo—not by imagined tracker effects.

### Channel inventory

The values below describe the uploaded file's event data, not a general assumption about what each channel should do.

| Channel | Note events | Instrument/sample identity |
|---|---:|---|
| CH01 | 211 | Instrument 1 — `j.wav` |
| CH02 | 768 | Instruments 6/7 — `R-8808 hh c.wav` / `R-8808 hh o.wav` |
| CH03 | 141 | Instruments 5/6 — `13.wav` / closed hi-hat |
| CH04 | 32 | Instrument 2 — `1 39.wav` |
| CH05 | 56 | Instrument 3 — `43.wav` |
| CH06 | 29 | Instruments 4/9 — `10.wav` / `R8 Reverb HClap.wav` |
| CH07 | 187 | Instrument 8 — `R-8high q.wav` |
| CH08 | 52 | Instruments 9/10 — reverb clap / unnamed sample |
| CH09 | 11 | Instrument 10 — unnamed sample |
| CH10 | 6 | Instrument 10 — unnamed sample |
| CH11–14 | 0 | No note events in this module |

The last four channels are not removed. They remain stable, low-salience voices so the visual arrangement preserves the XM's full 14-channel topology.

## 3. Tracker-first data path

The current implementation follows this path:

```text
XM file
  │
  ▼
XM metadata / pattern / instrument parser
  │
  ▼
VisualScore (orders, patterns, rows, channel profiles, sample identities)
  │
  ▼
Tracker packet at musical time
  │
  ├── current order and pattern
  ├── current row and row progress
  ├── held note, pitch and note age per channel
  ├── channel instrument and sample identity
  ├── volume and effect-column state
  ├── recent note activity
  └── transition and pattern-reprise signals
  │
  ▼
Mapping / visual director
  │
  ▼
TRACKER ENSEMBLE + structural environment
  │
  ▼
Preview compositor / offline renderer
```

The XM parser reads pattern cells and instrument/sample headers, then seeks over sample payload bytes. Visual import does not decode sample audio. Sample names are metadata used to maintain voice identity and improve inspection.

### Stable voice identity

Every XM channel receives a stable content-scoped identity:

`<score-id>:channel:<channel-number>`

The channel number is the primary identity. Instrument/sample assignment can change during the piece without changing the channel's identity or its spatial anchor. The current score packet also carries instrument selection across order boundaries, so an omitted instrument column does not cause the visual voice to fall back to an unrelated predominant sample.

## 4. One ensemble renderer, many real voices

The visual scene should represent the XM channel structure without creating a separate full-canvas renderer for every channel.

The current composition uses:

1. a restrained structural environment layer;
2. one **TRACKER ENSEMBLE** layer that draws all XM channels as independently mapped voices.

Within the ensemble, channel identity determines a stable spatial anchor. Instrument identity chooses a geometric/material family and ink. The current tracker state controls its deformation and salience.

| Tracker data | Current visual mapping |
|---|---|
| Channel number / voice ID | Persistent spatial identity and label |
| Instrument and sample | Geometry family, material colour and sample annotation |
| Note pitch | Radial/elevation displacement and shape proportion |
| Note trigger | Attack pulse and directional gesture |
| Held note / note age | Decaying contour and activity envelope |
| Recent note hits | Short density/trace accent |
| Volume column | Pulse weight and opacity |
| Panning command | Bounded movement inside that channel's sector |
| Arpeggio / slide / portamento | Lobe count and phase/drift |
| Vibrato / tremolo | Contour modulation and radial echo |
| Sample offset | Phase displacement |
| Pattern boundary | Brief structural ring/transition accent |
| Pattern reprise | Low-opacity return trace |
| Channel silence | Quiet latent node; no fabricated note activity |

This is an initial mapping profile, not a claim that every tracker command is fully emulated. Unsupported flow-control commands remain explicitly marked as approximate timing. For `total fvckery.xm`, the effect column is empty; its visual activity therefore comes from notes, instruments, sample identities, channel density and arrangement structure.

## 5. Timing and transport

The musical clock is the authoritative timebase for XM-only sessions.

- The XM order list establishes arrangement position.
- Pattern rows and current tempo/speed establish row timing.
- Pattern boundaries provide structural cue points.
- The visual animation clock may continue to drive continuous geometry, but it must not replace musical time.
- Audio playback, when present, is synchronized to the same playhead as a secondary clock/input.

The application now supports a standalone tracker transport: play, pause, seek, loop and timeline position work without starting the audio engine. When audio is imported, it can be played alongside the tracker-driven visual score.

Future clock work should follow the guide's separation of musical, audio, performance-wall and render clocks. These clocks need explicit mapping rather than hidden assumptions.

## 6. Audio is optional

Audio input has two distinct jobs:

**Reference playback / final sound:** WAV, FLAC and other supported stems can be imported, mixed and included in MP4 export. This is optional for XM-driven visuals.

**External sound analysis:** When audio is present, RMS, spectrum, transients and cross-source features can modulate the visual scene. They should remain subordinate to the XM's exact structural and per-channel events.

Tracker-only preview and tracker-only video export must work without fake PCM buffers, silent placeholder stems or an audio decoder.

## 7. Rendering cost and export profiles

The previous export path rendered every frame through the compositor at the full 1920×1440 resolution. At 4,000 frames this asks the Python/Pillow generator pipeline to process approximately **11.06 billion output pixels** before accounting for layer passes, masks, transforms and feedback.

The current export profiles keep the delivery canvas at 1920×1440 but allow generator/compositor work at a smaller internal resolution. FFmpeg performs the final upscale during encoding.

| Profile | Internal render | Pixels per frame | Relative pixel work |
|---|---:|---:|---:|
| PERFORMANCE | 640×480 | 307,200 | 1/9 |
| BALANCED | 960×720 | 691,200 | 1/4 |
| FULL | 1920×1440 | 2,764,800 | 1× |

For 4,000 frames, the respective internal canvases represent approximately 1.23B, 2.76B and 11.06B pixels. These are arithmetic pixel-work comparisons, **not measured wall-clock speedups**. The actual benefit depends on generator cost, layer count, GPU/CPU path and encoding.

The goal is to reduce expensive Python image generation and raw RGBA pipe traffic. FFmpeg still produces the selected delivery dimensions. Performance and Balanced are practical preview/export choices; Full remains available for work where every source pixel matters.

### Next rendering work

1. Profile each generator separately at the selected internal resolution.
2. Cache invariant geometry, masks, sample textures and static scene layers.
3. Separate slow simulation update cadence from final frame cadence.
4. Keep per-pixel processing out of Python where a shader or native vectorized path is justified.
5. Add frame-time percentiles, memory, dropped-frame and encode-throughput telemetry.
6. Preserve deterministic scene identity and musical timing across quality tiers.

## 8. Automation and effects

The existing timeline automation lanes (Complexity, Motion, Sensitivity) remain useful global controls. The tracker mapping adds event-level automation on top of them.

The next iteration should promote the current direct mappings into explicit **MappingRule** records with:

- source event/feature and stable channel ID;
- target visual object/property;
- normalized units and range;
- mapping curve, smoothing and decay;
- priority and manual override behaviour;
- randomization seed/stream;
- missing/stale-data policy and safety clamp.

This keeps an XM channel's identity and semantic role stable even when its visual geometry changes. It also gives a future live operator a way to override density, motion, palette, foreground, transition mode, feedback, freeze/hold and bounded variation without changing the underlying score.

## 9. Scene and cue model — the architectural direction

The guide's longer-term Visual Instrument model remains the target. The first persistent `VisualScene` / `VisualObject` / `VisualScore` slice is now implemented:

- **VisualBrief / VisualIdentity:** still planned; artistic intention, visual vocabulary, palette, material and continuity are not yet an editable project model.
- **VisualScore:** implemented as a serializable ordered trajectory with score-linked XM order/pattern cues.
- **VisualScene / VisualObject:** implemented as persistent scene and object records linked to executable renderer layers through stable IDs.
- **VisualRelationship:** a typed relationship record is available; authoring tools and runtime relationship semantics remain planned.
- **VisualCue / VisualEvent:** structural XM order cues are represented with explicit musical time; note/phrase/performer event scheduling remains planned.
- **VisualRole / VisualMotif / VisualPhrase:** basic object roles and scene attention groups exist; reusable motif and phrase grammar remains planned.
- **MappingRule / SourceBinding:** source-binding records exist for audio routes and XM channel identities; an executable rule engine is still planned.
- **SceneTransition:** declarative transition contracts, lifecycle validation, proposal/commit separation, deterministic progress sampling and interruption policies are implemented; application-level multi-scene execution and visual interpolation remain planned.
- **VisualSnapshot / ShowManifest:** deterministic snapshots, recovery and live-show packaging remain planned.

The scene's canonical layer order is consumed by preview and offline rendering. `VisualLayer` remains the rendering unit for this compatibility step; a logical VisualObject containing multiple layers is future work.

The director should propose candidate scene changes separately from committing them. Manual performance overrides should take precedence over explicit cues, structured musical state, per-voice features, audio estimates and autonomous visual motion, following the priority model in the companion guide.

## 10. Implementation status

### Implemented in the current tracker-first pass

- XM instrument and sample header metadata, with sample payload seeking rather than audio decode.
- Stable per-channel voice IDs and channel profiles.
- Per-order note, instrument, volume and effect matrices.
- Carried instrument and held-note state across XM order boundaries.
- Per-channel note envelope, event density, recent hits and current command state.
- TRACKER ENSEMBLE as a single multi-voice visual generator.
- XM-aware automatic composition while preserving manual compositions.
- Channel/sample inspector in the UI, including silent channels.
- XM-only play/pause/seek/loop and XM-only MP4 export.
- PERFORMANCE / BALANCED / FULL internal render profiles, with FFmpeg upscale to the fixed delivery canvas.
- CI smoke validation rather than a reinstated pytest suite.
- Persistent VisualObject IDs linked to renderer layers; archived object identity after layer removal.
- VisualScene serialization, canonical layer order, attention grouping, and audio/XM source bindings.
- VisualScore serialization with timed XM order-entry and pattern-return cues.
- Scene graph layer order applied in live preview and offline rendering.
- Validated scene lifecycle state machine and declarative SceneTransition contracts.
- Proposal/commit controller, deterministic preparation/transformation/establishment phases, and complete/cancel/reject interruption policies.
- Version-2 project persistence with version-1 migration from the existing layer stack and tracker data.

### Still planned — do not treat as implemented

- Full Bxx/Dxx/E6x order-jump, break and pattern-loop playback simulation.
- General tracker formats beyond XM.
- Editable VisualBrief and VisualIdentity models.
- Multi-layer logical objects, authorable relationship graph and motif lineage tools.
- Multi-scene project collection and active-scene persistence.
- Cue-driven transition nomination/commit and visual interpolation in the compositor.
- Editable per-channel MappingRule profiles and channel solo/mute/focus controls.
- Cue/phrase-based scene transitions with renderer-side preparation, transformation and establishment effects.
- A GPU-native tracker ensemble and multi-resolution simulation cache.
- Live MIDI/OSC operator controls and a full show/venue output manager.
- Benchmarks on the target Windows hardware and 4,000-frame export comparisons.

The principle for future work is simple: **preserve musical meaning first, then adapt visual quality and rendering strategy around it.**
