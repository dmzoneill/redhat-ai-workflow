"""Overlay renderer that uses the shared realtime drawing mixins."""

from tool_modules.aa_meet_bot.src.video_config import Attendee, VideoConfig
from tool_modules.aa_meet_bot.src.video_draw import RealtimeDrawMixin
from tool_modules.aa_meet_bot.src.video_frame import RealtimeFrameMixin

__all__ = [
    "Attendee",
    "RealtimeDrawMixin",
    "RealtimeFrameMixin",
    "VideoConfig",
    "VideoOverlayRenderer",
]


class VideoOverlayRenderer(  # pylint: disable=too-few-public-methods
    RealtimeDrawMixin, RealtimeFrameMixin
):
    """CPU overlay helpers backed by the live draw and frame mixins."""

    def __init__(self, config: VideoConfig | None = None) -> None:
        self.__dict__["config"] = config or VideoConfig()
