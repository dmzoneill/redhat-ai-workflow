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
        """
        Start capturing captions via DOM observation.

        Args:
            callback: Function to call with each new caption entry.
        """
        if not self.page or self._caption_observer_running:
            return

        self._caption_callback = callback
        self._caption_observer_running = True

        # Inject DEBOUNCED caption observer with UPDATE-IN-PLACE support
        # Google Meet corrects text in-place, so we:
        # 1. Wait for text to "settle" (800ms no changes)
        # 2. Use UPDATE mode for refinements of the same utterance (not new entries)
        # 3. Only create NEW entries when speaker changes or it's clearly a new sentence
        await self.page.evaluate(
            """
            () => {
                window._meetBotCaptions = [];
                window._meetBotCurrentSpeaker = 'Unknown';
                window._meetBotLastText = '';
                window._meetBotDebounceTimer = null;
                window._meetBotLastEmittedText = '';
                window._meetBotLastEmittedId = null;  // Track ID for updates
                window._meetBotLastSpeakerForText = 'Unknown';
                window._meetBotCaptionIdCounter = 0;

                function findCaptionContainer() {
                    // Try multiple selectors for the caption container
                    return document.querySelector('[aria-label="Captions"]') ||
                           document.querySelector('.a4cQT') ||
                           document.querySelector('[jsname="dsyhDe"]');
                }

                function findCaptionTextDiv(container) {
                    if (!container) return null;
                    const divs = container.querySelectorAll('div');
                    let bestDiv = null;
                    let bestLen = 0;
                    for (const div of divs) {
                        if (div.querySelector('button, img')) continue;
                        const text = div.textContent || '';
                        if (text.length > bestLen && !text.includes('Jump to')) {
                            bestLen = text.length;
                            bestDiv = div;
                        }
                    }
                    return bestDiv;
                }

                function getSpeaker(container) {
                    if (!container) return null;

                    // Method 1: Look for speaker name near avatar image
                    const img = container.querySelector('img');
                    if (img) {
                        // Check parent and siblings for name
                        let parent = img.parentElement;
                        for (let i = 0; i < 3 && parent; i++) {
                            const spans = parent.querySelectorAll('span');
                            for (const span of spans) {
                                const t = span.textContent.trim();
                                // Name should be reasonable length, not contain common UI text
                                if (t && t.length > 1 && t.length < 50 &&
                                    !t.includes('Jump') && !t.includes('caption') &&
                                    !t.includes('English') && !t.includes('Live')) {
                                    return t;
                                }
                            }
                            parent = parent.parentElement;
                        }
                    }

                    // Method 2: Look for speaker class patterns
                    const speakerEl = container.querySelector('.zs7s8d, .KcIKyf, [data-speaker-name]');
                    if (speakerEl) {
                        const t = speakerEl.textContent.trim();
                        if (t && t.length > 1 && t.length < 50) return t;
                    }

                    return null;
                }

                // Normalize text for comparison (lowercase, collapse whitespace)
                function normalizeText(text) {
                    return (text || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                }

                // Check if newText is a refinement of oldText (same utterance, just corrected/extended)
                function isRefinement(oldText, newText) {
                    if (!oldText) return false;
                    const oldNorm = normalizeText(oldText);
                    const newNorm = normalizeText(newText);

                    // Same text (case correction only)
                    if (oldNorm === newNorm) return true;

                    // New text starts with old text (extension)
                    if (newNorm.startsWith(oldNorm)) return true;

                    // Old text starts with new text (correction that shortened)
                    if (oldNorm.startsWith(newNorm)) return true;

                    // Check if they share a significant common prefix (>60% of shorter)
                    const minLen = Math.min(oldNorm.length, newNorm.length);
                    let commonLen = 0;
                    for (let i = 0; i < minLen; i++) {
                        if (oldNorm[i] === newNorm[i]) commonLen++;
                        else break;
                    }
                    if (commonLen > minLen * 0.6) return true;

                    return false;
                }

                function emitCaption() {
                    const text = window._meetBotLastText;
                    const speaker = window._meetBotLastSpeakerForText || window._meetBotCurrentSpeaker || 'Unknown';

                    if (!text) return;

                    // Check if this is a refinement of the last emitted caption
                    const lastEmitted = window._meetBotLastEmittedText;
                    const lastId = window._meetBotLastEmittedId;

                    if (lastId !== null && isRefinement(lastEmitted, text)) {
                        // UPDATE existing caption instead of creating new one
                        window._meetBotCaptions.push({
                            id: lastId,
                            speaker: speaker,
                            text: text,
                            ts: Date.now(),
                            isUpdate: true  // Signal to update, not append
                        });
                        console.log('[MeetBot] Caption UPDATED:', speaker, text.substring(0, 50));
                    } else {
                        // NEW caption entry
                        const newId = ++window._meetBotCaptionIdCounter;
                        window._meetBotCaptions.push({
                            id: newId,
                            speaker: speaker,
                            text: text,
                            ts: Date.now(),
                            isUpdate: false
                        });
                        window._meetBotLastEmittedId = newId;
                        console.log('[MeetBot] Caption NEW:', speaker, text.substring(0, 50));
                    }
                    window._meetBotLastEmittedText = text;
                }

                const observer = new MutationObserver((mutations) => {
                    const container = findCaptionContainer();
                    if (!container) return;

                    // Always try to get the current speaker
                    const speaker = getSpeaker(container);
                    if (speaker) {
                        window._meetBotCurrentSpeaker = speaker;
                        // Store the speaker associated with the current text being built
                        window._meetBotLastSpeakerForText = speaker;
                    }

                    const captionDiv = findCaptionTextDiv(container);
                    if (!captionDiv) return;

                    const fullText = (captionDiv.textContent || '').trim();
                    if (!fullText) return;

                    // Detect speaker change - force new caption
                    const lastSpeaker = window._meetBotLastSpeakerForText;
                    if (speaker && lastSpeaker && speaker !== lastSpeaker) {
                        // Speaker changed - emit previous caption and start fresh
                        if (window._meetBotDebounceTimer) {
                            clearTimeout(window._meetBotDebounceTimer);
                            emitCaption();
                        }
                        window._meetBotLastEmittedText = '';
                        window._meetBotLastEmittedId = null;
                        window._meetBotLastSpeakerForText = speaker;
                    }

                    // Text changed - reset debounce timer
                    window._meetBotLastText = fullText;

                    if (window._meetBotDebounceTimer) {
                        clearTimeout(window._meetBotDebounceTimer);
                    }

                    // Wait 400ms of no changes before emitting (allows corrections to settle)
                    // Reduced from 800ms for faster wake word detection
                    window._meetBotDebounceTimer = setTimeout(emitCaption, 400);
                });

                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    characterData: true
                });

                window._meetBotObserver = observer;
                console.log('[MeetBot] Caption observer started (800ms debounce, update-in-place mode)');
            }
        """
        )

        # Start polling for new captions (track task for cleanup)
        self._caption_poll_task = asyncio.create_task(self._poll_captions())
        logger.info("Caption capture started")

    async def _poll_captions(self) -> None:
        """Poll for settled/corrected captions from the JS observer buffer."""
        # Track caption IDs to their index in buffer for updates
        caption_id_to_index: dict[int, int] = {}

        while self._caption_observer_running and self.page:
            try:
                # Fetch and clear the caption buffer - these are already debounced/corrected
                captions = await self.page.evaluate(
                    """
                    () => {
                        const c = window._meetBotCaptions || [];
                        window._meetBotCaptions = [];
                        return c;
                    }
                """
                )

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
                await self.page.evaluate(
                    """
                    () => {
                        if (window._meetBotObserver) {
                            window._meetBotObserver.disconnect();
                        }
                    }
                """
                )
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
