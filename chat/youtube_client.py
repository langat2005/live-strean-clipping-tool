"""
YouTube Live Chat Ingestion using pytchat.
Streams live chat messages from a YouTube video ID or URL in a dedicated thread.
"""

import logging
import threading
import time
from typing import Optional

from chat.base import BaseChatClient, ChatMessage

logger = logging.getLogger(__name__)


class YouTubeChatClient(BaseChatClient):
    """Monitors YouTube Live stream chat via pytchat."""

    def __init__(self, video_id_or_url: str):
        super().__init__(video_id_or_url)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._live_chat = None

    def _extract_video_id(self, input_val: str) -> str:
        """Extracts 11-character video ID if a full URL was passed."""
        if "v=" in input_val:
            return input_val.split("v=")[1].split("&")[0]
        elif "youtu.be/" in input_val:
            return input_val.split("youtu.be/")[1].split("?")[0]
        return input_val

    def _worker(self) -> None:
        video_id = self._extract_video_id(self.channel_or_url)
        logger.info(f"Starting YouTube chat worker for video ID: {video_id}")
        
        try:
            import pytchat
            self._live_chat = pytchat.create(video_id=video_id, interruptable=False)
        except ImportError:
            logger.error("pytchat is not installed. Please run: pip install pytchat")
            self._is_running = False
            return
        except Exception as e:
            logger.error(f"Failed to initialize pytchat: {e}")
            self._is_running = False
            return

        while not self._stop_event.is_set() and self._live_chat.is_alive():
            try:
                for c in self._live_chat.get().sync_items():
                    msg = ChatMessage(
                        author=c.author.name,
                        message=c.message,
                        timestamp=time.time(),
                        platform="youtube"
                    )
                    self._dispatch_message(msg)
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Error fetching YouTube chat: {e}")
                time.sleep(1.0)

        self._is_running = False
        logger.info("YouTube chat listener terminated.")

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._live_chat:
            try:
                self._live_chat.terminate()
            except Exception:
                pass
        self._is_running = False
