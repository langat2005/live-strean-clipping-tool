import unittest
from pathlib import Path
from types import SimpleNamespace
import wave
from unittest.mock import patch

import numpy as np

from config import ViralityConfig
from transcription.transcriber import TranscribedSegment
from virality.scorer import (
    AudioIntensityAnalyzer,
    SemanticTranscriptAnalyzer,
    ViralityScorer,
    VisualMotionAnalyzer,
)


class FixedAnalyzer:
    def __init__(self, value):
        self.value = value

    def analyze(self, _video_path):
        del _video_path
        return self.value


class TestViralityScorer(unittest.TestCase):
    def test_audio_score_detects_loudness_change_and_silence(self):
        config = ViralityConfig(audio_sample_rate=8000, audio_window_seconds=0.5)
        analyzer = AudioIntensityAnalyzer(config)
        samples = np.concatenate((
            np.full(4000, 300, dtype=np.int16),
            np.full(4000, 24000, dtype=np.int16)
        ))

        self.assertGreaterEqual(analyzer.score_samples(samples), 80)
        self.assertEqual(analyzer.score_samples(np.zeros(8000, dtype=np.int16)), 0)

    def test_audio_score_respects_configured_dbfs_threshold(self):
        samples = np.full(4000, 3277, dtype=np.int16)
        strict_analyzer = AudioIntensityAnalyzer(ViralityConfig(
            audio_sample_rate=8000,
            audio_window_seconds=0.5,
            audio_peak_threshold_db=-18.0
        ))
        permissive_analyzer = AudioIntensityAnalyzer(ViralityConfig(
            audio_sample_rate=8000,
            audio_window_seconds=0.5,
            audio_peak_threshold_db=-25.0
        ))

        self.assertEqual(strict_analyzer.score_samples(samples), 0.0)
        self.assertGreater(permissive_analyzer.score_samples(samples), 0.0)

    def test_audio_analyzer_reads_and_cleans_temporary_wav(self):
        wav_paths = []

        def fake_ffmpeg(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            wav_path = Path(command[-1])
            wav_paths.append(wav_path)
            with wave.open(str(wav_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(8000)
                wav_file.writeframes(np.full(8000, 8192, dtype=np.int16).tobytes())
            return SimpleNamespace(returncode=0, stderr="")

        analyzer = AudioIntensityAnalyzer(ViralityConfig(audio_sample_rate=8000))
        with patch("virality.scorer.resolve_ffmpeg", return_value="ffmpeg"):
            with patch("virality.scorer.subprocess.run", side_effect=fake_ffmpeg):
                score = analyzer.analyze(Path("candidate.mp4"))

        self.assertGreater(score, 0)
        self.assertEqual(len(wav_paths), 1)
        self.assertFalse(wav_paths[0].parent.exists())

    def test_motion_score_distinguishes_static_from_action(self):
        self.assertEqual(VisualMotionAnalyzer.score_differences([0.0, 0.0]), 0)
        self.assertGreater(VisualMotionAnalyzer.score_differences([0.2, 0.25]), 90)

    def test_transcript_matches_phrases_without_partial_word_matches(self):
        analyzer = SemanticTranscriptAnalyzer(ViralityConfig())
        segments = [
            TranscribedSegment(text="No way, let's go!", start=0, end=2, words=[])
        ]

        score, matches = analyzer.analyze(segments)

        self.assertEqual(score, 50)
        self.assertEqual(matches, ["let's go", "no way"])

    def test_combined_score_uses_weights_and_threshold(self):
        config = ViralityConfig(minimum_score=70)
        scorer = ViralityScorer(
            config=config,
            audio_analyzer=FixedAnalyzer(100),
            motion_analyzer=FixedAnalyzer(80)
        )
        segments = [
            TranscribedSegment(text="Let's go, no way!", start=0, end=2, words=[])
        ]

        result = scorer.score("candidate.mp4", segments)

        self.assertEqual(result.total_score, 79)
        self.assertTrue(result.accepted)
        self.assertEqual(result.matched_keywords, ["let's go", "no way"])

    def test_below_threshold_candidate_is_rejected(self):
        scorer = ViralityScorer(
            config=ViralityConfig(minimum_score=70),
            audio_analyzer=FixedAnalyzer(40),
            motion_analyzer=FixedAnalyzer(50)
        )

        result = scorer.score("candidate.mp4", [])

        self.assertLess(result.total_score, result.threshold)
        self.assertFalse(result.accepted)


if __name__ == "__main__":
    unittest.main()
