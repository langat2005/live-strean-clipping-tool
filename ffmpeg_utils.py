"""Helpers for locating external FFmpeg executables."""

import os
from pathlib import Path
import shutil


def resolve_ffmpeg() -> str:
    """Return a usable FFmpeg executable or raise an actionable error."""
    configured_path = os.environ.get("FFMPEG_PATH")
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        resolved = shutil.which(configured_path)
        if resolved:
            return resolved
        raise FileNotFoundError(
            f"FFMPEG_PATH points to an unavailable executable: {configured_path}"
        )

    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    raise FileNotFoundError(
        "FFmpeg was not found on PATH. Install FFmpeg or set FFMPEG_PATH "
        "to the full path of ffmpeg.exe."
    )


def resolve_ffprobe() -> str:
    """Return a usable FFprobe executable or raise an actionable error."""
    configured_path = os.environ.get("FFPROBE_PATH")
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        resolved = shutil.which(configured_path)
        if resolved:
            return resolved
        raise FileNotFoundError(
            f"FFPROBE_PATH points to an unavailable executable: {configured_path}"
        )

    ffmpeg_path = Path(resolve_ffmpeg())
    sibling_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    sibling = ffmpeg_path.with_name(sibling_name)
    if sibling.is_file():
        return str(sibling)

    executable = shutil.which("ffprobe")
    if executable:
        return executable
    raise FileNotFoundError(
        "FFprobe was not found beside FFmpeg or on PATH. Set FFPROBE_PATH "
        "to the full path of ffprobe.exe."
    )
