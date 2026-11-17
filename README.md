# eli_lab — WAVEFORMING

An experimental audio-reactive visual composition workstation for abstract IDM-style motion graphics. The visual system is built from sound descriptors, mathematical generators and layered compositing—not standard equalizer displays.

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

- Up to seven sources share one output clock and can be loaded, removed, muted, soloed, panned and gain-adjusted independently.
- Sources with different sample rates are converted to the selected output device rate.
- Shared play/pause/stop, seek and loop transport.
- Per-source RMS, peak, FFT spectrum, logarithmic bands, spectral centroid, rolloff, bandwidth, flatness, entropy, spectral flux, zero-crossing rate, stereo width and crest factor.
- Pairwise zero-lag correlation between active source blocks.
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
- Export requires the FFmpeg executable on PATH. The renderer uses H.264/AAC and pauses live playback while exporting to reserve CPU resources. It analyses trailing FFT windows ending at each frame timestamp and only replaces the chosen output file after a complete successful encode.

The supplied target machine is an AMD Ryzen AI 5 330 at 2.00 GHz with Radeon 820M integrated graphics (512 MB reported graphics memory) and 16 GB RAM. The compositor is still CPU-based, so M5 defaults to an **ECO 5 fps 320×240** preview, with selectable LOW and BALANCED profiles, a one-item latest-frame worker queue and **8 Hz** audio feature analysis. Preview and analysis threads run below normal thread priority where the operating system allows it. A slow preview frame cannot block the audio callback or the UI. Full-resolution offline rendering is independent of preview quality and is intentionally not real-time.

See [docs/M5_TIMELINE_RENDERING.md](docs/M5_TIMELINE_RENDERING.md) for implementation details, export assumptions and acceptance checks.

## Canvas and performance

- Project coordinate system: **1920 × 1440** (4:3).
- Interactive preview defaults to **320 × 240** (ECO), with **360 × 270** (LOW) and **480 × 360** (BALANCED) options; all are scaled into the application window without changing the 4:3 project aspect ratio.
- The compositor uses CPU image-space operations in this milestone. It is structured so a GPU/GLSL backend can replace the preview implementation later.
- Offline rendering uses FFmpeg from PATH; the preview remains CPU/Pillow/NumPy based. Printable-area masks scale with the selected render size, and completed MP4s replace the destination atomically.

## Requirements and limitations

Python 3.12 (64-bit) recommended. Playback requires an available sounddevice/PortAudio output device. MP4 export requires FFmpeg on PATH; ffmpeg -version should succeed.

- Decoded audio is currently held in memory; long seven-source sessions can require substantial RAM.
- MP3 support depends on the installed libsndfile build. WAV, FLAC, AIFF and OGG are preferred.
- The frame-region coordinates are stored per screen template in engine/visual/assets.py and can be tuned if a guide design changes.
