import os
import unittest
from unittest.mock import patch

from ffmpeg_utils import resolve_ffmpeg, resolve_ffprobe


class TestResolveFFmpeg(unittest.TestCase):
    def test_invalid_override_raises_actionable_error(self):
        with patch.dict(os.environ, {"FFMPEG_PATH": "missing-ffmpeg-executable"}):
            with patch("ffmpeg_utils.shutil.which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "FFMPEG_PATH"):
                    resolve_ffmpeg()

    def test_invalid_ffprobe_override_raises_actionable_error(self):
        with patch.dict(os.environ, {"FFPROBE_PATH": "missing-ffprobe-executable"}):
            with patch("ffmpeg_utils.shutil.which", return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, "FFPROBE_PATH"):
                    resolve_ffprobe()


if __name__ == "__main__":
    unittest.main()
