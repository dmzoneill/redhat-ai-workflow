"""Device selection and Chrome dialog handling mixin for Google Meet browser controller."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class DeviceMixin:
    """Mixin providing device selection (camera, mic, speaker) and Chrome permission/sync dialog handling."""

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
                    f"[DEVICES] Looking for mic: {mic_name}, speaker: {speaker_name}"
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

    async def _dismiss_chrome_sync_dialog(self) -> bool:
        """
        Dismiss the "Sign in to Chromium?" dialog that appears after Google SSO login.

        This dialog offers to sync Chrome with the Google account. We dismiss it by
        clicking "Use Chromium without an account" or pressing Escape.

        Returns:
            True if dialog was dismissed, False if not present.
        """
        if not self.page:
            return False

        try:
            # Wait a moment for the dialog to appear (it can be delayed)
            logger.info("Checking for Chrome sync dialog (waiting up to 5s)...")
            await asyncio.sleep(2)

            # Look for the "Sign in to Chromium?" dialog - check page content
            page_content = await self.page.content()
            dialog_found = False

            if (
                "Sign in to Chromium" in page_content
                or "Sign in to Chrome" in page_content
            ):
                dialog_found = True
                logger.info("Chrome sync dialog detected via page content")

            if not dialog_found:
                # Also try locator-based detection
                dialog_selectors = [
                    'text="Sign in to Chromium?"',
                    'text="Sign in to Chrome?"',
                    'text="Turn on sync?"',
                    ':text("Sign in to Chromium")',
                ]

                for selector in dialog_selectors:
                    try:
                        if await self.page.locator(selector).count() > 0:
                            dialog_found = True
                            logger.info(f"Chrome sync dialog detected: {selector}")
                            break
                    except Exception as e:
                        logger.debug("Suppressed dialog check: %s", e, exc_info=True)

            if not dialog_found:
                logger.info("No Chrome sync dialog found")
                return False

            # Try to click "Use Chromium without an account" or similar dismiss button
            dismiss_selectors = [
                # Exact button text matches
                'button:has-text("Use Chromium without an account")',
                'button:has-text("Use Chrome without an account")',
                # Role-based
                'role=button[name="Use Chromium without an account"]',
                # Partial text matches
                'button:has-text("without an account")',
                'button:has-text("No thanks")',
                'button:has-text("Cancel")',
                'button:has-text("Not now")',
                # The X close button
                'button[aria-label="Close"]',
                'button[aria-label="Dismiss"]',
            ]

            for selector in dismiss_selectors:
                try:
                    btn = self.page.locator(selector)
                    count = await btn.count()
                    if count > 0:
                        logger.info(f"Found dismiss button: {selector} (count={count})")
                        await btn.first.click(force=True, timeout=5000)
                        await asyncio.sleep(1)
                        logger.info("Chrome sync dialog dismissed")
                        return True
                except Exception as e:
                    logger.debug(f"Dismiss button {selector} failed: {e}")

            # Try Playwright's get_by_role
            try:
                logger.info("Trying get_by_role for dismiss button...")
                await self.page.get_by_role(
                    "button", name="Use Chromium without an account"
                ).click(timeout=3000)
                logger.info("Chrome sync dialog dismissed via get_by_role")
                return True
            except Exception as e:
                logger.debug(f"get_by_role failed: {e}")

            # Fallback: press Escape to close
            logger.info("Trying Escape key to dismiss Chrome sync dialog")
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            return True

        except Exception as e:
            logger.warning(f"Error handling Chrome sync dialog: {e}")
            return False

    async def _handle_permissions_dialog(self) -> bool:
        """
        Handle the "Do you want people to hear you in the meeting?" permissions dialog.

        This dialog appears when joining a meeting and asks about mic/camera permissions.
        We try to click "Microphone allowed", but if buttons are unresponsive (hardware issue),
        we dismiss via X button or Escape key.

        Returns:
            True if dialog was handled, False if not present or failed.
        """
        if not self.page:
            return False

        try:
            # Wait for the dialog to appear - it can take a moment
            logger.info("Checking for permissions dialog...")
            await asyncio.sleep(2)

            # Check if dialog is present by looking for the dialog text
            dialog_text = self.page.locator(
                'text="Do you want people to hear you in the meeting?"'
            )
            if await dialog_text.count() == 0:
                logger.info("No permissions dialog found")
                return False

            logger.info("Permissions dialog detected")

            # First try clicking "Microphone allowed" button
            mic_selectors = [
                'button:has-text("Microphone allowed")',
                'div[role="button"]:has-text("Microphone allowed")',
            ]

            for selector in mic_selectors:
                try:
                    mic_only = self.page.locator(selector)
                    count = await mic_only.count()
                    if count > 0:
                        logger.info(
                            f"Trying to click 'Microphone allowed' ({selector})"
                        )
                        await mic_only.first.click(force=True, timeout=3000)
                        await asyncio.sleep(1)
                        # Check if dialog is gone
                        if await dialog_text.count() == 0:
                            logger.info(
                                "Dialog dismissed via Microphone allowed button"
                            )
                            return True
                except Exception as e:
                    logger.debug(f"Mic button click failed: {e}")
                    continue

            # If mic button didn't work, try X button
            logger.info("Mic button unresponsive, trying X button...")
            close_selectors = [
                'button[aria-label="Close"]',
                '[aria-label="Close"]',
                'svg[aria-label="Close"]',
            ]

            for selector in close_selectors:
                try:
                    close_button = self.page.locator(selector)
                    if await close_button.count() > 0:
                        logger.info(f"Clicking X button ({selector})")
                        await close_button.first.click(force=True, timeout=3000)
                        await asyncio.sleep(1)
                        if await dialog_text.count() == 0:
                            logger.info("Dialog dismissed via X button")
                            return True
                except Exception:
                    continue

            # Last resort - press Escape to dismiss
            logger.info("Buttons unresponsive, pressing Escape...")
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            if await dialog_text.count() == 0:
                logger.info("Dialog dismissed via Escape key")
                return True

            logger.warning("Could not dismiss permissions dialog")
            return False

        except Exception as e:
            logger.debug(f"Error handling permissions dialog: {e}")

        return False

    async def _dismiss_info_popups(self) -> None:
        """Dismiss info popups like 'Others may see your video differently' or 'Full HD'.

        These popups have buttons like 'Got it', 'Not now', etc. that need to be clicked.
        IMPORTANT: Be very careful not to click buttons that toggle camera/mic!
        """
        if not self.page:
            return

        try:
            # SAFE button texts - these are clearly for dismissing info popups
            # DO NOT include "Close" as it can match toolbar buttons
            safe_button_texts = [
                "Not now",  # For "Turn on 1080p" popup - we don't want HD
                "Got it",
                "Dismiss",
                "Skip",
                "Maybe later",
            ]

            for text in safe_button_texts:
                try:
                    # Only click buttons that are clearly in dialogs/popups
                    # Use role="dialog" or role="alertdialog" to be safe
                    button = self.page.locator(
                        f'[role="dialog"] button:has-text("{text}"), [role="alertdialog"] button:has-text("{text}")'
                    )
                    count = await button.count()
                    if count > 0:
                        await button.first.click(timeout=1000)
                        logger.info(
                            f"Dismissed dialog popup by clicking '{text}' button"
                        )
                        await asyncio.sleep(0.3)
                        return  # Only dismiss one popup at a time
                except Exception as e:
                    logger.debug("Suppressed dialog dismiss: %s", e, exc_info=True)

            # Fallback: try button text without dialog constraint, but only for very safe texts
            for text in ["Got it", "Not now"]:
                try:
                    button = self.page.locator(f'button:has-text("{text}")')
                    count = await button.count()
                    if count > 0:
                        await button.first.click(timeout=1000)
                        logger.info(f"Dismissed popup by clicking '{text}' button")
                        await asyncio.sleep(0.3)
                        return
                except Exception as e:
                    logger.debug("Suppressed popup dismiss: %s", e, exc_info=True)

        except Exception as e:
            logger.debug(f"Error dismissing info popups: {e}")
