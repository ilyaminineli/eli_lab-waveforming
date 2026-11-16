from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw


@dataclass(slots=True)
class VisualMetrics:
    rms: float = 0.0
    flux: float = 0.0
    centroid: float = 0.0
    flatness: float = 0.0
    entropy: float = 0.0
    zcr: float = 0.0
    width: float = 0.0
    rolloff: float = 0.0
    crest: float = 0.0
    cross: float = 0.0
    bands: np.ndarray | None = None
    energies: np.ndarray | None = None
    correlation: np.ndarray | None = None
    source_count: int = 0

    @classmethod
    def from_packet(cls, packet: dict | None) -> "VisualMetrics":
        packet = packet or {}
        frames = list(packet.get("frames", {}).values())
        if not frames:
            return cls()

        def mean(field: str) -> float:
            return float(np.mean([getattr(frame, field) for frame in frames]))

        bands = np.mean(np.stack([frame.bands for frame in frames]), axis=0).astype(np.float32)
        energies = np.asarray([frame.rms for frame in frames], dtype=np.float32)
        corr = np.asarray(packet.get("correlation", np.eye(len(frames))), dtype=np.float32)
        if corr.ndim != 2 or corr.size == 0 or corr.shape[0] <= 1:
            cross = 0.0
        else:
            cross = float(np.mean(np.abs(corr[np.triu_indices(corr.shape[0], 1)])))
        return cls(
            rms=mean("rms"), flux=mean("flux"), centroid=mean("centroid_norm"),
            flatness=mean("flatness"), entropy=mean("entropy"), zcr=mean("zcr"),
            width=mean("stereo_width"), rolloff=mean("rolloff"), crest=mean("crest"),
            cross=cross, bands=bands, energies=energies, correlation=corr,
            source_count=len(frames),
        )


@dataclass(slots=True)
class GeneratorSettings:
    complexity: float = 58.0
    motion: float = 42.0
    sensitivity: float = 110.0
    seed: int = 17

    @property
    def density(self) -> float:
        return float(np.clip(self.complexity / 100.0, 0.05, 1.0))

    @property
    def speed(self) -> float:
        return self.motion / 100.0

    @property
    def response(self) -> float:
        return self.sensitivity / 100.0


class VisualGenerator:
    name = "ABSTRACT"

    def render(self, metrics: VisualMetrics, seconds: float, size: tuple[int, int],
               settings: GeneratorSettings) -> Image.Image:
        raise NotImplementedError

    @staticmethod
    def _blank(size: tuple[int, int]) -> Image.Image:
        return Image.new("RGBA", size, (0, 0, 0, 0))


class InterferenceField(VisualGenerator):
    name = "INTERFERENCE FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        x = np.linspace(-2.4, 2.4, w, dtype=np.float32)[None, :]
        y = np.linspace(-1.8, 1.8, h, dtype=np.float32)[:, None]
        response = settings.response
        density = settings.density
        motion = seconds * (0.15 + settings.speed * 1.8)
        centroid = metrics.centroid * response
        flux = metrics.flux * response * 8.0
        cross = metrics.cross
        bands = metrics.bands if metrics.bands is not None else np.zeros(64, np.float32)
        low = float(np.mean(bands[:max(2, len(bands) // 8)])) if len(bands) else 0.0
        mid = float(np.mean(bands[len(bands) // 3:2 * len(bands) // 3])) if len(bands) else 0.0
        field_a = np.sin((x * (8 + 22 * density) + np.sin(y * (4 + 10 * mid) + motion) * 1.8) * (1 + centroid))
        field_b = np.cos((y * (9 + 25 * density) + np.sin(x * (3 + 12 * low) - motion) * 1.6) * (1 + cross))
        field_c = np.sin((x + y) * (4 + 14 * centroid) + motion * 1.7 + flux)
        field = field_a + field_b * (0.65 + cross * 0.7) + field_c * 0.32
        ridge = np.abs(np.sin(field * (3.0 + density * 13.0) + metrics.entropy * 3.0))
        threshold = 0.035 + (1.0 - density) * 0.025 + min(0.04, flux * 0.03)
        alpha = np.where(ridge < threshold, np.clip(0.35 + (1 - ridge / threshold) * 0.65, 0, 1), 0)
        lum = np.clip(150 + (1 - ridge) * 100 + metrics.rms * 90, 0, 255).astype(np.uint8)
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        pixels[..., 0] = lum
        pixels[..., 1] = lum
        pixels[..., 2] = lum
        pixels[..., 3] = (alpha * 235).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA")


class PhaseOrbit(VisualGenerator):
    name = "PHASE ORBIT"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        scale = min(w, h) * 0.34
        energies = metrics.energies if metrics.energies is not None else np.array([metrics.rms], np.float32)
        corr = metrics.correlation if metrics.correlation is not None else np.eye(len(energies))
        count = max(2, min(8, 2 + metrics.source_count))
        points_n = int(320 + settings.density * 2100)
        theta = np.linspace(0, math.tau * 3.0, points_n, dtype=np.float32)
        speed = seconds * (0.1 + settings.speed * 1.1)
        for index in range(count):
            energy = float(energies[index % len(energies)]) if len(energies) else 0.0
            partner = float(corr[index % corr.shape[0], (index + 1) % corr.shape[1]]) if corr.size else 0.0
            a = 2 + (index % 5)
            b = 3 + ((index * 2 + 1) % 7)
            phase = speed * (1 + index * 0.17) + index * 0.73 + partner * 1.1
            radius = scale * (0.32 + 0.55 * min(1.0, energy * settings.response * 5.0))
            modulation = 0.18 + metrics.centroid * 0.55 + metrics.flux * settings.response * 2.0
            r = radius * (0.72 + modulation * np.sin(b * theta + phase) + 0.08 * np.sin((a + b) * theta))
            x = cx + r * np.cos(a * theta + phase * 0.6)
            y = cy + r * np.sin(b * theta - phase * 0.4)
            pts = [(int(px), int(py)) for px, py in zip(x, y)]
            alpha = int(np.clip(95 + energy * settings.response * 300, 90, 235))
            shade = max(150, 245 - index * 10)
            draw.line(pts, fill=(shade, shade, shade, alpha), width=1 + (index % 2))
        mark = int(min(w, h) * 0.035)
        draw.rectangle((cx - mark, cy - mark, cx + mark, cy + mark), outline=(220, 220, 220, 110), width=1)
        return image


class ParticleField(VisualGenerator):
    name = "PARTICLE FIELD"

    def __init__(self):
        self._cache_key = None
        self._points = None

    def _ensure_points(self, size, settings):
        count = int(180 + settings.density * 2600)
        key = (size, count, settings.seed)
        if key != self._cache_key:
            rng = np.random.default_rng(settings.seed)
            self._points = rng.random((count, 2), dtype=np.float32)
            self._cache_key = key

    def render(self, metrics, seconds, size, settings):
        w, h = size
        self._ensure_points(size, settings)
        x0, y0 = self._points[:, 0], self._points[:, 1]
        angle = seconds * (0.12 + settings.speed * 0.9) + x0 * math.tau + metrics.centroid * 3
        warp = 0.015 + metrics.flux * settings.response * 0.035 + metrics.cross * 0.012
        x = x0 + np.sin(y0 * math.tau * 2 + angle) * warp
        y = y0 + np.cos(x0 * math.tau * 3 - angle * 0.7) * warp
        x = (x + np.sin(angle * 0.3) * 0.025) % 1.0
        y = (y + np.cos(angle * 0.27) * 0.018) % 1.0
        xi = np.clip((x * w).astype(np.int32), 0, w - 1)
        yi = np.clip((y * h).astype(np.int32), 0, h - 1)
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        brightness = int(np.clip(130 + metrics.rms * settings.response * 250 + metrics.entropy * 50, 110, 255))
        pixels[yi, xi, :3] = brightness
        pixels[yi, xi, 3] = 210
        image = Image.fromarray(pixels, "RGBA")
        draw = ImageDraw.Draw(image)
        stride = max(1, len(xi) // 420)
        for idx in range(0, len(xi) - stride, stride):
            dx = xi[idx + stride] - xi[idx]
            if abs(dx) < w * 0.25:
                draw.line((int(xi[idx]), int(yi[idx]), int(xi[idx + stride]), int(yi[idx + stride])),
                          fill=(220, 220, 220, 55), width=1)
        return image


class CellularSystem(VisualGenerator):
    name = "CELLULAR SYSTEM"

    def __init__(self):
        self._grid = None
        self._last_step = 0.0
        self._shape = None
        self._rng = None

    def _reset(self, size, settings):
        gw = max(72, int(size[0] // 7))
        gh = max(54, int(size[1] // 7))
        self._shape = (gh, gw, settings.seed)
        self._rng = np.random.default_rng(settings.seed)
        self._grid = (self._rng.random((gh, gw)) > 0.77).astype(np.uint8)
        self._last_step = 0.0

    def render(self, metrics, seconds, size, settings):
        w, h = size
        shape = (max(54, int(h // 7)), max(72, int(w // 7)), settings.seed)
        if self._shape != shape or self._grid is None or seconds < self._last_step:
            self._reset(size, settings)
        step_interval = max(0.025, 0.14 - settings.speed * 0.09)
        steps = min(4, int(max(0.0, seconds - self._last_step) / step_interval))
        for _ in range(steps):
            neighbors = sum(np.roll(np.roll(self._grid, dy, axis=0), dx, axis=1)
                            for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
            flux_drive = float(np.clip(metrics.flux * settings.response * 5.0, 0.0, 0.25))
            birth = (neighbors == 3) | ((neighbors == 6) & (self._rng.random(self._grid.shape) < flux_drive))
            survive = (self._grid == 1) & ((neighbors == 2) | (neighbors == 3))
            self._grid = (birth | survive).astype(np.uint8)
            if metrics.source_count > 1 and metrics.cross < 0.25:
                perturb = self._rng.random(self._grid.shape) < min(0.015, metrics.flux * settings.response)
                self._grid[perturb] ^= 1
            self._last_step += step_interval
        gh, gw = self._grid.shape
        lum = self._grid.astype(np.uint8) * int(np.clip(145 + metrics.rms * settings.response * 220, 145, 255))
        alpha = self._grid.astype(np.uint8) * 225
        small = np.zeros((gh, gw, 4), dtype=np.uint8)
        small[..., :3] = lum[..., None]
        small[..., 3] = alpha
        return Image.fromarray(small, "RGBA").resize(size, Image.Resampling.NEAREST)


class PhaseLattice(VisualGenerator):
    name = "PHASE LATTICE"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cols = int(9 + settings.density * 38)
        rows = max(6, int(cols * h / w))
        xs = np.linspace(w * 0.08, w * 0.92, cols, dtype=np.float32)
        ys = np.linspace(h * 0.08, h * 0.92, rows, dtype=np.float32)
        xg, yg = np.meshgrid(xs, ys)
        phase = seconds * (0.1 + settings.speed * 1.4)
        amp = 4 + metrics.rms * settings.response * 35 + metrics.flux * settings.response * 120
        xwarp = np.sin(yg / h * math.tau * 3 + phase + metrics.centroid * 4) * amp
        ywarp = np.cos(xg / w * math.tau * 4 - phase * 0.8 + metrics.cross * 2) * amp
        points = np.stack((xg + xwarp, yg + ywarp), axis=-1)
        for row in points:
            draw.line([(int(x), int(y)) for x, y in row], fill=(230, 230, 230, 155), width=1)
        for col in range(cols):
            draw.line([(int(points[r, col, 0]), int(points[r, col, 1])) for r in range(rows)],
                      fill=(185, 185, 185, 110), width=1)
        for r in range(rows):
            for c in range(cols):
                if (r + c) % max(2, int(8 - settings.density * 5)) == 0:
                    x, y = points[r, c]
                    rr = 1 + int(metrics.flux * settings.response * 6)
                    draw.ellipse((int(x - rr), int(y - rr), int(x + rr), int(y + rr)), fill=(255, 255, 255, 205))
        return image


class GeneratorBank:
    def __init__(self):
        self._generators: dict[str, VisualGenerator] = {
            InterferenceField.name: InterferenceField(),
            PhaseOrbit.name: PhaseOrbit(),
            ParticleField.name: ParticleField(),
            CellularSystem.name: CellularSystem(),
            PhaseLattice.name: PhaseLattice(),
        }

    def names(self) -> list[str]:
        return list(self._generators)

    def render(self, name: str, packet: dict | None, seconds: float,
               size: tuple[int, int], settings: GeneratorSettings) -> Image.Image:
        generator = self._generators.get(name, self._generators[InterferenceField.name])
        metrics = VisualMetrics.from_packet(packet)
        return generator.render(metrics, seconds, size, settings)
