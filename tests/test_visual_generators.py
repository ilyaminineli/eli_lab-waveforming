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


def test_stateful_generators_keep_independent_layer_instances():
    bank = GeneratorBank()
    packet = make_packet()
    settings = GeneratorSettings(complexity=40, motion=45, sensitivity=120)

    bank.render("CELLULAR SYSTEM", packet, 0.0, (240, 180), settings, state_key="layer-a")
    bank.render("CELLULAR SYSTEM", packet, 0.0, (240, 180), settings, state_key="layer-b")

    first = bank._instances[("layer-a", "CELLULAR SYSTEM")]
    second = bank._instances[("layer-b", "CELLULAR SYSTEM")]
    assert first is not second
    assert first._grid is not second._grid

    bank.release_state("layer-a")
    assert ("layer-a", "CELLULAR SYSTEM") not in bank._instances
    assert ("layer-b", "CELLULAR SYSTEM") in bank._instances


def test_cellular_system_keeps_evolving_after_repeated_steps():
    from engine.visual.generators import CellularSystem, VisualMetrics

    generator = CellularSystem()
    metrics = VisualMetrics(
        energy=0.62, transient=0.72, centroid=0.35,
        low=0.7, mid=0.5, high=0.35,
    )
    settings = GeneratorSettings(complexity=50, motion=45, sensitivity=125)
    for frame in range(16):
        generator.render(metrics, frame * 0.075, (240, 180), settings)

    assert generator._grid is not None
    assert float(generator._grid.sum()) > 20.0



def test_source_routing_creates_independent_feature_frames():
    from engine.visual.generators import VisualMetrics

    packet = make_packet()
    source_a = VisualMetrics.from_packet(packet, "a")
    source_b = VisualMetrics.from_packet(packet, "b")

    assert source_a.source_count == 1
    assert source_b.source_count == 1
    assert abs(source_a.centroid - source_b.centroid) > 0.005
    assert VisualMetrics.from_packet(packet, "not-present").source_count == 0


def test_geometric_and_axonometric_generators_render():
    bank = GeneratorBank()
    packet = make_packet()
    settings = GeneratorSettings(complexity=52, motion=30, sensitivity=105)
    expected = {
        "GEOMETRIC PLATE",
        "GEOMETRIC FIELD",
        "AXONOMETRIC FIELD",
        "POLYHEDRAL FIELD",
    }
    assert expected.issubset(set(bank.names()))
    for name in expected:
        image = bank.render(name, packet, 2.0, (360, 270), settings, state_key=name)
        alpha = np.asarray(image)[..., 3]
        assert image.mode == "RGBA"
        assert alpha.max() > 0
        assert np.count_nonzero(alpha) > 20



def test_reaction_diffusion_keeps_unactivated_paper_transparent():
    from engine.visual.generators import ReactionDiffusion, VisualMetrics

    generator = ReactionDiffusion()
    image = generator.render(
        VisualMetrics(), 0.0, (240, 180),
        GeneratorSettings(complexity=40, motion=30, sensitivity=100),
    )
    alpha = np.asarray(image)[..., 3]

    assert alpha.max() > 0
    # Seeded activator structures occupy a small fraction of the printable field.
    assert np.count_nonzero(alpha) < alpha.size * 0.35
