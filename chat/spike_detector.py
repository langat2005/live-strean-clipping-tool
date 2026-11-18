"""
Chat Spike Detection Module.
Tracks chat velocity using a sliding time-window (collections.deque), applies
sentiment/hype keyword weighting, and enforces cooldowns between clip triggers.
"""

from collections import deque
from dataclasses import dataclass
import logging
import time
from typing import Callable, Deque, List, Optional, Tuple

from chat.base import ChatMessage
from config import ChatSpikeConfig

logger = logging.getLogger(__name__)


@dataclass
class SpikeEvent:
    """Carries context about the detected chat engagement surge."""
    timestamp: float
    velocity: float
    threshold: float
    trigger_message: ChatMessage
    window_duration: float
    top_keywords_found: List[str]


# Callback signature for when a spike trigger fires
SpikeCallback = Callable[[SpikeEvent], None]


class SpikeDetector:
    """
    Real-time rolling-window velocity calculator and trigger mechanism.
    
    Uses collections.deque to store (timestamp, weight, message) entries.
    Evicts stale records in O(1) amortized time per incoming message.
    """

    def __init__(self, config: Optional[ChatSpikeConfig] = None, on_spike: Optional[SpikeCallback] = None):
        self.config = config or ChatSpikeConfig()
        self.on_spike_callback = on_spike

        # Queue storing: (timestamp, weighted_score, message_obj, matched_keywords)
        self._window_queue: Deque[Tuple[float, float, ChatMessage, List[str]]] = deque()
        
        # State tracking
        self.last_trigger_time: float = 0.0
        self.current_velocity: float = 0.0
        self.total_messages_processed: int = 0
        
        # Telemetry history for dashboards: stores (timestamp, velocity)
        self.velocity_history: Deque[Tuple[float, float]] = deque(maxlen=300)

    def _evaluate_message_weight(self, text: str) -> Tuple[float, List[str]]:
        """
        Calculates the message weight based on presence of viral hype keywords.
        Multipliers prevent generic spam/bots while prioritizing authentic excitement.
        """
        text_lower = text.lower()
        matched_keywords = []

        for kw in self.config.hype_keywords:
            if kw in text_lower:
                matched_keywords.append(kw)

        weight = self.config.default_message_weight
        if matched_keywords:
            # Scale weight by multiplier and boost if multiple distinct hype words appear
            weight *= self.config.hype_weight_multiplier * (1.0 + 0.2 * (len(matched_keywords) - 1))

        return weight, matched_keywords

    def _prune_stale_messages(self, now: float) -> None:
        """Evicts messages that fall outside the active sliding window."""
        cutoff_time = now - self.config.window_duration_seconds
        while self._window_queue and self._window_queue[0][0] < cutoff_time:
            self._window_queue.popleft()

    def process_message(self, message: ChatMessage) -> Optional[SpikeEvent]:
        """
        Ingests a new chat message, updates moving-window velocity,
        and triggers a clipping event if threshold is exceeded and cooldown has elapsed.
        """
        now = message.timestamp or time.time()
        self.total_messages_processed += 1

        weight, matched_keywords = self._evaluate_message_weight(message.message)
        self._window_queue.append((now, weight, message, matched_keywords))
        
        # Maintain window
        self._prune_stale_messages(now)

        # Calculate current velocity: sum of weighted messages within the window
        total_window_weight = sum(entry[1] for entry in self._window_queue)
        self.current_velocity = total_window_weight

        # Record for graphing
        self.velocity_history.append((now, self.current_velocity))

        # Update live dashboard chat telemetry
        try:
            from pipeline_state import broadcaster
            broadcaster.record_chat_message(
                author=message.author,
                text=message.message,
                weight=weight,
                velocity=self.current_velocity,
                is_hype=bool(matched_keywords)
            )
        except Exception:
            pass

        # Check for spike trigger
        spike_event: Optional[SpikeEvent] = None
        if self.current_velocity >= self.config.spike_threshold:
            time_since_last_trigger = now - self.last_trigger_time

            if time_since_last_trigger >= self.config.cooldown_seconds:
                # Aggregate matched hype keywords in this spike window
                active_keywords = list({
                    kw for entry in self._window_queue for kw in entry[3]
                })

                spike_event = SpikeEvent(
                    timestamp=now,
                    velocity=self.current_velocity,
                    threshold=self.config.spike_threshold,
                    trigger_message=message,
                    window_duration=self.config.window_duration_seconds,
                    top_keywords_found=active_keywords
                )

                self.last_trigger_time = now
                logger.info(
                    f"[SPIKE DETECTED] Velocity: {self.current_velocity:.1f} "
                    f"(Threshold: {self.config.spike_threshold}) | Triggered by '{message.author}': '{message.message}'"
                )

                if self.on_spike_callback:
                    try:
                        self.on_spike_callback(spike_event)
                    except Exception as exc:
                        logger.error(f"Error executing on_spike callback: {exc}", exc_info=True)
            else:
                logger.debug(
                    f"Spike threshold reached ({self.current_velocity:.1f}) but suppressed by cooldown "
                    f"({time_since_last_trigger:.1f}s / {self.config.cooldown_seconds}s)"
                )

        return spike_event

    def get_velocity(self) -> float:
        """Returns the current moving-window chat velocity, pruning stale entries if idle."""
        self._prune_stale_messages(time.time())
        self.current_velocity = sum(entry[1] for entry in self._window_queue)
        return self.current_velocity
