import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from chat.youtube_client import YouTubeChatClient


class TestYouTubeChatClient(unittest.TestCase):
    def test_creates_pytchat_without_worker_thread_signal_handler(self):
        live_chat = MagicMock()
        live_chat.is_alive.return_value = False
        pytchat = SimpleNamespace(create=MagicMock(return_value=live_chat))
        client = YouTubeChatClient("video-id")

        with patch.dict(sys.modules, {"pytchat": pytchat}):
            client._worker()

        pytchat.create.assert_called_once_with(
            video_id="video-id",
            interruptable=False
        )


if __name__ == "__main__":
    unittest.main()
