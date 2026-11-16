from __future__ import annotations

import numpy as np
from PIL import Image

from .assets import AssetCatalog
from .generators import GeneratorBank, GeneratorSettings

PREVIEW_SIZE = (960, 720)


class VisualCompositor:
    """Low-latency preview compositor; project coordinates remain 1920×1440."""

    def __init__(self, assets: AssetCatalog):
        self.assets = assets
        self.generators = GeneratorBank()
        self._screen_cache: dict[str, Image.Image] = {}
        self._pass_cache: dict[str, Image.Image] = {}

    def generator_names(self) -> list[str]:
        return self.generators.names()

    def _screen(self, name: str) -> Image.Image | None:
        if name == "No guide":
            return None
        if name not in self._screen_cache:
            image = self.assets.load_screen(name)
            if image is not None:
                self._screen_cache[name] = image.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        return self._screen_cache.get(name)

    def _pass(self, name: str) -> Image.Image | None:
        if name == "None":
            return None
        if name not in self._pass_cache:
            image = self.assets.load_pass(name)
            if image is not None:
                self._pass_cache[name] = image.resize(PREVIEW_SIZE, Image.Resampling.BILINEAR)
        return self._pass_cache.get(name)

    @staticmethod
    def _apply_pass(layer: Image.Image, pass_image: Image.Image, pass_name: str,
                    blend: str, strength: float) -> Image.Image:
        visual = np.asarray(layer.convert("RGBA"), dtype=np.uint8).copy()
        pmap = np.asarray(pass_image.convert("RGB"), dtype=np.uint8)
        rgb = visual[..., :3].astype(np.float32)
        map_rgb = pmap.astype(np.float32) / 255.0
        gray = map_rgb.mean(axis=2)
        amount = float(np.clip(strength, 0.0, 1.0))

        if pass_name == "DISPLACEMENT":
            h, w = visual.shape[:2]
            yy, xx = np.indices((h, w), dtype=np.float32)
            dx = (map_rgb[..., 0] - 0.5) * (7.0 + amount * 35.0)
            dy = (map_rgb[..., 1] - 0.5) * (7.0 + amount * 35.0)
            sx = np.clip((xx + dx).astype(np.int32), 0, w - 1)
            sy = np.clip((yy + dy).astype(np.int32), 0, h - 1)
            visual = visual[sy, sx].copy()
            rgb = visual[..., :3].astype(np.float32)
        elif pass_name == "NORMAL":
            gy, gx = np.gradient(gray)
            shade = np.clip(0.78 - gx * (1.5 + amount * 3.0) - gy * (1.5 + amount * 3.0), 0.35, 1.35)
            rgb *= shade[..., None]
        elif pass_name == "TEXTURE":
            modulation = 0.45 + gray * (0.55 + amount * 0.65)
            rgb *= modulation[..., None]

        if blend == "Add":
            rgb = np.clip(rgb + map_rgb * (28.0 + amount * 75.0), 0, 255)
        elif blend == "Multiply":
            rgb *= (0.35 + map_rgb * (0.65 + amount * 0.35))
        elif blend == "Screen":
            overlay = map_rgb * (0.25 + amount * 0.55)
            rgb = 255.0 - (255.0 - rgb) * (1.0 - overlay)
        elif blend == "Difference":
            rgb = np.abs(rgb - map_rgb * 255.0 * (0.35 + amount * 0.65))
        elif blend == "Overlay":
            normalized = rgb / 255.0
            rgb = np.where(normalized < 0.5,
                           2.0 * normalized * map_rgb,
                           1.0 - 2.0 * (1.0 - normalized) * (1.0 - map_rgb)) * 255.0
        visual[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        return Image.fromarray(visual, "RGBA")

    def render(self, packet: dict | None, seconds: float, generator: str,
               settings: GeneratorSettings, screen: str, screen_pass: str,
               blend: str, opacity: float) -> Image.Image:
        base = Image.new("RGBA", PREVIEW_SIZE, (12, 12, 12, 255))
        guide = self._screen(screen)
        if guide is not None:
            base.alpha_composite(guide)

        visual = self.generators.render(generator, packet, seconds, PREVIEW_SIZE, settings)
        pass_image = self._pass(screen_pass)
        if pass_image is not None:
            visual = self._apply_pass(visual, pass_image, screen_pass, blend, settings.response)

        if opacity < 1.0:
            factor = max(0.0, min(1.0, opacity))
            alpha = visual.getchannel("A").point([int(value * factor) for value in range(256)])
            visual.putalpha(alpha)
        base.alpha_composite(visual)
        return base
