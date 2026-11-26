# M14 — Renderer-side scene-pair transitions

**Status:** Scene-pair dissolve/cut and first object-aware morph increment implemented  
**Depends on:** M11 VisualScene/VisualScore, M12 transition controller, M13 VisualProject

## 1. Goal

M14 introduces a shared outgoing/incoming render contract and uses the M12 transition sample to produce an actual image transition. The scene-pair renderer supports deterministic dissolve/crossfade, cut, and an initial object-aware morph. The same pair snapshot and compositor path are used by live preview and offline export.

Transition policy remains owned by `SceneTransitionController`. The renderer receives two scene snapshots and a resolved sample; it does not select targets, commit transitions or reinterpret musical cues.

## 2. ScenePairRenderContract

`engine/visual/scene_pair.py` introduces a serializable `ScenePairRenderContract` containing:

- transition ID, source and target scene IDs, family and phase;
- raw and eased progress, outgoing/incoming weights, duration and completion state;
- an outgoing side with its VisualScene graph and independent VisualLayer records;
- an incoming side with its VisualScene graph and independent VisualLayer records;
- resolved project/scene-state metadata and trigger context;
- the selected renderer mode.

The contract validates scene IDs, family/phase names, finite normalized progress/weights, and the invariant that the two weights sum to one. `from_project()` captures the two scene graphs and each project's independent layer snapshot from one M12 controller sample. `to_dict()/from_dict()` preserve the render input across worker boundaries.

Renderer modes in this increment:

| M12 family | M14 renderer behavior |
| --- | --- |
| `dissolve` | Real pixel crossfade using incoming weight |
| `cut` | Outgoing image until completion, then incoming |
| `morph` | Matched VisualObjects interpolate transforms/material values; supported generator paths deform point-by-point; unmatched objects/paths fade independently |
| Assembly, erosion, mask reveal, displacement, temporal echo and other future families | Lifecycle-only hold; no fake dissolve |

`blend_scene_pair_frames()` is the shared pixel-level blend function. It validates identical frame dimensions and always works in RGBA.

## 3. VisualObject correspondence and morph composition

M14 adds a one-to-one correspondence list to `SceneTransition`. Each entry identifies a `source_object_id` in the outgoing scene and a `target_object_id` in the incoming scene. The controller rejects mappings that reference an object on the wrong side, duplicate source IDs or duplicate target IDs. Exact IDs present in both scenes are recorded as identity matches. Duplicated objects can also be matched through their `lineage` / `duplicated_from_object_id` ancestry when the relationship is uniquely one-to-one. No name-based or fuzzy matching is attempted.

`ScenePairRenderContract` snapshots the resolved correspondence. A matched pair becomes one intermediate `VisualObject` and one renderer layer. Position, scale, shortest-path rotation, opacity, pass strength, salience and numeric geometry/material values interpolate using the controller's eased progress. Categorical generator/material modes switch at the midpoint, while the outgoing layer ID remains the generator simulation key for the duration of the morph.

Unmatched outgoing objects fade by the outgoing weight; unmatched incoming objects fade by the incoming weight. The compositor renders this single intermediate scene, so the screen guide and paper-grain background are drawn once rather than crossfading two complete textured frames. Layer order follows the outgoing scene before the midpoint and the incoming scene after it.

### Generator-aware path deformation

For line/edge generators, the compositor obtains normalized vector paths from the generator at the current tracker/audio packet and show time. The first supported set is **Phase Orbit, Phase Lattice, Geometric Field, Geometric Plate, Axonometric Field, Polyhedral Field and Mobius Field**.

Paths are matched by stable path IDs first, then by compatible semantic path groups and nearest normalized centroid. Matched paths are resampled by arc length, their direction/orientation is aligned, and corresponding points, stroke width and ink values are interpolated using eased transition progress. Unmatched source/target paths fade independently. The resulting paths are rasterized into one intermediate layer and then pass through the normal compositor palette, paper-relief, transform and mask stages.

Particle, cellular, reaction-diffusion, interference and other raster/simulation generators retain the existing object-level morph fallback. The path model does not invent topology for raster outputs.

## 4. Compositor

`VisualCompositor.render_scene_pair()` renders both scene snapshots independently using the same:

- tracker/audio feature packet;
- visual show time;
- generator settings and screen guide;
- compositor dimensions.

Each side uses its own canonical scene layer order and independent layer IDs, so per-layer generators retain their own simulation identity. The rendered images are then passed through the shared blend function. Temporal feedback is applied once to the final pair image, not once to each side; this avoids feedback from one scene being accumulated separately into the other.

The resulting profile reports the transition ID/family/mode/phase/progress, source and target scene IDs, both weights, total timing and both scenes' layer timings.

## 5. Live preview

The application snapshots the active M12 transition sample into a `ScenePairRenderContract` and passes it to `PreviewRenderWorker`.

While a pair is active the worker:

- retains generator state for the union of both layer sets;
- renders both scene snapshots on its compositor thread;
- applies the crossfade and feedback;
- returns one complete RGBA frame to the canvas.

The pair path uses CPU composition, including when OpenGL preview is otherwise available. This is deliberate for the first correctness-focused implementation: the existing GPU path composites one scene's layer descriptors and does not yet have a two-scene transition shader. Normal GPU preview resumes after the transition completes.

## 6. Offline export

Offline export builds the same pair contract from the project and the current M12 sample, then calls `render_scene_pair()`. Cue-triggered transitions therefore use identical frame blending and easing values in preview and export. A fixed project, score, transition and frame time resolve to the same pair weights and output composition.

Manual transition replay remains outside the current offline scope; M13 already records manual contracts, but only score-cue routes are replayed on the offline score clock.

## 7. Validation

The CI smoke path checks:

- pair-contract creation from a two-scene VisualProject;
- scene and layer snapshot IDs on both sides;
- contract JSON round-trip;
- exact outgoing endpoint, 50/50 midpoint and incoming endpoint pixel values;
- the compositor's two-scene rendering orchestration and crossfade output;
- explicit hold behavior for unimplemented transition families;
- the existing XM, M11, M12 and M13 smoke coverage;
- Python compile and GLSL shader validation.

## 8. Current limitations and next steps

This first M14 increment implements the pair-rendering architecture and dissolve, not all transition families.

- Scene-pair rendering is CPU-side; a future GPU-native pair compositor can optimize it.
- `assembly`, `erosion`, `mask_reveal`, `displacement` and `temporal_echo` currently hold the outgoing frame until lifecycle completion.
- Generator path morphing currently targets line/edge families listed above. Raster simulations use the object-level fallback; topology-aware fluid contour extraction, path splitting/merging and semantic anchor editing remain future work.
- Correspondence is one-to-one. Split/merge mapping and explicit object transfer/merge policies remain future work.
- There is no independent preparation or establishment image treatment yet; the M12 phase sample is exposed to the compositor.
- Runtime transition checkpoints and replay of manually authored transitions in offline export are not implemented.

**Next M14 slices:** extend path correspondence with authored anchors and split/merge operations; implement assembly and erosion as deterministic object lifecycle operations; then introduce temporal echo as a transition-local history buffer. Keep each effect behind the same scene-pair contract so live and offline rendering stay aligned.
