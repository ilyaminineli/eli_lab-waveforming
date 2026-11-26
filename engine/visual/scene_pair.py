from __future__ import annotations

"""Shared outgoing/incoming scene-pair contract for transition rendering."""

import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from .transitions import TRANSITION_FAMILIES, normalize_path_correspondence


RENDERED_TRANSITION_MODES = {
    "dissolve": "crossfade",
    "cut": "cut",
    "morph": "object_morph",
    "assembly": "assembly",
    "erosion": "erosion",
}


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _records(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


@dataclass(slots=True)
class ScenePairRenderContract:
    """Immutable-by-snapshot renderer input for one active scene transition.

    Each side contains its own serialized VisualScene graph and renderer-layer
    records. The contract carries the exact M12 sample so preview and offline
    export do not independently reinterpret timing or easing.
    """

    transition_id: str
    source_scene_id: str
    target_scene_id: str
    family: str
    phase: str
    progress: float
    eased_progress: float
    outgoing_weight: float
    incoming_weight: float
    duration_seconds: float
    completed: bool = False
    render_mode: str = ""
    outgoing: dict = field(default_factory=dict)
    incoming: dict = field(default_factory=dict)
    object_correspondence: list[dict] = field(default_factory=list)
    path_correspondence: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    version: int = 3

    def __post_init__(self) -> None:
        self.transition_id = str(self.transition_id)
        self.source_scene_id = str(self.source_scene_id)
        self.target_scene_id = str(self.target_scene_id)
        self.family = str(self.family).lower()
        if self.family not in TRANSITION_FAMILIES:
            raise ValueError(f"Unsupported scene-pair family: {self.family}")
        if not self.source_scene_id or not self.target_scene_id:
            raise ValueError("A scene pair requires both source and target scene IDs.")
        if self.source_scene_id == self.target_scene_id:
            raise ValueError("A scene pair cannot render the same scene twice.")

        self.phase = str(self.phase).upper()
        if self.phase not in ("PREPARATION", "TRANSFORMATION", "ESTABLISHMENT"):
            raise ValueError(f"Unknown transition phase: {self.phase}")

        self.progress = self._finite_unit(self.progress, "progress")
        self.eased_progress = self._finite_unit(
            self.eased_progress, "eased_progress"
        )
        self.outgoing_weight = self._finite_unit(
            self.outgoing_weight, "outgoing_weight"
        )
        self.incoming_weight = self._finite_unit(
            self.incoming_weight, "incoming_weight"
        )
        if abs(self.outgoing_weight + self.incoming_weight - 1.0) > 1e-5:
            raise ValueError("Outgoing and incoming weights must sum to 1.")
        self.duration_seconds = float(self.duration_seconds)
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0.0:
            raise ValueError("Transition duration must be finite and non-negative.")

        self.completed = bool(self.completed)
        # Rendering capability is derived from the selected family, never
        # trusted from serialized data. This prevents a future family from
        # accidentally inheriting "crossfade" after changing its family name.
        expected_mode = RENDERED_TRANSITION_MODES.get(self.family, "hold")
        self.render_mode = expected_mode
        self.outgoing = self._clean_side(self.outgoing, self.source_scene_id)
        self.incoming = self._clean_side(self.incoming, self.target_scene_id)
        outgoing_layer_ids = {
            str(item["layer_id"]) for item in self.outgoing["layers"]
        }
        incoming_layer_ids = {
            str(item["layer_id"]) for item in self.incoming["layers"]
        }
        shared_layer_ids = outgoing_layer_ids & incoming_layer_ids
        if shared_layer_ids:
            raise ValueError(
                "Outgoing and incoming scene snapshots must own distinct layer IDs: "
                + ", ".join(sorted(shared_layer_ids))
            )

        outgoing_objects = _records(self.outgoing["scene"].get("objects"))
        incoming_objects = _records(self.incoming["scene"].get("objects"))
        outgoing_object_ids = {str(item.get("object_id", "")) for item in outgoing_objects}
        incoming_object_ids = {str(item.get("object_id", "")) for item in incoming_objects}
        if "" in outgoing_object_ids or "" in incoming_object_ids:
            raise ValueError("Every scene-pair VisualObject requires a stable object_id.")
        if len(outgoing_object_ids) != len(outgoing_objects):
            raise ValueError("Outgoing scene contains duplicate VisualObject IDs.")
        if len(incoming_object_ids) != len(incoming_objects):
            raise ValueError("Incoming scene contains duplicate VisualObject IDs.")

        normalized_pairs = []
        used_sources, used_targets = set(), set()
        for item in _records(self.object_correspondence):
            source_object_id = str(
                item.get("source_object_id", item.get("source_id", ""))
            ).strip()
            target_object_id = str(
                item.get("target_object_id", item.get("target_id", ""))
            ).strip()
            if not source_object_id or not target_object_id:
                raise ValueError("Object correspondence requires source and target IDs.")
            if source_object_id not in outgoing_object_ids:
                raise ValueError(
                    f"Correspondence source {source_object_id} is not in the outgoing scene."
                )
            if target_object_id not in incoming_object_ids:
                raise ValueError(
                    f"Correspondence target {target_object_id} is not in the incoming scene."
                )
            if source_object_id in used_sources or target_object_id in used_targets:
                raise ValueError("Scene-pair object correspondence must be one-to-one.")
            used_sources.add(source_object_id)
            used_targets.add(target_object_id)
            normalized_pairs.append({
                "source_object_id": source_object_id,
                "target_object_id": target_object_id,
                "kind": "explicit",
            })

        # Shared VisualObject IDs already define an unambiguous identity match.
        # Add them after explicit mappings; no name-based or fuzzy matching occurs.
        for object_id in sorted(outgoing_object_ids & incoming_object_ids):
            if object_id in used_sources or object_id in used_targets:
                continue
            normalized_pairs.append({
                "source_object_id": object_id,
                "target_object_id": object_id,
                "kind": "identity",
            })
            used_sources.add(object_id)
            used_targets.add(object_id)
        # A duplicated VisualScene deliberately receives fresh object IDs.
        # Its lineage/duplicated_from_object_id is an explicit, deterministic
        # ancestry signal and can therefore be used as a one-to-one match.
        candidates_by_source = {}
        candidates_by_target = {}
        for source_object in outgoing_objects:
            source_object_id = str(source_object.get("object_id", ""))
            if source_object_id in used_sources:
                continue
            for target_object in incoming_objects:
                target_object_id = str(target_object.get("object_id", ""))
                if target_object_id in used_targets:
                    continue
                target_metadata = _dict(target_object.get("metadata"))
                source_metadata = _dict(source_object.get("metadata"))
                target_lineage = set(
                    str(value) for value in target_object.get("lineage", [])
                )
                source_lineage = set(
                    str(value) for value in source_object.get("lineage", [])
                )
                related = (
                    source_object_id in target_lineage
                    or str(target_metadata.get("duplicated_from_object_id", "")) == source_object_id
                    or target_object_id in source_lineage
                    or str(source_metadata.get("duplicated_from_object_id", "")) == target_object_id
                )
                if related:
                    candidates_by_source.setdefault(source_object_id, []).append(target_object_id)
                    candidates_by_target.setdefault(target_object_id, []).append(source_object_id)
        for source_object_id, targets in candidates_by_source.items():
            if len(targets) != 1:
                continue
            target_object_id = targets[0]
            if len(candidates_by_target.get(target_object_id, [])) != 1:
                continue
            if source_object_id in used_sources or target_object_id in used_targets:
                continue
            normalized_pairs.append({
                "source_object_id": source_object_id,
                "target_object_id": target_object_id,
                "kind": "lineage",
            })
            used_sources.add(source_object_id)
            used_targets.add(target_object_id)

        self.object_correspondence = normalized_pairs
        object_pairs = {
            (item["source_object_id"], item["target_object_id"])
            for item in normalized_pairs
        }
        self.path_correspondence = normalize_path_correspondence(
            self.path_correspondence, object_pairs
        )
        self.metadata = _dict(self.metadata)
        self.version = max(1, int(self.version))

    @staticmethod
    def _finite_unit(value: Any, name: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{name} must be finite.")
        if result < -1e-6 or result > 1.0 + 1e-6:
            raise ValueError(f"{name} must be between 0 and 1.")
        return max(0.0, min(1.0, result))

    @staticmethod
    def _clean_side(value: Any, expected_scene_id: str) -> dict:
        side = _dict(value)
        scene = _dict(side.get("scene"))
        scene_id = str(scene.get("scene_id", ""))
        if scene_id != expected_scene_id:
            raise ValueError(
                f"Scene-pair side expected {expected_scene_id}, got {scene_id or 'no scene ID'}."
            )
        side["scene"] = scene
        side["layers"] = _records(side.get("layers"))
        layer_ids = [str(item.get("layer_id", "")) for item in side["layers"]]
        if any(not layer_id for layer_id in layer_ids):
            raise ValueError("Every scene-pair layer record requires a layer_id.")
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("A scene-pair side cannot contain duplicate layer IDs.")
        return side

    @classmethod
    def from_project(cls, project, sample: dict) -> "ScenePairRenderContract":
        """Capture two registered VisualScenes and their independent layer stacks."""
        sample_data = _dict(sample)
        source_id = str(sample_data.get("source_scene_id", ""))
        target_id = str(sample_data.get("target_scene_id", ""))
        source = project.get_scene(source_id)
        target = project.get_scene(target_id)
        if source is None or target is None:
            raise ValueError("Transition sample references a scene outside the project.")

        scene_states = {
            scene.scene_id: scene.state for scene in project.scenes
        }
        transition_record = next(
            (
                item for item in reversed(project.transitions)
                if item.get("transition_id") == sample_data.get("transition_id")
            ),
            {},
        )
        requested_correspondence = sample_data.get("object_correspondence")
        if not requested_correspondence:
            requested_correspondence = transition_record.get("object_correspondence", [])
        requested_path_correspondence = sample_data.get("path_correspondence")
        if not requested_path_correspondence:
            requested_path_correspondence = transition_record.get("path_correspondence", [])
        resolved = {
            "project_id": project.project_id,
            "active_scene_id": project.active_scene_id,
            "scene_states": scene_states,
            "transition_active": not bool(sample_data.get("completed", False)),
            "transition": deepcopy(sample_data),
        }
        outgoing_scene = source.to_dict()
        incoming_scene = target.to_dict()
        outgoing_scene["resolved_state"] = resolved
        incoming_scene["resolved_state"] = resolved
        return cls(
            transition_id=str(sample_data.get("transition_id", "")),
            source_scene_id=source_id,
            target_scene_id=target_id,
            family=str(sample_data.get("family", "dissolve")),
            phase=str(sample_data.get("phase", "TRANSFORMATION")),
            progress=float(sample_data.get("progress", 0.0)),
            eased_progress=float(sample_data.get("eased_progress", 0.0)),
            outgoing_weight=float(sample_data.get("outgoing_weight", 1.0)),
            incoming_weight=float(sample_data.get("incoming_weight", 0.0)),
            duration_seconds=float(sample_data.get("duration_seconds", 0.0)),
            completed=bool(sample_data.get("completed", False)),
            outgoing={
                "scene": outgoing_scene,
                "layers": project.layers_for_scene(source_id),
            },
            incoming={
                "scene": incoming_scene,
                "layers": project.layers_for_scene(target_id),
            },
            object_correspondence=_records(requested_correspondence),
            path_correspondence=_records(requested_path_correspondence),
            metadata={
                "trigger": deepcopy(transition_record.get("trigger", {})),
                "seed": int(transition_record.get("seed", sample_data.get("seed", 0))),
                "transition_metadata": deepcopy(
                    transition_record.get("metadata", sample_data.get("metadata", {}))
                ),
            },
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "ScenePairRenderContract":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        return cls(**clean)


def _lerp(a: Any, b: Any, progress: float) -> float:
    return float(a) + (float(b) - float(a)) * progress


def _lerp_angle(a: Any, b: Any, progress: float) -> float:
    start, end = float(a), float(b)
    delta = (end - start + 180.0) % 360.0 - 180.0
    return start + delta * progress


def _interpolate_structure(source: Any, target: Any, progress: float, path=()):
    if (
        isinstance(source, (int, float))
        and not isinstance(source, bool)
        and isinstance(target, (int, float))
        and not isinstance(target, bool)
    ):
        return _lerp(source, target, progress)
    if isinstance(source, list) and isinstance(target, list) and len(source) == len(target):
        result = []
        for index, (a, b) in enumerate(zip(source, target)):
            if path and path[-1] == "rotation" and index == 2:
                result.append(_lerp_angle(a, b, progress))
            else:
                result.append(_interpolate_structure(a, b, progress, path + (index,)))
        return result
    if isinstance(source, dict) and isinstance(target, dict):
        result = {}
        for key in dict.fromkeys([*source.keys(), *target.keys()]):
            if key in source and key in target:
                result[key] = _interpolate_structure(
                    source[key], target[key], progress, path + (str(key),)
                )
            elif key in source:
                result[key] = deepcopy(source[key])
            else:
                result[key] = deepcopy(target[key])
        return result
    return deepcopy(target if progress >= 0.5 else source)


def _interpolate_layer(source: dict, target: dict, progress: float) -> dict:
    result = deepcopy(source)
    for key in ("x_offset", "y_offset", "scale", "pass_strength"):
        result[key] = _lerp(
            source.get(key, 0.0), target.get(key, source.get(key, 0.0)), progress
        )
    result["rotation"] = _lerp_angle(
        source.get("rotation", 0.0),
        target.get("rotation", source.get("rotation", 0.0)),
        progress,
    )
    source_opacity = (
        float(source.get("opacity", 1.0)) if source.get("visible", True) else 0.0
    )
    target_opacity = (
        float(target.get("opacity", 1.0)) if target.get("visible", True) else 0.0
    )
    result["opacity"] = _lerp(source_opacity, target_opacity, progress)
    result["visible"] = result["opacity"] > 1e-5
    for key in (
        "name", "generator", "blend_mode", "mask_mode", "pass_map", "pass_mode",
        "source_id", "palette_mode", "palette_index", "role",
    ):
        if key in target and progress >= 0.5:
            result[key] = deepcopy(target[key])
    # Outgoing layer identity remains the simulation key throughout the morph.
    result["layer_id"] = str(source["layer_id"])
    return result


def _fade_layer(record: dict, weight: float) -> dict:
    result = deepcopy(record)
    result["opacity"] = float(result.get("opacity", 1.0)) * max(
        0.0, min(1.0, weight)
    )
    result["visible"] = (
        bool(result.get("visible", True)) and result["opacity"] > 1e-5
    )
    return result


def _interpolate_object(source: dict, target: dict, progress: float) -> dict:
    result = deepcopy(source)
    result["object_id"] = str(source["object_id"])
    result["layer_id"] = str(source.get("layer_id", ""))
    for key in ("geometry", "material", "transform", "animation_state"):
        result[key] = _interpolate_structure(
            _dict(source.get(key)), _dict(target.get(key)), progress, (key,)
        )
    result["salience"] = _lerp(
        source.get("salience", 0.5), target.get("salience", 0.5), progress
    )
    if progress >= 0.5:
        for key in (
            "name", "role", "source_method", "source_asset",
            "source_bindings", "metadata",
        ):
            if key in target:
                result[key] = deepcopy(target[key])
    result["lifecycle"] = "ACTIVE"
    result["lineage"] = list(dict.fromkeys(
        [*source.get("lineage", []), *target.get("lineage", [])]
    ))
    result["motion_history"] = deepcopy(
        target.get("motion_history", []) if progress >= 0.5
        else source.get("motion_history", [])
    )
    return result


def build_object_morph_state(
    contract: ScenePairRenderContract | dict,
) -> tuple[dict, list[dict]]:
    """Build one intermediate scene using the contract's explicit object matches.

    Matched objects become one renderer layer with interpolated spatial/material
    values. Unmatched outgoing/incoming objects fade by their respective weights.
    The screen/paper background is therefore rendered once and remains continuous.
    """
    resolved = (
        contract if isinstance(contract, ScenePairRenderContract)
        else ScenePairRenderContract.from_dict(contract)
    )
    progress = resolved.eased_progress
    outgoing_scene = _dict(resolved.outgoing.get("scene"))
    incoming_scene = _dict(resolved.incoming.get("scene"))
    outgoing_objects = _records(outgoing_scene.get("objects"))
    incoming_objects = _records(incoming_scene.get("objects"))
    outgoing_layers = _records(resolved.outgoing.get("layers"))
    incoming_layers = _records(resolved.incoming.get("layers"))

    outgoing_by_object = {str(item["object_id"]): item for item in outgoing_objects}
    incoming_by_object = {str(item["object_id"]): item for item in incoming_objects}
    outgoing_by_layer = {str(item["layer_id"]): item for item in outgoing_layers}
    incoming_by_layer = {str(item["layer_id"]): item for item in incoming_layers}

    target_for_source = {
        item["source_object_id"]: item["target_object_id"]
        for item in resolved.object_correspondence
    }
    output_layers: dict[str, dict] = {}
    output_objects: dict[str, dict] = {}
    incoming_layer_map: dict[str, str] = {}
    incoming_object_map = {
        object_id: object_id for object_id in incoming_by_object
    }
    matched_source_layers, matched_target_layers = set(), set()
    matched_source_objects, matched_target_objects = set(), set()

    for source_object_id, target_object_id in target_for_source.items():
        source_object = outgoing_by_object[source_object_id]
        target_object = incoming_by_object[target_object_id]
        source_layer_id = str(source_object.get("layer_id", ""))
        target_layer_id = str(target_object.get("layer_id", ""))
        source_layer = outgoing_by_layer.get(source_layer_id)
        target_layer = incoming_by_layer.get(target_layer_id)
        if not source_layer or not target_layer:
            continue
        output_layers[source_layer_id] = _interpolate_layer(
            source_layer, target_layer, progress
        )
        output_objects[source_object_id] = _interpolate_object(
            source_object, target_object, progress
        )
        output_objects[source_object_id]["layer_id"] = source_layer_id
        incoming_layer_map[target_layer_id] = source_layer_id
        incoming_object_map[target_object_id] = source_object_id
        matched_source_layers.add(source_layer_id)
        matched_target_layers.add(target_layer_id)
        matched_source_objects.add(source_object_id)
        matched_target_objects.add(target_object_id)

    for layer_id, layer in outgoing_by_layer.items():
        if layer_id not in matched_source_layers:
            output_layers[layer_id] = _fade_layer(layer, resolved.outgoing_weight)
    for layer_id, layer in incoming_by_layer.items():
        if layer_id not in matched_target_layers:
            output_layers[layer_id] = _fade_layer(layer, resolved.incoming_weight)
            incoming_layer_map[layer_id] = layer_id

    # Retain graph metadata for objects that are not part of a matched pair.
    for object_id, visual_object in outgoing_by_object.items():
        if object_id not in matched_source_objects:
            obj = deepcopy(visual_object)
            layer_id = str(obj.get("layer_id", ""))
            if layer_id in output_layers:
                weight = resolved.outgoing_weight
                obj["salience"] = float(obj.get("salience", 0.5)) * weight
                material = _dict(obj.get("material"))
                if "opacity" in material:
                    material["opacity"] = float(material["opacity"]) * weight
                obj["material"] = material
                output_objects[object_id] = obj
    for object_id, visual_object in incoming_by_object.items():
        if object_id not in matched_target_objects:
            obj = deepcopy(visual_object)
            layer_id = str(obj.get("layer_id", ""))
            if layer_id in output_layers:
                weight = resolved.incoming_weight
                obj["salience"] = float(obj.get("salience", 0.5)) * weight
                material = _dict(obj.get("material"))
                if "opacity" in material:
                    material["opacity"] = float(material["opacity"]) * weight
                obj["material"] = material
                output_objects[object_id] = obj

    # Preserve legacy renderer layers even when no VisualObject record exists.
    for layer_id, layer in outgoing_by_layer.items():
        output_layers.setdefault(
            layer_id, _fade_layer(layer, resolved.outgoing_weight)
        )
    for layer_id, layer in incoming_by_layer.items():
        if layer_id not in matched_target_layers:
            output_layers.setdefault(
                layer_id, _fade_layer(layer, resolved.incoming_weight)
            )
            incoming_layer_map.setdefault(layer_id, layer_id)

    source_order = [
        str(value) for value in outgoing_scene.get("layer_order", [])
        if str(value) in outgoing_by_layer
    ] or list(outgoing_by_layer)
    target_order = [
        incoming_layer_map.get(str(value), str(value))
        for value in incoming_scene.get("layer_order", [])
        if str(value) in incoming_by_layer
    ] or [
        incoming_layer_map.get(layer_id, layer_id)
        for layer_id in incoming_by_layer
    ]
    preferred_order = source_order if progress < 0.5 else target_order
    layer_order = list(dict.fromkeys(
        [*preferred_order, *source_order, *target_order, *output_layers.keys()]
    ))

    object_id_map = {
        object_id: object_id for object_id in outgoing_by_object
    } if progress < 0.5 else incoming_object_map
    chosen_scene = outgoing_scene if progress < 0.5 else incoming_scene
    relationships = _records(chosen_scene.get("relationships"))
    for relation in relationships:
        for key in ("source_object_id", "target_object_id"):
            value = str(relation.get(key, ""))
            relation[key] = object_id_map.get(value, value)
    attention = _dict(chosen_scene.get("attention_plan"))
    if attention.get("primary"):
        value = str(attention["primary"])
        attention["primary"] = object_id_map.get(value, value)
    for key in ("secondary", "background"):
        attention[key] = [
            object_id_map.get(str(value), str(value))
            for value in attention.get(key, [])
        ]

    morph_scene = deepcopy(chosen_scene)
    morph_scene["scene_id"] = (
        f"morph:{resolved.source_scene_id}:{resolved.target_scene_id}"
    )
    morph_scene["state"] = "ACTIVE"
    morph_scene["objects"] = list(output_objects.values())
    morph_scene["layer_order"] = layer_order
    morph_scene["relationships"] = relationships
    morph_scene["attention_plan"] = attention
    morph_scene["resolved_state"] = {
        **_dict(chosen_scene.get("resolved_state")),
        "transition_active": True,
        "transition": {
            "transition_id": resolved.transition_id,
            "family": resolved.family,
            "phase": resolved.phase,
            "progress": resolved.progress,
            "eased_progress": resolved.eased_progress,
            "object_correspondence": deepcopy(resolved.object_correspondence),
        },
    }
    return morph_scene, list(output_layers.values())


def blend_scene_pair_frames(
    outgoing_frame,
    incoming_frame,
    contract: ScenePairRenderContract | dict,
):
    """Blend two equal-sized RGBA frames according to the shared pair contract."""
    from PIL import Image

    resolved = (
        contract
        if isinstance(contract, ScenePairRenderContract)
        else ScenePairRenderContract.from_dict(contract)
    )
    if outgoing_frame.size != incoming_frame.size:
        raise ValueError(
            "Outgoing and incoming scene frames must have identical dimensions."
        )
    outgoing = outgoing_frame.convert("RGBA")
    incoming = incoming_frame.convert("RGBA")
    if resolved.render_mode == "crossfade":
        return Image.blend(
            outgoing, incoming, resolved.incoming_weight
        )
    if resolved.render_mode == "cut":
        return incoming.copy() if resolved.completed else outgoing.copy()
    if resolved.render_mode == "object_morph":
        raise ValueError("Object morphing must resolve a VisualScene graph before rendering.")
    # Unsupported future families retain the legacy lifecycle-only behavior;
    # they do not masquerade as a dissolve until their renderer is implemented.
    return incoming.copy() if resolved.completed else outgoing.copy()
