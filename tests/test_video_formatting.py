import unittest

from config import VideoFormattingConfig
from video.formatting import VideoFormatter


class TestVideoFormatter(unittest.TestCase):
    def test_split_screen_uses_30_70_vertical_layout(self):
        formatter = VideoFormatter(VideoFormattingConfig(framing_mode="split_screen"))

        graph = formatter._build_filter_graph((100, 50, 900, 480))

        self.assertIn("crop=900:480:100:50,scale=1080:576[cam]", graph)
        self.assertIn("scale=1080:1344[game]", graph)
        self.assertIn("vstack=inputs=2[outv]", graph)

    def test_split_screen_requires_facecam_crop(self):
        formatter = VideoFormatter(VideoFormattingConfig(framing_mode="split_screen"))

        with self.assertRaisesRegex(ValueError, "requires a detected facecam crop"):
            formatter._build_filter_graph()

    def test_fallback_facecam_crop_scales_and_matches_panel_aspect(self):
        formatter = VideoFormatter(VideoFormattingConfig(framing_mode="split_screen"))

        x, y, width, height = formatter._scale_fallback_facecam_box(1280, 720)

        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + width, 1280)
        self.assertLessEqual(y + height, 720)
        self.assertAlmostEqual(width / height, 1080 / 576, places=2)


if __name__ == "__main__":
    unittest.main()
