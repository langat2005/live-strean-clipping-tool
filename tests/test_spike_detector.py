"""
Unit tests for Chat Spike Detector (collections.deque sliding window,
velocity calculation, keyword weighting, and cooldowns).
"""

import time
import unittest

from chat.base import ChatMessage
from chat.spike_detector import SpikeDetector, SpikeEvent
from config import ChatSpikeConfig


class TestSpikeDetector(unittest.TestCase):
    def setUp(self):
        self.config = ChatSpikeConfig(
            window_duration_seconds=3.0,
            spike_threshold=6.0,
            cooldown_seconds=10.0,
            hype_weight_multiplier=2.5
        )
        self.triggered_events = []
        self.detector = SpikeDetector(
            config=self.config,
            on_spike=lambda evt: self.triggered_events.append(evt)
        )

    def test_baseline_chat_below_threshold(self):
        """Verify normal low-frequency chat does not trigger a spike."""
        now = time.time()
        for i in range(3):
            msg = ChatMessage(author="User", message="hi", timestamp=now + (i * 0.5))
            event = self.detector.process_message(msg)
            self.assertIsNone(event)

        self.assertEqual(len(self.triggered_events), 0)
        self.assertLess(self.detector.get_velocity(), self.config.spike_threshold)

    def test_hype_burst_triggers_spike(self):
        """Verify rapid hype keywords spike velocity above threshold and trigger callback."""
        now = time.time()
        # Send 3 rapid messages with hype words: "clutch", "omg", "wtf"
        # Each gets 1.0 * 2.5 = 2.5 weight. 3 * 2.5 = 7.5 > threshold 6.0
        msgs = [
            ChatMessage(author="User1", message="OMG WHAT A PLAY", timestamp=now),
            ChatMessage(author="User2", message="INSANE CLUTCH", timestamp=now + 0.1),
            ChatMessage(author="User3", message="WTF NO WAY", timestamp=now + 0.2),
        ]

        event = None
        for m in msgs:
            res = self.detector.process_message(m)
            if res:
                event = res

        self.assertIsNotNone(event)
        self.assertEqual(len(self.triggered_events), 1)
        self.assertGreaterEqual(event.velocity, 6.0)
        self.assertIn("clutch", [k.lower() for k in event.top_keywords_found])

    def test_cooldown_suppresses_subsequent_spikes(self):
        """Verify cooldown prevents spam triggers within the cooldown window."""
        now = time.time()
        
        # 1st spike
        for i in range(5):
            self.detector.process_message(
                ChatMessage(author="User", message="WTF CLUTCH", timestamp=now + (i * 0.05))
            )
        self.assertEqual(len(self.triggered_events), 1)

        # 2nd burst right after (within 10s cooldown)
        for i in range(5):
            self.detector.process_message(
                ChatMessage(author="User", message="INSANE HYPE", timestamp=now + 2.0 + (i * 0.05))
            )
        # Should still be 1 due to cooldown
        self.assertEqual(len(self.triggered_events), 1)

        # 3rd burst after cooldown elapsed
        for i in range(5):
            self.detector.process_message(
                ChatMessage(author="User", message="LETS GOOO", timestamp=now + 12.0 + (i * 0.05))
            )
        # Should now be 2
        self.assertEqual(len(self.triggered_events), 2)

    def test_stale_window_pruning(self):
        """Verify messages older than window_duration_seconds are evicted from deque."""
        t0 = 1000.0
        # Send 2 messages at t0
        self.detector.process_message(ChatMessage(author="A", message="hi", timestamp=t0))
        self.detector.process_message(ChatMessage(author="B", message="hi", timestamp=t0 + 0.5))
        
        self.assertEqual(len(self.detector._window_queue), 2)

        # Send 1 message at t0 + 4.0s (exceeds 3.0s window)
        self.detector.process_message(ChatMessage(author="C", message="hi", timestamp=t0 + 4.0))

        # First 2 messages must have been evicted, only 1 message remains in deque
        self.assertEqual(len(self.detector._window_queue), 1)
        self.assertEqual(self.detector._window_queue[0][2].author, "C")


if __name__ == "__main__":
    unittest.main()
