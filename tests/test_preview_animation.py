import numpy as np
from PIL import Image

from engine.visual.assets import AssetCatalog
from engine.visual.compositor import VisualCompositor
from engine.visual.generators import (
    CellularSystem,
    GeneratorBank,
    GeneratorSettings,
    ReactionDiffusion,
    VisualMetrics,
)
from engine.visual.layers import VisualLayer
from engine.visual.preview_worker import is_newer_preview_frame


def _generator_packet():
    bands = np.linspace(0.05, 1.0, 64, dtype=np.float32)
    frame = type("Frame", (), {
        "bands": bands,
        "rms": 0.31,
        "peak": 0.42,
        "centroid": 1200.0,
        "centroid_norm": 0.12,
        "rolloff": 5200.0,
        "bandwidth": 800.0,
        "flatness": 0.14,
        "entropy": 0.62,
        "flux": 0.025,
        "zcr": 0.07,
        "stereo_width": 0.1,
        "crest": 1.35,
        "spectrum": bands,
    })()
    return {
        "source_ids": ["track-a"],
        "frames": {"track-a": frame},
        "correlation": np.ones((1, 1), dtype=np.float32),
    }


def test_stateful_simulations_keep_advancing_with_visual_clock():
    packet = _generator_packet()
    settings = GeneratorSettings(complexity=45, motion=60, sensitivity=125)
    bank = GeneratorBank()
    for name in ("CELLULAR SYSTEM", "REACTION DIFFUSION"):
        before = bank.render(
            name, packet, 10.0, (320, 240), settings, state_key=name
        )
        after = bank.render(
            name, packet, 10.2, (320, 240), settings, state_key=name
        )
        assert before.size == after.size
        assert not np.array_equal(np.asarray(before), np.asarray(after))


def test_feedback_reset_can_preserve_generator_simulations():
    compositor = VisualCompositor(
        AssetCatalog.locate_project_assets(__import__("pathlib").Path(".")),
        render_size=(320, 240),
    )
    layer = VisualLayer(
        "Cellular", "CELLULAR SYSTEM",
        pass_mode="NONE", pass_strength=0.0, mask_mode="FULL",
    )
    packet = _generator_packet()
    settings = GeneratorSettings()
    compositor.generators.render(
        layer.generator, packet, 1.0, (160, 120), settings,
        state_key=layer.layer_id,
    )
    instance = compositor.generators._instances[(layer.layer_id, layer.generator)]
    compositor.reset_feedback(preserve_generators=True)
    assert compositor.generators._instances[(layer.layer_id, layer.generator)] is instance


def test_generator_bank_releases_hidden_or_removed_layer_state():
    bank = GeneratorBank()
    settings = GeneratorSettings()
    bank.render("CELLULAR SYSTEM", None, 0.0, (160, 120), settings, state_key="keep")
    bank.render("REACTION DIFFUSION", None, 0.0, (160, 120), settings, state_key="drop")
    bank.retain_layers({"keep": "CELLULAR SYSTEM"})
    assert ("keep", "CELLULAR SYSTEM") in bank._instances
    assert ("drop", "REACTION DIFFUSION") not in bank._instances


def test_preview_frame_delivery_accepts_latest_completed_monotonic_sequence():
    assert is_newer_preview_frame(4, 2)
    assert not is_newer_preview_frame(2, 4)
    assert not is_newer_preview_frame(4, 4)


def test_generator_layers_remain_independent_in_small_preview_resolution():
    packet = _generator_packet()
    bank = GeneratorBank()
    settings = GeneratorSettings(complexity=40, motion=55, sensitivity=115)
    a = bank.render(
        "GEOMETRIC FIELD", packet, 3.0, (320, 240), settings,
        state_key="layer-a", source_id="track-a",
    )
    b = bank.render(
        "AXONOMETRIC FIELD", packet, 3.0, (320, 240), settings,
        state_key="layer-b", source_id="track-a",
    )
    assert a.size == b.size == (320, 240)
    assert np.count_nonzero(np.asarray(a)[..., 3]) > 100
    assert np.count_nonzero(np.asarray(b)[..., 3]) > 100
    assert not np.array_equal(np.asarray(a), np.asarray(b))
