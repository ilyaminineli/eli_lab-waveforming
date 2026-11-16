# ELI LAB — WAVEFORMING

An experimental audio-reactive visual composition workstation. Not a conventional waveform visualiser.

## Launch from PyCharm

The application entry point is main.py in the repository root.

1. Open the repository folder in PyCharm.
2. Set the project interpreter to the repository's .venv Python interpreter (or create one using Python 3.12, 64-bit).
3. Select the shared WAVEFORMING run configuration from the run-configuration selector.
4. Press Run (Shift+F10).

The committed configuration runs $PROJECT_DIR$/main.py with $PROJECT_DIR$ as its working directory, so relative screens/ assets resolve correctly.

## Launch from a terminal

    py -3.12 -m venv .venv
    .venv\Scripts\activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python main.py

## Current milestones

### M1 — Synchronized audio and analysis

- Up to seven sources share one output clock and can be loaded, removed, muted, soloed, panned and gain-adjusted independently.
- Sources with different sample rates are converted to the selected output device rate.
- Shared play/pause/stop, seek and loop transport.
- Per-source RMS, peak, FFT spectrum, logarithmic bands, spectral centroid, rolloff, bandwidth, flatness, entropy, spectral flux, zero-crossing rate, stereo width and crest factor.
- Pairwise zero-lag correlation between active source blocks.
- The PortAudio output callback performs bounded mixing and queueing only; FFT and descriptor calculations run on a separate analysis thread.

### M2 — Mathematical visual generators

Five transparent, audio-reactive generators are included:

- **Interference Field** — coupled nonlinear spatial fields and quantised contours.
- **Phase Orbit** — source-specific parametric curves modulated by energy and pairwise correlation.
- **Particle Field** — deterministic particle distribution warped by spectral and cross-source features.
- **Cellular System** — audio-influenced cellular automaton.
- **Phase Lattice** — displaced grid geometry with phase-driven intersections.

Generator parameters include complexity, motion and audio response. The selected screen guide remains the fixed 4:3 composition plate; visual output is composited above it. Displacement, normal and texture maps are available as image passes with blend operations.

## Core canvas

- Native composition space: **1920 × 1440** (4:3).
- Screen guides and pass maps live in screens/.
- Live preview is rendered at 960 × 720 and displayed in the same 4:3 coordinate space. The target project/output canvas remains 1920 × 1440; full-resolution offline rendering is a later milestone.

## Requirements

Python 3.12 (64-bit) recommended. Install dependencies with:

    pip install -r requirements.txt

The audio engine uses sounddevice/PortAudio. An available output device is required for playback.

## Current limitations

- Decoded sources are currently held in memory; very long multitrack sessions can require substantial RAM.
- MP3 support depends on the installed libsndfile build; WAV, FLAC, AIFF and OGG are the preferred formats.
- Video export, GPU shader graph, keyframe automation and project save/load are not implemented yet.
