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
    scratch: np.ndarray | None = None


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
        # Eight updates per second keeps eight-source sessions practical on low-power CPUs.
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
            frames = max((track.frame_count for track in self._tracks), default=0)
        return frames / self.sample_rate

    @property
    def position(self) -> float:
        with self._lock:
            return self._master_frame / self.sample_rate

    def add_source(self, source: AudioSource) -> str:
        """Add a prepared source, streaming long matching-rate files from disk."""
        with self._lock:
            if len(self._tracks) >= MAX_AUDIO_SOURCES:
                raise ValueError(f"WAVEFORMING supports up to {MAX_AUDIO_SOURCES} audio sources.")

        stream = None
        data: np.ndarray | None = source.samples
        if data is None and source.storage_mode == "stream" and source.sample_rate == self.sample_rate:
            stream = StreamedAudioBuffer(source.path, source.frame_count, source.sample_rate)
            frame_count = int(source.frame_count)
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
            frame_count = len(data)

        track_id = uuid.uuid4().hex[:10]
        try:
            with self._lock:
                if len(self._tracks) >= MAX_AUDIO_SOURCES:
                    raise ValueError(f"WAVEFORMING supports up to {MAX_AUDIO_SOURCES} audio sources.")
                cursor = min(self._master_frame, frame_count)
                self._tracks.append(_Track(
                    track_id=track_id,
                    source=source,
                    pcm=data,
                    cursor=cursor,
                    stream=stream,
                    frame_count=frame_count,
                    scratch=np.empty((max(self.block_size, 2048), 2), dtype=np.float32),
                ))
                self._refresh_analysis_interval_locked()
                self._invalidate_analysis_locked()
        except Exception:
            if stream is not None:
                stream.close()
            raise
        return track_id

    def remove_source(self, track_id: str) -> None:
        with self._lock:
            removed = [track for track in self._tracks if track.track_id == track_id]
            self._tracks = [track for track in self._tracks if track.track_id != track_id]
            self._master_frame = min(self._master_frame, max(0, self._max_frames() - 1))
            self._refresh_analysis_interval_locked()
            self._invalidate_analysis_locked()
        for track in removed:
            if track.stream is not None:
                track.stream.close()

    def _invalidate_analysis_locked(self) -> None:
        self._analysis_revision += 1
        self._analysis_frames_elapsed = 0
        while True:
            try:
                self._analysis_queue.get_nowait()
            except Empty:
                break

    def _refresh_analysis_interval_locked(self) -> None:
        count = len(self._tracks)
        rate = 8.0 if count <= 8 else 6.0 if count <= 16 else 3.0
        self._analysis_interval_frames = max(
            self.block_size, int(self.sample_rate / rate)
        )

    def _max_frames(self) -> int:
        return max((track.frame_count for track in self._tracks), default=0)

    def request_preview_analysis(self) -> int:
        """Queue one analysis snapshot per enabled track without starting playback.

        The initial preview uses the next FFT window at the playhead. Streamed
        sources use their pre-read head/ring cache and never wait for disk I/O.
        Returns the number of tracks included in the preview packet.
        """
        with self._lock:
            tracks = tuple(self._tracks)
            revision = self._analysis_revision
            fft_size = self._analysis_fft
            band_count = self._analysis_bands
            window = self._analysis_window
            master_frame = self._master_frame
            playing = self._playing
            loop = self._loop

        snapshots: dict[str, tuple[np.ndarray, int]] = {}
        packet_end = master_frame
        for track in tracks:
            if not track.source.analysis_enabled or track.frame_count <= 0:
                continue

            frame_count = track.frame_count
            cursor = min(max(0, int(track.cursor)), frame_count)
            if playing:
                end = cursor
                available = min(fft_size, end)
                start = end - available
                target_start = fft_size - available
            else:
                start = min(cursor, max(0, frame_count - fft_size))
                end = min(frame_count, start + fft_size)
                available = max(0, end - start)
                target_start = 0

            if not available:
                continue
            block = np.zeros((fft_size, 2), dtype=np.float32)
            destination = block[target_start:target_start + available]

            if track.stream is not None:
                copied = track.stream.read_into(
                    start, destination, update_request=False
                )
                if copied != available:
                    continue
            else:
                pcm = track.pcm
                if pcm is None:
                    continue
                block_slice = pcm[start:end]
                if len(block_slice) != available:
                    continue
                destination[:] = block_slice

            snapshots[track.track_id] = (block, self.sample_rate)
            packet_end = max(packet_end, end)

        if not snapshots:
            return 0

        payload = (
            snapshots, packet_end, revision, fft_size, band_count, window,
        )
        with self._lock:
            if revision != self._analysis_revision:
                return 0
            try:
                self._analysis_queue.put_nowait(payload)
            except Full:
                try:
                    self._analysis_queue.get_nowait()
                except Empty:
                    pass
                try:
                    self._analysis_queue.put_nowait(payload)
                except Full:
                    return 0
        return len(snapshots)

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
                track.cursor = min(self._master_frame, track.frame_count)
            self._analysis_frames_elapsed = 0
        self.position_changed.emit(self.position)

    @staticmethod
    def _read_stream_window(
        stream: StreamedAudioBuffer, frame_count: int, end: int,
        fft_size: int, loop: bool,
    ) -> np.ndarray | None:
        """Copy a full trailing FFT window from bounded ring history."""
        if frame_count <= 0 or fft_size <= 0:
            return None
        result = np.zeros((fft_size, 2), dtype=np.float32)
        end = int(end)
        if loop:
            start = (end - fft_size) % frame_count
            if start + fft_size > frame_count:
                return None
            return result if stream.read_into(start, result, update_request=False) == fft_size else None
        available = min(fft_size, max(0, end))
        if not available:
            return result
        source_start = end - available
        target_start = fft_size - available
        copied = stream.read_into(source_start, result[target_start:], update_request=False)
        return result if copied == available else None

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
                frame_count = track.frame_count
                audible = not source.muted and (not has_solo or source.solo)
                if audible:
                    pan = float(np.clip(source.pan, -1.0, 1.0))
                    gain_left = float(source.gain) * (1.0 if pan <= 0 else 1.0-pan)
                    gain_right = float(source.gain) * (1.0 if pan >= 0 else 1.0+pan)
                else:
                    gain_left = gain_right = 0.0

                if track.stream is not None:
                    if track.scratch is None or track.scratch.shape[0] < frames:
                        track.scratch = np.empty((frames, 2), dtype=np.float32)
                    block = track.scratch[:frames]
                    block.fill(0.0)
                    if frame_count > 0 and loop:
                        position = start % frame_count
                        offset = 0
                        remaining = frames
                        while remaining:
                            count = min(remaining, frame_count-position)
                            track.stream.read_into(position, block[offset:offset+count])
                            offset += count
                            remaining -= count
                            position = 0
                        track.cursor = (start+frames) % frame_count
                        all_finished = False
                        take = frames
                    else:
                        take = min(frames, max(0, frame_count-start))
                        if take:
                            track.stream.read_into(start, block[:take])
                        track.cursor = min(start+frames, frame_count)
                        if track.cursor < frame_count:
                            all_finished = False
                    if audible and take:
                        mix[:, 0] += block[:, 0] * gain_left
                        mix[:, 1] += block[:, 1] * gain_right
                    if source.analysis_enabled and analysis_due:
                        window_block = self._read_stream_window(
                            track.stream, frame_count, track.cursor, analysis_fft, loop
                        )
                        if window_block is not None:
                            snapshots[track.track_id] = (window_block, self.sample_rate)
                    continue

                pcm = track.pcm
                if pcm is None or frame_count <= 0:
                    track.cursor = 0
                    continue

                if loop:
                    position = start % frame_count
                    offset = 0
                    remaining = frames
                    while remaining:
                        count = min(remaining, frame_count-position)
                        if audible:
                            segment = pcm[position:position+count]
                            mix[offset:offset+count, 0] += segment[:, 0] * gain_left
                            mix[offset:offset+count, 1] += segment[:, 1] * gain_right
                        offset += count
                        remaining -= count
                        position = 0
                    track.cursor = (start+frames) % frame_count
                    all_finished = False
                else:
                    take = min(frames, max(0, frame_count-start))
                    if audible and take:
                        segment = pcm[start:start+take]
                        mix[:take, 0] += segment[:, 0] * gain_left
                        mix[:take, 1] += segment[:, 1] * gain_right
                    track.cursor = min(start+frames, frame_count)
                    if track.cursor < frame_count:
                        all_finished = False

                if source.analysis_enabled and analysis_due:
                    window_size = analysis_fft
                    end = track.cursor
                    if loop and frame_count:
                        window_start = (end-window_size) % frame_count
                        if window_start+window_size <= frame_count:
                            snapshots[track.track_id] = (
                                pcm[window_start:window_start+window_size].copy(),
                                self.sample_rate,
                            )
                    else:
                        window_start = end-window_size
                        source_start = max(0, window_start)
                        analysis_block = np.zeros((window_size, 2), dtype=np.float32)
                        if end > source_start:
                            target_start = source_start-window_start
                            analysis_block[target_start:target_start+end-source_start] = (
                                pcm[source_start:end]
                            )
                        snapshots[track.track_id] = (analysis_block, self.sample_rate)

            if loop and self._max_frames() > 0:
                self._master_frame = (self._master_frame+frames) % self._max_frames()
            else:
                self._master_frame = min(self._master_frame+frames, self._max_frames())
            if all_finished and not loop:
                self._playing = False

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
        # callback so a dense multichannel analysis cannot cause output underruns.
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
                if len(snapshots) <= 12:
                    correlation_blocks[track_id] = np.mean(block, axis=1)

            ids = list(frames)
            matrix = np.eye(len(ids), dtype=np.float32)
            if len(ids) <= 12:
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
