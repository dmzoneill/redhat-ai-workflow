"""
Google Meet Caption Capture.

Handles caption capture via DOM observation:
- Injects JavaScript MutationObserver into the meeting page
- Debounces caption text to wait for corrections to settle
- Supports update-in-place for refined captions
- Polls for new captions and dispatches via callback

Extracted from GoogleMeetController to separate caption concerns.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

from tool_modules.aa_meet_bot.src.browser_controller import (
    _shared_GoogleMeetController_start_caption_capture,
)

logger = logging.getLogger(__name__)


MAX_CAPTION_BUFFER = 10000


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


class MeetCaptions:
    """Handles caption capture from Google Meet via DOM observation.

    Uses composition: receives a reference to the GoogleMeetController
    to access page and state.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller
        self._caption_callback: Optional[Callable[[CaptionEntry], None]] = None
        self._caption_observer_running = False
        self._caption_poll_task: Optional[asyncio.Task] = None

    @property
    def page(self):
        return self._controller.page

    @property
    def state(self):
        return self._controller.state

    @property
    def _instance_id(self):
        return self._controller._instance_id

    async def start_caption_capture(
        self, callback: Callable[[CaptionEntry], None]
    ) -> None:
        return await _shared_GoogleMeetController_start_caption_capture(
            self, callback, logger=logger
        )

    start_caption_capture.__doc__ = (
        _shared_GoogleMeetController_start_caption_capture.__doc__
    )

    async def _poll_captions(self) -> None:
        """Poll for settled/corrected captions from the JS observer buffer."""
        # Track caption IDs to their index in buffer for updates
        caption_id_to_index: dict[int, int] = {}

        while self._caption_observer_running and self.page:
            try:
                # Fetch and clear the caption buffer - these are already debounced/corrected
                captions = await self.page.evaluate("""
                    () => {
                        const c = window._meetBotCaptions || [];
                        window._meetBotCaptions = [];
                        return c;
                    }
                """)

                for cap in captions:
                    speaker = cap.get("speaker", "Unknown")
                    text = cap.get("text", "")
                    ts = cap.get("ts", 0)
                    cap_id = cap.get("id", 0)
                    is_update = cap.get("isUpdate", False)

                    if not text.strip():
                        continue

                    # Determine if this is truly an update (JS says update AND we've seen this ID before)
                    is_true_update = is_update and cap_id in caption_id_to_index

                    entry = CaptionEntry(
                        speaker=speaker,
                        text=text.strip(),
                        timestamp=(
                            datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
                        ),
                        caption_id=cap_id,
                        is_update=is_true_update,
                    )

                    if entry.is_update:
                        # UPDATE existing caption in buffer
                        idx = caption_id_to_index[cap_id]
                        if self.state and 0 <= idx < len(self.state.caption_buffer):
                            self.state.caption_buffer[idx] = entry
                            logger.debug(f"Caption UPDATE [{speaker}] {text[:50]}...")
                        # Also notify callback with updated entry (for live display)
                        if self._caption_callback:
                            self._caption_callback(entry)
                    else:
                        # NEW caption entry
                        if self.state:
                            caption_id_to_index[cap_id] = len(self.state.caption_buffer)
                            self.state.caption_buffer.append(entry)
                            # Trim old entries when buffer exceeds max size
                            if len(self.state.caption_buffer) > MAX_CAPTION_BUFFER:
                                trim_count = (
                                    len(self.state.caption_buffer) - MAX_CAPTION_BUFFER
                                )
                                self.state.caption_buffer = self.state.caption_buffer[
                                    trim_count:
                                ]
                                # Rebuild index mapping after trim
                                caption_id_to_index = {
                                    e.caption_id: i
                                    for i, e in enumerate(self.state.caption_buffer)
                                }
                        if self._caption_callback:
                            self._caption_callback(entry)
                        logger.debug(f"Caption NEW [{speaker}] {text[:50]}...")

                await asyncio.sleep(0.5)  # Poll every 500ms

            except Exception as e:
                error_msg = str(e)
                # Detect browser/page closure
                if (
                    "Target closed" in error_msg
                    or "Target page, context or browser has been closed" in error_msg
                    or "Browser has been closed" in error_msg
                ):
                    logger.warning(
                        f"[Caption poll] Browser closed detected: {error_msg}"
                    )
                    self._controller._browser_closed = True
                    if self.state:
                        self.state.joined = False
                    break
                logger.debug(f"Caption poll error: {e}")
                await asyncio.sleep(1)

    async def stop_caption_capture(self) -> None:
        """Stop capturing captions."""
        self._caption_observer_running = False
        self._caption_callback = None

        # Cancel the polling task if it exists
        if self._caption_poll_task and not self._caption_poll_task.done():
            self._caption_poll_task.cancel()
            try:
                await asyncio.wait_for(self._caption_poll_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._caption_poll_task = None

        if self.page:
            try:
                await self.page.evaluate("""
                    () => {
                        if (window._meetBotObserver) {
                            window._meetBotObserver.disconnect();
                        }
                    }
                """)
            except Exception as e:
                logger.debug(
                    f"Suppressed error in stop_caption_capture (observer disconnect): {e}"
                )

        logger.info("Caption capture stopped")

    async def get_captions(self) -> list[CaptionEntry]:
        """Get all captured captions."""
        if self.state:
            return self.state.caption_buffer.copy()
        return []
