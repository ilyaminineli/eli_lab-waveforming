import numpy as np

from engine.audio.analyzer import AudioAnalyzer
from engine.audio.feature_bus import FeatureBus
from engine.project.session import ProjectSession, SessionTrack, scan_audio_tree
from engine.visual.composition_director import CompositionDirector


def make_packet():
    rate = 48000
    t = np.arange(4096, dtype=np.float32) / rate
    a = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    b = np.sin(2 * np.pi * 880 * t).astype(np.float32)
    analyzer = AudioAnalyzer(4096, 32)
    return {
        "position": 1.0,
        "source_ids": ["a", "b"],
        "frames": {
            "a": analyzer.analyze(a, rate),
            "b": analyzer.analyze(b, rate),
        },
        "correlation": np.eye(2, dtype=np.float32),
    }


def test_feature_bus_builds_group_and_master_features():
    packet = make_packet()
    enriched = FeatureBus().update(packet, {"a": "edn11", "b": "edn11"})
    assert enriched["master_features"]["track_count"] == 2
    assert enriched["group_features"]["edn11"]["track_count"] == 2
    assert enriched["group_frames"]["edn11"].bands.shape == (32,)
    assert "novelty" in enriched["track_features"]["a"]


def test_feature_bus_emits_transient_events_for_spikes():
    bus = FeatureBus()
    packet = make_packet()
    frame = packet["frames"]["a"]
    # A strong flux value should be exposed as an event.
    from dataclasses import replace
    packet["frames"]["a"] = replace(frame, flux=0.08)
    enriched = bus.update(packet, {"a": "edn11", "b": "edn11"})
    assert any(event["kind"] == "transient" for event in enriched["events"])


def test_director_modes_and_auto_variation_request():
    director = CompositionDirector("AUTO", variation_cooldown=5.0)
    packet = {"position": 1.0, "master_features": {
        "energy": 0.5, "density": 0.8, "novelty": 0.9, "onset": 0.9,
    }}
    output = director.update(packet)
    assert output.mode == "AUTO"
    assert output.state in director.STATES
    # First qualifying state may be held by hysteresis; after it settles, auto can request a variation.
    packet["position"] = 1.3
    output = director.update(packet)
    packet["position"] = 20.0
    output = director.update(packet)
    assert output.request_variation is True


def test_session_roundtrip_and_canvas_invariants(tmp_path):
    session = ProjectSession(
        tracks=[SessionTrack("id", "stem.wav", "stem", "group", "Group")],
        director_mode="AUTO",
    )
    path = tmp_path / "session.waveforming.json"
    session.save(path)
    restored = ProjectSession.load(path)
    assert restored.canvas_size == (1920, 1440)
    assert restored.frame_size == (1322, 1058)
    assert restored.tracks[0].track_id == "id"
    assert restored.director_mode == "AUTO"


def test_scan_audio_tree_groups_by_subfolder(tmp_path):
    root = tmp_path / "edn11"
    (root / "drums").mkdir(parents=True)
    (root / "synths").mkdir()
    (root / "drums" / "kick.wav").write_bytes(b"")
    (root / "synths" / "pad.wav").write_bytes(b"")
    groups = scan_audio_tree(root)
    assert set(groups) == {"edn11/drums", "edn11/synths"}
    assert len(groups["edn11/drums"]) == 1

def test_long_matching_rate_source_selects_stream_storage(tmp_path):
    import soundfile as sf
    import time
    from engine.audio.source import AudioSource
    from engine.audio.storage import StreamedAudioBuffer

    rate = 48000
    samples = np.zeros((24000, 2), dtype=np.float32)
    samples[:, 0] = 0.25
    samples[:, 1] = -0.25
    path = tmp_path / "long_stem.wav"
    sf.write(path, samples, rate, subtype="FLOAT")

    source = AudioSource.from_file(
        path, target_sample_rate=rate, preload_threshold_mb=0.0
    )
    assert source.storage_mode == "stream"
    assert source.samples is None

    stream = StreamedAudioBuffer(path, source.frame_count, source.sample_rate)
    try:
        destination = np.zeros((256, 2), dtype=np.float32)
        deadline = time.monotonic() + 2.0
        copied = 0
        while time.monotonic() < deadline and copied == 0:
            copied = stream.read_into(0, destination)
            if copied == 0:
                time.sleep(0.01)
        assert copied == len(destination)
        assert np.allclose(destination[:, 0], 0.25, atol=1e-3)
        assert np.allclose(destination[:, 1], -0.25, atol=1e-3)
    finally:
        stream.close()


def test_stream_storage_falls_back_to_memory_when_resampling_is_needed(tmp_path):
    import soundfile as sf
    from engine.audio.source import AudioSource

    path = tmp_path / "different_rate.wav"
    sf.write(path, np.zeros((4096, 2), dtype=np.float32), 44100)
    source = AudioSource.from_file(
        path, target_sample_rate=48000, preload_threshold_mb=0.0
    )
    assert source.storage_mode == "memory"
    assert source.samples is not None



def test_director_uses_tracker_cues_for_scene_state_and_accents():
    director = CompositionDirector("SEMI-AUTO")
    packet = {
        "position": 1.0,
        "master_features": {},
        "tracker_cue": {
            "order": 10,
            "pattern": 7,
            "progress": 0.0,
            "density": 0.15,
            "row_activity": 0.4,
            "transition_strength": 0.8,
            "pattern_reprise": True,
        },
    }

    first = director.update(packet, 1.0)
    packet["position"] = 1.3
    settled = director.update(packet, 1.3)

    assert first.tracker_order == 10
    assert first.tracker_pattern == 7
    assert first.tracker_transition == 0.8
    assert first.tracker_activity == 0.4
    assert settled.tracker_reprise is True
    assert settled.state == "INSTABILITY"
    assert settled.energy > 0.0
    assert settled.motion_scale > 1.0
    assert settled.accent_amount > 0.0
    assert settled.request_variation is False


def test_auto_director_can_request_tracker_boundary_variation():
    director = CompositionDirector("AUTO", variation_cooldown=5.0)
    packet = {
        "position": 1.0,
        "master_features": {},
        "tracker_cue": {
            "order": 4,
            "pattern": 3,
            "progress": 0.0,
            "density": 0.18,
            "row_activity": 0.5,
            "transition_strength": 0.9,
            "pattern_reprise": False,
        },
    }

    director.update(packet, 1.0)
    packet["position"] = 1.3
    output = director.update(packet, 1.3)

    assert output.state == "EMERGENCE"
    assert output.request_variation is True
