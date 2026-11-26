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
