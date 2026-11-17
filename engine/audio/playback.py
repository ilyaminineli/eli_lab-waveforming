from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from math import gcd
from queue import Queue, Empty, Full

import numpy as np
from PySide6.QtCore import QObject, Signal
from scipy.signal import resample_poly

from .analyzer import AudioAnalyzer, FeatureFrame
from .source import AudioSource


@dataclass(slots=True)
class _Track:
    track_id: str
    source: AudioSource
    pcm: np.ndarray
    cursor: int = 0


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
        self._stream = None
        self._playing = False
        self._loop = False
        self._master_frame = 0
        self._analysis_fft = 4096
        self._analysis_bands = 64
        self._analysis_window = "hann"
        self._analysis_revision = 0
        # Visual descriptors do not need one FFT per 1024-sample audio callback.
        # Eight updates per second keeps seven-source sessions practical on low-power CPUs.
        self._analysis_interval_frames = max(self.block_size, int(self.sample_rate / 8))
        self._analysis_frames_elapsed = 0
        self._analysis_queue: Queue = Queue(maxsize=2)
        self._analysis_stop = threading.Event()
        self._analysis_thread = threading.Thread(
            target=self._analysis_loop, name="WaveformingAnalysis", daemon=True
        )
        self._analysis_thread.start()
        self._last_emit = 0.0

    @staticmethod
    def _output_sample_rate() -> int:
        # sounddevice initializes PortAudio at import time. Keep it lazy so
        # importing the engine, opening a project or running headless tests
        # does not require an active PulseAudio/WASAPI/CoreAudio output device.
        try:
            import sounddevice as sd
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
            frames = max((len(track.pcm) for track in self._tracks), default=0)
        return frames / self.sample_rate

    @property
    def position(self) -> float:
        with self._lock:
            return self._master_frame / self.sample_rate

    def add_source(self, source: AudioSource) -> str:
        data = np.asarray(source.samples, dtype=np.float32)
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
        # Keep only the device-rate buffer to avoid retaining a second full-length
        # decoded copy alongside the resampled playback copy.
        source.samples = data
        source.sample_rate = self.sample_rate
        track_id = uuid.uuid4().hex[:10]
        with self._lock:
            # Sources imported during a session join at the current shared playhead.
            cursor = min(self._master_frame, len(data))
            self._tracks.append(_Track(track_id, source, data, cursor))
            self._invalidate_analysis_locked()
        return track_id

    def remove_source(self, track_id: str) -> None:
        with self._lock:
            self._tracks = [track for track in self._tracks if track.track_id != track_id]
            self._master_frame = min(self._master_frame, max(0, self._max_frames() - 1))
            self._invalidate_analysis_locked()

    def _invalidate_analysis_locked(self) -> None:
        self._analysis_revision += 1
        self._analysis_frames_elapsed = 0
        while True:
            try:
                self._analysis_queue.get_nowait()
            except Empty:
                break

    def _max_frames(self) -> int:
        return max((len(track.pcm) for track in self._tracks), default=0)

    def configure_analysis(self, fft_size: int, band_count: int, window: str) -> None:
        with self._lock:
            self._analysis_fft = int(fft_size)
            self._analysis_bands = int(band_count)
            self._analysis_window = str(window).lower()
            self._invalidate_analysis_locked()

    def set_loop(self, enabled: bool) -> None:
        with self._lock:
            self._loop = bool(enabled)

    def play(self) -> None:
        with self._lock:
            if not self._tracks:
                self.error.emit("Import at least one audio source before playback.")
                return
            try:
                # Initialize PortAudio only when playback is requested. This also
                # gives the UI a recoverable error on machines without an output
                # device instead of failing during module import.
                import sounddevice as sd
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
            self._analysis_frames_elapsed = 0
        self.state_changed.emit(False)
        self.position_changed.emit(0.0)

    def seek(self, seconds: float) -> None:
        target = max(0, int(float(seconds) * self.sample_rate))
        with self._lock:
            maximum = self._max_frames()
            self._master_frame = min(target, maximum)
            for track in self._tracks:
                track.cursor = min(self._master_frame, len(track.pcm))
            self._analysis_frames_elapsed = 0
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
            self._analysis_frames_elapsed += frames
            analysis_due = self._analysis_frames_elapsed >= self._analysis_interval_frames
            if analysis_due:
                self._analysis_frames_elapsed %= self._analysis_interval_frames
            analysis_revision = self._analysis_revision
            analysis_fft = self._analysis_fft
            analysis_bands = self._analysis_bands
            analysis_window = self._analysis_window
            mix = np.zeros((frames, 2), dtype=np.float32)
            all_finished = True

            for track in tracks:
                source = track.source
                start = track.cursor
                audible = not source.muted and (not has_solo or source.solo)
                if audible:
                    pan = float(np.clip(source.pan, -1.0, 1.0))
                    gain_left = float(source.gain) * (1.0 if pan <= 0 else 1.0-pan)
                    gain_right = float(source.gain) * (1.0 if pan >= 0 else 1.0+pan)
                else:
                    gain_left = gain_right = 0.0

                if loop and len(track.pcm) > 0:
                    cursor = start % len(track.pcm)
                    written = 0
                    while written < frames:
                        count = min(frames-written, len(track.pcm)-cursor)
                        if audible:
                            segment = track.pcm[cursor:cursor+count]
                            mix[written:written+count, 0] += segment[:, 0] * gain_left
                            mix[written:written+count, 1] += segment[:, 1] * gain_right
                        written += count
                        cursor = (cursor+count) % len(track.pcm)
                    track.cursor = cursor
                    all_finished = False
                else:
                    available = len(track.pcm)-start
                    take = min(frames, max(0, available))
                    if audible and take > 0:
                        segment = track.pcm[start:start+take]
                        mix[:take, 0] += segment[:, 0] * gain_left
                        mix[:take, 1] += segment[:, 1] * gain_right
                    track.cursor = min(start+frames, len(track.pcm))
                    if track.cursor < len(track.pcm):
                        all_finished = False

                if source.analysis_enabled and analysis_due:
                    # The callback snapshots a complete FFT window ending at the
                    # current playhead. The analysis worker can drop stale packets
                    # without ever joining non-contiguous PCM fragments.
                    window_size = analysis_fft
                    end = track.cursor
                    if loop and len(track.pcm):
                        indices = (
                            np.arange(window_size, dtype=np.int64) + end - window_size
                        ) % len(track.pcm)
                        analysis_block = track.pcm[indices].copy()
                    else:
                        window_start = end-window_size
                        source_start = max(0, window_start)
                        analysis_block = np.zeros((window_size, 2), dtype=np.float32)
                        if end > source_start:
                            target_start = source_start-window_start
                            analysis_block[target_start:target_start+end-source_start] = (
                                track.pcm[source_start:end]
                            )
                    snapshots[track.track_id] = (analysis_block, self.sample_rate)

            if loop and self._max_frames() > 0:
                self._master_frame = (self._master_frame+frames) % self._max_frames()
            else:
                self._master_frame = min(self._master_frame+frames, self._max_frames())
            if all_finished and not loop:
                self._playing = False

            # The callback only performs bounded PCM mixing/copies and a non-blocking
            # queue operation. FFTs and descriptors stay on the analysis worker.
            if snapshots:
                item = (
                    snapshots, self._master_frame, analysis_revision,
                    analysis_fft, analysis_bands, analysis_window,
                )
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

            # Avoid allocating a magnitude array on every callback when the mix
            # is already below the soft ceiling.
            peak = max(float(np.max(mix)), float(-np.min(mix)))
            if peak > 0.98:
                magnitude = np.abs(mix)
                over = magnitude > 0.98
                mix[over] = np.sign(mix[over]) * (
                    0.98 + 0.02*np.tanh((magnitude[over]-0.98)/0.02)
                )
            np.copyto(outdata, mix)
            finished_now = not self._playing

        now = time.monotonic()
        if now-self._last_emit >= 0.08:
            self._last_emit = now
            self.position_changed.emit(self.position)
        if finished_now:
            self.state_changed.emit(False)

    def _analysis_loop(self) -> None:
        analyzers: dict[str, AudioAnalyzer] = {}
        revision = -1

        # The analysis thread is deliberately lower priority than the PortAudio
        # callback so a dense seven-source analysis cannot cause output underruns.
        try:
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.GetCurrentThread.restype = ctypes.c_void_p
                kernel32.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
                kernel32.SetThreadPriority.restype = ctypes.c_int
                kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)
            else:
                os.nice(4)
        except Exception:
            pass

        while not self._analysis_stop.is_set():
            try:
                payload = self._analysis_queue.get(timeout=0.2)
            except Empty:
                continue
            if payload is None:
                break
            snapshots, frame_position, packet_revision, fft_size, band_count, window = payload
            with self._lock:
                if packet_revision != self._analysis_revision:
                    continue
            if revision != packet_revision:
                analyzers.clear()
                revision = packet_revision

            frames: dict[str, FeatureFrame] = {}
            correlation_blocks: dict[str, np.ndarray] = {}
            for track_id, (block, sample_rate) in snapshots.items():
                analyzer = analyzers.get(track_id)
                if analyzer is None:
                    analyzer = AudioAnalyzer(fft_size, band_count, window)
                    analyzers[track_id] = analyzer
                # Each packet already contains a complete FFT-sized PCM window.
                # No history concatenation or second copy is needed here.
                frames[track_id] = analyzer.analyze(block, sample_rate)
                correlation_blocks[track_id] = np.mean(block, axis=1)

            ids = list(correlation_blocks)
            matrix = np.eye(len(ids), dtype=np.float32)
            common_length = min((len(correlation_blocks[key]) for key in ids), default=0)
            for i in range(len(ids)):
                a = correlation_blocks[ids[i]][-common_length:] if common_length else np.zeros(0, np.float32)
                for j in range(i+1, len(ids)):
                    b = correlation_blocks[ids[j]][-common_length:] if common_length else np.zeros(0, np.float32)
                    denom = float(np.linalg.norm(a)*np.linalg.norm(b)+1e-9)
                    corr = float(np.dot(a,b)/denom) if common_length else 0.0
                    matrix[i,j] = matrix[j,i] = np.clip(corr, -1.0, 1.0)

            with self._lock:
                if packet_revision != self._analysis_revision:
                    continue
            if frames:
                self.features_ready.emit({
                    "frames": frames,
                    "correlation": matrix,
                    "source_ids": ids,
                    "position": frame_position/self.sample_rate,
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
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
