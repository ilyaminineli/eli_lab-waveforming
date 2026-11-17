from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


CANVAS_SIZE = (1920, 1440)
DEFAULT_FRAME_SIZE = (1322, 1058)
DEFAULT_FRAME_RECT = (
    (CANVAS_SIZE[0] - DEFAULT_FRAME_SIZE[0]) // 2,
    (CANVAS_SIZE[1] - DEFAULT_FRAME_SIZE[1]) // 2,
    (CANVAS_SIZE[0] + DEFAULT_FRAME_SIZE[0]) // 2,
    (CANVAS_SIZE[1] + DEFAULT_FRAME_SIZE[1]) // 2,
)


class AssetCatalog:
    """Screen plates, pre-designed plates and pixel-accurate content-region metadata."""

    LEGACY_FRAME_BOXES = {
        "SCREEN 1 / BLACK": (0.075, 0.085, 0.925, 0.835),
        "SCREEN 1 / WHITE": (0.075, 0.085, 0.925, 0.835),
        "SCREEN 2 / BLACK": (0.172, 0.133, 0.755, 0.855),
        "SCREEN 2 / WHITE": (0.172, 0.133, 0.755, 0.855),
    }

    def __init__(self, root: Path):
        self.root = Path(root)
        self._screens: dict[str, Path] = {
            "SCREEN 1 / BLACK": self.root / "screen_1_black.png",
            "SCREEN 1 / WHITE": self.root / "screen_1_white.png",
            "SCREEN 2 / BLACK": self.root / "screen_2_black.png",
            "SCREEN 2 / WHITE": self.root / "screen_2_white.png",
        }
        self._passes = {
            "DISPLACEMENT": self.root / "screen_pass" / "screen_displacement.png",
            "NORMAL": self.root / "screen_pass" / "screen_normal.png",
            "TEXTURE": self.root / "screen_pass" / "screen_texture.png",
        }
        self._frame_boxes = dict(self.LEGACY_FRAME_BOXES)
        self._frame_rects_px: dict[str, tuple[int, int, int, int]] = {}
        self._profiles_path = self.root.parent / "layout" / "layout_profiles.json"
        self._load_profiles()
        self._discover_pre_designed()

    def _load_profiles(self) -> None:
        if not self._profiles_path.is_file():
            return
        try:
            data = json.loads(self._profiles_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        canvas = tuple(data.get("canvas_size", CANVAS_SIZE))
        if canvas != CANVAS_SIZE:
            # WAVEFORMING's export coordinate system stays fixed at 1920x1440.
            return
        for item in data.get("profiles", []):
            name = str(item.get("name", "")).strip()
            rect = item.get("frame_rect_px")
            normalized = item.get("frame_box")
            if name and isinstance(rect, list) and len(rect) == 4:
                self._frame_rects_px[name] = tuple(int(value) for value in rect)
            elif name and isinstance(normalized, list) and len(normalized) == 4:
                self._frame_boxes[name] = tuple(float(value) for value in normalized)

    def _discover_pre_designed(self) -> None:
        folder = self.root / "pre_designed"
        if not folder.is_dir():
            return
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            name = f"PRE-DESIGNED / {path.stem.upper()}"
            self._screens[name] = path

    def screen_names(self) -> list[str]:
        return [name for name, path in self._screens.items() if path.is_file()]

    def pass_names(self) -> list[str]:
        return [name for name, path in self._passes.items() if path.is_file()]

    def load_screen(self, name: str) -> Image.Image | None:
        path = self._screens.get(name)
        if path and path.is_file():
            with Image.open(path) as image:
                return image.convert("RGBA")
        return None

    def load_pass(self, name: str) -> Image.Image | None:
        path = self._passes.get(name)
        if path and path.is_file():
            with Image.open(path) as image:
                return image.convert("RGBA")
        return None

    def frame_rect_px(self, screen: str) -> tuple[int, int, int, int]:
        """Return x0,y0,x1,y1 in native 1920x1440 project coordinates."""
        if screen in self._frame_rects_px:
            return self._frame_rects_px[screen]
        if screen in self._frame_boxes:
            x0, y0, x1, y1 = self._frame_boxes[screen]
            return (
                round(x0 * CANVAS_SIZE[0]), round(y0 * CANVAS_SIZE[1]),
                round(x1 * CANVAS_SIZE[0]), round(y1 * CANVAS_SIZE[1]),
            )
        return DEFAULT_FRAME_RECT

    def frame_box(self, screen: str) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.frame_rect_px(screen)
        width, height = CANVAS_SIZE
        return (x0 / width, y0 / height, x1 / width, y1 / height)

    def validate(self) -> dict:
        return {
            "canvas_size": CANVAS_SIZE,
            "default_frame_size": DEFAULT_FRAME_SIZE,
            "default_frame_rect": DEFAULT_FRAME_RECT,
            "screens": {
                name: {"size": self._size(path), "frame_rect_px": self.frame_rect_px(name)}
                for name, path in self._screens.items()
            },
            "passes": {name: self._size(path) for name, path in self._passes.items()},
            "layout_profiles": str(self._profiles_path),
        }

    @staticmethod
    def _size(path: Path) -> tuple[int, int] | None:
        if not path.is_file():
            return None
        with Image.open(path) as image:
            return image.size
