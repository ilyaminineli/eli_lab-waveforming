import numpy as np
from engine.audio.analyzer import AudioAnalyzer


def test_silence_is_finite():
    frame = AudioAnalyzer(1024, 24).analyze(np.zeros((1024, 2), np.float32), 48000)
    assert np.isfinite(frame.rms)
    assert np.isfinite(frame.centroid)
    assert np.isfinite(frame.flatness)
    assert frame.bands.shape == (24,)


def test_tone_has_expected_centroid_and_low_zcr():
    sample_rate = 48000
    t = np.arange(4096, dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    frame = AudioAnalyzer(4096, 64).analyze(tone, sample_rate)
    assert 850 < frame.centroid < 1150
    assert 0.03 < frame.zcr < 0.06
    assert 0.0 <= frame.centroid_norm <= 1.0


def test_noise_has_higher_flatness_than_tone():
    rng = np.random.default_rng(4)
    noise = rng.normal(0, 0.1, 4096).astype(np.float32)
    tone_t = np.arange(4096, dtype=np.float32) / 48000
    tone = np.sin(2 * np.pi * 800 * tone_t).astype(np.float32)
    tone_frame = AudioAnalyzer(4096, 48).analyze(tone, 48000)
    noise_frame = AudioAnalyzer(4096, 48).analyze(noise, 48000)
    assert noise_frame.flatness > tone_frame.flatness
