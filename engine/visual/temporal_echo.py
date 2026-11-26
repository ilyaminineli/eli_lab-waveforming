from __future__ import annotations

"""Time-addressable, transition-local frame history for temporal echo."""

import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True, slots=True)
class TemporalEchoSettings:
    """Validated temporal-echo controls stored in SceneTransition.metadata."""

    enabled: bool = True
    history_seconds: float = 0.48
    max_samples: int = 8
    sample_interval_seconds: float = 0.125
    strength: float = 0.42
    decay: float = 0.72
    offset_x: float = 0.0
    offset_y: float = 0.0
    direction_x: float = 1.0
    direction_y: float = 0.0
    directional_persistence: float = 0.025
    history_scale: float = 0.5
    blend_mode: str = "Screen"

    @classmethod
    def from_mapping(cls, values: Any = None) -> "TemporalEchoSettings":
        data = dict(values) if isinstance(values, dict) else {}
        defaults = cls()
        enabled = data.get("enabled", defaults.enabled)
        if not isinstance(enabled, bool):
            raise ValueError("temporal_echo.enabled must be a boolean.")

        def finite(name: str, default: float, lower: float, upper: float) -> float:
            try:
                value = float(data.get(name, default))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"temporal_echo.{name} must be numeric.") from exc
            if not math.isfinite(value) or value < lower or value > upper:
                raise ValueError(
                    f"temporal_echo.{name} must be finite and in [{lower}, {upper}]."
                )
            return value

        try:
            max_samples = int(data.get("max_samples", defaults.max_samples))
        except (TypeError, ValueError) as exc:
            raise ValueError("temporal_echo.max_samples must be an integer.") from exc
        if max_samples < 2 or max_samples > 32:
            raise ValueError("temporal_echo.max_samples must be between 2 and 32.")

        blend_mode = str(data.get("blend_mode", defaults.blend_mode)).title()
        if blend_mode not in {"Screen", "Add", "Lighten", "Overlay", "Normal"}:
            raise ValueError(
                "temporal_echo.blend_mode must be Screen, Add, Lighten, Overlay or Normal."
            )
        direction_x = finite("direction_x", defaults.direction_x, -100.0, 100.0)
        direction_y = finite("direction_y", defaults.direction_y, -100.0, 100.0)
        direction_length = math.hypot(direction_x, direction_y)
        if direction_length > 1e-9:
            direction_x /= direction_length
            direction_y /= direction_length

        return cls(
            enabled=enabled,
            history_seconds=finite("history_seconds", defaults.history_seconds, 0.05, 8.0),
            max_samples=max_samples,
            sample_interval_seconds=finite(
                "sample_interval_seconds", defaults.sample_interval_seconds, 0.005, 1.0
            ),
            strength=finite("strength", defaults.strength, 0.0, 1.0),
            decay=finite("decay", defaults.decay, 0.0, 0.99),
            offset_x=finite("offset_x", defaults.offset_x, -1.0, 1.0),
            offset_y=finite("offset_y", defaults.offset_y, -1.0, 1.0),
            direction_x=direction_x,
            direction_y=direction_y,
            directional_persistence=finite(
                "directional_persistence", defaults.directional_persistence, 0.0, 1.0
            ),
            history_scale=finite("history_scale", defaults.history_scale, 0.125, 1.0),
            blend_mode=blend_mode,
        )


@dataclass(slots=True)
class _FrameSample:
    timestamp: float
    frame: Image.Image


class TemporalEchoHistoryBuffer:
    """Bounded timestamped history, isolated by transition identity.

    The buffer stores downsampled immutable source frames. prepare() returns
    previous samples as drawable overlays, then records the current base frame.
    It never records the already-echoed result, preventing recursive feedback.
    """

    def __init__(self) -> None:
        self._transition_id = ""
        self._last_timestamp: float | None = None
        self._frame_size: tuple[int, int] | None = None
        self._samples: deque[_FrameSample] = deque()
        self.last_reset_reason = "initial"

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def transition_id(self) -> str:
        return self._transition_id

    def reset(self, reason: str = "manual") -> None:
        self._transition_id = ""
        self._last_timestamp = None
        self._frame_size = None
        self._samples.clear()
        self.last_reset_reason = str(reason)

    def prepare(
        self,
        frame: Image.Image,
        *,
        timestamp: float,
        transition_id: str,
        settings: TemporalEchoSettings,
    ) -> tuple[list[tuple[Image.Image, tuple[int, int], float]], dict]:
        """Return image/offset/opacity overlays from prior timestamps."""
        now = float(timestamp)
        if not math.isfinite(now):
            raise ValueError("Temporal echo timestamp must be finite.")
        identity = str(transition_id).strip()
        if not identity:
            raise ValueError("Temporal echo requires a stable transition ID.")

        if not settings.enabled:
            self.reset("disabled")
            return [], {
                "sample_count": 0,
                "buffer_size": 0,
                "sampled_current_frame": False,
                "oldest_age_seconds": 0.0,
                "reset_reason": "disabled",
            }

        reset_reason = ""
        if self._transition_id and identity != self._transition_id:
            reset_reason = "transition_changed"
        elif self._frame_size is not None and frame.size != self._frame_size:
            reset_reason = "frame_size_changed"
        elif self._last_timestamp is not None and now < self._last_timestamp - 1e-9:
            reset_reason = "backward_seek"
        if reset_reason:
            self.reset(reset_reason)

        self._transition_id = identity
        self._frame_size = frame.size
        self.last_reset_reason = reset_reason or self.last_reset_reason

        # Re-rendering the same timestamp replaces that sample rather than
        # creating a zero-age echo of itself.
        replace_latest = bool(
            self._samples
            and abs(self._samples[-1].timestamp - now) <= 1e-9
        )
        if replace_latest:
            self._samples.pop()
        record_sample = (
            replace_latest
            or not self._samples
            or now - self._samples[-1].timestamp
            >= settings.sample_interval_seconds - 1e-9
        )

        while self._samples and now - self._samples[0].timestamp > settings.history_seconds:
            self._samples.popleft()

        history = [
            sample for sample in self._samples
            if 1e-9 < now - sample.timestamp <= settings.history_seconds
        ]
        overlays: list[tuple[Image.Image, tuple[int, int], float]] = []
        if settings.enabled and settings.strength > 0.0 and history:
            raw_weights = [
                settings.decay ** (
                    (now - sample.timestamp) / settings.sample_interval_seconds
                )
                for sample in history
            ]
            weight_total = sum(raw_weights)
            if weight_total > 1e-12:
                width, height = frame.size
                for sample, raw_weight in zip(history, raw_weights):
                    age_fraction = min(
                        1.0, max(0.0, (now - sample.timestamp) / settings.history_seconds)
                    )
                    dx_fraction = (
                        settings.offset_x
                        + settings.direction_x * settings.directional_persistence
                    ) * age_fraction
                    dy_fraction = (
                        settings.offset_y
                        + settings.direction_y * settings.directional_persistence
                    ) * age_fraction
                    dx = int(round(dx_fraction * width))
                    dy = int(round(dy_fraction * height))
                    sample_image = sample.frame
                    if sample_image.size != frame.size:
                        sample_image = sample_image.resize(
                            frame.size, Image.Resampling.BILINEAR
                        )
                    if dx or dy:
                        sample_image = sample_image.transform(
                            frame.size,
                            Image.Transform.AFFINE,
                            (1, 0, -dx, 0, 1, -dy),
                            resample=Image.Resampling.BILINEAR,
                        )
                    # Preserve absolute age decay when only one (or a few)
                    # history samples are available; cap aggregate opacity at
                    # the authored strength once the weighted stack exceeds 1.
                    opacity = (
                        settings.strength * raw_weight / max(1.0, weight_total)
                    )
                    overlays.append((sample_image, (0, 0), opacity))

        scaled_size = (
            max(1, int(round(frame.width * settings.history_scale))),
            max(1, int(round(frame.height * settings.history_scale))),
        )
        stored = frame.convert("RGBA")
        if scaled_size != frame.size:
            stored = stored.resize(scaled_size, Image.Resampling.BILINEAR)
        if record_sample:
            self._samples.append(_FrameSample(now, stored.copy()))
            while len(self._samples) > settings.max_samples:
                self._samples.popleft()
        self._last_timestamp = now

        oldest_age = max(0.0, now - history[0].timestamp) if history else 0.0
        return overlays, {
            "sample_count": len(overlays),
            "buffer_size": len(self._samples),
            "sampled_current_frame": record_sample,
            "oldest_age_seconds": oldest_age,
            "reset_reason": reset_reason,
        }
