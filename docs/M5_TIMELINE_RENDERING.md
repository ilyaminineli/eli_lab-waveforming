# M5 — Timeline, Automation and Deterministic Rendering

## Goal

M5 makes a WAVEFORMING composition editable over time and exportable without depending on real-time preview speed. Playback, preview and offline rendering have separate responsibilities so a slow frame cannot block the audio output callback or the Qt interface.

## M5.1 — Timeline

Implemented:

- A time ruler with bar guides derived from BPM and beats-per-bar.
- Click-to-seek on the timeline and a playhead that follows the shared audio clock.
- Named marker and section-boundary events.
- Optional beat snapping when adding markers or sections.
- Marker deletion near the current playhead.
- BPM control (20–300) with 4/4 as the default time signature.

The timeline stores time in seconds. BPM affects beat/bar guides and snapping, not the underlying audio clock.

## M5.2 — Parameter automation

Implemented automation lanes:

- Generator Complexity
- Generator Motion
- Audio Response

When RECORD AUTOMATION is enabled during playback, changes to the matching generator control are recorded at the current playhead time. The timeline evaluates each lane with linear interpolation by default. HOLD/STEP and SMOOTH interpolation are supported by the data model.

The same evaluated settings are used in the interactive preview and deterministic offline render.

## M5.3 — Project files

Implemented .wfp JSON project save/load:

- Source file paths and each source's gain, pan, mute, solo and analysis state.
- Layer stack, per-layer source routing, masks, transforms, passes and blend operations.
- Global generator settings and deterministic seed.
- Selected paper template and feedback parameters.
- Timeline BPM, markers, sections and automation lanes.

Media is referenced by its absolute file path; audio is not embedded in the project. When a source is moved, WAVEFORMING reports the unavailable path when opening the project.

## M5.4 — Deterministic offline rendering

Implemented MP4 export:

- Native composition resolution: **1920×1440**.
- User-selectable output rate: 15, 24, 25 or 30 fps.
- Audio features are analysed at each exact video frame timestamp from the source PCM buffers.
- Generator seeds, layer order, automation evaluation and the compositor graph are fixed for the render.
- A project audio mix is written block-by-block to a temporary WAV, then muxed with RGBA frames through FFmpeg.
- Export runs in a worker thread with progress reporting and cancellation.
- Live playback is paused when an export starts to preserve CPU time for the offline render.

For a reproducible output, keep the same audio files, layer state, generator seed, timeline/automation, frame rate, resolution and software version. The export is deterministic for that fixed project state; changes to FFmpeg codec builds can still alter compressed MP4 bytes even when rendered frames are identical.

**FFmpeg is an external executable.** WAVEFORMING resolves it from PATH, FFMPEG_BINARY, common Windows package-manager locations or the bundled imageio-ffmpeg package. The application uses H.264 / AAC with the ultrafast x264 preset to reduce encoding overhead. Frame generation itself remains CPU-based.

## M5.5 — Low-power preview and audio scheduling

The current target machine profile supplied for this milestone is:

- AMD Ryzen AI 5 330, reported at 2.00 GHz.
- Integrated AMD Radeon 820M, 512 MB reported graphics memory.
- 16 GB installed RAM (15.3 GB usable), 5600 MT/s.

The renderer is CPU/Pillow/NumPy based; it does not currently use the Radeon GPU. M5 therefore reduces CPU work rather than introducing a GPU dependency:

- Preview defaults to **320×240 at 5 fps (ECO)**; LOW (360×270 at 6 fps) and BALANCED (480×360 at 8 fps) can be selected. The project remains **1920×1440**.
- The selected preview profile is applied at a worker frame boundary; the Qt event loop never reconstructs or renders the compositor.
- A dedicated preview thread owns the compositor. The UI sends immutable snapshots through a one-item latest-frame queue; obsolete pending renders are dropped.
- Preview and live analysis threads are set to below-normal priority where supported, yielding CPU time to the Qt event loop and audio output.
- Preview frames can finish late and still display in sequence; the UI does not wait for rendering.
- Live feature analysis is throttled to **8 updates per second** up to eight sources, **6 Hz** up to sixteen, and **3 Hz** for larger sessions instead of taking and analysing a new FFT window on every 1024-sample audio callback.
- Each analysis snapshot contains a complete FFT-sized PCM window ending at the current playhead. Dropping a stale queue item therefore never causes an FFT to combine non-contiguous audio.
- The audio callback mixes track segments directly into the master buffer instead of allocating an extra zero-filled block per source; the soft limiter skips magnitude arrays unless the mix actually exceeds its ceiling.
- Analysis packets carry a configuration revision; changing FFT settings, or adding/removing a source, invalidates stale packets before they can reach the analyzer. Streamed-source FFT reads do not alter the forward disk-prefetch target.
- Offline rendering has its own compositor instance and does not alter the live preview's state.

These limits are conservative starting points for the supplied low-power CPU, not a promise of a fixed frame rate under every seven-layer composition. The offline 1920×1440 renderer is intentionally slower than real time.

## Acceptance checks

1. A saved project reopens with its source routing, layer stack, paper template, markers and automation intact.
2. A marker can be added at the playhead, snapped to a beat, selected by timeline click/seek, and removed near the playhead.
3. Recording Complexity, Motion or Audio Response while playing creates keyframes on the corresponding lane.
4. Automation produces the same parameter values in preview and export at the same timestamp.
5. Rendering the same fixed project twice produces the same RGBA frame sequence before video encoding.
6. MP4 export includes the project mix and produces a 1920×1440 H.264 video with the selected frame rate.
7. A late preview frame never blocks audio output or the Qt event loop.
8. The preview queue never accumulates an unbounded backlog of obsolete frames.

## Next milestone

**M6 — Composition performance and structural editing**

- Structural recipe library: frame, anchor, orbit, plane stack, polyhedron, typographic module and relief layers.
- Per-layer modulation matrix with smoothing, response curves, quantisation and hold.
- Marker-driven scene changes and beat/bar-aware transitions.
- Cached static-layer output and dirty-region invalidation for preview.
- Optional GPU backend only if profiling proves it helps the supported hardware.
- Render benchmarks and per-layer profiler on the target laptop.


## M5 stability corrections

- Printable-area masks now use the compositor instance's canvas dimensions. The previous preview constant caused an incompatible 480×360 mask during 1920×1440 export.
- Offline analysis now takes the same trailing FFT-sized window ending at each frame timestamp as live analysis; it no longer uses a centred window that shifts audio-reactive content by half an FFT window.
- FFmpeg writes to a temporary MP4 and atomically replaces the destination only after a successful encode. Cancelled or failed exports do not leave a partial file at the requested destination.


## Integration corrections — multichannel application wiring

The current application exposes the engine's 64-source limit in both import and status UI. Multi-file import and recursive folder import use the same path, and folder IDs are persisted with each project source. Long device-rate-matched stems above 96 MB use the ring reader; per-track stream scratch memory is reused in the audio callback.

The screen catalogue resolves resources/screens first and supports the former screens directory as a fallback. The composition director is initialized in the window, its MANUAL / SEMI-AUTO / AUTO selector is saved with the project, and its motion, complexity, glitch and accent values are applied to both preview and offline render.

AUTO COMPOSE uses distinct 2-column or 3-column channel cells (up to eight visually routed sources). Channel variation preserves those cell positions. Export feature analysis is sampled at up to 8 Hz and held between analysis updates, rather than recalculating every track FFT on every video frame.


## Incremental GPU-native generator path

The live OpenGL preview can evaluate INTERFERENCE FIELD directly in a GLSL 3.3 fragment shader. The preview worker passes a compact parameter packet (audio descriptors, generator settings, ink and rectangle) to the canvas instead of rasterizing this compatible layer into a Pillow image and uploading it each frame. This path currently requires FULL or FRAME masks, identity transform, no active paper-relief/displacement/texture pass, a supported editorial/monochrome palette and no director glitch/accent operation. Unsupported combinations intentionally use the existing CPU generator path. The other generators, paper-relief fields and offline render remain CPU-side; a real GPU performance gain must be measured on target hardware before promoting the shader path to a default.

## HTML artwork extraction

The two PSD-to-HTML exports are 1920×1440 static layer compositions. The full version has 23 image layers and the simple version 18; 18 positioned layer instances match and five are full-only. The extraction utility preserves embedded PNGs, DOM draw order, exact top-left rectangles, accumulated group offsets, opacity, CSS blend mode, group hierarchy and nested inline image styles. GitHub Actions regenerates the deduplicated parts and manifest under resources/layout/artwork. This artwork manifest remains separate from the printable-area masks in layout_profiles.json.
