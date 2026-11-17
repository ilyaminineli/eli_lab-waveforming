from pathlib import Path

from engine.visual.assets import AssetCatalog
from engine.visual.generators import GeneratorSettings
from engine.visual.layers import VisualLayer
from engine.visual.preview_worker import PreviewRenderWorker


def test_preview_worker_switches_resolution_without_touching_ui_thread():
    worker = PreviewRenderWorker(AssetCatalog(Path("missing-assets")))
    worker.set_render_size((360, 270))

    assert worker.render_size == (360, 270)
    assert worker._render_size == (320, 240)


def test_preview_queue_keeps_only_the_latest_request():
    worker = PreviewRenderWorker(AssetCatalog(Path("missing-assets")))
    settings = GeneratorSettings()
    layer = VisualLayer("Layer", "PHASE ORBIT")

    for sequence in range(5):
        worker.submit(
            packet=None,
            seconds=float(sequence),
            layers=[layer],
            settings=settings,
            screen="No guide",
            feedback_enabled=False,
            feedback_amount=0.0,
            feedback_decay=0.9,
            feedback_shift=0.0,
            sequence=sequence,
        )

    request = worker._queue.get_nowait()
    assert request["sequence"] == 4
    assert request["seconds"] == 4.0
    assert worker._queue.empty()
