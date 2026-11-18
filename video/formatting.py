"""
Video Formatting & Re-framing Module.
Transforms standard 16:9 widescreen stream clips into vertical 9:16 (1080x1920)
videos tailored for TikTok, YouTube Shorts, and Instagram Reels.
"""

import logging
from pathlib import Path
import subprocess
from typing import List, Optional, Tuple

import cv2
import numpy as np
from config import VideoFormattingConfig
from ffmpeg_utils import resolve_ffmpeg

logger = logging.getLogger(__name__)


class VideoFormatter:
    """Handles aspect ratio conversion, dynamic cropping, and split-screen framing."""

    def __init__(self, config: Optional[VideoFormattingConfig] = None):
        self.config = config or VideoFormattingConfig()
        cv2.setNumThreads(1)

    def _build_filter_graph(
        self,
        facecam_box: Optional[Tuple[int, int, int, int]] = None
    ) -> str:
        """
        Builds the FFmpeg video filtergraph based on the configured framing mode.
        """
        mode = self.config.framing_mode
        target_w = self.config.target_width
        target_h = self.config.target_height

        if mode == "center_crop":
            # Center-crops the 16:9 input to 9:16 and scales to target resolution
            return f"crop=ih*(9/16):ih:(iw-ow)/2:0,scale={target_w}:{target_h}"

        elif mode == "blur_background":
            # Creates an aesthetic frosted/blurred vertical background behind centered 16:9 gameplay
            return (
                f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h},"
                f"boxblur=25:5[bg];"
                f"[0:v]scale={target_w}:-1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
            )

        elif mode in ("split_cam_game", "split_screen"):
            if mode == "split_screen" and facecam_box is None:
                raise ValueError("split_screen framing requires a detected facecam crop.")
            cam_x, cam_y, cam_w, cam_h = facecam_box or self.config.facecam_box
            cam_height = int(target_h * (0.30 if mode == "split_screen" else 0.35))
            game_height = target_h - cam_height

            return (
                f"[0:v]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},scale={target_w}:{cam_height}[cam];"
                f"[0:v]crop=ih*({target_w}/{game_height}):ih:(iw-ow)/2:0,scale={target_w}:{game_height}[game];"
                f"[cam][game]vstack=inputs=2[outv]"
            )

        else:
            raise ValueError(f"Unknown framing mode: {mode}")

    def _scale_fallback_facecam_box(
        self,
        frame_width: int,
        frame_height: int
    ) -> Tuple[int, int, int, int]:
        """Scale the configured 1920x1080 fallback crop to the input dimensions."""
        x, y, width, height = self.config.facecam_box
        x = round(x * frame_width / 1920)
        y = round(y * frame_height / 1080)
        width = max(1, round(width * frame_width / 1920))
        height = max(1, round(height * frame_height / 1080))
        x = min(max(0, x), max(0, frame_width - 1))
        y = min(max(0, y), max(0, frame_height - 1))
        width = min(width, frame_width - x)
        height = min(height, frame_height - y)
        desired_aspect = self.config.target_width / (self.config.target_height * 0.30)
        center_x = x + width / 2
        center_y = y + height / 2
        if width / height < desired_aspect:
            width = min(frame_width, round(height * desired_aspect))
        else:
            height = min(frame_height, round(width / desired_aspect))
        x = int(min(max(0, center_x - width / 2), frame_width - width))
        y = int(min(max(0, center_y - height / 2), frame_height - height))
        return x, y, width, height

    def _detect_facecam_box(self, input_path: Path) -> Tuple[int, int, int, int]:
        """Find a consistently located face and expand it into a top-panel crop."""
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        classifier = cv2.CascadeClassifier(str(cascade_path))
        if classifier.empty():
            raise FileNotFoundError(f"OpenCV face cascade was not found: {cascade_path}")

        capture = cv2.VideoCapture(str(input_path))
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"OpenCV could not open candidate video: {input_path}")

        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not np.isfinite(fps) or fps <= 0:
                fps = 30.0
            frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frame_step = max(1, int(round(fps)))
            cell_width = max(1, frame_width // 8)
            cell_height = max(1, frame_height // 8)
            detections = {}
            sampled_frame_count = 0

            def inspect_frame(frame: np.ndarray) -> None:
                nonlocal frame_width, frame_height
                nonlocal cell_width, cell_height, sampled_frame_count
                frame_height, frame_width = frame.shape[:2]
                cell_width = max(1, frame_width // 8)
                cell_height = max(1, frame_height // 8)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = classifier.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(40, 40)
                )
                for x, y, width, height in faces:
                    cell = (
                        round((x + width / 2) / cell_width),
                        round((y + height / 2) / cell_height)
                    )
                    detections.setdefault(cell, []).append((x, y, width, height))
                sampled_frame_count += 1

            if np.isfinite(frame_count) and frame_count > 0:
                max_frame = min(int(frame_count), max(1, int(fps * 12)))
                for frame_index in range(0, max_frame, frame_step):
                    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    success, frame = capture.read()
                    if success:
                        inspect_frame(frame)
            else:
                for _ in range(12):
                    success, frame = capture.read()
                    if not success:
                        break
                    inspect_frame(frame)

            if sampled_frame_count == 0 or frame_width <= 0 or frame_height <= 0:
                raise RuntimeError(f"Could not determine input dimensions for {input_path}.")

            if not detections:
                logger.warning(
                    "No face detected for split_screen; using the configured facecam region."
                )
                return self._scale_fallback_facecam_box(frame_width, frame_height)

            stable_faces: List[Tuple[int, int, int, int]] = max(
                detections.values(),
                key=lambda boxes: (len(boxes), sum(box[2] * box[3] for box in boxes))
            )
            face_x, face_y, face_width, face_height = (
                int(np.median([box[index] for box in stable_faces]))
                for index in range(4)
            )

            panel_height = int(self.config.target_height * 0.30)
            panel_aspect = self.config.target_width / panel_height
            crop_width = min(
                frame_width,
                max(face_width * 3, face_height * panel_aspect, frame_width * 0.16)
            )
            crop_height = min(frame_height, crop_width / panel_aspect)
            crop_width = min(frame_width, crop_height * panel_aspect)
            crop_height = min(frame_height, crop_width / panel_aspect)

            center_x = face_x + face_width / 2
            center_y = face_y + face_height / 2
            crop_x = int(min(max(0, center_x - crop_width / 2), frame_width - crop_width))
            crop_y = int(min(max(0, center_y - crop_height / 2), frame_height - crop_height))
            result = (crop_x, crop_y, int(crop_width), int(crop_height))
            logger.info("Detected facecam crop at %s.", result)
            return result
        finally:
            capture.release()

    def convert_to_vertical(self, input_path: Path, output_path: Path) -> Path:
        """
        Renders the input clip into vertical 9:16 format with hardware or CPU H.264 encoding.
        
        Args:
            input_path: Path to the sliced raw .mp4 clip.
            output_path: Path for the reformatted vertical video.
            
        Returns:
            Path to the vertical video file.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        facecam_box = None
        if self.config.framing_mode == "split_screen":
            facecam_box = self._detect_facecam_box(input_path)
        filtergraph = self._build_filter_graph(facecam_box)
        
        # Determine if we used named output pad [outv] or simple filter
        has_named_pad = "[outv]" in filtergraph

        cmd = [
            resolve_ffmpeg(),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(input_path),
            "-filter_complex" if has_named_pad else "-vf",
            filtergraph,
        ]

        if has_named_pad:
            cmd.extend(["-map", "[outv]", "-map", "0:a?"])

        cmd.extend([
            "-c:v", "libx264",
            "-threads", str(self.config.encoder_threads),
            "-preset", "veryfast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path)
        ])

        logger.info(f"Re-framing video to 9:16 ({self.config.framing_mode}) -> {output_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg vertical formatting failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg formatting error: {result.stderr}")

        return output_path
