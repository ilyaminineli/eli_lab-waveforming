from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window


@dataclass(slots=True)
class FeatureFrame:
    rms: float
    peak: float
    centroid: float
    centroid_norm: float
    rolloff: float
    bandwidth: float
    flatness: float
    entropy: float
    flux: float
    zcr: float
    stereo_width: float
    crest: float
    bands: np.ndarray
    spectrum: np.ndarray


class AudioAnalyzer:
    """Windowed spectral and temporal descriptors for one audio source."""

    def __init__(self, fft_size: int = 4096, band_count: int = 64, window: str = "hann"):
        self.fft_size = int(fft_size)
        self.band_count = int(band_count)
        self.window_name = window.lower()
        self._previous: np.ndarray | None = None
        self._configure_window()

    def _configure_window(self) -> None:
        self._window = get_window(self.window_name, self.fft_size, fftbins=True).astype(np.float32)
        edges = np.geomspace(1, self.fft_size // 2 + 1, self.band_count + 1)
        self._edges = np.clip(edges.astype(np.int32), 0, self.fft_size // 2 + 1)

    def configure(self, fft_size: int | None = None, band_count: int | None = None,
                  window: str | None = None) -> None:
        if fft_size is not None:
            self.fft_size = int(fft_size)
        if band_count is not None:
            self.band_count = int(band_count)
        if window is not None:
            self.window_name = str(window).lower()
        self._previous = None
        self._configure_window()

    def analyze(self, block: np.ndarray, sample_rate: int) -> FeatureFrame:
        x = np.asarray(block, dtype=np.float32)
        if x.ndim == 2:
            left = x[:, 0]
            right = x[:, 1] if x.shape[1] > 1 else left
            mono = (left + right) * 0.5
            mid_energy = float(np.mean(mono * mono))
            side = (left - right) * 0.5
            width = float(np.sqrt(np.mean(side * side)) / (np.sqrt(mid_energy) + 1e-9))
        else:
            mono = x.reshape(-1)
            width = 0.0

        if len(mono) < self.fft_size:
            mono = np.pad(mono, (self.fft_size - len(mono), 0))
        else:
            mono = mono[-self.fft_size:]

        rms = float(np.sqrt(np.mean(mono * mono) + 1e-12))
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        zcr = float(np.mean(np.not_equal(np.signbit(mono[1:]), np.signbit(mono[:-1])))) if mono.size > 1 else 0.0
        crest = float(peak / (rms + 1e-9))

        spectrum = np.abs(np.fft.rfft(mono * self._window)).astype(np.float32)
        power = spectrum * spectrum
        frequencies = np.fft.rfftfreq(self.fft_size, 1.0 / max(1, int(sample_rate)))
        total = float(np.sum(power) + 1e-12)
        centroid = float(np.sum(frequencies * power) / total)
        centroid_norm = float(np.clip(centroid / (sample_rate * 0.5), 0.0, 1.0))
        bandwidth = float(np.sqrt(np.sum(((frequencies - centroid) ** 2) * power) / total))
        cumulative = np.cumsum(power)
        rolloff_index = int(np.searchsorted(cumulative, total * 0.85))
        rolloff = float(frequencies[min(rolloff_index, len(frequencies) - 1)])
        positive = power / total
        entropy = float(-np.sum(positive * np.log(positive + 1e-12)) / np.log(max(2, len(positive))))
        flatness = float(np.exp(np.mean(np.log(power + 1e-12))) / (np.mean(power) + 1e-12))

        normalized = spectrum / (float(np.max(spectrum)) + 1e-9)
        flux = 0.0 if self._previous is None else float(
            np.mean(np.maximum(normalized - self._previous, 0.0))
        )
        self._previous = normalized

        bands = np.zeros(self.band_count, dtype=np.float32)
        for index, (start, stop) in enumerate(zip(self._edges[:-1], self._edges[1:])):
            lo = min(int(start), len(power) - 1)
            hi = max(lo + 1, min(int(stop), len(power)))
            bands[index] = np.sqrt(np.mean(power[lo:hi]))
        bands /= float(np.max(bands) + 1e-9)

        return FeatureFrame(
            rms=rms, peak=peak, centroid=centroid, centroid_norm=centroid_norm,
            rolloff=rolloff, bandwidth=bandwidth, flatness=flatness, entropy=entropy,
            flux=flux, zcr=zcr, stereo_width=width, crest=crest,
            bands=bands, spectrum=normalized,
        )
