from __future__ import annotations

"""Project-level persistence for multiple visual scenes and cue routing."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .layers import VisualLayer
from .scene import VisualScene
from .transitions import SceneTransition


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _layer_records(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, VisualLayer):
            result.append(item.to_dict())
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


@dataclass(slots=True)
class VisualProject:
    """Persistent scene collection, per-scene layer snapshots and cue routes.

    VisualScene owns compositional identity. The layer snapshots retain the
    executable renderer state required to restore each scene without sharing
    mutable VisualLayer instances between scenes.
    """

    project_id: str = field(default_factory=lambda: _new_id("vproject"))
    name: str = "WAVEFORMING PROJECT"
    version: int = 1
    scenes: list[VisualScene] = field(default_factory=list)
    active_scene_id: str = ""
    layer_snapshots: dict[str, list[dict]] = field(default_factory=dict)
    transitions: list[dict] = field(default_factory=list)
    cue_routes: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scenes = [
            scene if isinstance(scene, VisualScene) else VisualScene.from_dict(scene)
            for scene in self.scenes
        ]
        if not self.scenes:
            first = VisualScene(name="SCENE 01", state="ACTIVE")
            self.scenes.append(first)
            self.active_scene_id = first.scene_id
        if not any(scene.scene_id == self.active_scene_id for scene in self.scenes):
            self.active_scene_id = self.scenes[0].scene_id
        self.layer_snapshots = {
            str(scene_id): _layer_records(snapshot)
            for scene_id, snapshot in _dict(self.layer_snapshots).items()
            if str(scene_id)
        }
        self.transitions = [
            SceneTransition.from_dict(item).to_dict()
            for item in self.transitions
            if isinstance(item, dict)
        ]
        self.cue_routes = [
            dict(route) for route in self.cue_routes if isinstance(route, dict)
        ]
        self.metadata = _dict(self.metadata)
        self._normalise_active_state()
        for scene in self.scenes:
            self.layer_snapshots.setdefault(scene.scene_id, [])

    def _normalise_active_state(self) -> None:
        for scene in self.scenes:
            if scene.scene_id == self.active_scene_id:
                scene.state = "ACTIVE"
            elif scene.state == "ACTIVE":
                scene.state = "INACTIVE"
            elif scene.state == "EXITING":
                # Runtime transitions are not resumed on load without a clock
                # snapshot: retain the outgoing scene as a stable held scene.
                scene.state = "HELD"
            elif scene.state == "ENTERING":
                scene.state = "PREPARED"

    @property
    def active_scene(self) -> VisualScene:
        return self.get_scene(self.active_scene_id) or self.scenes[0]

    def get_scene(self, scene_id: str) -> VisualScene | None:
        return next(
            (scene for scene in self.scenes if scene.scene_id == str(scene_id)),
            None,
        )

    def store_layers(self, scene_id: str, layers: Any) -> None:
        if self.get_scene(scene_id) is None:
            raise KeyError(f"Unknown visual scene: {scene_id}")
        self.layer_snapshots[str(scene_id)] = _layer_records(layers)

    def layers_for_scene(self, scene_id: str) -> list[dict]:
        return deepcopy(self.layer_snapshots.get(str(scene_id), []))

    def register_scene(
        self,
        scene: VisualScene,
        layers: Any = None,
        *,
        make_active: bool = False,
    ) -> None:
        if self.get_scene(scene.scene_id) is not None:
            raise ValueError(f"Scene already exists: {scene.scene_id}")
        self.scenes.append(scene)
        self.layer_snapshots[scene.scene_id] = _layer_records(layers)
        if make_active:
            self.select_scene(scene.scene_id)

    def select_scene(self, scene_id: str) -> VisualScene:
        """Select a scene immediately, retaining the previous scene as HELD."""
        target = self.get_scene(scene_id)
        if target is None:
            raise KeyError(f"Unknown visual scene: {scene_id}")
        if target.scene_id == self.active_scene_id:
            return target

        previous = self.active_scene
        if previous.state == "ACTIVE":
            previous.transition_state("HELD")

        if target.state in ("INACTIVE", "ARCHIVED"):
            target.transition_state("PREPARED")
        if target.state == "PREPARED":
            target.transition_state("ENTERING")
        if target.state in ("ENTERING", "HELD", "SAFE_FALLBACK"):
            target.transition_state("ACTIVE")
        if target.state != "ACTIVE":
            raise ValueError(
                f"Scene {target.scene_id} cannot be selected from state {target.state}."
            )
        self.active_scene_id = target.scene_id
        return target

    def duplicate_scene(
        self, scene_id: str | None = None, *, name: str | None = None
    ) -> VisualScene:
        """Duplicate scene identity and renderer state without sharing layer IDs."""
        source_id = str(scene_id or self.active_scene_id)
        source = self.get_scene(source_id)
        if source is None:
            raise KeyError(f"Unknown visual scene: {source_id}")

        layer_id_map: dict[str, str] = {}
        duplicated_layers: list[dict] = []
        for record in self.layers_for_scene(source_id):
            clean = dict(record)
            old_layer_id = str(clean.pop("layer_id", ""))
            clean["name"] = f"{clean.get('name', 'Layer')} COPY"
            layer = VisualLayer.from_dict(clean)
            if old_layer_id:
                layer_id_map[old_layer_id] = layer.layer_id
            duplicated_layers.append(layer.to_dict())

        clone = VisualScene.from_dict(source.to_dict())
        clone.scene_id = _new_id("scene")
        clone.name = str(name or f"{source.name} COPY")
        clone.state = "INACTIVE"
        clone.role = "variation"
        clone.transition_in = ""
        clone.transition_out = ""
        clone.fallback_scene_id = ""
        clone.metadata = deepcopy(clone.metadata)
        clone.metadata["duplicated_from_scene_id"] = source.scene_id
        clone.layer_order = [
            layer_id_map[layer_id]
            for layer_id in clone.layer_order
            if layer_id in layer_id_map
        ]

        object_id_map: dict[str, str] = {}
        for visual_object in clone.objects:
            old_object_id = visual_object.object_id
            object_id_map[old_object_id] = _new_id("obj")
            visual_object.object_id = object_id_map[old_object_id]
            old_layer_id = visual_object.layer_id
            if old_layer_id and old_layer_id not in layer_id_map:
                # Archived graph objects can outlive their backing layer record.
                # Give those identities a fresh layer key too, so duplication
                # never creates two scenes that claim the same renderer layer.
                layer_id_map[old_layer_id] = uuid4().hex[:10]
            visual_object.layer_id = layer_id_map.get(
                old_layer_id, old_layer_id
            )
            visual_object.lineage = [
                *visual_object.lineage,
                old_object_id,
            ]
            visual_object.metadata = deepcopy(visual_object.metadata)
            visual_object.metadata["duplicated_from_object_id"] = old_object_id

        for relationship in clone.relationships:
            relationship.relationship_id = _new_id("rel")
            relationship.source_object_id = object_id_map.get(
                relationship.source_object_id,
                relationship.source_object_id,
            )
            relationship.target_object_id = object_id_map.get(
                relationship.target_object_id,
                relationship.target_object_id,
            )

        attention = deepcopy(clone.attention_plan)
        if attention.get("primary"):
            attention["primary"] = object_id_map.get(
                attention["primary"], attention["primary"]
            )
        for key in ("secondary", "background"):
            attention[key] = [
                object_id_map.get(value, value)
                for value in attention.get(key, [])
            ]
        clone.attention_plan = attention
        self.register_scene(clone, duplicated_layers)
        return clone

    def set_cue_route(
        self,
        cue_id: str,
        target_scene_id: str,
        *,
        source_scene_id: str | None = None,
        family: str = "dissolve",
        duration_seconds: float = 2.0,
        easing: str = "smoothstep",
        interruption_policy: str = "cancel",
        outgoing_policy: str = "archive",
        object_correspondence: list[dict] | None = None,
        path_correspondence: list[dict] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        cue_id = str(cue_id)
        source_id = str(source_scene_id or self.active_scene_id)
        target_id = str(target_scene_id)
        if not cue_id:
            raise ValueError("A cue route requires a stable cue_id.")
        if self.get_scene(source_id) is None or self.get_scene(target_id) is None:
            raise ValueError("Cue route source and target must exist in this project.")
        if source_id == target_id:
            raise ValueError("A cue route must target a different scene.")

        contract = SceneTransition(
            source_scene_id=source_id,
            target_scene_id=target_id,
            family=family,
            duration_seconds=duration_seconds,
            easing=easing,
            interruption_policy=interruption_policy,
            outgoing_policy=outgoing_policy,
            object_correspondence=list(object_correspondence or []),
            path_correspondence=list(path_correspondence or []),
            metadata=dict(metadata or {}),
            trigger={"type": "tracker_cue", "cue_id": cue_id},
        )
        route = {
            "cue_id": cue_id,
            "source_scene_id": source_id,
            "target_scene_id": target_id,
            "family": contract.family,
            "duration_seconds": contract.duration_seconds,
            "easing": contract.easing,
            "interruption_policy": contract.interruption_policy,
            "outgoing_policy": contract.outgoing_policy,
            "object_correspondence": [dict(item) for item in contract.object_correspondence],
            "path_correspondence": [dict(item) for item in contract.path_correspondence],
            "metadata": dict(contract.metadata),
        }
        self.cue_routes = [
            item for item in self.cue_routes
            if str(item.get("cue_id", "")) != cue_id
        ]
        self.cue_routes.append(route)
        return deepcopy(route)

    def route_for_cue(self, cue_id: str) -> dict | None:
        route = next(
            (
                item for item in self.cue_routes
                if str(item.get("cue_id", "")) == str(cue_id)
            ),
            None,
        )
        return deepcopy(route) if route else None

    def add_transition(self, transition: SceneTransition) -> None:
        self.transitions.append(transition.to_dict())

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "version": self.version,
            "scenes": [scene.to_dict() for scene in self.scenes],
            "active_scene_id": self.active_scene_id,
            "layer_snapshots": deepcopy(self.layer_snapshots),
            "transitions": deepcopy(self.transitions),
            "cue_routes": deepcopy(self.cue_routes),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: dict | None) -> "VisualProject":
        data = _dict(values)
        scenes = [
            VisualScene.from_dict(item)
            for item in data.get("scenes", [])
            if isinstance(item, dict)
        ]
        return cls(
            project_id=str(data.get("project_id") or _new_id("vproject")),
            name=str(data.get("name") or "WAVEFORMING PROJECT"),
            version=max(1, int(data.get("version", 1))),
            scenes=scenes,
            active_scene_id=str(data.get("active_scene_id", "")),
            layer_snapshots=_dict(data.get("layer_snapshots")),
            transitions=[
                item for item in data.get("transitions", [])
                if isinstance(item, dict)
            ],
            cue_routes=[
                item for item in data.get("cue_routes", [])
                if isinstance(item, dict)
            ],
            metadata=_dict(data.get("metadata")),
        )

    @classmethod
    def from_legacy(
        cls, scene: VisualScene, layers: Any
    ) -> "VisualProject":
        """Migrate the single-scene M11/M12 project representation."""
        return cls(
            scenes=[scene],
            active_scene_id=scene.scene_id,
            layer_snapshots={scene.scene_id: _layer_records(layers)},
            metadata={"migration": "single_scene_project"},
        )
