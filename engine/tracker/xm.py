from __future__ import annotations

"""Dependency-free XM metadata parser and tracker cue extraction.

Only song/pattern metadata is decoded. Instrument sample payloads are deliberately
skipped; this module is a visual-score importer, not an XM audio player.
"""

import bisect
import hashlib
import math
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
class XMInstrument:
    index: int
    name: str
    sample_names: tuple[str, ...] = ()
    sample_count: int = 0


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

    def to_dict(
        self, note_map: tuple[tuple[int, ...], ...] | None = None
    ) -> dict[str, Any]:
        result = asdict(self)
        if note_map is not None:
            result["notes"] = [list(row) for row in note_map]
        return result


@dataclass(frozen=True, slots=True)
class XMModule:
    title: str
    tracker: str
    channels: int
    instrument_count: int
    instruments: tuple[XMInstrument, ...]
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

    @property
    def score_id(self) -> str:
        """Stable content-derived ID for this tracker score."""
        digest = hashlib.sha256()
        digest.update(self.title.encode("utf-8", "replace"))
        digest.update(self.tracker.encode("utf-8", "replace"))
        digest.update(bytes((self.channels, self.bpm, self.speed)))
        digest.update(bytes(self.orders))
        for pattern in self.patterns:
            for row in pattern:
                for event in row:
                    digest.update(bytes((
                        event.note, event.instrument, event.volume,
                        event.effect, event.parameter,
                    )))
        return "xm-" + digest.hexdigest()[:16]

    def channel_profiles(self) -> list[dict[str, Any]]:
        """Describe each real XM channel and its predominant instrument/sample identity."""
        profiles: list[dict[str, Any]] = []
        score_id = self.score_id
        instrument_map = {item.index: item for item in self.instruments}
        for channel_index in range(self.channels):
            note_values: list[int] = []
            instrument_counts: dict[int, int] = {}
            pattern_ids: list[int] = []
            for pattern_index, pattern in enumerate(self.patterns):
                pattern_notes = 0
                for row in pattern:
                    event = row[channel_index]
                    if event.instrument:
                        instrument_counts[event.instrument] = (
                            instrument_counts.get(event.instrument, 0) + 1
                        )
                    if event.has_note:
                        note_values.append(event.note)
                        pattern_notes += 1
                if pattern_notes:
                    pattern_ids.append(pattern_index)

            dominant_instrument = (
                max(instrument_counts, key=instrument_counts.get)
                if instrument_counts else 0
            )
            instrument = instrument_map.get(dominant_instrument)
            sample_name = (
                instrument.sample_names[0]
                if instrument and instrument.sample_names else ""
            )
            display_name = sample_name or (
                instrument.name if instrument and instrument.name else ""
            )
            profiles.append({
                "channel": channel_index + 1,
                "voice_id": f"{score_id}:channel:{channel_index + 1:02d}",
                "label": f"CH {channel_index + 1:02d}",
                "instrument_id": dominant_instrument,
                "instrument_name": instrument.name if instrument else "",
                "sample_name": display_name,
                "sample_names": list(instrument.sample_names) if instrument else [],
                "note_count": len(note_values),
                "pitch_min": min(note_values) if note_values else 0,
                "pitch_max": max(note_values) if note_values else 0,
                "pitch_mean": (
                    float(sum(note_values) / len(note_values)) if note_values else 0.0
                ),
                "active_patterns": pattern_ids,
                "instrument_ids": sorted(instrument_counts),
                "silent": not note_values,
            })
        return profiles

    def visual_data(self) -> dict[str, Any]:
        """Return a structured, JSON-serialisable tracker score for visual composition."""
        cue_data = []
        seen_patterns: set[int] = set()
        previous: XMOrderCue | None = None
        carried_instruments = [0] * self.channels
        carried_notes = [0] * self.channels
        carried_note_ages = [0] * self.channels
        for cue in self.cues:
            rows = self.patterns[cue.pattern]
            initial_instruments = list(carried_instruments)
            initial_notes = list(carried_notes)
            initial_note_ages = list(carried_note_ages)
            item = cue.to_dict(
                tuple(
                    tuple(event.note if event.has_note else 0 for event in row)
                    for row in rows
                )
            )
            item["instruments"] = [
                [event.instrument for event in row] for row in rows
            ]
            item["channel_initial_instruments"] = initial_instruments
            item["channel_initial_notes"] = initial_notes
            item["channel_initial_note_ages"] = initial_note_ages
            item["note_commands"] = [
                [event.note for event in row] for row in rows
            ]
            for row in rows:
                for channel_index, event in enumerate(row):
                    if event.instrument:
                        carried_instruments[channel_index] = event.instrument
                    if 1 <= event.note <= 96:
                        carried_notes[channel_index] = event.note
                        carried_note_ages[channel_index] = 0
                    elif event.note in (97, 98, 99):
                        carried_notes[channel_index] = 0
                        carried_note_ages[channel_index] = 0
                    elif carried_notes[channel_index]:
                        carried_note_ages[channel_index] += 1
            # One more row elapses between the final row and the next order.
            for channel_index in range(self.channels):
                if carried_notes[channel_index]:
                    carried_note_ages[channel_index] += 1
            item["volumes"] = [
                [event.volume for event in row] for row in rows
            ]
            item["effects"] = [
                [event.effect for event in row] for row in rows
            ]
            item["parameters"] = [
                [event.parameter for event in row] for row in rows
            ]
            item["channel_note_counts"] = [
                sum(1 for row in rows if row[channel].has_note)
                for channel in range(self.channels)
            ]
            if previous is None:
                transition = 0.55 if cue.note_count else 0.15
            else:
                pattern_change = 1.0 if cue.pattern != previous.pattern else 0.2
                density_change = abs(cue.density - previous.density)
                channel_change = abs(
                    len(cue.active_channels) - len(previous.active_channels)
                ) / max(1, self.channels)
                transition = min(
                    1.0,
                    0.12
                    + pattern_change * 0.35
                    + density_change * 0.8
                    + channel_change * 0.5,
                )
            item["transition_strength"] = float(transition)
            item["pattern_reprise"] = cue.pattern in seen_patterns
            cue_data.append(item)
            seen_patterns.add(cue.pattern)
            previous = cue

        instruments = [
            {
                "index": item.index,
                "name": item.name,
                "sample_names": list(item.sample_names),
                "sample_count": item.sample_count,
            }
            for item in self.instruments
        ]
        return {
            "score_id": self.score_id,
            "title": self.title,
            "tracker": self.tracker,
            "channels": self.channels,
            "channel_profiles": self.channel_profiles(),
            "instrument_count": self.instrument_count,
            "instruments": instruments,
            "bpm": self.bpm,
            "speed": self.speed,
            "duration": self.duration,
            "effect_count": self.effect_count,
            "flow_control_effect_count": self.flow_control_effect_count,
            "cues": cue_data,
        }

    def visual_packet(self, seconds: float) -> dict[str, Any] | None:
        return tracker_packet_at(self.visual_data(), seconds)


def tracker_packet_at(
    data: dict[str, Any] | None, seconds: float
) -> dict[str, Any] | None:
    """Resolve an XM order and its 14/64 channel event states at an exact time."""
    if not data:
        return None
    cues = data.get("cues") or []
    if not cues:
        return None
    starts = [float(item.get("start_seconds", 0.0)) for item in cues]
    position = max(0.0, float(seconds))
    index = bisect.bisect_right(starts, position) - 1
    cue = dict(cues[max(0, min(index, len(cues) - 1))])
    start = float(cue.get("start_seconds", 0.0))
    end = float(cue.get("end_seconds", start))
    span = max(1e-9, end - start)
    progress = max(0.0, min(1.0, (position - start) / span))
    cue["progress"] = progress

    note_rows = cue.get("notes") or []
    row_counts = cue.get("row_note_counts") or []
    row_total = len(note_rows) or len(row_counts)
    row_index = min(row_total - 1, int(progress * row_total)) if row_total else 0
    row_notes = note_rows[row_index] if note_rows and row_index < len(note_rows) else []
    row_note_count = (
        int(row_counts[row_index])
        if row_index < len(row_counts)
        else sum(1 for note in row_notes if 1 <= int(note) <= 96)
    )
    channel_count = max(1, int(data.get("channels", len(row_notes) or 1)))
    row_progress = (progress * row_total) - row_index if row_total else 0.0
    cue["row_index"] = row_index
    cue["row_progress"] = max(0.0, min(1.0, row_progress))
    cue["row_note_count"] = row_note_count
    cue["row_activity"] = max(0.0, min(1.0, row_note_count / channel_count))
    cue["transition_strength"] = float(
        max(0.0, min(1.0, cue.get("transition_strength", 0.0)))
    )
    cue["pattern_reprise"] = bool(cue.get("pattern_reprise", False))

    profiles = data.get("channel_profiles") or []
    instrument_map = {
        int(item.get("index", 0)): item
        for item in (data.get("instruments") or [])
    }
    instrument_rows = cue.get("instruments") or []
    initial_instruments = cue.get("channel_initial_instruments") or []
    note_command_rows = cue.get("note_commands") or []
    initial_notes = cue.get("channel_initial_notes") or []
    initial_note_ages = cue.get("channel_initial_note_ages") or []
    volume_rows = cue.get("volumes") or []
    effect_rows = cue.get("effects") or []
    parameter_rows = cue.get("parameters") or []
    channel_note_counts = cue.get("channel_note_counts") or []
    channel_states: list[dict[str, Any]] = []
    for channel_index in range(channel_count):
        profile = (
            profiles[channel_index]
            if channel_index < len(profiles)
            else {"channel": channel_index + 1, "label": f"CH {channel_index + 1:02d}"}
        )
        current_note = (
            int(row_notes[channel_index])
            if channel_index < len(row_notes) else 0
        )
        current_note_command = (
            int(note_command_rows[row_index][channel_index])
            if row_index < len(note_command_rows)
            and channel_index < len(note_command_rows[row_index])
            else current_note
        )
        current_instrument = (
            int(instrument_rows[row_index][channel_index])
            if row_index < len(instrument_rows)
            and channel_index < len(instrument_rows[row_index])
            else 0
        )
        current_volume = (
            int(volume_rows[row_index][channel_index])
            if row_index < len(volume_rows)
            and channel_index < len(volume_rows[row_index])
            else 0
        )
        current_effect = (
            int(effect_rows[row_index][channel_index])
            if row_index < len(effect_rows)
            and channel_index < len(effect_rows[row_index])
            else 0
        )
        current_parameter = (
            int(parameter_rows[row_index][channel_index])
            if row_index < len(parameter_rows)
            and channel_index < len(parameter_rows[row_index])
            else 0
        )

        # Tracker instrument selection and note pitch persist until replaced.
        held_note = (
            int(initial_notes[channel_index])
            if channel_index < len(initial_notes) else 0
        )
        held_instrument = (
            int(initial_instruments[channel_index])
            if channel_index < len(initial_instruments) else 0
        )
        note_age = (
            int(initial_note_ages[channel_index]) + row_index
            if held_note and channel_index < len(initial_note_ages)
            else row_total + 1
        )
        recent_hits = 0
        volume = 0.82
        volume_found = False
        for scan_row in range(row_index, -1, -1):
            if scan_row < len(note_command_rows) and channel_index < len(note_command_rows[scan_row]):
                note_command = int(note_command_rows[scan_row][channel_index])
                if 1 <= note_command <= 96:
                    held_note = note_command
                    note_age = row_index - scan_row
                    break
                if note_command in (97, 98, 99):
                    held_note = 0
                    note_age = row_index - scan_row
                    break
            if scan_row < len(instrument_rows) and channel_index < len(instrument_rows[scan_row]):
                instrument_value = int(instrument_rows[scan_row][channel_index])
                if instrument_value and held_instrument == 0:
                    held_instrument = instrument_value
            if scan_row < len(volume_rows) and channel_index < len(volume_rows[scan_row]):
                volume_command = int(volume_rows[scan_row][channel_index])
                if 0x10 <= volume_command <= 0x50 and not volume_found:
                    volume = (volume_command - 0x10) / 64.0
                    volume_found = True
        recent_start = max(0, row_index - 15)
        for scan_row in range(recent_start, row_index + 1):
            if scan_row < len(note_rows) and channel_index < len(note_rows[scan_row]):
                if 1 <= int(note_rows[scan_row][channel_index]) <= 96:
                    recent_hits += 1

        note_density = (
            float(channel_note_counts[channel_index]) / max(1, row_total)
            if channel_index < len(channel_note_counts) else 0.0
        )
        envelope = math.exp(-max(0, note_age) / 5.0) if held_note else 0.0
        trigger = 1.0 if 1 <= current_note_command <= 96 else 0.0
        activity = max(trigger, envelope * 0.78) * max(0.12, volume)
        pan = 0.5
        if current_effect == 0x08:
            pan = current_parameter / 255.0
        elif current_effect == 0x0E and (current_parameter >> 4) == 0x08:
            pan = (current_parameter & 0x0F) / 15.0

        effect_names = {
            0x00: "ARPEGGIO",
            0x01: "SLIDE_UP",
            0x02: "SLIDE_DOWN",
            0x03: "PORTAMENTO",
            0x04: "VIBRATO",
            0x05: "PORTA_VOLUME",
            0x06: "VIBRATO_VOLUME",
            0x07: "TREMOLO",
            0x08: "PAN",
            0x09: "SAMPLE_OFFSET",
            0x0A: "VOLUME_SLIDE",
            0x0B: "ORDER_JUMP",
            0x0D: "PATTERN_BREAK",
            0x0F: "TEMPO_SPEED",
        }
        effect_name = effect_names.get(current_effect, "")
        if current_effect == 0x0E:
            effect_name = {
                0x1: "FINE_SLIDE_UP",
                0x2: "FINE_SLIDE_DOWN",
                0x4: "VIBRATO_WAVE",
                0x6: "PATTERN_LOOP",
                0x7: "TREMolo_WAVE",
                0x8: "PAN",
                0x9: "RETRIGGER",
                0xC: "NOTE_CUT",
                0xD: "NOTE_DELAY",
                0xE: "PATTERN_DELAY",
            }.get(current_parameter >> 4, "EXTENDED")
        resolved_instrument = current_instrument or held_instrument or int(
            profile.get("instrument_id", 0)
        )
        resolved_sample = instrument_map.get(resolved_instrument, {})
        sample_names = resolved_sample.get("sample_names") or []
        resolved_sample_name = (
            sample_names[0] if sample_names
            else resolved_sample.get("name", profile.get("sample_name", ""))
        )
        channel_states.append({
            **profile,
            "channel": channel_index + 1,
            "voice_id": profile.get(
                "voice_id", f"xm:channel:{channel_index + 1:02d}"
            ),
            "current_note": current_note,
            "held_note": held_note,
            "pitch": (held_note - 1) / 95.0 if held_note else 0.0,
            "note_age_rows": note_age if held_note else -1,
            "trigger": trigger,
            "envelope": float(max(0.0, min(1.0, envelope))),
            "activity": float(max(0.0, min(1.0, activity))),
            "note_density": float(max(0.0, min(1.0, note_density))),
            "recent_hits": recent_hits,
            "instrument_id": resolved_instrument,
            "sample_name": str(resolved_sample_name or ""),
            "volume_command": current_volume,
            "volume": float(max(0.0, min(1.0, volume))),
            "effect": current_effect,
            "parameter": current_parameter,
            "effect_name": effect_name,
            "effect_amount": current_parameter / 255.0,
            "pan": float(max(0.0, min(1.0, pan))),
            "silent": bool(profile.get("silent", False)),
        })
    cue["channel_states"] = channel_states
    cue["active_channel_count"] = sum(
        1 for state in channel_states if state["activity"] > 0.05
    )
    cue["mean_channel_activity"] = (
        sum(state["activity"] for state in channel_states) / max(1, channel_count)
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


def _read_exact(stream, size: int, description: str) -> bytes:
    if size < 0:
        raise XMParseError(f"Invalid {description} size.")
    data = stream.read(size)
    if len(data) != size:
        raise XMParseError(f"Truncated {description}.")
    return data


def _read_pattern(stream, channels: int) -> tuple[tuple[tuple[XMEvent, ...], ...], int]:
    header = _read_exact(stream, 9, "XM pattern header")
    header_size = _u32(header, 0)
    if header_size < 9 or header_size > 4096:
        raise XMParseError("Invalid XM pattern header size.")
    if header_size > 9:
        _read_exact(stream, header_size - 9, "extended XM pattern header")
    packing_type = header[4]
    rows = _u16(header, 5)
    packed_size = _u16(header, 7)
    if rows < 1 or rows > 256 or packing_type != 0:
        raise XMParseError("Unsupported XM pattern packing or row count.")

    # XM permits a zero-length packed block to represent an entirely empty pattern.
    if packed_size == 0:
        empty_row = tuple(XMEvent() for _ in range(channels))
        return tuple(empty_row for _ in range(rows)), 0

    payload = _read_exact(stream, packed_size, "XM pattern data")
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
                values[:] = [lead, *payload[cursor : cursor + 4]]
                cursor += 4
            row.append(XMEvent(*values))
        decoded.append(tuple(row))
    if cursor != len(payload):
        raise XMParseError("XM pattern contains unconsumed packed event data.")
    return tuple(decoded), packed_size


def _read_instrument_table(stream, instrument_count: int, file_size: int) -> tuple[XMInstrument, ...]:
    """Read XM instrument/sample headers, then seek over raw sample payloads."""
    instruments: list[XMInstrument] = []
    for index in range(instrument_count):
        size_bytes = _read_exact(stream, 4, "XM instrument header size")
        header_size = _u32(size_bytes, 0)
        if header_size < 29 or header_size > 65536:
            raise XMParseError("Invalid XM instrument header size.")
        header = _read_exact(stream, header_size - 4, "XM instrument header")
        name = header[:22].split(b"\\0", 1)[0].decode("latin-1", "replace").strip()
        sample_count = _u16(header, 23)
        if sample_count > 256:
            raise XMParseError("XM instrument contains an unreasonable sample count.")
        sample_names: list[str] = []
        sample_lengths: list[int] = []
        if sample_count:
            if len(header) < 29:
                raise XMParseError("Truncated XM instrument sample header size.")
            sample_header_size = _u32(header, 25)
            if not 40 <= sample_header_size <= 4096:
                raise XMParseError("Unsupported XM sample header size.")
            for _sample_index in range(sample_count):
                sample_header = _read_exact(
                    stream, sample_header_size, "XM sample header"
                )
                sample_length = _u32(sample_header, 0)
                sample_name = (
                    sample_header[18:40]
                    .split(b"\\0", 1)[0]
                    .decode("latin-1", "replace")
                    .strip()
                )
                sample_lengths.append(sample_length)
                if sample_name:
                    sample_names.append(sample_name)
            skip_bytes = sum(sample_lengths)
            current = stream.tell()
            if current + skip_bytes > file_size:
                raise XMParseError("Truncated XM instrument sample payload.")
            # Seek rather than read/decode sample data. Visual import only needs
            # instrument/sample identity, not tracker audio playback.
            stream.seek(skip_bytes, 1)
        instruments.append(
            XMInstrument(
                index=index + 1,
                name=name,
                sample_names=tuple(sample_names),
                sample_count=sample_count,
            )
        )
    return tuple(instruments)


def load_xm(path: str | Path) -> XMModule:
    """Read XM structure, instrument/sample metadata and skip sample audio payloads."""
    path = Path(path)
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = _read_exact(stream, 80, "XM module header")
        if header[:17] != b"Extended Module: " or header[37] != 0x1A:
            raise XMParseError("Not a valid XM module.")
        title = (
            header[17:37].split(b"\\0", 1)[0]
            .decode("latin-1", "replace").strip()
            or path.stem
        )
        tracker = header[38:58].split(b"\\0", 1)[0].decode("latin-1", "replace").strip()
        version = _u16(header, 58)
        if version < 0x0104:
            raise XMParseError(f"Unsupported XM version 0x{version:04x}.")
        header_size = _u32(header, 60)
        if header_size < 20:
            raise XMParseError("Invalid XM song header size.")
        (
            song_length,
            _restart,
            channels,
            pattern_count,
            instrument_count,
            _flags,
            speed,
            bpm,
        ) = struct.unpack_from("<8H", header, 64)
        if (
            not 1 <= channels <= 64
            or not 1 <= song_length <= 256
            or not 1 <= pattern_count <= 256
            or not 0 <= instrument_count <= 128
        ):
            raise XMParseError(
                "XM header contains unreasonable channel, order, pattern or instrument counts."
            )
        if not 1 <= speed <= 31 or not 32 <= bpm <= 255:
            raise XMParseError("XM module has invalid initial tempo settings.")

        header_end = 60 + header_size
        orders_end = 80 + song_length
        if header_end < orders_end:
            raise XMParseError("XM song header is too short for its order list.")
        orders = tuple(_read_exact(stream, song_length, "XM order list"))
        remaining_header = header_end - orders_end
        if remaining_header:
            _read_exact(stream, remaining_header, "XM song header extension")
        if any(index >= pattern_count for index in orders):
            raise XMParseError("XM order list references a missing pattern.")

        patterns: list[tuple[tuple[XMEvent, ...], ...]] = []
        for _ in range(pattern_count):
            pattern, _packed_size = _read_pattern(stream, channels)
            patterns.append(pattern)

        instruments = _read_instrument_table(stream, instrument_count, file_size)

    effect_count = 0
    flow_control_effect_count = 0
    cues: list[XMOrderCue] = []
    current_speed, current_bpm = speed, bpm
    elapsed = 0.0
    for order_index, pattern_index in enumerate(orders):
        rows = patterns[pattern_index]
        order_start = elapsed
        row_counts: list[int] = []
        order_note_count = 0
        active_channels: set[int] = set()
        used_instruments: set[int] = set()
        for row in rows:
            for channel_index, event in enumerate(row):
                if event.effect or event.parameter:
                    effect_count += 1
                    if event.effect in (0x0B, 0x0D) or (
                        event.effect == 0x0E and (event.parameter >> 4) == 0x06
                    ):
                        flow_control_effect_count += 1
                    if event.effect == 0x0F and event.parameter:
                        if event.parameter < 32:
                            current_speed = max(1, event.parameter)
                        else:
                            current_bpm = max(32, event.parameter)
                if event.instrument:
                    used_instruments.add(event.instrument)
                if event.has_note:
                    order_note_count += 1
                    active_channels.add(channel_index + 1)
            row_counts.append(sum(1 for event in row if event.has_note))
            elapsed += current_speed * 2.5 / current_bpm

        cues.append(
            XMOrderCue(
                order=order_index,
                pattern=pattern_index,
                start_seconds=order_start,
                end_seconds=elapsed,
                note_count=order_note_count,
                active_channels=tuple(sorted(active_channels)),
                instrument_ids=tuple(sorted(used_instruments)),
                density=order_note_count / max(1, len(rows) * channels),
                row_note_counts=tuple(row_counts),
                is_silent=order_note_count == 0,
            )
        )

    return XMModule(
        title=title,
        tracker=tracker,
        channels=channels,
        instrument_count=instrument_count,
        instruments=instruments,
        bpm=bpm,
        speed=speed,
        orders=orders,
        patterns=tuple(patterns),
        cues=tuple(cues),
        effect_count=effect_count,
        flow_control_effect_count=flow_control_effect_count,
    )
