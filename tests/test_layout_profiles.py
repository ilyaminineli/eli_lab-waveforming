from engine.visual.assets import AssetCatalog, CANVAS_SIZE, DEFAULT_FRAME_SIZE, DEFAULT_FRAME_RECT


def test_layout_canvas_and_default_frame_dimensions():
    assert CANVAS_SIZE == (1920, 1440)
    assert DEFAULT_FRAME_SIZE == (1322, 1058)
    assert DEFAULT_FRAME_RECT == (299, 191, 1621, 1249)


def test_pre_designed_screens_are_discovered(tmp_path):
    from PIL import Image

    root = tmp_path / "screens"
    (root / "pre_designed").mkdir(parents=True)
    Image.new("RGB", (1920, 1440)).save(root / "pre_designed" / "Scr1.png")
    catalog = AssetCatalog(root)
    name = "PRE-DESIGNED / SCR1"
    assert name in catalog.screen_names()
    assert catalog.frame_rect_px(name) == DEFAULT_FRAME_RECT
