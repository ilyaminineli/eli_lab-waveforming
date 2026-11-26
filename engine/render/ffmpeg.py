from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_ffmpeg() -> str | None:
    """Resolve FFmpeg from PATH, explicit environment variables or bundled imageio-ffmpeg."""
    for variable in ("FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE"):
        value = os.environ.get(variable, "").strip().strip('"')
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        located = shutil.which(value)
        if located:
            return located

    for command in ("ffmpeg", "ffmpeg.exe"):
        located = shutil.which(command)
        if located:
            return located

    # Common Windows package-manager locations; these do not require a PATH edit.
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    windows_candidates = (
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/FFmpeg/bin/ffmpeg.exe"),
        Path("C:/tools/ffmpeg/bin/ffmpeg.exe"),
        local_app_data / "Microsoft/WinGet/Links/ffmpeg.exe",
        program_data / "chocolatey/bin/ffmpeg.exe",
    )
    for candidate in windows_candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled.is_file():
            return str(bundled.resolve())
    except (ImportError, OSError, RuntimeError):
        pass
    return None
