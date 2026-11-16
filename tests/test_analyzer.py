import numpy as np
from engine.audio.analyzer import AudioAnalyzer

def test_silence_is_finite():
    frame = AudioAnalyzer(1024,24).analyze(np.zeros((1024,2),np.float32),48000)
    assert np.isfinite(frame.rms) and np.isfinite(frame.centroid)
    assert frame.bands.shape == (24,)

def test_tone_has_expected_centroid():
    sr=48000; t=np.arange(4096,dtype=np.float32)/sr
    tone=np.sin(2*np.pi*1000*t).astype(np.float32)
    frame=AudioAnalyzer(4096,64).analyze(tone,sr)
    assert 850 < frame.centroid < 1150
