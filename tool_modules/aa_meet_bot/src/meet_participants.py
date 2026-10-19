"""
Google Meet Participant Management.

Handles scraping and tracking participants in a Google Meet meeting:
- Opens/closes the People panel
- Extracts names via JavaScript accessibility tree queries
- Falls back to Playwright selectors
- Provides participant count without opening the panel

Extracted from GoogleMeetController to separate participant concerns.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from tool_modules.aa_meet_bot.src.meet_runtime import MeetControllerView

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)

_UI_KEYWORDS = (
    "mute",
    "unmute",
    "pin",
    "unpin",
    "remove",
    "more options",
    "more actions",
    "turn of",
    "turn on",
    "present",
    "presentation",
    "screen",
    "camera",
    "microphone",
    "admit",
    "deny",
    "waiting",
)

_PARTICIPANT_JS = """
() => {
    const participants = [];
    const seen = new Set();
    const uiKeywords = [
        'mute', 'unmute', 'pin', 'unpin', 'remove', 'more options',
        'more actions', 'turn of', 'turn on', 'present', 'presentation',
        'screen', 'camera', 'microphone', 'admit', 'deny', 'waiting',
        'contributors', 'in the meeting', 'waiting to join'
    ];

    function isValidName(name) {
        if (!name || name.length < 2 || name.length > 100) return false;
        const lower = name.toLowerCase();
        if (uiKeywords.some(kw => lower.includes(kw))) return false;
        if (['(you)', 'you', 'me'].includes(lower)) return false;
        if (/^\\d+$/.test(name)) return false;
        return true;
    }

    function cleanName(name) {
        name = name.replace(/\\s*\\(You\\)\\s*/g, '').trim();
        name = name.replace(/\\s*Meeting host\\s*/gi, '').trim();
        return name;
    }

    function addParticipant(name, email = null) {
        name = cleanName(name);
        if (isValidName(name) && !seen.has(name)) {
            seen.add(name);
            participants.push({ name, email });
        }
    }

    const listItems = document.querySelectorAll(
        '[role="listitem"][aria-label]'
    );
    listItems.forEach(item => {
        const name = item.getAttribute('aria-label');
        if (name) {
            addParticipant(name);
        }
    });

    if (participants.length === 0) {
        const participantItems = document.querySelectorAll(
            '[data-participant-id][aria-label]'
        );
        participantItems.forEach(item => {
            const name = item.getAttribute('aria-label');
            if (name) {
                addParticipant(name);
            }
        });
    }

    if (participants.length === 0) {
        const list = document.querySelector(
            '[role="list"][aria-label="Participants"]'
        );
        if (list) {
            const items = list.querySelectorAll(
                '[role="listitem"][aria-label]'
            );
            items.forEach(item => {
                const name = item.getAttribute('aria-label');
                if (name) {
                    addParticipant(name);
                }
            });
        }
    }

    if (participants.length === 0) {
        const region = document.querySelector(
            '[role="region"][aria-label="In call"]'
        );
        if (region) {
            const items = region.querySelectorAll(
                '[role="listitem"][aria-label]'
            );
            items.forEach(item => {
                const name = item.getAttribute('aria-label');
                if (name) {
                    addParticipant(name);
                }
            });
        }
    }

    if (participants.length === 0) {
        const participantItems = document.querySelectorAll(
            '[data-participant-id]'
        );
        participantItems.forEach(item => {
            const labeled = item.querySelector('[aria-label]');
            if (labeled) {
                const name = labeled.getAttribute('aria-label');
                if (name) {
                    addParticipant(name);
                }
            }
        });
    }

    return participants;
}
"""

_PEOPLE_PANEL_SELECTOR = (
    '[role="region"][aria-label="In call"], '
    + '[role="list"][aria-label="Participants"]'
)

_PEOPLE_BUTTON_SELECTORS = (
    "[data-avatar-count]",
    '[aria-label="Show everyone"]',
    '[aria-label="People"]',
    '[data-tooltip="Show everyone"]',
    '[role="button"][aria-label*="People" i]',
    '[role="button"][aria-label*="participant" i]',
)


def _is_valid_participant_name(name: str) -> bool:
    """Check if a string looks like a valid participant name."""
    if not name or len(name) < 2 or len(name) > 100:
        return False
    name_lower = name.lower()
    if any(keyword in name_lower for keyword in _UI_KEYWORDS):
        return False
    if name_lower in ["(you)", "you", "me"]:
        return False
    return True


def _clean_participant_name(name: str) -> str:
    """Clean up a participant name."""
    if "(You)" in name:
        name = name.replace("(You)", "").strip()
    for suffix in ["Meeting host", "Host", "Co-host", "Presentation"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name.strip()


class ParticipantMixin:
    """Participant scraping methods shared by the controller and MeetParticipants."""

    # Declared for mixins that read sibling state.
    _instance_id: Any
    page: Any
    state: Any

    async def _count_on_element(self, element) -> int | None:
        """Read a participant count from one Meet badge."""
        count_str = await element.get_attribute("data-participant-count")
        if count_str:
            return int(count_str)
        text = await element.text_content()
        if not text:
            return None
        match = re.search(r"(\d+)", text)
        if not match:
            return None
        return int(match.group(1))

    async def _count_from_selector(self, selector: str) -> int | None:
        """Return a count from one selector, or None if it is not usable."""
        try:
            element = await self.page.wait_for_selector(selector, timeout=500)
        except Exception:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: a missing badge must not stop the count scan.
            return None
        if not element:
            return None
        try:
            return await self._count_on_element(element)
        except (TypeError, ValueError):
            return None

    async def get_participant_count(self) -> int:
        """
        Get the number of participants in the meeting.

        This is a lightweight alternative to get_participants() that just
        reads the participant count from the UI without opening the panel.

        Returns:
            Number of participants, or 0 if unavailable.
        """
        if not self.page or not self.state or not self.state.joined:
            return 0
        try:
            for selector in (
                "[data-participant-count]",
                ".rua5Nb",
                '[aria-label*="participant" i]',
            ):
                count = await self._count_from_selector(selector)
                if count is not None:
                    return count
            if self.state and self.state.participants:
                return len(self.state.participants)
        except Exception as count_error:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: participant count must not kill the bot.
            logger.debug("Failed to get participant count: %s", count_error)
        return 0

    async def _people_panel_is_open(self) -> bool:
        """Return True when the People panel is already visible."""
        try:
            panel = await self.page.wait_for_selector(
                _PEOPLE_PANEL_SELECTOR, timeout=500
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: a closed panel is a normal state.
            return False
        if not panel:
            return False
        return bool(await panel.is_visible())

    async def _click_people_button(self, selector: str) -> bool:
        """Click one People-button candidate. Return True if it opened."""
        try:
            button = await self.page.wait_for_selector(selector, timeout=1000)
        except Exception:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: try the next stable selector.
            return False
        if not button or not await button.is_visible():
            return False
        await button.click()
        await asyncio.sleep(1.5)
        return True

    async def _open_people_panel(self) -> bool:
        """Open the People panel. Return True when this call opened it."""
        for selector in _PEOPLE_BUTTON_SELECTORS:
            if await self._click_people_button(selector):
                return True
        return False

    async def _append_element_name(self, participants: list[dict], element) -> None:
        """Append one aria-label when it looks like a participant name."""
        try:
            name = await element.get_attribute("aria-label")
        except Exception:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: one bad row must not drop the rest.
            return
        if not name:
            return
        name = _clean_participant_name(name)
        if not _is_valid_participant_name(name):
            return
        if any(person["name"] == name for person in participants):
            return
        participants.append({"name": name, "email": None})

    async def _append_named_elements(
        self, participants: list[dict], selector: str, failure: str
    ) -> None:
        """Collect aria-labels from one Playwright selector."""
        try:
            elements = await self.page.query_selector_all(selector)
        except Exception as scrape_error:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: a failed selector falls through to the next.
            logger.debug("%s: %s", failure, scrape_error)
            return
        for element in elements:
            await self._append_element_name(participants, element)

    async def _close_people_panel(self) -> None:
        """Close a People panel this bot opened."""
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: failing to close the panel is non-fatal.
            return

    async def _read_participant_rows(self, participants: list[dict]) -> bool:
        """Fill participants. Return True if this call opened the panel."""
        opened = False
        if not await self._people_panel_is_open():
            opened = await self._open_people_panel()
        js_participants = await self.page.evaluate(_PARTICIPANT_JS)
        if js_participants:
            participants.extend(js_participants)
            logger.debug(
                "JavaScript extraction found %s participants", len(participants)
            )
        if not participants:
            await self._append_named_elements(
                participants,
                '[role="listitem"][aria-label]',
                "Playwright fallback failed",
            )
        if not participants:
            await self._append_named_elements(
                participants,
                "[data-participant-id]",
                "data-participant-id fallback failed",
            )
        if self.state:
            self.state.participants = [person["name"] for person in participants]
        logger.info("[%s] Found %s participants", self._instance_id, len(participants))
        return opened

    async def get_participants(self) -> list[dict]:
        """
        Scrape the participant list from Google Meet UI.

        Uses accessibility attributes (aria-label, role) which are stable across
        Google's CSS obfuscation. Opens the People panel if needed, extracts
        participant names, then closes the panel.

        Returns:
            List of dicts with 'name' and optionally 'email' for each participant.
            Returns empty list if not in a meeting or scraping fails.
        """
        if not self.page or not self.state or not self.state.joined:
            return []
        participants: list[dict] = []
        panel_was_opened = False
        try:
            panel_was_opened = await self._read_participant_rows(participants)
        except Exception as scrape_error:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: participant scraping must not kill the bot.
            logger.error(
                "[%s] Failed to get participants: %s",
                self._instance_id,
                scrape_error,
            )
        finally:
            if panel_was_opened:
                await self._close_people_panel()
        return participants


class MeetParticipants(ParticipantMixin, MeetControllerView):
    """Handles participant list scraping from Google Meet."""

    def __init__(self, controller: GoogleMeetController) -> None:
        MeetControllerView.__init__(self, controller)
