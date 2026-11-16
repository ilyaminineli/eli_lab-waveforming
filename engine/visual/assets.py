from pathlib import Path

from PIL import Image


class AssetCatalog:
    def __init__(self, root: Path):
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

    def screen_names(self): return list(self._screens)

    def pass_names(self): return list(self._passes)

    def load_screen(self, name):
        path = self._screens.get(name)
        return Image.open(path).convert("RGBA") if path and path.exists() else None

    def load_pass(self, name):
        path = self._passes.get(name)
        return Image.open(path).convert("RGBA") if path and path.exists() else None

    def validate(self):
        return {"screens": {k: self._size(v) for k, v in self._screens.items()},
                "passes": {k: self._size(v) for k, v in self._passes.items()}}

    @staticmethod
    def _size(path):
        if not path.exists(): return None
        with Image.open(path) as im: return im.size
