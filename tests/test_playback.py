from pathlib import Path

import numpy as np

from engine.audio.playback import PlaybackEngine
from engine.audio.source import AudioSource


def test_audio_callback_mixes_tracks_without_changing_gain_or_pan():
    engine = PlaybackEngine()
    try:
        sample_rate = engine.sample_rate
        left_source = AudioSource(
            Path("left.wav"),
            np.full((2048, 2), 0.2, dtype=np.float32),
            sample_rate,
            "Left",
            gain=0.5,
            pan=-1.0,
        )
        right_source = AudioSource(
            Path("right.wav"),
            np.full((2048, 2), 0.4, dtype=np.float32),
            sample_rate,
            "Right",
            gain=0.5,
            pan=1.0,
        )
        engine.add_source(left_source)
        engine.add_source(right_source)
        engine._playing = True

        output = np.zeros((256, 2), dtype=np.float32)
        engine._audio_callback(output, 256, None, None)

        assert np.allclose(output[:, 0], 0.1, atol=1e-6)
        assert np.allclose(output[:, 1], 0.2, atol=1e-6)
        assert engine.position == 256 / sample_rate
    finally:
        engine.close()


def test_audio_callback_obeys_solo_and_mute_without_audio_hardware():
    engine = PlaybackEngine()
    try:
        sample_rate = engine.sample_rate
        muted = AudioSource(
            Path("muted.wav"),
            np.full((1024, 2), 0.7, dtype=np.float32),
            sample_rate,
            "Muted",
            muted=True,
        )
        solo = AudioSource(
            Path("solo.wav"),
            np.full((1024, 2), 0.25, dtype=np.float32),
            sample_rate,
            "Solo",
            solo=True,
        )
        other = AudioSource(
            Path("other.wav"),
            np.full((1024, 2), 0.5, dtype=np.float32),
            sample_rate,
            "Other",
        )
        engine.add_source(muted)
        engine.add_source(solo)
        engine.add_source(other)
        engine._playing = True

        output = np.zeros((128, 2), dtype=np.float32)
        engine._audio_callback(output, 128, None, None)

        assert np.allclose(output, 0.25, atol=1e-6)
    finally:
        engine.close()
