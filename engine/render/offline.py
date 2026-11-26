from __future__ import annotations

import math
import os
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QThread, Signal

from engine.audio.analyzer import AudioAnalyzer
from engine.audio.feature_bus import FeatureBus
from engine.render.ffmpeg import resolve_ffmpeg
from engine.timeline import Timeline
from engine.tracker.xm import tracker_packet_at
from engine.visual.assets import AssetCatalog
from engine.visual.composition_director import CompositionDirector, vary_composition
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
        director_mode: str = "SEMI-AUTO",
        tracker_data: dict | None = None,
        render_scale: float = 0.5,
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
                "group_id": str(source.get("group_id", "")),
                "group_name": str(source.get("group_name", "")),
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
        self.render_scale = float(max(0.25, min(1.0, render_scale)))
        self.render_resolution = (
            max(2, int(round(self.resolution[0] * self.render_scale)) // 2 * 2),
            max(2, int(round(self.resolution[1] * self.render_scale)) // 2 * 2),
        )
        self.feedback = dict(feedback or {})
        self.tracker_data = dict(tracker_data or {})
        self.director_mode = (
            director_mode if director_mode in CompositionDirector.MODES else "SEMI-AUTO"
        )
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _duration(self) -> float:
        audio_duration = max(
            (
                len(source["samples"]) / max(1, self.sample_rate)
                for source in self.sources
            ),
            default=0.0,
        )
        tracker_duration = float(self.tracker_data.get("duration", 0.0))
        return max(audio_duration, tracker_duration)

    def _write_audio_mix(self, path: Path, duration: float) -> None:
        total_frames = max(0, int(math.ceil(duration * self.sample_rate)))
        block_size = 32768
        active_solo = any(
            source["solo"] and not source["muted"] for source in self.sources
        )
        with sf.SoundFile(
            str(path),
            mode="w",
            samplerate=self.sample_rate,
            channels=2,
            subtype="PCM_16",
            format="WAV",
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
                peak = max(float(np.max(mix)), float(-np.min(mix)))
                if peak > 0.98:
                    magnitude = np.abs(mix)
                    over = magnitude > 0.98
                    mix[over] = np.sign(mix[over]) * (
                        0.98 + 0.02 * np.tanh((magnitude[over] - 0.98) / 0.02)
                    )
                output.write(np.clip(mix, -1.0, 1.0))

    @staticmethod
    def _window_ending_at(
        samples: np.ndarray, end_frame: int, fft_size: int
    ) -> np.ndarray:
        """Return the last fft_size samples ending at end_frame, zero-padded at edges."""
        window_start = int(end_frame) - int(fft_size)
        window_end = int(end_frame)
        block = np.zeros((fft_size, 2), dtype=np.float32)
        source_start = max(0, window_start)
        source_end = min(len(samples), window_end)
        if source_end > source_start:
            target_start = source_start - window_start
            target_end = target_start + (source_end - source_start)
            block[target_start:target_end] = samples[source_start:source_end]
        return block

    def _analysis_packet(self, seconds: float, analyzers: dict) -> dict:
        frame_map = {}
        analysis_sources = [
            source for source in self.sources if source["analysis_enabled"]
        ]
        mono_blocks = {}
        # Live analysis windows end at the audio playhead. Offline analysis uses
        # the same trailing window; a centred window would shift the visual response.
        end_frame = int(round(seconds * self.sample_rate))

        for source in analysis_sources:
            track_id = source["track_id"]
            block = self._window_ending_at(source["samples"], end_frame, self.fft_size)
            analyzer = analyzers.get(track_id)
            if analyzer is None:
                analyzer = AudioAnalyzer(self.fft_size, self.band_count, self.window)
                analyzers[track_id] = analyzer
            frame_map[track_id] = analyzer.analyze(block, self.sample_rate)
            if len(analysis_sources) <= 12:
                mono_blocks[track_id] = np.mean(block, axis=1)

        ids = list(frame_map)
        correlation = np.eye(len(ids), dtype=np.float32)
        if len(ids) <= 12:
            for i in range(len(ids)):
                a = mono_blocks[ids[i]]
                for j in range(i + 1, len(ids)):
                    b = mono_blocks[ids[j]]
                    denominator = float(np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
                    value = float(np.dot(a, b) / denominator)
                    correlation[i, j] = correlation[j, i] = np.clip(value, -1.0, 1.0)
        return {"frames": frame_map, "source_ids": ids, "correlation": correlation}

    def run(self) -> None:
        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            self.failed.emit(
                "FFmpeg was not found. Install the project requirements (imageio-ffmpeg), "
                "add ffmpeg.exe to PATH, or set FFMPEG_BINARY to its full path."
            )
            return
        if not self.sources and not self.tracker_data:
            self.failed.emit("Import an XM tracker score or audio source before exporting.")
            return

        duration = self._duration()
        if duration <= 0:
            self.failed.emit("The project has no audio duration to render.")
            return
        total_frames = max(1, int(math.ceil(duration * self.fps)))
        width, height = self.resolution
        render_width, render_height = self.render_resolution
        output_path = self.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(
                prefix="waveforming_m5_", dir=output_path.parent
            ) as temporary:
                audio_path = Path(temporary) / "mix.wav"
                temporary_video = Path(temporary) / "rendered.mp4"
                has_audio = bool(self.sources)
                if has_audio:
                    self._write_audio_mix(audio_path, duration)
                if self.cancelled:
                    self.render_cancelled.emit()
                    return

                command = [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "rgba",
                    "-video_size",
                    f"{render_width}x{render_height}",
                    "-framerate",
                    str(self.fps),
                    "-i",
                    "pipe:0",
                ]
                if has_audio:
                    command.extend(["-i", str(audio_path)])
                command.extend(["-map", "0:v:0"])
                if has_audio:
                    command.extend(["-map", "1:a:0"])
                else:
                    command.append("-an")
                if (render_width, render_height) != (width, height):
                    # Keep the output dimensions fixed while doing the expensive
                    # Python/Pillow generator work at a smaller internal canvas.
                    command.extend([
                        "-vf",
                        f"scale={width}:{height}:flags=bicubic",
                    ])
                command.extend([
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                ])
                if has_audio:
                    command.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
                command.extend(["-movflags", "+faststart", str(temporary_video)])
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                compositor = VisualCompositor(
                    AssetCatalog(self.assets_root), render_size=self.render_resolution
                )
                compositor.reset_feedback()
                analyzers = {}

                try:
                    analysis_stride = max(
                        1, int(math.ceil(self.fps / min(8.0, float(self.fps))))
                    )
                    feature_bus = FeatureBus(analysis_rate=self.fps / analysis_stride)
                    source_groups = {
                        source["track_id"]: source["group_id"]
                        for source in self.sources
                        if source["group_id"]
                    }
                    director = CompositionDirector(self.director_mode)
                    cached_packet = None
                    for frame_index in range(total_frames):
                        if self.cancelled:
                            process.terminate()
                            break
                        seconds = frame_index / float(self.fps)
                        if has_audio and (
                            cached_packet is None or frame_index % analysis_stride == 0
                        ):
                            raw_packet = self._analysis_packet(seconds, analyzers)
                            raw_packet["position"] = seconds
                            cached_packet = feature_bus.update(
                                raw_packet, source_groups
                            )
                        elif cached_packet is None:
                            # XM-only projects need no audio decoder, FFT, or
                            # placeholder PCM. Tracker events are the score input.
                            cached_packet = {
                                "frames": {},
                                "source_ids": [],
                                "correlation": np.empty((0, 0), dtype=np.float32),
                                "master_features": {},
                                "position": seconds,
                            }
                        packet = dict(cached_packet)
                        packet["position"] = seconds
                        tracker_cue = tracker_packet_at(self.tracker_data, seconds)
                        if tracker_cue is not None:
                            packet["tracker_cue"] = tracker_cue
                        director_output = director.update(packet, seconds)
                        packet["director_output"] = {
                            "glitch_amount": director_output.glitch_amount,
                            "accent_amount": director_output.accent_amount,
                            "state": director_output.state,
                        }
                        if director_output.request_variation and self.layers:
                            # A frame-derived seed makes automatic offline changes reproducible.
                            seed = (
                                int(self.settings.seed) + frame_index * 104729
                            ) & 0x7FFFFFFF
                            self.layers = vary_composition(
                                self.layers, compositor.generator_names(), seed
                            )
                            self.settings.seed = seed
                        frame_settings = self.timeline.settings_at(
                            seconds, self.settings
                        )
                        frame_settings = GeneratorSettings(
                            complexity=max(
                                5.0,
                                min(
                                    100.0,
                                    frame_settings.complexity
                                    * director_output.complexity_scale,
                                ),
                            ),
                            motion=max(
                                0.0,
                                min(
                                    100.0,
                                    frame_settings.motion
                                    * director_output.motion_scale,
                                ),
                            ),
                            sensitivity=frame_settings.sensitivity,
                            seed=frame_settings.seed,
                        )
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
                            raise RuntimeError(
                                "FFmpeg video input pipe was not created."
                            )
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
                        error = (
                            process.stderr.read().decode("utf-8", errors="replace")
                            if process.stderr
                            else ""
                        )
                        raise RuntimeError(
                            error.strip() or f"FFmpeg exited with code {return_code}."
                        )
                    if (
                        not temporary_video.is_file()
                        or temporary_video.stat().st_size <= 0
                    ):
                        raise RuntimeError(
                            "FFmpeg finished without producing a valid MP4 file."
                        )
                    # Only replace the destination after a complete successful encode;
                    # cancellation or failure cannot leave a corrupt partial file.
                    os.replace(temporary_video, output_path)
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
