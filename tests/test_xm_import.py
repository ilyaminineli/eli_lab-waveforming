from pathlib import Path

import pytest

from engine.tracker.xm import XMParseError, load_xm


def test_loads_fixture_and_extracts_order_cues(tmp_path):
    path = Path(__file__).parent / "fixtures" / "total fvckery.xm"
    if not path.exists():
        pytest.skip("Binary XM fixture is not committed to the repository.")
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


def test_repeated_order_entries_have_consecutive_cue_times(tmp_path):
    path = Path(__file__).parent / "fixtures" / "total fvckery.xm"
    if not path.exists():
        pytest.skip("Binary XM fixture is not committed to the repository.")
    module = load_xm(path)

    assert module.cues[0].pattern == module.cues[1].pattern
    assert module.cues[0].end_seconds == pytest.approx(module.cues[1].start_seconds)
    assert module.cues[0].start_seconds == 0.0


def test_parser_rejects_invalid_xm(tmp_path):
    path = tmp_path / "broken.xm"
    path.write_bytes(b"not an XM")
    with pytest.raises(XMParseError):
        load_xm(path)


def test_parser_rejects_truncated_pattern_payload(tmp_path):
    # Valid minimal XM song header followed by a pattern with a missing event.
    import struct

    header = bytearray(336)
    header[:17] = b"Extended Module: "
    header[37] = 0x1A
    struct.pack_into("<H", header, 58, 0x0104)
    struct.pack_into("<I", header, 60, 276)
    struct.pack_into("<8H", header, 64, 1, 0, 1, 1, 0, 1, 6, 125)
    pattern = struct.pack("<IBHH", 9, 0, 1, 0)
    path = tmp_path / "truncated.xm"
    path.write_bytes(bytes(header) + pattern)
    with pytest.raises(XMParseError):
        load_xm(path)
