from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from engine.visual.assets import AssetCatalog
from engine.visual.compositor import VisualCompositor
from engine.visual.layers import LayerStack, VisualLayer


def test_blending_keeps_transparent_regions_transparent():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")))
    destination = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    source = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((8, 6, 23, 17), fill=(230, 230, 230, 200))

    result = compositor._blend_into(destination, source, "Screen")

    assert result.getpixel((0, 0))[3] == 0
    assert result.getpixel((12, 12))[3] > 0


def test_frame_box_is_normalized_and_inset():
    assets = AssetCatalog(Path("missing-assets"))
    screen1 = assets.frame_box("SCREEN 1 / BLACK")
    screen2 = assets.frame_box("SCREEN 2 / BLACK")

    for x0, y0, x1, y1 in (screen1, screen2):
        assert 0.0 < x0 < x1 < 1.0
        assert 0.0 < y0 < y1 < 1.0
    assert (screen2[2] - screen2[0]) < (screen1[2] - screen1[0])


def test_layer_stack_duplicate_and_reorder():
    stack = LayerStack()
    first = stack.add("PHASE LATTICE")
    second = stack.add("CELLULAR SYSTEM")
    duplicate = stack.duplicate(first.layer_id)

    assert duplicate is not None
    assert duplicate.layer_id != first.layer_id
    assert len(stack.layers) == 3

    stack.move(second.layer_id, -1)
    assert stack.layers[1].layer_id == second.layer_id


def test_frame_mask_constrains_layer_to_printable_area():
    assets = AssetCatalog(Path("missing-assets"))
    compositor = VisualCompositor(assets)
    layer = VisualLayer(
        name="Orbit",
        generator="PHASE ORBIT",
        mask_mode="FRAME",
        pass_map="None",
        pass_mode="NONE",
    )

    output = compositor.render(
        packet=None,
        seconds=1.0,
        layers=[layer],
        screen="SCREEN 2 / BLACK",
    )
    frame = np.asarray(output.convert("RGB"))

    assert tuple(frame[4, 4]) == (10, 10, 10)
    assert output.size == (960, 720)


def test_paper_relief_pass_produces_a_valid_rgba_layer(tmp_path):
    root = tmp_path / "screens"
    pass_dir = root / "screen_pass"
    pass_dir.mkdir(parents=True)
    yy, xx = np.indices((160, 220))
    height = ((np.sin(xx * 0.12) * np.cos(yy * 0.09) + 1.0) * 127.5).astype(np.uint8)
    normal = np.zeros((160, 220, 3), dtype=np.uint8)
    normal[..., 0] = 128
    normal[..., 1] = 128
    normal[..., 2] = 245
    texture = np.clip(235 + height.astype(np.int16) // 12, 0, 255).astype(np.uint8)
    Image.fromarray(height, "L").save(pass_dir / "screen_displacement.png")
    Image.fromarray(normal, "RGB").save(pass_dir / "screen_normal.png")
    Image.fromarray(texture, "L").save(pass_dir / "screen_texture.png")

    compositor = VisualCompositor(AssetCatalog(root))
    image = Image.new("RGBA", (96, 72), (230, 230, 230, 220))
    result = compositor._apply_paper_relief(image, 0.7, "DISPLACEMENT")

    assert result.size == image.size
    assert result.mode == "RGBA"
    assert np.asarray(result)[..., :3].std() > 0
