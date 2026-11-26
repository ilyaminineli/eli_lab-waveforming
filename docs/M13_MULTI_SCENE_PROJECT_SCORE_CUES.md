# M13 — Multi-scene Project State and Score-Cue Integration

**Status:** Implemented foundation  
**Depends on:** M11 VisualScore/scene graph, M12 scene lifecycle and transition controller

## 1. Goal

M13 makes the visual composition a project containing multiple persistent scenes rather than one mutable scene graph. Each scene owns its compositional graph and a separate snapshot of executable renderer layers. The active scene can be selected or duplicated, and XM score cues can be explicitly mapped to another scene through a validated M12 transition contract.

The milestone connects the project state, cue routing, UI, live preview and deterministic offline rendering. It does not implement transition-family pixel effects.

## 2. Project model

`engine/visual/project.py` adds `VisualProject`:

- a stable project ID and name;
- an ordered collection of `VisualScene` objects;
- an explicit `active_scene_id`;
- independent `layer_snapshots` keyed by scene ID;
- committed transition contracts;
- explicit cue-to-scene routes;
- project metadata.

A `VisualScene` continues to own the M11 graph: persistent `VisualObject` identities, relationships, attention plan, source bindings, tracker-channel bindings and canonical layer order. The corresponding `VisualLayer` records are stored separately per scene. Switching scenes therefore loads another scene's renderer state rather than mutating a shared layer list.

An intentionally empty scene is valid and remains empty after save/load.

## 3. Scene selection and duplication

The scene selector changes the active scene immediately. The outgoing active scene becomes `HELD`; the selected scene is moved through the applicable lifecycle states into `ACTIVE`. The application restores that scene's saved layer snapshot and resets renderer feedback/simulation state.

Scene duplication creates new identities rather than aliasing the source:

- new scene ID;
- new layer IDs, including IDs associated with archived graph objects;
- new VisualObject IDs with source identity retained in lineage/metadata;
- remapped object-to-layer links, relationships and attention-plan references;
- an inactive `variation` scene with a separate layer snapshot.

This is a structural duplicate, not a live shared-instance relationship. Subsequent layer edits in one scene do not change the other.

## 4. XM score-cue routing

M11's `VisualScoreCue` records provide stable cue IDs and the XM order/pattern/time metadata. M13 adds an explicit route for a cue:

- cue ID;
- expected source scene ID;
- target scene ID;
- transition family;
- duration and easing;
- interruption and outgoing-scene policies.

The **ROUTE CURRENT XM CUE** control maps the most recent visual-score cue at the playhead to the selected target scene. This is intentionally explicit: the importer does not guess which visual scene should follow a musical pattern.

During playback the application detects cue crossings, queues routed cues while another transition is active, and ignores a route if its declared source scene is no longer active. Cue scanning detects playhead wraparound and starts a new pass from the beginning, so opening cues remain eligible on looped playback. An eligible route creates a `SceneTransition`, calls `SceneTransitionController.propose()`, then commits the returned proposal through `commit()`. The controller remains the authority for source/target validation and lifecycle changes.

The live preview samples transitions on its show-time clock. Offline rendering uses score time, the same project routes and the same M12 controller, so XM-driven scene changes are deterministic for a fixed project and export configuration.

## 5. Authoring UI

The **VISUAL SCENES** panel provides:

- active-scene selector;
- transition-target selector;
- **+ SCENE** and **DUPLICATE**;
- transition-family selection and duration;
- **COMMIT TRANSITION** for a manual transition;
- **ROUTE CURRENT XM CUE** for mapping the current tracker cue.

Scene collection edits are blocked while a transition is active. Direct scene selection is an explicit immediate switch; an active transition is first handled according to its interruption policy.

## 6. Project persistence and migration

The `.wfp` project format is now version **3**. It stores the full `visual_project` collection in addition to the legacy active-scene/layer fields retained for compatibility and recovery.

Older M11/M12 single-scene projects are migrated by building a one-scene `VisualProject` from their existing `visual_scene` and `layers` records. Their visual score and embedded tracker data remain intact. Version-3 projects restore the active scene's independent layer snapshot, including an empty snapshot.

A saved in-progress runtime transition is not resumed at an arbitrary partial frame after reopening. Incomplete lifecycle states are normalized to stable held/prepared states because the runtime show-clock position is not persisted as an execution checkpoint.

## 7. Compositor integration

M13 passes a `resolved_state` snapshot with project/active-scene IDs, lifecycle states, the latest M12 sample and pending cue count.

M14 extends this state handoff with `ScenePairRenderContract`. During a supported dissolve, live preview and offline export capture both scene graphs and their independent layer snapshots, render both sides with the same score packet/settings/show time, then blend the resulting RGBA frames. The normal single-scene path remains unchanged when no pair is active.

## 8. Validation

The CI smoke path checks:

- M11 XM parsing, channel bindings, VisualScene and VisualScore round trips;
- M12 proposal/commit, lifecycle, interruption and transition serialization;
- M13 project migration, independent layer snapshots, unique IDs after duplication, relationship/attention remapping, cue-route persistence and active-scene selection;
- Python compilation and GLSL shader validation.

## 9. Renderer effects beyond M14

M13 does not itself render transitions. M14 adds the shared scene-pair contract and real dissolve/crossfade behavior; `cut` switches at completion. During an active dissolve the compositor renders both scene stacks; the M12 sample's weights determine the outgoing/incoming pixel blend.

Still not implemented:

- object-aware morphing, assembly, erosion, mask reveal, displacement or temporal echo;
- actual transfer/merging of preserved VisualObjects between scenes;
- semantic auto-generation of routes from XM phrase or pattern meaning;
- performer override layers and persisted runtime transition checkpoints;
- replay of manually committed transitions at their original show-time in offline export (cue-routed transitions are replayed from the score).

See [M14_RENDERER_SCENE_PAIR_CROSSFADE.md](M14_RENDERER_SCENE_PAIR_CROSSFADE.md) for the new renderer contract and current CPU path limitations.
