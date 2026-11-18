"""
Configuration module for the Live Stream Automated Clipping Tool.
Handles settings for Chat Ingestion, Spike Detection, FFmpeg Ring Buffer,
Virality Scoring, Video Framing (9:16), Transcription, and Subtitle Styling.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


@dataclass
class ChatSpikeConfig:
    """Settings for monitoring chat velocity and spike detection."""
    # Moving window duration in seconds for velocity calculation
    window_duration_seconds: float = 3.0
    
    # Velocity threshold (weighted messages per window interval) to trigger a clip
    spike_threshold: float = 8.0
    
    # Cooldown in seconds after a trigger to prevent spam/duplicate clips
    cooldown_seconds: float = 45.0
    
    # Baseline message weight
    default_message_weight: float = 1.0
    
    # Sentiment/hype keyword multiplier to prioritize viral stream moments
    hype_keywords: List[str] = field(default_factory=lambda: [
        "clip", "clutch", "wtf", "omg", "w", "lmao", "lol", "pog", "poggers",
        "holy", "insane", "huge", "gg", "no way", "lets go", "let's go",
        "sheesh", "hacker", "aimbot", "cracked", "goat"
    ])
    hype_weight_multiplier: float = 2.5


@dataclass
class RingBufferConfig:
    """Settings for the rolling FFmpeg video buffer."""
    # Base directory where rolling chunks and temporary files will reside
    buffer_dir: Path = Path("./storage/buffer")
    
    # Total rolling buffer duration kept on disk (in seconds)
    total_buffer_duration: int = 60
    
    # Individual chunk length in seconds (smaller chunks = faster extraction granularity)
    segment_time_seconds: int = 2
    
    # Clip duration extracted when a spike occurs
    clip_duration_seconds: int = 45
    
    # Pre-roll context captured before the trigger instant (seconds)
    pre_trigger_seconds: int = 15

    def __post_init__(self):
        if self.segment_time_seconds <= 0:
            raise ValueError("segment_time_seconds must be greater than zero.")
        if self.pre_trigger_seconds < 0:
            raise ValueError("pre_trigger_seconds cannot be negative.")
        if self.clip_duration_seconds <= self.pre_trigger_seconds:
            raise ValueError("clip_duration_seconds must exceed pre_trigger_seconds.")
        if self.total_buffer_duration < self.clip_duration_seconds:
            raise ValueError("total_buffer_duration must cover the complete clip.")


@dataclass
class ViralityConfig:
    """Scoring weights and sampling limits for the secondary clip filter."""
    minimum_score: float = 50.0
    scoring_whisper_model_size: str = "tiny"
    audio_weight: float = 0.4
    motion_weight: float = 0.3
    semantic_weight: float = 0.3
    audio_sample_rate: int = 8000
    audio_window_seconds: float = 0.5
    audio_peak_threshold_db: float = -18.0
    motion_sample_interval_seconds: float = 1.0
    motion_width: int = 160
    motion_height: int = 90
    engagement_keywords: List[str] = field(default_factory=lambda: [
        "wait what", "what just happened", "let's go", "lets go", "no way",
        "oh my god", "holy", "insane", "unbelievable", "that's crazy",
        "thats crazy", "clutch", "pog", "wow", "what a play"
    ])

    def __post_init__(self):
        weights = (self.audio_weight, self.motion_weight, self.semantic_weight)
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("Virality score weights must be non-negative with a positive sum.")
        if not 0 <= self.minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100.")
        if self.audio_sample_rate <= 0 or self.audio_window_seconds <= 0:
            raise ValueError("Audio sampling settings must be greater than zero.")
        if self.audio_peak_threshold_db > 0:
            raise ValueError("audio_peak_threshold_db must be zero or a negative dBFS value.")
        if self.motion_sample_interval_seconds <= 0:
            raise ValueError("motion_sample_interval_seconds must be greater than zero.")
        if self.motion_width <= 0 or self.motion_height <= 0:
            raise ValueError("Motion analysis dimensions must be greater than zero.")


@dataclass
class VideoFormattingConfig:
    """Settings for 9:16 vertical re-framing."""
    target_width: int = 1080
    target_height: int = 1920
    
    # Framing mode:
    # 'center_crop'       -> Standard 16:9 cropped to vertical center
    # 'blur_background'   -> 16:9 gameplay centered with blurred top/bottom filler
    # 'split_cam_game'    -> Top 35% facecam crop, bottom 65% gameplay crop
    framing_mode: str = "blur_background"
    
    # Custom coordinates for Facecam (x, y, width, height) relative to original 1920x1080 source
    facecam_box: Tuple[int, int, int, int] = (1440, 30, 450, 300)
    
    # Output directory for exported clips
    output_dir: Path = Path("./storage/clips")
    encoder_threads: int = 2

    def __post_init__(self):
        if self.encoder_threads <= 0:
            raise ValueError("encoder_threads must be greater than zero.")


@dataclass
class SubtitleConfig:
    """Settings for faster-whisper transcription and TikTok ASS subtitle styling."""
    whisper_model_size: str = "base"  # e.g., tiny, base, small, medium, large-v3
    device: str = "auto"              # "cuda", "cpu", or "auto"
    compute_type: str = "auto"        # "float16", "int8", or "auto"
    
    # ASS Subtitle Typography & Colors (TikTok aesthetic)
    font_name: str = "Montserrat ExtraBold"
    font_size: int = 68
    
    # Color format in ASS is &HAABBGGRR& (Hex alpha + blue + green + red)
    primary_color: str = "&H00FFFFFF&"      # Inactive context words: Solid White
    highlight_color: str = "&H0000E5FF&"    # Active word: Punchy Gold / Yellow-Amber
    outline_color: str = "&H00000000&"      # Heavy black outline
    outline_width: int = 5
    shadow_depth: int = 2
    
    # Layout & Pacing
    max_words_per_line: int = 3             # Keep short-form caption chunks bite-sized (2-4 words)
    margin_v: int = 360                     # Vertical offset from bottom (above TikTok UI buttons)
    cpu_threads: int = 4

    def __post_init__(self):
        if self.cpu_threads <= 0:
            raise ValueError("cpu_threads must be greater than zero.")


@dataclass
class AppConfig:
    """Master application configuration."""
    chat: ChatSpikeConfig = field(default_factory=ChatSpikeConfig)
    buffer: RingBufferConfig = field(default_factory=RingBufferConfig)
    formatting: VideoFormattingConfig = field(default_factory=VideoFormattingConfig)
    subtitles: SubtitleConfig = field(default_factory=SubtitleConfig)
    virality: ViralityConfig = field(default_factory=ViralityConfig)
