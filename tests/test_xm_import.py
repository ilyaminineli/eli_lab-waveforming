from pathlib import Path

import pytest

from engine.tracker.xm import XMParseError, load_xm


def test_loads_fixture_and_extracts_order_cues():
    path = Path(__file__).parent / "fixtures" / "total fvckery.xm"
    if not path.exists():
        pytest.skip("Place the user-provided XM fixture here for integration coverage.")
    module = load_xm(path)

    assert module.tracker.startswith("MilkyTracker")
    assert module.channels == 14
    assert module.bpm == 173
    assert module.speed == 6
    assert len(module.orders) == 24
    assert module.orders[:6] == (0, 0, 1, 1, 2, 3)
    assert len(module.cues) == 24
    assert module.cues[0].note_count == 17
    assert module.cues[0].active_channels == (1,)
    assert module.cues[-1].is_silent
    assert module.duration == pytest.approx(133.17919075, abs=1e-5)


def test_repeated_order_entries_have_consecutive_cue_times():
    path = Path(__file__).parent / "fixtures" / "total fvckery.xm"
    if not path.exists():
        pytest.skip("Place the user-provided XM fixture here for integration coverage.")
    module = load_xm(path)

    assert module.cues[0].pattern == module.cues[1].pattern
    assert module.cues[0].end_seconds == pytest.approx(module.cues[1].start_seconds)
    assert module.cues[0].start_seconds == 0.0


def test_invalid_xm_is_rejected(tmp_path):
    path = tmp_path / "broken.xm"
    path.write_bytes(b"not an XM")

    with pytest.raises(XMParseError):
        load_xm(path)
