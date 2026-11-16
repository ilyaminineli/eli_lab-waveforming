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

## Core canvas

- Native composition space: 1920 × 1440 (4:3).
- Screen guides and screen-pass maps live in screens/; they are treated as fixed-resolution composition assets.
- UI zoom never changes the output canvas dimensions.

## Initial architecture

- main.py: root application entry point.
- app/: desktop UI and project orchestration.
- engine/audio/: multi-source loading and analysis.
- engine/visual/: screen/pass assets and composition preview.
- tests/: deterministic engine tests.

## Requirements

Python 3.12 (64-bit) recommended. Install dependencies with:

    pip install -r requirements.txt

## First implementation

- Up to 7 independent audio sources.
- Per-source gain, pan, mute, solo and analysis enable.
- Analysis features: RMS/envelope, peak, FFT spectrum, logarithmic bands, spectral centroid, spectral flatness, spectral flux, zero-crossing rate and stereo width.
- Analysis is computed independently from visual generators; future generators consume normalized feature frames.
- Screen guides and passes are imported as repository assets.
- The current UI is a foundation: live synchronized playback, live visual modulation, shader graph and video export are subsequent milestones.

## Design principles

1. The project canvas is always 1920×1440.
2. Visual generators do not own audio decoding or device playback.
3. Every visual element will be a compositing layer with opacity, blend mode, transform and optional pass input.
4. Preview and export should share the same frame graph.
5. Analysis is multi-resolution and visual parameters are normalized and deterministic where possible.
