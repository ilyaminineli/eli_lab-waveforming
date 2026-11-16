from pathlib import Path

from PIL import Image


class AssetCatalog:
    """Repository-owned screen plates and pass maps, with printable-area metadata."""

    FRAME_BOXES = {
        # Screen 1 is an open plate: keep away from the registration marks and lower hatch.
        "SCREEN 1 / BLACK": (0.075, 0.085, 0.925, 0.835),
        "SCREEN 1 / WHITE": (0.075, 0.085, 0.925, 0.835),
        # Screen 2 has a central inset frame. The box describes its interior.
        "SCREEN 2 / BLACK": (0.172, 0.133, 0.755, 0.855),
        "SCREEN 2 / WHITE": (0.172, 0.133, 0.755, 0.855),
    }

    def __init__(self, root: Path):
        self.root = root
        self._screens = {
            "SCREEN 1 / BLACK": root / "screen_1_black.png",
            "SCREEN 1 / WHITE": root / "screen_1_white.png",
            "SCREEN 2 / BLACK": root / "screen_2_black.png",
            "SCREEN 2 / WHITE": root / "screen_2_white.png",
        }
        self._passes = {
            "DISPLACEMENT": root / "screen_pass" / "screen_displacement.png",
            "NORMAL": root / "screen_pass" / "screen_normal.png",
            "TEXTURE": root / "screen_pass" / "screen_texture.png",
        }

    def screen_names(self) -> list[str]:
        return list(self._screens)

    def pass_names(self) -> list[str]:
        return list(self._passes)

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

    def frame_box(self, screen: str) -> tuple[float, float, float, float]:
        """Normalized x0,y0,x1,y1 printable/content region for a screen plate."""
        return self.FRAME_BOXES.get(screen, (0.075, 0.085, 0.925, 0.835))

    def validate(self) -> dict:
        return {
            "screens": {name: self._size(path) for name, path in self._screens.items()},
            "passes": {name: self._size(path) for name, path in self._passes.items()},
        }

    @staticmethod
    def _size(path: Path) -> tuple[int, int] | None:
        if not path.is_file():
            return None
        with Image.open(path) as image:
            return image.size
