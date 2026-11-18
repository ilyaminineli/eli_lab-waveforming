from pathlib import Path
import threading

import numpy as np

from engine.audio.playback import PlaybackEngine
from engine.audio.source import AudioSource
from engine.visual.composition_director import is_default_placeholder_composition
from engine.visual.layers import VisualLayer
from engine.visual.preview_worker import is_newer_preview_frame


def test_preview_frame_acceptance_does_not_starve_when_worker_falls_behind():
    # A finished frame is useful even if newer requests are queued. The
    # one-item worker queue will deliver a later frame when it completes.
    assert is_newer_preview_frame(12, 8)
    assert is_newer_preview_frame(12, 11)
    assert not is_newer_preview_frame(11, 12)
    assert not is_newer_preview_frame(12, 12)


def test_untouched_starter_layer_is_detected_for_auto_composition():
    starter = VisualLayer(
        name="PHASE LATTICE 01",
        generator="PHASE LATTICE",
        pass_mode="PAPER RELIEF",
        pass_map="DISPLACEMENT",
        pass_strength=0.55,
    )
    assert is_default_placeholder_composition([starter])

    edited = VisualLayer(
        name="My phase lattice",
        generator="PHASE LATTICE",
        pass_mode="PAPER RELIEF",
        pass_map="DISPLACEMENT",
        pass_strength=0.55,
    )
    assert not is_default_placeholder_composition([edited])
    assert not is_default_placeholder_composition([starter, edited])


def test_imported_sources_can_be_analyzed_for_preview_before_playback(
    monkeypatch, tmp_path
):
    # Hold the analysis worker so the queued payload can be inspected without
    # introducing a dependency on a Qt event loop or audio output device.
    monkeypatch.setattr(
        PlaybackEngine, "_output_sample_rate", staticmethod(lambda: 48_000)
    )
    monkeypatch.setattr(
        PlaybackEngine, "_analysis_loop",
        lambda self: self._analysis_stop.wait(),
    )
    engine = PlaybackEngine()
    try:
        rate = 48_000
        time = np.arange(8192, dtype=np.float32) / rate
        tone = np.sin(2.0 * np.pi * 440.0 * time).astype(np.float32)
        samples = np.column_stack((tone, tone)).astype(np.float32)
        source = AudioSource(
            path=Path(tmp_path) / "preview-tone.wav",
            samples=samples,
            sample_rate=rate,
            name="preview-tone",
            frame_count=len(samples),
        )
        track_id = engine.add_source(source)

        assert engine.is_playing is False
        assert engine.request_preview_analysis() == 1

        snapshots, frame_position, revision, fft_size, band_count, window = (
            engine._analysis_queue.get_nowait()
        )
        assert set(snapshots) == {track_id}
        block, sample_rate = snapshots[track_id]
        assert block.shape == (fft_size, 2)
        assert sample_rate == rate
        assert np.max(np.abs(block)) > 0.5
        assert frame_position == fft_size
        assert revision >= 1
        assert band_count == 64
        assert window == "hann"
    finally:
        engine.close()


def test_preview_analysis_includes_streamed_source_preloaded_head(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        PlaybackEngine, "_output_sample_rate", staticmethod(lambda: 48_000)
    )
    monkeypatch.setattr(
        PlaybackEngine, "_analysis_loop",
        lambda self: self._analysis_stop.wait(),
    )
    engine = PlaybackEngine()
    try:
        rate = 48_000
        time = np.arange(24_000, dtype=np.float32) / rate
        tone = (0.4 * np.sin(2.0 * np.pi * 220.0 * time)).astype(np.float32)
        import soundfile as sf

        path = Path(tmp_path) / "stream-preview.wav"
        sf.write(path, np.column_stack((tone, tone)), rate, subtype="FLOAT")
        source = AudioSource.from_file(
            path, target_sample_rate=rate, preload_threshold_mb=0.0
        )
        track_id = engine.add_source(source)

        assert source.storage_mode == "stream"
        assert engine.request_preview_analysis() == 1

        snapshots, frame_position, *_ = engine._analysis_queue.get_nowait()
        block, sample_rate = snapshots[track_id]
        assert block.shape == (4096, 2)
        assert sample_rate == rate
        assert np.max(np.abs(block)) > 0.25
        assert frame_position == 4096
    finally:
        engine.close()
