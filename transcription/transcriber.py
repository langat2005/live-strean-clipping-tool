"""
Transcription Module using faster-whisper.
Extracts clean audio from clips and yields word-level timestamps.
"""

from dataclasses import dataclass
import gc
import logging
from pathlib import Path
import subprocess
from typing import List, Optional

from config import SubtitleConfig
from ffmpeg_utils import resolve_ffmpeg

logger = logging.getLogger(__name__)


@dataclass
class TranscribedWord:
    """Represents an individual spoken word and its exact time boundaries."""
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscribedSegment:
    """Represents a spoken sentence/phrase along with its constituent words."""
    text: str
    start: float
    end: float
    words: List[TranscribedWord]


class NoAudioStreamError(RuntimeError):
    """Raised when a source video has no audio stream to transcribe."""


class WhisperTranscriber:
    """Handles audio extraction and word-level speech transcription."""

    def __init__(self, config: Optional[SubtitleConfig] = None):
        self.config = config or SubtitleConfig()
        self._model = None

    def _init_model(self):
        """Lazy-loads the faster-whisper model on first transcription call."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                logger.error("faster-whisper is not installed. Please run: pip install faster-whisper")
                raise

            device = self.config.device
            compute_type = self.config.compute_type

            # Auto-detect CUDA availability if device="auto"
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            if compute_type == "auto":
                compute_type = "float16" if device == "cuda" else "int8"

            logger.info(f"Loading faster-whisper ({self.config.whisper_model_size}) on {device} ({compute_type})...")
            self._model = WhisperModel(
                self.config.whisper_model_size,
                device=device,
                compute_type=compute_type,
                cpu_threads=self.config.cpu_threads,
                num_workers=1
            )

    def extract_audio(self, video_path: Path, output_audio_path: Optional[Path] = None) -> Path:
        """
        Extracts high-fidelity 16kHz mono WAV from the video container for Whisper.
        """
        video_path = Path(video_path)
        if output_audio_path is None:
            output_audio_path = video_path.with_suffix(".wav")
        else:
            output_audio_path = Path(output_audio_path)

        cmd = [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_audio_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if output_audio_path.exists():
                try:
                    output_audio_path.unlink()
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove incomplete audio file %s: %s",
                        output_audio_path,
                        cleanup_error
                    )

            if "does not contain any stream" in result.stderr.lower():
                raise NoAudioStreamError(
                    f"No audio stream is present in {video_path}."
                )
            logger.error(f"FFmpeg audio extraction failed: {result.stderr}")
            raise RuntimeError(f"Audio extraction error: {result.stderr}")

        return output_audio_path

    def transcribe(
        self,
        video_path: Path,
        word_timestamps: bool = True
    ) -> List[TranscribedSegment]:
        """
        Transcribes the video audio, returning phrase segments with word-level timings.
        """
        try:
            audio_path = self.extract_audio(video_path)
        except NoAudioStreamError as error:
            logger.warning("%s Skipping speech transcription and captions.", error)
            return []

        self._init_model()

        try:
            logger.info(f"Running faster-whisper transcription on: {audio_path.name}")
            segments, _ = self._model.transcribe(
                str(audio_path),
                word_timestamps=word_timestamps,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            results: List[TranscribedSegment] = []
            for seg in segments:
                words = [
                    TranscribedWord(
                        word=w.word.strip(),
                        start=w.start,
                        end=w.end,
                        probability=w.probability
                    )
                    for w in (seg.words or [])
                    if w.word.strip()
                ]

                results.append(TranscribedSegment(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    words=words
                ))

            logger.info(f"Transcription complete: {len(results)} dialogue segments extracted.")
            return results

        finally:
            # Clean up intermediate WAV file
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass

    def release_model(self) -> None:
        """Release model memory after an accepted clip has been processed."""
        self._model = None
        gc.collect()
