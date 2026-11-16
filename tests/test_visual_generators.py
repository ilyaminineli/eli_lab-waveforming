import numpy as np
from engine.audio.analyzer import AudioAnalyzer
from engine.visual.generators import GeneratorBank, GeneratorSettings


def make_packet():
    sample_rate = 48000
    t = np.arange(4096, dtype=np.float32) / sample_rate
    a = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    b = np.sin(2 * np.pi * 770 * t + 0.3).astype(np.float32)
    analyzer_a = AudioAnalyzer(4096, 48)
    analyzer_b = AudioAnalyzer(4096, 48)
    return {
        "frames": {"a": analyzer_a.analyze(np.column_stack([a, a]), sample_rate),
                   "b": analyzer_b.analyze(np.column_stack([b, b]), sample_rate)},
        "correlation": np.asarray([[1.0, 0.2], [0.2, 1.0]], dtype=np.float32),
        "source_ids": ["a", "b"],
    }


def test_all_generators_return_transparent_rgba_frames():
    bank = GeneratorBank()
    packet = make_packet()
    settings = GeneratorSettings(complexity=45, motion=35, sensitivity=110)
    for name in bank.names():
        image = bank.render(name, packet, 1.25, (480, 360), settings)
        assert image.size == (480, 360)
        assert image.mode == "RGBA"
        assert np.asarray(image)[..., 3].max() > 0
