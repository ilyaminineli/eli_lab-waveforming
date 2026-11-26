# M8 — Tracker event modulation and cue transitions

## Status

Implemented: tracker row activity and order-level transition/reprise signals are
shared with the existing visual metric system in live preview and offline export.

## Goal

Use the XM score as a structural and event-level source for generative visuals.
Audio analysis remains the continuous timbral layer; tracker data supplies exact
note rows, pattern density, channel activity and repeated-motif context.

## Cue data

Each serialised order cue includes:

- note and instrument matrices indexed by pattern row and tracker channel;
- row note counts and active channel/instrument summaries;
- normalized pattern density (note events divided by pattern rows × channel count);
- cue transition strength, derived from pattern change, note-density difference
  and active-channel difference;
- a pattern reprise flag when the pattern has appeared earlier in the order list.

The active cue packet additionally reports:

- current row index and fractional progress through that row;
- active row note count and row activity (active notes / module channels);
- pattern progress, transition strength and reprise status.

The transition strength is deterministic. It decays over the first 20% of the
order position so it acts as a scene-change impulse rather than a permanent
brightness multiplier.

## Visual metric mapping

The existing `VisualMetrics` object combines tracker and audio signals:

- tracker row activity contributes to visual energy and transient response;
- normalized pattern density contributes a slower structural energy component;
- order transition contributes a short accent envelope;
- pattern reprise adds a small, repeatable energy bias;
- the mean pitch of the active tracker row contributes to spectral centroid.

When audio is loaded, audio descriptors remain present and tracker influence is
blended conservatively into energy, transient and centroid. With tracker data but
no audio frames, the tracker signals still drive the generators. This lets the
user inspect and audition the visual score before loading a final WAV mix.

No generator is forced to render another visual layer. The existing Phase Orbit,
Interference Field, Particle Field, geometry and other instruments receive these
signals through the common metric packet. TRACKER MATRIX remains the dedicated
pattern/channel overview.

## Determinism and performance

- Preview and offline export call the same `tracker_packet_at` cue resolver.
- Cue data is serialised in the .wfp project; export does not need to reopen the XM.
- Tracker cue evaluation is a small lookup over the order list and row matrix.
- Derived visual metrics are still cached once per feature packet and source route.
- No extra thread, sample decoder or GPU library is introduced.

## Limitations

- Bxx order jumps, Dxx pattern breaks and E6x pattern loops are detected and
  surfaced as approximate timing, but playback flow is not simulated yet.
- The XM importer is not an audio player; import WAV/FLAC separately for audio.
- Pattern reprise is order-list based. It does not infer melodic similarity between
  different pattern numbers.

## Acceptance checks

1. A cue packet identifies the active row and row-level note activity.
2. Repeated pattern IDs are flagged as reprises.
3. Pattern and channel-activity changes create deterministic transition strength.
4. Tracker-only projects produce non-zero visual metrics when note rows are active.
5. Audio and tracker signals coexist in one metric packet without replacing audio
   analysis.
6. Live preview and offline export resolve identical cue packets at the same time.

## Next

M9 — Perceptual scene director: convert transition/reprise/activity features into
scene-level decisions, controlled visual mutations and beat/bar-aware transitions.
