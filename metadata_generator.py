"""
Auto-Export Metadata Module.
Generates viral titles, YouTube Shorts/TikTok tags, and descriptions from
the transcript and spike keywords using heuristic NLP / local LLM hooks.
"""

from dataclasses import dataclass
import logging
from typing import List, Optional

from chat.spike_detector import SpikeEvent
from transcription.transcriber import TranscribedSegment

logger = logging.getLogger(__name__)


@dataclass
class ClipMetadata:
    """Export metadata for publishing to social platforms."""
    title: str
    tags: List[str]
    description: str
    transcript_summary: str


class MetadataGenerator:
    """Extracts high-impact titles and hashtags based on transcript and chat sentiment."""

    def __init__(self, platform_tags: Optional[List[str]] = None):
        self.default_tags = platform_tags or [
            "#Shorts", "#Gaming", "#TwitchClips", "#TikTokGaming", "#ViralMoment", "#StreamHighlights"
        ]

    def generate(
        self,
        segments: List[TranscribedSegment],
        spike_event: Optional[SpikeEvent] = None
    ) -> ClipMetadata:
        """
        Creates catchy titles and tags.
        Integrates with local LLM or rule-based keyword extraction.
        """
        full_transcript = " ".join(seg.text for seg in segments).strip()
        
        # Determine dominant hype keywords
        spike_kws = spike_event.top_keywords_found if spike_event else []
        keyword_str = " / ".join(k.upper() for k in spike_kws[:3]) if spike_kws else "INSANE PLAY"

        # Generate catchy title
        if full_transcript:
            first_sentence = full_transcript.split(".")[0][:45]
            title = f"{keyword_str}! \"{first_sentence}...\""
        else:
            title = f"Streamer Had NO IDEA! ({keyword_str})"

        # Dynamic tags
        tags = list(self.default_tags)
        for kw in spike_kws:
            clean_tag = f"#{kw.replace(' ', '').capitalize()}"
            if clean_tag not in tags:
                tags.append(clean_tag)

        desc = (
            f"{title}\n\n"
            f"Watch the full moment live!\n"
            f"Transcript: {full_transcript}\n\n"
            f"{' '.join(tags)}"
        )

        return ClipMetadata(
            title=title,
            tags=tags,
            description=desc,
            transcript_summary=full_transcript
        )
