from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.signal import get_window

@dataclass
class FeatureFrame:
    rms: float
    peak: float
    centroid: float
    flatness: float
    flux: float
    zcr: float
    stereo_width: float
    bands: np.ndarray
    spectrum: np.ndarray

class AudioAnalyzer:
    """Feature extraction only: no rendering, playback or UI dependencies."""
    def __init__(self, fft_size: int = 4096, band_count: int = 64, window: str = "hann"):
        self.fft_size = int(fft_size); self.band_count = int(band_count); self.window_name = window
        self._previous = None
        self._configure_window()

    def _configure_window(self):
        self._window = get_window(self.window_name, self.fft_size, fftbins=True).astype(np.float32)
        self._edges = np.geomspace(1, self.fft_size // 2 + 1, self.band_count + 1).astype(int)

    def configure(self, fft_size=None, band_count=None, window=None):
        if fft_size is not None: self.fft_size = int(fft_size)
        if band_count is not None: self.band_count = int(band_count)
        if window is not None: self.window_name = str(window).lower()
        self._previous = None
        self._configure_window()

    def analyze(self, block: np.ndarray, sample_rate: int) -> FeatureFrame:
        x = np.asarray(block, dtype=np.float32)
        if x.ndim == 2:
            left = x[:, 0]; right = x[:, 1] if x.shape[1] > 1 else left
            mono = (left + right) * 0.5
            width = float(np.sqrt(np.mean((left-right)**2)) / (np.sqrt(np.mean(mono**2))+1e-9))
        else:
            mono = x.reshape(-1); width = 0.0
        if len(mono) < self.fft_size: mono = np.pad(mono, (0, self.fft_size-len(mono)))
        else: mono = mono[-self.fft_size:]
        rms = float(np.sqrt(np.mean(mono*mono)+1e-12))
        peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
        zcr = float(np.mean(np.diff(np.signbit(mono).astype(np.int8)) != 0)) if len(mono)>1 else 0.0
        spectrum = np.abs(np.fft.rfft(mono*self._window)).astype(np.float32)
        power = spectrum*spectrum
        freq = np.fft.rfftfreq(self.fft_size, 1.0/max(1, int(sample_rate)))
        total = float(np.sum(power)+1e-12)
        centroid = float(np.sum(freq*power)/total)
        flatness = float(np.exp(np.mean(np.log(power+1e-12))) / (np.mean(power)+1e-12))
        norm = spectrum / (np.max(spectrum)+1e-9)
        flux = 0.0 if self._previous is None else float(np.mean(np.maximum(norm-self._previous, 0.0)))
        self._previous = norm
        bands = np.zeros(self.band_count, dtype=np.float32)
        for i, (a,b) in enumerate(zip(self._edges[:-1], self._edges[1:])):
            bands[i] = np.sqrt(np.mean(power[a:max(a+1,b)])) if b>a else 0.0
        bands /= float(np.max(bands)+1e-9)
        return FeatureFrame(rms, peak, centroid, flatness, flux, zcr, width, bands, norm)
