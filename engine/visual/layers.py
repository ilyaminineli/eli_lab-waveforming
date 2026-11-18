from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class VisualLayer:
    name: str
    generator: str
    layer_id: str = field(default_factory=lambda: uuid4().hex[:10])
    visible: bool = True
    opacity: float = 1.0
    blend_mode: str = "Normal"
    x_offset: float = 0.0
    y_offset: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    mask_mode: str = "FRAME"
    pass_map: str = "DISPLACEMENT"
    pass_mode: str = "PAPER RELIEF"
    pass_strength: float = 0.55
    source_id: str = ""
    palette_mode: str = "EDITORIAL TRICOLOR"
    palette_index: int = 0
    role: str = "MOTION"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "VisualLayer":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})


class LayerStack:
    def __init__(self):
        self.layers: list[VisualLayer] = []

    def add(self, generator: str, name: str | None = None) -> VisualLayer:
        layer = VisualLayer(name or f"{generator.title()} {len(self.layers)+1:02d}", generator)
        self.layers.append(layer)
        return layer

    def remove(self, layer_id: str) -> None:
        self.layers = [layer for layer in self.layers if layer.layer_id != layer_id]

    def move(self, layer_id: str, direction: int) -> None:
        index = next((i for i, layer in enumerate(self.layers) if layer.layer_id == layer_id), -1)
        target = index + int(direction)
        if index >= 0 and 0 <= target < len(self.layers):
            self.layers[index], self.layers[target] = self.layers[target], self.layers[index]

    def duplicate(self, layer_id: str) -> VisualLayer | None:
        source = next((layer for layer in self.layers if layer.layer_id == layer_id), None)
        if source is None:
            return None
        data = source.to_dict()
        data.pop("layer_id", None)
        data["name"] = source.name + " COPY"
        clone = VisualLayer.from_dict(data)
        self.layers.insert(self.layers.index(source) + 1, clone)
        return clone

    def to_list(self) -> list[dict]:
        return [layer.to_dict() for layer in self.layers]

    def from_list(self, items: list[dict]) -> None:
        self.layers = [VisualLayer.from_dict(item) for item in items]
