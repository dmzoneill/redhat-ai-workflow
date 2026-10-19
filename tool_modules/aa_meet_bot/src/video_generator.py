"""Public video-generator API.

Implementations live in the sibling modules. This module re-exports the names
callers already import.
"""

import logging
import wave
from pathlib import Path
from typing import Optional

from tool_modules.aa_meet_bot.src.video_color import (
    GPUColorConverter,
    StreamingRenderer,
    UltraLowCPURenderer,
    bgr_to_yuyv_fast,
    rgb_to_yuyv_fast,
)
from tool_modules.aa_meet_bot.src.video_config import Attendee, VideoConfig
from tool_modules.aa_meet_bot.src.video_realtime import RealtimeVideoRenderer
from tool_modules.aa_meet_bot.src.video_research import (
    ResearchVideoGenerator,
    generate_research_video,
)
from tool_modules.aa_meet_bot.src.video_theme import get_npu_stats

logger = logging.getLogger(__name__)


class VideoResult:  # pylint: disable=too-few-public-methods,too-many-arguments,too-many-positional-arguments
    """Result of video generation."""

    def __init__(
        self,
        success: bool,
        video_path: Optional[Path] = None,
        duration_seconds: float = 0.0,
        resolution: tuple[int, int] = (1280, 720),
        fps: int = 30,
        source: str = "static",
        error: Optional[str] = None,
    ):
        self.success = success
        self.video_path = video_path
        self.duration_seconds = duration_seconds
        self.resolution = resolution
        self.fps = fps
        self.source = source
        self.error = error


class VideoGenerator:
    """Backward-compatible wrapper used by the Meet bot tools."""

    def __init__(self) -> None:
        self._initialized = False

    async def initialize(self) -> bool:
        """Mark the generator ready."""
        self._initialized = True
        return True

    async def generate_video(
        self,
        audio_path: Path,
        output_filename: Optional[str] = None,
    ) -> VideoResult:
        """Return a static-avatar result for an audio clip."""
        try:
            audio = Path(audio_path)
            if not audio.exists():
                return VideoResult(
                    success=False, error=f"Audio file not found: {audio}"
                )
            try:
                with wave.open(str(audio), "rb") as handle:
                    duration = handle.getnframes() / float(handle.getframerate())
            except (OSError, wave.Error):
                duration = 5.0
            if output_filename:
                output_path = Path(output_filename)
            else:
                output_dir = (
                    Path.home() / ".config" / "aa-workflow" / "meet_bot" / "clips"
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"response_{audio.stem}.mp4"
            return VideoResult(
                success=True,
                video_path=output_path,
                duration_seconds=duration,
                source="static",
            )
        except OSError as exc:
            logger.error("Video generation failed: %s", exc)
            return VideoResult(success=False, error=str(exc))


_video_generator: Optional[VideoGenerator] = None  # pylint: disable=invalid-name


def get_video_generator() -> VideoGenerator:
    """Get or create the global video generator instance."""
    global _video_generator  # pylint: disable=global-statement
    if _video_generator is None:
        _video_generator = VideoGenerator()
    return _video_generator


__all__ = [
    "Attendee",
    "GPUColorConverter",
    "RealtimeVideoRenderer",
    "ResearchVideoGenerator",
    "StreamingRenderer",
    "UltraLowCPURenderer",
    "VideoConfig",
    "VideoGenerator",
    "VideoResult",
    "bgr_to_yuyv_fast",
    "generate_research_video",
    "get_npu_stats",
    "get_video_generator",
    "rgb_to_yuyv_fast",
]
