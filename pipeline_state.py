"""
Live Pipeline State & Telemetry Broadcaster.
Writes real-time status, clipping stages, chat telemetry, and event history
to JSON files in storage/ so the Dashboard can render a live activity feed.
"""

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path("./storage/pipeline_state.json")
CHAT_FILE = Path("./storage/chat_telemetry.json")


class PipelineStateBroadcaster:
    """Singleton broadcaster that synchronizes live clipping activity for the dashboard."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = {
            "status": "IDLE",            # IDLE, BUFFERING, SPIKE_DETECTED, SLICING, TRANSCRIBING, VIRALITY_CHECK, FILTERED, REFRAMING, BURNING, COMPLETED
            "step": 0,                   # 0 to 6
            "total_steps": 8,
            "step_title": "Waiting for stream start...",
            "active_clip_id": None,
            "clip_progress_pct": 0,
            "last_updated": time.time(),
            "latest_spike": None,
            "buffer_info": {
                "buffered_seconds": 0,
                "total_chunks": 0,
                "latest_chunk": None
            },
            "events_feed": []
        }
        self.save_state()

    def log_event(self, event_type: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Append an event to the live activity feed."""
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "type": event_type,  # 'spike', 'clip_start', 'clip_step', 'clip_done', 'info', 'warning'
            "message": message,
            "details": details or {}
        }
        self.state["events_feed"].insert(0, entry)
        # Keep latest 50 events
        self.state["events_feed"] = self.state["events_feed"][:50]
        self.save_state()

    def update_stage(self, status: str, step: int, title: str, clip_id: Optional[str] = None):
        """Update active clipping pipeline step."""
        self.state["status"] = status
        self.state["step"] = step
        self.state["step_title"] = title
        if clip_id:
            self.state["active_clip_id"] = clip_id
        self.state["clip_progress_pct"] = int((step / self.state["total_steps"]) * 100) if step > 0 else 0
        self.state["last_updated"] = time.time()
        self.log_event("clip_step", f"[{step}/{self.state['total_steps']}] {title}")
        self.save_state()

    def record_spike(self, spike_data: Dict[str, Any]):
        """Record when chat velocity spikes above threshold."""
        self.state["status"] = "SPIKE_DETECTED"
        self.state["latest_spike"] = spike_data
        self.state["last_updated"] = time.time()
        msg = f"🔥 Spike detected! Velocity: {spike_data.get('velocity', 0):.1f} (Threshold: {spike_data.get('threshold', 0):.1f})"
        self.log_event("spike", msg, spike_data)
        self.save_state()

    def record_chat_message(self, author: str, text: str, weight: float, velocity: float, is_hype: bool):
        """Record incoming chat for live dashboard ticker."""
        if "chat_ticker" not in self.state:
            self.state["chat_ticker"] = []
        self.state["current_velocity"] = round(velocity, 1)
        self.state["chat_ticker"].insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "author": author,
            "text": text,
            "weight": round(weight, 1),
            "is_hype": is_hype
        })
        self.state["chat_ticker"] = self.state["chat_ticker"][:30]
        # Save every few messages or on hype to reduce disk I/O
        if is_hype or len(self.state["chat_ticker"]) % 3 == 0:
            self.save_state()

    def update_buffer_info(self, buffered_seconds: float, chunks_count: int, latest_chunk: str):
        """Update live buffer health stats."""
        self.state["buffer_info"] = {
            "buffered_seconds": round(buffered_seconds, 1),
            "total_chunks": chunks_count,
            "latest_chunk": latest_chunk,
            "last_updated": time.time()
        }
        self.save_state()

    def save_state(self):
        """Atomic write state to disk."""
        try:
            temp_path = STATE_FILE.with_suffix(".tmp")
            temp_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
            temp_path.replace(STATE_FILE)
        except Exception as e:
            logger.debug(f"State write failed: {e}")

    @staticmethod
    def load_state() -> Dict[str, Any]:
        """Read state from disk."""
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


broadcaster = PipelineStateBroadcaster()
