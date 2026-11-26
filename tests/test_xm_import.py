from pathlib import Path
import struct

import pytest

from engine.tracker.xm import XMParseError, load_xm, tracker_packet_at


def make_xm(path: Path, *, tempo_effect: tuple[int, int] | None = None) -> Path:
    header = bytearray(336)
    header[:17] = b"Extended Module: "
    header[17:37] = b"Tracker fixture".ljust(20, b"\0")
    header[37] = 0x1A
    header[38:58] = b"MilkyTracker 1.05.01".ljust(20, b"\0")
    struct.pack_into("<H", header, 58, 0x0104)
    struct.pack_into("<I", header, 60, 276)
    struct.pack_into("<8H", header, 64, 2, 0, 2, 2, 2, 1, 6, 125)
    header[80:82] = bytes((0, 1))

    events = []
    for row in range(64):
        for channel in range(2):
            if row == 0 and channel == 0:
                events.append(bytes((49, 1, 0, 0, 0)))
            elif row == 8 and channel == 1:
                events.append(bytes((61, 2, 0, 0, 0)))
            elif tempo_effect == (row, channel):
                events.append(bytes((0, 0, 0, 0x0F, 3)))
            else:
                events.append(b"\x80")
    payload = b"".join(events)
    pattern0 = struct.pack("<IBHH", 9, 0, 64, len(payload)) + payload
    pattern1 = struct.pack("<IBHH", 9, 0, 64, 0)
    path.write_bytes(bytes(header) + pattern0 + pattern1)
    return path


def test_parser_reads_order_cues_and_empty_pattern(tmp_path):
    module = load_xm(make_xm(tmp_path / "fixture.xm"))

    assert module.channels == 2
    assert module.instrument_count == 2
    assert module.bpm == 125
    assert module.speed == 6
    assert module.orders == (0, 1)
    assert module.cues[0].note_count == 2
    assert module.cues[0].active_channels == (1, 2)
    assert module.cues[0].instrument_ids == (1, 2)
    assert module.cues[0].row_note_counts[0] == 1
    assert module.cues[0].row_note_counts[8] == 1
    assert module.cues[1].is_silent
    assert module.duration == pytest.approx(15.36)


def test_tracker_visual_packet_contains_note_grid_and_progress(tmp_path):
    module = load_xm(make_xm(tmp_path / "fixture.xm"))
    packet = module.visual_packet(3.84)

    assert packet is not None
    assert packet["order"] == 0
    assert packet["pattern"] == 0
    assert packet["progress"] == pytest.approx(0.5)
    assert packet["notes"][0] == [49, 0]
    assert packet["notes"][8] == [0, 61]
    assert packet["instruments"][0] == [1, 0]
    assert packet["instruments"][8] == [0, 2]


def test_serialised_tracker_packet_matches_live_packet(tmp_path):
    module = load_xm(make_xm(tmp_path / "fixture.xm"))
    live = module.visual_packet(9.0)
    offline = tracker_packet_at(module.visual_data(), 9.0)

    assert live == offline
    assert offline["order"] == 1
    assert offline["is_silent"] is True


def test_tempo_effect_updates_subsequent_row_timing(tmp_path):
    module = load_xm(make_xm(tmp_path / "tempo.xm", tempo_effect=(1, 0)))

    # F03 changes speed to three ticks per row from the first row onward.
    assert module.effect_count == 1
    expected = (6 * 2.5 / 125) + (63 * 3 * 2.5 / 125)
    assert module.cues[0].end_seconds == pytest.approx(expected)


def test_parser_rejects_invalid_xm(tmp_path):
    path = tmp_path / "broken.xm"
    path.write_bytes(b"not an XM")
    with pytest.raises(XMParseError):
        load_xm(path)


def test_parser_rejects_truncated_pattern_payload(tmp_path):
    header = bytearray(336)
    header[:17] = b"Extended Module: "
    header[37] = 0x1A
    struct.pack_into("<H", header, 58, 0x0104)
    struct.pack_into("<I", header, 60, 276)
    struct.pack_into("<8H", header, 64, 1, 0, 1, 1, 0, 1, 6, 125)
    pattern = struct.pack("<IBHH", 9, 0, 1, 1)
    path = tmp_path / "truncated.xm"
    path.write_bytes(bytes(header) + pattern)
    with pytest.raises(XMParseError):
        load_xm(path)


def test_real_uploaded_total_fvckery_module(tmp_path):
    # Binary creative assets stay outside Git; this optional test runs when the
    # developer places the source module alongside the local fixture tests.
    path = Path(__file__).parent / "fixtures" / "total fvckery.xm"
    if not path.exists():
        pytest.skip("User XM fixture is not stored in the repository.")
    module = load_xm(path)
    assert module.tracker.startswith("MilkyTracker")
    assert module.channels == 14
    assert module.instrument_count == 10
    assert module.bpm == 173
    assert module.speed == 6
    assert len(module.orders) == 24
    assert module.orders == (0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 7, 7, 5, 5, 14, 15, 16)
    assert module.cues[0].note_count == 17
    assert module.cues[-1].is_silent
    assert module.effect_count == 0
