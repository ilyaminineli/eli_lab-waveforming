# M11 — VisualScore and persistent scene graph foundation

**Status:** Implemented foundation on `main`.

**Design basis:** IDM Visual Instrument guide, especially §§12–15 (visual ontology and object identity), §§44–47 (stateful scenes and transitions), §60–61 (reference architecture), §87 (visual scene schema), and §96 (Phase 0 foundation).

## Goal

Move the project representation beyond a flat list of renderer layers while keeping the current rendering engine operational.

M11 introduces three persistent model entities:

- `VisualObject` — an identifiable compositional object backed by an existing `VisualLayer`;
- `VisualScene` — persistent scene state, object relationships, attention roles and canonical layer order;
- `VisualScore` — a timed visual trajectory whose cues can refer to a structured musical score and one or more scenes.

This is a compatibility step, not a complete implementation of every entity in the guide.

## 1. VisualObject

Each live `VisualLayer` is reconciled with a persistent `VisualObject` through its stable `layer_id`.

The object keeps its own `object_id` when the layer's generator, name, material, transform, visibility or compositing settings change. It records:

- compositional role and lifecycle;
- source method and optional source asset;
- geometry/generator and mask/pass configuration;
- material and compositing properties;
- position, scale and orientation;
- animation state and motion history containers;
- salience intention;
- audio and tracker-channel source bindings;
- lineage and permitted transformation vocabulary;
- metadata linking the object to its current renderer layer.

Removing a renderer layer archives its corresponding object rather than silently reusing its identity. Reordering layers updates the scene order but does not recreate objects.

The relationship is currently one renderer layer to one VisualObject. Future scene-graph work can introduce logical objects that contain several layers or objects rendered by a non-layer backend.

## 2. VisualScene

A scene serializes:

- stable scene ID, name, role and version;
- explicit lifecycle state;
- visual-identity reference;
- active and archived VisualObjects;
- canonical renderer-layer order;
- typed relationship records;
- attention plan with primary, secondary and background objects;
- spatial environment and camera placeholder;
- mapping-rule, motion and safety containers;
- score position, transition eligibility and fallback-scene reference.

The layer stack remains the editing interface in this increment. `VisualScene.synchronize_layers()` reconciles that stack into the persistent scene graph. Visible objects are assigned attention roles from their existing layer roles; a primary object is selected only when no valid primary is already recorded.

The scene graph's `layer_order` is now consumed by the compositor. The order is passed through the latest-frame preview worker and the offline export worker. Unknown/new layers are appended safely, preserving compatibility with callers that do not yet provide scene metadata.

## 3. XM source relationships

When a layer uses `TRACKER ENSEMBLE`, its VisualObject receives a `tracker_channel` source binding for every profile in the imported XM score.

Each binding preserves:

- score ID;
- stable XM voice ID;
- channel number;
- sample label;
- silent/active status.

Silent channels are retained as source relationships. The scene model does not invent musical activity for them.

Audio-linked renderer layers similarly receive `audio_source` bindings. These bindings are refreshed from the current layer after project loading and audio-source ID remapping.

## 4. VisualScore and structural cues

`VisualScore.from_tracker_data()` turns XM order cues into explicit timed visual cues. Each cue carries:

- stable cue ID derived from the visual-score ID and XM order;
- musical time from the tracker's `start_seconds`;
- the referenced scene ID;
- source XM score ID;
- order and pattern indices;
- order end time, note count, active channels and density;
- whether the pattern is a return/reprise.

Cue types are `pattern_enter` and `pattern_return`. A score without XM input receives a static `scene_open` cue. This model does not yet execute transitions; it records the structural trajectory so a later director can interpret it without re-parsing an ad hoc layer list.

## 5. Project persistence and migration

WAVEFORMING project files now write:

- `visual_scene`;
- `visual_score`;
- the existing `layers`, tracker data, timeline, settings and audio references.

The project format version is incremented to 2. The loader remains backward-compatible with existing version-1 `.wfp` files:

1. restore their original layer stack;
2. construct a new VisualScene from those layers;
3. derive a VisualScore from embedded tracker data or create a static visual score;
4. continue rendering with the same layer and generator definitions.

No audio assets are duplicated or embedded by this scene-model change.

## 6. Validation

The GitHub Actions validation now covers:

- Python application compilation;
- existing OpenGL shader validation;
- XM parser → channel packet → TRACKER ENSEMBLE rendering;
- XM sample/instrument identity in the channel state;
- one-to-one layer/object creation;
- persistence of object IDs after layer property edits;
- scene layer order after reordering;
- XM channel source bindings on the TRACKER ENSEMBLE object;
- JSON round-trip of VisualScene and VisualScore;
- compositor ordering from serialized scene data;
- reconstruction of a scene for a legacy project with no scene graph.

The current scene/score smoke validation passed on GitHub Actions.

## 7. Explicitly not implemented yet

Do not interpret the M11 schema containers as completed runtime features. The following work remains after M12 and M13:

- editable VisualIdentity and VisualBrief;
- authorable object relationships, motif lineage tools and relationship-editing UI;
- logical objects composed from multiple renderer layers;
- MappingRule execution, curve/smoothing/priority/conflict semantics and manual override;
- visual motifs, patterns, phrases and higher-level visual-form editor;
- deterministic scene snapshots, recovery/fallback execution and runtime transition checkpointing;
- transition-family rendering beyond M14: object-aware morph, assembly, erosion, mask reveal, displacement and temporal echo;
- multi-scene rehearsal tools, performer overrides and show-control integration.

**M12 — Scene State Machine and Transition Contracts** is implemented as the deterministic model/controller foundation. **M13 — Multi-scene Project State and Score-Cue Integration** adds project-level scenes, scene duplication, cue routes, the authoring panel, project persistence and compositor state handoff. See [M12_SCENE_STATE_MACHINE_TRANSITIONS.md](M12_SCENE_STATE_MACHINE_TRANSITIONS.md) and [M13_MULTI_SCENE_PROJECT_SCORE_CUES.md](M13_MULTI_SCENE_PROJECT_SCORE_CUES.md).

M14 now provides the outgoing/incoming scene-pair contract and crossfade renderer. The compositor continues receiving resolved scene state rather than owning transition policy itself. See [M14_RENDERER_SCENE_PAIR_CROSSFADE.md](M14_RENDERER_SCENE_PAIR_CROSSFADE.md).
