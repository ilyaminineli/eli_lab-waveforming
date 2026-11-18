from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class AudioSource:
    path: Path
    samples: np.ndarray | None
    sample_rate: int
    name: str
    gain: float = 1.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False
    analysis_enabled: bool = True
    cursor: int = 0
    frame_count: int = 0
    storage_mode: str = "memory"
    group_id: str = ""
    group_name: str = ""

    @classmethod
    def from_file(
            cls,
            path: Path,
            *,
            target_sample_rate: int | None = None,
            preload_threshold_mb: float = 96.0,
    ) -> "AudioSource":
        path = Path(path)
        info = sf.info(str(path))
        if info.frames <= 0 or info.channels <= 0:
            raise ValueError("Audio source is empty.")
        expected_bytes = int(info.frames) * min(int(info.channels), 2) * 4
        group_id = path.parent.resolve().as_posix().casefold()
        group_name = path.parent.name or "Ungrouped"
        threshold_bytes = max(1, int(float(preload_threshold_mb) * 1024 * 1024))
        can_stream = (
                target_sample_rate is not None
                and int(target_sample_rate) == int(info.samplerate)
                and expected_bytes >= threshold_bytes
        )
        if can_stream:
            return cls(
                path=path,
                samples=None,
                sample_rate=int(info.samplerate),
                name=path.stem,
                frame_count=int(info.frames),
                storage_mode="stream",
                group_id=group_id,
                group_name=group_name,
            )

        data = cls._read_all(path)
        return cls(
            path=path,
            samples=data,
            sample_rate=int(info.samplerate),
            name=path.stem,
            frame_count=len(data),
            storage_mode="memory",
            group_id=group_id,
            group_name=group_name,
        )

    @staticmethod
    def _read_all(path: Path) -> np.ndarray:
        data, _ = sf.read(str(path), dtype="float32", always_2d=True)
        if data.size == 0:
            raise ValueError("Audio source is empty.")
        if not np.isfinite(data).all():
            raise ValueError("Audio contains non-finite samples.")
        return np.ascontiguousarray(data, dtype=np.float32)

    def load_into_memory(self) -> np.ndarray:
        if self.samples is None:
            data = self._read_all(self.path)
            self.samples = data
            self.frame_count = len(data)
            self.storage_mode = "memory"
        return self.samples

    @property
    def duration(self) -> float:
        frames = self.frame_count if self.frame_count else (len(self.samples) if self.samples is not None else 0)
        return frames / max(1, self.sample_rate)

    @property
    def channels(self) -> int:
        if self.samples is not None:
            return int(self.samples.shape[1])
        return 2
