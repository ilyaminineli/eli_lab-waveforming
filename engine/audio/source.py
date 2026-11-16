from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class AudioSource:
    path: Path
    samples: np.ndarray
    sample_rate: int
    name: str
    gain: float = 1.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False
    analysis_enabled: bool = True
    cursor: int = 0

    @classmethod
    def from_file(cls, path: Path) -> "AudioSource":
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if data.size == 0:
            raise ValueError("Audio file is empty.")
        if not np.isfinite(data).all():
            raise ValueError("Audio contains non-finite samples.")
        return cls(path, np.ascontiguousarray(data), int(sr), path.stem)

    @property
    def duration(self) -> float:
        return len(self.samples) / max(1, self.sample_rate)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])
