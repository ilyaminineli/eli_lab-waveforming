from pathlib import Path

import numpy as np
import soundfile as sf

from engine.render.offline import OfflineRenderWorker


def make_worker(samples, tmp_path, *, gain=1.0, pan=0.0):
    return OfflineRenderWorker(
        output_path=tmp_path / "unused.mp4",
        assets_root=tmp_path,
        sources=[{
            "track_id": "tone-a",
            "samples": samples,
            "gain": gain,
            "pan": pan,
            "muted": False,
            "solo": False,
            "analysis_enabled": True,
        }],
        layers=[],
        settings={"complexity": 30, "motion": 40, "sensitivity": 100, "seed": 23},
        timeline={},
        screen="No guide",
        sample_rate=48000,
        fft_size=1024,
        band_count=24,
        fps=24,
        resolution=(64, 48),
    )


def test_offline_feature_packet_is_reproducible_for_a_fixed_frame(tmp_path):
    t = np.arange(4096, dtype=np.float32) / 48000.0
    tone = np.column_stack((
        0.3 * np.sin(2 * np.pi * 440 * t),
        0.3 * np.sin(2 * np.pi * 440 * t),
    )).astype(np.float32)
    first = make_worker(tone, tmp_path)._analysis_packet(0.04, {})
    second = make_worker(tone, tmp_path)._analysis_packet(0.04, {})

    assert first["source_ids"] == ["tone-a"]
    assert np.array_equal(first["frames"]["tone-a"].bands, second["frames"]["tone-a"].bands)
    assert first["frames"]["tone-a"].centroid == second["frames"]["tone-a"].centroid


def test_offline_audio_mix_respects_gain_and_pan(tmp_path):
    samples = np.full((4800, 2), 0.5, dtype=np.float32)
    worker = make_worker(samples, tmp_path, gain=0.5, pan=0.0)
    output_path = tmp_path / "mix.wav"

    worker._write_audio_mix(output_path, 0.1)
    mixed, sample_rate = sf.read(output_path, dtype="float32", always_2d=True)

    assert sample_rate == 48000
    assert mixed.shape == (4800, 2)
    assert np.allclose(mixed.mean(axis=0), [0.25, 0.25], atol=0.002)



def test_offline_analysis_window_ends_at_frame_timestamp(tmp_path):
    samples = np.column_stack((
        np.arange(12, dtype=np.float32),
        np.arange(12, dtype=np.float32) + 100,
    ))
    block = OfflineRenderWorker._window_ending_at(samples, end_frame=8, fft_size=4)

    assert np.array_equal(block[:, 0], [4, 5, 6, 7])
    assert np.array_equal(block[:, 1], [104, 105, 106, 107])


def test_offline_analysis_window_zero_pads_before_audio_start(tmp_path):
    samples = np.ones((12, 2), dtype=np.float32)
    block = OfflineRenderWorker._window_ending_at(samples, end_frame=2, fft_size=4)

    assert np.array_equal(block[:, 0], [0, 0, 1, 1])
