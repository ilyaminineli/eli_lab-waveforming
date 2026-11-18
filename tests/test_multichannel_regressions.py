from pathlib import Path
import time

import numpy as np
import pytest
import soundfile as sf
from PIL import Image

from engine.audio.playback import MAX_AUDIO_SOURCES, PlaybackEngine
from engine.audio.source import AudioSource
from engine.audio.storage import StreamedAudioBuffer
from engine.render.ffmpeg import resolve_ffmpeg
from engine.visual.assets import AssetCatalog
from engine.visual.composition_director import create_auto_composition, vary_composition
from engine.visual.compositor import VisualCompositor


GENERATOR_NAMES = [
    "GEOMETRIC PLATE", "AXONOMETRIC FIELD", "GEOMETRIC FIELD",
    "POLYHEDRAL FIELD", "PHASE ORBIT", "MOBIUS FIELD",
    "SPECTRAL TOPOGRAPHY", "PHYLLOTAXIS",
]


def test_auto_composition_separates_seven_audio_channels():
    source_ids = [f"track-{index}" for index in range(7)]
    layers = create_auto_composition(GENERATOR_NAMES, source_ids, seed=17)
    channels = layers[1:]

    assert [layer.source_id for layer in channels] == source_ids
    assert len({(layer.x_offset, layer.y_offset) for layer in channels}) == 7
    assert channels[-1].x_offset == pytest.approx(0.0)
    assert all(abs(layer.x_offset) <= 0.24 for layer in channels)
    assert all(abs(layer.y_offset) <= 0.25 for layer in channels)
    assert all(layer.scale == pytest.approx(0.30) for layer in channels)
    assert all(layer.pass_mode == "NONE" for layer in channels)


def test_variation_preserves_channel_positions_and_source_routes():
    source_ids = [f"track-{index}" for index in range(7)]
    layers = create_auto_composition(GENERATOR_NAMES, source_ids, seed=23)
    before = {
        layer.source_id: (layer.x_offset, layer.y_offset, layer.scale)
        for layer in layers if layer.source_id
    }

    varied = vary_composition(layers, GENERATOR_NAMES, seed=1234)
    after = {
        layer.source_id: (layer.x_offset, layer.y_offset, layer.scale)
        for layer in varied if layer.source_id
    }

    assert after == before


def test_director_effects_are_deterministic_and_non_destructive_without_fx():
    height, width = 48, 72
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[..., 3] = 170
    pixels[:, ::4, :3] = (240, 240, 240)
    source = Image.fromarray(pixels, "RGBA")

    assert VisualCompositor._apply_director_effects(
        source, {}, 1.0, "test-layer"
    ) is source

    packet = {"director_output": {"glitch_amount": 0.9, "accent_amount": 0.7}}
    first = VisualCompositor._apply_director_effects(source, packet, 1.25, "test-layer")
    second = VisualCompositor._apply_director_effects(source, packet, 1.25, "test-layer")
    assert np.array_equal(np.asarray(first), np.asarray(second))
    assert not np.array_equal(np.asarray(first), np.asarray(source))


def test_asset_catalog_prefers_resources_screens_and_supports_legacy_layout(tmp_path):
    current = tmp_path / "resources" / "screens"
    current.mkdir(parents=True)
    (tmp_path / "screens").mkdir()
    assert AssetCatalog.locate_project_assets(tmp_path) == current

    legacy_root = tmp_path / "legacy"
    legacy = legacy_root / "screens"
    legacy.mkdir(parents=True)
    assert AssetCatalog.locate_project_assets(legacy_root) == legacy


def test_ffmpeg_resolver_accepts_explicit_windows_executable(monkeypatch, tmp_path):
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"test binary")
    monkeypatch.setenv("FFMPEG_BINARY", str(executable))
    monkeypatch.delenv("IMAGEIO_FFMPEG_EXE", raising=False)

    assert resolve_ffmpeg() == str(executable.resolve())


def test_stream_analysis_read_does_not_rewind_prefetch_target(tmp_path):
    sample_rate = 48_000
    path = tmp_path / "stream.wav"
    sf.write(path, np.zeros((24_000, 2), dtype=np.float32), sample_rate, subtype="FLOAT")
    stream = StreamedAudioBuffer(
        path, 24_000, sample_rate, chunk_frames=1024, ring_chunks=4
    )
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with stream._condition:
                ready = stream._write_pos >= 2048
            if ready:
                break
            time.sleep(0.01)
        destination = np.zeros((256, 2), dtype=np.float32)
        assert stream.read_into(0, destination) == 256
        with stream._condition:
            requested_before = stream._requested_pos
        assert stream.read_into(0, destination, update_request=False) == 256
        with stream._condition:
            assert stream._requested_pos == requested_before
    finally:
        stream.close()


def test_playback_engine_accepts_the_advertised_64_source_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        PlaybackEngine, "_output_sample_rate", staticmethod(lambda: 48_000)
    )
    engine = PlaybackEngine()
    try:
        for index in range(MAX_AUDIO_SOURCES):
            samples = np.zeros((128, 2), dtype=np.float32)
            source = AudioSource(
                path=Path(tmp_path) / f"{index}.wav",
                samples=samples,
                sample_rate=48_000,
                name=f"source-{index}",
                frame_count=len(samples),
            )
            engine.add_source(source)
        assert engine.source_count == 64
        assert MAX_AUDIO_SOURCES == 64

        overflow = AudioSource(
            path=Path(tmp_path) / "overflow.wav",
            samples=np.zeros((128, 2), dtype=np.float32),
            sample_rate=48_000,
            name="overflow",
            frame_count=128,
        )
        with pytest.raises(ValueError, match="64 audio sources"):
            engine.add_source(overflow)
    finally:
        engine.close()


def test_audio_sources_from_different_folders_have_distinct_group_ids(tmp_path):
    first_dir = tmp_path / "kit-a" / "drums"
    second_dir = tmp_path / "kit-b" / "drums"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    first_path = first_dir / "kick.wav"
    second_path = second_dir / "snare.wav"
    audio = np.zeros((512, 2), dtype=np.float32)
    sf.write(first_path, audio, 48_000)
    sf.write(second_path, audio, 48_000)

    first = AudioSource.from_file(first_path, target_sample_rate=48_000)
    second = AudioSource.from_file(second_path, target_sample_rate=48_000)

    assert first.group_name == second.group_name == "drums"
    assert first.group_id != second.group_id
