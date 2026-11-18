"""
Rolling Video Buffer Package.
"""

from buffer.ring_buffer import FFmpegRollingBuffer, VideoSegment

__all__ = ["FFmpegRollingBuffer", "VideoSegment"]
