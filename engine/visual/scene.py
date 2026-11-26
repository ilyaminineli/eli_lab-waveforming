from __future__ import annotations

"""Persistent visual-scene and visual-score models.

The existing VisualLayer remains the renderer's executable unit. VisualObject
adds stable compositional identity around a layer, while VisualScene owns
relationships, attention, lifecycle and canonical layer order. VisualScore
stores timed visual cues linked to structured musical input.
"""

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


SCENE_STATES = frozenset({
    "INACTIVE", "PREPARED", "ENTERING", "ACTIVE", "HELD",
    "EXITING", "ARCHIVED", "SAFE_FALLBACK",
})
OBJECT_LIFECYCLES = frozenset({"ACTIVE", "HELD", "ARCHIVED", "REMOVED"})
RELATIONSHIP_TYPES = frozenset({
    "derived_from", "responds_to", "accompanies", "transforms",
    "foregrounds", "backgrounds", "reinforces", "contrasts_with",
    "prepares", "returns_as", "occupies", "synchronised_with",
    "independent_of",
})
SCENE_STATE_TRANSITIONS = {
    "INACTIVE": {"PREPARED", "SAFE_FALLBACK"},
    "PREPARED": {"ENTERING", "INACTIVE", "SAFE_FALLBACK"},
    "ENTERING": {"ACTIVE", "PREPARED", "SAFE_FALLBACK"},
    "ACTIVE": {"HELD", "EXITING", "SAFE_FALLBACK"},
    "HELD": {"ACTIVE", "EXITING", "ARCHIVED", "SAFE_FALLBACK"},
    "EXITING": {"ARCHIVED", "HELD", "ACTIVE", "SAFE_FALLBACK"},
    "ARCHIVED": {"PREPARED", "SAFE_FALLBACK"},
    "SAFE_FALLBACK": {"PREPARED", "ACTIVE", "INACTIVE"},
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _role_name(value: str) -> str:
    raw = str(value or "MOTION").strip().upper().replace(" ", "_")
    aliases = {
        "BACKGROUND_ENVIRONMENT": "background",
        "BACKGROUND": "background",
        "STRUCTURE": "background_structure",
        "FOREGROUND_MOTIF": "foreground_anchor",
        "ANCHOR": "foreground_anchor",
        "MOTION": "midground_motion",
        "TEXTURE": "midground_texture",
        "ACCENT": "accent",
        "ATMOSPHERE": "background_atmosphere",
    }
    return aliases.get(raw, raw.lower())


@dataclass(slots=True)
class VisualObject:
    """A stable compositional entity backed by one executable renderer layer."""

    object_id: str = field(default_factory=lambda: _new_id("obj"))
    layer_id: str = ""
    name: str = "Visual Object"
    role: str = "midground_motion"
    locked: bool = False
    source_method: str = "generator"
    source_asset: str = ""
    geometry: dict = field(default_factory=dict)
    material: dict = field(default_factory=dict)
    transform: dict = field(default_factory=dict)
    animation_state: dict = field(default_factory=dict)
    motion_history: list[dict] = field(default_factory=list)
    salience: float = 0.5
    source_bindings: list[dict] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    permitted_transformations: list[str] = field(default_factory=lambda: [
        "translate", "scale", "rotate", "recolour", "morph",
        "freeze", "hold", "remove",
    ])
    lifecycle: str = "ACTIVE"
    metadata: dict = field(default_factory=dict)

    def sync_layer(self, layer: Any) -> None:
        """Refresh renderer-owned properties without changing object identity."""
        self.layer_id = str(layer.layer_id)
        self.name = str(layer.name)
        self.role = _role_name(str(layer.role))
        self.source_method = "generator"
        self.geometry = {
            "generator": str(layer.generator),
            "mask_mode": str(layer.mask_mode),
            "pass_mode": str(layer.pass_mode),
            "pass_map": str(layer.pass_map),
            "pass_strength": float(layer.pass_strength),
        }
        self.material = {
            "blend_mode": str(layer.blend_mode),
            "opacity": float(layer.opacity),
            "palette_mode": str(layer.palette_mode),
            "palette_index": int(layer.palette_index),
        }
        self.transform = {
            "position": [float(layer.x_offset), float(layer.y_offset), 0.0],
            "scale": [float(layer.scale), float(layer.scale), 1.0],
            "rotation": [0.0, 0.0, float(layer.rotation)],
        }
        self.salience = max(0.0, min(1.0, float(layer.opacity)))
        self.lifecycle = "ACTIVE"
        self.metadata["visible"] = bool(layer.visible)
        self.metadata["generator"] = str(layer.generator)
        self.metadata["layer_name"] = str(layer.name)

        source_id = str(layer.source_id or "")
        self.source_bindings = [
            binding for binding in self.source_bindings
            if binding.get("type") != "audio_source"
        ]
        if source_id:
            self.source_bindings.append({
                "type": "audio_source",
                "entity_id": source_id,
                "route": "group" if source_id.startswith("group:") else "track",
            })

    @classmethod
    def from_layer(cls, layer: Any) -> "VisualObject":
        result = cls(layer_id=str(layer.layer_id))
        result.sync_layer(layer)
        return result

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualObject":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        if not clean.get("object_id"):
            clean["object_id"] = _new_id("obj")
        clean["geometry"] = _dict(clean.get("geometry"))
        clean["material"] = _dict(clean.get("material"))
        clean["transform"] = _dict(clean.get("transform"))
        clean["animation_state"] = _dict(clean.get("animation_state"))
        clean["motion_history"] = _list_of_dicts(clean.get("motion_history"))
        clean["source_bindings"] = _list_of_dicts(clean.get("source_bindings"))
        clean["lineage"] = _string_list(clean.get("lineage"))
        clean["permitted_transformations"] = _string_list(
            clean.get("permitted_transformations")
        ) or ["translate", "scale", "rotate", "recolour", "morph", "freeze", "hold", "remove"]
        clean["metadata"] = _dict(clean.get("metadata"))
        lifecycle = str(clean.get("lifecycle", "ACTIVE")).upper()
        clean["lifecycle"] = lifecycle if lifecycle in OBJECT_LIFECYCLES else "ACTIVE"
        clean["salience"] = max(0.0, min(1.0, float(clean.get("salience", 0.5))))
        return cls(**clean)


@dataclass(slots=True)
class VisualRelationship:
    """A typed edge explaining why two visual entities are related."""

    relationship_id: str = field(default_factory=lambda: _new_id("rel"))
    source_object_id: str = ""
    target_object_id: str = ""
    kind: str = "accompanies"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualRelationship":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        kind = str(clean.get("kind", "accompanies"))
        clean["kind"] = kind if kind in RELATIONSHIP_TYPES else "accompanies"
        clean["metadata"] = _dict(clean.get("metadata"))
        return cls(**clean)


@dataclass(slots=True)
class VisualScene:
    """Persistent composition state; not merely a saved preset of generator layers."""

    scene_id: str = field(default_factory=lambda: _new_id("scene"))
    name: str = "SCENE 01"
    version: int = 1
    role: str = "development"
    visual_identity_id: str = ""
    state: str = "ACTIVE"
    objects: list[VisualObject] = field(default_factory=list)
    layer_order: list[str] = field(default_factory=list)
    relationships: list[VisualRelationship] = field(default_factory=list)
    attention_plan: dict = field(default_factory=lambda: {
        "primary": None, "secondary": [], "background": [],
    })
    spatial_environment: dict = field(default_factory=lambda: {
        "camera": {"position": [0.0, 0.0, 1.0], "orientation": [0.0, 0.0, 0.0]},
        "space": "2D_COMPOSITION",
    })
    mapping_rules: list[dict] = field(default_factory=list)
    score_position: float = 0.0
    motion_state: dict = field(default_factory=dict)
    safety_constraints: dict = field(default_factory=dict)
    transition_in: str = ""
    transition_out: str = ""
    transition_eligible: bool = True
    fallback_scene_id: str = ""
    metadata: dict = field(default_factory=dict)

    def can_transition_to(self, next_state: str) -> bool:
        next_state = str(next_state).upper()
        if next_state not in SCENE_STATES:
            return False
        if next_state == "SAFE_FALLBACK":
            return self.state != "SAFE_FALLBACK"
        return next_state in SCENE_STATE_TRANSITIONS.get(self.state, set())

    def transition_state(self, next_state: str) -> None:
        """Apply one declared scene lifecycle transition or reject it explicitly."""
        next_state = str(next_state).upper()
        if next_state == self.state:
            return
        if not self.can_transition_to(next_state):
            raise ValueError(
                f"Invalid scene transition: {self.state} -> {next_state}"
            )
        self.state = next_state

    def synchronize_layers(
        self, layers: list[Any], tracker_data: dict | None = None
    ) -> None:
        """Reconcile the persistent object graph with the live renderer layer stack.

        Existing object IDs survive edits to their backing layers. Removed layers
        are archived rather than silently deleting their visual identity.
        """
        existing = {item.layer_id: item for item in self.objects if item.layer_id}
        active_ids: list[str] = []
        for layer in layers:
            layer_id = str(layer.layer_id)
            if not layer_id:
                continue
            active_ids.append(layer_id)
            visual_object = existing.get(layer_id)
            if visual_object is None:
                visual_object = VisualObject.from_layer(layer)
                self.objects.append(visual_object)
                existing[layer_id] = visual_object
            else:
                visual_object.sync_layer(layer)

        active_set = set(active_ids)
        for visual_object in self.objects:
            if visual_object.layer_id and visual_object.layer_id not in active_set:
                if visual_object.lifecycle != "ARCHIVED":
                    visual_object.lifecycle = "ARCHIVED"
                    visual_object.metadata["archive_reason"] = "backing_layer_removed"
            elif visual_object.layer_id in active_set and visual_object.lifecycle == "ARCHIVED":
                visual_object.lifecycle = "ACTIVE"

        self.layer_order = active_ids
        self._refresh_attention_plan()
        self.bind_tracker_channels(tracker_data or {})

    def bind_tracker_channels(self, tracker_data: dict) -> None:
        """Attach every XM channel identity to the ensemble object, including silent channels."""
        tracker_data = _dict(tracker_data)
        profiles = tracker_data.get("channel_profiles") or []
        score_id = str(tracker_data.get("score_id", ""))
        for visual_object in self.objects:
            if visual_object.metadata.get("generator") != "TRACKER ENSEMBLE":
                continue
            visual_object.source_bindings = [
                binding for binding in visual_object.source_bindings
                if binding.get("type") != "tracker_channel"
            ]
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                visual_object.source_bindings.append({
                    "type": "tracker_channel",
                    "entity_id": str(profile.get("voice_id", "")),
                    "score_id": score_id,
                    "channel": int(profile.get("channel", 0)),
                    "sample_name": str(profile.get("sample_name", "")),
                    "silent": bool(profile.get("silent", False)),
                })

    def _refresh_attention_plan(self) -> None:
        active = [
            item for item in self.objects
            if item.lifecycle == "ACTIVE" and bool(item.metadata.get("visible", True))
        ]
        active_ids = {item.object_id for item in active}
        plan = _dict(self.attention_plan)
        primary = plan.get("primary")
        if primary not in active_ids:
            anchors = [
                item for item in active
                if item.role in ("foreground_anchor", "foreground", "accent")
            ]
            primary = (anchors or active)[0].object_id if active else None
        secondary = [
            value for value in _string_list(plan.get("secondary"))
            if value in active_ids and value != primary
        ]
        background = [
            value for value in _string_list(plan.get("background"))
            if value in active_ids and value != primary and value not in secondary
        ]
        for item in active:
            if item.object_id == primary or item.object_id in secondary or item.object_id in background:
                continue
            if item.role.startswith("background"):
                background.append(item.object_id)
            else:
                secondary.append(item.object_id)
        self.attention_plan = {
            "primary": primary,
            "secondary": secondary,
            "background": background,
        }

    def ordered_layers(self, layers: list[Any]) -> list[Any]:
        """Return renderer layers in the scene's canonical graph order."""
        by_id = {str(layer.layer_id): layer for layer in layers}
        ordered = [
            by_id[layer_id] for layer_id in self.layer_order if layer_id in by_id
        ]
        known = set(self.layer_order)
        ordered.extend(
            layer for layer in layers if str(layer.layer_id) not in known
        )
        return ordered

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "name": self.name,
            "version": self.version,
            "role": self.role,
            "visual_identity_id": self.visual_identity_id,
            "state": self.state,
            "objects": [item.to_dict() for item in self.objects],
            "layer_order": list(self.layer_order),
            "relationships": [item.to_dict() for item in self.relationships],
            "attention_plan": self.attention_plan,
            "spatial_environment": self.spatial_environment,
            "mapping_rules": self.mapping_rules,
            "score_position": self.score_position,
            "motion_state": self.motion_state,
            "safety_constraints": self.safety_constraints,
            "transition_in": self.transition_in,
            "transition_out": self.transition_out,
            "transition_eligible": self.transition_eligible,
            "fallback_scene_id": self.fallback_scene_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualScene":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        clean["objects"] = [
            VisualObject.from_dict(item)
            for item in clean.get("objects", [])
            if isinstance(item, dict)
        ]
        clean["relationships"] = [
            VisualRelationship.from_dict(item)
            for item in clean.get("relationships", [])
            if isinstance(item, dict)
        ]
        clean["layer_order"] = _string_list(clean.get("layer_order"))
        clean["attention_plan"] = _dict(clean.get("attention_plan")) or {
            "primary": None, "secondary": [], "background": [],
        }
        clean["spatial_environment"] = _dict(clean.get("spatial_environment")) or {
            "camera": {"position": [0.0, 0.0, 1.0], "orientation": [0.0, 0.0, 0.0]},
            "space": "2D_COMPOSITION",
        }
        clean["mapping_rules"] = _list_of_dicts(clean.get("mapping_rules"))
        clean["motion_state"] = _dict(clean.get("motion_state"))
        clean["safety_constraints"] = _dict(clean.get("safety_constraints"))
        clean["metadata"] = _dict(clean.get("metadata"))
        state = str(clean.get("state", "ACTIVE")).upper()
        clean["state"] = state if state in SCENE_STATES else "ACTIVE"
        clean["score_position"] = max(0.0, float(clean.get("score_position", 0.0)))
        clean["version"] = max(1, int(clean.get("version", 1)))
        return cls(**clean)


@dataclass(slots=True)
class VisualScoreCue:
    """A timed structural cue in the authored visual trajectory."""

    cue_id: str = field(default_factory=lambda: _new_id("cue"))
    time: float = 0.0
    cue_type: str = "scene_hold"
    source_id: str = ""
    scene_id: str = ""
    priority: int = 50
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualScoreCue":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        clean["time"] = max(0.0, float(clean.get("time", 0.0)))
        clean["priority"] = max(0, min(100, int(clean.get("priority", 50))))
        clean["payload"] = _dict(clean.get("payload"))
        return cls(**clean)


@dataclass(slots=True)
class VisualScore:
    """Ordered visual trajectory with source-linked cues and scene references."""

    score_id: str = field(default_factory=lambda: _new_id("vscore"))
    version: int = 1
    name: str = "VISUAL SCORE"
    duration: float = 0.0
    clock_domain: str = "PERFORMANCE"
    source_score_id: str = ""
    scene_ids: list[str] = field(default_factory=list)
    cues: list[VisualScoreCue] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def bind_scene(self, scene_id: str) -> None:
        scene_id = str(scene_id)
        if scene_id and scene_id not in self.scene_ids:
            self.scene_ids.append(scene_id)
        for cue in self.cues:
            if not cue.scene_id:
                cue.scene_id = scene_id

    @classmethod
    def from_tracker_data(
        cls, tracker_data: dict | None, scene_id: str, duration: float = 0.0
    ) -> "VisualScore":
        data = _dict(tracker_data)
        source_score_id = str(data.get("score_id", ""))
        visual_score_id = (
            f"visual_{source_score_id}" if source_score_id
            else _new_id("vscore")
        )
        cues: list[VisualScoreCue] = []
        for index, cue in enumerate(data.get("cues") or []):
            if not isinstance(cue, dict):
                continue
            order = int(cue.get("order", index))
            pattern = int(cue.get("pattern", -1))
            is_return = bool(cue.get("pattern_reprise", False))
            cues.append(VisualScoreCue(
                cue_id=f"{visual_score_id}:order:{order:03d}",
                time=max(0.0, float(cue.get("start_seconds", 0.0))),
                cue_type="pattern_return" if is_return else "pattern_enter",
                source_id=source_score_id,
                scene_id=scene_id,
                priority=70,
                payload={
                    "order": order,
                    "pattern": pattern,
                    "end_seconds": max(0.0, float(cue.get("end_seconds", 0.0))),
                    "note_count": int(cue.get("note_count", 0)),
                    "active_channels": list(cue.get("active_channels") or []),
                    "density": float(cue.get("density", 0.0)),
                    "pattern_reprise": is_return,
                },
            ))
        score_duration = max(0.0, float(data.get("duration", duration)), float(duration))
        result = cls(
            score_id=visual_score_id,
            name=str(data.get("title") or "VISUAL SCORE"),
            duration=score_duration,
            clock_domain="MUSICAL_SCORE" if source_score_id else "PERFORMANCE",
            source_score_id=source_score_id,
            scene_ids=[scene_id] if scene_id else [],
            cues=cues,
            metadata={
                "source_type": "XM" if source_score_id else "STATIC",
                "channel_count": int(data.get("channels", 0)),
                "tracker": str(data.get("tracker", "")),
            },
        )
        if not cues:
            result.cues.append(VisualScoreCue(
                cue_id=f"{visual_score_id}:scene:open",
                time=0.0,
                cue_type="scene_open",
                source_id=source_score_id,
                scene_id=scene_id,
                priority=50,
            ))
        return result

    def to_dict(self) -> dict:
        return {
            "score_id": self.score_id,
            "version": self.version,
            "name": self.name,
            "duration": self.duration,
            "clock_domain": self.clock_domain,
            "source_score_id": self.source_score_id,
            "scene_ids": list(self.scene_ids),
            "cues": [cue.to_dict() for cue in self.cues],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualScore":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        clean["duration"] = max(0.0, float(clean.get("duration", 0.0)))
        clean["scene_ids"] = _string_list(clean.get("scene_ids"))
        clean["cues"] = [
            VisualScoreCue.from_dict(item)
            for item in clean.get("cues", [])
            if isinstance(item, dict)
        ]
        clean["metadata"] = _dict(clean.get("metadata"))
        clean["version"] = max(1, int(clean.get("version", 1)))
        clean["cues"].sort(key=lambda cue: (cue.time, -cue.priority, cue.cue_id))
        return cls(**clean)
