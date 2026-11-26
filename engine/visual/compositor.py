from __future__ import annotations

import numpy as np
from time import perf_counter
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .assets import AssetCatalog
from .generators import GeneratorBank, GeneratorSettings
from .layers import VisualLayer

# Native project/export geometry stays 1920x1440. Preview is a lighter 4:3
# working surface; the UI refreshes it at about 15 fps to avoid saturating CPUs.
PREVIEW_SIZE = (320, 240)
PROJECT_SIZE = (1920, 1440)

# Three-ink editorial palette based on the user's reference artwork:
# dusty cobalt, aged yellow and violet, with tonal variants for seven channels.
EDITORIAL_TRICOLOR_DARK = (
    (86, 102, 164),  # muted cobalt
    (196, 183, 89),  # aged yellow
    (157, 116, 173),  # dusty violet
    (113, 124, 166),  # blue-grey
    (176, 160, 91),  # ochre
    (145, 111, 157),  # violet-grey
    (94, 117, 143),  # slate blue
)
EDITORIAL_TRICOLOR_LIGHT = (
    (52, 67, 121),
    (142, 128, 44),
    (109, 75, 126),
    (66, 82, 121),
    (130, 116, 47),
    (101, 76, 113),
    (61, 84, 110),
)


class VisualCompositor:
    """Cached region compositor with paper relief and channel-aware ink palettes."""

    def __init__(self, assets: AssetCatalog, render_size: tuple[int, int] = PREVIEW_SIZE):
        self.assets = assets
        self.size = (max(1, int(render_size[0])), max(1, int(render_size[1])))
        self.generators = GeneratorBank()
        self._screen_cache: dict[str, Image.Image] = {}
        self._pass_cache: dict[tuple[str, tuple[int, int]], Image.Image] = {}
        self._mask_cache: dict[tuple[str, str], Image.Image] = {}
        self._frame_cache: dict[str, tuple[int, int, int, int]] = {}
        self._grid_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        self._paper_cache: dict[tuple[str, tuple[int, int]], tuple] = {}
        self._feedback: Image.Image | None = None
        self._last_time: float | None = None
        self.last_profile: dict = {"scene_ms": 0.0, "compose_ms": 0.0, "frame_ms": 0.0, "layers": []}

    def generator_names(self) -> list[str]:
        return self.generators.names()

    def pass_names(self) -> list[str]:
        return ["None", *self.assets.pass_names()]

    def reset_feedback(self, *, preserve_generators: bool = False) -> None:
        """Clear temporal feedback; optionally retain stateful generator simulations."""
        self._feedback = None
        self._last_time = None
        if not preserve_generators:
            self.generators.reset_states()

    def _screen(self, name: str) -> Image.Image | None:
        if name == "No guide":
            return None
        if name not in self._screen_cache:
            image = self.assets.load_screen(name)
            if image is not None:
                self._screen_cache[name] = image.resize(self.size, Image.Resampling.LANCZOS)
        return self._screen_cache.get(name)

    def _pass(self, name: str, size: tuple[int, int]) -> Image.Image | None:
        if name in ("None", ""):
            return None
        key = (name, size)
        if key not in self._pass_cache:
            image = self.assets.load_pass(name)
            if image is not None:
                self._pass_cache[key] = image.resize(size, Image.Resampling.BILINEAR)
        return self._pass_cache.get(key)

    def _frame_box(self, screen: str) -> tuple[int, int, int, int]:
        if screen not in self._frame_cache:
            normalized = self.assets.frame_box(screen)
            w, h = self.size
            x0, y0, x1, y1 = normalized
            self._frame_cache[screen] = (
                int(round(x0 * w)), int(round(y0 * h)),
                int(round(x1 * w)), int(round(y1 * h)),
            )
        return self._frame_cache[screen]

    def _mask(self, mode: str, screen: str,
              frame_box: tuple[int, int, int, int]) -> Image.Image:
        key = (mode, screen)
        if key not in self._mask_cache:
            # Preview and offline export share the same compositor. Mask
            # geometry must follow this instance's canvas, not the preview
            # constant, otherwise 1920×1440 export crops against a 480×360 mask.
            w, h = self.size
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            x0, y0, x1, y1 = frame_box
            if mode == "FULL":
                draw.rectangle((0, 0, w - 1, h - 1), fill=255)
            elif mode == "ELLIPSE":
                draw.ellipse((x0, y0, x1, y1), fill=255)
            elif mode == "INSET":
                pad_x = int((x1 - x0) * 0.075)
                pad_y = int((y1 - y0) * 0.075)
                draw.rectangle((x0 + pad_x, y0 + pad_y, x1 - pad_x, y1 - pad_y), fill=255)
            else:
                inset = max(1, int(min(x1 - x0, y1 - y0) * 0.006))
                draw.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset), fill=255)
            self._mask_cache[key] = mask
        return self._mask_cache[key]

    @staticmethod
    def _normalize_height(image: Image.Image) -> np.ndarray:
        gray_image = image.convert("L").filter(ImageFilter.GaussianBlur(0.45))
        gray = np.asarray(gray_image, dtype=np.float32)
        center = float(np.mean(gray))
        spread = float(np.std(gray))
        low, high = center - 2.2 * spread, center + 2.2 * spread
        if high <= low + 1e-5:
            return np.zeros_like(gray, dtype=np.float32) + 0.5
        return np.clip((gray - low) / (high - low), 0.0, 1.0)

    def _grid(self, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        if size not in self._grid_cache:
            w, h = size
            yy, xx = np.indices((h, w), dtype=np.float32)
            self._grid_cache[size] = (yy, xx)
        return self._grid_cache[size]

    def _paper_fields(self, size: tuple[int, int], height_name: str) -> tuple:
        """Build expensive relief data once per pass-map / preview-size combination."""
        key = (height_name, size)
        if key in self._paper_cache:
            return self._paper_cache[key]

        height_image = self._pass(height_name, size)
        if height_image is None or height_name == "NORMAL":
            height_image = self._pass("DISPLACEMENT", size)
        if height_image is None:
            height_image = self._pass("TEXTURE", size)
        if height_image is None:
            height = np.full((size[1], size[0]), 0.5, dtype=np.float32)
        else:
            height = self._normalize_height(height_image)

        gy, gx = np.gradient(height)
        gx = np.clip(gx, -0.35, 0.35).astype(np.float32)
        gy = np.clip(gy, -0.35, 0.35).astype(np.float32)

        normal_image = self._pass("NORMAL", size)
        normals = None
        if normal_image is not None:
            normal_rgb = np.asarray(normal_image.convert("RGB"), dtype=np.float32) / 127.5 - 1.0
            if float(np.mean(normal_rgb[..., 2])) > 0.10:
                length = np.linalg.norm(normal_rgb, axis=-1, keepdims=True)
                normals = normal_rgb / np.maximum(length, 1e-6)

        if normals is None:
            amount = 5.0
            nx, ny = -gx * amount, -gy * amount
            nz = np.ones_like(nx)
            length = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-8
            normals = np.stack((nx / length, ny / length, nz / length), axis=-1)

        light = np.asarray([-0.42, -0.48, 0.77], dtype=np.float32)
        light /= np.linalg.norm(light)
        diffuse = np.clip(np.sum(normals * light, axis=-1), 0.0, 1.0)

        texture_image = self._pass("TEXTURE", size)
        if texture_image is None:
            grain_gain = np.ones((size[1], size[0]), dtype=np.float32)
        else:
            grain = np.asarray(texture_image.convert("L"), dtype=np.float32)
            center = float(np.mean(grain))
            spread = float(np.std(grain))
            grain = np.clip((grain - (center - 1.8 * spread)) / (3.6 * spread + 1e-6), 0, 1)
            grain_gain = 0.92 + (grain - 0.5) * 0.18

        result = (gx, gy, diffuse.astype(np.float32), grain_gain.astype(np.float32))
        self._paper_cache[key] = result
        return result

    def _apply_paper_relief(self, image: Image.Image, strength: float,
                            pass_map: str = "DISPLACEMENT") -> Image.Image:
        amount = float(np.clip(strength, 0.0, 1.0))
        if amount <= 0.001:
            return image
        w, h = image.size
        gx, gy, diffuse, grain_gain = self._paper_fields(image.size, pass_map)
        yy, xx = self._grid(image.size)
        shift = 1.2 + amount * 8.0
        sx = np.clip((xx + gx * shift).astype(np.int32), 0, w - 1)
        sy = np.clip((yy + gy * shift).astype(np.int32), 0, h - 1)

        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        warped = rgba[sy, sx].copy()
        shade = 0.66 + diffuse * (0.28 + 0.34 * amount)
        rgb = warped[..., :3].astype(np.float32)
        rgb *= (shade * grain_gain)[..., None]
        warped[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        return Image.fromarray(warped, "RGBA")

    def _apply_pass_mode(self, image: Image.Image, mode: str, strength: float,
                         pass_map: str) -> Image.Image:
        amount = float(np.clip(strength, 0.0, 1.0))
        if mode in ("NONE", "None") or amount <= 0.001:
            return image
        if mode == "PAPER RELIEF":
            return self._apply_paper_relief(image, amount, pass_map)
        w, h = image.size
        gx, gy, diffuse, grain_gain = self._paper_fields(image.size, pass_map)
        if mode == "DISPLACE":
            yy, xx = self._grid(image.size)
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
            sx = np.clip((xx + gx * amount * 6.0).astype(np.int32), 0, w - 1)
            sy = np.clip((yy + gy * amount * 6.0).astype(np.int32), 0, h - 1)
            return Image.fromarray(rgba[sy, sx].copy(), "RGBA")
        if mode == "NORMAL LIGHT":
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
            shade = np.clip(0.58 + diffuse * (0.42 + amount * 0.42), 0.3, 1.22)
            rgba[..., :3] = np.clip(
                rgba[..., :3].astype(np.float32) * shade[..., None], 0, 255
            ).astype(np.uint8)
            return Image.fromarray(rgba, "RGBA")
        if mode == "TEXTURE":
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
            gain = 0.76 + grain_gain * (0.34 + amount * 0.25)
            rgba[..., :3] = np.clip(
                rgba[..., :3].astype(np.float32) * gain[..., None], 0, 255
            ).astype(np.uint8)
            return Image.fromarray(rgba, "RGBA")
        return image

    @staticmethod
    def _apply_palette(image: Image.Image, layer: VisualLayer,
                       packet: dict | None, white_plate: bool) -> Image.Image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        visible = rgba[..., 3] > 0
        if layer.palette_mode == "MONOCHROME":
            if white_plate:
                rgba[..., :3][visible] = 255 - rgba[..., :3][visible]
            return Image.fromarray(rgba, "RGBA")

        source_ids = list((packet or {}).get("source_ids") or (packet or {}).get("frames", {}).keys())
        if layer.source_id and layer.source_id in source_ids:
            index = source_ids.index(layer.source_id)
        else:
            index = int(layer.palette_index)
        # Compatibility: old MUTED PRIDE projects now use the editorial
        # blue/yellow/violet inks rather than the former seven-hue rainbow.
        palette = EDITORIAL_TRICOLOR_LIGHT if white_plate else EDITORIAL_TRICOLOR_DARK
        colour = np.asarray(palette[index % len(palette)], dtype=np.float32)
        if not np.any(visible):
            return Image.fromarray(rgba, "RGBA")
        rgb = rgba[..., :3].astype(np.float32)
        luminance = (
                            rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
                    ) / 255.0
        intensity = 0.46 + luminance * 0.54
        tinted = np.clip(colour[None, None, :] * intensity[..., None], 0, 255).astype(np.uint8)
        rgba[..., :3][visible] = tinted[visible]
        return Image.fromarray(rgba, "RGBA")

    @staticmethod
    def _apply_director_effects(
            image: Image.Image, packet: dict | None, seconds: float, layer_id: str
    ) -> Image.Image:
        """Apply deterministic, restrained glitch and accent impulses to one layer."""
        output = (packet or {}).get("director_output") or {}
        glitch = float(np.clip(output.get("glitch_amount", 0.0), 0.0, 1.0))
        accent = float(np.clip(output.get("accent_amount", 0.0), 0.0, 1.0))
        if glitch <= 0.001 and accent <= 0.001:
            return image

        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        height, width = rgba.shape[:2]
        if glitch > 0.04 and width > 2 and height > 2:
            layer_seed = sum((index + 1) * ord(char) for index, char in enumerate(layer_id))
            seed = (int(round(seconds * 30.0)) * 1000003 + layer_seed) & 0xFFFFFFFF
            rng = np.random.default_rng(seed)
            strips = 1 + int(glitch * 5)
            max_shift = max(1, int(width * (0.006 + glitch * 0.035)))
            max_height = max(2, int(height * 0.035))
            for _ in range(strips):
                y0 = int(rng.integers(0, max(1, height - 1)))
                strip_height = int(rng.integers(1, max_height + 1))
                y1 = min(height, y0 + strip_height)
                shift = int(rng.integers(-max_shift, max_shift + 1))
                rgba[y0:y1] = np.roll(rgba[y0:y1], shift, axis=1)

        if accent > 0.001:
            visible = rgba[..., 3] > 0
            rgb = rgba[..., :3].astype(np.float32)
            rgb[visible] = np.clip(
                rgb[visible] * (1.0 + 0.18 * accent) + 12.0 * accent, 0, 255
            )
            rgba[..., :3] = rgb.astype(np.uint8)
            alpha = rgba[..., 3].astype(np.float32)
            rgba[..., 3] = np.clip(alpha * (1.0 + 0.16 * accent), 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")

    def _transform(self, layer: Image.Image, center: tuple[float, float],
                   x_offset: float, y_offset: float, scale: float,
                   rotation: float) -> tuple[Image.Image, tuple[int, int]]:
        sw, sh = layer.size
        scale = max(0.05, min(4.0, float(scale)))
        # Orthogonal rotations preserve geometry and avoid interpolation
        # fringes. Any legacy arbitrary angle is snapped to a quarter turn.
        quarter_turn = int(round(float(rotation) / 90.0)) % 4
        if abs(scale - 1.0) < 1e-4 and quarter_turn == 0:
            transformed = layer
        else:
            tw, th = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
            transformed = (
                layer if (tw, th) == (sw, sh)
                else layer.resize((tw, th), Image.Resampling.BILINEAR)
            )
            if quarter_turn == 1:
                transformed = transformed.transpose(Image.Transpose.ROTATE_90)
            elif quarter_turn == 2:
                transformed = transformed.transpose(Image.Transpose.ROTATE_180)
            elif quarter_turn == 3:
                transformed = transformed.transpose(Image.Transpose.ROTATE_270)
        cx = center[0] + x_offset * self.size[0]
        cy = center[1] + y_offset * self.size[1]
        return transformed, (
            int(round(cx - transformed.width / 2)),
            int(round(cy - transformed.height / 2)),
        )

    def _apply_mask_crop(self, source: Image.Image, position: tuple[int, int],
                         screen: str, mode: str,
                         frame_box: tuple[int, int, int, int],
                         masks: dict) -> tuple[Image.Image, tuple[int, int]] | None:
        px, py = position
        sw, sh = source.size
        x0, y0 = max(0, px), max(0, py)
        x1, y1 = min(self.size[0], px + sw), min(self.size[1], py + sh)
        if x1 <= x0 or y1 <= y0:
            return None
        crop = source.crop((x0 - px, y0 - py, x1 - px, y1 - py))
        mask = masks(mode, screen, frame_box).crop((x0, y0, x1, y1))
        alpha = ImageChops.multiply(crop.getchannel("A"), mask)
        crop.putalpha(alpha)
        if alpha.getbbox() is None:
            return None
        return crop, (x0, y0)

    @staticmethod
    def _blend_at(destination: Image.Image, source: Image.Image,
                  position: tuple[int, int], mode: str,
                  opacity: float = 1.0) -> None:
        """Composite only the intersection rectangle; never allocate full-frame float arrays."""
        px, py = position
        sw, sh = source.size
        x0, y0 = max(0, px), max(0, py)
        x1, y1 = min(destination.width, px + sw), min(destination.height, py + sh)
        if x1 <= x0 or y1 <= y0 or opacity <= 0.001:
            return
        src = source.crop((x0 - px, y0 - py, x1 - px, y1 - py)).convert("RGBA")
        if mode == "Normal":
            if opacity < 0.999:
                alpha = src.getchannel("A").point(
                    [int(value * opacity) for value in range(256)]
                )
                src.putalpha(alpha)
            destination.alpha_composite(src, (x0, y0))
            return

        dst = destination.crop((x0, y0, x1, y1)).convert("RGBA")
        dst_arr = np.asarray(dst, dtype=np.float32)
        src_arr = np.asarray(src, dtype=np.float32)
        cb = dst_arr[..., :3] / 255.0
        cs = src_arr[..., :3] / 255.0
        da = dst_arr[..., 3:4] / 255.0
        sa = src_arr[..., 3:4] / 255.0 * float(np.clip(opacity, 0.0, 1.0))

        if mode == "Add":
            blended = np.clip(cb + cs, 0.0, 1.0)
        elif mode == "Multiply":
            blended = cb * cs
        elif mode == "Screen":
            blended = 1.0 - (1.0 - cb) * (1.0 - cs)
        elif mode == "Difference":
            blended = np.abs(cb - cs)
        elif mode == "Overlay":
            blended = np.where(cb <= 0.5, 2.0 * cb * cs,
                               1.0 - 2.0 * (1.0 - cb) * (1.0 - cs))
        elif mode == "Lighten":
            blended = np.maximum(cb, cs)
        elif mode == "Darken":
            blended = np.minimum(cb, cs)
        else:
            blended = cs

        out_alpha = sa + da * (1.0 - sa)
        premult = (
                (1.0 - sa) * da * cb
                + (1.0 - da) * sa * cs
                + da * sa * blended
        )
        out_rgb = np.where(out_alpha > 1e-8, premult / np.maximum(out_alpha, 1e-8), 0.0)
        out = np.empty_like(dst_arr, dtype=np.uint8)
        out[..., :3] = np.clip(out_rgb * 255.0, 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(out_alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)
        destination.paste(Image.fromarray(out, "RGBA"), (x0, y0))

    @staticmethod
    def _blend_into(destination: Image.Image, source: Image.Image,
                    mode: str, opacity: float = 1.0) -> Image.Image:
        # Compatibility helper used by compositor tests and callers from M3.
        result = destination.copy()
        VisualCompositor._blend_at(result, source, (0, 0), mode, opacity)
        return result

    def _render_layer(self, layer: VisualLayer, packet: dict | None, seconds: float,
                      settings: GeneratorSettings, screen: str,
                      frame_box: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int]] | None:
        w, h = self.size
        if layer.mask_mode == "FULL":
            target_box = (0, 0, w, h)
        else:
            target_box = frame_box
        x0, y0, x1, y1 = target_box
        local_size = (max(1, x1 - x0), max(1, y1 - y0))

        visual = self.generators.render(
            layer.generator, packet, seconds, local_size, settings,
            state_key=layer.layer_id, source_id=layer.source_id or None,
        )
        visual = self._apply_director_effects(visual, packet, seconds, layer.layer_id)
        visual = self._apply_pass_mode(visual, layer.pass_mode,
                                       layer.pass_strength, layer.pass_map)
        visual = self._apply_palette(
            visual, layer, packet, white_plate=screen.upper().endswith("/ WHITE")
        )
        center = ((x0 + x1) / 2, (y0 + y1) / 2)
        transformed, position = self._transform(
            visual, center, layer.x_offset, layer.y_offset, layer.scale, layer.rotation
        )
        return self._apply_mask_crop(
            transformed, position, screen, layer.mask_mode, frame_box, self._mask
        )

    def _render_interference_reference(
            self,
            layer: VisualLayer,
            packet: dict | None,
            seconds: float,
            settings: GeneratorSettings,
            screen: str,
            frame_box: tuple[int, int, int, int],
    ) -> tuple[Image.Image, tuple[int, int]] | None:
        """CPU reference for the shader instrument, using the same layer geometry."""
        from .generators import VisualMetrics

        metrics = VisualMetrics.from_packet(packet, source_id=layer.source_id or None)
        x0, y0, x1, y1 = (
            (0, 0, self.size[0], self.size[1])
            if layer.mask_mode == "FULL" else frame_box
        )
        width, height = max(1, x1 - x0), max(1, y1 - y0)
        x = np.linspace(-2.4, 2.4, width, dtype=np.float32)[None, :]
        y = np.linspace(-1.8, 1.8, height, dtype=np.float32)[:, None]
        motion = float(seconds) * (0.15 + settings.speed * 1.8)
        drive = metrics.energy * settings.response
        field_a = np.sin(
            (x * (8.0 + 22.0 * settings.density)
             + np.sin(y * (4.0 + 10.0 * metrics.mid) + motion) * 1.8)
            * (1.0 + metrics.centroid)
        )
        field_b = np.cos(
            (y * (9.0 + 25.0 * settings.density)
             + np.sin(x * (3.0 + 12.0 * metrics.low) - motion) * 1.6)
            * (1.0 + metrics.cross)
        )
        field_c = np.sin(
            (x + y) * (4.0 + 14.0 * metrics.centroid)
            + motion * 1.7 + metrics.transient * 2.5
        )
        field = field_a + field_b * (0.65 + metrics.coherence * 0.4) + field_c * 0.32
        ridge = np.abs(np.sin(
            field * (3.0 + settings.density * 13.0)
            + metrics.entropy * 3.0 + drive
        ))
        threshold = 0.035 + (1.0 - settings.density) * 0.025 + metrics.transient * 0.045
        alpha = np.where(
            ridge < threshold,
            np.clip(0.3 + (1.0 - ridge / threshold) * 0.7, 0.0, 1.0),
            0.0,
        )
        luminance = np.clip(
            155.0 + (1.0 - ridge) * 95.0 + drive * 50.0
            + metrics.high * 35.0,
            0.0, 255.0,
        )
        white_plate = screen.upper().endswith("/ WHITE")
        if layer.palette_mode == "MONOCHROME":
            ink = np.asarray((10, 10, 10) if white_plate else (236, 236, 232), dtype=np.float32)
        else:
            palette = EDITORIAL_TRICOLOR_LIGHT if white_plate else EDITORIAL_TRICOLOR_DARK
            source_ids = list(
                (packet or {}).get("source_ids")
                or (packet or {}).get("frames", {}).keys()
            )
            palette_index = (
                source_ids.index(layer.source_id)
                if layer.source_id and layer.source_id in source_ids
                else int(layer.palette_index)
            )
            ink = np.asarray(palette[palette_index % len(palette)], dtype=np.float32)
        rgb = np.clip(
            ink[None, None, :] * (0.46 + luminance[..., None] / 255.0 * 0.54),
            0.0, 255.0,
        )
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., :3] = np.broadcast_to(rgb, (height, width, 3)).astype(np.uint8)
        rgba[..., 3] = (alpha * 235.0).astype(np.uint8)
        visual = Image.fromarray(rgba, "RGBA")
        visual = self._apply_director_effects(visual, packet, seconds, layer.layer_id)
        visual = self._apply_pass_mode(
            visual, layer.pass_mode, layer.pass_strength, layer.pass_map
        )
        visual = self._apply_palette(
            visual, layer, packet, white_plate=white_plate
        )
        transformed, position = self._transform(
            visual,
            ((x0 + x1) / 2.0, (y0 + y1) / 2.0),
            layer.x_offset, layer.y_offset, layer.scale, layer.rotation,
        )
        return self._apply_mask_crop(
            transformed, position, screen, layer.mask_mode,
            frame_box, self._mask,
        )

    def _gpu_interference_spec(
            self,
            layer: VisualLayer,
            packet: dict | None,
            seconds: float,
            settings: GeneratorSettings,
            size: tuple[int, int],
            screen: str,
    ) -> dict | None:
        """Describe a GPU-native interference field when no CPU-only operation is needed."""
        if layer.generator != "INTERFERENCE FIELD":
            return None
        if layer.pass_mode not in ("NONE", "None") and layer.pass_strength > 0.001:
            return None
        if layer.mask_mode not in ("FULL", "FRAME"):
            return None
        if (
                abs(layer.x_offset) > 1e-6 or abs(layer.y_offset) > 1e-6
                or abs(layer.scale - 1.0) > 1e-6
                or abs(layer.rotation) > 1e-6
        ):
            return None
        if layer.palette_mode not in ("EDITORIAL TRICOLOR", "MUTED PRIDE", "MONOCHROME"):
            return None

        output = (packet or {}).get("director_output") or {}
        if (
                float(output.get("glitch_amount", 0.0)) > 0.001
                or float(output.get("accent_amount", 0.0)) > 0.001
        ):
            return None

        from .generators import VisualMetrics
        metrics = VisualMetrics.from_packet(packet, source_id=layer.source_id or None)
        if layer.mask_mode == "FULL":
            x0, y0, x1, y1 = 0, 0, size[0], size[1]
        else:
            x0, y0, x1, y1 = VisualCompositor._frame_box_for_size(
                self, screen, size
            )
            inset = max(1, int(min(x1 - x0, y1 - y0) * 0.006))
            x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        width, height = max(1, x1 - x0), max(1, y1 - y0)
        white_plate = screen.upper().endswith("/ WHITE")
        if layer.palette_mode == "MONOCHROME":
            ink = (10, 10, 10) if white_plate else (236, 236, 232)
            palette_mode = "MONOCHROME"
        else:
            palette = EDITORIAL_TRICOLOR_LIGHT if white_plate else EDITORIAL_TRICOLOR_DARK
            source_ids = list((packet or {}).get("source_ids") or (packet or {}).get("frames", {}).keys())
            if layer.source_id and layer.source_id in source_ids:
                palette_index = source_ids.index(layer.source_id)
            else:
                palette_index = int(layer.palette_index)
            ink = palette[palette_index % len(palette)]
            palette_mode = "TRICOLOR"

        return {
            "kind": "interference",
            "size": (width, height),
            "rect": (x0, y0, width, height),
            "blend_mode": layer.blend_mode,
            "opacity": float(layer.opacity),
            "palette_mode": palette_mode,
            "ink": tuple(int(channel) for channel in ink),
            "metrics": {
                "low": float(metrics.low),
                "mid": float(metrics.mid),
                "high": float(metrics.high),
                "energy": float(metrics.energy),
                "centroid": float(metrics.centroid),
                "cross": float(metrics.cross),
                "coherence": float(metrics.coherence),
                "transient": float(metrics.transient),
                "entropy": float(metrics.entropy),
            },
            "settings": {
                "density": float(settings.density),
                "speed": float(settings.speed),
                "response": float(settings.response),
            },
            "seconds": float(seconds),
            "layer_id": layer.layer_id,
        }

    def _frame_box_for_size(
            self, screen: str, size: tuple[int, int]
    ) -> tuple[int, int, int, int]:
        normalized = self.assets.frame_box(screen)
        width, height = size
        x0, y0, x1, y1 = normalized
        return (
            int(round(x0 * width)), int(round(y0 * height)),
            int(round(x1 * width)), int(round(y1 * height)),
        )

    def render_scene(
            self,
            packet: dict | None,
            seconds: float,
            layers: list[VisualLayer] | None = None,
            settings: GeneratorSettings | None = None,
            screen: str = "No guide",
            gpu_native: bool = False,
            include_guide: bool = True,
    ) -> dict:
        """Build a layer-separated scene for GPU composition."""
        frame_started = perf_counter()
        settings = settings or GeneratorSettings()
        layers = layers or []
        layer_profiles = []
        background = Image.new("RGBA", self.size, (10, 10, 10, 255))
        guide = self._screen(screen)
        if guide is not None and include_guide:
            background.alpha_composite(guide)
        frame_box = self._frame_box(screen)
        rendered_layers = []

        for layer in layers:
            if not layer.visible:
                continue
            layer_started = perf_counter()
            if gpu_native:
                spec = self._gpu_interference_spec(
                    layer, packet, seconds, settings, self.size, screen
                )
                if spec is not None:
                    rendered_layers.append({
                        "gpu_instrument": spec,
                        "position": (spec["rect"][0], spec["rect"][1]),
                        "size": (spec["rect"][2], spec["rect"][3]),
                        "blend_mode": layer.blend_mode,
                        "opacity": layer.opacity,
                        "layer_id": layer.layer_id,
                    })
                    layer_profiles.append({
                        "layer_id": layer.layer_id,
                        "generator": layer.generator,
                        "render_ms": (perf_counter() - layer_started) * 1000.0,
                        "backend": "OPENGL_SPEC",
                    })
                    continue
            if layer.generator == "INTERFERENCE FIELD":
                rendered = self._render_interference_reference(
                    layer, packet, seconds, settings, screen, frame_box
                )
            else:
                rendered = self._render_layer(
                    layer, packet, seconds, settings, screen, frame_box
                )
            if rendered is None:
                continue
            image, position = rendered
            rendered_layers.append({
                "image": image,
                "position": position,
                "blend_mode": layer.blend_mode,
                "opacity": layer.opacity,
                "layer_id": layer.layer_id,
            })
            layer_profiles.append({
                "layer_id": layer.layer_id,
                "generator": layer.generator,
                "render_ms": (perf_counter() - layer_started) * 1000.0,
                "backend": "CPU",
            })
        if not include_guide and guide is not None:
            rendered_layers.append({
                "image": guide,
                "position": (0, 0),
                "blend_mode": "Normal",
                "opacity": 1.0,
                "layer_id": "__screen_guide__",
            })
        scene_ms = (perf_counter() - frame_started) * 1000.0
        self.last_profile = {
            "scene_ms": scene_ms,
            "compose_ms": 0.0,
            "frame_ms": scene_ms,
            "layer_count": len(layer_profiles),
            "layers": layer_profiles,
            "backend": "OPENGL_SPEC" if gpu_native else "CPU",
        }
        return {
            "background": background,
            "layers": rendered_layers,
            "size": self.size,
            "time": float(seconds),
            "screen": screen,
            "profile": self.last_profile,
        }

    def render_cpu_frame(
            self,
            packet: dict | None,
            seconds: float,
            layers: list[VisualLayer] | None = None,
            settings: GeneratorSettings | None = None,
            screen: str = "No guide",
            feedback_enabled: bool = False,
            feedback_amount: float = 0.35,
            feedback_decay: float = 0.90,
            feedback_shift: float = 0.0,
    ) -> Image.Image:
        """Compose every generator and effect into a complete CPU RGBA frame."""
        scene = self.render_scene(
            packet=packet,
            seconds=seconds,
            layers=layers,
            settings=settings,
            screen=screen,
            gpu_native=False,
            include_guide=False,
        )
        compose_started = perf_counter()
        frame = scene["background"].copy()
        for layer in scene["layers"]:
            self._blend_at(
                frame,
                layer["image"],
                layer["position"],
                layer.get("blend_mode", "Normal"),
                layer.get("opacity", 1.0),
            )
        if self._last_time is not None and seconds < self._last_time:
            self._feedback = None
        if feedback_enabled and self._feedback is not None and seconds > (self._last_time or seconds):
            dx = int(round(float(feedback_shift) * self.size[0]))
            dy = int(round(float(feedback_shift) * self.size[1] * 0.62))
            previous = self._feedback.copy()
            if dx or dy:
                previous = previous.transform(
                    self.size, Image.Transform.AFFINE,
                    (1, 0, -dx, 0, 1, -dy),
                    resample=Image.Resampling.BILINEAR,
                )
            alpha = previous.getchannel("A").point(
                [int(value * float(np.clip(feedback_decay, 0.0, 0.99)))
                 for value in range(256)]
            )
            previous.putalpha(alpha)
            self._blend_at(
                frame, previous, (0, 0), "Screen",
                float(np.clip(feedback_amount, 0.0, 1.0)),
            )
        self._feedback = frame.copy() if feedback_enabled else None
        self._last_time = float(seconds)
        guide = self._screen(screen)
        if guide is not None:
            frame.alpha_composite(guide)
        compose_ms = (perf_counter() - compose_started) * 1000.0
        self.last_profile["compose_ms"] = compose_ms
        self.last_profile["frame_ms"] = self.last_profile["scene_ms"] + compose_ms
        return frame

    def render(self, packet: dict | None, seconds: float,
               layers: list[VisualLayer] | None = None,
               settings: GeneratorSettings | None = None,
               screen: str = "No guide",
               feedback_enabled: bool = False,
               feedback_amount: float = 0.35,
               feedback_decay: float = 0.90,
               feedback_shift: float = 0.0) -> Image.Image:
        settings = settings or GeneratorSettings()
        layers = layers or []
        base = Image.new("RGBA", self.size, (10, 10, 10, 255))
        guide = self._screen(screen)

        frame_box = self._frame_box(screen)
        stack = Image.new("RGBA", self.size, (0, 0, 0, 0))
        for layer in layers:
            if not layer.visible:
                continue
            rendered = self._render_layer(layer, packet, seconds, settings, screen, frame_box)
            if rendered is None:
                continue
            visual, position = rendered
            self._blend_at(stack, visual, position, layer.blend_mode, layer.opacity)

        if feedback_enabled:
            if self._last_time is not None and seconds < self._last_time:
                self._feedback = None
            if self._feedback is not None:
                dx = int(round(feedback_shift * self.size[0]))
                dy = int(round(feedback_shift * self.size[1] * 0.62))
                previous = self._feedback
                if dx or dy:
                    previous = previous.transform(
                        self.size, Image.Transform.AFFINE,
                        (1, 0, -dx, 0, 1, -dy),
                        resample=Image.Resampling.BILINEAR,
                    )
                alpha = previous.getchannel("A").point(
                    [int(value * float(np.clip(feedback_decay, 0, 0.99)))
                     for value in range(256)]
                )
                previous.putalpha(alpha)
                self._blend_at(
                    stack, previous, (0, 0), "Screen",
                    float(np.clip(feedback_amount, 0, 1)),
                )
            self._feedback = stack.copy()
            self._last_time = seconds
        else:
            self._feedback = None
            self._last_time = seconds

        # Keep screen artwork above generated ink in both CPU and GPU paths.
        base.alpha_composite(stack)
        if guide is not None:
            base.alpha_composite(guide)
        return base
