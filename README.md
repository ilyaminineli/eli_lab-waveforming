# eli_lab — WAVEFORMING

An experimental audio-reactive visual composition workstation for abstract IDM-style motion graphics. The visual system is built from sound descriptors, mathematical generators and layered compositing—not standard equalizer displays.

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

For the test dependencies:

    pip install -r requirements-dev.txt
    python -m pytest -q

The repository includes `pytest.ini` and `tests/conftest.py` so imports such as `engine.audio` resolve from the repository root in terminal and PyCharm test runs.

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

## M6 — XM tracker-driven visuals

- Import XM tracker scores from PROJECT → Import XM tracker score… (Ctrl+Shift+M).
- Extract order/pattern cues, note rows, instrument assignments and active channels.
- Set timeline tempo from the module and add independently styled TRACKER order markers.
- Save tracker cue/note maps inside the .wfp project; live preview and offline export use the same cue packet.
- **TRACKER MATRIX** visual instrument renders channel/row note activity with instrument-coloured cells and a pattern playhead.
- The importer reads metadata only; it does not play XM samples. Import the corresponding audio separately for playback and spectral response.
- Fxx speed/tempo changes are included in cue timing. Bxx/Dxx/E6x control-flow commands are not yet simulated and are flagged as approximate timing.

See [docs/M6_XM_TRACKER_WORKFLOW.md](docs/M6_XM_TRACKER_WORKFLOW.md).

## M8 — Tracker event modulation

- The active XM cue exposes current row index, row note count/activity, pattern density, cue transition strength and pattern reprise state.
- Tracker note activity and order transitions modulate the shared visual metrics (energy, transient response and pitch centroid) used by existing generative instruments.
- Audio-derived metrics remain active and are blended conservatively with the tracker score; tracker-only visual preview is also supported.
- The same cue resolver drives live preview and deterministic offline export.

See [docs/M8_TRACKER_EVENT_MODULATION.md](docs/M8_TRACKER_EVENT_MODULATION.md).

## M7 — Balanced preview and render profiling

- Default preview is BALANCED at **480×360 / 8 FPS**, with ECO and LOW profiles retained.
- The preview header displays measured scene/frame time; hover to inspect individual layer costs.
- Generator feature metrics are cached per frame and source route, avoiding repeated aggregation when multiple layers share the same audio feature packet.
- Profiling distinguishes CPU scene preparation from final CPU composition. The OpenGL profile currently measures scene preparation, not completed GPU draw time.
- These measurements are intended to guide further optimisation; no universal FPS guarantee is implied.

See [docs/M7_RENDER_PROFILE.md](docs/M7_RENDER_PROFILE.md).

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
