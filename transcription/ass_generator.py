"""
TikTok-Style Dynamic ASS Subtitle Generator.
Generates Advanced SubStation Alpha (.ass) subtitle files with word-level sequential
highlighting (e.g. glowing yellow for the active spoken word, bold white for context)
chunked into fast-paced viral short-form lines.
"""

import logging
from pathlib import Path
from typing import List, Optional

from config import SubtitleConfig, VideoFormattingConfig
from transcription.transcriber import TranscribedSegment, TranscribedWord

logger = logging.getLogger(__name__)


def format_ass_time(seconds: float) -> str:
    """Converts seconds into ASS time format: H:MM:SS.CC (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


class ASSSubtitleGenerator:
    """Generates styled ASS files from Whisper word-level timestamp outputs."""

    def __init__(
        self,
        sub_config: Optional[SubtitleConfig] = None,
        video_config: Optional[VideoFormattingConfig] = None
    ):
        self.sub_cfg = sub_config or SubtitleConfig()
        self.vid_cfg = video_config or VideoFormattingConfig()

    def _build_ass_header(self) -> str:
        """Constructs the standard ASS header with 9:16 target canvas and TikTok style."""
        play_res_x = self.vid_cfg.target_width
        play_res_y = self.vid_cfg.target_height

        header = f"""[Script Info]
Title: Dynamic Viral Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokDefault,{self.sub_cfg.font_name},{self.sub_cfg.font_size},{self.sub_cfg.primary_color},&H000000FF,{self.sub_cfg.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{self.sub_cfg.outline_width},{self.sub_cfg.shadow_depth},2,40,40,{self.sub_cfg.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        return header

    def _chunk_words(self, words: List[TranscribedWord]) -> List[List[TranscribedWord]]:
        """
        Groups words into bite-sized chunks (e.g. 2-4 words) suitable for short-form video.
        Breaks chunks early if there is a noticeable pause between words (> 0.5s).
        """
        chunks: List[List[TranscribedWord]] = []
        current_chunk: List[TranscribedWord] = []

        for word in words:
            if not current_chunk:
                current_chunk.append(word)
                continue

            prev_word = current_chunk[-1]
            pause_gap = word.start - prev_word.end

            if len(current_chunk) >= self.sub_cfg.max_words_per_line or pause_gap > 0.45:
                chunks.append(current_chunk)
                current_chunk = [word]
            else:
                current_chunk.append(word)

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def generate_ass(self, segments: List[TranscribedSegment], output_ass_path: Path) -> Path:
        """
        Builds the .ass subtitle script, creating discrete timed events for each word's highlight.
        
        Args:
            segments: Transcribed segments from Whisper.
            output_ass_path: Output file path for .ass script.
            
        Returns:
            Path to written .ass file.
        """
        output_ass_path = Path(output_ass_path)
        output_ass_path.parent.mkdir(parents=True, exist_ok=True)

        # Collect all individual words across segments
        all_words: List[TranscribedWord] = []
        for seg in segments:
            all_words.extend(seg.words)

        chunks = self._chunk_words(all_words)
        dialogue_lines: List[str] = []

        highlight_tag = f"{{\\c{self.sub_cfg.highlight_color}}}"
        normal_tag = f"{{\\c{self.sub_cfg.primary_color}}}"

        for chunk in chunks:
            if not chunk:
                continue

            # For each word in the chunk, generate an active highlight state
            for i, active_word in enumerate(chunk):
                start_t = format_ass_time(active_word.start)
                end_t = format_ass_time(active_word.end)

                # Assemble the formatted line
                formatted_words = []
                for j, w in enumerate(chunk):
                    clean_w = w.word.upper()  # Uppercase adds popular punchy aesthetic
                    if j == i:
                        formatted_words.append(f"{highlight_tag}{clean_w}{normal_tag}")
                    else:
                        formatted_words.append(clean_w)

                chunk_text = " ".join(formatted_words)
                dialogue_lines.append(
                    f"Dialogue: 0,{start_t},{end_t},TikTokDefault,,0,0,0,,{chunk_text}"
                )

        content = self._build_ass_header() + "\n".join(dialogue_lines) + "\n"
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Generated dynamic ASS subtitles ({len(dialogue_lines)} events) -> {output_ass_path.name}")
        return output_ass_path
