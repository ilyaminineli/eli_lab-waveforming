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
    pytest -q

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
- Separate displacement, normal-lighting, texture and edge operations.
- Image-space shader filters: halftone, ordered dither, posterize, scanlines, wave warp and edge extraction.
- Temporal feedback with return mix, decay and drift controls.
- Alpha-aware blend modes: Normal, Add, Screen, Multiply, Difference, Overlay, Lighten and Darken.

The screen templates use explicit normalized printable-area boxes. FRAME mode clips generated geometry to the corresponding content region so the registration marks, outer frame and paper annotations remain visible. FULL mode is available when a layer is intentionally meant to cover the whole plate.

## Canvas and performance

- Project coordinate system: **1920 × 1440** (4:3).
- Interactive preview: **960 × 720**, scaled into the application window without changing the project aspect ratio.
- The compositor uses CPU image-space operations in this milestone. It is structured so a GPU/GLSL backend can replace the preview implementation later.
- Full-resolution offline rendering, frame-rate selection, video export and keyframe automation are subsequent milestones.

## Requirements and limitations

Python 3.12 (64-bit) recommended. Playback requires an available sounddevice/PortAudio output device.

- Decoded audio is currently held in memory; long seven-source sessions can require substantial RAM.
- MP3 support depends on the installed libsndfile build. WAV, FLAC, AIFF and OGG are preferred.
- The frame-region coordinates are stored per screen template in engine/visual/assets.py and can be tuned if a guide design changes.
