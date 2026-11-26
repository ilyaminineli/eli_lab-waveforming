# M6 — XM as a tracker-driven visual score

## Status

Tracker-first implementation is available on `main`: XM metadata and channel identities, standalone tracker transport, TRACKER ENSEMBLE, channel inspection and tracker-only export.

## Product principle

XM is not an audio file and is not just a source of timing markers. It is a structured musical score.

WAVEFORMING uses the XM's actual order list, pattern rows, channel identities, note events, instrument/sample assignments, volume-column state and effect-column commands to drive visuals directly. An external WAV/FLAC mix is optional. It may be imported for listening, final soundtrack, reference, synchronization or complementary audio-reactive modulation, but it is not required to preview or export the tracker-driven visual performance.

The tracker channels—not the number of imported audio files—are the primary visual voices.

## Supported input and parser behavior

The importer reads the XM song header and packed pattern blocks, then reads instrument/sample headers for identity metadata. It seeks across the sample payload bytes without loading or decoding them.

Extracted information includes:

- module title and tracker;
- channel, pattern, order and instrument counts;
- initial speed/tempo and row timing;
- order list and pattern references;
- per-row notes, instrument selections, volume values, effects and parameters;
- per-channel note counts, pitch range, active patterns and predominant sample/instrument names;
- carried instrument and held-note state across order positions;
- pattern repetition, transition strength and current row activity.

This is a visual-score importer, not an XM audio playback engine. The tracker provides note/event data to visual synthesis. If an audible soundtrack is required, import a reference mix or stems separately.

### Timing limitations

Fxx speed/tempo changes are included in row-time calculation. Bxx order jumps, Dxx pattern breaks and E6x pattern loops are detected but are not fully simulated by the order walker yet. When those commands occur, timing is flagged as approximate. The uploaded `total fvckery.xm` has no effect-column commands, so this limitation does not affect its current order timing.

## Current score: total fvckery.xm

| Property | Value |
|---|---:|
| Tracker | MilkyTracker 1.05.01 |
| Channels | 14 |
| Patterns | 17 |
| Pattern rows | 64 |
| Orders | 24 |
| Instruments | 10 |
| Initial BPM | 173 |
| Initial speed | 6 |
| Effect-column commands | 0 |
| Estimated duration | 133.18 s |

Order sequence:

`0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 7, 7, 5, 5, 14, 15, 16`

At 173 BPM and speed 6, one row is approximately 0.0867 seconds and a 64-row order is approximately 5.55 seconds. The final order uses empty pattern P16.

### Channel inventory

The active note-channel inventory in this uploaded file is:

| Channel | Note events | Predominant sample/instrument identity |
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

The four silent channels remain part of the 14-channel score. They are preserved as low-salience latent voices, not removed or assigned invented activity.

## Import and preview workflow

1. Use **+ XM** to load the tracker score, or **+ FOLDER** to discover XM scores and audio stems separately.
2. WAVEFORMING creates order markers, sets the timeline tempo and populates the XM TRACKER VOICES inspector.
3. The default starter layer is replaced by a tracker-aware composition when the project is still in its initial/automatic state. An intentionally edited manual scene is not overwritten.
4. Press **PLAY**. With no audio loaded, the tracker clock advances the XM score and drives TRACKER ENSEMBLE directly.
5. Use the transport to pause, seek and loop. The playhead is shared by the tracker cue resolver and the visual director.
6. Optionally import WAV/FLAC stems to hear the music and add audio-analysis modulation.
7. Save the .wfp project. The tracker structure and channel/sample metadata are embedded; export does not need to reopen the original XM file.

## XM TRACKER VOICES inspector

The inspector lists every XM channel, including silent channels. It displays:

- channel number and stable score-scoped voice ID;
- predominant instrument/sample label;
- total note events;
- pitch range;
- active patterns;
- silent/active status.

The channel number is the stable spatial identity. A channel may change instrument/sample during the score without changing its identity or spatial role.

## TRACKER ENSEMBLE

The ensemble renders all channels inside one compositional instrument, rather than creating 14 separate full-canvas generator layers.

Current mappings:

| Tracker information | Visual response |
|---|---|
| Channel number / voice ID | Stable spatial anchor and label |
| Instrument/sample | Geometry family, ink identity and annotation |
| Note pitch | Shape proportion and spatial elevation |
| Note trigger | Attack pulse and directional gesture |
| Held note / note age | Decaying contour/activity envelope |
| Recent note hits | Short trace-density accent |
| Volume column | Attack weight and opacity |
| Panning command | Bounded local channel displacement |
| Arpeggio / portamento / slides | Lobe count and phase/drift |
| Vibrato / tremolo | Contour modulation and echo |
| Sample offset | Phase displacement |
| Pattern boundary | Brief transition accent |
| Pattern reprise | Low-opacity return trace |
| Silent channel | Quiet latent node; no fabricated note activity |

The above is the current visual mapping, not a promise of complete tracker-effect emulation. The uploaded file has zero effect-column commands; its actual visuals are driven by note density, sample/instrument identity, channel recurrence and arrangement.

## Standalone tracker export

MP4 export accepts an XM tracker score without any audio sources. The output is a silent video stream in that case. When audio sources are present, WAVEFORMING mixes them and adds the soundtrack to the same tracker-driven visual export.

Export quality controls the internal rendering resolution while keeping the delivery canvas at 1920×1440:

- **PERF ⅓:** 640×480 internal render, then upscale;
- **BAL ½:** 960×720 internal render, then upscale;
- **FULL 1×:** full 1920×1440 internal render.

The lower-resolution modes reduce Python/Pillow generator and compositor pixel work. The arithmetic pixel reduction is not a measured wall-clock speedup; hardware and generator costs still matter.

## Next

- Full Bxx/Dxx/E6x order-jump, pattern-break and pattern-loop simulation.
- Editable channel-to-visual MappingRule profiles and per-channel mute/solo/focus.
- Persistent VisualScene/VisualObject state and cue/phrase transitions.
- GPU-native tracker ensemble and measured static-layer/simulation caching.

See [WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md](WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md) for the broader architecture.
