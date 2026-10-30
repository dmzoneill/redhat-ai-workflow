# pylint: disable=duplicate-code
"""Sign-in, join, leave, and screenshot methods for GoogleMeetController."""  # pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from tool_modules.aa_meet_bot.src.browser_errors import BROWSER_ERRORS
from tool_modules.aa_meet_bot.src.meet_runtime import MeetingState
from tool_modules.aa_meet_bot.src.meet_sign_in import MeetSignIn

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)


class SessionAuthMixin:  # pylint: disable=missing-class-docstring,no-member
    # Declared for mixins that read sibling state.
    SELECTORS: Any
    _browser_pid: Any
    _created_at: Any
    _dismiss_chrome_sync_dialog: Any
    _dismiss_info_popups: Any
    _handle_permissions_dialog: Any
    _instance_id: Any
    _instances: ClassVar[Any]
    _remove_virtual_audio_sink: Any
    _select_camera_in_meeting: Any
    _select_meetbot_camera: Any
    _select_meetbot_devices: Any
    _set_devices_via_js: Any
    _toggle_camera: Any
    _toggle_mute: Any
    _video_enabled: Any
    config: Any
    enable_captions: Any
    initialize: Any
    _device_manager: Any | None
    _devices: Any | None
    _playwright: Any
    browser: Any
    page: Any
    state: Any
    stop_caption_capture: Any

    async def sign_in_google(self) -> bool:
        """
        Sign in to Google using Red Hat SSO.

        Delegates to :class:`MeetSignIn`, which implements the OAuth + SSO flow.

        Returns:
            True if sign-in successful, False otherwise.
        """
        return await MeetSignIn(cast("GoogleMeetController", self)).sign_in_google()

    # pylint: disable-next=too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    async def join_meeting(self, meet_url: str) -> bool:
        """
        Join a Google Meet meeting.

        Args:
            meet_url: The Google Meet URL (e.g., https://meet.google.com/xxx-xxxx-xxx)

        Returns:
            True if successfully joined, False otherwise.
        """
        logger.info("[JOIN] ========== Starting join_meeting ==========")
        logger.info("[JOIN] URL: %s", meet_url)

        # Check if browser needs reinitialization
        needs_reinit = False
        if not self.page:
            logger.warning("[JOIN] page is None")
            needs_reinit = True
        elif self.page.is_closed():
            logger.warning("[JOIN] page.is_closed() is True")
            needs_reinit = True
        elif getattr(self, "_browser_closed", False):
            logger.warning("[JOIN] _browser_closed flag is True")
            needs_reinit = True

        if needs_reinit:
            logger.warning("[JOIN] Browser needs reinitialization...")
            # Reset the closed flag
            self._browser_closed = False
            # Close any existing browser resources
            await self.close()
            # Reinitialize the browser
            if not await self.initialize(video_enabled=getattr(self, "_video_enabled", False)):
                error_msg = "Failed to reinitialize browser after closure"
                logger.error("[JOIN] ERROR: %s", error_msg)
                if self.state:
                    self.state.errors.append(error_msg)
                return False
            logger.info("[JOIN] Browser reinitialized successfully")

        if not self.page:
            error_msg = "Browser not initialized - page is None"
            logger.error("[JOIN] ERROR: %s", error_msg)
            self.state.errors.append(error_msg)
            return False

        # Extract meeting ID from URL
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        if not match:
            error_msg = f"Invalid Meet URL format: {meet_url}"
            logger.error("[JOIN] ERROR: %s", error_msg)
            self.state.errors.append(error_msg)
            return False

        meeting_id = match.group(1)
        logger.info("[JOIN] Meeting ID: %s", meeting_id)

        # Update state but preserve errors
        old_errors = self.state.errors if self.state else []
        self.state = MeetingState(meeting_id=meeting_id, meeting_url=meet_url)
        self.state.errors = old_errors

        try:  # pylint: disable=too-many-nested-blocks
            # pylint: disable-next=line-too-long
            # Navigate to meeting - use domcontentloaded instead of networkidle (faster, more reliable)
            logger.info("[JOIN] Navigating to meeting URL...")
            await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
            logger.info("[JOIN] Navigation complete. Current URL: %s", self.page.url)

            # Wait for page to load
            logger.info("[JOIN] Waiting 2s for page to settle...")
            await asyncio.sleep(2)

            # Log page title and URL for debugging
            try:
                title = await self.page.title()
                logger.info("[JOIN] Page title: %s", title)
                logger.info("[JOIN] Current URL after wait: %s", self.page.url)
            except BROWSER_ERRORS as e:
                logger.warning("[JOIN] Could not get page title: %s", e)

            # Handle permissions dialog - "Do you want people to hear you in the meeting?"
            # This appears before joining and asks about mic/camera permissions
            logger.info("[JOIN] Checking for permissions dialog...")
            await self._handle_permissions_dialog()

            # Handle "Got it" dialog if present
            logger.info("[JOIN] Checking for 'Got it' dialog...")
            try:
                got_it = await self.page.wait_for_selector(self.SELECTORS["got_it_button"], timeout=3000)
                if got_it:
                    logger.info("[JOIN] Found 'Got it' dialog - clicking")
                    await got_it.click()
                    await asyncio.sleep(1)
            except BROWSER_ERRORS:
                logger.info("[JOIN] No 'Got it' dialog found")

            # Check if we need to sign in (look for Sign in button or name input for guest)
            logger.info("[JOIN] Checking if sign-in is required...")
            sign_in_button = await self.page.locator('div[role="button"]:has-text("Sign in")').count() > 0
            name_input = await self.page.query_selector(self.SELECTORS["name_input"])
            logger.info(
                "[JOIN] Sign-in button present: %s, Name input present: %s",
                sign_in_button,
                name_input is not None,
            )

            if sign_in_button or name_input:
                logger.info("[JOIN] Sign-in required - initiating OAuth flow")
                if not await self.sign_in_google():
                    logger.error("[JOIN] Sign-in failed!")
                    self.state.errors.append("Failed to sign in to Google")
                    return False

                # After sign-in, we should already be on the Meet page
                # Wait a moment for the page to settle
                logger.info("[JOIN] Sign-in complete, waiting for page to settle...")
                await asyncio.sleep(3)

                # Dismiss Chrome sync dialog if present ("Sign in to Chromium?")
                await self._dismiss_chrome_sync_dialog()

                # Check if we need to re-navigate (sometimes SSO redirects elsewhere)
                if "meet.google.com" not in self.page.url:
                    logger.info(
                        "[JOIN] Re-navigating to meeting after sign-in (current: %s)",
                        self.page.url,
                    )
                    await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
            else:
                logger.info("[JOIN] No sign-in required, proceeding to join")

            # Check again for Chrome sync dialog (it can appear delayed)
            logger.info("[JOIN] Checking for Chrome sync dialog before joining...")
            await self._dismiss_chrome_sync_dialog()

            # UNMUTE microphone (it's a virtual pipe - only produces sound when we write to it)
            # Turn off camera before joining (we use virtual avatar instead)
            logger.info("[JOIN] Setting up audio/video (UNMUTE virtual mic, turn off camera)...")
            # Always unmute - the bot's mic is a virtual pipe, not a real microphone
            # It only produces sound when TTS writes audio to it
            await self._toggle_mute(mute=False)

            # Dismiss any popups that might block device selection
            # (e.g., "Let people see you in Full HD", "Turn on 1080p", etc.)
            logger.info("[JOIN] Dismissing any blocking popups...")
            await self._dismiss_info_popups()

            # Select MeetBot virtual devices before joining
            # This ensures Google Meet uses our virtual devices instead of system defaults
            logger.info("[JOIN] Selecting MeetBot virtual devices...")
            await self._select_meetbot_devices()

            # Also set devices programmatically via JavaScript MediaDevices API
            # This is more reliable than clicking UI elements
            logger.info("[JOIN] Setting devices programmatically via JS...")
            await self._set_devices_via_js()

            # Set camera state based on video_enabled setting
            # If video is enabled, keep camera ON to show the AI overlay
            # If video is disabled, turn camera OFF (we're streaming black anyway)
            if self._video_enabled:
                logger.info("[JOIN] Video enabled - keeping camera ON for AI overlay")
                await self._toggle_camera(camera_on=True)
            else:
                logger.info("[JOIN] Video disabled - turning camera OFF")
                await self._toggle_camera(camera_on=False)

            # Click join button - try multiple selectors
            logger.info("[JOIN] Looking for Join button...")
            join_button = None

            # Try various join buttons in order of preference
            join_button_texts = [
                "Join now",
                "Join anyway",  # When meeting hasn't started or scheduling conflict
                "Switch here",  # When Google thinks another browser is already in the meeting
                "Ask to join",  # When you need to be admitted
            ]

            for btn_text in join_button_texts:
                if join_button:
                    break
                try:
                    # Try multiple selector patterns - Google Meet uses various button structures
                    selectors = [
                        f'button:has-text("{btn_text}")',
                        f'div[role="button"]:has-text("{btn_text}")',
                        f'span:has-text("{btn_text}")',  # Sometimes the text is in a span
                        # pylint: disable-next=line-too-long
                        f'[data-mdc-dialog-action]:has-text("{btn_text}")',  # Material dialog buttons
                    ]
                    for selector in selectors:
                        locator = self.page.locator(selector)
                        if await locator.count() > 0:
                            join_button = locator.first
                            logger.info(
                                "Found '%s' button with selector: %s",
                                btn_text,
                                selector,
                            )
                            break
                except BROWSER_ERRORS as e:
                    logger.debug("Error finding '%s': %s", btn_text, e)

            # If no button found, wait and retry once
            if not join_button:
                logger.info("[JOIN] No join button found on first try, waiting 3s and retrying...")

                # Take a screenshot for debugging
                try:
                    screenshot_path = str(Path(tempfile.gettempdir()) / f"meet_debug_{meeting_id}.png")
                    await self.page.screenshot(path=screenshot_path)
                    logger.info("[JOIN] Debug screenshot saved to: %s", screenshot_path)
                except BROWSER_ERRORS as e:
                    logger.warning("[JOIN] Could not save debug screenshot: %s", e)

                # Log visible text on page for debugging
                try:
                    body_text = await self.page.inner_text("body")
                    # Truncate to first 500 chars
                    logger.info("[JOIN] Page body text (first 500 chars): %s", body_text[:500])
                except BROWSER_ERRORS as e:
                    logger.warning("[JOIN] Could not get page text: %s", e)

                await asyncio.sleep(3)
                for btn_text in join_button_texts:
                    if join_button:
                        break
                    try:
                        for selector in [
                            f'button:has-text("{btn_text}")',
                            f'div[role="button"]:has-text("{btn_text}")',
                            f'span:has-text("{btn_text}")',
                        ]:
                            locator = self.page.locator(selector)
                            if await locator.count() > 0:
                                join_button = locator.first
                                logger.info("[JOIN] Found '%s' button on retry", btn_text)
                                break
                    except BROWSER_ERRORS:
                        logger.debug("Ignoring browser error", exc_info=True)

            if join_button:
                logger.info("[JOIN] Clicking join button...")
                await join_button.click()
                logger.info("[JOIN] Join button clicked successfully")

                # Wait for meeting to load
                await asyncio.sleep(3)

                # Handle permissions dialog if it appears
                # "Do you want people to hear you in the meeting?"
                try:
                    mic_button = self.page.locator('button:has-text("Microphone allowed")')
                    if await mic_button.count() > 0:
                        logger.info("Permissions dialog detected - clicking 'Microphone allowed'")
                        await mic_button.click(force=True)
                        await asyncio.sleep(2)
                except BROWSER_ERRORS as e:
                    logger.debug("No permissions dialog or error: %s", e)

                # Handle device selection dialog if it appears
                # This shows microphone and speaker dropdowns
                # We use this opportunity to select the MeetBot virtual camera
                # NOTE: Do NOT press Escape here - in Google Meet it can toggle camera!
                try:
                    device_dialog = self.page.locator('[aria-label="Settings"], [aria-label="Audio settings"]')
                    if await device_dialog.count() > 0:
                        logger.info("Device selection dialog detected")
                        # Try to select the MeetBot camera before dismissing
                        await self._select_meetbot_camera()
                        # Click outside the dialog to close it instead of Escape
                        # (Escape can toggle camera in Google Meet!)
                        try:
                            # Click on the main meeting area to close dialog
                            await self.page.click("body", position={"x": 100, "y": 100})
                            await asyncio.sleep(0.5)
                        except BROWSER_ERRORS:
                            logger.debug("Ignoring browser error", exc_info=True)
                except BROWSER_ERRORS as e:
                    logger.debug("No device dialog or error: %s", e)

                # After permissions dialog, we may need to click Join again
                # Look for "Join anyway" or "Join now" button
                try:
                    for btn_text in ["Join anyway", "Join now"]:
                        join_again = self.page.locator(f'button:has-text("{btn_text}")')
                        if await join_again.count() > 0:
                            logger.info("Found '%s' after permissions - clicking", btn_text)
                            await join_again.first.click()
                            await asyncio.sleep(3)
                            break
                except BROWSER_ERRORS as e:
                    logger.debug("No second join button needed: %s", e)

                # Brief wait for meeting UI to stabilize
                # NOTE: Removed generic "Close" button clicking - it was toggling camera!
                # _dismiss_info_popups() handles safe popup dismissal
                logger.info("[JOIN] Waiting 2s for meeting UI to stabilize...")
                await asyncio.sleep(2)

                # Dismiss any info popups (like "Others may see your video differently")
                await self._dismiss_info_popups()

                # Check if we're in the meeting
                self.state.joined = True
                logger.info("[JOIN] Meeting state set to joined=True")

                # Enable captions if configured
                if self.config.auto_enable_captions:
                    logger.info("[JOIN] Auto-enabling captions...")
                    await self.enable_captions()

                # IMPORTANT: Google Meet may turn off camera due to privacy settings
                # Always ensure camera is ON after joining if video is enabled
                if self._video_enabled:
                    logger.info("[JOIN] Ensuring camera is ON after join...")
                    await asyncio.sleep(1.0)  # Wait for Meet to settle

                    # First, select the MeetBot camera via Video settings dropdown
                    await self._select_camera_in_meeting()

                    # Then turn on the camera
                    await self._toggle_camera(camera_on=True)

                logger.info(
                    "[JOIN] ========== SUCCESS: Joined meeting %s ==========",
                    meeting_id,
                )
                return True
            logger.error("[JOIN] ========== FAILED: Join button not found ==========")
            logger.error("[JOIN] Current URL: %s", self.page.url)
            self.state.errors.append("Join button not found")
            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = f"Failed to join meeting: {e}"
            logger.exception("[JOIN] ========== EXCEPTION: %s ==========", error_msg)
            self.state.errors.append(error_msg)
            return False

    async def leave_meeting(self) -> bool:
        """Leave the current meeting."""
        if not self.page or not self.state:
            return False

        try:
            # Stop caption capture
            await self.stop_caption_capture()

            # Click leave button
            leave_button = await self.page.wait_for_selector(self.SELECTORS["leave_button"], timeout=5000)

            if leave_button:
                await leave_button.click()
                self.state.joined = False
                logger.info("Left meeting")
                return True

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to leave meeting")

        return False

    async def close(self, restore_browser_audio: bool = False) -> None:
        """Close the browser and cleanup resources.

        Args:
            restore_browser_audio: If True, restore browser mic connections that were
                                   saved before device creation. Set to True when the
                                   meeting dies unexpectedly (browser crashed, service
                                   restarted, etc.) to ensure user's Chrome keeps mic.
        """
        logger.info(
            "[%s] Closing browser controller (restore_audio=%s)...",
            self._instance_id,
            restore_browser_audio,
        )

        # Stop caption capture first (this cancels the polling task)
        try:
            await asyncio.wait_for(self.stop_caption_capture(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("[%s] Timeout stopping caption capture", self._instance_id)

        if self.browser:
            try:
                await asyncio.wait_for(self.browser.close(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("[%s] Timeout closing browser, forcing...", self._instance_id)
                await self.force_kill()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("[%s] Error closing browser: %s", self._instance_id, e, exc_info=True)
            self.browser = None

        if hasattr(self, "_playwright") and self._playwright:
            try:
                await asyncio.wait_for(self._playwright.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[%s] Timeout stopping playwright", self._instance_id)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("[%s] Error stopping playwright: %s", self._instance_id, e, exc_info=True)
            self._playwright = None

        # Clean up per-instance audio devices (new method)
        if self._device_manager:
            await self._device_manager.cleanup(restore_browser_audio=restore_browser_audio)
            self._device_manager = None
            self._devices = None
        else:
            # Legacy cleanup
            await self._remove_virtual_audio_sink()

        # Unregister this instance
        if self._instance_id in type(self)._instances:
            del type(self)._instances[self._instance_id]

        logger.info("[%s] Browser closed", self._instance_id)

    def _on_browser_close(self) -> None:
        """Handle browser close event from Playwright.

        This is called IMMEDIATELY when the browser window is closed by the user.
        It sets the _browser_closed flag and triggers async cleanup.

        CRITICAL: This is a sync callback, so we schedule the async cleanup.
        """
        logger.warning("[%s] *** BROWSER CLOSE EVENT DETECTED ***", self._instance_id)
        self._browser_closed = True

        # Update state to reflect browser is gone
        if self.state:
            self.state.joined = False

        # Schedule async cleanup - this runs the device cleanup
        # We use asyncio.create_task but need to get the event loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handle_browser_close_async())
        except RuntimeError:
            # No running event loop - cleanup will happen via health monitor
            logger.warning(
                "[%s] No event loop for async cleanup, relying on health monitor",
                self._instance_id,
            )

    async def _handle_browser_close_async(self) -> None:
        """Async handler for browser close - cleans up devices immediately."""
        logger.info(
            "[%s] Running immediate device cleanup after browser close...",
            self._instance_id,
        )

        # Clean up audio devices - RESTORE browser audio since this is unexpected
        if self._device_manager:
            try:
                await self._device_manager.cleanup(restore_browser_audio=True)
                logger.info("[%s] Device cleanup completed", self._instance_id)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("[%s] Device cleanup error: %s", self._instance_id, e, exc_info=True)
            finally:
                self._device_manager = None
                self._devices = None

        # Also run orphan cleanup to catch anything else
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (  # pylint: disable=import-outside-toplevel
                cleanup_orphaned_meetbot_devices,
            )

            results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())
            if results.get("removed_modules") or results.get("killed_processes"):
                logger.info(
                    "[%s] Orphan cleanup: %s modules, %s processes",
                    self._instance_id,
                    len(results.get("removed_modules", [])),
                    len(results.get("killed_processes", [])),
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("[%s] Orphan cleanup error: %s", self._instance_id, e, exc_info=True)

        # Unregister this instance
        if self._instance_id in type(self)._instances:
            del type(self)._instances[self._instance_id]

        logger.info("[%s] Browser close cleanup complete", self._instance_id)

    async def force_kill(self) -> bool:
        """Force kill this browser instance and its processes.

        This is called when the browser is unresponsive or crashed.
        Always restores browser audio since this is an unexpected termination.
        """
        logger.warning("[%s] Force killing browser instance...", self._instance_id)
        killed = False

        # Kill browser process
        if self._browser_pid:
            try:
                import os  # pylint: disable=import-outside-toplevel
                import signal  # pylint: disable=import-outside-toplevel

                os.kill(self._browser_pid, signal.SIGKILL)
                logger.info("[%s] Killed browser PID %s", self._instance_id, self._browser_pid)
                killed = True
            except (ProcessLookupError, PermissionError) as e:
                logger.debug(
                    "[%s] Browser already dead or inaccessible: %s",
                    self._instance_id,
                    e,
                )

        # Try to find and kill by instance ID in cmdline
        try:
            import psutil  # pylint: disable=import-outside-toplevel

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    if any(self._instance_id in str(arg) for arg in cmdline):
                        proc.kill()
                        logger.info(
                            "[%s] Killed process %s by cmdline match",
                            self._instance_id,
                            proc.info["pid"],
                        )
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass

        # Clean up audio devices and RESTORE browser audio (force kill = unexpected)
        if self._device_manager:
            await self._device_manager.cleanup(restore_browser_audio=True)
            self._device_manager = None
            self._devices = None

        # Unregister
        if self._instance_id in type(self)._instances:
            del type(self)._instances[self._instance_id]

        return killed

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = datetime.now()  # noqa: DTZ005 - naive local time, matches meet_runtime

    def get_instance_info(self) -> dict:
        """Get information about this instance."""
        return {
            "instance_id": self._instance_id,
            "browser_pid": self._browser_pid,
            "created_at": self._created_at.isoformat(),
            "last_activity": self._last_activity.isoformat(),
            "meeting_url": self.state.meeting_url if self.state else None,
            "joined": self.state.joined if self.state else False,
        }

    @classmethod
    def get_all_instances(cls) -> dict[str, GoogleMeetController]:
        """Get all active controller instances."""
        return cls._instances.copy()

    @classmethod
    async def cleanup_hung_instances(cls, max_age_minutes: int = 120) -> list[str]:
        """Find and kill instances that haven't had activity for too long."""
        now = datetime.now()  # noqa: DTZ005 - compared with naive _last_activity
        killed = []

        for instance_id, controller in list(cls._instances.items()):
            age = (now - controller.last_activity).total_seconds() / 60
            if age > max_age_minutes:
                logger.warning(
                    "Instance %s is hung (no activity for %s min)",
                    instance_id,
                    format(age, ".1f"),
                )
                await controller.force_kill()
                killed.append(instance_id)

        return killed

    async def unmute_and_speak(self) -> bool:
        """Unmute microphone to allow bot to speak."""
        return await self._toggle_mute(mute=False)

    async def mute(self) -> bool:
        """Mute microphone after speaking."""
        return await self._toggle_mute(mute=True)
