r"""
Subtitle Burn-in Module.
Applies FFmpeg libass/subtitles filter to permanently render dynamic
ASS subtitles into the vertical video.
"""

import logging
from pathlib import Path
import subprocess

from ffmpeg_utils import resolve_ffmpeg

logger = logging.getLogger(__name__)


class SubtitleBurner:
    """Burns ASS subtitles into a video stream."""

    def __init__(self, encoder_threads: int = 2):
        if encoder_threads <= 0:
            raise ValueError("encoder_threads must be greater than zero.")
        self.encoder_threads = encoder_threads

    @staticmethod
    def _sanitize_path_for_ffmpeg_filter(path: Path) -> str:
        r"""
        Escapes backslashes and drive colons for FFmpeg filter syntax, especially on Windows.
        Example: C:\path\subs.ass -> C\\:/path/subs.ass
        """
        resolved = path.resolve().as_posix()
        # Escape colon after Windows drive letter: C: -> C\\:
        if len(resolved) > 1 and resolved[1] == ":":
            resolved = resolved[0] + "\\:" + resolved[2:]
        return resolved

    def burn_subtitles(self, video_path: Path, ass_path: Path, output_path: Path) -> Path:
        """
        Burns the ASS subtitle script onto the input video.
        
        Args:
            video_path: Input vertical video.
            ass_path: Generated ASS subtitle file.
            output_path: Destination path for finished clip with hardcoded captions.
            
        Returns:
            Path to final exported clip.
        """
        video_path = Path(video_path)
        ass_path = Path(ass_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        escaped_ass = self._sanitize_path_for_ffmpeg_filter(ass_path)
        
        # Use ass filter (or subtitles filter)
        cmd = [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(video_path),
            "-vf", f"ass='{escaped_ass}'",
            "-c:v", "libx264",
            "-threads", str(self.encoder_threads),
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ]

        logger.info(f"Burning subtitles onto {video_path.name} -> {output_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg subtitle burn failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg subtitle burn failed: {result.stderr}")

        return output_path
