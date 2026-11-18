"""
FFmpeg Rolling Ring-Buffer Module.
Continuously captures a live stream into a rolling sequence of short video chunks.
Maintains an automated segment eviction window to keep disk usage strictly bounded,
and extracts precise multi-second clip windows on demand.
"""

from dataclasses import dataclass
import glob
import logging
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import List, Optional

from config import RingBufferConfig
from ffmpeg_utils import resolve_ffmpeg

logger = logging.getLogger(__name__)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class VideoSegment:
    """Metadata tracking an individual chunk written by FFmpeg."""
    filepath: Path
    start_time: float
    duration: float


class FFmpegRollingBuffer:
    """
    Continuous ring-buffer recorder powered by FFmpeg segment muxer.
    
    Streams live media into rotating chunks (e.g. 2-second .ts segments).
    Maintains a rolling index and automatically unlinks segments older than
    the configured buffer window (e.g. 60 seconds) to prevent disk exhaustion.
    """

    def __init__(
        self,
        stream_url: str,
        config: Optional[RingBufferConfig] = None,
        audio_stream_url: Optional[str] = None
    ):
        self.stream_url = stream_url
        self.audio_stream_url = audio_stream_url
        self.config = config or RingBufferConfig()
        self.buffer_dir = Path(self.config.buffer_dir)
        
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        # Track indexed segments in chronological order
        self._segments: List[VideoSegment] = []

    def _prepare_directories(self) -> None:
        """Ensure buffer storage exists and clean up old remnants."""
        if self.buffer_dir.exists():
            shutil.rmtree(self.buffer_dir, ignore_errors=True)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)

    def _build_ffmpeg_command(self) -> List[str]:
        """
        Constructs the FFmpeg command line to ingest stream and output segmented chunks.
        '-c copy' guarantees low CPU overhead and zero transcoding latency.
        """
        segment_pattern = str(self.buffer_dir / "chunk_%06d.ts")
        command = [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel", "warning",
            "-re",  # Read stream in real-time
            "-i", self.stream_url,
        ]
        if self.audio_stream_url:
            command.extend([
                "-re", "-i", self.audio_stream_url,
                "-map", "0:v:0",
                "-map", "1:a:0",
            ])
        command.extend([
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(self.config.segment_time_seconds),
            "-reset_timestamps", "1",
            segment_pattern
        ])
        return command

    def _clean_old_segments(self, now: float) -> None:
        """Deletes video segments older than the total buffer window limit."""
        retention_window = self.config.total_buffer_duration
        cutoff_time = now - retention_window

        with self._lock:
            retained_segments = []
            for seg in self._segments:
                if seg.start_time + seg.duration < cutoff_time:
                    try:
                        if seg.filepath.exists():
                            seg.filepath.unlink()
                            logger.debug(f"Evicted aged segment: {seg.filepath.name}")
                    except OSError as e:
                        logger.warning(f"Failed to delete segment {seg.filepath}: {e}")
                else:
                    retained_segments.append(seg)
            self._segments = retained_segments

    def _segment_watcher(self) -> None:
        """
        Background worker that monitors newly completed chunk files,
        indexes their timestamps, and purges expired segments.
        """
        known_files = set()

        while not self._stop_event.is_set():
            time.sleep(1.0)
            if self._ffmpeg_process and self._ffmpeg_process.poll() is not None:
                logger.error(
                    "FFmpeg ring-buffer process exited unexpectedly with code %s.",
                    self._ffmpeg_process.returncode
                )
                self._stop_event.set()
                return
            now = time.time()
            all_chunks = sorted(glob.glob(str(self.buffer_dir / "chunk_*.ts")))

            # We treat all but the latest chunk as finalized (the latest might still be open for writing)
            if len(all_chunks) > 1:
                finalized = all_chunks[:-1]
                new_chunk_found = False
                with self._lock:
                    for chunk_str in finalized:
                        chunk_path = Path(chunk_str)
                        if chunk_path not in known_files:
                            known_files.add(chunk_path)
                            seg = VideoSegment(
                                filepath=chunk_path,
                                start_time=now - self.config.segment_time_seconds,
                                duration=float(self.config.segment_time_seconds)
                            )
                            self._segments.append(seg)
                            new_chunk_found = True

                if new_chunk_found and finalized:
                    latest = Path(finalized[-1])
                    # Update snapshot preview of live buffer feed
                    preview_img = self.buffer_dir / "live_preview.jpg"
                    try:
                        subprocess.run([
                            resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", "0.5", "-i", str(latest),
                            "-vframes", "1", "-q:v", "2",
                            str(preview_img)
                        ], timeout=3, capture_output=True)
                    except (OSError, subprocess.SubprocessError) as error:
                        logger.debug("Could not refresh live preview image: %s", error)

                    # Notify pipeline state
                    from pipeline_state import broadcaster
                    total_secs = len(self._segments) * self.config.segment_time_seconds
                    broadcaster.update_buffer_info(total_secs, len(self._segments), latest.name)

            self._clean_old_segments(now)

    @staticmethod
    def _drain_ffmpeg_stderr(process: subprocess.Popen) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.strip()
            if message:
                safe_message = _URL_PATTERN.sub("[stream URL]", message)
                logger.warning("FFmpeg capture: %s", safe_message)

    def start(self) -> None:
        """Launches FFmpeg recording subprocess and segment indexer thread."""
        self._prepare_directories()
        self._stop_event.clear()

        cmd = self._build_ffmpeg_command()
        logger.info("Starting FFmpeg ring-buffer stream capture.")
        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
        except FileNotFoundError:
            logger.exception("Could not start the configured FFmpeg executable.")
            raise

        self._stderr_thread = threading.Thread(
            target=self._drain_ffmpeg_stderr,
            args=(self._ffmpeg_process,),
            daemon=True
        )
        self._stderr_thread.start()
        self._watcher_thread = threading.Thread(target=self._segment_watcher, daemon=True)
        self._watcher_thread.start()

    def wait_until_buffered(self, required_seconds: float, timeout_seconds: float = 60.0) -> None:
        """Wait until enough finalized footage exists for a reliable pre-roll."""
        if required_seconds <= 0:
            return
        if self._ffmpeg_process is None:
            raise RuntimeError("Start the ring buffer before waiting for buffered footage.")

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            process = self._ffmpeg_process
            if process and process.poll() is not None:
                raise RuntimeError(
                    f"FFmpeg stopped before the ring buffer was ready (exit code {process.returncode})."
                )

            with self._lock:
                buffered_seconds = sum(
                    segment.duration
                    for segment in self._segments
                    if segment.filepath.exists()
                )
            if buffered_seconds >= required_seconds:
                return
            time.sleep(0.25)

        raise TimeoutError(
            f"Ring buffer did not collect {required_seconds:.1f}s of footage "
            f"within {timeout_seconds:.1f}s."
        )

    def stop(self) -> None:
        """Gracefully halts FFmpeg and terminates watcher thread."""
        self._stop_event.set()
        if self._ffmpeg_process and self._ffmpeg_process.poll() is None:
            logger.info("Terminating FFmpeg capture process...")
            self._ffmpeg_process.terminate()
            try:
                self._ffmpeg_process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                self._ffmpeg_process.kill()
        if self._stderr_thread:
            self._stderr_thread.join(timeout=1.0)
            self._stderr_thread = None
        self._ffmpeg_process = None

    def extract_clip(self, output_path: Path, duration_seconds: Optional[int] = None) -> Path:
        """
        Extracts a standalone .mp4 clip from the rolling segments.
        Combines the most recent N seconds of footage up to current time.
        
        Args:
            output_path: Destination .mp4 file path.
            duration_seconds: Clip duration (defaults to config.clip_duration_seconds).
            
        Returns:
            Path to the generated temporary clip.
        """
        target_duration = duration_seconds or self.config.clip_duration_seconds
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            if not self._segments:
                raise RuntimeError("No finalized video segments available in ring buffer yet.")

            # Calculate required segments from back to front
            selected_segments: List[VideoSegment] = []
            accumulated_time = 0.0

            for seg in reversed(self._segments):
                if seg.filepath.exists():
                    selected_segments.insert(0, seg)
                    accumulated_time += seg.duration
                    if accumulated_time >= target_duration:
                        break

            if not selected_segments:
                raise RuntimeError("No valid segment files found on disk to construct clip.")

        # Write concat demuxer file
        concat_list_file = self.buffer_dir / f"concat_{int(time.time())}.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for seg in selected_segments:
                # Use forward slashes for FFmpeg compat on Windows
                safe_path = seg.filepath.resolve().as_posix()
                f.write(f"file '{safe_path}'\n")

        # Concat segments using FFmpeg
        concat_cmd = [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-t", str(target_duration),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path)
        ]

        logger.info(f"Extracting {target_duration}s clip from {len(selected_segments)} segments -> {output_path}")
        result = subprocess.run(concat_cmd, capture_output=True, text=True)

        # Cleanup concat list
        try:
            concat_list_file.unlink(missing_ok=True)
        except Exception:
            pass

        if result.returncode != 0:
            logger.error(f"FFmpeg concat failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg clip extraction failed: {result.stderr}")

        return output_path
