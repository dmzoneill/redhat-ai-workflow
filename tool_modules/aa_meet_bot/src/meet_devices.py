"""
Google Meet Device Selection.

Handles selecting MeetBot virtual devices in the Google Meet UI:
- Camera selection via dropdown
- Microphone selection via dropdown
- Speaker selection via dropdown
- Programmatic device selection via JavaScript MediaDevices API

Extracted from GoogleMeetController to separate device-selection concerns.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING

from tool_modules.aa_meet_bot.src.meet_runtime import MeetControllerView

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)


class DeviceMixin:
    """Device-selection methods shared by the controller and MeetDevices."""

    async def _select_audio_device(
        self,
        device_type: str,
        device_name: str,  # pylint: disable=unused-argument
    ) -> bool:
        """
        Select an audio device (microphone or speaker) in Google Meet's UI.

        Args:
            device_type: "microphone" or "speaker"
            device_name: The PulseAudio device name to look for (e.g., "MeetBot_meet_bot_1_...")

        Returns:
            True if device was selected, False otherwise.
        """
        # device_name is part of the fixed call signature. Selection matches
        # the MeetBot label in Chrome, which is what Meet exposes in the menu.
        if not self.page:
            return False
        return await self._select_audio_device_ui(device_type)

    async def _select_audio_device_ui(self, device_type: str) -> bool:
        """Open the Meet device menu and click the MeetBot entry."""
        try:
            # Map device_type to WebRTC device kind
            kind = "audioinput" if device_type == "microphone" else "audiooutput"

            # First, find the device in the browser's device list
            js_find_device = f"""
            async () => {{
                const devices = await navigator.mediaDevices.enumerateDevices();
                const matches = devices.filter(d => d.kind === '{kind}');
                console.log('Available {device_type}s:', matches.map(d => d.label));
                // Look for MeetBot device
                const meetbot = matches.find(d => d.label.includes('MeetBot'));
                return meetbot ? {{ label: meetbot.label, deviceId: meetbot.deviceId }} : null;
            }}
            """
            device_info = await self.page.evaluate(js_find_device)

            if not device_info:
                logger.info("[AUDIO] MeetBot %s not found in browser", device_type)
                return False

            device_label = device_info.get("label", "")
            logger.info("[AUDIO] Found MeetBot %s: %s", device_type, device_label)

            # Step 1: Open the appropriate dropdown using aria-label (stable attribute)
            if device_type == "microphone":
                dropdown_selector = 'button[aria-label^="Microphone:"]'
            else:  # speaker
                dropdown_selector = 'button[aria-label^="Speaker:"]'

            try:
                dropdown_btn = self.page.locator(dropdown_selector)
                if await dropdown_btn.count() > 0:
                    await dropdown_btn.first.click()
                    logger.info(
                        "[AUDIO] Opened %s dropdown via: %s",
                        device_type,
                        dropdown_selector,
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.info(
                        "[AUDIO] Could not find %s dropdown button", device_type
                    )
                    return False
            # Meet UI boundary: page or callback failures must not kill the bot.
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.info("[AUDIO] Could not open %s dropdown: %s", device_type, e)
                return False

            # Step 2: Wait for dropdown menu to appear
            await asyncio.sleep(0.3)

            # Step 3: Find and click the MeetBot option using stable selectors
            # Structure: li[role="menuitemradio"] > ... > span[jsname="K4r5F"] contains device name
            is_speaker = device_type == "speaker"
            js_click_option = """
            async (args) => {
                const { searchText, excludeMic } = args;
                // Find all menu items with role="menuitemradio" and data-device-id
                const menuItems = document.querySelectorAll(
                    'li[role="menuitemradio"][data-device-id]'
                );

                for (const item of menuItems) {
                    // Get the device name from span[jsname="K4r5F"]
                    const nameSpan = item.querySelector('span[jsname="K4r5Ff"]');
                    if (!nameSpan) continue;

                    const deviceName = nameSpan.textContent || '';

                    // Check if this is a MeetBot device
                    if (!deviceName.includes(searchText)) continue;

                    // For speaker, exclude microphone entries (those ending with _Mic)
                    if (excludeMic && deviceName.includes('_Mic')) continue;

                    // Check if visible
                    const rect = item.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        item.click();
                        return {
                            success: true,
                            deviceName: deviceName,
                            deviceId: item.getAttribute('data-device-id')
                        };
                    }
                }

                // Debug: list all visible menu items
                const allNames = Array.from(menuItems).map(item => {
                    const span = item.querySelector('span[jsname="K4r5Ff"]');
                    return span ? span.textContent : 'no-name';
                });

                return {
                    success: false,
                    error: 'MeetBot device not found in menu',
                    availableDevices: allNames
                };
            }
            """
            js_result = await self.page.evaluate(
                js_click_option, {"searchText": "MeetBot", "excludeMic": is_speaker}
            )
            if js_result and js_result.get("success"):
                logger.info(
                    "[AUDIO] Selected %s: %s", device_type, js_result.get("deviceName")
                )
                await asyncio.sleep(0.5)
                return True

            logger.info("[AUDIO] %s selection failed: %s", device_type, js_result)

            # Close dropdown if we couldn't select
            await self.page.keyboard.press("Escape")
            logger.info(
                "[AUDIO] MeetBot %s found but couldn't click in UI", device_type
            )
            return False

        # Meet UI boundary: page or callback failures must not kill the bot.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("[AUDIO] Failed to select %s: %s", device_type, e)
            return False

    def _v4l2_card_type(self) -> str | None:
        """Read the v4l2 card type for the MeetBot camera, if any."""
        if not self._devices or not self._devices.video_device:
            return None
        result = subprocess.run(
            ["v4l2-ctl", "--device", self._devices.video_device, "--all"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.split("\n"):
            if "Card type" in line:
                return line.split(":")[-1].strip()
        return None

    async def _log_missing_meetbot_camera(self) -> bool:
        """Log enumerated cameras when MeetBot is absent. Always returns False."""
        logger.info("[CAMERA] MeetBot camera not found in browser device list")
        js_list_cameras = """
        async () => {
            const devices = await navigator.mediaDevices.enumerateDevices();
            return devices.filter(d => d.kind === 'videoinput').map(c => c.label);
        }
        """
        cameras = await self.page.evaluate(js_list_cameras)
        logger.info("[CAMERA] Available cameras: %s", cameras)
        return False

    async def _open_camera_dropdown(self) -> bool:
        """Open the pre-join camera menu. Return False if it cannot be opened."""
        dropdown_selector = 'button[aria-label^="Camera:"]'
        try:
            dropdown_btn = self.page.locator(dropdown_selector)
            if await dropdown_btn.count() > 0:
                await dropdown_btn.first.click()
                logger.info(
                    "[CAMERA] Opened camera dropdown via: %s", dropdown_selector
                )
                await asyncio.sleep(0.5)
                return True
            logger.info("[CAMERA] Could not find camera dropdown button")
        except Exception as open_error:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: a missing camera menu must not abort device setup.
            logger.info("[CAMERA] Could not open camera dropdown: %s", open_error)
        return False

    async def _click_meetbot_camera_menu(self) -> bool:
        """Click the MeetBot row in the open camera menu."""
        js_click_option = """
        async (searchText) => {
            const menuItems = document.querySelectorAll(
                'li[role="menuitemradio"][data-device-id]'
            );
            for (const item of menuItems) {
                const nameSpan = item.querySelector('span[jsname="K4r5Ff"]');
                if (!nameSpan) continue;
                const deviceName = nameSpan.textContent || '';
                if (!deviceName.includes(searchText)) continue;
                const rect = item.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    item.click();
                    return {
                        success: true,
                        deviceName: deviceName,
                        deviceId: item.getAttribute('data-device-id')
                    };
                }
            }
            const allNames = Array.from(menuItems).map(item => {
                const span = item.querySelector('span[jsname="K4r5Ff"]');
                return span ? span.textContent : 'no-name';
            });
            return {
                success: false,
                error: 'MeetBot device not found in menu',
                availableDevices: allNames
            };
        }
        """
        js_result = await self.page.evaluate(js_click_option, "MeetBot")
        if js_result and js_result.get("success"):
            logger.info("[CAMERA] Selected: %s", js_result.get("deviceName"))
            await asyncio.sleep(0.5)
            return True
        logger.info("[CAMERA] Selection failed: %s", js_result)
        return False

    async def _select_camera_programmatically(self) -> bool:
        """Ask Chrome for the MeetBot camera stream so Meet switches to it."""
        logger.info("[CAMERA] Attempting programmatic camera selection via JS...")
        js_select_camera = """
        async () => {
            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                const meetbot = devices.find(
                    d => d.kind === 'videoinput' && d.label.includes('MeetBot')
                );
                if (!meetbot) return { success: false, error: 'MeetBot not found' };
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: { deviceId: { exact: meetbot.deviceId } }
                });
                stream.getTracks().forEach(t => t.stop());
                return {
                    success: true,
                    deviceId: meetbot.deviceId,
                    label: meetbot.label
                };
            } catch (e) {
                return { success: false, error: e.message };
            }
        }
        """
        js_result = await self.page.evaluate(js_select_camera)
        if js_result and js_result.get("success"):
            logger.info(
                "[CAMERA] Programmatically selected: %s", js_result.get("label")
            )
            await asyncio.sleep(1)
            return True
        logger.info("[CAMERA] Programmatic selection failed: %s", js_result)
        return False

    async def _select_meetbot_camera_ui(self) -> bool:
        """Pre-join camera selection once the page is known to exist."""
        meetbot_device_name = self._v4l2_card_type()
        logger.info(
            "[CAMERA] Looking for MeetBot device: %s",
            meetbot_device_name or "any",
        )
        js_find_camera = """
        async () => {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const cameras = devices.filter(d => d.kind === 'videoinput');
            console.log('Available cameras:', cameras.map(c => c.label));
            const meetbot = cameras.find(c => c.label.includes('MeetBot'));
            return meetbot ? { label: meetbot.label, deviceId: meetbot.deviceId } : null;
        }
        """
        meetbot_info = await self.page.evaluate(js_find_camera)
        if not meetbot_info:
            return await self._log_missing_meetbot_camera()
        camera_label = meetbot_info.get("label", "")
        logger.info("[CAMERA] Found MeetBot in browser: %s", camera_label)
        if not await self._open_camera_dropdown():
            return False
        await asyncio.sleep(0.3)
        if await self._click_meetbot_camera_menu():
            return True
        return await self._select_camera_programmatically()

    async def _select_meetbot_camera(self) -> bool:
        """
        Select the MeetBot virtual camera in Google Meet's device settings.

        Opens the camera dropdown in Google Meet's pre-join screen and selects
        the MeetBot virtual camera.

        Returns:
            True if camera was selected, False otherwise.
        """
        if not self.page:
            return False
        try:
            return await self._select_meetbot_camera_ui()
        except Exception as camera_error:  # pylint: disable=broad-exception-caught
            # Meet UI boundary: camera selection must not abort joining.
            logger.warning("[CAMERA] Failed to select MeetBot camera: %s", camera_error)
            return False

    async def _set_devices_via_js(self) -> bool:
        """
        Programmatically set audio/video devices using JavaScript MediaDevices API.

        This requests getUserMedia with specific device constraints, which tells
        Chrome to use our MeetBot devices. This is more reliable than clicking
        UI elements.

        Returns:
            True if devices were set successfully.
        """
        if not self.page:
            return False

        try:
            # JavaScript to find MeetBot devices and request streams with them
            js_set_devices = """
            async () => {
                const results = { camera: false, microphone: false, speaker: false, errors: [] };

                try {
                    // Get all devices
                    const devices = await navigator.mediaDevices.enumerateDevices();

                    // Find MeetBot devices
                    const meetbotCamera = devices.find(
                        d => d.kind === 'videoinput' && d.label.includes('MeetBot')
                    );
                    const meetbotMic = devices.find(
                        d => d.kind === 'audioinput' && d.label.includes('MeetBot')
                    );
                    const meetbotSpeaker = devices.find(
                        d => d.kind === 'audiooutput' && d.label.includes('MeetBot')
                    );

                    console.log('[MeetBot] Found devices:', {
                        camera: meetbotCamera?.label,
                        mic: meetbotMic?.label,
                        speaker: meetbotSpeaker?.label
                    });

                    // Request camera stream with MeetBot device
                    if (meetbotCamera) {
                        try {
                            const videoStream = await navigator.mediaDevices.getUserMedia({
                                video: { deviceId: { exact: meetbotCamera.deviceId } }
                            });
                            // Keep the stream active briefly so Chrome
                            // registers it as the selected device
                            await new Promise(r => setTimeout(r, 500));
                            videoStream.getTracks().forEach(t => t.stop());
                            results.camera = true;
                            console.log('[MeetBot] Camera set to:', meetbotCamera.label);
                        } catch (e) {
                            results.errors.push('Camera: ' + e.message);
                        }
                    }

                    // Request microphone stream with MeetBot device
                    if (meetbotMic) {
                        try {
                            const audioStream = await navigator.mediaDevices.getUserMedia({
                                audio: { deviceId: { exact: meetbotMic.deviceId } }
                            });
                            await new Promise(r => setTimeout(r, 500));
                            audioStream.getTracks().forEach(t => t.stop());
                            results.microphone = true;
                            console.log('[MeetBot] Microphone set to:', meetbotMic.label);
                        } catch (e) {
                            results.errors.push('Microphone: ' + e.message);
                        }
                    }

                    // Set speaker output (if supported)
                    if (
                        meetbotSpeaker
                        && typeof document.createElement('audio').setSinkId
                            === 'function'
                    ) {
                        try {
                            // Create a temporary audio element to set the sink
                            const audio = document.createElement('audio');
                            await audio.setSinkId(meetbotSpeaker.deviceId);
                            results.speaker = true;
                            console.log('[MeetBot] Speaker set to:', meetbotSpeaker.label);
                        } catch (e) {
                            results.errors.push('Speaker: ' + e.message);
                        }
                    }

                } catch (e) {
                    results.errors.push('General: ' + e.message);
                }

                return results;
            }
            """

            result = await self.page.evaluate(js_set_devices)
            logger.info("[DEVICES-JS] Programmatic device selection: %s", result)

            if result.get("errors"):
                for err in result["errors"]:
                    logger.warning("[DEVICES-JS] Error: %s", err)

            return result.get("camera") or result.get("microphone")

        # Meet UI boundary: page or callback failures must not kill the bot.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("[DEVICES-JS] Failed to set devices via JS: %s", e)
            return False

    async def _select_meetbot_devices(self) -> dict:
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
            results["camera"] = await self._select_meetbot_camera()

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

        # Meet UI boundary: page or callback failures must not kill the bot.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("[DEVICES] Failed to select devices: %s", e)
            return results

    async def _select_camera_in_meeting(self) -> bool:
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
                # Meet UI boundary: page or callback failures must not kill the bot.
                except Exception:  # pylint: disable=broad-exception-caught
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
                    # Meet UI boundary: page or callback failures must not kill the bot.
                    except Exception:  # pylint: disable=broad-exception-caught
                        continue

                # Close dropdown if we didn't find MeetBot
                logger.warning(
                    "[CAMERA-SELECT] MeetBot not found in dropdown, pressing Escape"
                )
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.3)

            # Meet UI boundary: page or callback failures must not kill the bot.
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("[CAMERA-SELECT] Attempt %s failed: %s", attempt + 1, e)
                # Try to close any open dropdown
                try:
                    await self.page.keyboard.press("Escape")
                # Meet UI boundary: page or callback failures must not kill the bot.
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

        logger.error("[CAMERA-SELECT] Failed to select camera after 3 attempts")
        return False

    async def _toggle_mute(self, mute: bool = True) -> bool:
        """Toggle microphone mute state."""
        if not self.page:
            return False

        try:
            # Find mute button
            mute_button = await self.page.wait_for_selector(
                self.SELECTORS["mute_button"], timeout=5000
            )

            if mute_button:
                # Check current state
                is_muted = await mute_button.get_attribute("data-is-muted")
                current_muted = is_muted == "true"

                if current_muted != mute:
                    await mute_button.click()
                    if self.state:
                        self.state.muted = mute
                    logger.info("Microphone %s", "muted" if mute else "unmuted")

                return True

        # Meet UI boundary: page or callback failures must not kill the bot.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to toggle mute: %s", e)

        return False

    async def _toggle_camera(self, camera_on: bool = False) -> bool:
        """Toggle camera on/off state."""
        if not self.page:
            return False

        try:
            # Find camera button - try multiple selectors
            camera_button = None
            selectors = [
                '[aria-label*="camera" i]',
                '[data-tooltip*="camera" i]',
                '[aria-label*="video" i]',
                'button[aria-label*="Turn off camera"]',
                'button[aria-label*="Turn on camera"]',
            ]

            for selector in selectors:
                try:
                    camera_button = await self.page.wait_for_selector(
                        selector, timeout=2000
                    )
                    if camera_button:
                        break
                # Meet UI boundary: page or callback failures must not kill the bot.
                except Exception:  # pylint: disable=broad-exception-caught
                    continue

            if camera_button:
                # Get aria-label to determine current state
                aria_label = await camera_button.get_attribute("aria-label") or ""
                aria_label_lower = aria_label.lower()

                # Determine current state - if label says "turn of", camera is currently ON
                camera_currently_on = (
                    "turn of" in aria_label_lower or "stop" in aria_label_lower
                )

                if camera_currently_on != camera_on:
                    await camera_button.click()
                    if self.state:
                        self.state.camera_on = camera_on
                    logger.info("Camera %s", "enabled" if camera_on else "disabled")
                else:
                    logger.info("Camera already %s", "on" if camera_on else "off")

                return True

        # Meet UI boundary: page or callback failures must not kill the bot.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to toggle camera: %s", e)

        return False

    async def select_meetbot_devices(self) -> dict:
        """Public alias for _select_meetbot_devices."""
        return await self._select_meetbot_devices()

    async def select_meetbot_camera(self) -> bool:
        """Public alias for _select_meetbot_camera."""
        return await self._select_meetbot_camera()

    async def select_camera_in_meeting(self) -> bool:
        """Public alias for _select_camera_in_meeting."""
        return await self._select_camera_in_meeting()

    async def set_devices_via_js(self) -> bool:
        """Public alias for _set_devices_via_js."""
        return await self._set_devices_via_js()


class MeetDevices(DeviceMixin, MeetControllerView):
    """Handles device selection in Google Meet UI."""

    def __init__(self, controller: GoogleMeetController) -> None:
        MeetControllerView.__init__(self, controller)
