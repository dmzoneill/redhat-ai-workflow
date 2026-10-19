"""Shared Meet bot types and controller state.

Attribute storage lives here so GoogleMeetController can stay a thin subclass.
Other Meet helpers read protected fields through the public properties below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, ClassVar, Optional

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.virtual_devices import (
    InstanceDeviceManager,
    InstanceDevices,
)


class BrowserClosedError(Exception):
    """Raised when the browser has been closed unexpectedly."""


@dataclass
class CaptionEntry:
    """A single caption entry from the meeting."""

    speaker: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    caption_id: int = 0  # Unique ID for tracking updates
    is_update: bool = False  # True if this is an update to a previous caption

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.speaker}: {self.text}"


@dataclass
class MeetingState:  # pylint: disable=too-many-instance-attributes
    """Current state of the meeting."""

    meeting_id: str
    meeting_url: str
    joined: bool = False
    captions_enabled: bool = False
    muted: bool = True
    camera_on: bool = True
    participants: list[str] = field(default_factory=list)
    caption_buffer: list[CaptionEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ControllerStateMixin:  # pylint: disable=too-many-instance-attributes
    """Owns GoogleMeetController instance attributes.

    Subclasses must define ``_instance_counter`` and ``_instances``.
    """

    # Declared for mixins that read sibling state.
    _instance_counter: ClassVar[int]
    _instances: ClassVar[dict[str, Any]]

    def __init__(self) -> None:
        self.config = get_config()
        self.browser = None
        self.context = None
        self.page = None
        # Initialize state early so errors can be captured during initialization
        self.state: MeetingState = MeetingState(meeting_id="", meeting_url="")
        self._caption_callback: Optional[Callable[[CaptionEntry], None]] = None
        self._caption_observer_running: bool = False
        self._caption_poll_task: Optional[Any] = None
        self._playwright = None
        self._audio_sink_name: Optional[str] = None

        # Unique instance tracking
        owner = type(self)
        owner._instance_counter += 1
        self._instance_id = f"meet-bot-{owner._instance_counter}-{id(self)}"
        self._browser_pid: Optional[int] = None
        self._created_at = datetime.now()
        self._last_activity = datetime.now()

        # Per-instance audio device manager (for PULSE_SINK/PULSE_SOURCE pre-routing)
        self._device_manager: Optional[InstanceDeviceManager] = None
        self._devices: Optional[InstanceDevices] = None
        self._video_enabled = False
        self._browser_closed: bool = False

        owner._instances[self._instance_id] = self

    @property
    def instance_id(self) -> str:
        """Public view of the per-controller instance id."""
        return self._instance_id

    @property
    def audio_sink_name(self) -> Optional[str]:
        """Public view of the virtual audio sink name."""
        return self._audio_sink_name

    @audio_sink_name.setter
    def audio_sink_name(self, value: Optional[str]) -> None:
        self._audio_sink_name = value

    @property
    def browser_pid(self) -> Optional[int]:
        """Public view of the Chrome process id."""
        return self._browser_pid

    @property
    def device_manager(self) -> Optional[InstanceDeviceManager]:
        """Public view of the per-instance device manager."""
        return self._device_manager

    @property
    def devices(self) -> Optional[InstanceDevices]:
        """Public view of the per-instance virtual devices."""
        return self._devices

    @property
    def browser_closed(self) -> bool:
        """Public view of the browser-closed flag."""
        return self._browser_closed

    @browser_closed.setter
    def browser_closed(self, value: bool) -> None:
        self._browser_closed = value

    @property
    def last_activity(self) -> datetime:
        """Public view of the last-activity timestamp."""
        return self._last_activity

    @property
    def video_enabled(self) -> bool:
        """Public view of whether full video overlay is enabled."""
        return self._video_enabled


class MeetControllerView:
    """Proxy used by composition helpers so they do not touch protected fields."""

    def __init__(self, controller: ControllerStateMixin) -> None:
        self._controller = controller

    @property
    def page(self):
        """Playwright page owned by the controller."""
        return self._controller.page

    @property
    def state(self):
        """Meeting state owned by the controller."""
        return self._controller.state

    @property
    def config(self):
        """Bot config owned by the controller."""
        return self._controller.config

    @property
    def _instance_id(self) -> str:
        return self._controller.instance_id

    @property
    def _devices(self):
        return self._controller.devices

    @property
    def _browser_pid(self):
        return self._controller.browser_pid

    @property
    def _device_manager(self):
        return self._controller.device_manager

    @property
    def _audio_sink_name(self):
        return self._controller.audio_sink_name

    @_audio_sink_name.setter
    def _audio_sink_name(self, value) -> None:
        self._controller.audio_sink_name = value

    @property
    def _browser_closed(self) -> bool:
        return self._controller.browser_closed

    @_browser_closed.setter
    def _browser_closed(self, value: bool) -> None:
        self._controller.browser_closed = value

    @property
    def _video_enabled(self) -> bool:
        return self._controller.video_enabled
