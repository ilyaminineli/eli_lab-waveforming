# M14 — Renderer-side scene-pair transitions

**Status:** First renderer increment implemented  
**Depends on:** M11 VisualScene/VisualScore, M12 transition controller, M13 VisualProject

## 1. Goal

M14 introduces a shared outgoing/incoming render contract and uses the M12 transition sample to produce an actual image transition. The first supported effect is a deterministic dissolve/crossfade. The same pair snapshot and blend implementation are used by live preview and offline export.

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
| Morph, assembly, erosion, mask reveal, displacement, temporal echo and other future families | Lifecycle-only hold; no fake dissolve |

`blend_scene_pair_frames()` is the shared pixel-level blend function. It validates identical frame dimensions and always works in RGBA.

## 3. Compositor

`VisualCompositor.render_scene_pair()` renders both scene snapshots independently using the same:

- tracker/audio feature packet;
- visual show time;
- generator settings and screen guide;
- compositor dimensions.

Each side uses its own canonical scene layer order and independent layer IDs, so per-layer generators retain their own simulation identity. The rendered images are then passed through the shared blend function. Temporal feedback is applied once to the final pair image, not once to each side; this avoids feedback from one scene being accumulated separately into the other.

The resulting profile reports the transition ID/family/mode/phase/progress, source and target scene IDs, both weights, total timing and both scenes' layer timings.

## 4. Live preview

The application snapshots the active M12 transition sample into a `ScenePairRenderContract` and passes it to `PreviewRenderWorker`.

While a pair is active the worker:

- retains generator state for the union of both layer sets;
- renders both scene snapshots on its compositor thread;
- applies the crossfade and feedback;
- returns one complete RGBA frame to the canvas.

The pair path uses CPU composition, including when OpenGL preview is otherwise available. This is deliberate for the first correctness-focused implementation: the existing GPU path composites one scene's layer descriptors and does not yet have a two-scene transition shader. Normal GPU preview resumes after the transition completes.

## 5. Offline export

Offline export builds the same pair contract from the project and the current M12 sample, then calls `render_scene_pair()`. Cue-triggered transitions therefore use identical frame blending and easing values in preview and export. A fixed project, score, transition and frame time resolve to the same pair weights and output composition.

Manual transition replay remains outside the current offline scope; M13 already records manual contracts, but only score-cue routes are replayed on the offline score clock.

## 6. Validation

The CI smoke path checks:

- pair-contract creation from a two-scene VisualProject;
- scene and layer snapshot IDs on both sides;
- contract JSON round-trip;
- exact outgoing endpoint, 50/50 midpoint and incoming endpoint pixel values;
- the compositor's two-scene rendering orchestration and crossfade output;
- explicit hold behavior for unimplemented transition families;
- the existing XM, M11, M12 and M13 smoke coverage;
- Python compile and GLSL shader validation.

## 7. Current limitations and next steps

This first M14 increment implements the pair-rendering architecture and dissolve, not all transition families.

- Scene-pair rendering is CPU-side; a future GPU-native pair compositor can optimize it.
- `morph`, `assembly`, `erosion`, `mask_reveal`, `displacement` and `temporal_echo` currently hold the outgoing frame until lifecycle completion.
- Object preservation lists are still controller metadata; actual object transfer/merge and identity-aware correspondence are not implemented.
- There is no independent preparation or establishment image treatment yet; the M12 phase sample is exposed to the compositor.
- Runtime transition checkpoints and replay of manually authored transitions in offline export are not implemented.

**Next M14 slices:** add real morphing using explicit VisualObject correspondence; implement assembly and erosion as deterministic object lifecycle operations; then introduce temporal echo as a transition-local history buffer. Keep each effect behind the same scene-pair contract so live and offline rendering stay aligned.
