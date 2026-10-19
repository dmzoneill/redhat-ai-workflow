"""
Google Meet Device Selection.

Handles selecting MeetBot virtual devices in the Google Meet UI:
- Camera selection via dropdown
- Microphone selection via dropdown
- Speaker selection via dropdown
- Programmatic device selection via JavaScript MediaDevices API

Extracted from GoogleMeetController to separate device-selection concerns.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

from tool_modules.aa_meet_bot.src.browser_controller import (
    _shared_GoogleMeetController__select_audio_device,
    _shared_GoogleMeetController__select_meetbot_camera,
    _shared_GoogleMeetController__set_devices_via_js,
)

logger = logging.getLogger(__name__)


class MeetDevices:
    """Handles device selection in Google Meet UI.

    Uses composition: receives a reference to the GoogleMeetController
    to access page, state, and device configuration.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def page(self):
        "Page."
        return self._controller.page

    @property
    def _instance_id(self):
        return self._controller._instance_id

    @property
    def _devices(self):
        return self._controller._devices

    async def select_meetbot_devices(self) -> dict:
        """
        Select all MeetBot virtual devices (camera, microphone, speaker) in Google Meet.

        This opens the device settings and selects our virtual devices to ensure
        the meeting uses our controlled audio/video pipeline.

        Returns:
            Dict with results for each device type.
        """
        results = {"camera": False, "microphone": False, "speaker": False}

        if not self.page:
            return results

        try:
            # Get the device names we're looking for
            mic_name = None
            speaker_name = None
            if self._devices:
                # The source name is what appears as microphone in Chrome
                mic_name = self._devices.source_name
                # The sink name is what appears as speaker in Chrome
                speaker_name = self._devices.sink_name
                logger.info(
                    "[DEVICES] Looking for mic: %s, speaker: %s", mic_name, speaker_name
                )

            # Step 1: Select the camera
            logger.info("[DEVICES] Selecting MeetBot camera...")
            results["camera"] = await self.select_meetbot_camera()

            # Step 2: Select the microphone
            if mic_name:
                logger.info("[DEVICES] Selecting MeetBot microphone...")
                results["microphone"] = await self._select_audio_device(
                    "microphone", mic_name
                )

            # Step 3: Select the speaker
            if speaker_name:
                logger.info("[DEVICES] Selecting MeetBot speaker...")
                results["speaker"] = await self._select_audio_device(
                    "speaker", speaker_name
                )

            logger.info("[DEVICES] Selection results: %s", results)
            return results

        except Exception as e:
            logger.warning("[DEVICES] Failed to select devices: %s", e)
            return results

    async def _select_audio_device(self, device_type: str, device_name: str) -> bool:
        return await _shared_GoogleMeetController__select_audio_device(
            self, device_type, device_name, logger=logger
        )

    _select_audio_device.__doc__ = (
        _shared_GoogleMeetController__select_audio_device.__doc__
    )

    async def select_meetbot_camera(self) -> bool:
        "Select meetbot camera."
        return await _shared_GoogleMeetController__select_meetbot_camera(
            self, logger=logger
        )

    select_meetbot_camera.__doc__ = (
        _shared_GoogleMeetController__select_meetbot_camera.__doc__
    )

    async def select_camera_in_meeting(self) -> bool:
        """Select MeetBot camera via Video settings dropdown in the meeting.

        This is used AFTER joining when camera needs to be re-enabled.
        The Video settings button opens a dropdown to select the camera.
        """
        if not self.page:
            return False

        # Retry up to 3 times with increasing delays
        for attempt in range(3):
            try:
                if attempt > 0:
                    logger.info("[CAMERA-SELECT] Retry attempt %s/3...", attempt + 1)
                    await asyncio.sleep(2.0)  # Wait before retry

                logger.info("[CAMERA-SELECT] Opening Video settings dropdown...")

                # Wait for the Video settings button to be visible and clickable
                video_settings = self.page.locator(
                    'button[aria-label="Video settings"]'
                )

                try:
                    # Wait up to 5 seconds for button to be visible
                    await video_settings.first.wait_for(state="visible", timeout=5000)
                except Exception:
                    logger.warning(
                        "[CAMERA-SELECT] Video settings button not visible (attempt %s)",
                        attempt + 1,
                    )
                    continue

                # Click with a shorter timeout
                await video_settings.first.click(timeout=5000)
                await asyncio.sleep(0.8)  # Wait for dropdown to open

                # Look for MeetBot in the dropdown menu
                meetbot_pattern = "MeetBot"

                # Try to find and click the MeetBot option
                menu_items = self.page.locator(
                    '[role="menuitem"], [role="menuitemradio"], li'
                )
                count = await menu_items.count()
                logger.info("[CAMERA-SELECT] Found %s menu items", count)

                for i in range(count):
                    try:
                        item = menu_items.nth(i)
                        text = await item.text_content(timeout=1000) or ""
                        if meetbot_pattern.lower() in text.lower():
                            logger.info(
                                "[CAMERA-SELECT] Found MeetBot option: %s", text
                            )
                            await item.click(timeout=3000)
                            await asyncio.sleep(0.5)
                            logger.info("[CAMERA-SELECT] MeetBot camera selected")
                            return True
                    except Exception:
                        continue

                # Close dropdown if we didn't find MeetBot
                logger.warning(
                    "[CAMERA-SELECT] MeetBot not found in dropdown, pressing Escape"
                )
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning("[CAMERA-SELECT] Attempt %s failed: %s", attempt + 1, e)
                # Try to close any open dropdown
                try:
                    await self.page.keyboard.press("Escape")
                except Exception as e:
                    logger.debug(
                        "Suppressed error in _select_meetbot_camera (escape key): %s", e
                    )

        logger.error("[CAMERA-SELECT] Failed to select camera after 3 attempts")
        return False

    async def set_devices_via_js(self) -> bool:
        "Set devices via js."
        return await _shared_GoogleMeetController__set_devices_via_js(
            self, logger=logger
        )

    set_devices_via_js.__doc__ = (
        _shared_GoogleMeetController__set_devices_via_js.__doc__
    )
