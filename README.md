# eli_lab — WAVEFORMING

A tracker-first visual composition instrument for IDM and experimental electronic music. XM/MOD-style musical structure is a first-class visual score: every tracker channel keeps its identity and drives a persistent visual voice. Audio stems are optional for playback, reference and complementary timbral analysis.

## Multichannel, generative direction and GPU preview

The integrated branch combines the M5 timeline and deterministic export workflow with the multichannel evolution implementation:

- Up to **64 audio sources**, multi-file and recursive folder import, stable folder groups, and individual or group-based visual routing.
- Hybrid audio storage: stems larger than 96 MB use a background ring reader when their rate matches the output device; shorter or rate-mismatched stems are decoded/resampled before playback. The audio callback performs no disk I/O and reuses per-track stream buffers.
- A temporal feature bus derives smoothed track, folder-group and master descriptors, onset density, novelty and transient events. Pairwise correlation is limited to 12 sources; analysis cadence reduces from 8 Hz to 6 Hz or 3 Hz as sessions grow.
- MANUAL / SEMI-AUTO / AUTO composition director modes are wired into live preview and offline export, including audio-informed motion/complexity, deterministic glitch/accent impulses, hysteresis and cooldown-limited structural variation.
- OpenGL 3.3 layer blending for interactive preview when a compatible context is available, with Pillow retained for temporal feedback and CPU fallback. The INTERFERENCE FIELD now has an opt-in GLSL fragment-shader implementation when it uses identity transforms, no paper pass and supported ink palettes; unsupported layer configurations continue through the CPU renderer. Other generator families and paper-relief preparation remain CPU-side. AUTO COMPOSE lays up to eight channels into a spatial grid rather than stacking them at the canvas centre.
- Screen plates and layout profiles are loaded from `resources/screens` and `resources/layout`. The native canvas remains 1920×1440; the seven pre-designed plates use the 1322×1058 frame, while legacy SCREEN 1 / SCREEN 2 masks remain unchanged. The two PSD-to-HTML artwork exports are separately extracted to `resources/layout/artwork`: deduplicated PNG parts plus exact layer/group geometry; their HTML sources are retained until visual reconstruction is verified.
- The M5 latest-frame preview worker, timeline automation, project save/load and deterministic offline MP4 export remain in place. GPU-native instruments and device-specific Windows performance still require separate validation.

## Launch from PyCharm

The application entry point is **main.py in the repository root**.

1. Open the repository folder in PyCharm.
2. Set the project interpreter to the repository's .venv Python interpreter (Python 3.12, 64-bit recommended).
3. Select the shared **WAVEFORMING** run configuration.
4. Press **Run** (Shift+F10).

The shared run configuration launches $PROJECT_DIR$/main.py with $PROJECT_DIR$ as its working directory, so the screen and logo assets resolve independently of PyCharm's current working directory.

## Launch from a terminal

    py -3.12 -m venv .venv
    .venv\Scripts\activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python main.py

The repository's GitHub Actions workflow performs a Python compile check, validates the OpenGL shader source, and smoke-tests the XM-to-channel-to-visual-instrument path. The previous pytest suite was intentionally removed during the architecture cleanup.

## M1 — Synchronized audio and analysis

- Up to 64 sources share one output clock and can be loaded individually or recursively by folder, removed, muted, soloed, panned and gain-adjusted independently.
- Sources with different sample rates are converted to the selected output device rate.
- Shared play/pause/stop, seek and loop transport.
- Per-source RMS, peak, FFT spectrum, logarithmic bands, spectral centroid, rolloff, bandwidth, flatness, entropy, spectral flux, zero-crossing rate, stereo width and crest factor.
- Pairwise zero-lag correlation between active source blocks when 12 or fewer tracks are active; large sessions skip the quadratic correlation pass.
- FFT and descriptor calculations run on a dedicated analysis thread, outside the PortAudio output callback.

## M2 — Mathematical visual generators

Ten transparent generators are available:

- **Interference Field** — coupled nonlinear fields and interference contours.
- **Phase Orbit** — parametric orbital curves driven by energy and source correlation.
- **Particle Field** — deterministic particles warped by spectral and cross-source features.
- **Cellular System** — evolving cellular structures with band-dependent forcing and transient-driven excitation.
- **Phase Lattice** — phase-displaced grid geometry.
- **Reaction Diffusion** — Gray–Scott-like chemical patterns with audio-modulated feed/kill parameters.
- **Lorenz Attractor** — a continuously integrated chaotic trajectory.
- **Spectral Topography** — contour surfaces driven by the log-band spectrum.
- **Phyllotaxis** — golden-angle point structures with radial spectral modulation.
- **Mobius Field** — a twisted parametric surface.

Generator parameters include complexity, motion and audio response. Low, mid and high spectral energy, transient activity, source correlation and stereo width are available to the visual metric layer.

## M3 — Advanced compositor

- Independent layer stack with visibility, duplicate, remove and ordering. Stateful simulations (cellular, reaction-diffusion and Lorenz) keep separate state per layer.
- Per-layer generator, opacity, blend mode, transform, rotation and scale.
- Frame, inset, ellipse and full-canvas masks.
- Per-layer pass source and pass operation.
- **Paper Relief** combines the repository's displacement map, normal map (with derived-normal fallback) and paper texture to displace and shade generated pixels against the paper surface.
- Separate displacement, normal-lighting and texture pass operations.
- Temporal feedback with return mix, decay and drift controls.
- Alpha-aware blend modes: Normal, Add, Screen, Multiply, Difference, Overlay, Lighten and Darken.

The screen templates use explicit normalized printable-area boxes. FRAME mode clips generated geometry to the corresponding content region so the registration marks, outer frame and paper annotations remain visible. FULL mode is available when a layer is intentionally meant to cover the whole plate.

## M4 — Generative composition and performance

The composition system now adds geometric and pseudo-3D structures designed for layered print-like MV plates:

- **Geometric Plate** — offset paper planes, registration geometry, technical bars and editorial block arrangements.
- **Geometric Field** — superformula contours, orbital arcs, radial constructions and spectral nodes.
- **Axonometric Field** — pseudo-3D isometric prisms with band-driven extrusion.
- **Polyhedral Field** — rotating wireframe polyhedra with channel-sensitive orientation.

Each layer can bind to **MIX / ALL** or one independent audio source. A restrained three-ink editorial palette (dusty cobalt, aged yellow and violet, with tonal variants) distinguishes channels; white paper automatically uses darker inks, and monochrome scopes invert to dark ink.

**AUTO COMPOSE** builds a multi-layer layout from currently loaded sources. **VARIATE** changes its structure while keeping channel assignments; optional **AUTO VARIATE** performs a variation every 12 seconds during playback.

Preview performance changes:

- The default ECO preview is **320 × 240 at 5 fps**; LOW (360 × 270 / 6 fps) and BALANCED (480 × 360 / 8 fps) are selectable. The native project remains **1920 × 1440**. A dedicated worker renders the preview and drops stale pending frames.
- Blend operations work on each layer's clipped rectangle rather than repeatedly converting the full canvas to float arrays.
- Frame masks, screen plates, resized pass maps, coordinate grids and paper-relief derivatives are cached.
- Paper relief remains active but its height, normal-lighting and texture fields are prepared once per layer-size/pass combination.
- Dedicated shader-effect controls have been removed.
- Automatic layer rotations are limited to 0°, 90°, 180° or 270°; identity transforms avoid unnecessary image resampling.
- Reaction Diffusion renders the activator field and iso-contours only, rather than treating its near-uniform background as visible ink.
- Cellular and reaction-diffusion stencils use padded neighbour arrays instead of repeated full-frame roll allocations.
- Live spectral analysis is throttled to 8 updates per second and analyses a complete FFT-sized PCM window at each update, so dropped stale queue items cannot join non-contiguous audio.

The automatic variation is intentionally a composition jump, not a crossfade. Beat/bar-aware scene transitions and GPU rendering remain future work.

## M5 — Timeline, automation and deterministic rendering

- Clickable timeline ruler with playhead, beat/bar guides, named markers and section boundaries.
- BPM control and optional beat snapping; timeline time remains anchored to the audio clock.
- Three automation lanes: Complexity, Motion and Audio Response. Enable RECORD AUTOMATION and adjust a global generator control during playback to record keyframes.
- Linear interpolation by default, with HOLD and SMOOTH interpolation available in the timeline model.
- Save/open .wfp project files containing audio file paths, source controls, layers, settings, paper template, feedback, markers and automation. Audio files are referenced rather than embedded.
- Export deterministic MP4 at 1920×1440 and 15/24/25/30 fps. Frames are rendered from the same compositor and automation graph at fixed timestamps, with audio features analysed from PCM at each frame.
- Export resolves FFmpeg from PATH, FFMPEG_BINARY, common Windows install locations or the bundled imageio-ffmpeg executable. The renderer uses H.264/AAC and pauses live playback while exporting to reserve CPU resources. It analyses trailing FFT windows at up to 8 Hz while rendering at the selected frame rate, and only replaces the output after a successful encode.

The supplied target machine is an AMD Ryzen AI 5 330 at 2.00 GHz with Radeon 820M integrated graphics (512 MB reported graphics memory) and 16 GB RAM. The compositor is still CPU-based, so M5 defaults to an **ECO 5 fps 320×240** preview, with selectable LOW and BALANCED profiles, a one-item latest-frame worker queue and **8 Hz** audio feature analysis. Preview and analysis threads run below normal thread priority where the operating system allows it. A slow preview frame cannot block the audio callback or the UI. Full-resolution offline rendering is independent of preview quality and is intentionally not real-time.

See [docs/M5_TIMELINE_RENDERING.md](docs/M5_TIMELINE_RENDERING.md) for implementation details, export assumptions and acceptance checks.

## M6 — XM as a visual score

- **XM is not imported as audio.** Use **+ XM** for a tracker score, **+ AUDIO** for optional sound/stems, or **+ FOLDER** to discover both separately.
- The importer extracts all tracker channels, patterns, note rows, carried instrument assignments, instrument/sample names, volume-column values and effect-column commands. Sample payload bytes are skipped; they are not decoded for visual use.
- The channel inspector lists every XM channel, its sample identity, note count and silent/active state.
- **TRACKER ENSEMBLE** renders the actual channel voices together as one bounded compositional instrument. Channel number is a stable spatial identity; instrument/sample, pitch, note age, volume, recent hits and tracker commands modulate the voice.
- An XM score can be played as a standalone visual transport: play, pause, seek and loop do not require WAV/FLAC input.
- Saving a .wfp project embeds tracker structure and channel metadata. Tracker-only MP4 export is supported without a dummy audio stream.

See [docs/M6_XM_TRACKER_WORKFLOW.md](docs/M6_XM_TRACKER_WORKFLOW.md) and [docs/Guide/WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md](docs/Guide/WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md).

## M7 — Render profiling and efficient offline export

- Preview defaults to BALANCED at **480×360 / 8 FPS**, with ECO and LOW retained.
- The preview header exposes measured scene/frame time and per-layer cost.
- Screen plates are composited behind generated visuals in live CPU, OpenGL and offline paths.
- Offline export has three internal render profiles: PERFORMANCE (640×480), BALANCED (960×720) and FULL (1920×1440). FFmpeg upscales reduced internal renders to the fixed **1920×1440** delivery canvas.
- XM-only export produces a silent video stream; with audio stems imported, the same export path adds the mixed AAC soundtrack.
- At BALANCED, the generator/compositor handles one quarter of the pixels per frame compared with FULL; this is a pixel-work reduction, not a claim of a measured 4× speedup.
- FPS is independent of quality: for a 133.18 s XM, 30 FPS is about 3,996 frames while 15 FPS is about 1,998. Use 15 FPS for quick drafts and 24 FPS for general MV review.

See [docs/M7_RENDER_PROFILE.md](docs/M7_RENDER_PROFILE.md).

## M8 — Tracker event modulation

- The active XM cue exposes current row index, row note count/activity, pattern density, cue transition strength and pattern reprise state.
- Tracker note activity and order transitions modulate the shared visual metrics (energy, transient response and pitch centroid) used by existing generative instruments.
- Audio-derived metrics remain active and are blended conservatively with the tracker score; tracker-only visual preview is also supported.
- The same cue resolver drives live preview and deterministic offline export.

See [docs/M8_TRACKER_EVENT_MODULATION.md](docs/M8_TRACKER_EVENT_MODULATION.md).

## M9 — Perceptual scene director

- The existing audio-informed composition director now consumes tracker transition, row activity, pattern density and reprise signals.
- New pattern boundaries can nominate EMERGENCE; returns to earlier patterns can nominate INSTABILITY, with existing hysteresis preserved.
- Tracker cues briefly modulate motion, complexity, accent and glitch response; AUTO mode can request bounded seeded variations subject to the existing cooldown.
- Live preview and offline export now attach tracker cues before director evaluation, keeping the decision path aligned.

See [docs/M9_PERCEPTUAL_SCENE_DIRECTOR.md](docs/M9_PERCEPTUAL_SCENE_DIRECTOR.md).

## M10 — Tracker-first architecture

The next architectural direction is a score/scene model based on the IDM Visual Instrument guide: VisualScore, stable voice identities, persistent VisualScene/VisualObject state, explicit MappingRules, cue/phrase transitions, deterministic snapshots and a live performance override layer. The current tracker ensemble is the first executable slice, not the complete scene-graph system.

See [docs/Guide/WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md](docs/Guide/WAVEFORMING_TRACKER_FIRST_ARCHITECTURE.md).

## M11 — VisualScore and persistent scene graph

- Introduces typed `VisualObject`, `VisualScene`, `VisualRelationship`, `VisualScore` and timed `VisualScoreCue` records.
- Existing renderer layers gain persistent object identities linked by `layer_id`; IDs survive layer property changes and reorder operations.
- Removed layers archive their objects rather than silently reusing visual identity.
- The scene stores attention roles, source bindings, XM channel relationships, relationships, spatial-environment placeholders and canonical layer order.
- XM order/pattern boundaries become explicit `VisualScore` cues linked to the imported score and scene.
- The scene's canonical order is consumed by live CPU/OpenGL preview and offline export.
- Project format version 2 persists scene and score data. Version-1 projects migrate by rebuilding the scene from their existing layers and embedded tracker data.
- `VisualLayer` remains the executable rendering unit; multi-layer logical objects, transition execution and MappingRule evaluation are later steps.

See [docs/M11_VISUAL_SCORE_SCENE_GRAPH.md](docs/M11_VISUAL_SCORE_SCENE_GRAPH.md).

## M12 — Scene state machine and transition contracts

- Adds explicit validated scene states: INACTIVE, PREPARED, ENTERING, ACTIVE, HELD, EXITING, ARCHIVED and SAFE_FALLBACK.
- Adds serializable transition contracts for cut, dissolve, morph, assembly, erosion, mask reveal, displacement, camera, palette, attention transfer, temporal echo, negative, split/merge and hard reset.
- Contracts define duration, trigger metadata, easing, preparation/transformation/establishment proportions, object preservation/discard, interruption and outgoing-scene policies.
- Separates transition proposal from commit. Proposing validates source/target scenes and object references without mutating scene state.
- A deterministic, absolute-time controller samples progress and blend weights, and applies completion/cancel/hold/archive lifecycle decisions.
- Renderer effects are added in M14: dissolve/crossfade and cut use the shared outgoing/incoming scene-pair contract; morph, assembly, erosion and other families remain future implementations.

See [docs/M12_SCENE_STATE_MACHINE_TRANSITIONS.md](docs/M12_SCENE_STATE_MACHINE_TRANSITIONS.md).

## M13 — Multi-scene project state and score-cue integration

- Adds a persistent `VisualProject` collection containing multiple scene graphs, an active-scene ID, independent renderer-layer snapshots, transition contracts and explicit XM cue routes.
- Scene selection restores its own layer stack. Scene duplication regenerates scene/layer/object identities, remaps graph relationships and retains source lineage.
- The scene panel supports creating and duplicating scenes, selecting a transition target/family/duration, committing a manual M12 transition, and routing the current XM order/pattern cue to a target scene.
- Only explicitly routed XM cues trigger scene changes. Cue crossings are queued while another transition is active, validated through the M12 proposal/commit controller, and sampled on the live show clock. Cue scanning also resets on audio/XM loop wraps, so routed opening cues are eligible on each pass.
- Offline export also resolves cue routes against score time and uses the same transition controller for deterministic scene activation.
- `.wfp` format version 3 persists the scene collection. Existing M11/M12 single-scene projects migrate from their saved `visual_scene` and `layers` records.
- Live/offline compositor results receive resolved project and lifecycle metadata, including active scene, transition sample and queued cues.

M13 established the project-level scene and cue-routing model. Renderer-side dissolve/crossfade is now implemented in M14; morph, assembly, erosion and temporal echo remain future effects.

See [docs/M13_MULTI_SCENE_PROJECT_SCORE_CUES.md](docs/M13_MULTI_SCENE_PROJECT_SCORE_CUES.md).

## M14 — Renderer-side scene pairs and dissolve

- Adds a serializable `ScenePairRenderContract` with outgoing/incoming scene graphs, their independent layer snapshots, transition phase/progress/weights and resolved project metadata.
- A single `ScenePairRenderContract` is built from the M12 controller sample and reused by live preview and offline export.
- `VisualCompositor.render_scene_pair()` uses family-specific rendering: dissolve blends two complete RGBA frames, while morph builds one intermediate object/path scene and renders its continuous background once.
- `dissolve` performs a deterministic pixel crossfade; `cut` switches at completion; `morph` interpolates explicitly-corresponding `VisualObject`s, including point-by-point generator paths for Phase Orbit, Phase Lattice, Geometric Field, Geometric Plate, Axonometric Field, Polyhedral Field and Mobius Field. Unmatched objects and paths fade independently. Assembly, erosion and other families remain lifecycle-only until implemented.
- Temporal feedback is applied once to the final blended frame. The pair-render profile records both scene render timings and transition weights.
- Live preview retains generator state for both scene layer sets and sends a completed CPU frame to the canvas while a pair is active. The normal OpenGL single-scene path resumes after transition completion.
- Offline export uses the same pair contract and blend function, keeping score-cue transition output aligned with the live render path.

M14 currently implements dissolve/cut and object-aware morphing with generator-level path deformation for the supported line/edge families. Raster-only generators retain the transform/material fallback. Path splitting/merging, authored anchors, assembly, erosion, mask reveal, displacement and temporal echo remain future effects.

See [docs/M14_RENDERER_SCENE_PAIR_CROSSFADE.md](docs/M14_RENDERER_SCENE_PAIR_CROSSFADE.md).
## Canvas and performance

- Project coordinate system: **1920 × 1440** (4:3).
- Interactive preview defaults to **480 × 360** (BALANCED, 8 FPS), with **320 × 240** (ECO, 5 FPS) and **360 × 270** (LOW, 6 FPS) options; all are scaled into the application window without changing the 4:3 project aspect ratio.
- Generator simulation and paper-relief preparation remain CPU-side; OpenGL handles per-layer preview blending when available, with a CPU compositor fallback. This is not yet a fully GPU-native generator pipeline.
- Offline rendering uses FFmpeg from PATH; the preview remains CPU/Pillow/NumPy based. Printable-area masks scale with the selected render size, and completed MP4s replace the destination atomically.

## Requirements and limitations

Python 3.12 (64-bit) recommended. Playback requires an available sounddevice/PortAudio output device. MP4 export uses the bundled imageio-ffmpeg executable when no system FFmpeg is configured; FFMPEG_BINARY can point to a custom ffmpeg.exe.

- Long device-rate-matched stems above 96 MB are streamed from disk. Rate-mismatched stems and offline-export snapshots still require memory; large offline exports can therefore need substantial RAM.
- MP3 support depends on the installed libsndfile build. WAV, FLAC, AIFF and OGG are preferred.
- The frame-region coordinates are stored per screen template in engine/visual/assets.py and can be tuned if a guide design changes.
