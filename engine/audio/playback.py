from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from math import gcd
from queue import Queue, Empty, Full

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal
from scipy.signal import resample_poly

from .analyzer import AudioAnalyzer, FeatureFrame
from .source import AudioSource
from .storage import StreamedAudioBuffer


MAX_AUDIO_SOURCES = 64


@dataclass(slots=True)
class _Track:
    track_id: str
    source: AudioSource
    pcm: np.ndarray | None
    cursor: int = 0
    stream: StreamedAudioBuffer | None = None
    frame_count: int = 0


class PlaybackEngine(QObject):
    """One shared output clock, with per-source resampling and background analysis."""

    state_changed = Signal(bool)
    position_changed = Signal(float)
    features_ready = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sample_rate = self._output_sample_rate()
        self.block_size = 1024
        self._tracks: list[_Track] = []
        self._lock = threading.RLock()
        self._stream: sd.OutputStream | None = None
        self._playing = False
        self._loop = False
        self._master_frame = 0
        self._analysis_fft = 4096
        self._analysis_bands = 64
        self._analysis_window = "hann"
        self._analysis_revision = 0
        self._analysis_queue: Queue = Queue(maxsize=4)
        self._analysis_stop = threading.Event()
        self._analysis_thread = threading.Thread(
            target=self._analysis_loop, name="WaveformingAnalysis", daemon=True
        )
        self._analysis_thread.start()
        self._last_emit = 0.0

    @staticmethod
    def _output_sample_rate() -> int:
        try:
            device = sd.query_devices(kind="output")
            return int(round(float(device["default_samplerate"])))
        except Exception:
            return 48000

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    @property
    def source_count(self) -> int:
        with self._lock:
            return len(self._tracks)

    @property
    def duration(self) -> float:
        with self._lock:
            frames = max((track.frame_count for track in self._tracks), default=0)
        return frames / self.sample_rate

    @property
    def position(self) -> float:
        with self._lock:
            return self._master_frame / self.sample_rate

    def add_source(self, source: AudioSource) -> str:
        if len(self._tracks) >= MAX_AUDIO_SOURCES:
            raise ValueError(f"WAVEFORMING supports up to {MAX_AUDIO_SOURCES} audio sources.")

        stream = None
        data = source.samples
        if data is None and source.storage_mode == "stream" and source.sample_rate == self.sample_rate:
            stream = StreamedAudioBuffer(source.path, source.frame_count, source.sample_rate)
        else:
            if data is None:
                data = source.load_into_memory()
            data = np.asarray(data, dtype=np.float32)
            if data.ndim != 2 or data.shape[1] < 1:
                raise ValueError("Audio source must contain at least one channel.")
            if data.shape[1] == 1:
                data = np.repeat(data, 2, axis=1)
            elif data.shape[1] > 2:
                data = data[:, :2]
            if source.sample_rate != self.sample_rate:
                divisor = gcd(int(source.sample_rate), int(self.sample_rate))
                up = self.sample_rate // divisor
                down = int(source.sample_rate) // divisor
                data = resample_poly(data, up, down, axis=0).astype(np.float32, copy=False)
            data = np.ascontiguousarray(data, dtype=np.float32)
            source.samples = data
            source.sample_rate = self.sample_rate
            source.frame_count = len(data)
            source.storage_mode = "memory"

        frame_count = int(source.frame_count if stream is not None else len(data))
        track_id = uuid.uuid4().hex[:10]
        with self._lock:
            cursor = min(self._master_frame, frame_count)
            self._tracks.append(_Track(track_id, source, data, cursor, stream, frame_count))
        return track_id

    def remove_source(self, track_id: str) -> None:
        with self._lock:
            removed = [track for track in self._tracks if track.track_id == track_id]
            self._tracks = [track for track in self._tracks if track.track_id != track_id]
            self._master_frame = min(self._master_frame, max(0, self._max_frames() - 1))
        for track in removed:
            if track.stream is not None:
                track.stream.close()

    def _max_frames(self) -> int:
        return max((track.frame_count for track in self._tracks), default=0)

    def configure_analysis(self, fft_size: int, band_count: int, window: str) -> None:
        with self._lock:
            self._analysis_fft = int(fft_size)
            self._analysis_bands = int(band_count)
            self._analysis_window = str(window).lower()
            self._analysis_revision += 1

    def set_loop(self, enabled: bool) -> None:
        with self._lock:
            self._loop = bool(enabled)

    def play(self) -> None:
        with self._lock:
            if not self._tracks:
                self.error.emit("Import at least one audio source before playback.")
                return
            try:
                if self._stream is None:
                    self._stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        channels=2,
                        dtype="float32",
                        blocksize=self.block_size,
                        latency="low",
                        callback=self._audio_callback,
                    )
                    self._stream.start()
                elif not self._stream.active:
                    self._stream.start()
                self._playing = True
            except Exception as exc:
                self._playing = False
                self.error.emit(f"Audio output could not start: {exc}")
                return
        self.state_changed.emit(True)

    def pause(self) -> None:
        with self._lock:
            self._playing = False
        self.state_changed.emit(False)

    def stop(self) -> None:
        with self._lock:
            self._playing = False
            self._master_frame = 0
            for track in self._tracks:
                track.cursor = 0
        self.state_changed.emit(False)
        self.position_changed.emit(0.0)

    def seek(self, seconds: float) -> None:
        target = max(0, int(float(seconds) * self.sample_rate))
        with self._lock:
            maximum = self._max_frames()
            self._master_frame = min(target, maximum)
            for track in self._tracks:
                track.cursor = min(self._master_frame, track.frame_count)
        self.position_changed.emit(self.position)

    def _audio_callback(self, outdata, frames, time_info, status) -> None:
        outdata.fill(0.0)
        with self._lock:
            if not self._playing:
                return
            tracks = tuple(self._tracks)
            loop = self._loop
            has_solo = any(t.source.solo and not t.source.muted for t in tracks)
            snapshots: dict[str, tuple[np.ndarray, int]] = {}
            mix = np.zeros((frames, 2), dtype=np.float32)
            all_finished = True

            for track in tracks:
                source = track.source
                start = track.cursor
                frame_count = track.frame_count
                audible = not source.muted and (not has_solo or source.solo)
                gain = float(source.gain)
                pan = float(np.clip(source.pan, -1.0, 1.0))
                left_gain = gain * (1.0 if pan <= 0 else 1.0 - pan)
                right_gain = gain * (1.0 if pan >= 0 else 1.0 + pan)

                # The disk-backed reader only copies from its prefilled ring.
                # A cache miss produces silence; it never blocks the audio callback.
                if track.stream is not None:
                    block = np.zeros((frames, 2), dtype=np.float32)
                    if frame_count <= 0:
                        take = 0
                    elif loop:
                        position = start % frame_count
                        offset = 0
                        remaining = frames
                        while remaining:
                            segment = min(remaining, frame_count - position)
                            track.stream.read_into(position, block[offset:offset + segment])
                            offset += segment
                            remaining -= segment
                            position = 0
                        track.cursor = (start + frames) % frame_count
                        take = frames
                        all_finished = False
                    else:
                        take = min(frames, max(0, frame_count - start))
                        if take:
                            track.stream.read_into(start, block[:take])
                        track.cursor = min(start + frames, frame_count)
                        if track.cursor < frame_count:
                            all_finished = False
                    if source.analysis_enabled:
                        snapshots[track.track_id] = (block.copy(), self.sample_rate)
                    if audible and take:
                        block[:, 0] *= left_gain
                        block[:, 1] *= right_gain
                        mix += block
                    continue

                pcm = track.pcm
                if pcm is None or frame_count <= 0:
                    continue
                analysis_block = np.zeros((frames, 2), dtype=np.float32) if source.analysis_enabled else None

                if loop:
                    position = start % frame_count
                    offset = 0
                    remaining = frames
                    while remaining:
                        segment = min(remaining, frame_count - position)
                        source_block = pcm[position:position + segment]
                        if analysis_block is not None:
                            analysis_block[offset:offset + segment] = source_block
                        if audible:
                            mix[offset:offset + segment, 0] += source_block[:, 0] * left_gain
                            mix[offset:offset + segment, 1] += source_block[:, 1] * right_gain
                        offset += segment
                        remaining -= segment
                        position = 0
                    track.cursor = (start + frames) % frame_count
                    all_finished = False
                    take = frames
                else:
                    take = min(frames, max(0, frame_count - start))
                    if take:
                        source_block = pcm[start:start + take]
                        if analysis_block is not None:
                            analysis_block[:take] = source_block
                        if audible:
                            mix[:take, 0] += source_block[:, 0] * left_gain
                            mix[:take, 1] += source_block[:, 1] * right_gain
                    track.cursor = min(start + frames, frame_count)
                    if track.cursor < frame_count:
                        all_finished = False

                if analysis_block is not None:
                    snapshots[track.track_id] = (analysis_block, self.sample_rate)

            if loop and self._max_frames() > 0:
                self._master_frame = (self._master_frame + frames) % self._max_frames()
            else:
                self._master_frame = min(self._master_frame + frames, self._max_frames())
            if all_finished and not loop:
                self._playing = False

            # Analysis remains asynchronous. Keep only the newest packet when
            # the worker falls behind so visual latency cannot grow unbounded.
            if snapshots:
                item = (snapshots, self._master_frame)
                try:
                    self._analysis_queue.put_nowait(item)
                except Full:
                    try:
                        self._analysis_queue.get_nowait()
                    except Empty:
                        pass
                    try:
                        self._analysis_queue.put_nowait(item)
                    except Full:
                        pass

            magnitude = np.abs(mix)
            over = magnitude > 0.98
            mix[over] = np.sign(mix[over]) * (
                0.98 + 0.02 * np.tanh((magnitude[over] - 0.98) / 0.02)
            )
            np.copyto(outdata, mix)
            finished_now = not self._playing

        now = time.monotonic()
        if now - self._last_emit >= 0.08:
            self._last_emit = now
            self.position_changed.emit(self.position)
        if finished_now:
            self.state_changed.emit(False)

    def _analysis_loop(self) -> None:
        analyzers: dict[str, AudioAnalyzer] = {}
        histories: dict[str, np.ndarray] = {}
        revision = -1
        while not self._analysis_stop.is_set():
            try:
                payload = self._analysis_queue.get(timeout=0.2)
            except Empty:
                continue
            if payload is None:
                break
            snapshots, frame_position = payload
            with self._lock:
                current_revision = self._analysis_revision
                fft_size = self._analysis_fft
                band_count = self._analysis_bands
                window = self._analysis_window
            if revision != current_revision:
                analyzers.clear()
                histories.clear()
                revision = current_revision
            frames: dict[str, FeatureFrame] = {}
            correlation_blocks: dict[str, np.ndarray] = {}
            for track_id, (block, sample_rate) in snapshots.items():
                analyzer = analyzers.get(track_id)
                if analyzer is None:
                    analyzer = AudioAnalyzer(fft_size, band_count, window)
                    analyzers[track_id] = analyzer
                previous = histories.get(track_id)
                history = block if previous is None else np.concatenate((previous, block), axis=0)
                history = np.ascontiguousarray(history[-fft_size:])
                histories[track_id] = history
                if len(history) >= fft_size:
                    frames[track_id] = analyzer.analyze(history, sample_rate)
                correlation_blocks[track_id] = np.mean(block, axis=1)

            ids = list(correlation_blocks)
            matrix = np.eye(len(ids), dtype=np.float32)
            # Full pairwise correlation is useful for small sessions, but
            # scales quadratically and is not needed for group-based routing.
            if len(ids) <= 12:
                for i in range(len(ids)):
                    a = correlation_blocks[ids[i]]
                    for j in range(i + 1, len(ids)):
                        b = correlation_blocks[ids[j]]
                        denom = float(np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
                        corr = float(np.dot(a, b) / denom)
                        matrix[i, j] = matrix[j, i] = np.clip(corr, -1.0, 1.0)
            if frames:
                self.features_ready.emit({
                    "frames": frames,
                    "correlation": matrix,
                    "source_ids": ids,
                    "position": frame_position / self.sample_rate,
                })

    def close(self) -> None:
        self._analysis_stop.set()
        try:
            self._analysis_queue.put_nowait(None)
        except Full:
            pass
        if self._analysis_thread.is_alive():
            self._analysis_thread.join(timeout=1.0)
        with self._lock:
            self._playing = False
            stream = self._stream
            self._stream = None
            tracks = tuple(self._tracks)
            self._tracks.clear()
        for track in tracks:
            if track.stream is not None:
                track.stream.close()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
