# M7 — Balanced preview and render observability

## Status

Initial profiling and low-risk performance improvements implemented.

## Live render profile

The preview worker reports:

- scene preparation time;
- final CPU composition time;
- total measured CPU frame time;
- visible layer count;
- per-layer render duration and rendering backend (CPU or OpenGL instrument spec).

The preview header displays the latest measured time. Hovering the readout shows
per-layer details, making an expensive generator or layer configuration visible
before attempting to solve it with a new rendering backend.

For the OpenGL scene path, the current profile measures scene preparation and
instrument-spec generation. It does not yet include the later Qt/OpenGL draw and
GPU completion time; this is not a complete GPU frame-time measurement.

## Preview defaults

The default profile is BALANCED: 480 × 360 at an 8 FPS request cadence. ECO (320 ×
240 at 5 FPS) and LOW (360 × 270 at 6 FPS) remain selectable. The project/export
canvas is still 1920 × 1440 and is not reduced by preview settings.

The cadence is a request interval, not a guarantee that all frames complete at
that rate. The preview worker continues to use a one-item latest-frame queue.

## Per-frame feature reuse

Visual metrics were previously reconstructed separately by each generator layer,
even when several layers referenced the same feature packet and source route. The
generator bank now caches the derived metrics once per packet identity and source
route. The packet is retained for the duration of that frame cache to avoid object
identity reuse.

The cache is intentionally frame-scoped. New audio/tracker packets trigger a
fresh descriptor build; no stale feature values are carried between frames.

## What this milestone does not claim

- It does not make every generator GPU-native.
- It does not guarantee 8 FPS on every Windows machine or every layer stack.
- It does not change the deterministic offline export resolution or quality.
- It does not introduce asynchronous work inside the audio callback.
- It does not yet cache dynamic generator images across frames. Dynamic generators
  still depend on time/audio state; static-layer caching needs explicit invalidation
  semantics and will be addressed after profiling identifies candidates.

## Validation plan

1. Compare one-, three- and seven-layer scenes at ECO, LOW and BALANCED sizes.
2. Record median and 95th-percentile frame time per generator.
3. Identify layers where generator work dominates versus palette/pass/transform work.
4. Measure the actual OpenGL draw path separately from CPU scene preparation.
5. Use those measurements to choose the next optimisation (static layer cache,
   lower simulation cadence, vectorised generator, or GPU implementation).
