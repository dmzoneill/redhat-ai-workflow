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
                    f"[DEVICES] Looking for mic: {mic_name}, speaker: {speaker_name}"
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

            logger.info(f"[DEVICES] Selection results: {results}")
            return results

        except Exception as e:
            logger.warning(f"[DEVICES] Failed to select devices: {e}")
            return results

    async def _select_audio_device(self, device_type: str, device_name: str) -> bool:
        """
        Select an audio device (microphone or speaker) in Google Meet's UI.

        Args:
            device_type: "microphone" or "speaker"
            device_name: The PulseAudio device name to look for (e.g., "MeetBot_meet_bot_1_...")

        Returns:
            True if device was selected, False otherwise.
        """
        if not self.page:
            return False

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
                logger.info(f"[AUDIO] MeetBot {device_type} not found in browser")
                return False

            device_label = device_info.get("label", "")
            logger.info(f"[AUDIO] Found MeetBot {device_type}: {device_label}")

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
                        f"[AUDIO] Opened {device_type} dropdown via: {dropdown_selector}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.info(f"[AUDIO] Could not find {device_type} dropdown button")
                    return False
            except Exception as e:
                logger.info(f"[AUDIO] Could not open {device_type} dropdown: {e}")
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
                const menuItems = document.querySelectorAll('li[role="menuitemradio"][data-device-id]');

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
                        return { success: true, deviceName: deviceName, deviceId: item.getAttribute('data-device-id') };
                    }
                }

                // Debug: list all visible menu items
                const allNames = Array.from(menuItems).map(item => {
                    const span = item.querySelector('span[jsname="K4r5Ff"]');
                    return span ? span.textContent : 'no-name';
                });

                return { success: false, error: 'MeetBot device not found in menu', availableDevices: allNames };
            }
            """
            js_result = await self.page.evaluate(
                js_click_option, {"searchText": "MeetBot", "excludeMic": is_speaker}
            )
            if js_result and js_result.get("success"):
                logger.info(
                    f"[AUDIO] Selected {device_type}: {js_result.get('deviceName')}"
                )
                await asyncio.sleep(0.5)
                return True

            logger.info(f"[AUDIO] {device_type} selection failed: {js_result}")

            # Close dropdown if we couldn't select
            await self.page.keyboard.press("Escape")
            logger.info(f"[AUDIO] MeetBot {device_type} found but couldn't click in UI")
            return False

        except Exception as e:
            logger.warning(f"[AUDIO] Failed to select {device_type}: {e}")
            return False

    async def select_meetbot_camera(self) -> bool:
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
            # First, get the MeetBot device name from v4l2
            meetbot_device_name = None
            if self._devices and self._devices.video_device:
                import subprocess

                result = subprocess.run(
                    ["v4l2-ctl", "--device", self._devices.video_device, "--all"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if "Card type" in line:
                            meetbot_device_name = line.split(":")[-1].strip()
                            break

            logger.info(
                f"[CAMERA] Looking for MeetBot device: {meetbot_device_name or 'any'}"
            )

            # Use JavaScript to find the MeetBot camera in the browser's device list
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
                logger.info("[CAMERA] MeetBot camera not found in browser device list")
                # Log available cameras for debugging
                js_list_cameras = """
                async () => {
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    return devices.filter(d => d.kind === 'videoinput').map(c => c.label);
                }
                """
                cameras = await self.page.evaluate(js_list_cameras)
                logger.info(f"[CAMERA] Available cameras: {cameras}")
                return False

            camera_label = meetbot_info.get("label", "")
            logger.info(f"[CAMERA] Found MeetBot in browser: {camera_label}")

            # Step 1: Open camera dropdown using aria-label (stable attribute)
            dropdown_selector = 'button[aria-label^="Camera:"]'
            try:
                dropdown_btn = self.page.locator(dropdown_selector)
                if await dropdown_btn.count() > 0:
                    await dropdown_btn.first.click()
                    logger.info(
                        f"[CAMERA] Opened camera dropdown via: {dropdown_selector}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.info("[CAMERA] Could not find camera dropdown button")
                    return False
            except Exception as e:
                logger.info(f"[CAMERA] Could not open camera dropdown: {e}")
                return False

            # Step 2: Wait for dropdown menu to appear
            await asyncio.sleep(0.3)

            # Step 3: Find and click the MeetBot option using stable selectors
            # Structure: li[role="menuitemradio"] > ... > span[jsname="K4r5F"] contains device name
            js_click_option = """
            async (searchText) => {
                // Find all menu items with role="menuitemradio" and data-device-id
                const menuItems = document.querySelectorAll('li[role="menuitemradio"][data-device-id]');

                for (const item of menuItems) {
                    // Get the device name from span[jsname="K4r5F"]
                    const nameSpan = item.querySelector('span[jsname="K4r5Ff"]');
                    if (!nameSpan) continue;

                    const deviceName = nameSpan.textContent || '';

                    // Check if this is a MeetBot device
                    if (!deviceName.includes(searchText)) continue;

                    // Check if visible
                    const rect = item.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        item.click();
                        return { success: true, deviceName: deviceName, deviceId: item.getAttribute('data-device-id') };
                    }
                }

                // Debug: list all visible menu items
                const allNames = Array.from(menuItems).map(item => {
                    const span = item.querySelector('span[jsname="K4r5Ff"]');
                    return span ? span.textContent : 'no-name';
                });

                return { success: false, error: 'MeetBot device not found in menu', availableDevices: allNames };
            }
            """
            js_result = await self.page.evaluate(js_click_option, "MeetBot")
            if js_result and js_result.get("success"):
                logger.info(f"[CAMERA] Selected: {js_result.get('deviceName')}")
                await asyncio.sleep(0.5)
                return True

            logger.info(f"[CAMERA] Selection failed: {js_result}")

            # Step 3: Try using JavaScript to programmatically select the camera
            # This uses the MediaDevices API to request the specific camera
            logger.info("[CAMERA] Attempting programmatic camera selection via JS...")
            js_select_camera = """
            async () => {{
                try {{
                    // Get the MeetBot device
                    const devices = await navigator.mediaDevices.enumerateDevices();
                    const meetbot = devices.find(d => d.kind === 'videoinput' && d.label.includes('MeetBot'));
                    if (!meetbot) return {{ success: false, error: 'MeetBot not found' }};

                    // Request a stream with this specific device
                    // This should trigger Google Meet to switch to this camera
                    const stream = await navigator.mediaDevices.getUserMedia({{
                        video: {{ deviceId: {{ exact: meetbot.deviceId }} }}
                    }});

                    // Stop the stream - we just wanted to trigger the switch
                    stream.getTracks().forEach(t => t.stop());

                    return {{ success: true, deviceId: meetbot.deviceId, label: meetbot.label }};
                }} catch (e) {{
                    return {{ success: false, error: e.message }};
                }}
            }}
            """
            js_result = await self.page.evaluate(js_select_camera)
            if js_result and js_result.get("success"):
                logger.info(
                    f"[CAMERA] Programmatically selected: {js_result.get('label')}"
                )
                await asyncio.sleep(1)
                return True
            else:
                logger.info(f"[CAMERA] Programmatic selection failed: {js_result}")

            return False

        except Exception as e:
            logger.warning(f"[CAMERA] Failed to select MeetBot camera: {e}")
            return False

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
                    logger.info(f"[CAMERA-SELECT] Retry attempt {attempt + 1}/3...")
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
                        f"[CAMERA-SELECT] Video settings button not visible (attempt {attempt + 1})"
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
                logger.info(f"[CAMERA-SELECT] Found {count} menu items")

                for i in range(count):
                    try:
                        item = menu_items.nth(i)
                        text = await item.text_content(timeout=1000) or ""
                        if meetbot_pattern.lower() in text.lower():
                            logger.info(f"[CAMERA-SELECT] Found MeetBot option: {text}")
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
                logger.warning(f"[CAMERA-SELECT] Attempt {attempt + 1} failed: {e}")
                # Try to close any open dropdown
                try:
                    await self.page.keyboard.press("Escape")
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in _select_meetbot_camera (escape key): {e}"
                    )

        logger.error("[CAMERA-SELECT] Failed to select camera after 3 attempts")
        return False

    async def set_devices_via_js(self) -> bool:
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
                    const meetbotCamera = devices.find(d => d.kind === 'videoinput' && d.label.includes('MeetBot'));
                    const meetbotMic = devices.find(d => d.kind === 'audioinput' && d.label.includes('MeetBot'));
                    const meetbotSpeaker = devices.find(d => d.kind === 'audiooutput' && d.label.includes('MeetBot'));

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
                            // Keep the stream active briefly so Chrome registers it as the selected device
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
                    if (meetbotSpeaker && typeof document.createElement('audio').setSinkId === 'function') {
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
            logger.info(f"[DEVICES-JS] Programmatic device selection: {result}")

            if result.get("errors"):
                for err in result["errors"]:
                    logger.warning(f"[DEVICES-JS] Error: {err}")

            return result.get("camera") or result.get("microphone")

        except Exception as e:
            logger.warning(f"[DEVICES-JS] Failed to set devices via JS: {e}")
            return False
