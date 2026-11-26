from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import soundfile as sf


class StreamedAudioBuffer:
    """Non-blocking disk-backed stereo buffer.

    A worker thread fills a circular PCM cache. The audio callback only copies
    already-buffered samples; a cache miss returns silence and increments
    underruns rather than waiting for disk I/O.
    """

    def __init__(
        self,
        path: Path,
        frame_count: int,
        sample_rate: int,
        *,
        chunk_frames: int = 8192,
        ring_chunks: int = 8,
        lookbehind_frames: int = 16384,
    ) -> None:
        self.path = Path(path)
        self.frame_count = int(frame_count)
        self.sample_rate = int(sample_rate)
        self.channels = 2
        self.chunk_frames = max(1024, int(chunk_frames))
        self.capacity = self.chunk_frames * max(3, int(ring_chunks))
        self.lookbehind_frames = min(
            max(0, int(lookbehind_frames)), max(0, self.capacity - self.chunk_frames)
        )
        self._ring = np.zeros((self.capacity, 2), dtype=np.float32)
        self._head_frames = min(self.chunk_frames, self.frame_count)
        self._head = np.zeros((self._head_frames, 2), dtype=np.float32)
        if self._head_frames:
            head, _ = sf.read(
                str(self.path),
                start=0,
                frames=self._head_frames,
                dtype="float32",
                always_2d=True,
            )
            if head.shape[1] == 1:
                head = np.repeat(head, 2, axis=1)
            elif head.shape[1] > 2:
                head = head[:, :2]
            self._head[: len(head)] = head
            self._head_frames = len(head)
        self._ring_start = 0
        self._write_pos = 0
        self._requested_pos = 0
        self._condition = threading.Condition()
        self._stop = False
        self.underruns = 0
        self._thread = threading.Thread(
            target=self._reader_loop,
            name=f"WaveformingStream-{self.path.stem[:24]}",
            daemon=True,
        )
        self._thread.start()

    def _reader_loop(self) -> None:
        try:
            with sf.SoundFile(str(self.path), mode="r") as reader:
                while True:
                    with self._condition:
                        if self._stop:
                            return
                        requested = self._requested_pos
                        if requested < self._ring_start or requested > self._write_pos:
                            self._ring_start = requested
                            self._write_pos = requested
                        elif requested > self._ring_start:
                            # Keep a bounded look-behind for trailing FFT windows.
                            keep_from = max(0, requested - self.lookbehind_frames)
                            self._ring_start = min(keep_from, self._write_pos)
                        buffered_ahead = self._write_pos - requested
                        free = self.capacity - (self._write_pos - self._ring_start)
                        if (
                            free < self.chunk_frames
                            or buffered_ahead >= self.capacity - self.chunk_frames
                        ):
                            self._condition.wait(timeout=0.02)
                            continue
                        position = self._write_pos
                        count = min(self.chunk_frames, self.frame_count - position)
                        if count <= 0:
                            self._condition.wait(timeout=0.03)
                            continue

                    reader.seek(position)
                    data = reader.read(count, dtype="float32", always_2d=True)
                    if data.size == 0:
                        with self._condition:
                            self._condition.wait(timeout=0.03)
                        continue
                    if data.shape[1] == 1:
                        data = np.repeat(data, 2, axis=1)
                    elif data.shape[1] > 2:
                        data = data[:, :2]
                    data = np.ascontiguousarray(data, dtype=np.float32)

                    with self._condition:
                        # A seek may have arrived while the worker was reading.
                        if position != self._write_pos:
                            continue
                        offset = position % self.capacity
                        first = min(len(data), self.capacity - offset)
                        self._ring[offset : offset + first] = data[:first]
                        if first < len(data):
                            self._ring[: len(data) - first] = data[first:]
                        self._write_pos = position + len(data)
                        self._ring_start = max(
                            self._ring_start, self._write_pos - self.capacity
                        )
                        self._condition.notify_all()
        except Exception:
            # The callback stays real-time safe. A failed reader behaves like
            # an empty stream and reports cache misses through underruns.
            with self._condition:
                self._stop = True
                self._condition.notify_all()

    def read_into(
        self, position: int, destination: np.ndarray, *, update_request: bool = True
    ) -> int:
        """Copy buffered samples without waiting; optionally leave prefetch state untouched."""
        if destination.ndim != 2 or destination.shape[1] != 2:
            raise ValueError("Destination must have shape (frames, 2).")
        destination.fill(0.0)
        length = len(destination)
        position = max(0, int(position))
        with self._condition:
            end = position + length
            # Serve the synchronously pre-read head before the background ring
            # catches up. This avoids silence on the first audio blocks and also
            # makes an imported streamed source available to the still preview.
            if end <= self._head_frames:
                destination[:] = self._head[position:end]
                if update_request:
                    self._requested_pos = max(self._requested_pos, end)
                    self._condition.notify()
                return length
            if position < self._ring_start or end > self._write_pos:
                if update_request:
                    self._requested_pos = position
                    self._condition.notify()
                    self.underruns += 1
                return 0
            offset = position % self.capacity
            first = min(length, self.capacity - offset)
            destination[:first] = self._ring[offset : offset + first]
            if first < length:
                destination[first:] = self._ring[: length - first]
            if update_request:
                self._requested_pos = end
                self._condition.notify()
            return length

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
