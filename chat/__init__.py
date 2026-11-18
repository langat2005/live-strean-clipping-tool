"""
Chat Ingestion and Spike Detection Package.
"""

from chat.base import BaseChatClient, ChatMessage, MessageHandler
from chat.spike_detector import SpikeDetector, SpikeEvent, SpikeCallback
from chat.youtube_client import YouTubeChatClient
from chat.twitch_client import TwitchChatClient
from chat.mock_client import MockChatClient

__all__ = [
    "BaseChatClient",
    "ChatMessage",
    "MessageHandler",
    "SpikeDetector",
    "SpikeEvent",
    "SpikeCallback",
    "YouTubeChatClient",
    "TwitchChatClient",
    "MockChatClient"
]
