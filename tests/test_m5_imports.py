def test_m5_application_modules_import_without_creating_a_window():
    from app.main_window import MainWindow
    from app.timeline_widget import TimelineWidget
    from engine.render.offline import OfflineRenderWorker
    from engine.visual.preview_worker import PreviewRenderWorker

    assert MainWindow is not None
    assert TimelineWidget is not None
    assert OfflineRenderWorker is not None
    assert PreviewRenderWorker is not None
