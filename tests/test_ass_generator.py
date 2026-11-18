"""
Unit tests for ASS Subtitle Generator (time formatting, chunking, and highlight tags).
"""

from pathlib import Path
import unittest

from config import SubtitleConfig, VideoFormattingConfig
from transcription.ass_generator import ASSSubtitleGenerator, format_ass_time
from transcription.transcriber import TranscribedSegment, TranscribedWord


class TestASSGenerator(unittest.TestCase):
    def test_format_ass_time(self):
        """Test conversion of seconds to ASS H:MM:SS.CC timestamp."""
        self.assertEqual(format_ass_time(0.0), "0:00:00.00")
        self.assertEqual(format_ass_time(12.34), "0:00:12.34")
        self.assertEqual(format_ass_time(65.5), "0:01:05.50")
        self.assertEqual(format_ass_time(3661.05), "1:01:01.05")

    def test_generate_ass_content(self):
        """Test generation of ASS header and sequential highlight tags."""
        sub_cfg = SubtitleConfig(
            font_name="Montserrat ExtraBold",
            primary_color="&H00FFFFFF&",
            highlight_color="&H0000E5FF&",
            max_words_per_line=3
        )
        vid_cfg = VideoFormattingConfig(target_width=1080, target_height=1920)
        generator = ASSSubtitleGenerator(sub_config=sub_cfg, video_config=vid_cfg)

        segments = [
            TranscribedSegment(
                text="What an insane clutch",
                start=1.0,
                end=2.8,
                words=[
                    TranscribedWord(word="What", start=1.0, end=1.3, probability=0.99),
                    TranscribedWord(word="an", start=1.3, end=1.5, probability=0.98),
                    TranscribedWord(word="insane", start=1.5, end=2.0, probability=0.97),
                    TranscribedWord(word="clutch", start=2.0, end=2.8, probability=0.99)
                ]
            )
        ]

        test_out = Path("./storage/test_output.ass")
        try:
            generator.generate_ass(segments, test_out)
            self.assertTrue(test_out.exists())

            content = test_out.read_text(encoding="utf-8")
            self.assertIn("PlayResX: 1080", content)
            self.assertIn("PlayResY: 1920", content)
            self.assertIn("Style: TikTokDefault,Montserrat ExtraBold", content)
            self.assertIn(r"{\c&H0000E5FF&}WHAT{\c&H00FFFFFF&}", content)
            self.assertIn(r"{\c&H0000E5FF&}INSANE{\c&H00FFFFFF&}", content)
            self.assertIn("Dialogue: 0,0:00:01.00,0:00:01.30", content)
        finally:
            if test_out.exists():
                test_out.unlink()


if __name__ == "__main__":
    unittest.main()
