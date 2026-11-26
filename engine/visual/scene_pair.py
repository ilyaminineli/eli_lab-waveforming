from __future__ import annotations

"""Shared outgoing/incoming scene-pair contract for transition rendering."""

import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any

from .transitions import TRANSITION_FAMILIES


RENDERED_TRANSITION_MODES = {
    "dissolve": "crossfade",
    "cut": "cut",
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
    metadata: dict = field(default_factory=dict)
    version: int = 1

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
            metadata={
                "trigger": deepcopy(
                    next(
                        (
                            item.get("trigger", {})
                            for item in reversed(project.transitions)
                            if item.get("transition_id") == sample_data.get("transition_id")
                        ),
                        {},
                    )
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
    # Unsupported future families retain the legacy lifecycle-only behavior;
    # they do not masquerade as a dissolve until their renderer is implemented.
    return incoming.copy() if resolved.completed else outgoing.copy()
