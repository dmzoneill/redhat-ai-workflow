"""
Browser Controller for Google Meet.

Uses Playwright with stealth mode to:
- Join Google Meet meetings
- Enable captions
- Capture caption text via DOM observation
- Inject virtual camera/microphone

Audio Pre-Routing:
- Creates per-instance virtual audio devices BEFORE launching Chrome
- Uses PULSE_SINK/PULSE_SOURCE env vars to route audio from the start
- Prevents audio leaking to speakers before routing takes effect
"""

import asyncio
import logging
import os
import re
import threading
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.virtual_devices import (
    InstanceDeviceManager,
    InstanceDevices,
    cleanup_orphaned_meetbot_devices,
)

# Import centralized paths
try:
    from server.paths import MEETBOT_SCREENSHOTS_DIR
except ImportError:
    # Fallback for standalone usage
    MEETBOT_SCREENSHOTS_DIR = (
        Path.home() / ".config" / "aa-workflow" / "meet_bot" / "screenshots"
    )

from tool_modules.aa_meet_bot.src.meet_audio import MeetAudio
from tool_modules.aa_meet_bot.src.meet_captions import (  # noqa: E402,F401
    MAX_CAPTION_BUFFER,
    CaptionEntry,
    MeetCaptions,
)
from tool_modules.aa_meet_bot.src.meet_devices import MeetDevices
from tool_modules.aa_meet_bot.src.meet_participants import MeetParticipants
from tool_modules.aa_meet_bot.src.meet_sign_in import MeetSignIn

logger = logging.getLogger(__name__)


class BrowserClosedError(Exception):
    """Raised when the browser has been closed unexpectedly."""


@dataclass
class MeetingState:
    """Current state of the meeting."""

    meeting_id: str
    meeting_url: str
    joined: bool = False
    captions_enabled: bool = False
    muted: bool = True
    camera_on: bool = True
    participants: list[str] = field(default_factory=list)
    caption_buffer: list[CaptionEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GoogleMeetController:
    """Controls a Google Meet session via browser automation."""

    # CSS selectors for Google Meet elements (may need updates as Meet UI changes)
    SELECTORS = {
        # Join flow - buttons to join the meeting
        "join_button": (
            'button:has-text("Join now"), button:has-text("Ask to join"), '
            'div[role="button"]:has-text("Join now"), div[role="button"]:has-text("Ask to join")'
        ),
        "ask_to_join_button": 'button:has-text("Ask to join"), div[role="button"]:has-text("Ask to join")',
        "join_now_button": 'button:has-text("Join now"), div[role="button"]:has-text("Join now")',
        "got_it_button": 'button:has-text("Got it")',
        # Permissions dialog that appears after joining
        "mic_allowed_button": 'button:has-text("Microphone allowed")',
        "camera_mic_allowed_button": 'button:has-text("Camera and microphone allowed")',
        "permissions_dialog_close": '[aria-label="Close"], button:has-text("Close"), div[aria-label="Close dialog"]',
        # Sign in flow - Google Meet sign in button (div with role="button")
        "sign_in_button": 'div[role="button"]:has-text("Sign in"), span:has-text("Sign in")',
        # Google login page - email input
        "google_email_input": '#identifierId, input[name="identifier"], input[type="email"]',
        "google_email_next": '#identifierNext, button:has-text("Next")',
        "google_password_input": 'input[type="password"], input[name="Passwd"]',
        "google_password_next": '#passwordNext, button:has-text("Next")',
        # Red Hat SSO login page
        "saml_username": '#username, input[name="username"]',
        "saml_password": '#password, input[name="password"]',
        "saml_submit": '#submit, input[name="submit"], input[type="submit"]',
        # Name input for guest join
        "name_input": 'input[aria-label="Your name"], input[placeholder*="name"]',
        # Controls
        "mute_button": '[data-is-muted], [aria-label*="microphone"], [data-tooltip*="microphone"]',
        "camera_button": '[aria-label*="camera"], [data-tooltip*="camera"]',
        "captions_button": '[aria-label*="caption"], [data-tooltip*="caption"], [jsname="r8qRAd"]',
        "leave_button": '[aria-label*="Leave"], [data-tooltip*="Leave"]',
        # Caption display - these selectors target the caption container
        "caption_container": '.a4cQT, [jsname="dsyhDe"], .iOzk7',
        "caption_text": '.CNusmb, .TBMuR, [jsname="YSxPC"]',
        "caption_speaker": ".zs7s8d, .KcIKy",
        # Meeting info
        "participant_count": "[data-participant-count], .rua5Nb",
        "meeting_title": ".u6vdEc, [data-meeting-title]",
    }

    # Class-level counter for unique instance IDs
    _instance_counter = 0
    _counter_lock = threading.Lock()
    _instances: weakref.WeakValueDictionary[str, "GoogleMeetController"] = (
        weakref.WeakValueDictionary()
    )  # Track all instances; weak refs allow GC of crashed instances

    def __init__(self):
        self.config = get_config()
        self.browser = None
        self.context = None
        self.page = None
        # Initialize state early so errors can be captured during initialization
        self.state: MeetingState = MeetingState(meeting_id="", meeting_url="")
        self._playwright = None
        self._audio_sink_name: Optional[str] = (
            None  # Virtual audio sink for meeting output
        )

        # Unique instance tracking
        with GoogleMeetController._counter_lock:
            GoogleMeetController._instance_counter += 1
            counter_val = GoogleMeetController._instance_counter
        self._instance_id = f"meet-bot-{counter_val}-{id(self)}"
        self._browser_pid: Optional[int] = None
        self._created_at = datetime.now()
        self._last_activity = datetime.now()

        # Per-instance audio device manager (for PULSE_SINK/PULSE_SOURCE pre-routing)
        self._device_manager: Optional[InstanceDeviceManager] = None
        self._devices: Optional[InstanceDevices] = None

        # Composed subsystems (sign-in, captions, participants, audio, devices)
        self._sign_in = MeetSignIn(self)
        self._captions = MeetCaptions(self)
        self._participants = MeetParticipants(self)
        self._audio = MeetAudio(self)
        self._meet_devices = MeetDevices(self)

        # Register this instance
        GoogleMeetController._instances[self._instance_id] = self

    # Backward-compatible proxies for caption state (used by tests)
    @property
    def _caption_observer_running(self):
        return self._captions._caption_observer_running

    @_caption_observer_running.setter
    def _caption_observer_running(self, value):
        self._captions._caption_observer_running = value

    @property
    def _caption_callback(self):
        return self._captions._caption_callback

    @_caption_callback.setter
    def _caption_callback(self, value):
        self._captions._caption_callback = value

    @property
    def _caption_poll_task(self):
        return self._captions._caption_poll_task

    @_caption_poll_task.setter
    def _caption_poll_task(self, value):
        self._captions._caption_poll_task = value

    # ==================== Audio Routing (delegated to MeetAudio) ====================

    async def _create_virtual_audio_sink(self) -> bool:
        """Create a virtual PulseAudio sink. Delegates to MeetAudio."""
        return await self._audio.create_virtual_audio_sink()

    async def _remove_virtual_audio_sink(self) -> None:
        """Remove the virtual audio sink. Delegates to MeetAudio."""
        await self._audio.remove_virtual_audio_sink()

    def get_audio_sink_name(self) -> Optional[str]:
        """Get the virtual audio sink name. Delegates to MeetAudio."""
        return self._audio.get_audio_sink_name()

    def get_audio_devices(self) -> Optional[InstanceDevices]:
        """Get per-instance audio devices. Delegates to MeetAudio."""
        return self._audio.get_audio_devices()

    def get_monitor_source(self) -> Optional[str]:
        """Get the monitor source name. Delegates to MeetAudio."""
        return self._audio.get_monitor_source()

    def get_pipe_path(self) -> Optional[Path]:
        """Get the named pipe path for TTS injection. Delegates to MeetAudio."""
        return self._audio.get_pipe_path()

    async def _route_browser_audio_to_sink(self) -> None:
        """Route Chrome audio to virtual sink. Delegates to MeetAudio."""
        await self._audio.route_browser_audio_to_sink()

    def unmute_audio(self) -> bool:
        """Move meeting audio to default output. Delegates to MeetAudio."""
        return self._audio.unmute_audio()

    def mute_audio(self) -> bool:
        """Move meeting audio back to null sink. Delegates to MeetAudio."""
        return self._audio.mute_audio()

    def is_audio_muted(self) -> bool:
        """Check if meeting audio is muted. Delegates to MeetAudio."""
        return self._audio.is_audio_muted()

    async def _restore_user_default_source(self) -> None:
        """Restore user's default audio source. Delegates to MeetAudio."""
        await self._audio.restore_user_default_source()

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
            from scripts.common.dbus_base import get_client

            client = get_client("video")
            if not await client.connect():
                logger.warning(
                    f"[{self._instance_id}] Could not connect to video daemon"
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
                    f"[{self._instance_id}] Video daemon start failed: {result}"
                )
                return False

            # Wait for the device to switch to CAPTURE mode
            # With exclusive_caps=1, the device only shows as CAPTURE when actively streaming
            # Chrome will only detect it as a camera when it's in CAPTURE mode
            logger.info(
                f"[{self._instance_id}] Waiting for video device to become active..."
            )
            await asyncio.sleep(1.0)  # Give time for first frames to be written

            # Verify the device is now in capture mode
            import subprocess

            result = subprocess.run(
                ["v4l2-ctl", "--device", video_device, "--all"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "Video Capture" in result.stdout and "Video Output" not in result.stdout:
                logger.info(
                    f"[{self._instance_id}] Device is in CAPTURE mode - Chrome will detect it"
                )
            else:
                logger.warning(
                    f"[{self._instance_id}] Device may not be in pure CAPTURE mode"
                )

            logger.info(f"[{self._instance_id}] Video stream started on {video_device}")
            return True

        except Exception as e:
            logger.warning(f"[{self._instance_id}] Failed to start video stream: {e}")
            return False

    async def _copy_profile_data(self, source_dir: Path, dest_dir: Path) -> None:
        """Copy login cookies and session data from main profile to instance profile."""
        import shutil

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
                    logger.debug(f"Copied {file_rel} to instance profile")
                except Exception as e:
                    logger.warning(f"Failed to copy {file_rel}: {e}")

        for dir_rel in dirs_to_copy:
            src = source_dir / dir_rel
            dst = dest_dir / dir_rel
            if src.exists() and not dst.exists():
                try:
                    shutil.copytree(src, dst)
                    logger.debug(f"Copied {dir_rel} to instance profile")
                except Exception as e:
                    logger.warning(f"Failed to copy {dir_rel}: {e}")

        logger.info(f"[{self._instance_id}] Profile data copied from main profile")

    async def initialize(self, video_enabled: bool = False) -> bool:
        """Initialize the browser with stealth settings.

        Args:
            video_enabled: If True, start full AI video overlay. If False, start black screen.
        """
        self._video_enabled = video_enabled

        try:
            from playwright.async_api import async_playwright

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

            logger.info(f"Starting browser with DISPLAY={display}")

            # ========== CLEANUP ORPHANED DEVICES ==========
            # Remove any stale MeetBot devices from previous sessions
            # This prevents accumulation of orphaned sinks/sources/video devices
            logger.info(
                f"[{self._instance_id}] Cleaning up orphaned MeetBot devices..."
            )
            cleanup_result = await cleanup_orphaned_meetbot_devices(
                active_instance_ids=set()
            )
            if cleanup_result.get("removed_modules") or cleanup_result.get(
                "removed_video_devices"
            ):
                logger.info(
                    f"[{self._instance_id}] Cleanup removed: "
                    f"{len(cleanup_result.get('removed_modules', []))} audio modules, "
                    f"{len(cleanup_result.get('removed_video_devices', []))} video devices"
                )

            # ========== AUDIO PRE-ROUTING ==========
            # Create per-instance audio devices BEFORE launching Chrome
            # This ensures audio is routed correctly from the moment Chrome starts
            logger.info(f"[{self._instance_id}] Creating per-instance audio devices...")
            self._device_manager = InstanceDeviceManager(self._instance_id)
            self._devices = await self._device_manager.create_all()

            if self._devices:
                self._audio_sink_name = self._devices.sink_name
                logger.info(f"[{self._instance_id}] Audio devices ready:")
                logger.info(
                    f"[{self._instance_id}]   Sink: {self._devices.sink_name} (Chrome output)"
                )
                logger.info(
                    f"[{self._instance_id}]   Source: {self._devices.source_name} (Chrome mic input)"
                )
                logger.info(f"[{self._instance_id}]   Pipe: {self._devices.pipe_path}")
            else:
                logger.warning(
                    f"[{self._instance_id}] Failed to create audio devices, falling back to legacy method"
                )

            # Get virtual camera device path for Chrome launch args
            # The video_generator will stream to this device separately
            virtual_camera = None
            if self._devices and self._devices.video_device:
                virtual_camera = self._devices.video_device
                logger.info(
                    f"[{self._instance_id}] Video device available: {virtual_camera}"
                )
            elif Path(self.config.video.virtual_camera_device).exists():
                virtual_camera = self.config.video.virtual_camera_device
                logger.info(
                    f"[{self._instance_id}] Using shared video device: {virtual_camera}"
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
                        logger.info(f"Removed stale lock file: {lock_file}")
                    except Exception as e:
                        logger.warning(f"Could not remove lock file {lock_file}: {e}")
            logger.info(f"Using profile directory: {profile_dir}")

            # Verify avatar image exists
            avatar_path = Path(self.config.avatar.face_image)
            if not avatar_path.exists():
                logger.warning(f"Avatar image not found: {avatar_path}")

            # Launch browser - use real PulseAudio devices from system
            # Device settings are saved in the persistent profile
            # Use instance-specific profile to avoid lock conflicts, but copy cookies from main profile
            instance_profile_dir = profile_dir / f"instance-{self._instance_id}"
            instance_profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"[{self._instance_id}] Using instance profile: {instance_profile_dir}"
            )

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
                logger.info(f"[{self._instance_id}] Pre-routing audio via env vars:")
                logger.info(
                    f"[{self._instance_id}]   PULSE_SINK={self._devices.sink_name}"
                )
                logger.info(
                    f"[{self._instance_id}]   PULSE_SOURCE={self._devices.source_name}"
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
                    f"[{self._instance_id}] Virtual camera available: {virtual_camera}"
                )
                video_ready = await self._start_video_stream(
                    virtual_camera, self._video_enabled
                )
                if video_ready:
                    video_mode = (
                        "full AI overlay" if self._video_enabled else "black screen"
                    )
                    logger.info(
                        f"[{self._instance_id}] Video stream active ({video_mode}) - Chrome will see virtual camera"
                    )
                else:
                    logger.warning(
                        f"[{self._instance_id}] Video stream not ready - Chrome may not see virtual camera"
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
            logger.info(f"[{self._instance_id}] Registered browser close handler")

            # Try to get browser PID
            try:
                # Playwright doesn't expose PID directly, but we can find it
                import psutil

                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        cmdline = proc.info.get("cmdline") or []
                        if any(self._instance_id in str(arg) for arg in cmdline):
                            self._browser_pid = proc.info["pid"]
                            logger.info(
                                f"[{self._instance_id}] Browser PID: {self._browser_pid}"
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
                    f"[{self._instance_id}] Using legacy audio routing (no pre-routing)"
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

            # Don't navigate to meet.google.com here - it redirects to product page when not signed in
            # The browser will navigate directly to the meeting URL when join_meeting is called
            # Audio devices will be initialized when we navigate to the actual meeting

            logger.info(
                "Browser initialized successfully (will navigate when joining meeting)"
            )
            return True

        except ImportError as e:
            error_msg = f"Playwright not installed: {e}. Run: uv add playwright && playwright install chromium"
            logger.error(error_msg)
            if self.state:
                self.state.errors.append(error_msg)

            # Clean up any devices that were created before the import error
            if self._device_manager:
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in launch_browser (device cleanup): {e}"
                    )
                self._device_manager = None
                self._devices = None

            return False
        except Exception as e:
            error_msg = f"Failed to initialize browser: {e}"
            logger.error(error_msg, exc_info=True)
            if self.state:
                self.state.errors.append(error_msg)

            # CRITICAL: Clean up audio devices if browser initialization failed
            # Otherwise devices are orphaned and accumulate on repeated failures
            if self._device_manager:
                logger.info(
                    f"[{self._instance_id}] Cleaning up devices after browser init failure"
                )
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except Exception as cleanup_err:
                    logger.warning(
                        f"[{self._instance_id}] Device cleanup failed: {cleanup_err}"
                    )
                self._device_manager = None
                self._devices = None

            return False

    async def _inject_stealth_scripts(self) -> None:
        """Inject scripts to avoid bot detection."""
        await self.page.add_init_script(
            """
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
        """
        )

    async def sign_in_google(self) -> bool:
        """Sign in to Google using Red Hat SSO. Delegates to MeetSignIn."""
        return await self._sign_in.sign_in_google()

    async def join_meeting(self, meet_url: str) -> bool:  # noqa: C901
        """
        Join a Google Meet meeting.

        Args:
            meet_url: The Google Meet URL (e.g., https://meet.google.com/xxx-xxxx-xxx)

        Returns:
            True if successfully joined, False otherwise.
        """
        logger.info("[JOIN] ========== Starting join_meeting ==========")
        logger.info(f"[JOIN] URL: {meet_url}")

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
            if not await self.initialize(
                video_enabled=getattr(self, "_video_enabled", False)
            ):
                error_msg = "Failed to reinitialize browser after closure"
                logger.error(f"[JOIN] ERROR: {error_msg}")
                if self.state:
                    self.state.errors.append(error_msg)
                return False
            logger.info("[JOIN] Browser reinitialized successfully")

        if not self.page:
            error_msg = "Browser not initialized - page is None"
            logger.error(f"[JOIN] ERROR: {error_msg}")
            self.state.errors.append(error_msg)
            return False

        # Extract meeting ID from URL
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        if not match:
            error_msg = f"Invalid Meet URL format: {meet_url}"
            logger.error(f"[JOIN] ERROR: {error_msg}")
            self.state.errors.append(error_msg)
            return False

        meeting_id = match.group(1)
        logger.info(f"[JOIN] Meeting ID: {meeting_id}")

        # Update state but preserve errors
        old_errors = self.state.errors if self.state else []
        self.state = MeetingState(meeting_id=meeting_id, meeting_url=meet_url)
        self.state.errors = old_errors

        try:
            # Navigate to meeting - use domcontentloaded instead of networkidle (faster, more reliable)
            logger.info("[JOIN] Navigating to meeting URL...")
            await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
            logger.info(f"[JOIN] Navigation complete. Current URL: {self.page.url}")

            # Wait for page to load
            logger.info("[JOIN] Waiting 2s for page to settle...")
            await asyncio.sleep(2)

            # Log page title and URL for debugging
            try:
                title = await self.page.title()
                logger.info(f"[JOIN] Page title: {title}")
                logger.info(f"[JOIN] Current URL after wait: {self.page.url}")
            except Exception as e:
                logger.warning(f"[JOIN] Could not get page title: {e}")

            # Handle permissions dialog - "Do you want people to hear you in the meeting?"
            # This appears before joining and asks about mic/camera permissions
            logger.info("[JOIN] Checking for permissions dialog...")
            await self._handle_permissions_dialog()

            # Handle "Got it" dialog if present
            logger.info("[JOIN] Checking for 'Got it' dialog...")
            try:
                got_it = await self.page.wait_for_selector(
                    self.SELECTORS["got_it_button"], timeout=3000
                )
                if got_it:
                    logger.info("[JOIN] Found 'Got it' dialog - clicking")
                    await got_it.click()
                    await asyncio.sleep(1)
            except Exception:
                logger.info("[JOIN] No 'Got it' dialog found")

            # Check if we need to sign in (look for Sign in button or name input for guest)
            logger.info("[JOIN] Checking if sign-in is required...")
            sign_in_button = (
                await self.page.locator(
                    'div[role="button"]:has-text("Sign in")'
                ).count()
                > 0
            )
            name_input = await self.page.query_selector(self.SELECTORS["name_input"])
            logger.info(
                f"[JOIN] Sign-in button present: {sign_in_button}, Name input present: {name_input is not None}"
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
                        f"[JOIN] Re-navigating to meeting after sign-in (current: {self.page.url})"
                    )
                    await self.page.goto(
                        meet_url, wait_until="domcontentloaded", timeout=30000
                    )
                    await asyncio.sleep(2)
            else:
                logger.info("[JOIN] No sign-in required, proceeding to join")

            # Check again for Chrome sync dialog (it can appear delayed)
            logger.info("[JOIN] Checking for Chrome sync dialog before joining...")
            await self._dismiss_chrome_sync_dialog()

            # UNMUTE microphone (it's a virtual pipe - only produces sound when we write to it)
            # Turn off camera before joining (we use virtual avatar instead)
            logger.info(
                "[JOIN] Setting up audio/video (UNMUTE virtual mic, turn off camera)..."
            )
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
                        f'[data-mdc-dialog-action]:has-text("{btn_text}")',  # Material dialog buttons
                    ]
                    for selector in selectors:
                        locator = self.page.locator(selector)
                        if await locator.count() > 0:
                            join_button = locator.first
                            logger.info(
                                f"Found '{btn_text}' button with selector: {selector}"
                            )
                            break
                except Exception as e:
                    logger.debug(f"Error finding '{btn_text}': {e}")

            # If no button found, wait and retry once
            if not join_button:
                logger.info(
                    "[JOIN] No join button found on first try, waiting 3s and retrying..."
                )

                # Take a screenshot for debugging
                try:
                    screenshot_path = f"/tmp/meet_debug_{meeting_id}.png"
                    await self.page.screenshot(path=screenshot_path)
                    logger.info(f"[JOIN] Debug screenshot saved to: {screenshot_path}")
                except Exception as e:
                    logger.warning(f"[JOIN] Could not save debug screenshot: {e}")

                # Log visible text on page for debugging
                try:
                    body_text = await self.page.inner_text("body")
                    # Truncate to first 500 chars
                    logger.info(
                        f"[JOIN] Page body text (first 500 chars): {body_text[:500]}"
                    )
                except Exception as e:
                    logger.warning(f"[JOIN] Could not get page text: {e}")

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
                                logger.info(
                                    f"[JOIN] Found '{btn_text}' button on retry"
                                )
                                break
                    except Exception as e:
                        logger.debug(
                            f"Suppressed error in join_meeting (button retry): {e}"
                        )

            if join_button:
                logger.info("[JOIN] Clicking join button...")
                await join_button.click()
                logger.info("[JOIN] Join button clicked successfully")

                # Wait for meeting to load
                await asyncio.sleep(3)

                # Handle permissions dialog if it appears
                # "Do you want people to hear you in the meeting?"
                try:
                    mic_button = self.page.locator(
                        'button:has-text("Microphone allowed")'
                    )
                    if await mic_button.count() > 0:
                        logger.info(
                            "Permissions dialog detected - clicking 'Microphone allowed'"
                        )
                        await mic_button.click(force=True)
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.debug(f"No permissions dialog or error: {e}")

                # Handle device selection dialog if it appears
                # This shows microphone and speaker dropdowns
                # We use this opportunity to select the MeetBot virtual camera
                # NOTE: Do NOT press Escape here - in Google Meet it can toggle camera!
                try:
                    device_dialog = self.page.locator(
                        '[aria-label="Settings"], [aria-label="Audio settings"]'
                    )
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
                        except Exception as e:
                            logger.debug(
                                f"Suppressed error in join_meeting (dialog dismiss click): {e}"
                            )
                except Exception as e:
                    logger.debug(f"No device dialog or error: {e}")

                # After permissions dialog, we may need to click Join again
                # Look for "Join anyway" or "Join now" button
                try:
                    for btn_text in ["Join anyway", "Join now"]:
                        join_again = self.page.locator(f'button:has-text("{btn_text}")')
                        if await join_again.count() > 0:
                            logger.info(
                                f"Found '{btn_text}' after permissions - clicking"
                            )
                            await join_again.first.click()
                            await asyncio.sleep(3)
                            break
                except Exception as e:
                    logger.debug(f"No second join button needed: {e}")

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
                    f"[JOIN] ========== SUCCESS: Joined meeting {meeting_id} =========="
                )
                return True
            else:
                logger.error(
                    "[JOIN] ========== FAILED: Join button not found =========="
                )
                logger.error(f"[JOIN] Current URL: {self.page.url}")
                self.state.errors.append("Join button not found")
                return False

        except Exception as e:
            error_msg = f"Failed to join meeting: {e}"
            logger.error(f"[JOIN] ========== EXCEPTION: {error_msg} ==========")
            self.state.errors.append(error_msg)
            return False

    async def enable_captions(self) -> bool:
        """Enable closed captions in the meeting.

        NOTE: We do NOT use keyboard shortcut 'c' because in Google Meet:
        - 'c' toggles the CAMERA, not captions!
        - This was causing the bot to turn off video when trying to enable captions.
        Instead, we click the CC button directly.
        """
        if not self.page or not self.state:
            return False

        try:
            logger.info("Enabling captions via CC button...")

            # First check if captions are already on
            try:
                off_button = self.page.locator('button[aria-label="Turn off captions"]')
                if await off_button.count() > 0:
                    logger.info(
                        "[CAPTIONS] Captions already enabled (found 'Turn off captions' button)"
                    )
                    self.state.captions_enabled = True
                    return True
            except Exception as e:
                logger.debug(
                    f"Suppressed error in enable_captions (check existing): {e}"
                )

            # Find the "Turn on captions" button
            try:
                on_button = self.page.locator('button[aria-label="Turn on captions"]')
                if await on_button.count() > 0:
                    logger.info("[CAPTIONS] Found 'Turn on captions' button")

                    # Get the bounding box and click in the CENTER of the button
                    # This avoids accidentally clicking dropdown arrows or adjacent buttons
                    box = await on_button.first.bounding_box()
                    if box:
                        center_x = box["x"] + box["width"] / 2
                        center_y = box["y"] + box["height"] / 2
                        logger.info(
                            f"[CAPTIONS] Clicking at center ({center_x}, {center_y})"
                        )
                        await self.page.mouse.click(center_x, center_y)
                    else:
                        # Fallback to regular click
                        await on_button.first.click()

                    await asyncio.sleep(1.0)

                    # Verify captions are now on
                    off_button = self.page.locator(
                        'button[aria-label="Turn off captions"]'
                    )
                    if await off_button.count() > 0:
                        logger.info("[CAPTIONS] Captions enabled successfully")
                        self.state.captions_enabled = True

                        # WORKAROUND: Re-enable camera if it got turned off
                        # Google Meet sometimes toggles camera when clicking nearby buttons
                        if self._video_enabled:
                            logger.info(
                                "[CAPTIONS] Checking camera state after captions..."
                            )
                            await asyncio.sleep(0.5)
                            camera_btn = self.page.locator(
                                'button[aria-label="Turn on camera"]'
                            )
                            if await camera_btn.count() > 0:
                                logger.warning(
                                    "[CAPTIONS] Camera was turned OFF! Re-enabling..."
                                )
                                await camera_btn.first.click()
                                await asyncio.sleep(0.5)
                                logger.info("[CAPTIONS] Camera re-enabled")

                        return True
                    else:
                        logger.warning(
                            "[CAPTIONS] Button clicked but captions may not be on"
                        )
                        self.state.captions_enabled = True
                        return True
            except Exception as e:
                logger.debug(f"[CAPTIONS] Direct button click failed: {e}")

            # Method 3: Try through the three-dots menu (slowest)
            logger.info("Trying to enable captions via menu...")
            try:
                more_button = self.page.locator(
                    '[aria-label="More options"], [aria-label="More actions"]'
                )
                if await more_button.count() > 0:
                    await more_button.first.click()
                    await asyncio.sleep(0.5)

                    captions_option = self.page.locator(
                        'li:has-text("captions"), [aria-label*="captions" i]'
                    )
                    if await captions_option.count() > 0:
                        await captions_option.first.click()
                        self.state.captions_enabled = True
                        logger.info("Captions enabled via menu")
                        return True
            except Exception as e:
                logger.debug(f"Menu method failed: {e}")

            logger.warning("Could not enable captions - all methods failed")
            return False

        except Exception as e:
            logger.error(f"Failed to enable captions: {e}")
            return False

    async def _select_camera_in_meeting(self) -> bool:
        """Select MeetBot camera in meeting. Delegates to MeetDevices."""
        return await self._meet_devices.select_camera_in_meeting()

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
                    logger.info(f"Microphone {'muted' if mute else 'unmuted'}")

                return True

        except Exception as e:
            logger.error(f"Failed to toggle mute: {e}")

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
                except Exception:
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
                    logger.info(f"Camera {'enabled' if camera_on else 'disabled'}")
                else:
                    logger.info(f"Camera already {'on' if camera_on else 'off'}")

                return True

        except Exception as e:
            logger.error(f"Failed to toggle camera: {e}")

        return False

    # ==================== Device Selection (delegated to MeetDevices) ====================

    async def _set_devices_via_js(self) -> bool:
        """Set devices via JavaScript MediaDevices API. Delegates to MeetDevices."""
        return await self._meet_devices.set_devices_via_js()

    async def _select_meetbot_devices(self) -> dict:
        """Select all MeetBot virtual devices. Delegates to MeetDevices."""
        return await self._meet_devices.select_meetbot_devices()

    async def _select_meetbot_camera(self) -> bool:
        """Select MeetBot virtual camera. Delegates to MeetDevices."""
        return await self._meet_devices.select_meetbot_camera()

    async def _dismiss_chrome_sync_dialog(self) -> bool:
        """Dismiss Chrome sync dialog. Delegates to MeetSignIn."""
        return await self._sign_in.dismiss_chrome_sync_dialog()

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
                    logger.debug(
                        f"Suppressed error in _dismiss_info_popups (dialog click '{text}'): {e}"
                    )

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
                    logger.debug(
                        f"Suppressed error in _dismiss_info_popups (fallback click '{text}'): {e}"
                    )

        except Exception as e:
            logger.debug(f"Error dismissing info popups: {e}")

    async def start_caption_capture(
        self, callback: Callable[[CaptionEntry], None]
    ) -> None:
        """Start capturing captions via DOM observation. Delegates to MeetCaptions."""
        await self._captions.start_caption_capture(callback)

    async def stop_caption_capture(self) -> None:
        """Stop capturing captions. Delegates to MeetCaptions."""
        await self._captions.stop_caption_capture()

    async def get_captions(self) -> list[CaptionEntry]:
        """Get all captured captions. Delegates to MeetCaptions."""
        return await self._captions.get_captions()

    async def leave_meeting(self) -> bool:
        """Leave the current meeting."""
        if not self.page or not self.state:
            return False

        try:
            # Stop caption capture
            await self.stop_caption_capture()

            # Click leave button
            leave_button = await self.page.wait_for_selector(
                self.SELECTORS["leave_button"], timeout=5000
            )

            if leave_button:
                await leave_button.click()
                self.state.joined = False
                logger.info("Left meeting")
                return True

        except Exception as e:
            logger.error(f"Failed to leave meeting: {e}")

        return False

    async def get_participants(self) -> list[dict]:
        """Get participant list. Delegates to MeetParticipants."""
        return await self._participants.get_participants()

    async def get_participant_count(self) -> int:
        """Get participant count. Delegates to MeetParticipants."""
        return await self._participants.get_participant_count()

    async def close(self, restore_browser_audio: bool = False) -> None:
        """Close the browser and cleanup resources.

        Args:
            restore_browser_audio: If True, restore browser mic connections that were
                                   saved before device creation. Set to True when the
                                   meeting dies unexpectedly (browser crashed, service
                                   restarted, etc.) to ensure user's Chrome keeps mic.
        """
        logger.info(
            f"[{self._instance_id}] Closing browser controller (restore_audio={restore_browser_audio})..."
        )

        # Stop caption capture first (this cancels the polling task)
        try:
            await asyncio.wait_for(self.stop_caption_capture(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"[{self._instance_id}] Timeout stopping caption capture")

        if self.browser:
            try:
                await asyncio.wait_for(self.browser.close(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    f"[{self._instance_id}] Timeout closing browser, forcing..."
                )
                await self.force_kill()
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Error closing browser: {e}")
            self.browser = None

        if hasattr(self, "_playwright") and self._playwright:
            try:
                await asyncio.wait_for(self._playwright.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self._instance_id}] Timeout stopping playwright")
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Error stopping playwright: {e}")
            self._playwright = None

        # Clean up per-instance audio devices (new method)
        if self._device_manager:
            await self._device_manager.cleanup(
                restore_browser_audio=restore_browser_audio
            )
            self._device_manager = None
            self._devices = None
        else:
            # Legacy cleanup
            await self._remove_virtual_audio_sink()

        # Unregister this instance
        if self._instance_id in GoogleMeetController._instances:
            del GoogleMeetController._instances[self._instance_id]

        logger.info(f"[{self._instance_id}] Browser closed")

    def _on_browser_close(self) -> None:
        """Handle browser close event from Playwright.

        This is called IMMEDIATELY when the browser window is closed by the user.
        It sets the _browser_closed flag and triggers async cleanup.

        CRITICAL: This is a sync callback, so we schedule the async cleanup.
        """
        logger.warning(f"[{self._instance_id}] *** BROWSER CLOSE EVENT DETECTED ***")
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
                f"[{self._instance_id}] No event loop for async cleanup, relying on health monitor"
            )

    async def _handle_browser_close_async(self) -> None:
        """Async handler for browser close - cleans up devices immediately."""
        logger.info(
            f"[{self._instance_id}] Running immediate device cleanup after browser close..."
        )

        # Clean up audio devices - RESTORE browser audio since this is unexpected
        if self._device_manager:
            try:
                await self._device_manager.cleanup(restore_browser_audio=True)
                logger.info(f"[{self._instance_id}] Device cleanup completed")
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Device cleanup error: {e}")
            finally:
                self._device_manager = None
                self._devices = None

        # Also run orphan cleanup to catch anything else
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
            )

            results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())
            if results.get("removed_modules") or results.get("killed_processes"):
                logger.info(
                    f"[{self._instance_id}] Orphan cleanup: "
                    f"{len(results.get('removed_modules', []))} modules, "
                    f"{len(results.get('killed_processes', []))} processes"
                )
        except Exception as e:
            logger.warning(f"[{self._instance_id}] Orphan cleanup error: {e}")

        # Unregister this instance
        if self._instance_id in GoogleMeetController._instances:
            del GoogleMeetController._instances[self._instance_id]

        logger.info(f"[{self._instance_id}] Browser close cleanup complete")

    async def force_kill(self) -> bool:
        """Force kill this browser instance and its processes.

        This is called when the browser is unresponsive or crashed.
        Always restores browser audio since this is an unexpected termination.
        """
        logger.warning(f"[{self._instance_id}] Force killing browser instance...")
        killed = False

        # Kill browser process
        if self._browser_pid:
            try:
                import os
                import signal

                os.kill(self._browser_pid, signal.SIGKILL)
                logger.info(
                    f"[{self._instance_id}] Killed browser PID {self._browser_pid}"
                )
                killed = True
            except (ProcessLookupError, PermissionError) as e:
                logger.debug(
                    f"[{self._instance_id}] Browser already dead or inaccessible: {e}"
                )

        # Try to find and kill by instance ID in cmdline
        try:
            import psutil

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    if any(self._instance_id in str(arg) for arg in cmdline):
                        proc.kill()
                        logger.info(
                            f"[{self._instance_id}] Killed process {proc.info['pid']} by cmdline match"
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
        if self._instance_id in GoogleMeetController._instances:
            del GoogleMeetController._instances[self._instance_id]

        return killed

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = datetime.now()

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
    def get_all_instances(cls) -> dict[str, "GoogleMeetController"]:
        """Get all active controller instances."""
        return cls._instances.copy()

    @classmethod
    async def cleanup_hung_instances(cls, max_age_minutes: int = 120) -> list[str]:
        """Find and kill instances that haven't had activity for too long."""
        now = datetime.now()
        killed = []

        for instance_id, controller in list(cls._instances.items()):
            age = (now - controller._last_activity).total_seconds() / 60
            if age > max_age_minutes:
                logger.warning(
                    f"Instance {instance_id} is hung (no activity for {age:.1f} min)"
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

    # ==================== Screenshot Capture ====================

    # Directory for storing meeting screenshots
    SCREENSHOT_DIR = MEETBOT_SCREENSHOTS_DIR

    async def take_screenshot(self) -> Optional[Path]:
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
            logger.debug(f"[{self._instance_id}] Screenshot saved: {screenshot_path}")
            return screenshot_path
        except Exception as e:
            error_msg = str(e)
            # Detect browser/page closure
            if (
                "Target page, context or browser has been closed" in error_msg
                or "Target closed" in error_msg
                or "Browser has been closed" in error_msg
            ):
                logger.error(f"[{self._instance_id}] Browser was closed unexpectedly!")
                self._browser_closed = True
                raise BrowserClosedError("Browser was closed")
            logger.warning(f"[{self._instance_id}] Failed to take screenshot: {e}")
            return None

    def is_browser_closed(self) -> bool:
        """Check if the browser has been closed.

        Checks browser/page state. Returns True only if we're certain the browser is closed.
        """
        # Check flag first (set by error handlers when we catch closure exceptions)
        if getattr(self, "_browser_closed", False):
            logger.debug(
                f"[{self._instance_id}] is_browser_closed: _browser_closed flag is True"
            )
            return True

        # Check if page exists and is closed
        try:
            if self.page is None:
                logger.warning(f"[{self._instance_id}] is_browser_closed: page is None")
                self._browser_closed = True
                return True
            if self.page.is_closed():
                logger.warning(
                    f"[{self._instance_id}] is_browser_closed: page.is_closed() returned True"
                )
                self._browser_closed = True
                return True

        except Exception as e:
            # Any error checking means browser is likely dead
            logger.warning(
                f"[{self._instance_id}] is_browser_closed: exception during check: {e}"
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
            f"[{self._instance_id}] Starting screenshot loop (every {interval_seconds}s)"
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
                    f"[{self._instance_id}] Browser closed - stopping screenshot loop"
                )
                self.state.joined = False
                break
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Screenshot loop error: {e}")
                consecutive_failures += 1

            # If too many consecutive failures, assume browser is dead
            if consecutive_failures >= max_failures:
                logger.error(
                    f"[{self._instance_id}] Too many screenshot failures - browser likely closed"
                )
                self._browser_closed = True
                self.state.joined = False
                break

            await asyncio.sleep(interval_seconds)

        logger.info(f"[{self._instance_id}] Screenshot loop stopped")

    def get_screenshot_path(self) -> Optional[Path]:
        """Get the path to the latest screenshot for this meeting."""
        if not self.state.meeting_id:
            return None
        screenshot_path = self.SCREENSHOT_DIR / f"{self.state.meeting_id}.png"
        return screenshot_path if screenshot_path.exists() else None


# Convenience function
async def create_meet_controller() -> GoogleMeetController:
    """Create and initialize a Google Meet controller."""
    controller = GoogleMeetController()
    await controller.initialize()
    return controller
