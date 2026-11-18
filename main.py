"""
Main CLI Entrypoint for the Live Stream Automated Clipping Tool.
Supports YouTube Live, Twitch, and Mock Simulation modes.
"""

import argparse
import logging
import sys
import time

from chat.mock_client import MockChatClient
from chat.twitch_client import TwitchChatClient
from chat.youtube_client import YouTubeChatClient
from config import (
    AppConfig,
    ChatSpikeConfig,
    RingBufferConfig,
    SubtitleConfig,
    VideoFormattingConfig,
    ViralityConfig,
)
from pipeline import ClippingPipeline
from stream_resolver import StreamResolver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Main")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated Live Stream Clipping & TikTok Subtitle Generator"
    )
    
    # Input modes (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", "--stream", type=str, dest="stream_input",
                       help="Direct stream URL or channel name (YouTube link, Twitch channel, or video stream)")
    group.add_argument("--youtube", type=str, help="YouTube Live video ID or URL")
    group.add_argument("--twitch", type=str, help="Twitch channel name (e.g. shroud)")
    group.add_argument("--mock", action="store_true", help="Run with synthetic chat generator for offline testing")
    
    # Stream media source for FFmpeg ring buffer
    parser.add_argument("--stream-url", type=str, default=None,
                        help="Direct HLS (.m3u8), RTMP, or local test video URL for FFmpeg ingestion")
    parser.add_argument("--audio-stream-url", type=str, default=None,
                        help="Optional separate audio URL to mux with --stream-url")
    
    # Thresholds
    parser.add_argument("--threshold", type=float, default=8.0,
                        help="Chat velocity threshold (messages per 3s window) to trigger clip")
    parser.add_argument("--cooldown", type=float, default=45.0,
                        help="Cooldown period in seconds between clips")
    parser.add_argument("--min-virality-score", "--virality-threshold",
                        dest="virality_threshold", type=float, default=50.0,
                        help="Minimum multimodal virality score (0-100) required to render a clip")
    parser.add_argument("--audio-peak-threshold-db", type=float, default=-18.0,
                        help="Minimum audio peak level in dBFS used by the virality filter")
    parser.add_argument("--scoring-whisper-model", default="tiny",
                        choices=["tiny", "base", "small"],
                        help="Fast Whisper model used only for the initial semantic filter")
    parser.add_argument("--pre-trigger-seconds", type=int, default=15,
                        help="Seconds of footage to keep before the chat spike")
    
    # Video & Subtitles
    parser.add_argument(
        "--framing",
        choices=["blur_background", "center_crop", "split_cam_game", "split_screen"],
        default="blur_background",
        help="9:16 vertical formatting style"
    )
    parser.add_argument("--whisper-model", default="base",
                        help="faster-whisper model size (tiny, base, small, medium, large-v3)")
    parser.add_argument("--clip-duration", type=int, default=45,
                        help="Total clip duration in seconds (default: 15s pre-spike + 30s after)")
    
    return parser.parse_args()


def main():
    args = parse_arguments()
    logger.info("Initializing Live Stream Engagement Clipper...")

    # Assemble configuration
    app_config = AppConfig(
        chat=ChatSpikeConfig(
            spike_threshold=args.threshold,
            cooldown_seconds=args.cooldown
        ),
        buffer=RingBufferConfig(
            clip_duration_seconds=args.clip_duration,
            pre_trigger_seconds=args.pre_trigger_seconds
        ),
        virality=ViralityConfig(
            minimum_score=args.virality_threshold,
            scoring_whisper_model_size=args.scoring_whisper_model,
            audio_peak_threshold_db=args.audio_peak_threshold_db
        ),
        formatting=VideoFormattingConfig(
            framing_mode=args.framing
        ),
        subtitles=SubtitleConfig(
            whisper_model_size=args.whisper_model
        )
    )

    # Initialize chat listener and media stream
    if args.stream_input:
        logger.info(f"Resolving stream target from input: {args.stream_input}")
        resolved = StreamResolver.resolve(args.stream_input)
        logger.info(f"Resolved platform: {resolved.platform.upper()} | Target: {resolved.chat_target}")
        
        if resolved.platform == "youtube":
            chat_client = YouTubeChatClient(resolved.chat_target)
            stream_media_url = args.stream_url or resolved.media_url
        elif resolved.platform == "twitch":
            chat_client = TwitchChatClient(resolved.chat_target)
            stream_media_url = args.stream_url or resolved.media_url
        elif resolved.platform == "mock":
            chat_client = MockChatClient("mock_streamer")
            stream_media_url = args.stream_url or resolved.media_url
        else:
            chat_client = MockChatClient("stream_viewer")
            stream_media_url = args.stream_url or resolved.media_url

        if resolved.error:
            logger.warning(f"Stream resolution notice: {resolved.error}")

    elif args.mock:
        logger.info("Operating in MOCK SIMULATION mode.")
        chat_client = MockChatClient("mock_streamer")
        stream_media_url = args.stream_url or "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"
    elif args.youtube:
        logger.info(f"Connecting to YouTube Live chat: {args.youtube}")
        chat_client = YouTubeChatClient(args.youtube)
        stream_media_url = args.stream_url or args.youtube
    elif args.twitch:
        logger.info(f"Connecting to Twitch chat: #{args.twitch}")
        chat_client = TwitchChatClient(args.twitch)
        stream_media_url = args.stream_url or f"https://twitch.tv/{args.twitch}"
    else:
        logger.error("No valid chat provider specified.")
        sys.exit(1)

    # Instantiate and start the pipeline
    pipeline = ClippingPipeline(
        config=app_config,
        chat_client=chat_client,
        stream_url=stream_media_url,
        audio_stream_url=args.audio_stream_url,
        on_clip_ready=lambda result: logger.info(f"==> Exported New Clip: {result.final_video_path}")
    )

    try:
        pipeline.start()
        logger.info("Pipeline running. Press Ctrl+C to stop.")

        if args.mock:
            # If in mock mode, trigger a demonstration burst after 8 seconds
            def demo_trigger():
                time.sleep(8)
                logger.info("Triggering simulated hype chat burst...")
                chat_client.trigger_burst(duration_seconds=5)

            import threading
            threading.Thread(target=demo_trigger, daemon=True).start()

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Interrupt received, shutting down gracefully...")
    finally:
        pipeline.stop()
        logger.info("Pipeline terminated.")


if __name__ == "__main__":
    main()
