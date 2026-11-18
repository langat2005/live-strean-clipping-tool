"""
Twitch Live Chat Ingestion using twitchio or raw Twitch IRC.
Listens to live Twitch channel chat in a background thread or asyncio loop.
"""

import asyncio
import logging
import threading
import time
from typing import Optional

from chat.base import BaseChatClient, ChatMessage

logger = logging.getLogger(__name__)


class TwitchChatClient(BaseChatClient):
    """Monitors Twitch channel chat using twitchio."""

    def __init__(self, channel_name: str, oauth_token: Optional[str] = None):
        super().__init__(channel_name.strip("#").lower())
        self.oauth_token = oauth_token or "oauth:anonymous"
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._bot = None

    def _run_twitchio(self) -> None:
        try:
            from twitchio.ext import commands
        except ImportError:
            logger.error("twitchio is not installed. Please run: pip install twitchio")
            self._is_running = False
            return

        client_self = self
        channel = self.channel_or_url

        class SimpleTwitchBot(commands.Bot):
            def __init__(self):
                super().__init__(
                    token=client_self.oauth_token,
                    prefix="!",
                    initial_channels=[channel]
                )

            async def event_ready(self):
                logger.info(f"Twitch bot connected. Listening to #{channel}")

            async def event_message(self, message):
                # Avoid bot echo if applicable
                if message.echo:
                    return

                chat_msg = ChatMessage(
                    author=message.author.name if message.author else "anonymous",
                    message=message.content,
                    timestamp=time.time(),
                    platform="twitch"
                )
                client_self._dispatch_message(chat_msg)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._bot = SimpleTwitchBot()

        try:
            self._loop.run_until_complete(self._bot.start())
        except Exception as e:
            logger.info(f"Twitch bot stopped: {e}")
        finally:
            self._is_running = False

    def start(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run_twitchio, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._is_running = False
        if self._bot and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._bot.close(), self._loop)
