"""Browser session lifecycle for Google Meet.

Join, sign-in, shutdown, and screenshot methods extracted from
GoogleMeetController so the controller module stays small.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

from tool_modules.aa_meet_bot.src.meet_runtime import BrowserClosedError
from tool_modules.aa_meet_bot.src.virtual_devices import (
    InstanceDeviceManager,
    InstanceDevices,
    cleanup_orphaned_meetbot_devices,
)

logger = logging.getLogger(__name__)


class SessionMixin:  # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """Join, sign-in, and teardown methods for GoogleMeetController."""

    # Declared for mixins that read sibling state.
    SCREENSHOT_DIR: Any
    _create_virtual_audio_sink: Any
    _instance_id: Any
    _on_browser_close: Any
    _restore_user_default_source: Any
    _route_browser_audio_to_sink: Any
    _audio_sink_name: Optional[str]
    _device_manager: Optional[InstanceDeviceManager]
    _devices: Optional[InstanceDevices]
    config: Any
    state: Any
    update_activity: Any

    async def _start_video_stream(
        self, video_device: str, video_enabled: bool = False
    ) -> bool:
        """
        Start video daemon streaming to the virtual camera device.

        This must be called BEFORE launching Chrome so the v4l2loopback device
        is actively streaming when Chrome enumerates cameras.

        Args:
            video_device: Path to v4l2loopback device (e.g., /dev/video0)
            video_enabled: If True, start full AI video overlay.
                          If False, start black screen (minimal CPU/GPU).

        Returns:
            True if video stream is ready, False otherwise.
        """
        try:
            from scripts.common.dbus_base import (  # pylint: disable=import-outside-toplevel,no-name-in-module
                get_client,
            )

            client = get_client("video")
            if not await client.connect():
                logger.warning(
                    "[%s] Could not connect to video daemon", self._instance_id
                )
                return False

            # Start black screen or full video based on video_enabled setting
            if video_enabled:
                # Full AI video overlay
                audio_source = (
                    f"{self._devices.sink_name}.monitor" if self._devices else ""
                )
                result = await client.call_method(
                    "start_video",
                    [video_device, audio_source, "", 1920, 1080, False],
                )
            else:
                # Black screen (minimal resources, device still active)
                result = await client.call_method(
                    "start_black_screen",
                    [video_device, 1920, 1080],
                )

            await client.disconnect()

            if not result or not result.get("success"):
                logger.warning(
                    "[%s] Video daemon start failed: %s", self._instance_id, result
                )
                return False

            # Wait for the device to switch to CAPTURE mode
            # With exclusive_caps=1, the device only shows as CAPTURE when actively streaming
            # Chrome will only detect it as a camera when it's in CAPTURE mode
            logger.info(
                "[%s] Waiting for video device to become active...", self._instance_id
            )
            await asyncio.sleep(1.0)  # Give time for first frames to be written

            # Verify the device is now in capture mode
            import subprocess  # pylint: disable=import-outside-toplevel

            device_info = subprocess.run(
                ["v4l2-ctl", "--device", video_device, "--all"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if (
                "Video Capture" in device_info.stdout
                and "Video Output" not in device_info.stdout
            ):
                logger.info(
                    "[%s] Device is in CAPTURE mode - Chrome will detect it",
                    self._instance_id,
                )
            else:
                logger.warning(
                    "[%s] Device may not be in pure CAPTURE mode", self._instance_id
                )

            logger.info(
                "[%s] Video stream started on %s", self._instance_id, video_device
            )
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "[%s] Failed to start video stream: %s", self._instance_id, e
            )
            return False

    async def _copy_profile_data(self, source_dir: Path, dest_dir: Path) -> None:
        """Copy login cookies and session data from main profile to instance profile."""
        import shutil  # pylint: disable=import-outside-toplevel

        # Files to copy for session persistence
        files_to_copy = [
            "Default/Cookies",
            "Default/Cookies-journal",
            "Default/Login Data",
            "Default/Login Data-journal",
            "Default/Web Data",
            "Default/Web Data-journal",
        ]

        # Directories to copy
        dirs_to_copy = [
            "Default/Accounts",
        ]

        dest_default = dest_dir / "Default"
        dest_default.mkdir(parents=True, exist_ok=True)

        for file_rel in files_to_copy:
            src = source_dir / file_rel
            dst = dest_dir / file_rel
            if src.exists() and not dst.exists():
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    logger.debug("Copied %s to instance profile", file_rel)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to copy %s: %s", file_rel, e)

        for dir_rel in dirs_to_copy:
            src = source_dir / dir_rel
            dst = dest_dir / dir_rel
            if src.exists() and not dst.exists():
                try:
                    shutil.copytree(src, dst)
                    logger.debug("Copied %s to instance profile", dir_rel)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.warning("Failed to copy %s: %s", dir_rel, e)

        logger.info("[%s] Profile data copied from main profile", self._instance_id)

    async def initialize(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        self, video_enabled: bool = False
    ) -> bool:  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        """Initialize the browser with stealth settings.

        Args:
            video_enabled: If True, start full AI video overlay. If False, start black screen.
        """
        self._video_enabled = video_enabled

        try:
            from playwright.async_api import (  # pylint: disable=import-outside-toplevel
                async_playwright,
            )

            # Check DISPLAY is set (required for headless=False)
            display = os.environ.get("DISPLAY")
            if not display:
                logger.error(
                    "DISPLAY environment variable not set - cannot launch visible browser"
                )
                if self.state:
                    self.state.errors.append(
                        "DISPLAY not set - browser requires X11 display"
                    )
                return False

            logger.info("Starting browser with DISPLAY=%s", display)

            # ========== CLEANUP ORPHANED DEVICES ==========
            # Remove any stale MeetBot devices from previous sessions
            # This prevents accumulation of orphaned sinks/sources/video devices
            logger.info(
                "[%s] Cleaning up orphaned MeetBot devices...", self._instance_id
            )
            cleanup_result = await cleanup_orphaned_meetbot_devices(
                active_instance_ids=set()
            )
            if cleanup_result.get("removed_modules") or cleanup_result.get(
                "removed_video_devices"
            ):
                logger.info(
                    "[%s] Cleanup removed: %s audio modules, %s video devices",
                    self._instance_id,
                    len(cleanup_result.get("removed_modules", [])),
                    len(cleanup_result.get("removed_video_devices", [])),
                )

            # ========== AUDIO PRE-ROUTING ==========
            # Create per-instance audio devices BEFORE launching Chrome
            # This ensures audio is routed correctly from the moment Chrome starts
            logger.info(
                "[%s] Creating per-instance audio devices...", self._instance_id
            )
            self._device_manager = InstanceDeviceManager(self._instance_id)
            self._devices = await self._device_manager.create_all()

            if self._devices:
                self._audio_sink_name = self._devices.sink_name
                logger.info("[%s] Audio devices ready:", self._instance_id)
                logger.info(
                    "[%s]   Sink: %s (Chrome output)",
                    self._instance_id,
                    self._devices.sink_name,
                )
                logger.info(
                    "[%s]   Source: %s (Chrome mic input)",
                    self._instance_id,
                    self._devices.source_name,
                )
                logger.info(
                    "[%s]   Pipe: %s", self._instance_id, self._devices.pipe_path
                )
            else:
                logger.warning(
                    "[%s] Failed to create audio devices, falling back to legacy method",
                    self._instance_id,
                )

            # Get virtual camera device path for Chrome launch args
            # The video_generator will stream to this device separately
            virtual_camera = None
            if self._devices and self._devices.video_device:
                virtual_camera = self._devices.video_device
                logger.info(
                    "[%s] Video device available: %s", self._instance_id, virtual_camera
                )
            elif Path(self.config.video.virtual_camera_device).exists():
                virtual_camera = self.config.video.virtual_camera_device
                logger.info(
                    "[%s] Using shared video device: %s",
                    self._instance_id,
                    virtual_camera,
                )

            # Legacy fallback: create audio sink if per-instance devices failed
            if not self._devices:
                await self._create_virtual_audio_sink()

            self._playwright = await async_playwright().start()

            # Use Chrome with a persistent profile for the bot account
            profile_dir = Path(self.config.bot_account.profile_dir).expanduser()
            profile_dir.mkdir(parents=True, exist_ok=True)

            # Clean up any stale lock files from crashed processes
            for lock_file in ["SingletonCookie", "SingletonLock", "SingletonSocket"]:
                lock_path = profile_dir / lock_file
                if lock_path.exists() or lock_path.is_symlink():
                    try:
                        lock_path.unlink()
                        logger.info("Removed stale lock file: %s", lock_file)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning(
                            "Could not remove lock file %s: %s", lock_file, e
                        )
            logger.info("Using profile directory: %s", profile_dir)

            # Verify avatar image exists
            avatar_path = Path(self.config.avatar.face_image)
            if not avatar_path.exists():
                logger.warning("Avatar image not found: %s", avatar_path)

            # Launch browser - use real PulseAudio devices from system
            # Device settings are saved in the persistent profile
            # pylint: disable-next=line-too-long
            # Use instance-specific profile to avoid lock conflicts, but copy cookies from main profile
            instance_profile_dir = profile_dir / f"instance-{self._instance_id}"
            instance_profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "[%s] Using instance profile: %s",
                self._instance_id,
                instance_profile_dir,
            )

            # pylint: disable-next=line-too-long
            # Copy cookies and login data from main profile if they exist and instance doesn't have them
            await self._copy_profile_data(profile_dir, instance_profile_dir)

            # ========== AUDIO PRE-ROUTING VIA ENVIRONMENT ==========
            # Set PULSE_SINK and PULSE_SOURCE env vars BEFORE launching Chrome
            # This routes audio to our virtual devices from the moment Chrome starts
            # Prevents audio from leaking to speakers before we can route it
            browser_env = os.environ.copy()
            if self._devices:
                browser_env["PULSE_SINK"] = self._devices.sink_name
                browser_env["PULSE_SOURCE"] = self._devices.source_name
                logger.info("[%s] Pre-routing audio via env vars:", self._instance_id)
                logger.info(
                    "[%s]   PULSE_SINK=%s", self._instance_id, self._devices.sink_name
                )
                logger.info(
                    "[%s]   PULSE_SOURCE=%s",
                    self._instance_id,
                    self._devices.source_name,
                )

            # Build Chrome args - include video device if available
            chrome_args = [
                # Minimal flags - same as working simple test
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu-sandbox",
                "--disable-dev-shm-usage",
                # Disable Chrome sync prompts (browser-level dialogs)
                "--disable-sync",
                "--disable-sync-preferences",
                "--no-service-autorun",
                "--password-store=basic",
                # Disable the "Sign in to Chrome" prompt
                "--disable-features=SyncPromo",
                "--disable-signin-promo",
                # Auto-approve mic permissions for fake devices
                "--use-fake-ui-for-media-stream",
            ]

            # ========== VIDEO PRE-STREAMING ==========
            # Start video daemon streaming BEFORE launching Chrome
            # This ensures the v4l2loopback device is active when Chrome enumerates cameras
            # Without an active stream, Chrome may not see the device as a valid camera
            if virtual_camera and Path(virtual_camera).exists():
                logger.info(
                    "[%s] Virtual camera available: %s",
                    self._instance_id,
                    virtual_camera,
                )
                video_ready = await self._start_video_stream(
                    virtual_camera, self._video_enabled
                )
                if video_ready:
                    video_mode = (
                        "full AI overlay" if self._video_enabled else "black screen"
                    )
                    logger.info(
                        "[%s] Video stream active (%s) - Chrome will see virtual camera",
                        self._instance_id,
                        video_mode,
                    )
                else:
                    logger.warning(
                        "[%s] Video stream not ready - Chrome may not see virtual camera",
                        self._instance_id,
                    )

            self.browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(instance_profile_dir),
                headless=False,  # Must be visible for virtual camera
                args=chrome_args,
                ignore_default_args=["--enable-automation"],
                permissions=["camera", "microphone"],
                env=browser_env,  # Critical: routes audio BEFORE any streams created
            )

            # CRITICAL: Register disconnect handler to detect when browser is closed
            # This triggers cleanup immediately when user closes the browser window
            self.browser.on("close", self._on_browser_close)
            logger.info("[%s] Registered browser close handler", self._instance_id)

            # Try to get browser PID
            try:
                # Playwright doesn't expose PID directly, but we can find it
                import psutil  # pylint: disable=import-outside-toplevel

                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        cmdline = proc.info.get("cmdline") or []
                        if any(self._instance_id in str(arg) for arg in cmdline):
                            self._browser_pid = proc.info["pid"]
                            logger.info(
                                "[%s] Browser PID: %s",
                                self._instance_id,
                                self._browser_pid,
                            )
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                logger.debug("psutil not available for PID tracking")

            # Audio routing note:
            # With PULSE_SINK/PULSE_SOURCE env vars, Chrome's audio is pre-routed from the start.
            # No need to call _route_browser_audio_to_sink() anymore - audio goes directly
            # to our virtual sink without ever touching the default speakers.
            #
            # Legacy fallback: if we didn't use per-instance devices, route manually
            if not self._devices and self._audio_sink_name:
                logger.info(
                    "[%s] Using legacy audio routing (no pre-routing)",
                    self._instance_id,
                )
                asyncio.create_task(self._route_browser_audio_to_sink())

            # CRITICAL: Restore the user's default audio source
            # PipeWire/Chrome may have switched the default to our virtual source
            # This runs in the background to restore it after Chrome settles
            asyncio.create_task(self._restore_user_default_source())

            self.page = (
                self.browser.pages[0]
                if self.browser.pages
                else await self.browser.new_page()
            )

            # Skip stealth scripts - they may break Google Meet UI
            # await self._inject_stealth_scripts()

            # pylint: disable-next=line-too-long
            # Don't navigate to meet.google.com here - it redirects to product page when not signed in
            # The browser will navigate directly to the meeting URL when join_meeting is called
            # Audio devices will be initialized when we navigate to the actual meeting

            logger.info(
                "Browser initialized successfully (will navigate when joining meeting)"
            )
            return True

        except ImportError as e:
            # pylint: disable-next=line-too-long
            error_msg = f"Playwright not installed: {e}. Run: uv add playwright && playwright install chromium"
            logger.error(error_msg)
            if self.state:
                self.state.errors.append(error_msg)

            # Clean up any devices that were created before the import error
            if self._device_manager:
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                self._device_manager = None
                self._devices = None

            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = f"Failed to initialize browser: {e}"
            logger.error(error_msg, exc_info=True)
            if self.state:
                self.state.errors.append(error_msg)

            # CRITICAL: Clean up audio devices if browser initialization failed
            # Otherwise devices are orphaned and accumulate on repeated failures
            if self._device_manager:
                logger.info(
                    "[%s] Cleaning up devices after browser init failure",
                    self._instance_id,
                )
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except (
                    Exception  # pylint: disable=broad-exception-caught
                ) as cleanup_err:  # pylint: disable=broad-exception-caught
                    logger.warning(
                        "[%s] Device cleanup failed: %s", self._instance_id, cleanup_err
                    )
                self._device_manager = None
                self._devices = None

            return False

    async def _inject_stealth_scripts(self) -> None:
        """Inject scripts to avoid bot detection."""
        await self.page.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

    # pylint: disable=trailing-newlines

    async def take_screenshot(
        self,
    ) -> Path | None:
        """
        Take a screenshot of the current meeting view.

        Returns:
            Path to the screenshot file, or None if failed.

        Raises:
            BrowserClosedError: If the browser/page has been closed.
        """
        if not self.page or not self.state.joined:
            return None

        try:
            self.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            # Use meeting_id for filename so each meeting has its own screenshot
            screenshot_path = self.SCREENSHOT_DIR / f"{self.state.meeting_id}.png"

            await self.page.screenshot(path=str(screenshot_path))
            self.update_activity()
            logger.debug(
                "[%s] Screenshot saved: %s", self._instance_id, screenshot_path
            )
            return screenshot_path
        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = str(e)
            # Detect browser/page closure
            if (
                "Target page, context or browser has been closed" in error_msg
                or "Target closed" in error_msg
                or "Browser has been closed" in error_msg
            ):
                logger.error("[%s] Browser was closed unexpectedly!", self._instance_id)
                self._browser_closed = True
                raise BrowserClosedError("Browser was closed") from e
            logger.warning("[%s] Failed to take screenshot: %s", self._instance_id, e)
            return None

    def is_browser_closed(self) -> bool:
        """Check if the browser has been closed.

        Checks browser/page state. Returns True only if we're certain the browser is closed.
        """
        # Check flag first (set by error handlers when we catch closure exceptions)
        if getattr(self, "_browser_closed", False):
            logger.debug(
                "[%s] is_browser_closed: _browser_closed flag is True",
                self._instance_id,
            )
            return True

        # Check if page exists and is closed
        try:
            if self.page is None:
                logger.warning(
                    "[%s] is_browser_closed: page is None", self._instance_id
                )
                self._browser_closed = True
                return True
            if self.page.is_closed():
                logger.warning(
                    "[%s] is_browser_closed: page.is_closed() returned True",
                    self._instance_id,
                )
                self._browser_closed = True
                return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Any error checking means browser is likely dead
            logger.warning(
                "[%s] is_browser_closed: exception during check: %s",
                self._instance_id,
                e,
            )
            self._browser_closed = True
            return True

        return False

    async def start_screenshot_loop(self, interval_seconds: int = 10) -> None:
        """
        Start periodic screenshot capture.

        Args:
            interval_seconds: Time between screenshots (default 10s)
        """
        logger.info(
            "[%s] Starting screenshot loop (every %ss)",
            self._instance_id,
            interval_seconds,
        )
        consecutive_failures = 0
        max_failures = 3  # Stop after 3 consecutive failures (browser likely closed)

        while self.state.joined and self.page:
            try:
                result = await self.take_screenshot()
                if result:
                    consecutive_failures = 0  # Reset on success
                else:
                    consecutive_failures += 1
            except BrowserClosedError:
                logger.error(
                    "[%s] Browser closed - stopping screenshot loop", self._instance_id
                )
                self.state.joined = False
                break
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("[%s] Screenshot loop error: %s", self._instance_id, e)
                consecutive_failures += 1

            # If too many consecutive failures, assume browser is dead
            if consecutive_failures >= max_failures:
                logger.error(
                    "[%s] Too many screenshot failures - browser likely closed",
                    self._instance_id,
                )
                self._browser_closed = True
                self.state.joined = False
                break

            await asyncio.sleep(interval_seconds)

        logger.info("[%s] Screenshot loop stopped", self._instance_id)

    def get_screenshot_path(
        self,
    ) -> Path | None:
        """Get the path to the latest screenshot for this meeting."""
        if not self.state.meeting_id:
            return None
        screenshot_path = self.SCREENSHOT_DIR / f"{self.state.meeting_id}.png"
        return screenshot_path if screenshot_path.exists() else None
