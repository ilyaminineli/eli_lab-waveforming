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
from engine.visual.project import VisualProject
from engine.visual.scene import VisualScore
from engine.visual.transitions import SceneTransition, SceneTransitionController


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
        visual_scene: dict | None = None,
        visual_project: dict | None = None,
        visual_score: dict | None = None,
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
        self.visual_scene = dict(visual_scene or {})
        self.visual_project_data = dict(visual_project or {})
        self.visual_score_data = dict(visual_score or {})
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

                # Offline export resolves the same persistent scene collection
                # and XM cue routes as live preview. Transition families remain
                # lifecycle contracts here; visual interpolation is a later milestone.
                project_model = (
                    VisualProject.from_dict(self.visual_project_data)
                    if self.visual_project_data else None
                )
                score_model = (
                    VisualScore.from_dict(self.visual_score_data)
                    if self.visual_score_data else None
                )
                transition_controller = SceneTransitionController()
                scene_layers: dict[str, list[VisualLayer]] = {}
                pending_cue_routes: list[dict] = []
                last_cue_scan_position = -1e-6
                if project_model is not None:
                    for scene in project_model.scenes:
                        transition_controller.register_scene(
                            scene,
                            active=(scene.scene_id == project_model.active_scene_id),
                        )
                    scene_layers = {
                        scene_id: [
                            VisualLayer.from_dict(record)
                            for record in records
                        ]
                        for scene_id, records in project_model.layer_snapshots.items()
                    }

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

                        active_transition_sample = transition_controller.sample(seconds)
                        if (
                            active_transition_sample is not None
                            and active_transition_sample.get("completed")
                            and project_model is not None
                        ):
                            project_model.active_scene_id = (
                                transition_controller.active_scene_id
                            )

                        if project_model is not None and score_model is not None:
                            crossed_cues = [
                                cue for cue in score_model.cues
                                if last_cue_scan_position < float(cue.time) <= seconds + 1e-6
                            ]
                            last_cue_scan_position = seconds
                            for cue in crossed_cues:
                                route = project_model.route_for_cue(cue.cue_id)
                                if route is not None:
                                    pending_cue_routes.append({
                                        "cue": cue.to_dict(),
                                        "route": route,
                                    })

                            if not transition_controller.transition_active:
                                while pending_cue_routes:
                                    pending = pending_cue_routes.pop(0)
                                    cue_data = pending["cue"]
                                    route = pending["route"]
                                    source_id = str(route.get("source_scene_id", ""))
                                    target_id = str(route.get("target_scene_id", ""))
                                    if (
                                        source_id != transition_controller.active_scene_id
                                        or target_id == source_id
                                    ):
                                        continue
                                    trigger = {
                                        "type": "tracker_cue",
                                        "cue_id": cue_data.get("cue_id", ""),
                                        "order": cue_data.get("payload", {}).get("order"),
                                        "pattern": cue_data.get("payload", {}).get("pattern"),
                                        "cue_time": cue_data.get("time", 0.0),
                                    }
                                    try:
                                        transition = SceneTransition(
                                            source_scene_id=source_id,
                                            target_scene_id=target_id,
                                            family=str(route.get("family", "dissolve")),
                                            duration_seconds=float(
                                                route.get("duration_seconds", 2.0)
                                            ),
                                            easing=str(route.get("easing", "smoothstep")),
                                            interruption_policy=str(
                                                route.get("interruption_policy", "cancel")
                                            ),
                                            outgoing_policy=str(
                                                route.get("outgoing_policy", "archive")
                                            ),
                                            trigger=trigger,
                                        )
                                        proposal = transition_controller.propose(
                                            transition,
                                            proposed_at=float(cue_data.get("time", seconds)),
                                            rationale="XM order/pattern cue route",
                                        )
                                        commit_sample = transition_controller.commit(
                                            proposal.proposal_id,
                                            start_time=float(cue_data.get("time", seconds)),
                                        )
                                        project_model.add_transition(transition)
                                        if commit_sample.get("completed"):
                                            project_model.active_scene_id = (
                                                transition_controller.active_scene_id
                                            )
                                        break
                                    except (ValueError, RuntimeError):
                                        continue

                            active_transition_sample = transition_controller.sample(seconds)
                            if (
                                active_transition_sample is not None
                                and active_transition_sample.get("completed")
                            ):
                                project_model.active_scene_id = (
                                    transition_controller.active_scene_id
                                )

                        director_output = director.update(packet, seconds)
                        packet["director_output"] = {
                            "glitch_amount": director_output.glitch_amount,
                            "accent_amount": director_output.accent_amount,
                            "state": director_output.state,
                        }
                        active_scene_id = (
                            project_model.active_scene_id
                            if project_model is not None else ""
                        )
                        frame_layers = (
                            scene_layers.get(active_scene_id, [])
                            if project_model is not None else self.layers
                        )
                        if director_output.request_variation and frame_layers:
                            # A frame-derived seed makes automatic offline changes reproducible.
                            seed = (
                                int(self.settings.seed) + frame_index * 104729
                            ) & 0x7FFFFFFF
                            frame_layers = vary_composition(
                                frame_layers, compositor.generator_names(), seed
                            )
                            if project_model is not None:
                                scene_layers[active_scene_id] = frame_layers
                                project_model.store_layers(
                                    active_scene_id,
                                    [layer.to_dict() for layer in frame_layers],
                                )
                            else:
                                self.layers = frame_layers
                            self.settings.seed = seed

                        frame_scene = self.visual_scene
                        if project_model is not None:
                            active_scene = project_model.get_scene(active_scene_id)
                            frame_scene = (
                                active_scene.to_dict()
                                if active_scene is not None else {}
                            )
                            frame_scene["resolved_state"] = {
                                "project_id": project_model.project_id,
                                "active_scene_id": active_scene_id,
                                "scene_states": {
                                    scene.scene_id: scene.state
                                    for scene in project_model.scenes
                                },
                                "transition_active": transition_controller.transition_active,
                                "transition": dict(active_transition_sample or {}),
                                "pending_cue_routes": len(pending_cue_routes),
                            }
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
                            layers=frame_layers,
                            settings=frame_settings,
                            screen=self.screen,
                            feedback_enabled=bool(self.feedback.get("enabled", False)),
                            feedback_amount=float(self.feedback.get("amount", 0.28)),
                            feedback_decay=float(self.feedback.get("decay", 0.88)),
                            feedback_shift=float(self.feedback.get("shift", 0.0)),
                            visual_scene=frame_scene,
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
