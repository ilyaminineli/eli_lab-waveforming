# ELI LAB — WAVEFORMING

An experimental audio-reactive visual composition workstation. Not a conventional waveform visualiser.

## Core canvas
- Native composition space: **1920 × 1440** (4:3).
- Screen guides and screen-pass maps live in `screens/`; they are treated as fixed-resolution composition assets.
- UI zoom never changes the output canvas dimensions.

## Initial architecture
- `app/`: desktop UI and project orchestration.
- `engine/audio/`: multi-source loading, playback clock and analysis.
- `engine/visual/`: frame graph, screen/pass assets and abstract generators.
- `projects/`: portable session files.
- `tests/`: deterministic engine tests.

## Requirements
Python 3.12 (64-bit) recommended.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

## First implementation
- Up to 7 independent audio sources.
- Per-source gain, pan, mute, solo and analysis enable.
- Analysis features: RMS/envelope, peak, FFT spectrum, logarithmic bands, spectral centroid, spectral flatness, spectral flux, zero-crossing rate and stereo width.
- Analysis is computed independently from visual generators; generators consume normalized feature frames.
- Screen guides and passes are imported as repository assets, not resized to fit arbitrary display aspect ratios.
- Starter generators create abstract structures from audio descriptors rather than drawing a standard equalizer.

## Design principles
1. The project canvas is always 1920×1440.
2. Visual generators do not own audio decoding or device playback.
3. Every visual element is a compositing layer with opacity, blend mode, transform and optional pass input.
4. Export and preview share the same frame graph.
5. Analysis is multi-resolution and cached per source; visual parameters are normalized and deterministic where possible.

This is the foundation milestone, not the final visual language. New generators and shader passes can be added without rewriting the audio engine.
