"""Audio, visual-motion, and transcript scoring for candidate clips."""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import subprocess
import tempfile
from typing import List, Optional, Sequence, Tuple
import wave

import cv2
import numpy as np

from config import ViralityConfig
from ffmpeg_utils import resolve_ffmpeg
from transcription.transcriber import TranscribedSegment

logger = logging.getLogger(__name__)


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


class AudioIntensityAnalyzer:
    """Measures loudness peaks and short-term changes from an extracted WAV."""

    def __init__(self, config: ViralityConfig):
        self.config = config

    def analyze(self, video_path: Path) -> float:
        with tempfile.TemporaryDirectory(prefix="clip-audio-score-") as temp_dir:
            wav_path = Path(temp_dir) / "analysis.wav"
            command = [
                resolve_ffmpeg(),
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-i", str(video_path),
                "-map", "0:a:0?",
                "-vn",
                "-ac", "1",
                "-ar", str(self.config.audio_sample_rate),
                "-c:a", "pcm_s16le",
                str(wav_path),
            ]
            try:
                result = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                    check=False
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"FFmpeg audio analysis timed out for {video_path}.") from exc

            if result.returncode != 0:
                error = result.stderr.strip()
                if "does not contain any stream" in error:
                    logger.info("No audio stream found in %s; audio score is zero.", video_path)
                    return 0.0
                raise RuntimeError(f"FFmpeg audio analysis failed: {error}")
            if not wav_path.exists() or wav_path.stat().st_size == 0:
                logger.info("No audio samples found in %s; audio score is zero.", video_path)
                return 0.0

            with wave.open(str(wav_path), "rb") as wav_file:
                if wav_file.getsampwidth() != 2:
                    raise RuntimeError("FFmpeg audio analysis expected 16-bit PCM WAV data.")
                samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
                return self.score_samples(samples, wav_file.getframerate())

    def score_samples(self, samples: np.ndarray, sample_rate: Optional[int] = None) -> float:
        """Score PCM using a configured dBFS peak threshold and short-term change."""
        if samples.size == 0:
            return 0.0

        sample_rate = sample_rate or self.config.audio_sample_rate
        window_size = max(
            1,
            int(sample_rate * self.config.audio_window_seconds)
        )
        normalized = samples.astype(np.float32) / 32768.0
        windows = [
            normalized[start:start + window_size]
            for start in range(0, normalized.size, window_size)
            if normalized[start:start + window_size].size
        ]
        rms_levels = [float(np.sqrt(np.mean(np.square(window)))) for window in windows]
        peak_levels = [float(np.max(np.abs(window))) for window in windows]
        rms_db = 20.0 * np.log10(np.maximum(rms_levels, 1e-8))
        peak_db = float(np.percentile(
            20.0 * np.log10(np.maximum(peak_levels, 1e-8)),
            95
        ))
        median_db = float(np.median(rms_db))

        if peak_db < self.config.audio_peak_threshold_db:
            return 0.0

        loudness_score = _clamp_score(
            (peak_db - self.config.audio_peak_threshold_db) * 4.0
        )
        spike_score = _clamp_score((peak_db - median_db - 5.0) * (100.0 / 15.0))
        return round(max(loudness_score, spike_score), 1)


class VisualMotionAnalyzer:
    """Samples resized grayscale frames and scores frame-to-frame motion."""

    def __init__(self, config: ViralityConfig):
        self.config = config
        cv2.setNumThreads(1)

    def analyze(self, video_path: Path) -> float:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"OpenCV could not open candidate video: {video_path}")

        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not np.isfinite(fps) or fps <= 0:
                fps = 30.0
            frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps if np.isfinite(frame_count) and frame_count > 0 else 0
            previous_frame: Optional[np.ndarray] = None
            differences: List[float] = []

            def sample_frame(frame: np.ndarray) -> None:
                nonlocal previous_frame
                nonlocal differences
                small_frame = cv2.resize(
                    frame,
                    (self.config.motion_width, self.config.motion_height),
                    interpolation=cv2.INTER_AREA
                )
                gray_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
                if previous_frame is not None:
                    difference = cv2.absdiff(gray_frame, previous_frame)
                    differences.append(float(np.mean(difference) / 255.0))
                previous_frame = gray_frame

            if duration > 0:
                timestamps = np.arange(
                    0.0,
                    duration,
                    self.config.motion_sample_interval_seconds
                )
                for timestamp in timestamps:
                    capture.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
                    success, frame = capture.read()
                    if success:
                        sample_frame(frame)
            else:
                sample_every = max(
                    1,
                    int(round(fps * self.config.motion_sample_interval_seconds))
                )
                frame_index = 0
                while True:
                    success, frame = capture.read()
                    if not success:
                        break
                    if frame_index % sample_every == 0:
                        sample_frame(frame)
                    frame_index += 1

            if previous_frame is None:
                raise RuntimeError(f"OpenCV could not decode any frames from {video_path}.")
            return self.score_differences(differences)
        finally:
            capture.release()

    @staticmethod
    def score_differences(differences: Sequence[float]) -> float:
        if not differences:
            return 0.0
        upper_quartile_motion = float(np.percentile(differences, 75))
        return round(_clamp_score((upper_quartile_motion - 0.01) * (100.0 / 0.14)), 1)


class SemanticTranscriptAnalyzer:
    """Scores transcript phrases that commonly indicate audience excitement."""

    def __init__(self, config: ViralityConfig):
        self._patterns = [
            (
                keyword,
                re.compile(
                    r"(?<!\w)" + r"\s+".join(
                        re.escape(part) for part in keyword.casefold().split()
                    ) + r"(?!\w)"
                )
            )
            for keyword in config.engagement_keywords
            if keyword.strip()
        ]

    def analyze(self, segments: Sequence[TranscribedSegment]) -> Tuple[float, List[str]]:
        transcript = " ".join(segment.text for segment in segments).casefold()
        matched = [
            keyword
            for keyword, pattern in self._patterns
            if pattern.search(transcript)
        ]
        return round(min(100.0, len(matched) * 25.0), 1), matched


@dataclass(frozen=True)
class ViralityScore:
    audio_score: float
    motion_score: float
    semantic_score: float
    total_score: float
    threshold: float
    accepted: bool
    matched_keywords: List[str]


class ViralityScorer:
    """Combines the three analysis signals into a configurable 0-100 score."""

    def __init__(
        self,
        config: Optional[ViralityConfig] = None,
        audio_analyzer: Optional[AudioIntensityAnalyzer] = None,
        motion_analyzer: Optional[VisualMotionAnalyzer] = None,
        transcript_analyzer: Optional[SemanticTranscriptAnalyzer] = None
    ):
        self.config = config or ViralityConfig()
        self.audio_analyzer = audio_analyzer or AudioIntensityAnalyzer(self.config)
        self.motion_analyzer = motion_analyzer or VisualMotionAnalyzer(self.config)
        self.transcript_analyzer = transcript_analyzer or SemanticTranscriptAnalyzer(self.config)

    def score(self, video_path: Path, segments: Sequence[TranscribedSegment]) -> ViralityScore:
        audio_score = self.audio_analyzer.analyze(video_path)
        motion_score = self.motion_analyzer.analyze(video_path)
        semantic_score, matched_keywords = self.transcript_analyzer.analyze(segments)

        weight_total = (
            self.config.audio_weight
            + self.config.motion_weight
            + self.config.semantic_weight
        )
        total_score = (
            audio_score * self.config.audio_weight
            + motion_score * self.config.motion_weight
            + semantic_score * self.config.semantic_weight
        ) / weight_total
        total_score = round(total_score, 1)

        return ViralityScore(
            audio_score=audio_score,
            motion_score=motion_score,
            semantic_score=semantic_score,
            total_score=total_score,
            threshold=self.config.minimum_score,
            accepted=total_score >= self.config.minimum_score,
            matched_keywords=matched_keywords
        )
