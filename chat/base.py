"""
Base abstractions for Chat Ingestion across various streaming platforms.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional
import time


@dataclass
class ChatMessage:
    """Represents a standardized chat message across all streaming platforms."""
    author: str
    message: str
    timestamp: float = 0.0
    platform: str = "unknown"

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


# Callback signature for message ingestion
MessageHandler = Callable[[ChatMessage], None]


class BaseChatClient(ABC):
    """Abstract Base Class for live stream chat listeners."""

    def __init__(self, channel_or_url: str):
        self.channel_or_url = channel_or_url
        self._message_handler: Optional[MessageHandler] = None
        self._is_running: bool = False

    def on_message(self, handler: MessageHandler) -> None:
        """Register the consumer callback for incoming messages."""
        self._message_handler = handler

    def _dispatch_message(self, message: ChatMessage) -> None:
        """Dispatch message to registered handler if present."""
        if self._message_handler:
            self._message_handler(message)

    @abstractmethod
    def start(self) -> None:
        """Start listening to chat asynchronously in a worker thread/task."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and close connections cleanly."""
        pass

    @property
    def is_running(self) -> bool:
        return self._is_running
