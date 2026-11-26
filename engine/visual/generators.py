from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@dataclass(slots=True)
class VisualMetrics:
    rms: float = 0.0
    energy: float = 0.0
    transient: float = 0.0
    flux: float = 0.0
    centroid: float = 0.0
    flatness: float = 0.0
    entropy: float = 0.0
    zcr: float = 0.0
    width: float = 0.0
    rolloff: float = 0.0
    crest: float = 0.0
    cross: float = 0.0
    coherence: float = 1.0
    low: float = 0.0
    mid: float = 0.0
    high: float = 0.0
    bands: np.ndarray | None = None
    energies: np.ndarray | None = None
    correlation: np.ndarray | None = None
    source_count: int = 0
    tracker_notes: np.ndarray | None = None
    tracker_instruments: np.ndarray | None = None
    tracker_progress: float = 0.0
    tracker_order: int = -1
    tracker_pattern: int = -1
    tracker_density: float = 0.0
    tracker_row: int = 0
    tracker_row_note_count: int = 0
    tracker_row_activity: float = 0.0
    tracker_pitch_centroid: float = 0.0
    tracker_transition: float = 0.0
    tracker_reprise: bool = False

    @classmethod
    def from_packet(
        cls, packet: dict | None, source_id: str | None = None
    ) -> "VisualMetrics":
        packet = packet or {}
        tracker = packet.get("tracker_cue") or {}
        raw_notes = tracker.get("notes")
        tracker_notes = np.asarray(
            raw_notes if raw_notes is not None else [], dtype=np.uint8
        )
        if tracker_notes.ndim != 2:
            tracker_notes = None
        raw_instruments = tracker.get("instruments")
        tracker_instruments = np.asarray(
            raw_instruments if raw_instruments is not None else [], dtype=np.uint8
        )
        if (
            tracker_instruments.ndim != 2
            or tracker_notes is None
            or tracker_instruments.shape != tracker_notes.shape
        ):
            tracker_instruments = None
        progress = float(np.clip(tracker.get("progress", 0.0), 0.0, 1.0))
        tracker_density = float(np.clip(tracker.get("density", 0.0), 0.0, 1.0))
        if tracker_notes is not None and tracker_notes.size:
            note_rows, note_channels = tracker_notes.shape
            row_index = int(
                np.clip(
                    tracker.get("row_index", int(progress * note_rows)),
                    0,
                    note_rows - 1,
                )
            )
            row_values = tracker_notes[row_index]
            valid_notes = row_values[(row_values >= 1) & (row_values <= 96)]
            row_note_count = int(tracker.get("row_note_count", len(valid_notes)))
            row_activity = float(
                np.clip(
                    tracker.get("row_activity", row_note_count / max(1, note_channels)),
                    0.0,
                    1.0,
                )
            )
            pitch_centroid = (
                float(np.mean(valid_notes) / 96.0) if len(valid_notes) else 0.0
            )
        else:
            row_index = int(tracker.get("row_index", 0))
            row_note_count = int(tracker.get("row_note_count", 0))
            row_activity = float(np.clip(tracker.get("row_activity", 0.0), 0.0, 1.0))
            pitch_centroid = 0.0
        transition_strength = float(
            np.clip(tracker.get("transition_strength", 0.0), 0.0, 1.0)
        )
        # A cue transition is a short structural impulse, not a sustained
        # brightness boost for the entire pattern.
        transition_envelope = transition_strength * max(0.0, 1.0 - progress * 5.0)
        pattern_reprise = bool(tracker.get("pattern_reprise", False))
        tracker_values = {
            "tracker_notes": tracker_notes,
            "tracker_instruments": tracker_instruments,
            "tracker_progress": progress,
            "tracker_order": int(tracker.get("order", -1)),
            "tracker_pattern": int(tracker.get("pattern", -1)),
            "tracker_density": tracker_density,
            "tracker_row": row_index,
            "tracker_row_note_count": row_note_count,
            "tracker_row_activity": row_activity,
            "tracker_pitch_centroid": pitch_centroid,
            "tracker_transition": transition_envelope,
            "tracker_reprise": pattern_reprise,
        }
        tracker_energy = float(
            np.clip(
                tracker_density * 0.20
                + row_activity * 0.48
                + transition_envelope * 0.18
                + (0.06 if pattern_reprise else 0.0),
                0.0,
                0.85,
            )
        )
        tracker_transient = float(
            np.clip(row_activity * 0.55 + transition_envelope * 0.25, 0.0, 0.85)
        )
        frame_map = packet.get("frames", {})
        group_map = packet.get("group_frames", {})
        source_ids = list(packet.get("source_ids") or frame_map.keys())
        group_id = (
            source_id[len("group:") :]
            if source_id and source_id.startswith("group:")
            else source_id
        )
        if group_id and group_id in group_map:
            # A folder is one visual channel even when it contains many stems.
            frames = [group_map[group_id]]
            indices = [0]
        elif source_id:
            if source_id not in frame_map:
                return cls(
                    energy=tracker_energy,
                    transient=tracker_transient,
                    centroid=pitch_centroid,
                    **tracker_values,
                )
            frames = [frame_map[source_id]]
            indices = [source_ids.index(source_id)] if source_id in source_ids else [0]
        else:
            frames = list(frame_map.values())
            indices = list(range(len(frames)))
        if not frames:
            return cls(
                energy=tracker_energy,
                transient=tracker_transient,
                centroid=pitch_centroid,
                **tracker_values,
            )

        def mean(field: str) -> float:
            return float(np.mean([getattr(frame, field) for frame in frames]))

        bands = np.mean(np.stack([frame.bands for frame in frames]), axis=0).astype(
            np.float32
        )
        n = len(bands)
        low = float(np.mean(bands[: max(1, n // 4)]))
        mid = float(np.mean(bands[n // 4 : max(n // 4 + 1, 3 * n // 4)]))
        high = float(np.mean(bands[3 * n // 4 :])) if n else 0.0
        energies = np.asarray([frame.rms for frame in frames], dtype=np.float32)

        full_corr = np.asarray(
            packet.get("correlation", np.eye(len(source_ids))), dtype=np.float32
        )
        if full_corr.ndim == 2 and full_corr.shape[0] >= max(indices, default=-1) + 1:
            corr = full_corr[np.ix_(indices, indices)]
        else:
            corr = np.eye(len(frames), dtype=np.float32)
        if corr.ndim != 2 or corr.size == 0 or corr.shape[0] <= 1:
            cross, coherence = 0.0, 1.0
        else:
            offdiag = corr[np.triu_indices(corr.shape[0], 1)]
            cross = float(np.mean(np.abs(offdiag)))
            coherence = float(np.mean(offdiag))
        rms = mean("rms")
        flux = mean("flux")
        audio_energy = float(np.tanh(rms * 4.5))
        audio_transient = float(np.clip(flux * 32.0, 0.0, 1.0))
        audio_centroid = mean("centroid_norm")
        return cls(
            rms=rms,
            energy=max(audio_energy, tracker_energy * 0.72),
            transient=max(audio_transient, tracker_transient * 0.72),
            flux=flux,
            centroid=(
                (audio_centroid * 0.88 + pitch_centroid * 0.12)
                if row_note_count
                else audio_centroid
            ),
            flatness=mean("flatness"),
            entropy=mean("entropy"),
            zcr=mean("zcr"),
            width=mean("stereo_width"),
            rolloff=mean("rolloff"),
            crest=mean("crest"),
            cross=cross,
            coherence=coherence,
            low=low,
            mid=mid,
            high=high,
            bands=bands,
            energies=energies,
            correlation=corr,
            source_count=len(frames),
            **tracker_values,
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

    def render(
        self,
        metrics: VisualMetrics,
        seconds: float,
        size: tuple[int, int],
        settings: GeneratorSettings,
    ) -> Image.Image:
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
        response, density = settings.response, settings.density
        motion = seconds * (0.15 + settings.speed * 1.8)
        bands = metrics.bands if metrics.bands is not None else np.zeros(64, np.float32)
        low = metrics.low
        mid = metrics.mid
        high = metrics.high
        drive = metrics.energy * response
        field_a = np.sin(
            (x * (8 + 22 * density) + np.sin(y * (4 + 10 * mid) + motion) * 1.8)
            * (1 + metrics.centroid)
        )
        field_b = np.cos(
            (y * (9 + 25 * density) + np.sin(x * (3 + 12 * low) - motion) * 1.6)
            * (1 + metrics.cross)
        )
        field_c = np.sin(
            (x + y) * (4 + 14 * metrics.centroid)
            + motion * 1.7
            + metrics.transient * 2.5
        )
        field = field_a + field_b * (0.65 + metrics.coherence * 0.4) + field_c * 0.32
        ridge = np.abs(
            np.sin(field * (3.0 + density * 13.0) + metrics.entropy * 3.0 + drive)
        )
        threshold = 0.035 + (1 - density) * 0.025 + metrics.transient * 0.045
        alpha = np.where(
            ridge < threshold, np.clip(0.3 + (1 - ridge / threshold) * 0.7, 0, 1), 0
        )
        lum = np.clip(155 + (1 - ridge) * 95 + drive * 50 + high * 35, 0, 255).astype(
            np.uint8
        )
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        pixels[..., :3] = lum[..., None]
        pixels[..., 3] = (alpha * 235).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA")


class PhaseOrbit(VisualGenerator):
    name = "PHASE ORBIT"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        scale = min(w, h) * 0.36
        energies = (
            metrics.energies
            if metrics.energies is not None
            else np.array([metrics.rms], np.float32)
        )
        corr = (
            metrics.correlation
            if metrics.correlation is not None
            else np.eye(len(energies))
        )
        count = max(2, min(8, 2 + metrics.source_count))
        theta = np.linspace(
            0, math.tau * 3.0, int(320 + settings.density * 2100), dtype=np.float32
        )
        speed = seconds * (0.1 + settings.speed * 1.1)
        for index in range(count):
            energy = float(energies[index % len(energies)]) if len(energies) else 0.0
            partner = (
                float(corr[index % corr.shape[0], (index + 1) % corr.shape[1]])
                if corr.size
                else 0.0
            )
            a, b = 2 + (index % 5), 3 + ((index * 2 + 1) % 7)
            phase = (
                speed * (1 + index * 0.17)
                + index * 0.73
                + partner * 1.1
                + metrics.transient * 0.8
            )
            radius = scale * (
                0.28 + 0.62 * np.clip(energy * settings.response * 5, 0, 1)
            )
            modulation = 0.18 + metrics.centroid * 0.55 + metrics.transient * 0.22
            r = radius * (
                0.72
                + modulation * np.sin(b * theta + phase)
                + 0.08 * np.sin((a + b) * theta)
            )
            x = cx + r * np.cos(a * theta + phase * 0.6)
            y = cy + r * np.sin(b * theta - phase * 0.4)
            pts = [(int(px), int(py)) for px, py in zip(x, y)]
            alpha = int(
                np.clip(
                    90 + energy * settings.response * 320 + metrics.transient * 35,
                    80,
                    245,
                )
            )
            shade = max(145, 245 - index * 10)
            draw.line(pts, fill=(shade, shade, shade, alpha), width=1 + (index % 2))
        mark = int(min(w, h) * 0.035)
        draw.rectangle(
            (cx - mark, cy - mark, cx + mark, cy + mark),
            outline=(220, 220, 220, 110),
            width=1,
        )
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
        drive = metrics.energy * settings.response
        phase = (
            seconds * (0.12 + settings.speed * 0.9)
            + x0 * math.tau
            + metrics.centroid * 3
        )
        warp = 0.012 + metrics.transient * 0.06 + metrics.cross * 0.018 + drive * 0.025
        x = x0 + np.sin(y0 * math.tau * 2 + phase) * warp
        y = y0 + np.cos(x0 * math.tau * 3 - phase * 0.7) * warp
        x = (x + np.sin(phase * 0.3 + metrics.low) * 0.025) % 1.0
        y = (y + np.cos(phase * 0.27 + metrics.high) * 0.018) % 1.0
        xi = np.clip((x * w).astype(np.int32), 0, w - 1)
        yi = np.clip((y * h).astype(np.int32), 0, h - 1)
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        brightness = int(
            np.clip(
                120 + drive * 90 + metrics.entropy * 55 + metrics.transient * 65,
                100,
                255,
            )
        )
        pixels[yi, xi, :3] = brightness
        pixels[yi, xi, 3] = 210
        image = Image.fromarray(pixels, "RGBA")
        draw = ImageDraw.Draw(image)
        stride = max(1, len(xi) // 420)
        for idx in range(0, len(xi) - stride, stride):
            if abs(xi[idx + stride] - xi[idx]) < w * 0.25:
                draw.line(
                    (
                        int(xi[idx]),
                        int(yi[idx]),
                        int(xi[idx + stride]),
                        int(yi[idx + stride]),
                    ),
                    fill=(220, 220, 220, 55 + int(metrics.transient * 60)),
                    width=1,
                )
        return image


class CellularSystem(VisualGenerator):
    name = "CELLULAR SYSTEM"

    def __init__(self):
        self._grid = None
        self._shape = None
        self._rng = None
        self._last_time = None
        self._accumulator = 0.0

    def reset(self) -> None:
        self._grid = None
        self._shape = None
        self._rng = None
        self._last_time = None
        self._accumulator = 0.0

    def _reset(self, size, settings):
        gw = max(160, int(size[0] // 3))
        gh = max(120, int(size[1] // 3))
        self._shape = (gh, gw, settings.seed)
        self._rng = np.random.default_rng(settings.seed)
        self._grid = (self._rng.random((gh, gw)) > 0.91).astype(np.float32)
        self._yy = np.linspace(0, math.tau * 2, gh, dtype=np.float32)[:, None]
        self._xx = np.linspace(0, math.tau * 2, gw, dtype=np.float32)[None, :]
        self._last_time = None
        self._accumulator = 0.0

    def _step(self, metrics, settings, step_index):
        grid = self._grid
        padded = np.pad(grid, 1, mode="wrap")
        neighbors = (
            padded[:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, :-2]
            + padded[1:-1, 2:]
            + padded[:-2, :-2]
            + padded[:-2, 2:]
            + padded[2:, :-2]
            + padded[2:, 2:]
        )
        gh, gw = grid.shape
        yy = self._yy
        xx = self._xx
        phase = step_index * 0.11 + metrics.centroid * math.tau
        # Low, middle and high bands push different spatial axes.
        forcing = (
            np.sin(yy * (1 + metrics.low * 5) + phase) * metrics.low
            + np.cos(xx * (1 + metrics.high * 7) - phase) * metrics.high
        ) * 0.5
        forcing = forcing + metrics.mid * np.sin((xx + yy) * 2 + phase)
        transient = metrics.transient * settings.response
        # The field is continuous and decays slightly, so use tolerant neighbour
        # bands instead of exact integer comparisons (which would stop births).
        birth_target = 2.75 if metrics.centroid > 0.58 else 3.0
        birth_tolerance = 0.42 + metrics.low * 0.12
        births = (neighbors >= birth_target - birth_tolerance) & (
            neighbors <= birth_target + birth_tolerance
        )
        births |= (
            (neighbors >= 2.0)
            & (neighbors <= 2.45)
            & (forcing > 0.55 + metrics.mid * 0.15)
        )
        survival = (neighbors >= 1.55) & (
            neighbors <= 3.75 + (1 if metrics.energy > 0.45 else 0)
        )
        next_grid = np.where(
            births, 1.0, np.where(survival, grid * 0.992, grid * 0.015)
        )
        # Transients excite short radial and diagonal fronts, rather than merely
        # changing the output brightness.
        probability = 0.0007 + min(0.045, transient * 0.055) + metrics.energy * 0.003
        injection = self._rng.random(grid.shape) < probability
        next_grid[injection] = 1.0
        if transient > 0.08:
            cx = int((0.5 + 0.28 * math.sin(phase)) * gw)
            cy = int((0.5 + 0.28 * math.cos(phase * 0.73)) * gh)
            radius = max(2, int(2 + transient * 13))
            yy0, xx0 = np.ogrid[:gh, :gw]
            ring = np.abs(np.sqrt((xx0 - cx) ** 2 + (yy0 - cy) ** 2) - radius) < 1.8
            next_grid[ring] = np.maximum(next_grid[ring], 0.85)
        self._grid = np.clip(next_grid, 0, 1).astype(np.float32)

    def render(self, metrics, seconds, size, settings):
        w, h = size
        shape = (max(120, int(h // 3)), max(160, int(w // 3)), settings.seed)
        if (
            self._shape != shape
            or self._grid is None
            or (self._last_time is not None and seconds < self._last_time)
        ):
            self._reset(size, settings)
        if self._last_time is None:
            self._last_time = seconds
        elapsed = max(0.0, min(0.18, seconds - self._last_time))
        self._last_time = seconds
        step_interval = max(0.018, 0.075 - settings.speed * 0.045)
        self._accumulator += elapsed
        steps = min(6, int(self._accumulator / step_interval))
        for _ in range(steps):
            self._step(metrics, settings, int(seconds / step_interval) - steps + _)
            self._accumulator -= step_interval
        grid = self._grid
        # Contrast follows energy, while alpha/density follows transients.
        intensity = np.clip(
            grid * (150 + metrics.energy * 65 + metrics.transient * 70), 0, 255
        )
        alpha = np.clip(grid * (150 + metrics.transient * 105), 0, 245)
        rgba = np.zeros((grid.shape[0], grid.shape[1], 4), dtype=np.uint8)
        rgba[..., :3] = intensity[..., None].astype(np.uint8)
        rgba[..., 3] = alpha.astype(np.uint8)
        return Image.fromarray(rgba, "RGBA").resize(size, Image.Resampling.NEAREST)


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
        amp = 3 + metrics.energy * settings.response * 45 + metrics.transient * 60
        xwarp = np.sin(yg / h * math.tau * 3 + phase + metrics.centroid * 4) * amp
        ywarp = np.cos(xg / w * math.tau * 4 - phase * 0.8 + metrics.cross * 2) * amp
        points = np.stack((xg + xwarp, yg + ywarp), axis=-1)
        for row in points:
            draw.line(
                [(int(x), int(y)) for x, y in row], fill=(230, 230, 230, 155), width=1
            )
        for col in range(cols):
            draw.line(
                [(int(points[r, col, 0]), int(points[r, col, 1])) for r in range(rows)],
                fill=(185, 185, 185, 110),
                width=1,
            )
        interval = max(2, int(8 - settings.density * 5))
        for r in range(rows):
            for c in range(cols):
                if (r + c) % interval == 0:
                    x, y = points[r, c]
                    rr = 1 + int(metrics.transient * 6 * settings.response)
                    draw.ellipse(
                        (int(x - rr), int(y - rr), int(x + rr), int(y + rr)),
                        fill=(255, 255, 255, 170 + int(metrics.energy * 70)),
                    )
        return image


class ReactionDiffusion(VisualGenerator):
    name = "REACTION DIFFUSION"

    def __init__(self):
        self.u = None
        self.v = None
        self._shape = None
        self._last_time = None
        self._accumulator = 0.0
        self._rng = np.random.default_rng(31)

    @staticmethod
    def _laplace(field):
        # A single wrapped pad plus zero-copy neighbour views is cheaper than
        # creating eight separate rolled arrays for every diffusion step.
        padded = np.pad(field, 1, mode="wrap")
        cardinals = (
            padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] + padded[1:-1, 2:]
        )
        diagonals = (
            padded[:-2, :-2] + padded[:-2, 2:] + padded[2:, :-2] + padded[2:, 2:]
        )
        return cardinals * 0.2 + diagonals * 0.05 - field

    def reset(self) -> None:
        self.u = None
        self.v = None
        self._shape = None
        self._last_time = None
        self._accumulator = 0.0

    def _reset(self, size, settings):
        gh = max(112, int(size[1] // 3))
        gw = max(160, int(size[0] // 3))
        self._shape = (gh, gw, settings.seed)
        self.u = np.ones((gh, gw), dtype=np.float32)
        self.v = np.zeros((gh, gw), dtype=np.float32)
        rng = np.random.default_rng(settings.seed)
        for _ in range(4):
            cx = int(rng.integers(gw // 5, 4 * gw // 5))
            cy = int(rng.integers(gh // 5, 4 * gh // 5))
            radius = max(4, int(min(gh, gw) * 0.025))
            self.v[cy - radius : cy + radius, cx - radius : cx + radius] = 0.8
            self.u[cy - radius : cy + radius, cx - radius : cx + radius] = 0.15
        self._last_time = None
        self._accumulator = 0.0

    def render(self, metrics, seconds, size, settings):
        w, h = size
        shape = (max(112, int(h // 3)), max(160, int(w // 3)), settings.seed)
        if (
            self._shape != shape
            or self.u is None
            or (self._last_time is not None and seconds < self._last_time)
        ):
            self._reset(size, settings)
        if self._last_time is None:
            self._last_time = seconds
        elapsed = max(0.0, min(0.15, seconds - self._last_time))
        self._last_time = seconds
        self._accumulator += elapsed
        # Keep the chemistry simulation at a modest independent rate; render FPS
        # and display refresh must not force multiple expensive simulation steps.
        step_interval = 0.075
        steps = min(2, int(self._accumulator / step_interval))
        self._accumulator -= steps * step_interval
        feed = 0.034 + metrics.low * 0.012 + metrics.transient * 0.012
        kill = 0.058 + metrics.high * 0.010 + metrics.cross * 0.004
        for _ in range(steps):
            uvv = self.u * self.v * self.v
            du = 0.16 * self._laplace(self.u) - uvv + feed * (1 - self.u)
            dv = 0.08 * self._laplace(self.v) + uvv - (feed + kill) * self.v
            self.u = np.clip(self.u + du, 0, 1)
            self.v = np.clip(self.v + dv, 0, 1)
            if metrics.transient > 0.12:
                gh, gw = self.v.shape
                cx = int((0.5 + 0.30 * math.sin(seconds * 3 + metrics.centroid)) * gw)
                cy = int((0.5 + 0.30 * math.cos(seconds * 2.1)) * gh)
                radius = max(2, int(3 + metrics.transient * 10))
                self.v[
                    max(0, cy - radius) : cy + radius, max(0, cx - radius) : cx + radius
                ] = np.maximum(
                    self.v[
                        max(0, cy - radius) : cy + radius,
                        max(0, cx - radius) : cx + radius,
                    ],
                    0.75,
                )
        # Render the activator (V) field only. The previous abs(U-V) term is
        # close to 1 across the untouched background and therefore painted an
        # almost opaque tinted rectangle over the entire print area.
        activator = np.clip(self.v, 0.0, 1.0)
        iso_level = 0.105 + metrics.mid * 0.055
        iso_width = 0.018 + metrics.transient * 0.012
        contour = np.clip(1.0 - np.abs(activator - iso_level) / iso_width, 0.0, 1.0)
        body = np.clip((activator - 0.075) * 2.8, 0.0, 1.0)
        texture = np.maximum(contour * 0.82, body * 0.24)
        texture = np.where(activator > 0.065, texture, 0.0)
        rgba = np.zeros((*texture.shape, 4), dtype=np.uint8)
        lum = (155 + texture * 100 + metrics.energy * 12).astype(np.uint8)
        rgba[..., :3] = lum[..., None]
        rgba[..., 3] = np.clip(texture * 215, 0, 215).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA").resize(size, Image.Resampling.BILINEAR)


class LorenzAttractor(VisualGenerator):
    name = "LORENZ ATTRACTOR"

    def __init__(self):
        self._state = None
        self._points = None
        self._key = None

    def render(self, metrics, seconds, size, settings):
        w, h = size
        key = settings.seed
        if self._key != key or self._state is None:
            self._state = np.asarray([0.12, 0.08, 0.04], dtype=np.float64)
            self._points = []
            self._key = key
        sigma = 10.0 + metrics.high * 3.0
        rho = 25.0 + metrics.centroid * 9.0 + metrics.energy * 5.0
        beta = 2.666 + metrics.coherence * 0.18
        dt = 0.0045 + settings.speed * 0.001
        steps = 180 + int(settings.density * 180)
        for _ in range(steps):
            x, y, z = self._state
            dx = sigma * (y - x)
            dy = x * (rho - z) - y
            dz = x * y - beta * z
            self._state += np.asarray([dx, dy, dz]) * dt
            self._points.append(self._state.copy())
        if len(self._points) > 12000:
            self._points = self._points[-12000:]
        points = np.asarray(self._points, dtype=np.float64)
        if len(points) < 2:
            return self._blank(size)
        x = points[:, 0]
        y = points[:, 1]
        z = points[:, 2]
        yaw = seconds * (0.12 + settings.speed * 0.5) + metrics.transient * 0.3
        xr = x * np.cos(yaw) - y * np.sin(yaw)
        yr = x * np.sin(yaw) + y * np.cos(yaw)
        xn = (xr / 38.0 + 0.5) * w
        yn = (0.5 - ((yr + (z - 25) * 0.32) / 48.0)) * h
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        stride = max(1, len(xn) // 4200)
        pts = [
            (int(np.clip(xn[i], 0, w - 1)), int(np.clip(yn[i], 0, h - 1)))
            for i in range(0, len(xn), stride)
        ]
        if len(pts) > 1:
            for i in range(1, len(pts)):
                a = int(80 + 175 * i / len(pts))
                draw.line(
                    (pts[i - 1], pts[i]),
                    fill=(230, 230, 230, a),
                    width=1 + (i % 3 == 0),
                )
        return image


class SpectralTopography(VisualGenerator):
    name = "SPECTRAL TOPOGRAPHY"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        bands = (
            metrics.bands
            if metrics.bands is not None
            else np.zeros(64, dtype=np.float32)
        )
        columns = max(64, int(100 + settings.density * 240))
        x = np.linspace(0, 1, columns, dtype=np.float32)
        spectral = (
            np.interp(x, np.linspace(0, 1, len(bands)), bands)
            if len(bands)
            else np.zeros(columns)
        )
        y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        phase = seconds * (0.08 + settings.speed * 0.6)
        base = np.sin(x[None, :] * math.tau * (2 + settings.density * 5) + phase) * 0.08
        ridge = np.sin(
            (y * (8 + metrics.low * 18) + base * 3 + metrics.centroid * 2) * math.tau
        )
        spectral_curve = (spectral[None, :] - 0.25) * 0.38
        harmonic = np.sin((x[None, :] * 13 + y * 5 + phase) * math.tau) * 0.06
        field = (
            y
            - 0.5
            - spectral_curve
            - ridge * 0.055
            - harmonic
            - metrics.transient * 0.035
        )
        contour = np.abs(
            np.sin(field * (32 + settings.density * 90) + metrics.entropy * 5)
        )
        band_energy = np.clip(spectral[None, :] * 0.75 + metrics.energy * 0.25, 0, 1)
        alpha = np.where(
            contour < 0.11 + metrics.transient * 0.12, 180 + band_energy * 70, 0
        )
        pixels = np.zeros((h, columns, 4), dtype=np.uint8)
        lum = np.clip(150 + band_energy * 100, 0, 255).astype(np.uint8)
        pixels[..., :3] = lum[..., None]
        pixels[..., 3] = np.clip(alpha, 0, 245).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA").resize(size, Image.Resampling.BILINEAR)


class Phyllotaxis(VisualGenerator):
    name = "PHYLLOTAXIS"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        count = int(240 + settings.density * 2600)
        index = np.arange(count, dtype=np.float32)
        golden = math.pi * (3 - math.sqrt(5))
        phase = seconds * (0.06 + settings.speed * 0.6)
        energy = metrics.energy * settings.response
        radius = np.sqrt(index / count) * min(w, h) * 0.46
        theta = index * golden + phase + metrics.centroid * 1.8
        bands = metrics.bands if metrics.bands is not None else np.zeros(64, np.float32)
        modulation = (
            np.interp(index / count, np.linspace(0, 1, len(bands)), bands)
            if len(bands)
            else 0
        )
        radius *= (
            0.76 + modulation * 0.36 + metrics.transient * 0.12 * np.sin(theta * 3)
        )
        cx = w * 0.5 + np.cos(theta * 0.5) * energy * w * 0.04
        cy = h * 0.5 + np.sin(theta * 0.5) * energy * h * 0.04
        x = cx + radius * np.cos(theta)
        y = cy + radius * np.sin(theta)
        stride = max(1, count // 1600)
        for i in range(0, count, stride):
            rr = 0.6 + modulation[i] * 2.2 + metrics.transient * 1.6
            alpha = int(
                np.clip(95 + modulation[i] * 115 + metrics.energy * 60, 70, 235)
            )
            draw.ellipse(
                (int(x[i] - rr), int(y[i] - rr), int(x[i] + rr), int(y[i] + rr)),
                fill=(240, 240, 240, alpha),
            )
            if i > stride and i % max(2, int(15 - settings.density * 10)) == 0:
                draw.line(
                    (int(x[i - stride]), int(y[i - stride]), int(x[i]), int(y[i])),
                    fill=(190, 190, 190, 75),
                    width=1,
                )
        return image


class MobiusField(VisualGenerator):
    name = "MOBIUS FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        u = np.linspace(0, math.tau, int(60 + settings.density * 120), dtype=np.float32)
        v = np.linspace(-0.8, 0.8, int(12 + settings.density * 28), dtype=np.float32)
        U, V = np.meshgrid(u, v)
        twist = (
            0.5 * U + seconds * (0.08 + settings.speed * 0.5) + metrics.transient * 0.2
        )
        radius = min(w, h) * (0.22 + metrics.energy * 0.13)
        x = (radius + V * radius * 0.55 * np.cos(twist)) * np.cos(U)
        y = (radius + V * radius * 0.55 * np.cos(twist)) * np.sin(U)
        z = V * radius * 0.55 * np.sin(twist)
        tilt = 0.45 + metrics.centroid * 0.6
        xp = cx + x * np.cos(tilt) - z * np.sin(tilt)
        yp = cy + y + z * np.cos(tilt) * 0.42
        for row in range(len(v)):
            pts = [(int(a), int(b)) for a, b in zip(xp[row], yp[row])]
            draw.line(
                pts, fill=(220, 220, 220, int(80 + metrics.energy * 100)), width=1
            )
        for col in range(0, len(u), max(1, int(5 - settings.density * 3))):
            pts = [(int(xp[row, col]), int(yp[row, col])) for row in range(len(v))]
            draw.line(pts, fill=(180, 180, 180, 90), width=1)
        return image


class GeometricPlate(VisualGenerator):
    """Editorial plate: offset planes, registration geometry and measured grid marks."""

    name = "GEOMETRIC PLATE"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        unit = min(w, h)
        energy = metrics.energy * settings.response
        phase = seconds * (0.035 + settings.speed * 0.12) + metrics.centroid * 0.7
        inset = unit * (0.10 + metrics.low * 0.035)
        x0, y0, x1, y1 = inset, inset * 0.72, w - inset, h - inset * 0.72
        line = (236, 236, 232, 205)
        soft = (190, 190, 188, 125)

        # Offset rectangular plates inspired by print registration and editorial layouts.
        for index in range(3):
            dx = (
                math.sin(phase + index * 1.7)
                * unit
                * (0.025 + metrics.transient * 0.025)
            )
            dy = math.cos(phase * 0.83 + index) * unit * 0.018
            pad = index * unit * 0.045
            rect = (x0 + pad + dx, y0 + pad + dy, x1 - pad + dx, y1 - pad + dy)
            draw.rectangle(
                tuple(map(int, rect)),
                outline=line if index == 0 else soft,
                width=max(1, int(unit / 480)),
            )

        # One offset slab and one outlined counter-plane, balanced by the current bands.
        slab_w = w * (0.20 + metrics.mid * 0.10)
        slab_h = h * (0.18 + metrics.high * 0.10)
        shift = math.sin(phase) * w * 0.05
        left_rect = (
            int(cx - slab_w - shift),
            int(cy - slab_h * 0.42),
            int(cx - shift),
            int(cy + slab_h * 0.58),
        )
        right_rect = (
            int(cx + shift),
            int(cy - slab_h * 0.60),
            int(cx + slab_w + shift),
            int(cy + slab_h * 0.40),
        )
        draw.rectangle(
            left_rect, fill=(220, 220, 218, 0), outline=(235, 235, 232, 195), width=2
        )
        draw.rectangle(right_rect, outline=(215, 215, 212, 180), width=2)

        # Technical bars behave like abstract typography, not rendered text.
        bar_count = 7 + int(settings.density * 11)
        bar_x = int(w * 0.14)
        bar_y = int(h * 0.76)
        for index in range(bar_count):
            band = (
                float(metrics.bands[index % len(metrics.bands)])
                if metrics.bands is not None
                else 0.0
            )
            height = int(h * (0.012 + band * 0.085 + metrics.transient * 0.02))
            x = bar_x + index * int(w * 0.034)
            draw.line((x, bar_y - height, x, bar_y), fill=soft, width=2)
        # Crosshair and small corner cuts.
        mark = max(3, int(unit * 0.012))
        for px, py in (
            (int(w * 0.12), int(h * 0.17)),
            (int(w * 0.88), int(h * 0.17)),
            (int(w * 0.12), int(h * 0.83)),
            (int(w * 0.88), int(h * 0.83)),
        ):
            draw.line((px - mark, py, px + mark, py), fill=line, width=1)
            draw.line((px, py - mark, px, py + mark), fill=line, width=1)
        return image


class GeometricField(VisualGenerator):
    """Superformula contours, orbital arcs and non-uniform radial constructions."""

    name = "GEOMETRIC FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        unit = min(w, h)
        theta = np.linspace(0, math.tau, 360, endpoint=True, dtype=np.float32)
        motion = seconds * (0.025 + settings.speed * 0.12)
        base = unit * (0.12 + metrics.energy * 0.11)
        rings = 3 + int(settings.density * 5)
        for ring in range(rings):
            m = 3 + ((ring * 2 + int(metrics.centroid * 8)) % 9)
            n1 = 0.55 + metrics.low * 1.1 + ring * 0.07
            n2 = 1.2 + metrics.mid * 2.2
            n3 = 1.2 + metrics.high * 2.5
            phase = motion * (1 + ring * 0.13) + ring * 0.31
            angle = theta + phase
            radial = (
                np.abs(np.cos(m * angle / 4.0)) ** n2
                + np.abs(np.sin(m * angle / 4.0)) ** n3
            ) ** (-1.0 / max(0.35, n1))
            radial = np.clip(radial, 0.0, 2.6)
            radius = base * (0.50 + ring * 0.24) * radial
            x = cx + radius * np.cos(angle)
            y = cy + radius * np.sin(angle) * (0.78 + metrics.width * 0.22)
            points = [(int(px), int(py)) for px, py in zip(x, y)]
            alpha = int(72 + 25 * ring + metrics.transient * 65)
            draw.line(
                points, fill=(235, 235, 232, min(220, alpha)), width=1 + (ring % 2)
            )

        spokes = 10 + int(settings.density * 22)
        for spoke in range(spokes):
            angle = math.tau * spoke / spokes + motion * 0.7
            inner = base * (0.18 + metrics.low * 0.14)
            outer = base * (1.05 + metrics.high * 0.30)
            start = (cx + math.cos(angle) * inner, cy + math.sin(angle) * inner)
            stop = (cx + math.cos(angle) * outer, cy + math.sin(angle) * outer)
            draw.line(
                (*map(int, start), *map(int, stop)), fill=(205, 205, 202, 70), width=1
            )

        node_count = 8 + int(settings.density * 16)
        for index in range(node_count):
            angle = math.tau * index / node_count + motion
            radius = base * (0.72 + 0.16 * math.sin(angle * 3 + metrics.centroid * 4))
            px = cx + math.cos(angle) * radius
            py = cy + math.sin(angle) * radius
            r = max(1, int(unit * (0.003 + metrics.transient * 0.006)))
            draw.rectangle(
                (int(px - r), int(py - r), int(px + r), int(py + r)),
                fill=(244, 244, 240, 165),
            )
        return image


class AxonometricField(VisualGenerator):
    """Pseudo-3D isometric volumes with audio-controlled extrusion and skew."""

    name = "AXONOMETRIC FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.54
        unit = min(w, h)
        cos30 = 0.8660254
        sin30 = 0.5
        cols = 3 + int(settings.density * 3)
        rows = 2 + int(settings.density * 2)
        spacing = unit * (0.085 + settings.density * 0.018)
        phase = seconds * (0.025 + settings.speed * 0.11)

        def project(x, y, z):
            return (
                cx + (x - y) * cos30 * spacing,
                cy + (x + y) * sin30 * spacing - z * unit * 0.12,
            )

        # A sparse field of extruded rectangular cells, not a noisy particle cloud.
        for row in range(rows):
            for col in range(cols):
                idx = row * cols + col
                bands = (
                    metrics.bands
                    if metrics.bands is not None
                    else np.zeros(64, np.float32)
                )
                band = float(bands[(idx * 7) % len(bands)]) if len(bands) else 0.0
                wave = 0.5 + 0.5 * math.sin(phase + col * 0.72 - row * 0.51)
                height = (
                    0.22
                    + band * 1.35
                    + metrics.energy * 0.75
                    + wave * metrics.transient * 0.9
                )
                x, y = col - (cols - 1) / 2, row - (rows - 1) / 2
                p0 = project(x, y, 0.0)
                p1 = project(x + 0.78, y, 0.0)
                p2 = project(x + 0.78, y + 0.78, 0.0)
                p3 = project(x, y + 0.78, 0.0)
                q0 = project(x, y, height)
                q1 = project(x + 0.78, y, height)
                q2 = project(x + 0.78, y + 0.78, height)
                q3 = project(x, y + 0.78, height)
                base_alpha = int(100 + metrics.energy * 70)
                draw.polygon(
                    [
                        tuple(map(int, p0)),
                        tuple(map(int, p1)),
                        tuple(map(int, q1)),
                        tuple(map(int, q0)),
                    ],
                    fill=(215, 215, 212, int(base_alpha * 0.18)),
                    outline=(224, 224, 220, base_alpha),
                )
                draw.polygon(
                    [
                        tuple(map(int, p1)),
                        tuple(map(int, p2)),
                        tuple(map(int, q2)),
                        tuple(map(int, q1)),
                    ],
                    fill=(185, 185, 182, int(base_alpha * 0.12)),
                    outline=(210, 210, 206, int(base_alpha * 0.8)),
                )
                draw.polygon(
                    [
                        tuple(map(int, q0)),
                        tuple(map(int, q1)),
                        tuple(map(int, q2)),
                        tuple(map(int, q3)),
                    ],
                    outline=(244, 244, 240, min(235, base_alpha + 25)),
                )
                if idx % 2 == 0:
                    draw.line(
                        (*map(int, q0), *map(int, q2)),
                        fill=(220, 220, 216, 90),
                        width=1,
                    )
        # Perspective-like construction axes anchor the volume in the frame.
        extent = spacing * max(cols, rows) * 0.62
        for direction in (-1, 1):
            a = project(-direction * cols * 0.4, -rows * 0.45, 0)
            b = project(direction * cols * 0.7, rows * 0.65, 0)
            draw.line((*map(int, a), *map(int, b)), fill=(190, 190, 186, 75), width=1)
        return image


class PolyhedralField(VisualGenerator):
    """Rotating nested polyhedra, with audio-controlled 3D projection."""

    name = "POLYHEDRAL FIELD"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        draw = ImageDraw.Draw(image)
        cx, cy = w * 0.5, h * 0.5
        unit = min(w, h)
        motion = seconds * (0.025 + settings.speed * 0.10)
        rings = 2 + int(settings.density * 4)
        vertices = []
        for index in range(12):
            angle = math.tau * index / 6
            z = 1.0 if index < 6 else -1.0
            vertices.append((math.cos(angle), math.sin(angle), z * 0.62))
        edges = []
        for a in range(12):
            for b in range(a + 1, 12):
                if (a < 6 and b < 6 and (b - a) in (1, 5)) or (
                    a >= 6 and b >= 6 and (b - a) in (1, 5)
                ):
                    edges.append((a, b))
                elif a < 6 and b >= 6 and (b - 6 - a) in (0, 1, 5):
                    edges.append((a, b))
        for ring in range(rings):
            azimuth = motion * (1 + ring * 0.21) + ring * 0.46 + metrics.centroid
            elevation = 0.48 + metrics.high * 0.36 + ring * 0.035
            scale = unit * (0.10 + ring * 0.075 + metrics.energy * 0.035)
            projected = []
            for x, y, z in vertices:
                xr = x * math.cos(azimuth) - y * math.sin(azimuth)
                yr = x * math.sin(azimuth) + y * math.cos(azimuth)
                yy = yr * math.cos(elevation) - z * math.sin(elevation)
                zz = yr * math.sin(elevation) + z * math.cos(elevation)
                projected.append((cx + xr * scale, cy + yy * scale))
            alpha = min(220, 100 + ring * 20 + int(metrics.transient * 45))
            for a, b in edges:
                pa, pb = projected[a], projected[b]
                draw.line(
                    (*map(int, pa), *map(int, pb)),
                    fill=(225, 225, 220, alpha),
                    width=1 + (ring == rings - 1),
                )
            for px, py in projected:
                rr = max(1, int(unit * 0.003))
                draw.ellipse(
                    (int(px - rr), int(py - rr), int(px + rr), int(py + rr)),
                    fill=(245, 245, 238, alpha),
                )
        return image


class TrackerMatrix(VisualGenerator):
    """Render the current XM pattern as a restrained note/channel matrix."""

    name = "TRACKER MATRIX"

    def render(self, metrics, seconds, size, settings):
        w, h = size
        image = self._blank(size)
        notes = metrics.tracker_notes
        if notes is None or notes.ndim != 2 or not notes.size:
            return image

        rows, channels = notes.shape
        left, right = w * 0.075, w * 0.94
        top, bottom = h * 0.105, h * 0.91
        grid_w, grid_h = right - left, bottom - top
        cell_w, cell_h = grid_w / max(1, channels), grid_h / max(1, rows)
        draw = ImageDraw.Draw(image)

        # Sparse channel rails and row guides stay legible at small preview sizes.
        rail = (170, 178, 190, 72)
        guide = (170, 178, 190, 25)
        for channel in range(channels + 1):
            x = int(left + channel * cell_w)
            draw.line(
                (x, int(top), x, int(bottom)),
                fill=rail if channel % 4 == 0 else guide,
                width=1,
            )
        for row in range(0, rows + 1, 8):
            y = int(top + row * cell_h)
            draw.line(
                (int(left), y, int(right), y),
                fill=rail if row % 16 == 0 else guide,
                width=1,
            )

        palette = (
            (104, 145, 190, 220),
            (188, 166, 106, 220),
            (159, 135, 178, 220),
            (174, 184, 192, 205),
        )
        instruments = metrics.tracker_instruments
        for row in range(rows):
            for channel in range(channels):
                note = int(notes[row, channel])
                if not 1 <= note <= 96:
                    continue
                instrument = (
                    int(instruments[row, channel])
                    if instruments is not None
                    else channel
                )
                x0 = int(left + channel * cell_w + max(1.0, cell_w * 0.13))
                x1 = int(left + (channel + 1) * cell_w - max(1.0, cell_w * 0.13))
                pitch = (note - 1) / 95.0
                bar_h = max(1.0, cell_h * (0.34 + pitch * 0.46))
                y_center = top + (row + 0.5) * cell_h
                y0, y1 = int(y_center - bar_h * 0.5), int(y_center + bar_h * 0.5)
                colour = palette[(max(1, instrument) - 1) % len(palette)]
                draw.rectangle((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)), fill=colour)

        # The playhead advances through the 64-row pattern at tracker row timing.
        playhead_y = int(top + metrics.tracker_progress * grid_h)
        draw.line(
            (int(left), playhead_y, int(right), playhead_y),
            fill=(245, 245, 238, 210),
            width=max(1, int(min(w, h) / 300)),
        )
        cap = max(2, int(cell_w * 0.16))
        draw.rectangle(
            (int(left) - cap, playhead_y - 1, int(left) - 1, playhead_y + 1),
            fill=(245, 245, 238, 230),
        )
        draw.rectangle(
            (int(right) + 1, playhead_y - 1, int(right) + cap, playhead_y + 1),
            fill=(245, 245, 238, 230),
        )

        # Activity ticks identify the currently participating channels.
        for channel in range(channels):
            if np.any(notes[:, channel]):
                x = int(left + (channel + 0.5) * cell_w)
                draw.line(
                    (x, int(top * 0.40), x, int(top * 0.82)),
                    fill=palette[channel % len(palette)],
                    width=max(1, int(cell_w * 0.22)),
                )
        return image


class GeneratorBank:
    def __init__(self):
        self._generators: dict[str, VisualGenerator] = {}
        self._generator_types: dict[str, type[VisualGenerator]] = {}
        self._instances: dict[tuple[str, str], VisualGenerator] = {}
        self._metrics_packet: dict | None = None
        self._metrics_cache: dict[str, VisualMetrics] = {}
        for generator in (
            InterferenceField(),
            PhaseOrbit(),
            ParticleField(),
            CellularSystem(),
            PhaseLattice(),
            ReactionDiffusion(),
            LorenzAttractor(),
            SpectralTopography(),
            Phyllotaxis(),
            MobiusField(),
            GeometricPlate(),
            GeometricField(),
            AxonometricField(),
            PolyhedralField(),
            TrackerMatrix(),
        ):
            self._generators[generator.name] = generator
            self._generator_types[generator.name] = type(generator)

    def names(self) -> list[str]:
        return list(self._generators)

    def reset_states(self) -> None:
        self._instances.clear()

    def release_state(self, state_key: str) -> None:
        for key in [key for key in self._instances if key[0] == state_key]:
            self._instances.pop(key, None)

    def retain_layers(self, active_layers: dict[str, str]) -> None:
        """Drop generator state for removed/hidden/replaced layers."""
        for state_key, generator_name in tuple(self._instances):
            if active_layers.get(state_key) != generator_name:
                self._instances.pop((state_key, generator_name), None)

    def resize_states(self, size: tuple[int, int]) -> None:
        """Recreate simulation buffers after a preview-resolution change."""
        for key, generator in tuple(self._instances.items()):
            if isinstance(generator, (CellularSystem, ReactionDiffusion)):
                generator.reset()

    def _metrics_for(self, packet: dict | None, source_id: str | None) -> VisualMetrics:
        # All layers in a frame share one immutable audio/tracker packet.
        if packet is not self._metrics_packet:
            self._metrics_packet = packet
            self._metrics_cache = {}
        key = source_id or ""
        if key not in self._metrics_cache:
            self._metrics_cache[key] = VisualMetrics.from_packet(
                packet, source_id=source_id
            )
        return self._metrics_cache[key]

    def render(
        self,
        name: str,
        packet: dict | None,
        seconds: float,
        size: tuple[int, int],
        settings: GeneratorSettings,
        state_key: str | None = None,
        source_id: str | None = None,
    ) -> Image.Image:
        selected = name if name in self._generators else "INTERFERENCE FIELD"
        if state_key is None:
            generator = self._generators[selected]
        else:
            key = (state_key, selected)
            if key not in self._instances:
                self._instances[key] = self._generator_types[selected]()
            generator = self._instances[key]
        metrics = self._metrics_for(packet, source_id)
        return generator.render(metrics, seconds, size, settings)
