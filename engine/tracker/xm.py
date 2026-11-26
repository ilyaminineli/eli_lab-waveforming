from __future__ import annotations

"""Minimal, dependency-free XM pattern parser for visual cue extraction.

The parser reads pattern/event metadata only. Sample payloads are skipped rather
than decoded or loaded into memory.
"""

import struct
from dataclasses import dataclass
from pathlib import Path


class XMParseError(ValueError):
    """Raised when an XM file is truncated or structurally invalid."""


@dataclass(frozen=True, slots=True)
class XMEvent:
    note: int = 0
    instrument: int = 0
    volume: int = 0
    effect: int = 0
    parameter: int = 0

    @property
    def has_note(self) -> bool:
        return 1 <= self.note <= 96


@dataclass(frozen=True, slots=True)
class XMOrderCue:
    order: int
    pattern: int
    start_seconds: float
    end_seconds: float
    note_count: int
    active_channels: tuple[int, ...]
    instrument_ids: tuple[int, ...]
    density: float
    is_silent: bool = False


@dataclass(frozen=True, slots=True)
class XMModule:
    title: str
    tracker: str
    channels: int
    bpm: int
    speed: int
    orders: tuple[int, ...]
    patterns: tuple[tuple[tuple[XMEvent, ...], ...], ...]
    cues: tuple[XMOrderCue, ...]

    @property
    def duration(self) -> float:
        return self.cues[-1].end_seconds if self.cues else 0.0


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise XMParseError("Unexpected end of XM header.")
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise XMParseError("Unexpected end of XM structure.")
    return struct.unpack_from("<I", data, offset)[0]


def _read_pattern(
    data: bytes, offset: int, channels: int
) -> tuple[tuple[tuple[XMEvent, ...], ...], int]:
    header_size = _u32(data, offset)
    if header_size < 9 or offset + header_size > len(data):
        raise XMParseError("Invalid XM pattern header size.")
    packing_type = data[offset + 4]
    rows = _u16(data, offset + 5)
    packed_size = _u16(data, offset + 7)
    if rows < 1 or rows > 256 or packing_type != 0:
        raise XMParseError("Unsupported XM pattern packing or row count.")
    payload_start = offset + header_size
    payload_end = payload_start + packed_size
    if payload_end > len(data):
        raise XMParseError("Truncated XM pattern data.")
    payload = data[payload_start:payload_end]
    cursor = 0
    decoded: list[tuple[XMEvent, ...]] = []
    for _row in range(rows):
        row: list[XMEvent] = []
        for _channel in range(channels):
            if cursor >= len(payload):
                raise XMParseError("Truncated packed XM event.")
            lead = payload[cursor]
            cursor += 1
            values = [0, 0, 0, 0, 0]
            if lead & 0x80:
                for index, bit in enumerate((1, 2, 4, 8, 16)):
                    if lead & bit:
                        if cursor >= len(payload):
                            raise XMParseError("Truncated packed XM field.")
                        values[index] = payload[cursor]
                        cursor += 1
            else:
                if cursor + 4 > len(payload):
                    raise XMParseError("Truncated unpacked XM event.")
                values[:] = [lead, *payload[cursor:cursor + 4]]
                cursor += 4
            row.append(XMEvent(*values))
        decoded.append(tuple(row))
    return tuple(decoded), payload_end


def load_xm(path: str | Path) -> XMModule:
    """Read XM song structure and convert its order list to absolute cue times."""
    raw = Path(path).read_bytes()
    if len(raw) < 80 or raw[:17] != b"Extended Module: " or raw[37] != 0x1A:
        raise XMParseError("Not a valid XM module.")
    title = raw[17:37].split(b"\0", 1)[0].decode("latin-1", "replace").strip()
    tracker = raw[38:58].split(b"\0", 1)[0].decode("latin-1", "replace").strip()
    version = _u16(raw, 58)
    if version < 0x0104:
        raise XMParseError(f"Unsupported XM version 0x{version:04x}.")
    header_size = _u32(raw, 60)
    if header_size < 20 or 60 + header_size > len(raw):
        raise XMParseError("Invalid XM song header size.")
    song_length, _restart, channels, pattern_count, _instrument_count, _flags, speed, bpm = struct.unpack_from("<8H", raw, 64)
    if not 1 <= channels <= 64 or not 1 <= song_length <= 256 or pattern_count > 256:
        raise XMParseError("XM header contains unreasonable channel, order or pattern counts.")
    if speed < 1 or bpm < 1:
        raise XMParseError("XM module has invalid tempo settings.")
    orders = tuple(raw[80:80 + song_length])
    if len(orders) != song_length or any(index >= pattern_count for index in orders):
        raise XMParseError("XM order list references a missing pattern.")

    offset = 60 + header_size
    patterns: list[tuple[tuple[XMEvent, ...], ...]] = []
    for _ in range(pattern_count):
        pattern, offset = _read_pattern(raw, offset, channels)
        patterns.append(pattern)

    row_seconds = speed * 2.5 / bpm
    cues: list[XMOrderCue] = []
    for order_index, pattern_index in enumerate(orders):
        rows = patterns[pattern_index]
        notes = [event for row in rows for event in row if event.has_note]
        active_channels = tuple(
            channel + 1 for channel in range(channels)
            if any(row[channel].has_note for row in rows)
        )
        instruments = tuple(sorted({event.instrument for event in notes if event.instrument}))
        start = order_index * len(rows) * row_seconds
        end = start + len(rows) * row_seconds
        cues.append(XMOrderCue(
            order=order_index,
            pattern=pattern_index,
            start_seconds=start,
            end_seconds=end,
            note_count=len(notes),
            active_channels=active_channels,
            instrument_ids=instruments,
            density=len(notes) / max(1, len(rows)),
            is_silent=not notes,
        ))
    return XMModule(
        title=title,
        tracker=tracker,
        channels=channels,
        bpm=bpm,
        speed=speed,
        orders=orders,
        patterns=tuple(patterns),
        cues=tuple(cues),
    )
