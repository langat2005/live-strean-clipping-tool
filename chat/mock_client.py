"""
Mock Chat Client for offline testing, simulations, and validation.
Generates baseline chatter and simulates controllable engagement spikes.
"""

import logging
import random
import threading
import time
from typing import List, Optional

from chat.base import BaseChatClient, ChatMessage

logger = logging.getLogger(__name__)


class MockChatClient(BaseChatClient):
    """Generates synthetic chat messages with baseline rates and burst modes."""

    def __init__(self, channel_name: str = "mock_streamer"):
        super().__init__(channel_name)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._burst_active = threading.Event()
        
        self.usernames: List[str] = [
            "GamerX", "NinjaLover", "Vortex99", "PixelQueen", "SlayerPro",
            "ChillDude", "NoScope360", "ApexLegend", "ShadowRider", "StreamFan"
        ]
        
        self.normal_phrases: List[str] = [
            "hello everyone", "what game is this?", "nice play", "music is good",
            "how long have you been streaming?", "back from lunch", "gg", "w play"
        ]
        
        self.hype_phrases: List[str] = [
            "YOOOO WHAT A CLUTCH!!", "WTF WAS THAT?!?!", "CLIP THAT NOW!!",
            "OMG NO WAY", "LETS GOOOOOO", "SHEESH", "HOLY CRACKED", "POGGERS",
            "HACKER CONFIRMED LMAO", "INSANE FLICK"
        ]

    def trigger_burst(self, duration_seconds: float = 4.0) -> None:
        """Simulate an sudden burst of hype chat messages."""
        def burst_timer():
            logger.info(">>> MOCK CHAT BURST STARTED <<<")
            self._burst_active.set()
            time.sleep(duration_seconds)
            self._burst_active.clear()
            logger.info(">>> MOCK CHAT BURST ENDED <<<")

        threading.Thread(target=burst_timer, daemon=True).start()

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            author = random.choice(self.usernames)
            if self._burst_active.is_set():
                msg_text = random.choice(self.hype_phrases)
                sleep_delay = random.uniform(0.05, 0.18)  # Rapid 6-15 msgs/sec
            else:
                msg_text = random.choice(self.normal_phrases)
                sleep_delay = random.uniform(0.7, 2.5)   # Calm 0.5-1.5 msgs/sec

            msg = ChatMessage(
                author=author,
                message=msg_text,
                timestamp=time.time(),
                platform="mock"
            )
            self._dispatch_message(msg)
            time.sleep(sleep_delay)

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._is_running = False
