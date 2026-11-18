"""
Stream URL & Platform Resolver.
Automatically detects whether a user provided a YouTube Live URL, Twitch channel,
Kick URL, or direct media stream, and resolves the live HLS stream URL for FFmpeg
using streamlink or yt-dlp.
"""

from dataclasses import dataclass
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ResolvedStream:
    """Carries platform type, chat identifier, and direct media stream URL for FFmpeg."""
    platform: str            # 'youtube', 'twitch', 'direct', 'mock'
    chat_target: str         # channel name or youtube video id
    media_url: str           # resolved direct stream url (.m3u8 or video file)
    display_name: str
    is_live: bool = True
    error: Optional[str] = None


class StreamResolver:
    """Detects platform and resolves raw media stream URLs on the fly."""

    DEFAULT_TEST_STREAM = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"

    @classmethod
    def resolve(cls, user_input: str) -> ResolvedStream:
        """
        Parses user input string into a validated platform and direct stream URL.
        """
        text = user_input.strip()
        if not text or text.lower() in ["mock", "test", "demo", "sample"]:
            return ResolvedStream(
                platform="mock",
                chat_target="mock_streamer",
                media_url=cls.DEFAULT_TEST_STREAM,
                display_name="Mock Stream Simulation"
            )

        # 1. YouTube Live URL or Video ID
        if "youtube.com" in text or "youtu.be" in text or (len(text) == 11 and not text.startswith("http")):
            return cls._resolve_youtube(text)

        # 2. Twitch Channel URL or Channel Name
        if "twitch.tv" in text or (not text.startswith("http") and "/" not in text and "." not in text):
            return cls._resolve_twitch(text)

        # 3. Direct Video / HLS Stream (.m3u8, .mp4, rtmp, etc.)
        if any(text.endswith(ext) for ext in [".m3u8", ".mp4", ".ts", ".flv"]) or text.startswith("rtmp://"):
            return ResolvedStream(
                platform="direct",
                chat_target="mock_streamer",
                media_url=text,
                display_name="Direct Video Stream"
            )

        # Fallback: Try generic streamlink / yt-dlp resolution
        return cls._resolve_generic(text)

    @classmethod
    def _resolve_youtube(cls, text: str) -> ResolvedStream:
        """Extracts YouTube ID and resolves live stream URL."""
        video_id = text
        if "v=" in text:
            video_id = text.split("v=")[1].split("&")[0]
        elif "youtu.be/" in text:
            video_id = text.split("youtu.be/")[1].split("?")[0]
        elif "youtube.com/live/" in text:
            video_id = text.split("youtube.com/live/")[1].split("?")[0]

        target_url = f"https://www.youtube.com/watch?v={video_id}"

        # Resolve media URL using yt-dlp or streamlink
        resolved_media_url = None
        try:
            import yt_dlp
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
                resolved_media_url = info.get("url")
        except Exception as e:
            logger.debug(f"yt-dlp YouTube resolution notice: {e}")

        if not resolved_media_url:
            try:
                from streamlink.session import Streamlink
                session = Streamlink()
                streams = session.streams(target_url)
                if streams:
                    best = streams.get("best") or streams.get("720p") or list(streams.values())[0]
                    resolved_media_url = best.url
            except Exception as e:
                logger.debug(f"Streamlink YouTube resolution notice: {e}")

        if not resolved_media_url:
            return ResolvedStream(
                platform="youtube",
                chat_target=video_id,
                media_url=target_url,
                display_name=f"YouTube Live ({video_id})",
                is_live=False,
                error="Could not extract live stream HLS URL. Verify the stream is currently live."
            )

        return ResolvedStream(
            platform="youtube",
            chat_target=video_id,
            media_url=resolved_media_url,
            display_name=f"YouTube Live ({video_id})"
        )

    @classmethod
    def _resolve_twitch(cls, text: str) -> ResolvedStream:
        """Extracts Twitch channel name and resolves live HLS .m3u8 stream."""
        channel = text
        if "twitch.tv/" in text:
            channel = text.split("twitch.tv/")[1].strip("/").split("?")[0]
        channel = channel.strip("#").lower()

        twitch_url = f"https://twitch.tv/{channel}"
        resolved_media_url = None

        # Resolve using Streamlink
        try:
            from streamlink.session import Streamlink
            session = Streamlink()
            streams = session.streams(twitch_url)
            if streams:
                best = streams.get("best") or streams.get("720p") or streams.get("worst") or list(streams.values())[0]
                resolved_media_url = best.url
        except Exception as e:
            logger.debug(f"Streamlink Twitch error: {e}")

        # Fallback to yt-dlp
        if not resolved_media_url:
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                    info = ydl.extract_info(twitch_url, download=False)
                    resolved_media_url = info.get("url")
            except Exception as e:
                logger.debug(f"yt-dlp Twitch error: {e}")

        if not resolved_media_url:
            return ResolvedStream(
                platform="twitch",
                chat_target=channel,
                media_url=twitch_url,
                display_name=f"Twitch #{channel}",
                is_live=False,
                error=f"Streamer '{channel}' appears to be offline or channel does not exist."
            )

        return ResolvedStream(
            platform="twitch",
            chat_target=channel,
            media_url=resolved_media_url,
            display_name=f"Twitch #{channel}"
        )

    @classmethod
    def _resolve_generic(cls, url: str) -> ResolvedStream:
        """Fallback resolver for Kick or other platforms using yt-dlp/streamlink."""
        resolved = None
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                resolved = info.get("url")
        except Exception:
            pass

        if resolved:
            return ResolvedStream(
                platform="direct",
                chat_target="mock_streamer",
                media_url=resolved,
                display_name=f"Live Stream ({url[:30]}...)"
            )

        return ResolvedStream(
            platform="mock",
            chat_target="mock_streamer",
            media_url=cls.DEFAULT_TEST_STREAM,
            display_name="Fallback Demo Stream",
            is_live=False,
            error=f"Could not resolve live video for '{url}'. Running in test mode."
        )
