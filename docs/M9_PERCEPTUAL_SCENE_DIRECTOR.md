# M9 — Perceptual scene director

## Status

Implemented as an extension of the existing audio-informed CompositionDirector.
Tracker cues and audio features now participate in one shared scene-state decision.

## Inputs

The director reads the tracker cue already attached to the visual frame packet:

- cue transition strength with a short fade over the opening fifth of an order;
- active-row note activity;
- normalized pattern density;
- pattern reprise state;
- current order and pattern identifiers.

It continues to read the audio feature bus master descriptors:

- energy;
- density;
- novelty;
- onset strength.

The audio feature bus remains the continuous timbral source. Tracker values provide
structural events and can keep the director meaningful when previewing a tracker
without audio feature frames.

## State decisions

A sufficiently strong tracker transition with meaningful row activity or pattern
density can nominate a structural state:

- a new pattern transition nominates **EMERGENCE**;
- a transition into a previously seen pattern nominates **INSTABILITY**.

The existing hysteresis remains in place. A candidate state must persist for the
configured hold interval (or receive a strong onset) before the active state changes.
Audio novelty/onsets can independently nominate the existing state set:
DORMANT, EMERGENCE, DEVELOPMENT, INSTABILITY and RELEASE.

## Scene response

The director produces one bounded output for the frame:

- motion and complexity scales use audio energy/density/novelty plus tracker row
  activity and the decaying transition envelope;
- accent amount combines audio onset accents with a brief tracker-boundary accent;
- glitch amount remains restrained and follows instability/novelty;
- the output also exposes tracker transition, activity, reprise, order and pattern
  for diagnostics and future scene recipes.

Manual mode keeps director multipliers/effects neutral. Semi-auto mode applies
restrained parameter response but never mutates the layer stack. Auto mode may
request a seeded composition variation when the existing state/novelty thresholds
and variation cooldown are satisfied. Variation retains the source routing and
existing layer-count bounds.

## Preview/export parity

- Live preview now attaches the active tracker cue before calling the director.
- Offline export already attaches the same cue before calling the director.
- Both paths therefore use the same tracker-aware state evaluation at the same
  playhead timestamp.
- The director remains deterministic for the same ordered packet sequence and mode.

## Limitations

- Variation remains a discrete structural mutation; there is no crossfade, morph
  or depth-preserving transfer between scene graphs yet.
- Beat/bar-aware transitions are limited by the timing information currently
  imported from the XM. Bxx, Dxx and E6x flow-control effects are detected but
  not simulated.
- The director does not autonomously invent arbitrary scene recipes; it works with
  the current editable layer stack and the existing bounded variation routine.

## Acceptance checks

1. Tracker-only cues can nominate EMERGENCE or INSTABILITY without audio features.
2. Audio-only projects retain the original director behavior.
3. Tracker transitions influence motion/complexity and accent response in
   SEMI-AUTO mode without mutating the layer stack.
4. AUTO mode can request a variation at a strong tracker boundary, subject to the
   existing cooldown.
5. MANUAL mode keeps director multipliers/effects neutral.
6. Live preview and offline export pass tracker cues into the director before
   computing the visual packet.

## Next

M10 — Scene recipes and transition system: introduce reusable structural roles,
beat/bar-aware cue boundaries, crossfade/morph strategies and per-transition
seed locking without regenerating unrelated layers.
