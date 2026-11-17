from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QThread, Signal

from engine.audio.analyzer import AudioAnalyzer
from engine.timeline import Timeline
from engine.visual.assets import AssetCatalog
from engine.visual.compositor import PROJECT_SIZE, VisualCompositor
from engine.visual.generators import GeneratorSettings
from engine.visual.layers import VisualLayer


class OfflineRenderWorker(QThread):
    """Deterministic CPU renderer; playback and the preview thread remain independent."""

    progress = Signal(int, int)
    completed = Signal(str)
    failed = Signal(str)
    render_cancelled = Signal()

    def __init__(
        self,
        output_path: Path,
        assets_root: Path,
        sources: list[dict],
        layers: list[dict],
        settings: dict,
        timeline: dict,
        screen: str,
        sample_rate: int,
        fft_size: int = 4096,
        band_count: int = 64,
        window: str = "hann",
        fps: int = 24,
        resolution: tuple[int, int] = PROJECT_SIZE,
        feedback: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.output_path = Path(output_path)
        self.assets_root = Path(assets_root)
        # PCM arrays are shared read-only with the render thread; scalar controls
        # and layer/timeline records are copied so UI edits cannot change an export.
        self.sources = [
            {
                "track_id": str(source["track_id"]),
                "samples": source["samples"],
                "gain": float(source.get("gain", 1.0)),
                "pan": float(source.get("pan", 0.0)),
                "muted": bool(source.get("muted", False)),
                "solo": bool(source.get("solo", False)),
                "analysis_enabled": bool(source.get("analysis_enabled", True)),
            }
            for source in sources
        ]
        self.layers = [VisualLayer.from_dict(layer) for layer in layers]
        self.settings = GeneratorSettings(**settings)
        self.timeline = Timeline.from_dict(timeline)
        self.screen = str(screen)
        self.sample_rate = int(sample_rate)
        self.fft_size = int(fft_size)
        self.band_count = int(band_count)
        self.window = str(window).lower()
        self.fps = max(1, min(60, int(fps)))
        self.resolution = (
            max(2, int(resolution[0]) // 2 * 2),
            max(2, int(resolution[1]) // 2 * 2),
        )
        self.feedback = dict(feedback or {})
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _duration(self) -> float:
        return max(
            (len(source["samples"]) / max(1, self.sample_rate) for source in self.sources),
            default=0.0,
        )

    def _write_audio_mix(self, path: Path, duration: float) -> None:
        total_frames = max(0, int(math.ceil(duration * self.sample_rate)))
        block_size = 32768
        active_solo = any(source["solo"] and not source["muted"] for source in self.sources)
        with sf.SoundFile(
            str(path), mode="w", samplerate=self.sample_rate,
            channels=2, subtype="PCM_16", format="WAV",
        ) as output:
            for start in range(0, total_frames, block_size):
                if self.cancelled:
                    return
                end = min(total_frames, start + block_size)
                mix = np.zeros((end - start, 2), dtype=np.float32)
                for source in self.sources:
                    if source["muted"] or (active_solo and not source["solo"]):
                        continue
                    samples = source["samples"]
                    available_end = min(end, len(samples))
                    if available_end <= start:
                        continue
                    segment = samples[start:available_end]
                    take = len(segment)
                    pan = float(np.clip(source["pan"], -1.0, 1.0))
                    left_gain = 1.0 if pan <= 0 else 1.0 - pan
                    right_gain = 1.0 if pan >= 0 else 1.0 + pan
                    mix[:take, 0] += segment[:, 0] * source["gain"] * left_gain
                    mix[:take, 1] += segment[:, 1] * source["gain"] * right_gain
                magnitude = np.abs(mix)
                over = magnitude > 0.98
                mix[over] = np.sign(mix[over]) * (
                    0.98 + 0.02 * np.tanh((magnitude[over] - 0.98) / 0.02)
                )
                output.write(np.clip(mix, -1.0, 1.0))

    def _analysis_packet(self, seconds: float, analyzers: dict) -> dict:
        frame_map = {}
        analysis_sources = [
            source for source in self.sources if source["analysis_enabled"]
        ]
        mono_blocks = {}
        center = int(round(seconds * self.sample_rate))
        half = self.fft_size // 2

        for source in analysis_sources:
            track_id = source["track_id"]
            samples = source["samples"]
            start = center - half
            end = start + self.fft_size
            block = np.zeros((self.fft_size, 2), dtype=np.float32)
            source_start = max(0, start)
            source_end = min(len(samples), end)
            if source_end > source_start:
                target_start = source_start - start
                target_end = target_start + (source_end - source_start)
                block[target_start:target_end] = samples[source_start:source_end]
            analyzer = analyzers.get(track_id)
            if analyzer is None:
                analyzer = AudioAnalyzer(self.fft_size, self.band_count, self.window)
                analyzers[track_id] = analyzer
            frame_map[track_id] = analyzer.analyze(block, self.sample_rate)
            mono_blocks[track_id] = np.mean(block, axis=1)

        ids = list(mono_blocks)
        correlation = np.eye(len(ids), dtype=np.float32)
        for i in range(len(ids)):
            a = mono_blocks[ids[i]]
            for j in range(i + 1, len(ids)):
                b = mono_blocks[ids[j]]
                denominator = float(np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
                value = float(np.dot(a, b) / denominator)
                correlation[i, j] = correlation[j, i] = np.clip(value, -1.0, 1.0)
        return {"frames": frame_map, "source_ids": ids, "correlation": correlation}

    def run(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.failed.emit(
                "FFmpeg was not found in PATH. Install FFmpeg and restart WAVEFORMING before exporting MP4."
            )
            return
        if not self.sources:
            self.failed.emit("Import at least one audio source before exporting.")
            return

        duration = self._duration()
        if duration <= 0:
            self.failed.emit("The project has no audio duration to render.")
            return
        total_frames = max(1, int(math.ceil(duration * self.fps)))
        width, height = self.resolution
        output_path = self.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(prefix="waveforming_m5_") as temporary:
                audio_path = Path(temporary) / "mix.wav"
                self._write_audio_mix(audio_path, duration)
                if self.cancelled:
                    self.render_cancelled.emit()
                    return

                command = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "rawvideo", "-pixel_format", "rgba",
                    "-video_size", f"{width}x{height}",
                    "-framerate", str(self.fps), "-i", "pipe:0",
                    "-i", str(audio_path),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", "-shortest",
                    str(output_path),
                ]
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                compositor = VisualCompositor(
                    AssetCatalog(self.assets_root), render_size=self.resolution
                )
                compositor.reset_feedback()
                analyzers = {}

                try:
                    for frame_index in range(total_frames):
                        if self.cancelled:
                            process.terminate()
                            break
                        seconds = frame_index / float(self.fps)
                        packet = self._analysis_packet(seconds, analyzers)
                        frame_settings = self.timeline.settings_at(seconds, self.settings)
                        image = compositor.render(
                            packet=packet,
                            seconds=seconds,
                            layers=self.layers,
                            settings=frame_settings,
                            screen=self.screen,
                            feedback_enabled=bool(self.feedback.get("enabled", False)),
                            feedback_amount=float(self.feedback.get("amount", 0.28)),
                            feedback_decay=float(self.feedback.get("decay", 0.88)),
                            feedback_shift=float(self.feedback.get("shift", 0.0)),
                        )
                        if process.stdin is None:
                            raise RuntimeError("FFmpeg video input pipe was not created.")
                        process.stdin.write(image.tobytes("raw", "RGBA"))
                        self.progress.emit(frame_index + 1, total_frames)

                    if process.stdin is not None:
                        process.stdin.close()
                    if self.cancelled:
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        self.render_cancelled.emit()
                        return
                    return_code = process.wait()
                    if return_code != 0:
                        error = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                        raise RuntimeError(error.strip() or f"FFmpeg exited with code {return_code}.")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

            if not self.cancelled:
                self.completed.emit(str(output_path))
        except BrokenPipeError:
            if self.cancelled:
                self.render_cancelled.emit()
            else:
                self.failed.emit("FFmpeg closed the video input pipe unexpectedly.")
        except Exception as exc:
            if not self.cancelled:
                self.failed.emit(f"Offline render failed: {exc}")
