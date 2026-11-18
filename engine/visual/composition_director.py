from __future__ import annotations

import random
from dataclasses import dataclass

from .layers import VisualLayer

AUTO_GENERATORS = (
    "GEOMETRIC FIELD",
    "AXONOMETRIC FIELD",
    "POLYHEDRAL FIELD",
    "PHASE ORBIT",
    "PHASE LATTICE",
    "MOBIUS FIELD",
    "SPECTRAL TOPOGRAPHY",
    "PHYLLOTAXIS",
    "REACTION DIFFUSION",
)
BLEND_MODES = ("Normal", "Screen", "Add", "Difference", "Lighten")


@dataclass(slots=True)
class DirectorOutput:
    mode: str = "MANUAL"
    state: str = "DORMANT"
    energy: float = 0.0
    density: float = 0.0
    novelty: float = 0.0
    motion_scale: float = 1.0
    complexity_scale: float = 1.0
    glitch_amount: float = 0.0
    accent_amount: float = 0.0
    request_variation: bool = False


class CompositionDirector:
    """Audio-informed composition director with hysteresis and seeded variation requests."""

    MODES = ("MANUAL", "SEMI-AUTO", "AUTO")
    STATES = ("DORMANT", "EMERGENCE", "DEVELOPMENT", "INSTABILITY", "RELEASE")

    def __init__(self, mode: str = "SEMI-AUTO", *, variation_cooldown: float = 18.0):
        self.mode = mode if mode in self.MODES else "SEMI-AUTO"
        self.variation_cooldown = max(5.0, float(variation_cooldown))
        self.state = "DORMANT"
        self._candidate = self.state
        self._candidate_since = 0.0
        self._last_energy = 0.0
        self._last_variation = -1e9
        self._last_position = 0.0

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"Unsupported director mode: {mode}")
        self.mode = mode

    def reset(self) -> None:
        self.state = "DORMANT"
        self._candidate = self.state
        self._candidate_since = 0.0
        self._last_energy = 0.0
        self._last_variation = -1e9
        self._last_position = 0.0

    def update(self, packet: dict | None, position: float | None = None) -> DirectorOutput:
        packet = packet or {}
        features = packet.get("master_features") or {}
        now = float(packet.get("position", 0.0) if position is None else position)
        energy = float(features.get("energy", 0.0))
        density = float(features.get("density", 0.0))
        novelty = float(features.get("novelty", 0.0))
        onset = float(features.get("onset", 0.0))

        if energy < 0.025 and density < 0.04:
            candidate = "DORMANT"
        elif novelty > 0.72 and (density > 0.20 or onset > 0.62):
            candidate = "INSTABILITY"
        elif self._last_energy < 0.035 and energy >= 0.10:
            candidate = "EMERGENCE"
        elif self._last_energy > 0.08 and energy < self._last_energy * 0.48:
            candidate = "RELEASE"
        else:
            candidate = "DEVELOPMENT" if energy >= 0.035 else "DORMANT"

        if candidate != self._candidate:
            self._candidate = candidate
            self._candidate_since = now
        elif candidate != self.state and (now - self._candidate_since >= 0.18 or onset >= 0.9):
            self.state = candidate

        self._last_energy = energy
        self._last_position = now
        motion_scale = 0.82 + 0.48 * density + 0.16 * novelty
        complexity_scale = 0.88 + 0.32 * energy + 0.18 * density
        glitch = max(onset * 0.65, novelty * 0.72) if self.state == "INSTABILITY" else novelty * 0.18
        accent = max(0.0, onset - 0.55) if self.state in ("EMERGENCE", "INSTABILITY") else 0.0

        request_variation = False
        if (
                self.mode == "AUTO"
                and self.state in ("EMERGENCE", "INSTABILITY")
                and novelty >= 0.58
                and now - self._last_variation >= self.variation_cooldown
        ):
            request_variation = True
            self._last_variation = now

        if self.mode == "MANUAL":
            motion_scale = complexity_scale = 1.0
            glitch = accent = 0.0
        elif self.mode == "SEMI-AUTO":
            request_variation = False

        return DirectorOutput(
            mode=self.mode,
            state=self.state,
            energy=energy,
            density=density,
            novelty=novelty,
            motion_scale=max(0.5, min(1.8, motion_scale)),
            complexity_scale=max(0.65, min(1.5, complexity_scale)),
            glitch_amount=max(0.0, min(1.0, glitch)),
            accent_amount=max(0.0, min(1.0, accent)),
            request_variation=request_variation,
        )


def is_default_placeholder_composition(layers: list[VisualLayer]) -> bool:
    """True only for the untouched starter layer; safe to auto-build on first import."""
    if len(layers) != 1:
        return False
    layer = layers[0]
    return (
            layer.name == "PHASE LATTICE 01"
            and layer.generator == "PHASE LATTICE"
            and not layer.source_id
            and layer.pass_mode == "PAPER RELIEF"
            and layer.pass_map == "DISPLACEMENT"
            and abs(layer.x_offset) < 1e-9
            and abs(layer.y_offset) < 1e-9
            and abs(layer.scale - 1.0) < 1e-9
            and abs(layer.rotation) < 1e-9
    )


def create_auto_composition(
        generator_names: list[str],
        source_ids: list[str],
        seed: int,
) -> list[VisualLayer]:
    """Build a bounded composition with a distinct visual cell for each source."""
    rng = random.Random(seed)
    available = [name for name in AUTO_GENERATORS if name in generator_names]
    if not available:
        available = list(generator_names)
    if not available:
        return []

    layers: list[VisualLayer] = []
    base_name = "GEOMETRIC PLATE" if "GEOMETRIC PLATE" in generator_names else available[0]
    layers.append(VisualLayer(
        name="PLATE / STRUCTURE",
        generator=base_name,
        blend_mode="Screen",
        opacity=0.13,
        mask_mode="FRAME",
        pass_mode="NONE",
        pass_map="DISPLACEMENT",
        pass_strength=0.0,
        palette_mode="MONOCHROME",
        palette_index=0,
        role="STRUCTURE",
    ))

    # Audio can contain up to 64 stems, but the auto-generated visual stack is
    # intentionally bounded to eight channels to protect preview frame time.
    channel_ids = list(source_ids[:8]) if source_ids else [""] * 3
    count = len(channel_ids)
    if count <= 1:
        columns, rows, tile_scale = 1, 1, 0.88
    elif count <= 2:
        columns, rows, tile_scale = 2, 1, 0.58
    elif count <= 4:
        columns, rows, tile_scale = 2, 2, 0.52
    elif count <= 6:
        columns, rows, tile_scale = 3, 2, 0.40
    else:
        columns, rows, tile_scale = 3, 3, 0.34

    preferred = [
        "AXONOMETRIC FIELD", "GEOMETRIC FIELD", "POLYHEDRAL FIELD",
        "PHASE ORBIT", "MOBIUS FIELD", "SPECTRAL TOPOGRAPHY", "PHYLLOTAXIS",
    ]
    roles = ("ANCHOR", "MOTION", "TEXTURE", "ACCENT",
             "ATMOSPHERE", "MOTION", "TEXTURE", "ACCENT")

    for index, source_id in enumerate(channel_ids):
        candidates = [name for name in preferred if name in generator_names]
        if not candidates:
            candidates = available
        generator = candidates[index % len(candidates)]
        row, column = divmod(index, columns)
        row_start = row * columns
        row_count = min(columns, count - row_start)
        column += (columns - row_count) / 2.0
        # The source cell centres follow the default printable frame, not
        # the full canvas edges, so no channel is clipped by the FRAME mask.
        x_offset = (
            ((column + 0.5) / columns - 0.5) * (1322.0 / 1920.0)
            if columns > 1 else 0.0
        )
        y_offset = (
            ((row + 0.5) / rows - 0.5) * (1058.0 / 1440.0)
            if rows > 1 else 0.0
        )

        layers.append(VisualLayer(
            name=f"CHANNEL {index + 1:02d} / {generator}",
            generator=generator,
            blend_mode=("Screen", "Normal", "Difference", "Add")[index % 4],
            opacity=round(rng.uniform(0.76, 0.90), 2),
            x_offset=round(x_offset, 3),
            y_offset=round(y_offset, 3),
            scale=tile_scale,
            rotation=0,
            mask_mode="FRAME",
            # Relief is reserved for the background plate. Avoid running the
            # same full-layer paper pass seven times per preview frame.
            pass_mode="NONE",
            pass_map="DISPLACEMENT",
            pass_strength=0.0,
            source_id=source_id,
            palette_mode="EDITORIAL TRICOLOR",
            palette_index=index,
            role=roles[index % len(roles)],
        ))
    return layers


def vary_composition(
        layers: list[VisualLayer],
        generator_names: list[str],
        seed: int,
) -> list[VisualLayer]:
    """Mutate a small subset of visual decisions rather than replacing the entire plate."""
    rng = random.Random(seed)
    available = [name for name in AUTO_GENERATORS if name in generator_names]
    if not available:
        available = list(generator_names)
    if len(layers) <= 1:
        return layers

    candidates = list(range(1, len(layers)))
    rng.shuffle(candidates)
    selected = set(candidates[:max(1, min(2, len(candidates)))])
    for index, layer in enumerate(layers):
        if index == 0 and layer.generator == "GEOMETRIC PLATE":
            layer.rotation = rng.choice((0, 0, 0, 90, 180, 270))
            layer.scale = round(rng.uniform(0.96, 1.04), 2)
            continue
        if index not in selected:
            layer.opacity = round(max(0.2, min(0.95, layer.opacity + rng.uniform(-0.06, 0.06))), 2)
            continue
        if available:
            alternatives = [name for name in available if name != layer.generator]
            if alternatives and rng.random() < 0.55:
                layer.generator = rng.choice(alternatives)
                layer.name = f"{layer.role} / {layer.generator}"
        layer.blend_mode = rng.choice(BLEND_MODES)
        layer.opacity = round(rng.uniform(0.48, 0.88), 2)
        layer.rotation = rng.choice((0, 0, 0, 90, 180, 270))
        layer.pass_strength = round(rng.uniform(0.22, 0.62), 2)
    return layers
