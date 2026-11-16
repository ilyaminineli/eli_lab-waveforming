from __future__ import annotations

import random

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


def create_auto_composition(
    generator_names: list[str],
    source_ids: list[str],
    seed: int,
) -> list[VisualLayer]:
    """Build a deliberate, bounded multi-layer plate from available sources."""
    rng = random.Random(seed)
    available = [name for name in AUTO_GENERATORS if name in generator_names]
    if not available:
        available = list(generator_names)
    if not available:
        return []

    layers: list[VisualLayer] = []
    base_name = "GEOMETRIC PLATE" if "GEOMETRIC PLATE" in generator_names else available[0]
    base = VisualLayer(
        name="PLATE / STRUCTURE",
        generator=base_name,
        blend_mode="Normal",
        opacity=0.94,
        mask_mode="FRAME",
        pass_mode="PAPER RELIEF",
        pass_map="DISPLACEMENT",
        pass_strength=0.34,
        palette_mode="MONOCHROME",
        palette_index=0,
    )
    layers.append(base)

    if source_ids:
        channel_ids = list(source_ids[:7])
    else:
        channel_ids = [""] * 3

    preferred = [
        "AXONOMETRIC FIELD",
        "GEOMETRIC FIELD",
        "POLYHEDRAL FIELD",
        "PHASE ORBIT",
        "MOBIUS FIELD",
        "SPECTRAL TOPOGRAPHY",
        "PHYLLOTAXIS",
    ]
    for index, source_id in enumerate(channel_ids):
        candidates = [name for name in preferred if name in generator_names]
        if not candidates:
            candidates = available
        generator = candidates[index % len(candidates)]
        layer = VisualLayer(
            name=f"CHANNEL {index + 1:02d} / {generator}",
            generator=generator,
            blend_mode=("Screen", "Normal", "Difference", "Add")[index % 4],
            opacity=round(rng.uniform(0.48, 0.86), 2),
            x_offset=round(rng.uniform(-0.06, 0.06), 3),
            y_offset=round(rng.uniform(-0.055, 0.055), 3),
            scale=round(rng.uniform(0.76, 1.12), 2),
            rotation=rng.choice((-18, -12, -7, 0, 7, 12, 18)),
            mask_mode="FRAME",
            pass_mode="PAPER RELIEF" if index % 2 == 0 else "NORMAL LIGHT",
            pass_map="DISPLACEMENT",
            pass_strength=round(rng.uniform(0.26, 0.55), 2),
            source_id=source_id,
            palette_mode="MUTED PRIDE",
            palette_index=index,
        )
        layers.append(layer)

    return layers


def vary_composition(
    layers: list[VisualLayer],
    generator_names: list[str],
    seed: int,
) -> list[VisualLayer]:
    """Vary the existing arrangement without changing its layer count or source routing."""
    rng = random.Random(seed)
    available = [name for name in AUTO_GENERATORS if name in generator_names]
    if not available:
        available = list(generator_names)

    for index, layer in enumerate(layers):
        if index == 0 and layer.generator == "GEOMETRIC PLATE":
            # Keep the editorial plate as a visual anchor.
            layer.rotation = rng.choice((-2, 0, 0, 0, 2))
            layer.scale = round(rng.uniform(0.94, 1.05), 2)
            continue
        if available:
            current_family = layer.generator
            candidates = [name for name in available if name != current_family]
            if candidates and rng.random() < 0.72:
                layer.generator = rng.choice(candidates)
                layer.name = f"CHANNEL {index:02d} / {layer.generator}"
        layer.blend_mode = rng.choice(BLEND_MODES)
        layer.opacity = round(rng.uniform(0.42, 0.88), 2)
        layer.x_offset = round(rng.uniform(-0.10, 0.10), 3)
        layer.y_offset = round(rng.uniform(-0.085, 0.085), 3)
        layer.scale = round(rng.uniform(0.68, 1.24), 2)
        layer.rotation = rng.choice((-32, -24, -16, -8, 0, 8, 16, 24, 32))
        layer.pass_mode = rng.choice(("PAPER RELIEF", "NORMAL LIGHT", "DISPLACE"))
        layer.pass_strength = round(rng.uniform(0.2, 0.62), 2)
        layer.palette_mode = "MUTED PRIDE"
    return layers
