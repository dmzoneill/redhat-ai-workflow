"""
Browser Controller for Google Meet.

Uses Playwright with stealth mode to:
- Join Google Meet meetings
- Enable captions
- Capture caption text via DOM observation
- Inject virtual camera/microphone

Audio Pre-Routing:
- Creates per-instance virtual audio devices BEFORE launching Chrome
- Uses PULSE_SINK/PULSE_SOURCE env vars to route audio from the start
- Prevents audio leaking to speakers before routing takes effect
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.meet_audio import AudioMixin
from tool_modules.aa_meet_bot.src.meet_captions import CaptionMixin
from tool_modules.aa_meet_bot.src.meet_devices import DeviceMixin
from tool_modules.aa_meet_bot.src.meet_participants import ParticipantMixin
from tool_modules.aa_meet_bot.src.meet_runtime import (
    BrowserClosedError,
    CaptionEntry,
    ControllerStateMixin,
    MeetingState,
)
from tool_modules.aa_meet_bot.src.meet_session import SessionMixin
from tool_modules.aa_meet_bot.src.meet_session_auth import SessionAuthMixin

# Import centralized paths
try:
    from server.paths import MEETBOT_SCREENSHOTS_DIR
except ImportError:
    # Fallback for standalone usage
    MEETBOT_SCREENSHOTS_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot" / "screenshots"

__all__ = [
    "BrowserClosedError",
    "CaptionEntry",
    "GoogleMeetController",
    "MeetingState",
    "create_meet_controller",
]


# Public methods are inherited from mixins. Linting this file by path does not
# resolve those bases, so the local public-method count stays at zero.
class GoogleMeetController(  # pylint: disable=too-few-public-methods
    ControllerStateMixin,
    AudioMixin,
    CaptionMixin,
    DeviceMixin,
    ParticipantMixin,
    SessionMixin,
    SessionAuthMixin,
):
    """Controls a Google Meet session via browser automation."""

    # CSS selectors for Google Meet elements (may need updates as Meet UI changes)
    SELECTORS = MappingProxyType(
        {
            # Join flow - buttons to join the meeting
            "join_button": (
                'button:has-text("Join now"), button:has-text("Ask to join"), '
                'div[role="button"]:has-text("Join now"), '
                'div[role="button"]:has-text("Ask to join")'
            ),
            "ask_to_join_button": ('button:has-text("Ask to join"), div[role="button"]:has-text("Ask to join")'),
            "join_now_button": ('button:has-text("Join now"), div[role="button"]:has-text("Join now")'),
            "got_it_button": 'button:has-text("Got it")',
            # Permissions dialog that appears after joining
            "mic_allowed_button": 'button:has-text("Microphone allowed")',
            "camera_mic_allowed_button": ('button:has-text("Camera and microphone allowed")'),
            "permissions_dialog_close": (
                '[aria-label="Close"], button:has-text("Close"), div[aria-label="Close dialog"]'
            ),
            # Sign in flow - Google Meet sign in button (div with role="button")
            "sign_in_button": ('div[role="button"]:has-text("Sign in"), span:has-text("Sign in")'),
            # Google login page - email input
            "google_email_input": ('#identifierId, input[name="identifier"], input[type="email"]'),
            "google_email_next": '#identifierNext, button:has-text("Next")',
            "google_password_input": 'input[type="password"], input[name="Passwd"]',
            "google_password_next": '#passwordNext, button:has-text("Next")',
            # Red Hat SSO login page
            "saml_username": '#username, input[name="username"]',
            "saml_password": '#password, input[name="password"]',
            "saml_submit": '#submit, input[name="submit"], input[type="submit"]',
            # Name input for guest join
            "name_input": 'input[aria-label="Your name"], input[placeholder*="name"]',
            # Controls
            "mute_button": ('[data-is-muted], [aria-label*="microphone"], [data-tooltip*="microphone"]'),
            "camera_button": '[aria-label*="camera"], [data-tooltip*="camera"]',
            "captions_button": ('[aria-label*="caption"], [data-tooltip*="caption"], [jsname="r8qRAd"]'),
            "leave_button": '[aria-label*="Leave"], [data-tooltip*="Leave"]',
            # Caption display - these selectors target the caption container
            "caption_container": '.a4cQT, [jsname="dsyhDe"], .iOzk7',
            "caption_text": '.CNusmb, .TBMuR, [jsname="YSxPC"]',
            "caption_speaker": ".zs7s8d, .KcIKy",
            # Meeting info
            "participant_count": "[data-participant-count], .rua5Nb",
            "meeting_title": ".u6vdEc, [data-meeting-title]",
        }
    )

    # Class-level counter for unique instance IDs
    _instance_counter: ClassVar[int] = 0
    _instances: ClassVar[dict[str, Any]] = {}

    # Directory for storing meeting screenshots
    SCREENSHOT_DIR = MEETBOT_SCREENSHOTS_DIR

    @property
    def created_at(self) -> datetime:
        """When this controller instance was created (naive local time)."""
        return self._created_at


async def create_meet_controller() -> GoogleMeetController:
    """Create and initialize a Google Meet controller."""
    controller = GoogleMeetController()
    await controller.initialize()
    return controller
