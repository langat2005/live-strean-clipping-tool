import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcription.transcriber import NoAudioStreamError, WhisperTranscriber


class TestWhisperTranscriber(unittest.TestCase):
    def test_video_without_audio_returns_no_transcript_without_loading_model(self):
        transcriber = WhisperTranscriber()
        missing_audio_result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Output file does not contain any stream",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "silent.mp4"
            with patch("transcription.transcriber.resolve_ffmpeg", return_value="ffmpeg"):
                with patch(
                    "transcription.transcriber.subprocess.run",
                    return_value=missing_audio_result
                ):
                    with patch.object(transcriber, "_init_model") as init_model:
                        self.assertEqual(transcriber.transcribe(video_path), [])

        init_model.assert_not_called()

    def test_non_audio_ffmpeg_errors_are_not_suppressed(self):
        transcriber = WhisperTranscriber()
        failed_result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Invalid input file",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "broken.mp4"
            with patch("transcription.transcriber.resolve_ffmpeg", return_value="ffmpeg"):
                with patch(
                    "transcription.transcriber.subprocess.run",
                    return_value=failed_result
                ):
                    with self.assertRaisesRegex(RuntimeError, "Audio extraction error"):
                        transcriber.transcribe(video_path)

    def test_extract_audio_raises_specific_error_for_audio_missing_video(self):
        transcriber = WhisperTranscriber()
        missing_audio_result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Output file does not contain any stream",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "silent.mp4"
            output_path = Path(temp_dir) / "silent.wav"
            with patch("transcription.transcriber.resolve_ffmpeg", return_value="ffmpeg"):
                with patch(
                    "transcription.transcriber.subprocess.run",
                    return_value=missing_audio_result
                ):
                    with self.assertRaises(NoAudioStreamError):
                        transcriber.extract_audio(video_path, output_path)

            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
