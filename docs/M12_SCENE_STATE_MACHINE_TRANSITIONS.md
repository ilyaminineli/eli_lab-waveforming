# M12 — Scene state machine and transition contracts

**Status:** Lifecycle and transition-contract foundation implemented on `main`.

**Design basis:** IDM Visual Instrument guide §§44–47 (scene state, transition families and three-stage transition design), §§52–54 (candidate selection and deterministic/explainable decisions), and §87 (VisualScene schema).

## Goal

Make scene changes explicit and recoverable before adding visual transition effects.

M12 introduces:
- a validated VisualScene lifecycle;
- a declarative SceneTransition contract;
- a separate proposal and commit boundary;
- deterministic time sampling across preparation, transformation and establishment;
- explicit outgoing-scene and interruption policies.

The transition controller is a domain model. It does not own a timer, render pixels, or silently change the project layer stack.

## 1. Scene lifecycle

The current states are:

```text
INACTIVE
   |
   v
PREPARED -> ENTERING -> ACTIVE -> EXITING -> ARCHIVED
                ^         |          |
                |         v          v
              RESUME <- HELD <-------+
                
Any state -> SAFE_FALLBACK
```

The implementation validates each transition through `VisualScene.transition_state()`. An invalid jump raises `ValueError` and leaves the current state unchanged.

Current allowed transitions:

| Current | Allowed next states |
|---|---|
| INACTIVE | PREPARED, SAFE_FALLBACK |
| PREPARED | ENTERING, INACTIVE, SAFE_FALLBACK |
| ENTERING | ACTIVE, PREPARED, SAFE_FALLBACK |
| ACTIVE | HELD, EXITING, SAFE_FALLBACK |
| HELD | ACTIVE, EXITING, ARCHIVED, SAFE_FALLBACK |
| EXITING | ARCHIVED, HELD, ACTIVE, SAFE_FALLBACK |
| ARCHIVED | PREPARED, SAFE_FALLBACK |
| SAFE_FALLBACK | PREPARED, ACTIVE, INACTIVE |

This table is intentionally explicit. A new scene should normally be prepared and enter before becoming active. Returning to an archived scene requires preparing it again.

## 2. SceneTransition contract

A transition declares:

- stable transition ID;
- outgoing and incoming scene IDs;
- family;
- duration in seconds;
- trigger metadata;
- easing;
- preparation and transformation fractions (the remaining duration is establishment);
- preserved and discarded object IDs;
- interruption policy;
- outgoing-scene policy (archive or hold);
- deterministic seed and metadata.

Supported contract families are: cut, dissolve, morph, assembly, erosion, mask reveal, displacement, camera, palette, attention transfer, temporal echo, negative, split/merge and hard reset.

The family is descriptive in this step. Only a common progress/weight contract is evaluated; visual implementations for those families are not yet connected to the renderer. The preserved/discarded object lists are validated for overlap and known IDs, but the current renderer does not yet transfer object state between scenes.

### Three phases

A transition is sampled by absolute show time. Its phase is derived from elapsed progress:

1. **PREPARATION** — introduce the cue, focus or instability that prepares the change.
2. **TRANSFORMATION** — the main change between outgoing and incoming visual states.
3. **ESTABLISHMENT** — allow the incoming scene to become legible.

The sample includes raw progress, eased progress, outgoing/incoming weights, phase, completion and duration. The default contract uses 15% preparation, 70% transformation and 15% establishment with smoothstep easing.

A cut keeps the outgoing weight at 1 and incoming at 0 until the exact completion boundary, then switches. Other declared families use the common eased weights until a family-specific renderer is implemented.

## 3. Proposal versus commit

`SceneTransitionController.propose()` validates a candidate:
- its source must be the currently active scene;
- both scenes must be registered;
- source and target must differ;
- source must be ACTIVE;
- target must be inactive or resumable;
- preserved/discarded object IDs must exist in one of the two scenes.

Proposal does not mutate scene state.

`commit()` requires the matching proposal ID. It moves the source to EXITING, prepares the target if required, moves the target to ENTERING, and records the supplied absolute start time.

`sample(show_time)` computes deterministic transition phase and blend weights. When the contract completes, the outgoing scene becomes HELD or ARCHIVED according to policy, and the incoming scene becomes ACTIVE.

This allows a future director to generate and explain several candidate changes without accidentally changing the live scene.

## 4. Interruption policies

Every contract declares one policy:

- **reject** — refuse interruption while the transition is active;
- **complete** — immediately commit the target scene as active;
- **cancel** — restore the outgoing scene to ACTIVE and return the target to PREPARED.

The outgoing-scene policy independently determines whether a completed outgoing scene is archived or held for a possible return.

## 5. Determinism and clocking

The controller is sampled with caller-supplied show time. It does not use wall-clock timers or background threads. Identical transition data, start time and sample time produce identical results.

M13 connects the controller to a project-level scene collection and the standalone XM/audio transport. Each project now persists its scene collection, active-scene reference, per-scene layer snapshots, transition contracts and explicitly authored XM cue routes. Live preview and offline export can propose and commit those routes through this controller.

## 6. Validation

The CI smoke test checks:

- invalid scene-state jumps are rejected;
- proposal does not change either scene;
- commit enters the expected states;
- sampling enters the transformation phase at the expected time;
- completion archives the outgoing scene and activates the target;
- cancellation restores the outgoing scene and prepares the target;
- transition contracts round-trip through JSON;
- scene collection migration, scene/layer/object identity remapping, cue-route persistence and active-scene selection;
- the XM → VisualScene → VisualScore path still passes.

## 7. Renderer boundary after M14

M14 adds the shared outgoing/incoming `ScenePairRenderContract` and a real `dissolve` crossfade in live preview and offline export. `cut` switches at completion. Other transition families retain lifecycle-only hold behavior until their renderer implementations exist. See [M14_RENDERER_SCENE_PAIR_CROSSFADE.md](M14_RENDERER_SCENE_PAIR_CROSSFADE.md).

Still not implemented:

- morph, assembly, erosion, mask reveal, displacement and temporal-echo pixel effects;
- transfer or merging of preserved VisualObjects between scenes;
- automatic semantic candidate-generation from XM phrase/pattern meaning; cue routes are explicitly authored;
- performer overrides, reverse transitions and runtime transition checkpoint/resume;
- visual safety constraints during transition interpolation;
- deterministic offline replay of manual transitions at their original show-time (score-cue routes are replayed).
