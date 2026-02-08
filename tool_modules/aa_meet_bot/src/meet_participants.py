"""
Google Meet Participant Management.

Handles scraping and tracking participants in a Google Meet meeting:
- Opens/closes the People panel
- Extracts names via JavaScript accessibility tree queries
- Falls back to Playwright selectors
- Provides participant count without opening the panel

Extracted from GoogleMeetController to separate participant concerns.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)


class MeetParticipants:
    """Handles participant list scraping from Google Meet.

    Uses composition: receives a reference to the GoogleMeetController
    to access page and state.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def page(self):
        return self._controller.page

    @property
    def state(self):
        return self._controller.state

    @property
    def _instance_id(self):
        return self._controller._instance_id

    async def get_participants(self) -> list[dict]:  # noqa: C901
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

        participants = []
        panel_was_opened = False

        # Words that indicate UI elements, not participant names
        ui_keywords = [
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
        ]

        def is_valid_name(name: str) -> bool:
            """Check if a string looks like a valid participant name."""
            if not name or len(name) < 2 or len(name) > 100:
                return False
            name_lower = name.lower()
            # Filter out UI element labels
            if any(kw in name_lower for kw in ui_keywords):
                return False
            # Filter out strings that are just "(You)" or similar
            if name_lower in ["(you)", "you", "me"]:
                return False
            return True

        def clean_name(name: str) -> str:
            """Clean up a participant name."""
            # Remove "(You)" suffix for self
            if "(You)" in name:
                name = name.replace("(You)", "").strip()
            # Remove "Meeting host" or similar suffixes
            for suffix in ["Meeting host", "Host", "Co-host", "Presentation"]:
                if name.endswith(suffix):
                    name = name[: -len(suffix)].strip()
            return name.strip()

        try:
            # First check if People panel is already open by looking for the
            # participant list container (uses stable aria-label)
            panel_open = False
            try:
                # Look for the "In call" region which contains participants
                panel = await self.page.wait_for_selector(
                    '[role="region"][aria-label="In call"], '
                    '[role="list"][aria-label="Participants"]',
                    timeout=500,
                )
                if panel and await panel.is_visible():
                    panel_open = True
            except Exception as e:
                logger.debug(f"Suppressed error in get_participants (panel check): {e}")

            # If panel not open, click the People button to open it
            if not panel_open:
                # Use only stable attributes (aria-*, data-*, role) - NOT generated class names
                people_button_selectors = [
                    "[data-avatar-count]",  # Badge showing participant avatars
                    '[aria-label="Show everyone"]',
                    '[aria-label="People"]',
                    '[data-tooltip="Show everyone"]',
                    '[role="button"][aria-label*="People" i]',
                    '[role="button"][aria-label*="participant" i]',
                ]

                for selector in people_button_selectors:
                    try:
                        btn = await self.page.wait_for_selector(selector, timeout=1000)
                        if btn and await btn.is_visible():
                            await btn.click()
                            panel_was_opened = True
                            await asyncio.sleep(1.5)  # Wait for panel animation
                            break
                    except Exception:
                        continue

            # Primary method: Use JavaScript to extract from accessibility tree
            # This is the most reliable as it uses stable ARIA attributes
            js_participants = await self.page.evaluate(
                """
                () => {
                    const participants = [];
                    const seen = new Set();

                    // UI keywords to filter out (lowercase)
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
                        // Filter out numbers only (like "2" for participant count)
                        if (/^\\d+$/.test(name)) return false;
                        return true;
                    }

                    function cleanName(name) {
                        // Remove "(You)" suffix
                        name = name.replace(/\\s*\\(You\\)\\s*/g, '').trim();
                        // Remove "Meeting host" suffix
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

                    // ALL METHODS USE STABLE ATTRIBUTES ONLY (aria-*, data-*, role)
                    // NEVER use generated class names like .zWGUib, .fdZ55, etc.

                    // Method 1 (BEST): role="listitem" with aria-label contains the name
                    // Example: <div role="listitem" aria-label="David O Neill" ...>
                    const listItems = document.querySelectorAll('[role="listitem"][aria-label]');
                    listItems.forEach(item => {
                        const name = item.getAttribute('aria-label');
                        if (name) {
                            addParticipant(name);
                        }
                    });

                    // Method 2: data-participant-id elements have aria-label with name
                    if (participants.length === 0) {
                        const participantItems = document.querySelectorAll('[data-participant-id][aria-label]');
                        participantItems.forEach(item => {
                            const name = item.getAttribute('aria-label');
                            if (name) {
                                addParticipant(name);
                            }
                        });
                    }

                    // Method 3: Find participant list by aria-label="Participants"
                    if (participants.length === 0) {
                        const list = document.querySelector('[role="list"][aria-label="Participants"]');
                        if (list) {
                            const items = list.querySelectorAll('[role="listitem"][aria-label]');
                            items.forEach(item => {
                                const name = item.getAttribute('aria-label');
                                if (name) {
                                    addParticipant(name);
                                }
                            });
                        }
                    }

                    // Method 4: Find the "In call" region and extract from listitems
                    if (participants.length === 0) {
                        const region = document.querySelector('[role="region"][aria-label="In call"]');
                        if (region) {
                            const items = region.querySelectorAll('[role="listitem"][aria-label]');
                            items.forEach(item => {
                                const name = item.getAttribute('aria-label');
                                if (name) {
                                    addParticipant(name);
                                }
                            });
                        }
                    }

                    // Method 5: data-participant-id without aria-label - check nested aria-label
                    if (participants.length === 0) {
                        const participantItems = document.querySelectorAll('[data-participant-id]');
                        participantItems.forEach(item => {
                            // Look for nested element with aria-label
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
            )

            if js_participants:
                participants = js_participants
                logger.debug(
                    f"JavaScript extraction found {len(participants)} participants"
                )

            # Fallback: Try Playwright selectors if JS extraction failed
            if not participants:
                try:
                    # Use role-based selectors
                    elements = await self.page.query_selector_all(
                        '[role="listitem"][aria-label]'
                    )
                    for el in elements:
                        try:
                            name = await el.get_attribute("aria-label")
                            if name:
                                name = clean_name(name)
                                if is_valid_name(name):
                                    if not any(p["name"] == name for p in participants):
                                        participants.append(
                                            {"name": name, "email": None}
                                        )
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Playwright fallback failed: {e}")

            # Secondary fallback: data-participant-id elements
            if not participants:
                try:
                    elements = await self.page.query_selector_all(
                        "[data-participant-id]"
                    )
                    for el in elements:
                        try:
                            name = await el.get_attribute("aria-label")
                            if name:
                                name = clean_name(name)
                                if is_valid_name(name):
                                    if not any(p["name"] == name for p in participants):
                                        participants.append(
                                            {"name": name, "email": None}
                                        )
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"data-participant-id fallback failed: {e}")

            # Update state with participant list
            if self.state:
                self.state.participants = [p["name"] for p in participants]

            logger.info(f"[{self._instance_id}] Found {len(participants)} participants")

        except Exception as e:
            logger.error(f"[{self._instance_id}] Failed to get participants: {e}")

        finally:
            # Close the panel if we opened it
            if panel_was_opened:
                try:
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.3)  # Brief wait for panel to close
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in get_participants (panel close): {e}"
                    )

        return participants

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
            # Try to find participant count in the UI
            count_selectors = [
                "[data-participant-count]",
                ".rua5Nb",  # Participant count badge
                '[aria-label*="participant" i]',
            ]

            for selector in count_selectors:
                try:
                    el = await self.page.wait_for_selector(selector, timeout=500)
                    if el:
                        # Try data attribute first
                        count_str = await el.get_attribute("data-participant-count")
                        if count_str:
                            return int(count_str)

                        # Try text content
                        text = await el.text_content()
                        if text:
                            # Extract number from text like "5 participants" or just "5"
                            import re

                            match = re.search(r"(\d+)", text)
                            if match:
                                return int(match.group(1))
                except Exception:
                    continue

            # Fallback: count from state if we've scraped before
            if self.state and self.state.participants:
                return len(self.state.participants)

        except Exception as e:
            logger.debug(f"Failed to get participant count: {e}")

        return 0
