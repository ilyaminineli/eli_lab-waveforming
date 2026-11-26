# M4 — Generative Composition and Performance

## Intent

Move WAVEFORMING from a set of audio-reactive visualisers toward an abstract composition instrument. The visual result should feel authored: geometric plates, measured constructions, layered frames, modular typography-like marks, pseudo-3D volumes and deliberate negative space.

The supplied visual references point to a visual grammar with:

- overlapping rectangular planes and offset print frames;
- dashed and solid boundaries, registration marks and alignment systems;
- centred or deliberately displaced geometric objects;
- columns, bars and repeated marks that behave like abstract editorial typography;
- pseudo-3D forms, wireframe volumes, halos and technical overlays;
- monochrome paper grain and a restrained, desaturated multi-channel palette.

Noise remains one possible texture or generator family, not the default visual language.

## M4.1 — Composition primitives

**Implemented in this milestone**

- Geometric Plate: layered rectangular planes, registration geometry, alignment marks and modular bar structures.
- Geometric Field: superformula contours, radial constructions, orbital arcs and audio-driven nodes.
- Axonometric Field: isometric prisms with band-controlled extrusion.
- Polyhedral Field: a rotating wireframe polyhedron projected from 3D coordinates.
- Existing parametric families remain available: phase orbits, phase lattice, Möbius field, spectral topography, phyllotaxis, reaction-diffusion and cellular structures.

**Further work**

- More reusable primitives: arcs, spline paths, signed-distance shapes, grids, masks, polygon families, type-like glyph modules and repeated plane stacks.
- Parametric shape definitions that can be shared by generators rather than duplicated in every generator class.
- Multi-object 3D scenes with camera projection, depth ordering and simple lighting.

## M4.2 — Channel-driven composition

**Implemented in this milestone**

- Each visual layer can analyse MIX / ALL or bind to one independent audio source.
- Per-source descriptors drive each bound layer.
- A muted seven-colour pride-inspired palette identifies individual channels.
- White paper automatically uses darker ink variants; monochrome scopes invert to dark ink on white.

**Further work**

- A visible modulation matrix to map RMS, low/mid/high bands, transient, centroid, width and cross-source correlation to geometric parameters.
- Per-channel gain/response curves, smoothing, hold, hysteresis and quantisation.
- Cross-channel relationships: phase opposition, correlated motion, shared geometry and controlled interference.

## M4.3 — Automatic composition

**Implemented in this milestone**

- AUTO COMPOSE creates a multi-layer plate from loaded sources.
- VARIATE changes generator families, placement, rotation, scale, blend and pass strength while preserving source routing.
- Optional AUTO VARIATE changes the composition every 12 seconds during playback.

**Further work**

- Composition recipes with named structural roles: anchor, frame, volume, orbit, detail and annotation.
- A scoring system for balance, occupancy, negative space, contrast and edge safety.
- Weighted variation that changes one or two structural decisions at a time instead of replacing the whole composition.
- Transition modes between variations: morph, dissolve, geometric substitution and feedback transfer.
- Seed locking and reproducible variation history.

## M4.4 — Paper-aware composition

**Implemented in this milestone**

- Layers are clipped to the selected screen's printable region by default.
- Paper relief retains displacement, normal-derived lighting and texture modulation.
- The same frame masks keep generated content inside the intended composition region.

**Further work**

- Per-template editable safe regions and named sub-regions.
- Multiple independent masks per layer, mask inversion and mask-to-layer links.
- Local relief direction and depth controls, rather than one global paper-light direction.
- Optional deliberate bleed and registration-mark overlap for layers that should escape the print area.

## M4.5 — Performance architecture

**Implemented in this milestone**

- Interactive preview reduced to 720×540 while the project canvas remains 1920×1440.
- Preview refresh capped at 20 fps.
- Layer blending processes only the intersecting layer rectangle.
- Screen plates, frame masks, resized pass maps, coordinate grids and paper-relief fields are cached.
- Expensive per-layer relief derivatives are calculated once per pass-map and layer-size combination.
- Shader-effect controls and their per-frame processing have been removed.

**Further work / performance targets**

- Render worker thread with latest-frame replacement so the UI never waits for a slow render.
- Adaptive preview scale based on layer count and measured render time.
- Incremental invalidation: static layers should not regenerate when only another layer changes.
- GPU backend for transforms, blend operations, displacement and normal lighting.
- Profiling overlays for render time per layer, total frame time and dropped preview frames.
- Full-resolution offline rendering must use the exact same composition graph as the preview.

## Acceptance checks

1. A seven-source project can show at least one independent visual layer per source, each with a stable channel colour.
2. A geometric plate, a pseudo-3D layer and one audio-reactive layer can be combined without crossing the selected frame mask.
3. The paper relief remains visible on both black and white paper templates.
4. White-paper scopes are legible as dark ink; black-paper scopes are legible as pale ink.
5. AUTO COMPOSE creates a balanced multi-layer starting point; VARIATE preserves source routing.
6. Playback continues if a preview frame is late. Visual rendering must never run inside the audio output callback.
7. On the target Windows machine, a typical 3–5 layer composition should sustain a stable preview; seven-source/seven-layer performance must be measured before promising a frame rate.

## Next milestone

**M5 — Timeline, automation and deterministic rendering**

- Timeline with markers, sections, beats and manual cue points.
- Parameter automation and recorded performance gestures.
- Deterministic offline frame rendering at 1920×1440.
- Audio/video muxing and export presets.
- Preview and export must share the same composition graph and seed state.

## M4 visual/performance stability patch

Following the first Windows test session, the following corrections were added:

- Reaction Diffusion now renders the activator field and narrow iso-contours. The inactive U/V background is transparent; it no longer creates a nearly opaque tinted rectangle.
- Geometric Plate uses outlined planes rather than broad translucent fills.
- Layer transforms use exact 0°, 90°, 180° or 270° turns. Arbitrary legacy angles are snapped to quarter turns, and an identity transform bypasses image resampling.
- The interactive preview is reduced to 600×450 and refreshed at approximately 15 fps. The project coordinate system remains 1920×1440.
- Reaction Diffusion advances at a capped simulation rate; Cellular System and Reaction Diffusion use padded neighbour stencils instead of repeated full-frame array rolls.
- The former seven-hue rainbow is replaced with a restrained three-ink editorial palette based on dusty cobalt, aged yellow and violet. Existing project layers that still store the legacy palette label are interpreted using this new palette.
- `pytest.ini` and `tests/conftest.py` make the repository root importable during test collection. A GitHub Actions workflow runs the test suite on Python 3.12.

The preview is still CPU-rendered. The reduced preview and smaller simulation workload are intended to lower load, but frame time must still be measured on the target Windows machine with the actual layer count and source recordings.
