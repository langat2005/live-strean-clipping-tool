"""
Master Pipeline Orchestrator.
Connects the Chat Monitor, FFmpeg Ring Buffer, 9:16 Re-framing,
Faster-Whisper Transcription, and Dynamic Subtitle Burn-in into an automated workflow.
"""

from dataclasses import asdict, dataclass, replace
import json
import logging
from pathlib import Path
import shutil
import threading
import time
from typing import Callable, Optional

from buffer.ring_buffer import FFmpegRollingBuffer
from chat.base import BaseChatClient
from chat.spike_detector import SpikeDetector, SpikeEvent
from config import AppConfig
from metadata_generator import ClipMetadata, MetadataGenerator
from transcription.ass_generator import ASSSubtitleGenerator
from transcription.transcriber import WhisperTranscriber
from video.burn_in import SubtitleBurner
from video.formatting import VideoFormatter
from pipeline_state import broadcaster
from virality.scorer import ViralityScorer

logger = logging.getLogger(__name__)


@dataclass
class ClipJobResult:
    """Artifacts produced by an automated clip job."""
    clip_id: str
    final_video_path: Path
    raw_video_path: Path
    ass_subtitle_path: Path
    metadata: ClipMetadata
    created_at: float


class ClippingPipeline:
    """
    End-to-end automated live stream clipping pipeline.
    
    1. Monitors chat stream for velocity spikes.
    2. Buffers continuous stream via FFmpeg ring buffer.
    3. On spike: captures a pre/post event window and transcribes it.
    4. Scores audio intensity, visual motion, and transcript semantics.
    5. Reformats approved moments to vertical 9:16 and burns captions.
    6. Exports metadata with the score breakdown.
    """

    def __init__(
        self,
        config: AppConfig,
        chat_client: BaseChatClient,
        stream_url: str,
        on_clip_ready: Optional[Callable[[ClipJobResult], None]] = None,
        audio_stream_url: Optional[str] = None
    ):
        self.config = config
        self.chat_client = chat_client
        self.stream_url = stream_url
        self.audio_stream_url = audio_stream_url
        self.on_clip_ready = on_clip_ready

        # Submodules
        self.spike_detector = SpikeDetector(
            config=config.chat,
            on_spike=self._on_spike_triggered
        )
        self.ring_buffer = FFmpegRollingBuffer(
            stream_url=stream_url,
            config=config.buffer,
            audio_stream_url=audio_stream_url
        )
        self.formatter = VideoFormatter(config=config.formatting)
        self.scoring_transcriber = WhisperTranscriber(config=replace(
            config.subtitles,
            whisper_model_size=config.virality.scoring_whisper_model_size
        ))
        self.transcriber = WhisperTranscriber(config=config.subtitles)
        self.virality_scorer = ViralityScorer(config=config.virality)
        self.ass_generator = ASSSubtitleGenerator(
            sub_config=config.subtitles,
            video_config=config.formatting
        )
        self.burner = SubtitleBurner(encoder_threads=config.formatting.encoder_threads)
        self.metadata_gen = MetadataGenerator()

        self._processing_lock = threading.Lock()
        self._is_active = False

    def _on_spike_triggered(self, spike_event: SpikeEvent) -> None:
        """Invoked asynchronously when chat velocity exceeds threshold."""
        logger.info(f"Pipeline received SpikeEvent (Velocity: {spike_event.velocity:.1f}). Scheduling clip worker...")
        broadcaster.record_spike({
            "velocity": spike_event.velocity,
            "threshold": spike_event.threshold,
            "trigger_author": spike_event.trigger_message.author,
            "trigger_message": spike_event.trigger_message.message,
            "timestamp": spike_event.timestamp,
            "keywords": spike_event.top_keywords_found
        })
        worker = threading.Thread(target=self._process_clip_event, args=(spike_event,), daemon=True)
        worker.start()

    def _process_clip_event(self, spike_event: SpikeEvent) -> Optional[ClipJobResult]:
        """Extracts a spike window, filters it, then renders approved clips."""
        post_trigger_delay = max(
            0,
            self.config.buffer.clip_duration_seconds - self.config.buffer.pre_trigger_seconds
        )
        logger.info(f"Waiting {post_trigger_delay}s to capture post-spike stream footage...")
        broadcaster.log_event("info", f"Buffering post-spike celebration ({post_trigger_delay}s window)...")
        time.sleep(post_trigger_delay)

        with self._processing_lock:
            timestamp_str = time.strftime("%Y%m%d_%H%M%S")
            clip_id = f"clip_{timestamp_str}"
            temp_dir = Path("./storage/temp") / clip_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_dir = Path(self.config.formatting.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"=== PROCESSING CLIP: {clip_id} ===")
            broadcaster.update_stage(
                "SLICING",
                1,
                f"Extracting {self.config.buffer.clip_duration_seconds}s spike window",
                clip_id
            )
            try:
                # 1. Extract raw clip from Ring Buffer
                raw_clip_path = temp_dir / "raw_cut.mp4"
                self.ring_buffer.extract_clip(
                    output_path=raw_clip_path,
                    duration_seconds=self.config.buffer.clip_duration_seconds
                )

                # 2. Run a small text-only transcript pass for semantic scoring.
                broadcaster.update_stage(
                    "TRANSCRIBING",
                    2,
                    f"Quick transcript pass ({self.config.virality.scoring_whisper_model_size})",
                    clip_id
                )
                scoring_segments = self.scoring_transcriber.transcribe(
                    raw_clip_path,
                    word_timestamps=False
                )

                # 3. Reject low-value moments before spending time on rendering.
                broadcaster.update_stage("VIRALITY_CHECK", 3, "Scoring audio, motion, and transcript", clip_id)
                virality_score = self.virality_scorer.score(raw_clip_path, scoring_segments)
                score_details = asdict(virality_score)
                logger.info(
                    "Virality score %.1f/100 (audio %.1f, motion %.1f, semantic %.1f; threshold %.1f)",
                    virality_score.total_score,
                    virality_score.audio_score,
                    virality_score.motion_score,
                    virality_score.semantic_score,
                    virality_score.threshold
                )
                broadcaster.log_event(
                    "virality_score",
                    f"Virality score: {virality_score.total_score:.1f}/100 "
                    f"({'accepted' if virality_score.accepted else 'rejected'})",
                    score_details
                )
                if not virality_score.accepted:
                    logger.info("Discarding clip %s: score is below threshold.", clip_id)
                    broadcaster.update_stage(
                        "FILTERED",
                        3,
                        f"Discarded: virality score {virality_score.total_score:.1f}/100",
                        clip_id
                    )
                    try:
                        shutil.rmtree(temp_dir)
                    except OSError as cleanup_error:
                        logger.warning("Could not remove rejected clip temp folder %s: %s", temp_dir, cleanup_error)
                    return None

                # Free the small model before loading the final transcription model.
                self.scoring_transcriber.release_model()
                broadcaster.update_stage(
                    "TRANSCRIBING",
                    4,
                    f"Word-timed captions ({self.config.subtitles.whisper_model_size})",
                    clip_id
                )
                try:
                    segments = self.transcriber.transcribe(raw_clip_path, word_timestamps=True)
                finally:
                    self.transcriber.release_model()

                # 5. Format the approved clip to vertical 9:16.
                broadcaster.update_stage(
                    "REFRAMING",
                    5,
                    f"Re-framing to vertical 9:16 ({self.config.formatting.framing_mode})",
                    clip_id
                )
                vertical_path = temp_dir / "vertical.mp4"
                self.formatter.convert_to_vertical(
                    input_path=raw_clip_path,
                    output_path=vertical_path
                )

                # 6. Generate dynamic ASS subtitles from the word-timed transcript.
                broadcaster.update_stage("BURNING", 6, "Generating dynamic ASS word captions", clip_id)
                ass_path = temp_dir / "dynamic_captions.ass"
                self.ass_generator.generate_ass(segments, ass_path)

                # 7. Burn captions into the vertical export.
                broadcaster.update_stage("BURNING", 7, "Burning captions into vertical MP4", clip_id)
                final_video_path = output_dir / f"{clip_id}_final.mp4"
                self.burner.burn_subtitles(
                    video_path=vertical_path,
                    ass_path=ass_path,
                    output_path=final_video_path
                )

                # 8. Generate viral metadata
                metadata = self.metadata_gen.generate(segments, spike_event)
                meta_path = output_dir / f"{clip_id}_meta.json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    metadata_payload = metadata.__dict__.copy()
                    metadata_payload["virality_score"] = score_details
                    json.dump(metadata_payload, f, indent=2)
                broadcaster.update_stage("COMPLETED", 8, "Generated final clip and social metadata", clip_id)

                result = ClipJobResult(
                    clip_id=clip_id,
                    final_video_path=final_video_path,
                    raw_video_path=raw_clip_path,
                    ass_subtitle_path=ass_path,
                    metadata=metadata,
                    created_at=time.time()
                )

                logger.info(f"SUCCESS: Generated viral clip at {final_video_path}")
                broadcaster.log_event("clip_done", f"🎉 Final clip ready: {final_video_path.name}", {
                    "video": str(final_video_path.name),
                    "title": metadata.title
                })
                if self.on_clip_ready:
                    self.on_clip_ready(result)

                return result

            except Exception as e:
                logger.error(f"Error processing clip {clip_id}: {e}", exc_info=True)
                broadcaster.log_event("error", f"Error processing {clip_id}: {e}")
                return None

    def start(self) -> None:
        """Starts chat listener and video ring buffer capture."""
        if self._is_active:
            return
        self._is_active = True
        logger.info("Starting Clipping Pipeline...")
        broadcaster.log_event("info", "Clipping pipeline started. Ring buffer capturing stream...")
        broadcaster.update_stage("BUFFERING", 0, "Capturing live stream into rolling ring buffer...")

        try:
            self.ring_buffer.start()
            self.ring_buffer.wait_until_buffered(
                self.config.buffer.pre_trigger_seconds,
                timeout_seconds=self.config.buffer.total_buffer_duration
            )
            self.chat_client.on_message(self.spike_detector.process_message)
            self.chat_client.start()
        except Exception:
            self._is_active = False
            self.ring_buffer.stop()
            raise

    def stop(self) -> None:
        """Halts all modules cleanly."""
        self._is_active = False
        logger.info("Stopping Clipping Pipeline...")
        broadcaster.log_event("info", "Clipping pipeline stopped.")
        broadcaster.update_stage("IDLE", 0, "Clipper stopped.")
        self.chat_client.stop()
        self.ring_buffer.stop()
