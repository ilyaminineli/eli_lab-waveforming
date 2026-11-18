from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


AUDIO_EXTENSIONS = {".wav", ".flac", ".aiff", ".aif", ".ogg", ".mp3"}
CANVAS_SIZE = (1920, 1440)
FRAME_SIZE = (1322, 1058)
SCHEMA_VERSION = 1


@dataclass(slots=True)
class SessionTrack:
    track_id: str
    path: str
    name: str
    group_id: str
    group_name: str
    gain: float = 1.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False
    analysis_enabled: bool = True


@dataclass(slots=True)
class SessionGroup:
    group_id: str
    name: str
    folder: str = ""
    track_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectSession:
    """Portable project manifest; audio is referenced, not copied into the project."""

    title: str = "Untitled WAVEFORMING Session"
    canvas_size: tuple[int, int] = CANVAS_SIZE
    frame_size: tuple[int, int] = FRAME_SIZE
    screen: str = "SCREEN 1 / BLACK"
    fps: int = 30
    tracks: list[SessionTrack] = field(default_factory=list)
    groups: list[SessionGroup] = field(default_factory=list)
    layers: list[dict[str, Any]] = field(default_factory=list)
    generator_settings: dict[str, Any] = field(default_factory=dict)
    director_mode: str = "SEMI-AUTO"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "canvas_size": list(self.canvas_size),
            "frame_size": list(self.frame_size),
            "screen": self.screen,
            "fps": self.fps,
            "tracks": [asdict(track) for track in self.tracks],
            "groups": [asdict(group) for group in self.groups],
            "layers": self.layers,
            "generator_settings": self.generator_settings,
            "director_mode": self.director_mode,
        }

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ProjectSession":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("schema_version", 0)) > SCHEMA_VERSION:
            raise ValueError("This project was created by a newer WAVEFORMING version.")
        canvas = tuple(data.get("canvas_size", CANVAS_SIZE))
        if canvas != CANVAS_SIZE:
            raise ValueError(f"Unsupported canvas size {canvas}; expected {CANVAS_SIZE}.")
        tracks = [SessionTrack(**item) for item in data.get("tracks", [])]
        groups = [SessionGroup(**item) for item in data.get("groups", [])]
        return cls(
            title=str(data.get("title", path.stem)),
            canvas_size=CANVAS_SIZE,
            frame_size=tuple(data.get("frame_size", FRAME_SIZE)),
            screen=str(data.get("screen", "SCREEN 1 / BLACK")),
            fps=int(data.get("fps", 30)),
            tracks=tracks,
            groups=groups,
            layers=list(data.get("layers", [])),
            generator_settings=dict(data.get("generator_settings", {})),
            director_mode=str(data.get("director_mode", "SEMI-AUTO")),
            schema_version=SCHEMA_VERSION,
        )


def scan_audio_tree(root: Path) -> dict[str, list[Path]]:
    """Return supported audio files grouped by their immediate subdirectory."""
    root = Path(root)
    groups: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            relative_parent = path.parent.relative_to(root)
            group = root.name if str(relative_parent) == "." else f"{root.name}/{relative_parent.as_posix()}"
            groups.setdefault(group, []).append(path)
    return groups
