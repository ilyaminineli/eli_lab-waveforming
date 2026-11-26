from __future__ import annotations

"""Scene-transition contracts and a deterministic scene lifecycle controller."""

import math
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .scene import VisualScene


TRANSITION_FAMILIES = frozenset({
    "cut", "dissolve", "morph", "assembly", "erosion", "mask_reveal",
    "displacement", "camera", "palette", "attention_transfer",
    "temporal_echo", "negative", "split_merge", "hard_reset",
})
TRANSITION_EASINGS = frozenset({
    "linear", "smoothstep", "ease_in", "ease_out", "ease_in_out",
})
INTERRUPTION_POLICIES = frozenset({"reject", "complete", "cancel"})
OUTGOING_POLICIES = frozenset({"archive", "hold"})
TRANSITION_PHASES = ("PREPARATION", "TRANSFORMATION", "ESTABLISHMENT")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def normalize_path_correspondence(
    value: Any,
    object_pairs: set[tuple[str, str]] | None = None,
) -> list[dict]:
    """Validate authored path mappings, including one-to-many split/merge groups.

    Anchors are normalized arc-length fractions on each path. Missing endpoints
    are added automatically. Anchor order must remain monotonic on both paths.
    """
    if not isinstance(value, list):
        return []
    normalized = []
    used_source: set[tuple[str, str]] = set()
    used_target: set[tuple[str, str]] = set()
    allowed_pairs = set(object_pairs or ())
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Path correspondence entries must be mappings.")
        source_object_id = str(raw.get("source_object_id", "")).strip()
        target_object_id = str(raw.get("target_object_id", "")).strip()
        if not source_object_id or not target_object_id:
            raise ValueError("Path correspondence requires source and target object IDs.")
        pair = (source_object_id, target_object_id)
        if object_pairs is not None and pair not in allowed_pairs:
            raise ValueError(
                "Path correspondence must belong to a declared object correspondence."
            )

        def path_ids(key: str) -> list[str]:
            raw_ids = raw.get(key, [])
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            if not isinstance(raw_ids, list):
                raise ValueError(f"{key} must be a path ID or a list of path IDs.")
            result = [str(item).strip() for item in raw_ids]
            if not result or any(not item for item in result):
                raise ValueError(f"{key} must contain non-empty path IDs.")
            if len(result) != len(set(result)):
                raise ValueError(f"{key} contains duplicate path IDs.")
            return result

        source_ids = path_ids("source_path_ids")
        target_ids = path_ids("target_path_ids")
        mode = str(raw.get("mode", "pair")).strip().lower()
        expected = {
            "pair": (1, 1),
            "split": (1, None),
            "merge": (None, 1),
        }
        if mode not in expected:
            raise ValueError("Path correspondence mode must be pair, split or merge.")
        source_count, target_count = expected[mode]
        if source_count is not None and len(source_ids) != source_count:
            raise ValueError(f"{mode} correspondence requires {source_count} source path.")
        if target_count is not None and len(target_ids) != target_count:
            raise ValueError(f"{mode} correspondence requires {target_count} target path.")
        if mode == "split" and len(target_ids) < 2:
            raise ValueError("A split correspondence requires at least two target paths.")
        if mode == "merge" and len(source_ids) < 2:
            raise ValueError("A merge correspondence requires at least two source paths.")

        anchors_raw = raw.get("anchors", [])
        if not isinstance(anchors_raw, list):
            raise ValueError("Path anchors must be a list of normalized arc-length pairs.")
        anchors = []
        for anchor in anchors_raw:
            if not isinstance(anchor, dict):
                raise ValueError("Each path anchor must be a mapping.")
            source_t = float(anchor.get("source_t", anchor.get("source", 0.0)))
            target_t = float(anchor.get("target_t", anchor.get("target", 0.0)))
            if (
                not math.isfinite(source_t) or not math.isfinite(target_t)
                or source_t < 0.0 or source_t > 1.0
                or target_t < 0.0 or target_t > 1.0
            ):
                raise ValueError("Path anchor positions must be finite values in [0, 1].")
            anchors.append({"source_t": source_t, "target_t": target_t})
        anchors.sort(key=lambda item: item["source_t"])
        if not anchors or anchors[0]["source_t"] > 1e-9:
            anchors.insert(0, {"source_t": 0.0, "target_t": 0.0})
        elif abs(anchors[0]["source_t"]) <= 1e-9:
            if abs(anchors[0]["target_t"]) > 1e-9:
                raise ValueError("The first path anchor must start at (0, 0).")
        if anchors[-1]["source_t"] < 1.0 - 1e-9:
            anchors.append({"source_t": 1.0, "target_t": 1.0})
        elif abs(anchors[-1]["source_t"] - 1.0) <= 1e-9:
            if abs(anchors[-1]["target_t"] - 1.0) > 1e-9:
                raise ValueError("The final path anchor must end at (1, 1).")
        for previous, current in zip(anchors, anchors[1:]):
            if (
                current["source_t"] <= previous["source_t"]
                or current["target_t"] <= previous["target_t"]
            ):
                raise ValueError("Path anchors must be strictly increasing on both paths.")

        for path_id in source_ids:
            key = (source_object_id, path_id)
            if key in used_source:
                raise ValueError(f"Outgoing path is mapped more than once: {path_id}")
            used_source.add(key)
        for path_id in target_ids:
            key = (target_object_id, path_id)
            if key in used_target:
                raise ValueError(f"Incoming path is mapped more than once: {path_id}")
            used_target.add(key)
        normalized.append({
            "source_object_id": source_object_id,
            "target_object_id": target_object_id,
            "source_path_ids": source_ids,
            "target_path_ids": target_ids,
            "mode": mode,
            "anchors": anchors,
        })
    return normalized


@dataclass(slots=True)
class SceneTransition:
    """A declarative transition contract between two persistent scenes.

    The contract describes timing, trigger, easing, object preservation and
    interruption. It does not render pixels; the compositor receives resolved
    scene state after the controller has applied the lifecycle decision.
    """

    transition_id: str = field(default_factory=lambda: _new_id("transition"))
    source_scene_id: str = ""
    target_scene_id: str = ""
    family: str = "dissolve"
    duration_seconds: float = 2.0
    trigger: dict = field(default_factory=lambda: {"type": "manual"})
    easing: str = "smoothstep"
    preparation_fraction: float = 0.15
    transformation_fraction: float = 0.70
    preserved_object_ids: list[str] = field(default_factory=list)
    discarded_object_ids: list[str] = field(default_factory=list)
    object_correspondence: list[dict] = field(default_factory=list)
    path_correspondence: list[dict] = field(default_factory=list)
    interruption_policy: str = "reject"
    outgoing_policy: str = "archive"
    seed: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        family = str(self.family).lower()
        easing = str(self.easing).lower()
        interruption = str(self.interruption_policy).lower()
        outgoing = str(self.outgoing_policy).lower()
        if family not in TRANSITION_FAMILIES:
            raise ValueError(f"Unsupported transition family: {family}")
        if easing not in TRANSITION_EASINGS:
            raise ValueError(f"Unsupported transition easing: {easing}")
        if interruption not in INTERRUPTION_POLICIES:
            raise ValueError(f"Unsupported interruption policy: {interruption}")
        if outgoing not in OUTGOING_POLICIES:
            raise ValueError(f"Unsupported outgoing-scene policy: {outgoing}")
        self.family = family
        self.easing = easing
        self.interruption_policy = interruption
        self.outgoing_policy = outgoing
        duration = float(self.duration_seconds)
        if not math.isfinite(duration) or duration < 0.0:
            raise ValueError("Transition duration must be a finite non-negative number.")
        self.duration_seconds = duration
        self.preparation_fraction = float(self.preparation_fraction)
        self.transformation_fraction = float(self.transformation_fraction)
        if (
            not math.isfinite(self.preparation_fraction)
            or not math.isfinite(self.transformation_fraction)
            or self.preparation_fraction < 0.0
            or self.transformation_fraction < 0.0
            or self.preparation_fraction + self.transformation_fraction > 1.0
        ):
            raise ValueError("Transition phase fractions must sum to at most 1.")
        self.trigger = _dict(self.trigger)
        self.metadata = _dict(self.metadata)
        self.preserved_object_ids = list(dict.fromkeys(_strings(self.preserved_object_ids)))
        self.discarded_object_ids = list(dict.fromkeys(_strings(self.discarded_object_ids)))
        correspondence = []
        source_seen, target_seen = set(), set()
        for item in self.object_correspondence if isinstance(self.object_correspondence, list) else []:
            if not isinstance(item, dict):
                raise ValueError("Object correspondence entries must be mappings.")
            source_id = str(item.get("source_object_id", item.get("source_id", ""))).strip()
            target_id = str(item.get("target_object_id", item.get("target_id", ""))).strip()
            if not source_id or not target_id:
                raise ValueError("Every object correspondence requires source and target object IDs.")
            if source_id in source_seen or target_id in target_seen:
                raise ValueError("Object correspondence must be one-to-one on both scene sides.")
            source_seen.add(source_id)
            target_seen.add(target_id)
            correspondence.append({
                "source_object_id": source_id,
                "target_object_id": target_id,
                "kind": "explicit",
            })
        object_pairs = {
            (item["source_object_id"], item["target_object_id"])
            for item in correspondence
        }
        path_correspondence = normalize_path_correspondence(
            self.path_correspondence
        )
        # An authored path map also declares the parent VisualObject match.
        for item in path_correspondence:
            pair = (item["source_object_id"], item["target_object_id"])
            if pair in object_pairs:
                continue
            source_id, target_id = pair
            if source_id in source_seen or target_id in target_seen:
                raise ValueError(
                    "Path correspondence conflicts with one-to-one object correspondence."
                )
            source_seen.add(source_id)
            target_seen.add(target_id)
            object_pairs.add(pair)
            correspondence.append({
                "source_object_id": source_id,
                "target_object_id": target_id,
                "kind": "path_map",
            })
        self.object_correspondence = correspondence
        self.path_correspondence = normalize_path_correspondence(
            path_correspondence, object_pairs
        )
        overlap = set(self.preserved_object_ids) & set(self.discarded_object_ids)
        if overlap:
            raise ValueError(
                "An object cannot be both preserved and discarded: "
                + ", ".join(sorted(overlap))
            )
        self.seed = int(self.seed)

    def _ease(self, progress: float) -> float:
        value = max(0.0, min(1.0, float(progress)))
        if self.easing == "linear":
            return value
        if self.easing == "ease_in":
            return value * value
        if self.easing == "ease_out":
            return 1.0 - (1.0 - value) ** 2
        # smoothstep and ease_in_out intentionally share a continuous,
        # zero-velocity-at-the-ends curve in the first implementation.
        return value * value * (3.0 - 2.0 * value)

    def sample(self, elapsed_seconds: float) -> dict:
        """Return deterministic phase and blend weights for elapsed show time."""
        elapsed = max(0.0, float(elapsed_seconds))
        raw = (
            1.0
            if self.duration_seconds <= 0.0
            else max(0.0, min(1.0, elapsed / self.duration_seconds))
        )
        if self.family == "cut":
            eased = 1.0 if raw >= 1.0 else 0.0
        else:
            eased = self._ease(raw)

        preparation_end = self.preparation_fraction
        transformation_end = min(
            1.0, preparation_end + self.transformation_fraction
        )
        if raw < preparation_end:
            phase = "PREPARATION"
        elif raw < transformation_end:
            phase = "TRANSFORMATION"
        else:
            phase = "ESTABLISHMENT"

        return {
            "transition_id": self.transition_id,
            "family": self.family,
            "elapsed_seconds": elapsed,
            "duration_seconds": self.duration_seconds,
            "progress": raw,
            "eased_progress": eased,
            "phase": phase,
            "outgoing_weight": 1.0 - eased,
            "incoming_weight": eased,
            "completed": raw >= 1.0,
            "object_correspondence": [dict(item) for item in self.object_correspondence],
            "path_correspondence": [dict(item) for item in self.path_correspondence],
            "metadata": dict(self.metadata),
            "seed": int(self.seed),
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict | None) -> "SceneTransition":
        data = _dict(values)
        allowed = cls.__dataclass_fields__
        clean = {key: value for key, value in data.items() if key in allowed}
        return cls(**clean)


@dataclass(slots=True)
class SceneTransitionProposal:
    """A proposed change that has not yet mutated either scene."""

    proposal_id: str = field(default_factory=lambda: _new_id("proposal"))
    transition: SceneTransition = field(default_factory=SceneTransition)
    proposed_at: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "transition": self.transition.to_dict(),
            "proposed_at": self.proposed_at,
            "rationale": self.rationale,
        }


class SceneTransitionController:
    """Deterministic scene-state controller with a separate proposal/commit API."""

    def __init__(self):
        self.scenes: dict[str, VisualScene] = {}
        self.active_scene_id = ""
        self.pending_proposal: SceneTransitionProposal | None = None
        self._active_transition: SceneTransition | None = None
        self._transition_started_at = 0.0

    @property
    def transition_active(self) -> bool:
        return self._active_transition is not None

    def register_scene(self, scene: VisualScene, *, active: bool = False) -> None:
        if not scene.scene_id:
            raise ValueError("A scene must have a stable scene_id before registration.")
        if scene.scene_id in self.scenes:
            raise ValueError(f"Scene already registered: {scene.scene_id}")
        if active and self.active_scene_id:
            raise ValueError("A controller can have only one active scene.")
        self.scenes[scene.scene_id] = scene
        if active:
            scene.state = "ACTIVE"
            self.active_scene_id = scene.scene_id
        elif scene.state == "ACTIVE":
            # Registration is initialisation, not a runtime state transition.
            scene.state = "INACTIVE"

    def propose(
        self,
        transition: SceneTransition,
        *,
        proposed_at: float,
        rationale: str = "",
    ) -> SceneTransitionProposal:
        """Validate a candidate without changing any scene state."""
        if self._active_transition is not None:
            raise RuntimeError("A scene transition is already active.")
        if self.pending_proposal is not None:
            raise RuntimeError("A scene transition proposal is already pending.")
        if transition.source_scene_id != self.active_scene_id:
            raise ValueError("Transition source must be the currently active scene.")
        if transition.source_scene_id not in self.scenes:
            raise ValueError("Transition source scene is not registered.")
        if transition.target_scene_id not in self.scenes:
            raise ValueError("Transition target scene is not registered.")
        if transition.target_scene_id == transition.source_scene_id:
            raise ValueError("A scene cannot transition to itself.")

        source = self.scenes[transition.source_scene_id]
        target = self.scenes[transition.target_scene_id]
        if source.state != "ACTIVE":
            raise ValueError("The source scene must be ACTIVE before a transition.")
        if target.state not in ("INACTIVE", "PREPARED", "HELD", "ARCHIVED"):
            raise ValueError(
                f"Target scene must be inactive or resumable, not {target.state}."
            )

        known_objects = {
            item.object_id
            for scene in (source, target)
            for item in scene.objects
        }
        requested_objects = (
            set(transition.preserved_object_ids)
            | set(transition.discarded_object_ids)
        )
        unknown = requested_objects - known_objects
        if unknown:
            raise ValueError(
                "Transition references unknown visual objects: "
                + ", ".join(sorted(unknown))
            )

        source_object_ids = {item.object_id for item in source.objects}
        target_object_ids = {item.object_id for item in target.objects}
        for pair in transition.object_correspondence:
            if pair["source_object_id"] not in source_object_ids:
                raise ValueError(
                    "Object correspondence source is not in the outgoing scene: "
                    + pair["source_object_id"]
                )
            if pair["target_object_id"] not in target_object_ids:
                raise ValueError(
                    "Object correspondence target is not in the incoming scene: "
                    + pair["target_object_id"]
                )

        proposal = SceneTransitionProposal(
            transition=transition,
            proposed_at=float(proposed_at),
            rationale=str(rationale),
        )
        self.pending_proposal = proposal
        return proposal

    def commit(self, proposal_id: str, *, start_time: float) -> dict:
        """Commit a previously validated proposal and begin the scene transition."""
        proposal = self.pending_proposal
        if proposal is None or proposal.proposal_id != str(proposal_id):
            raise ValueError("No matching scene-transition proposal is pending.")
        transition = proposal.transition
        source = self.scenes[transition.source_scene_id]
        target = self.scenes[transition.target_scene_id]
        if source.state != "ACTIVE" or self.active_scene_id != source.scene_id:
            raise RuntimeError("The active scene changed after the proposal was made.")

        if target.state in ("INACTIVE", "HELD", "ARCHIVED"):
            target.transition_state("PREPARED")
        target.transition_state("ENTERING")
        source.transition_state("EXITING")

        self._active_transition = transition
        self._transition_started_at = float(start_time)
        self.pending_proposal = None
        sample = transition.sample(0.0)
        sample.update({
            "source_scene_id": source.scene_id,
            "target_scene_id": target.scene_id,
            "committed": True,
        })
        if sample["completed"]:
            self._complete_transition()
            sample["source_state"] = source.state
            sample["target_state"] = target.state
            sample["active_scene_id"] = self.active_scene_id
        return sample

    def _complete_transition(self) -> None:
        transition = self._active_transition
        if transition is None:
            return
        source = self.scenes[transition.source_scene_id]
        target = self.scenes[transition.target_scene_id]
        if transition.outgoing_policy == "hold":
            source.transition_state("HELD")
        else:
            source.transition_state("ARCHIVED")
        target.transition_state("ACTIVE")
        self.active_scene_id = target.scene_id
        self._active_transition = None

    def sample(self, show_time: float) -> dict | None:
        """Advance by sampling absolute show time; no timers or background work."""
        transition = self._active_transition
        if transition is None:
            return None
        elapsed = max(0.0, float(show_time) - self._transition_started_at)
        result = transition.sample(elapsed)
        result.update({
            "source_scene_id": transition.source_scene_id,
            "target_scene_id": transition.target_scene_id,
            "committed": True,
        })
        if result["completed"]:
            self._complete_transition()
            result["source_state"] = self.scenes[transition.source_scene_id].state
            result["target_state"] = self.scenes[transition.target_scene_id].state
            result["active_scene_id"] = self.active_scene_id
        return result

    def interrupt(self) -> str:
        """Apply the active contract's declared interruption policy."""
        transition = self._active_transition
        if transition is None:
            return "no_transition"
        if transition.interruption_policy == "reject":
            return "rejected"

        if transition.interruption_policy == "complete":
            self._complete_transition()
            return "completed"

        source = self.scenes[transition.source_scene_id]
        target = self.scenes[transition.target_scene_id]
        source.transition_state("ACTIVE")
        target.transition_state("PREPARED")
        self.active_scene_id = source.scene_id
        self._active_transition = None
        return "cancelled"

    def cancel_proposal(self, proposal_id: str) -> bool:
        proposal = self.pending_proposal
        if proposal is None or proposal.proposal_id != str(proposal_id):
            return False
        self.pending_proposal = None
        return True
