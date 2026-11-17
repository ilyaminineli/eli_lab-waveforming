from engine.timeline import Timeline
from engine.visual.generators import GeneratorSettings


def test_timeline_records_markers_sections_and_round_trips():
    timeline = Timeline(bpm=128.0, beats_per_bar=4)
    timeline.set_duration(60.0)
    marker = timeline.add_marker(4.25, "INTRO")
    section = timeline.add_marker(16.0, kind="SECTION")

    restored = Timeline.from_dict(timeline.to_dict())

    assert restored.bpm == 128.0
    assert restored.duration == 60.0
    assert [(m.time, m.label, m.kind) for m in restored.markers] == [
        (4.25, "INTRO", "MARKER"),
        (16.0, "Section 01", "SECTION"),
    ]
    assert restored.remove_marker(marker.marker_id)
    assert restored.remove_marker(section.marker_id)


def test_automation_interpolates_and_preserves_unautomated_settings():
    timeline = Timeline()
    timeline.record("complexity", 0.0, 20.0)
    timeline.record("complexity", 10.0, 80.0)
    timeline.record("motion", 0.0, 15.0)
    base = GeneratorSettings(complexity=50, motion=40, sensitivity=120, seed=77)

    at_midpoint = timeline.settings_at(5.0, base)
    after_last = timeline.settings_at(12.0, base)

    assert at_midpoint.complexity == 50.0
    assert at_midpoint.motion == 15.0
    assert at_midpoint.sensitivity == 120.0
    assert at_midpoint.seed == 77
    assert after_last.complexity == 80.0


def test_automation_hold_interpolation_and_beat_snap():
    timeline = Timeline(bpm=120.0)
    timeline.record("motion", 0.0, 10.0)
    timeline.record("motion", 2.0, 90.0)
    timeline.lanes["motion"].interpolation = "HOLD"

    assert timeline.value_at("motion", 1.0, 0.0) == 10.0
    assert timeline.snap_to_beat(1.12) == 1.0



def test_automation_before_first_keyframe_uses_base_value():
    timeline = Timeline()
    timeline.record("motion", 3.0, 90.0)

    assert timeline.value_at("motion", 0.0, 42.0) == 42.0
    assert timeline.value_at("motion", 2.99, 42.0) == 42.0
    assert timeline.value_at("motion", 3.0, 42.0) == 90.0
