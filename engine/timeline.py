from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from uuid import uuid4

from engine.visual.generators import GeneratorSettings


@dataclass(slots=True)
class TimelineMarker:
    time: float
    label: str
    kind: str = "MARKER"
    marker_id: str = field(default_factory=lambda: uuid4().hex[:10])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineMarker":
        return cls(
            time=max(0.0, float(data.get("time", 0.0))),
            label=str(data.get("label", "MARKER")),
            kind=str(data.get("kind", "MARKER")).upper(),
            marker_id=str(data.get("marker_id") or uuid4().hex[:10]),
        )


@dataclass(slots=True)
class AutomationPoint:
    time: float
    value: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AutomationPoint":
        return cls(max(0.0, float(data["time"])), float(data["value"]))


@dataclass(slots=True)
class AutomationLane:
    target: str
    points: list[AutomationPoint] = field(default_factory=list)
    interpolation: str = "LINEAR"

    def record(self, seconds: float, value: float, merge_window: float = 0.025) -> None:
        seconds = max(0.0, float(seconds))
        value = float(value)
        for index, point in enumerate(self.points):
            if abs(point.time - seconds) <= merge_window:
                self.points[index] = AutomationPoint(seconds, value)
                break
        else:
            self.points.append(AutomationPoint(seconds, value))
        self.points.sort(key=lambda point: point.time)

    def evaluate(self, seconds: float, default: float) -> float:
        if not self.points:
            return float(default)
        t = max(0.0, float(seconds))
        if t <= self.points[0].time:
            return float(self.points[0].value)
        if t >= self.points[-1].time:
            return float(self.points[-1].value)

        for left, right in zip(self.points, self.points[1:]):
            if left.time <= t <= right.time:
                span = max(1e-9, right.time - left.time)
                alpha = (t - left.time) / span
                mode = self.interpolation.upper()
                if mode in ("HOLD", "STEP"):
                    alpha = 0.0
                elif mode in ("SMOOTH", "SMOOTHSTEP"):
                    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                return float(left.value + (right.value - left.value) * alpha)
        return float(default)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "interpolation": self.interpolation,
            "points": [point.to_dict() for point in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AutomationLane":
        lane = cls(
            target=str(data.get("target", "motion")),
            interpolation=str(data.get("interpolation", "LINEAR")).upper(),
        )
        lane.points = sorted(
            (AutomationPoint.from_dict(point) for point in data.get("points", [])),
            key=lambda point: point.time,
        )
        return lane


class Timeline:
    """Serializable marker/section timeline with deterministic parameter automation."""

    TARGETS = ("complexity", "motion", "sensitivity")

    def __init__(self, bpm: float = 120.0, beats_per_bar: int = 4):
        self.bpm = float(min(300.0, max(20.0, bpm)))
        self.beats_per_bar = int(min(12, max(1, beats_per_bar)))
        self.duration = 0.0
        self.markers: list[TimelineMarker] = []
        self.lanes: dict[str, AutomationLane] = {
            name: AutomationLane(name) for name in self.TARGETS
        }

    @property
    def beat_duration(self) -> float:
        return 60.0 / max(1e-6, self.bpm)

    @property
    def bar_duration(self) -> float:
        return self.beat_duration * self.beats_per_bar

    def set_duration(self, seconds: float) -> None:
        self.duration = max(0.0, float(seconds))

    def add_marker(self, seconds: float, label: str | None = None,
                   kind: str = "MARKER") -> TimelineMarker:
        next_number = 1 + sum(1 for marker in self.markers if marker.kind == kind.upper())
        marker = TimelineMarker(
            time=min(self.duration, max(0.0, float(seconds))) if self.duration else max(0.0, float(seconds)),
            label=label or f"{kind.title()} {next_number:02d}",
            kind=kind.upper(),
        )
        self.markers.append(marker)
        self.markers.sort(key=lambda item: item.time)
        return marker

    def remove_marker(self, marker_id: str) -> bool:
        before = len(self.markers)
        self.markers = [marker for marker in self.markers if marker.marker_id != marker_id]
        return len(self.markers) != before

    def remove_nearest_marker(self, seconds: float, maximum_distance: float = 2.0) -> bool:
        if not self.markers:
            return False
        nearest = min(self.markers, key=lambda marker: abs(marker.time - float(seconds)))
        if abs(nearest.time - float(seconds)) > max(0.0, float(maximum_distance)):
            return False
        return self.remove_marker(nearest.marker_id)

    def record(self, target: str, seconds: float, value: float) -> None:
        if target not in self.TARGETS:
            raise ValueError(f"Unsupported automation target: {target}")
        self.lanes[target].record(seconds, value)

    def value_at(self, target: str, seconds: float, default: float) -> float:
        lane = self.lanes.get(target)
        return lane.evaluate(seconds, default) if lane else float(default)

    def settings_at(self, seconds: float, base: GeneratorSettings) -> GeneratorSettings:
        return replace(
            base,
            complexity=self.value_at("complexity", seconds, base.complexity),
            motion=self.value_at("motion", seconds, base.motion),
            sensitivity=self.value_at("sensitivity", seconds, base.sensitivity),
        )

    def snap_to_beat(self, seconds: float, subdivision: int = 1) -> float:
        subdivision = max(1, min(16, int(subdivision)))
        quantum = self.beat_duration / subdivision
        return max(0.0, round(float(seconds) / quantum) * quantum)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "bpm": self.bpm,
            "beats_per_bar": self.beats_per_bar,
            "duration": self.duration,
            "markers": [marker.to_dict() for marker in self.markers],
            "lanes": {name: lane.to_dict() for name, lane in self.lanes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Timeline":
        data = data or {}
        timeline = cls(
            bpm=float(data.get("bpm", 120.0)),
            beats_per_bar=int(data.get("beats_per_bar", 4)),
        )
        timeline.duration = max(0.0, float(data.get("duration", 0.0)))
        timeline.markers = sorted(
            (TimelineMarker.from_dict(item) for item in data.get("markers", [])),
            key=lambda item: item.time,
        )
        supplied = data.get("lanes", {})
        for target in cls.TARGETS:
            if target in supplied:
                timeline.lanes[target] = AutomationLane.from_dict(supplied[target])
        return timeline
