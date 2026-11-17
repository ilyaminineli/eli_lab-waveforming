import ast
from pathlib import Path


def test_main_window_source_parses_without_initializing_audio_hardware():
    repository_root = Path(__file__).resolve().parents[1]
    source = (repository_root / "app" / "main_window.py").read_text(encoding="utf-8")
    module = ast.parse(source, filename="app/main_window.py")

    assert any(
        isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        for node in module.body
    )


def test_m5_qt_and_render_modules_import():
    from app.timeline_widget import TimelineWidget
    from engine.render.offline import OfflineRenderWorker
    from engine.visual.preview_worker import PreviewRenderWorker

    assert TimelineWidget is not None
    assert OfflineRenderWorker is not None
    assert PreviewRenderWorker is not None
