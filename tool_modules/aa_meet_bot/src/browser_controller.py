"""
Browser Controller for Google Meet.

Uses Playwright with stealth mode to:
- Join Google Meet meetings
- Enable captions
- Capture caption text via DOM observation
- Inject virtual camera/microphone
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class CaptionEntry:
    """A single caption entry from the meeting."""
    speaker: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.speaker}: {self.text}"


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
        "join_button": 'button:has-text("Join now"), button:has-text("Ask to join"), div[role="button"]:has-text("Join now"), div[role="button"]:has-text("Ask to join")',
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
        "caption_speaker": '.zs7s8d, .KcIKyf',
        
        # Meeting info
        "participant_count": '[data-participant-count], .rua5Nb',
        "meeting_title": '.u6vdEc, [data-meeting-title]',
    }
    
    # Class-level counter for unique instance IDs
    _instance_counter = 0
    _instances: dict[str, "GoogleMeetController"] = {}  # Track all instances
    
    def __init__(self):
        self.config = get_config()
        self.browser = None
        self.context = None
        self.page = None
        # Initialize state early so errors can be captured during initialization
        self.state: MeetingState = MeetingState(meeting_id="", meeting_url="")
        self._caption_callback: Optional[Callable[[CaptionEntry], None]] = None
        self._caption_observer_running = False
        self._playwright = None
        self._ffmpeg_process = None  # For virtual camera feed
        
        # Unique instance tracking
        GoogleMeetController._instance_counter += 1
        self._instance_id = f"meet-bot-{GoogleMeetController._instance_counter}-{id(self)}"
        self._browser_pid: Optional[int] = None
        self._ffmpeg_pid: Optional[int] = None
        self._created_at = datetime.now()
        self._last_activity = datetime.now()
        
        # Register this instance
        GoogleMeetController._instances[self._instance_id] = self
    
    async def initialize(self) -> bool:
        """Initialize the browser with stealth settings."""
        import os
        import subprocess
        
        try:
            from playwright.async_api import async_playwright
            
            # Check DISPLAY is set (required for headless=False)
            display = os.environ.get('DISPLAY')
            if not display:
                logger.error("DISPLAY environment variable not set - cannot launch visible browser")
                if self.state:
                    self.state.errors.append("DISPLAY not set - browser requires X11 display")
                return False
            
            logger.info(f"Starting browser with DISPLAY={display}")
            
            # Start virtual camera feed - Chrome needs video data to recognize the device
            virtual_camera = self.config.video.virtual_camera_device
            if Path(virtual_camera).exists():
                logger.info(f"[{self._instance_id}] Starting virtual camera feed on {virtual_camera}...")
                try:
                    self._ffmpeg_process = subprocess.Popen(
                        [
                            "ffmpeg", "-f", "lavfi", 
                            "-i", "testsrc=size=640x480:rate=30",
                            "-f", "v4l2", "-pix_fmt", "yuv420p",
                            virtual_camera
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._ffmpeg_pid = self._ffmpeg_process.pid
                    await asyncio.sleep(1)  # Give ffmpeg time to start
                    logger.info(f"[{self._instance_id}] Virtual camera feed started (PID: {self._ffmpeg_pid})")
                except Exception as e:
                    logger.warning(f"[{self._instance_id}] Could not start virtual camera feed: {e}")
            
            self._playwright = await async_playwright().start()
            
            # Use Chrome with a persistent profile for the bot account
            profile_dir = Path(self.config.bot_account.profile_dir).expanduser()
            profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Using profile directory: {profile_dir}")
            
            # Verify avatar image exists
            avatar_path = Path(self.config.avatar.face_image)
            if not avatar_path.exists():
                logger.warning(f"Avatar image not found: {avatar_path}")
            
            # Launch browser - use real PulseAudio devices from system
            # Device settings are saved in the persistent profile
            logger.info("Launching Chromium browser...")
            
            # Use unique profile dir per instance to avoid conflicts
            instance_profile_dir = profile_dir / self._instance_id
            instance_profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[{self._instance_id}] Using instance profile: {instance_profile_dir}")
            
            self.browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(instance_profile_dir),
                headless=False,  # Must be visible for virtual camera
                args=[
                    # Minimal flags - same as working simple test
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-gpu-sandbox",
                    "--disable-dev-shm-usage",
                    # Add instance ID for process identification
                    f"--user-agent=MeetBot/{self._instance_id}",
                ],
                ignore_default_args=["--enable-automation"],
                permissions=["camera", "microphone"],
            )
            
            # Try to get browser PID
            try:
                # Playwright doesn't expose PID directly, but we can find it
                import psutil
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmdline = proc.info.get('cmdline') or []
                        if any(self._instance_id in str(arg) for arg in cmdline):
                            self._browser_pid = proc.info['pid']
                            logger.info(f"[{self._instance_id}] Browser PID: {self._browser_pid}")
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except ImportError:
                logger.debug("psutil not available for PID tracking")
            
            self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()
            
            # Skip stealth scripts - they may break Google Meet UI
            # await self._inject_stealth_scripts()
            
            # Navigate to meet.google.com first to initialize audio devices
            # This ensures the browser's audio subsystem is ready before joining a meeting
            # Use a short timeout - if it hangs, we'll proceed anyway
            logger.info("Navigating to meet.google.com to initialize audio devices...")
            try:
                await self.page.goto("https://meet.google.com", wait_until="domcontentloaded", timeout=5000)
            except Exception as e:
                logger.warning(f"meet.google.com took too long, proceeding anyway: {e}")
            await asyncio.sleep(2)  # Brief pause for audio devices to enumerate
            
            logger.info("Browser initialized successfully")
            return True
            
        except ImportError as e:
            error_msg = f"Playwright not installed: {e}. Run: pip install playwright && playwright install chromium"
            logger.error(error_msg)
            if self.state:
                self.state.errors.append(error_msg)
            return False
        except Exception as e:
            error_msg = f"Failed to initialize browser: {e}"
            logger.error(error_msg, exc_info=True)
            if self.state:
                self.state.errors.append(error_msg)
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
    
    async def sign_in_google(self) -> bool:
        """
        Sign in to Google using Red Hat SSO.
        
        Handles the OAuth flow:
        1. Click "Sign in" on Meet page
        2. Enter email on Google login
        3. Redirect to Red Hat SSO
        4. Enter username/password
        5. Return to Meet
        
        Returns:
            True if sign-in successful, False otherwise.
        """
        from tool_modules.aa_meet_bot.src.config import get_google_credentials
        
        if not self.page:
            logger.error("Browser not initialized")
            return False
        
        try:
            # Get credentials from redhatter API
            logger.info("Fetching credentials from redhatter API...")
            username, password = await get_google_credentials(self.config.bot_account.email)
            
            # Check if we need to sign in - look for Sign in button on Meet page
            # Google Meet uses a div[role="button"] with "Sign in" text
            sign_in_button = None
            
            # Try to find the Sign in button using Playwright locator (better for text matching)
            try:
                # Use locator for better text matching
                locator = self.page.locator('div[role="button"]:has-text("Sign in")')
                if await locator.count() > 0:
                    sign_in_button = locator.first
                    logger.info("Found Sign in button (div role=button)")
            except Exception as e:
                logger.debug(f"Locator search failed: {e}")
            
            # Fallback: try span with Sign in text
            if not sign_in_button:
                try:
                    locator = self.page.locator('span:has-text("Sign in")').first
                    if await locator.count() > 0:
                        sign_in_button = locator
                        logger.info("Found Sign in span")
                except Exception:
                    pass
            
            if sign_in_button:
                logger.info("Clicking Sign in button...")
                await sign_in_button.click()
                await asyncio.sleep(3)
            
            # Step 1: Wait for Google login page and enter email
            try:
                logger.info("Waiting for Google login page...")
                email_input = await self.page.wait_for_selector(
                    '#identifierId',  # Specific Google email input ID
                    timeout=15000
                )
                if email_input:
                    logger.info(f"Entering email: {self.config.bot_account.email}")
                    await email_input.fill(self.config.bot_account.email)
                    await asyncio.sleep(1)
                    
                    # Click Next button
                    next_button = await self.page.wait_for_selector(
                        '#identifierNext',
                        timeout=5000
                    )
                    if next_button:
                        logger.info("Clicking Next...")
                        await next_button.click()
                        await asyncio.sleep(5)  # Wait for redirect to SSO
            except Exception as e:
                logger.warning(f"Google email input not found: {e}")
                return False
            
            # Step 2: Wait for Red Hat SSO page and enter credentials
            try:
                logger.info("Waiting for Red Hat SSO page...")
                saml_username = await self.page.wait_for_selector(
                    '#username',  # Red Hat SSO username field
                    timeout=15000
                )
                if saml_username:
                    logger.info("Red Hat SSO page detected - entering credentials")
                    
                    # Enter Kerberos ID (username)
                    await saml_username.fill(username)
                    await asyncio.sleep(0.5)
                    
                    # Enter PIN and token (password)
                    saml_password = await self.page.wait_for_selector(
                        '#password',
                        timeout=5000
                    )
                    if saml_password:
                        await saml_password.fill(password)
                        await asyncio.sleep(0.5)
                    
                    # Click "Log in to SSO" submit button
                    submit_button = await self.page.wait_for_selector(
                        '#submit',
                        timeout=5000
                    )
                    if submit_button:
                        logger.info("Clicking 'Log in to SSO'...")
                        await submit_button.click()
                        await asyncio.sleep(10)  # Wait for SSO processing and redirect
                    
                    logger.info("SSO login submitted, waiting for redirect to Meet...")
                    
                    # Wait for redirect back to Meet
                    try:
                        await self.page.wait_for_url("**/meet.google.com/**", timeout=30000)
                        logger.info("Successfully signed in via Red Hat SSO")
                        return True
                    except Exception:
                        # Check if we're already on meet
                        if "meet.google.com" in self.page.url:
                            logger.info("Already on Meet page after SSO")
                            return True
                        raise
                    
            except Exception as e:
                logger.warning(f"Red Hat SSO login failed: {e}")
                self.state.errors.append(f"SSO login failed: {e}")
                return False
            
            # Check if we're now signed in (back on Meet page)
            current_url = self.page.url
            if "meet.google.com" in current_url:
                # Check if sign-in link is gone
                sign_in_link = await self.page.query_selector(self.SELECTORS["sign_in_link"])
                if not sign_in_link:
                    logger.info("Sign-in appears successful")
                    return True
            
            logger.warning("Sign-in flow completed but status unclear")
            return True
            
        except Exception as e:
            error_msg = f"Sign-in failed: {e}"
            logger.error(error_msg)
            self.state.errors.append(error_msg)
            return False
    
    async def join_meeting(self, meet_url: str) -> bool:
        """
        Join a Google Meet meeting.
        
        Args:
            meet_url: The Google Meet URL (e.g., https://meet.google.com/xxx-xxxx-xxx)
        
        Returns:
            True if successfully joined, False otherwise.
        """
        if not self.page:
            error_msg = "Browser not initialized - page is None"
            logger.error(error_msg)
            self.state.errors.append(error_msg)
            return False
        
        # Extract meeting ID from URL
        match = re.search(r'meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})', meet_url)
        if not match:
            error_msg = f"Invalid Meet URL format: {meet_url}"
            logger.error(error_msg)
            self.state.errors.append(error_msg)
            return False
        
        meeting_id = match.group(1)
        # Update state but preserve errors
        old_errors = self.state.errors if self.state else []
        self.state = MeetingState(meeting_id=meeting_id, meeting_url=meet_url)
        self.state.errors = old_errors
        
        try:
            # Navigate to meeting - use domcontentloaded instead of networkidle (faster, more reliable)
            logger.info(f"Navigating to meeting: {meet_url}")
            await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for page to load
            await asyncio.sleep(2)
            
            # Handle permissions dialog - "Do you want people to hear you in the meeting?"
            # This appears before joining and asks about mic/camera permissions
            await self._handle_permissions_dialog()
            
            # Handle "Got it" dialog if present
            try:
                got_it = await self.page.wait_for_selector(
                    self.SELECTORS["got_it_button"],
                    timeout=3000
                )
                if got_it:
                    await got_it.click()
                    await asyncio.sleep(1)
            except Exception:
                pass  # Dialog not present
            
            # Check if we need to sign in (look for Sign in button or name input for guest)
            sign_in_button = await self.page.locator('div[role="button"]:has-text("Sign in")').count() > 0
            name_input = await self.page.query_selector(self.SELECTORS["name_input"])
            
            if sign_in_button or name_input:
                logger.info("Sign-in required - initiating OAuth flow")
                if not await self.sign_in_google():
                    self.state.errors.append("Failed to sign in to Google")
                    return False
                
                # After sign-in, we should already be on the Meet page
                # Wait a moment for the page to settle
                await asyncio.sleep(3)
                
                # Check if we need to re-navigate (sometimes SSO redirects elsewhere)
                if "meet.google.com" not in self.page.url:
                    logger.info("Re-navigating to meeting after sign-in...")
                    await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
            
            # Mute microphone and turn off camera before joining
            if self.config.auto_mute_on_join:
                await self._toggle_mute(mute=True)
            
            # Always turn off camera for notes bot (we don't need video)
            await self._toggle_camera(camera_on=False)
            
            # Click join button - try multiple selectors
            logger.info("Looking for Join button...")
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
                            logger.info(f"Found '{btn_text}' button with selector: {selector}")
                            break
                except Exception as e:
                    logger.debug(f"Error finding '{btn_text}': {e}")
            
            # If no button found, wait and retry once
            if not join_button:
                logger.info("No join button found, waiting 3s and retrying...")
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
                                logger.info(f"Found '{btn_text}' button on retry")
                                break
                    except Exception:
                        pass
            
            if join_button:
                await join_button.click()
                logger.info("Clicked join button")
                
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
                except Exception as e:
                    logger.debug(f"No permissions dialog or error: {e}")
                
                # Handle device selection dialog if it appears
                # This shows microphone and speaker dropdowns
                try:
                    # Look for the settings/gear icon in device dialog or dismiss it
                    device_dialog = self.page.locator('[aria-label="Settings"], [aria-label="Audio settings"]')
                    if await device_dialog.count() > 0:
                        logger.info("Device selection dialog detected")
                        # Press Escape to dismiss it - fake devices should already be selected
                        await self.page.keyboard.press('Escape')
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.debug(f"No device dialog or error: {e}")
                
                # After permissions dialog, we may need to click Join again
                # Look for "Join anyway" or "Join now" button
                try:
                    for btn_text in ["Join anyway", "Join now"]:
                        join_again = self.page.locator(f'button:has-text("{btn_text}")')
                        if await join_again.count() > 0:
                            logger.info(f"Found '{btn_text}' after permissions - clicking")
                            await join_again.first.click()
                            await asyncio.sleep(3)
                            break
                except Exception as e:
                    logger.debug(f"No second join button needed: {e}")
                
                # Also try to close any other dialogs with X button
                try:
                    close_buttons = self.page.locator('[aria-label="Close"]')
                    if await close_buttons.count() > 0:
                        await close_buttons.first.click()
                        await asyncio.sleep(1)
                except Exception:
                    pass
                
                # Wait a bit more for meeting to fully load
                await asyncio.sleep(5)
                
                # Check if we're in the meeting
                self.state.joined = True
                
                # Enable captions if configured
                if self.config.auto_enable_captions:
                    await self.enable_captions()
                
                logger.info(f"Successfully joined meeting: {meeting_id}")
                return True
            else:
                self.state.errors.append("Join button not found")
                return False
                
        except Exception as e:
            error_msg = f"Failed to join meeting: {e}"
            logger.error(error_msg)
            self.state.errors.append(error_msg)
            return False
    
    async def enable_captions(self) -> bool:
        """Enable closed captions in the meeting."""
        if not self.page or not self.state:
            return False
        
        try:
            logger.info("Attempting to enable captions...")
            
            # Method 1: Try direct CC button selectors
            cc_selectors = [
                '[aria-label*="captions" i]',
                '[aria-label*="subtitles" i]',
                '[data-tooltip*="captions" i]',
                'button:has-text("CC")',
                '[jsname="r8qRAd"]',
            ]
            
            for selector in cc_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click()
                        self.state.captions_enabled = True
                        logger.info(f"Captions enabled via selector: {selector}")
                        return True
                except Exception:
                    continue
            
            # Method 2: Try through the three-dots menu
            logger.info("Trying to enable captions via menu...")
            try:
                # Click the three-dots/more options button
                more_button = self.page.locator('[aria-label="More options"], [aria-label="More actions"], button:has-text("More options")')
                if await more_button.count() > 0:
                    await more_button.first.click()
                    await asyncio.sleep(1)
                    
                    # Look for captions option in menu
                    captions_option = self.page.locator('text="Turn on captions", text="Captions", [aria-label*="captions" i]')
                    if await captions_option.count() > 0:
                        await captions_option.first.click()
                        self.state.captions_enabled = True
                        logger.info("Captions enabled via menu")
                        return True
            except Exception as e:
                logger.debug(f"Menu method failed: {e}")
            
            # Method 3: Try keyboard shortcut (c key toggles captions in Meet)
            logger.info("Trying keyboard shortcut for captions...")
            try:
                await self.page.keyboard.press('c')
                await asyncio.sleep(1)
                self.state.captions_enabled = True
                logger.info("Captions toggled via keyboard shortcut 'c'")
                return True
            except Exception as e:
                logger.debug(f"Keyboard shortcut failed: {e}")
            
            logger.warning("Could not find captions button")
            return False
            
        except Exception as e:
            logger.error(f"Failed to enable captions: {e}")
            return False
    
    async def _toggle_mute(self, mute: bool = True) -> bool:
        """Toggle microphone mute state."""
        if not self.page:
            return False
        
        try:
            # Find mute button
            mute_button = await self.page.wait_for_selector(
                self.SELECTORS["mute_button"],
                timeout=5000
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
                    camera_button = await self.page.wait_for_selector(selector, timeout=2000)
                    if camera_button:
                        break
                except Exception:
                    continue
            
            if camera_button:
                # Get aria-label to determine current state
                aria_label = await camera_button.get_attribute("aria-label") or ""
                aria_label_lower = aria_label.lower()
                
                # Determine current state - if label says "turn off", camera is currently ON
                camera_currently_on = "turn off" in aria_label_lower or "stop" in aria_label_lower
                
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
            dialog_text = self.page.locator('text="Do you want people to hear you in the meeting?"')
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
                        logger.info(f"Trying to click 'Microphone allowed' ({selector})")
                        await mic_only.first.click(force=True, timeout=3000)
                        await asyncio.sleep(1)
                        # Check if dialog is gone
                        if await dialog_text.count() == 0:
                            logger.info("Dialog dismissed via Microphone allowed button")
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
    
    async def start_caption_capture(
        self,
        callback: Callable[[CaptionEntry], None]
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
        
        # Inject DEBOUNCED caption observer
        # Google Meet corrects text in-place, so we wait for text to "settle"
        # Only emit when no changes for 800ms (speech pause) - captures corrected text
        await self.page.evaluate("""
            () => {
                window._meetBotCaptions = [];
                window._meetBotCurrentSpeaker = 'Unknown';
                window._meetBotLastText = '';
                window._meetBotDebounceTimer = null;
                window._meetBotLastEmittedText = '';
                
                function findCaptionContainer() {
                    return document.querySelector('[aria-label="Captions"]');
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
                    if (!container) return 'Unknown';
                    const img = container.querySelector('img');
                    if (img && img.parentElement) {
                        const spans = img.parentElement.querySelectorAll('span');
                        for (const span of spans) {
                            const t = span.textContent.trim();
                            if (t && t.length > 1 && t.length < 50) return t;
                        }
                    }
                    return 'Unknown';
                }
                
                function emitCaption() {
                    const text = window._meetBotLastText;
                    if (!text || text === window._meetBotLastEmittedText) return;
                    
                    // Only emit the NEW portion since last emit
                    let newText = text;
                    if (text.startsWith(window._meetBotLastEmittedText)) {
                        newText = text.slice(window._meetBotLastEmittedText.length).trim();
                    }
                    
                    if (newText) {
                        window._meetBotCaptions.push({
                            speaker: window._meetBotCurrentSpeaker,
                            text: newText,
                            ts: Date.now()
                        });
                    }
                    window._meetBotLastEmittedText = text;
                }
                
                const observer = new MutationObserver((mutations) => {
                    const container = findCaptionContainer();
                    if (!container) return;
                    
                    const speaker = getSpeaker(container);
                    if (speaker !== 'Unknown') {
                        window._meetBotCurrentSpeaker = speaker;
                    }
                    
                    const captionDiv = findCaptionTextDiv(container);
                    if (!captionDiv) return;
                    
                    const fullText = (captionDiv.textContent || '').trim();
                    if (!fullText) return;
                    
                    // Text changed - reset debounce timer
                    window._meetBotLastText = fullText;
                    
                    if (window._meetBotDebounceTimer) {
                        clearTimeout(window._meetBotDebounceTimer);
                    }
                    
                    // Wait 800ms of no changes before emitting (allows corrections to settle)
                    window._meetBotDebounceTimer = setTimeout(emitCaption, 800);
                });
                
                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    characterData: true
                });
                
                window._meetBotObserver = observer;
                console.log('[MeetBot] Debounced caption observer started (800ms settle time)');
            }
        """)
        
        # Start polling for new captions
        asyncio.create_task(self._poll_captions())
        logger.info("Caption capture started")
    
    async def _poll_captions(self) -> None:
        """Poll for settled/corrected captions from the JS observer buffer."""
        while self._caption_observer_running and self.page:
            try:
                # Fetch and clear the caption buffer - these are already debounced/corrected
                captions = await self.page.evaluate("""
                    () => {
                        const c = window._meetBotCaptions || [];
                        window._meetBotCaptions = [];
                        return c;
                    }
                """)
                
                for cap in captions:
                    speaker = cap.get("speaker", "Unknown")
                    text = cap.get("text", "")
                    ts = cap.get("ts", 0)
                    
                    if text.strip():
                        entry = CaptionEntry(
                            speaker=speaker,
                            text=text.strip(),
                            timestamp=datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
                        )
                        if self.state:
                            self.state.caption_buffer.append(entry)
                        if self._caption_callback:
                            self._caption_callback(entry)
                        logger.debug(f"Caption: [{speaker}] {text[:50]}...")
                
                await asyncio.sleep(0.5)  # Poll every 500ms
                
            except Exception as e:
                if "Target closed" in str(e):
                    break
                logger.debug(f"Caption poll error: {e}")
                await asyncio.sleep(1)
    
    async def stop_caption_capture(self) -> None:
        """Stop capturing captions."""
        self._caption_observer_running = False
        self._caption_callback = None
        
        if self.page:
            try:
                await self.page.evaluate("""
                    () => {
                        if (window._meetBotObserver) {
                            window._meetBotObserver.disconnect();
                        }
                    }
                """)
            except Exception:
                pass
        
        logger.info("Caption capture stopped")
    
    async def get_captions(self) -> list[CaptionEntry]:
        """Get all captured captions."""
        if self.state:
            return self.state.caption_buffer.copy()
        return []
    
    async def leave_meeting(self) -> bool:
        """Leave the current meeting."""
        if not self.page or not self.state:
            return False
        
        try:
            # Stop caption capture
            await self.stop_caption_capture()
            
            # Click leave button
            leave_button = await self.page.wait_for_selector(
                self.SELECTORS["leave_button"],
                timeout=5000
            )
            
            if leave_button:
                await leave_button.click()
                self.state.joined = False
                logger.info("Left meeting")
                return True
                
        except Exception as e:
            logger.error(f"Failed to leave meeting: {e}")
        
        return False
    
    async def close(self) -> None:
        """Close the browser and cleanup resources."""
        logger.info(f"[{self._instance_id}] Closing browser controller...")
        
        await self.stop_caption_capture()
        
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Error closing browser: {e}")
            self.browser = None
        
        if hasattr(self, '_playwright') and self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Error stopping playwright: {e}")
            self._playwright = None
        
        # Stop virtual camera feed
        if hasattr(self, '_ffmpeg_process') and self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=5)
            except Exception:
                try:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None
            self._ffmpeg_pid = None
            logger.info(f"[{self._instance_id}] Virtual camera feed stopped")
        
        # Unregister this instance
        if self._instance_id in GoogleMeetController._instances:
            del GoogleMeetController._instances[self._instance_id]
        
        logger.info(f"[{self._instance_id}] Browser closed")
    
    async def force_kill(self) -> bool:
        """Force kill this browser instance and its processes."""
        logger.warning(f"[{self._instance_id}] Force killing browser instance...")
        killed = False
        
        # Kill ffmpeg process
        if self._ffmpeg_pid:
            try:
                import os
                import signal
                os.kill(self._ffmpeg_pid, signal.SIGKILL)
                logger.info(f"[{self._instance_id}] Killed ffmpeg PID {self._ffmpeg_pid}")
                killed = True
            except (ProcessLookupError, PermissionError) as e:
                logger.debug(f"[{self._instance_id}] ffmpeg already dead or inaccessible: {e}")
        
        # Kill browser process
        if self._browser_pid:
            try:
                import os
                import signal
                os.kill(self._browser_pid, signal.SIGKILL)
                logger.info(f"[{self._instance_id}] Killed browser PID {self._browser_pid}")
                killed = True
            except (ProcessLookupError, PermissionError) as e:
                logger.debug(f"[{self._instance_id}] Browser already dead or inaccessible: {e}")
        
        # Try to find and kill by instance ID in cmdline
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    if any(self._instance_id in str(arg) for arg in cmdline):
                        proc.kill()
                        logger.info(f"[{self._instance_id}] Killed process {proc.info['pid']} by cmdline match")
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass
        
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
            "ffmpeg_pid": self._ffmpeg_pid,
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
                logger.warning(f"Instance {instance_id} is hung (no activity for {age:.1f} min)")
                await controller.force_kill()
                killed.append(instance_id)
        
        return killed
    
    async def unmute_and_speak(self) -> bool:
        """Unmute microphone to allow bot to speak."""
        return await self._toggle_mute(mute=False)
    
    async def mute(self) -> bool:
        """Mute microphone after speaking."""
        return await self._toggle_mute(mute=True)


# Convenience function
async def create_meet_controller() -> GoogleMeetController:
    """Create and initialize a Google Meet controller."""
    controller = GoogleMeetController()
    await controller.initialize()
    return controller


