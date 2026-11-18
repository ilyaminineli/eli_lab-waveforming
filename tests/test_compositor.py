from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from engine.visual.assets import AssetCatalog
from engine.visual.compositor import PREVIEW_SIZE, VisualCompositor
from engine.visual.generators import GeneratorSettings
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
    assert output.size == PREVIEW_SIZE


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



def test_white_paper_uses_dark_ink_palette():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")))
    source = Image.new("RGBA", (24, 16), (245, 245, 245, 255))
    layer = VisualLayer("Channel", "GEOMETRIC FIELD", palette_mode="MUTED PRIDE")

    black_paper = compositor._apply_palette(
        source, layer, {"source_ids": ["source-a"]}, white_plate=False
    )
    white_paper = compositor._apply_palette(
        source, layer, {"source_ids": ["source-a"]}, white_plate=True
    )

    assert np.asarray(white_paper)[..., :3].mean() < np.asarray(black_paper)[..., :3].mean()


def test_monochrome_scope_inverts_on_white_paper():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")))
    source = Image.new("RGBA", (12, 12), (245, 245, 245, 255))
    layer = VisualLayer("Mono", "PHASE ORBIT", palette_mode="MONOCHROME")

    result = compositor._apply_palette(source, layer, {}, white_plate=True)

    assert result.getpixel((4, 4))[:3] == (10, 10, 10)



def test_gpu_scene_keeps_layers_separate_for_gpu_blending():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")), render_size=(128, 96))
    layer = VisualLayer(
        name="GPU layer", generator="PHASE ORBIT",
        mask_mode="FULL", pass_mode="NONE",
    )
    scene = compositor.render_scene(
        packet=None, seconds=0.0, layers=[layer], screen="No guide"
    )
    assert scene["background"].size == (128, 96)
    assert len(scene["layers"]) == 1
    assert scene["layers"][0]["image"].mode == "RGBA"


def test_compositor_supports_an_independent_export_resolution():
    assets = AssetCatalog(Path("missing-assets"))
    compositor = VisualCompositor(assets, render_size=(128, 96))
    layer = VisualLayer(
        name="Plate", generator="GEOMETRIC PLATE",
        mask_mode="FULL", pass_mode="NONE",
    )

    image = compositor.render(
        packet=None, seconds=0.0, layers=[layer], screen="No guide"
    )

    assert image.size == (128, 96)



def test_transform_skips_identity_resampling_and_snaps_to_quarter_turns():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")))
    source = Image.new("RGBA", (20, 12), (0, 0, 0, 0))
    source.putpixel((2, 3), (240, 240, 240, 255))

    identity, origin = compositor._transform(source, (40, 30), 0, 0, 1.0, 0)
    assert identity is source
    assert origin == (30, 24)

    turned, _ = compositor._transform(source, (40, 30), 0, 0, 1.0, 87)
    assert turned.size == (12, 20)
    assert turned.getpixel((3, 20 - 1 - 2)) == source.getpixel((2, 3))


def test_editorial_palette_uses_blue_yellow_violet_ink_families():
    compositor = VisualCompositor(AssetCatalog(Path("missing-assets")))
    source = Image.new("RGBA", (8, 8), (230, 230, 230, 255))
    rgb = []
    for index in range(3):
        layer = VisualLayer(
            f"Channel {index + 1}", "GEOMETRIC FIELD",
            palette_mode="EDITORIAL TRICOLOR", palette_index=index,
        )
        rgb.append(compositor._apply_palette(source, layer, {}, False).getpixel((3, 3))[:3])

    blue, yellow, violet = rgb
    assert blue[2] > blue[0] + 35
    assert yellow[0] > yellow[2] + 55 and yellow[1] > yellow[2] + 45
    assert violet[0] > violet[1] + 20 and violet[2] > violet[1] + 35



def test_printable_mask_uses_offline_canvas_dimensions():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(1920, 1440)
    )
    screen = "SCREEN 1 / BLACK"
    frame_box = compositor._frame_box(screen)
    mask = compositor._mask("FRAME", screen, frame_box)

    assert mask.size == (1920, 1440)
    assert mask.getbbox() is not None


def test_gpu_native_interference_emits_shader_descriptor_without_cpu_image():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(128, 96)
    )
    layer = VisualLayer(
        name="Interference / GPU",
        generator="INTERFERENCE FIELD",
        mask_mode="FULL",
        pass_mode="NONE",
        pass_strength=0.0,
        palette_mode="EDITORIAL TRICOLOR",
        palette_index=2,
        blend_mode="Screen",
    )
    packet = {
        "source_ids": ["track-a"],
        "frames": {
            "track-a": type("Frame", (), {
                "bands": np.full(32, 0.25, dtype=np.float32),
                "rms": 0.2,
                "flux": 0.01,
                "centroid_norm": 0.45,
                "flatness": 0.3,
                "entropy": 0.5,
                "zcr": 0.1,
                "stereo_width": 0.2,
                "rolloff": 0.7,
                "crest": 2.0,
            })()
        },
    }
    scene = compositor.render_scene(
        packet, 1.25, [layer], GeneratorSettings(), "No guide", gpu_native=True
    )

    assert len(scene["layers"]) == 1
    descriptor = scene["layers"][0]["gpu_instrument"]
    assert descriptor["kind"] == "interference"
    assert descriptor["rect"] == (0, 0, 128, 96)
    assert descriptor["blend_mode"] == "Screen"
    assert descriptor["settings"]["density"] == pytest.approx(0.58)
    assert descriptor["seconds"] == pytest.approx(1.25)
    assert descriptor["palette_mode"] == "TRICOLOR"
    assert "image" not in scene["layers"][0]


def test_gpu_native_interference_falls_back_for_cpu_only_effects():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(128, 96)
    )
    cases = [
        VisualLayer(
            "Paper pass", "INTERFERENCE FIELD",
            mask_mode="FULL", pass_mode="PAPER RELIEF", pass_strength=0.5,
        ),
        VisualLayer(
            "Scaled", "INTERFERENCE FIELD",
            mask_mode="FULL", pass_mode="NONE", pass_strength=0.0, scale=0.8,
        ),
        VisualLayer(
            "Rotated", "INTERFERENCE FIELD",
            mask_mode="FULL", pass_mode="NONE", pass_strength=0.0, rotation=90,
        ),
        VisualLayer(
            "Unsupported palette", "INTERFERENCE FIELD",
            mask_mode="FULL", pass_mode="NONE", pass_strength=0.0,
            palette_mode="SOME CUSTOM MAP",
        ),
    ]

    for layer in cases:
        scene = compositor.render_scene(
            None, 0.0, [layer], GeneratorSettings(), "No guide", gpu_native=True
        )
        assert len(scene["layers"]) == 1
        assert "gpu_instrument" not in scene["layers"][0]
        assert scene["layers"][0]["image"].mode == "RGBA"


def test_gpu_native_interference_falls_back_when_director_effects_are_active():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(96, 72)
    )
    layer = VisualLayer(
        "Glitch fallback", "INTERFERENCE FIELD",
        mask_mode="FULL", pass_mode="NONE", pass_strength=0.0,
    )
    scene = compositor.render_scene(
        {"director_output": {"glitch_amount": 0.5}},
        0.5, [layer], GeneratorSettings(), "No guide", gpu_native=True,
    )

    assert "gpu_instrument" not in scene["layers"][0]
    assert scene["layers"][0]["image"].mode == "RGBA"


def test_gpu_shader_contains_procedural_interference_uniforms():
    from engine.visual.canvas import FRAGMENT_SHADER

    for uniform in (
        "uProcKind", "uProcA", "uProcB", "uProcC",
        "uProcEntropy", "uProcInk", "uProcMonochrome",
    ):
        assert uniform in FRAGMENT_SHADER
    assert "vec4 interferenceField(vec2 uv)" in FRAGMENT_SHADER
    assert "fieldA" in FRAGMENT_SHADER and "fieldB" in FRAGMENT_SHADER


def test_gpu_native_interference_scene_builds_with_frame_mask():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(128, 96)
    )
    layer = VisualLayer(
        "GPU interference", "INTERFERENCE FIELD",
        mask_mode="FRAME", pass_mode="NONE", pass_strength=0.0,
    )
    scene = compositor.render_scene(
        packet=None,
        seconds=2.5,
        layers=[layer],
        settings=GeneratorSettings(),
        screen="SCREEN 1 / BLACK",
        gpu_native=True,
    )

    assert len(scene["layers"]) == 1
    descriptor = scene["layers"][0]["gpu_instrument"]
    x, y, width, height = descriptor["rect"]
    assert descriptor["kind"] == "interference"
    assert (x, y, width, height) == (11, 9, 106, 70)
    assert descriptor["seconds"] == pytest.approx(2.5)


def test_cpu_scene_renders_gpu_native_interference_as_real_pixels():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(128, 96)
    )
    layer = VisualLayer(
        "CPU interference", "INTERFERENCE FIELD",
        mask_mode="FRAME", pass_mode="NONE", pass_strength=0.0,
        palette_mode="EDITORIAL TRICOLOR",
    )
    scene = compositor.render_scene(
        packet=None,
        seconds=1.25,
        layers=[layer],
        settings=GeneratorSettings(),
        screen="SCREEN 1 / BLACK",
        gpu_native=False,
    )

    assert isinstance(scene, Image.Image)
    assert scene.size == (128, 96)
    pixels = np.asarray(scene)
    assert np.count_nonzero(pixels[..., :3]) > 100
    assert pixels[..., :3].std() > 0


def test_gpu_interference_scene_keeps_cpu_fallback_layer_snapshot():
    compositor = VisualCompositor(
        AssetCatalog(Path("missing-assets")), render_size=(128, 96)
    )
    layer = VisualLayer(
        "GPU interference", "INTERFERENCE FIELD",
        mask_mode="FRAME", pass_mode="NONE", pass_strength=0.0,
    )
    cpu = compositor.render_scene(
        packet=None,
        seconds=1.25,
        layers=[layer],
        settings=GeneratorSettings(),
        screen="SCREEN 1 / BLACK",
        gpu_native=False,
    )
    gpu = compositor.render_scene(
        packet=None,
        seconds=1.25,
        layers=[layer],
        settings=GeneratorSettings(),
        screen="SCREEN 1 / BLACK",
        gpu_native=True,
        include_guide=False,
    )

    assert isinstance(cpu, Image.Image)
    assert "gpu_instrument" in gpu["layers"][0]
