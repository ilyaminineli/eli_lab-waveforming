# M6 — XM tracker-driven visual workflow

## Status

Implemented foundation: XM import, arrangement cues, project persistence, preview/export packet integration and the TRACKER MATRIX visual instrument.

## Purpose

Treat a tracker module as a visual score. The XM order list and pattern data provide
structural timing; the audio feature bus remains responsible for continuous sound
response. This avoids trying to infer a song's structure from amplitude peaks alone.

## Supported input

The importer reads XM song headers and packed pattern events sequentially. It
stops immediately after the pattern table and never reads the instrument headers
or sample payload section. It does not decode or retain sample audio. It extracts:

- module title, tracker name, channel count, initial tempo and speed;
- order list and referenced pattern index;
- row note counts and per-channel note/pitch/instrument maps;
- active channels, instrument assignments and note density;
- effect-column commands, including Fxx speed/tempo changes.

The importer is a metadata reader, not an XM playback engine. The existing audio
track must still be imported separately when audio playback and audio-reactive
modulation are required.

### Timing limitations

Fxx speed/tempo changes are applied while calculating cue durations. Bxx order jumps,
Dxx pattern breaks and E6x pattern loops change playback flow and are not simulated
by the current cue walker. When such commands are present, the UI flags the imported
score as using approximated flow timing. The order list remains available for review.

## Current module: total fvckery.xm

The uploaded module reports:

- MilkyTracker 1.05.01;
- 14 channels, 17 patterns and 24 order positions;
- 10 instruments;
- initial tempo 173 BPM and speed 6;
- 64 rows in each of the 17 patterns;
- the 1,165,933-byte uploaded file needs only 19,051 bytes read through its
  song header and pattern table; the remaining 1,146,882 bytes are not read by
  the metadata importer;
- order list:
  `0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 7, 7, 5, 5, 14, 15, 16`;
- zero effect-column commands;
- the last pattern (P16) contains no note events.

At the initial tempo/speed, each row lasts 6 × 2.5 / 173 seconds. Each 64-row
order therefore lasts approximately 5.55 seconds and the complete 24-order score
approximately 133.18 seconds (2:13). No control-flow effects alter that calculation
in this file.

Pattern note counts:

| Pattern | Note events | Active channels |
|---|---:|---|
| P00 | 17 | 1 |
| P01 | 21 | 1, 4 |
| P02 | 15 | 3, 4 |
| P03 | 41 | 1, 3, 4, 5, 6 |
| P04 | 105 | 1, 2, 3, 4, 5, 6 |
| P05 | 132 | 1, 2, 3, 4, 5, 6, 7, 8 |
| P06 | 132 | 1, 2, 3, 4, 5, 6, 7, 8 |
| P07 | 113 | 1, 2, 3, 5, 7 |
| P08 | 96 | 2, 3, 5, 7, 8, 9 |
| P09 | 93 | 2, 5, 7, 8, 9 |
| P10 | 127 | 1, 2, 3, 7, 8, 9 |
| P11 | 137 | 1, 2, 3, 6, 7, 8, 9, 10 |
| P12 | 137 | 1, 2, 3, 6, 7, 8, 9, 10 |
| P13 | 136 | 1, 2, 3, 6, 7, 8, 9, 10 |
| P14 | 96 | 2, 4, 6, 7, 8 |
| P15 | 95 | 2, 4, 7, 8 |
| P16 | 0 | none |

## Import workflow

1. Use PROJECT → Import XM tracker score… (Ctrl+Shift+M).
2. WAVEFORMING extracts the order cues and displays TRACKER markers on the timeline.
3. The timeline tempo is set to the module's initial BPM.
4. Add a TRACKER MATRIX layer from the generator selector.
5. Import the corresponding WAV/FLAC mix or stems for playback and continuous
   audio-reactive response.
6. Save the .wfp project. The compact tracker score (note/instrument maps and cue
   timing) is embedded in the project, so offline export does not need to reopen
   the original XM file.

The importer replaces only previous TRACKER markers; user-created MARKER and
SECTION entries remain intact. Tracker cue markers remain seekable even before
an audio file has been loaded.

## TRACKER MATRIX

The instrument draws the current pattern as a 2D channel/row matrix:

- columns represent tracker channels;
- rows represent pattern rows;
- note pitch affects each note cell's height;
- instrument assignment selects a restrained ink colour;
- the playhead advances through the pattern using the cue's row progress;
- the same packet is supplied to live preview and deterministic offline rendering.

The TRACKER MATRIX is available in the generator selector, but is excluded from
AUTO COMPOSE and automatic variation until tracker data is imported.

## Acceptance checks

- XM header, order list, pattern event maps and cue duration are parsed without
  decoding sample payloads.
- Empty packed patterns are accepted.
- Fxx speed changes affect subsequent row timing.
- Invalid/truncated pattern data is rejected.
- Tracker score serialisation round-trips to the same cue packet used in preview.
- The matrix renders with or without audio feature frames.
- Existing project files without tracker data continue to load.

## Next

M8 — Tracker event modulation is implemented in
[docs/M8_TRACKER_EVENT_MODULATION.md](M8_TRACKER_EVENT_MODULATION.md), and M9 —
Perceptual scene director is implemented in
[docs/M9_PERCEPTUAL_SCENE_DIRECTOR.md](M9_PERCEPTUAL_SCENE_DIRECTOR.md). M10 is the
scene recipe and transition system: reusable structural roles, transition curves,
seed locking and beat/bar-aware scene changes.
