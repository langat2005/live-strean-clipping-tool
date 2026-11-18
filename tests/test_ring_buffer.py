import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from buffer.ring_buffer import FFmpegRollingBuffer, VideoSegment


class TestFFmpegRollingBufferCommand(unittest.TestCase):
    def test_command_maps_separate_video_and_audio_inputs(self):
        buffer = FFmpegRollingBuffer(
            stream_url="video.m3u8",
            audio_stream_url="audio.m3u8"
        )

        command = buffer._build_ffmpeg_command()

        self.assertIn("video.m3u8", command)
        self.assertIn("audio.m3u8", command)
        self.assertEqual(command[command.index("-map") + 1], "0:v:0")
        audio_map_index = command.index("-map", command.index("-map") + 1)
        self.assertEqual(command[audio_map_index + 1], "1:a:0")

    def test_command_keeps_single_input_behavior(self):
        buffer = FFmpegRollingBuffer(stream_url="video.m3u8")

        command = buffer._build_ffmpeg_command()

        self.assertEqual(command.count("-i"), 1)
        self.assertNotIn("-map", command)

    def test_wait_until_buffered_returns_when_pre_roll_is_available(self):
        with TemporaryDirectory() as temp_dir:
            segment_path = Path(temp_dir) / "chunk.ts"
            segment_path.touch()
            buffer = FFmpegRollingBuffer(stream_url="video.m3u8")
            buffer._ffmpeg_process = Mock(poll=Mock(return_value=None))
            buffer._segments.append(VideoSegment(segment_path, 0, 15))

            buffer.wait_until_buffered(15, timeout_seconds=0.1)

    def test_wait_until_buffered_times_out_when_pre_roll_is_missing(self):
        buffer = FFmpegRollingBuffer(stream_url="video.m3u8")
        buffer._ffmpeg_process = Mock(poll=Mock(return_value=None))

        with self.assertRaises(TimeoutError):
            buffer.wait_until_buffered(15, timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
