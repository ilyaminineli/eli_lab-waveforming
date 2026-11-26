# M7 — Balanced preview and render observability

## Status

Initial profiling and low-risk performance improvements implemented.

## Screen and layer compositing order

Screen plates are the visual canvas background, not a foreground overlay. The live
CPU compositor, OpenGL scene compositor and offline renderer now all composite in
the same order:

1. black canvas base and screen artwork;
2. generated visual layers, in layer-stack order;
3. temporal feedback and final output handling.

The previous preview implementation appended the screen plate after generated
layers, and the CPU/offline paths alpha-composited it after the generated stack.
Opaque grain/registration artwork therefore concealed the generators. The corrected
ordering keeps the screen material visible underneath the generated ink.

## Offline export resolution profiles

Offline MP4 export accepts three internal render resolutions while keeping the
output/delivery canvas fixed at 1920 × 1440:

| Profile | Internal render | Pixels per frame | Relative to FULL |
|---|---:|---:|---:|
| PERFORMANCE | 640 × 480 | 307,200 | 1/9 |
| BALANCED | 960 × 720 | 691,200 | 1/4 |
| FULL | 1920 × 1440 | 2,764,800 | 1× |

At 4,000 frames these internal canvases represent approximately 1.23B, 2.76B
and 11.06B pixels respectively, before accounting for layers, masks, transformations,
feedback and intermediate buffers. The reduced profiles perform generator and
compositor work at the smaller resolution; FFmpeg scales the frame stream to the
fixed delivery dimensions during encoding.

These are pixel-work ratios, not measured elapsed-time speedups. CPU-side Python
generators, per-layer processing, cache misses, memory traffic and encoding may
dominate differently on different computers. The profile choice therefore remains
explicit, with FULL available when native-resolution detail is required.

Frame rate is a separate control from internal render resolution. For the 133.18 s
`total fvckery.xm` score, 30 FPS requires approximately 3,996 rendered frames;
15 FPS requires approximately 1,998 frames. Selecting 15 FPS therefore halves the
number of visual evaluations, while PERFORMANCE/BALANCED reduces pixel work per
evaluation. Use 15 FPS for quick drafts and motion checks, 24 FPS for general MV
review, and 30 FPS only where the extra temporal resolution is useful.

## Tracker-only export

- XM visual sessions can be exported without any audio sources.
- The XM order/row clock provides the timeline duration and cue data.
- No audio analyzer, dummy PCM or silent placeholder track is constructed for
  tracker-only export.
- FFmpeg receives video-only input and produces a silent MP4.
- When audio sources are present, the same renderer creates the mix and adds AAC
  audio to the MP4.

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
- It does not claim a measured 3×/4×/9× elapsed-time speedup from the pixel ratios.
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
