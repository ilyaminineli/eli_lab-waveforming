from __future__ import annotations

"""Dependency-free XM metadata parser and tracker cue extraction.

Only song/pattern metadata is decoded. Instrument sample payloads are deliberately
skipped; this module is a visual-score importer, not an XM audio player.
"""

import bisect
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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
    row_note_counts: tuple[int, ...]
    is_silent: bool = False

    def to_dict(self, note_map: tuple[tuple[int, ...], ...] | None = None) -> dict[str, Any]:
        result = asdict(self)
        if note_map is not None:
            result["notes"] = [list(row) for row in note_map]
        return result


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
    effect_count: int = 0
    flow_control_effect_count: int = 0

    @property
    def duration(self) -> float:
        return self.cues[-1].end_seconds if self.cues else 0.0

    def cue_at(self, seconds: float) -> XMOrderCue | None:
        if not self.cues:
            return None
        starts = [cue.start_seconds for cue in self.cues]
        index = bisect.bisect_right(starts, max(0.0, float(seconds))) - 1
        return self.cues[max(0, min(index, len(self.cues) - 1))]

    def visual_data(self) -> dict[str, Any]:
        """Return a compact, JSON-serialisable score for projects and render workers."""
        cue_data = []
        for cue in self.cues:
            rows = self.patterns[cue.pattern]
            item = cue.to_dict(tuple(
                tuple(event.note if event.has_note else 0 for event in row)
                for row in rows
            ))
            item["instruments"] = [
                [event.instrument if event.has_note else 0 for event in row]
                for row in rows
            ]
            cue_data.append(item)
        return {
            "title": self.title,
            "tracker": self.tracker,
            "channels": self.channels,
            "bpm": self.bpm,
            "speed": self.speed,
            "duration": self.duration,
            "effect_count": self.effect_count,
            "flow_control_effect_count": self.flow_control_effect_count,
            "cues": cue_data,
        }

    def visual_packet(self, seconds: float) -> dict[str, Any] | None:
        cue = self.cue_at(seconds)
        if cue is None:
            return None
        rows = self.patterns[cue.pattern]
        payload = cue.to_dict(tuple(
            tuple(event.note if event.has_note else 0 for event in row)
            for row in rows
        ))
        payload["instruments"] = [
            [event.instrument if event.has_note else 0 for event in row]
            for row in rows
        ]
        span = max(1e-9, cue.end_seconds - cue.start_seconds)
        payload["progress"] = max(
            0.0, min(1.0, (float(seconds) - cue.start_seconds) / span)
        )
        return payload


def tracker_packet_at(data: dict[str, Any] | None, seconds: float) -> dict[str, Any] | None:
    """Find the active order cue in a serialised tracker score."""
    if not data:
        return None
    cues = data.get("cues") or []
    if not cues:
        return None
    starts = [float(item.get("start_seconds", 0.0)) for item in cues]
    position = max(0.0, float(seconds))
    index = bisect.bisect_right(starts, position) - 1
    cue = dict(cues[max(0, min(index, len(cues) - 1))])
    span = max(1e-9, float(cue.get("end_seconds", 0.0)) - float(cue.get("start_seconds", 0.0)))
    cue["progress"] = max(
        0.0,
        min(1.0, (position - float(cue.get("start_seconds", 0.0))) / span),
    )
    return cue


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

    # XM permits a zero-length packed block to represent an entirely empty pattern.
    if packed_size == 0:
        empty_row = tuple(XMEvent() for _ in range(channels))
        return tuple(empty_row for _ in range(rows)), payload_end

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
    if cursor != len(payload):
        # Extra bytes can indicate an invalid pattern block or unsupported packing.
        raise XMParseError("XM pattern contains unconsumed packed event data.")
    return tuple(decoded), payload_end


def load_xm(path: str | Path) -> XMModule:
    """Read XM song structure and derive order cue times from tracker tempo."""
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
    song_length, _restart, channels, pattern_count, _instrument_count, _flags, speed, bpm = struct.unpack_from(
        "<8H", raw, 64
    )
    if not 1 <= channels <= 64 or not 1 <= song_length <= 256 or not 1 <= pattern_count <= 256:
        raise XMParseError("XM header contains unreasonable channel, order or pattern counts.")
    if not 1 <= speed <= 31 or not 32 <= bpm <= 255:
        raise XMParseError("XM module has invalid initial tempo settings.")
    orders = tuple(raw[80:80 + song_length])
    if len(orders) != song_length or any(index >= pattern_count for index in orders):
        raise XMParseError("XM order list references a missing pattern.")

    offset = 60 + header_size
    patterns: list[tuple[tuple[XMEvent, ...], ...]] = []
    for _ in range(pattern_count):
        pattern, offset = _read_pattern(raw, offset, channels)
        patterns.append(pattern)

    effect_count = 0
    flow_control_effect_count = 0
    cues: list[XMOrderCue] = []
    current_speed, current_bpm = speed, bpm
    elapsed = 0.0
    flow_effects = {0x0B, 0x0D, 0x0E}
    for order_index, pattern_index in enumerate(orders):
        rows = patterns[pattern_index]
        order_start = elapsed
        row_counts: list[int] = []
        order_note_count = 0
        active_channels: set[int] = set()
        instruments: set[int] = set()
        for row in rows:
            # Fxx changes speed (1..31) or tempo (32..255) for this row and onward.
            for channel_index, event in enumerate(row):
                if event.effect or event.parameter:
                    effect_count += 1
                    if (
                        event.effect in (0x0B, 0x0D)
                        or (event.effect == 0x0E and (event.parameter >> 4) == 0x06)
                    ):
                        flow_control_effect_count += 1
                    if event.effect == 0x0F and event.parameter:
                        if event.parameter < 32:
                            current_speed = max(1, event.parameter)
                        else:
                            current_bpm = max(32, event.parameter)
                if event.has_note:
                    order_note_count += 1
                    active_channels.add(channel_index + 1)
                    if event.instrument:
                        instruments.add(event.instrument)
            row_counts.append(sum(1 for event in row if event.has_note))
            elapsed += current_speed * 2.5 / current_bpm

        cues.append(XMOrderCue(
            order=order_index,
            pattern=pattern_index,
            start_seconds=order_start,
            end_seconds=elapsed,
            note_count=order_note_count,
            active_channels=tuple(sorted(active_channels)),
            instrument_ids=tuple(sorted(instruments)),
            density=order_note_count / max(1, len(rows)),
            row_note_counts=tuple(row_counts),
            is_silent=order_note_count == 0,
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
        effect_count=effect_count,
        flow_control_effect_count=flow_control_effect_count,
    )
