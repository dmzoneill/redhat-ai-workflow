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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDeviceManager, InstanceDevices

# Import centralized paths
try:
    from server.paths import MEETBOT_SCREENSHOTS_DIR
except ImportError:
    # Fallback for standalone usage
    MEETBOT_SCREENSHOTS_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot" / "screenshots"

logger = logging.getLogger(__name__)


class BrowserClosedError(Exception):
    """Raised when the browser has been closed unexpectedly."""

    pass


@dataclass
class CaptionEntry:
    """A single caption entry from the meeting."""

    speaker: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    caption_id: int = 0  # Unique ID for tracking updates
    is_update: bool = False  # True if this is an update to a previous caption

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
        "caption_speaker": ".zs7s8d, .KcIKyf",
        # Meeting info
        "participant_count": "[data-participant-count], .rua5Nb",
        "meeting_title": ".u6vdEc, [data-meeting-title]",
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
        self._caption_poll_task: Optional[asyncio.Task] = None  # Track caption polling task
        self._playwright = None
        self._ffmpeg_process = None  # For virtual camera feed
        self._audio_sink_name: Optional[str] = None  # Virtual audio sink for meeting output

        # Unique instance tracking
        GoogleMeetController._instance_counter += 1
        self._instance_id = f"meet-bot-{GoogleMeetController._instance_counter}-{id(self)}"
        self._browser_pid: Optional[int] = None
        self._ffmpeg_pid: Optional[int] = None
        self._created_at = datetime.now()
        self._last_activity = datetime.now()

        # Per-instance audio device manager (for PULSE_SINK/PULSE_SOURCE pre-routing)
        self._device_manager: Optional[InstanceDeviceManager] = None
        self._devices: Optional[InstanceDevices] = None

        # Register this instance
        GoogleMeetController._instances[self._instance_id] = self

    async def _create_virtual_audio_sink(self) -> bool:
        """Create a virtual PulseAudio sink for meeting audio output.

        This creates a null sink that:
        - Captures Chrome's audio output (meeting audio)
        - Doesn't play on speakers
        - Can be monitored if you want to listen (via the .monitor source)

        Returns:
            True if sink was created successfully.
        """
        import subprocess

        # Create a unique sink name for this instance
        sink_name = f"meet_bot_{self._instance_id.replace('-', '_')}"
        sink_description = f"Meet Bot Audio ({self._instance_id})"

        try:
            # Check if sink already exists
            result = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True)
            if sink_name in result.stdout:
                logger.info(f"[{self._instance_id}] Virtual audio sink already exists: {sink_name}")
                self._audio_sink_name = sink_name
                return True

            # Create null sink (audio goes nowhere, but can be monitored)
            result = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={sink_name}",
                    f'sink_properties=device.description="{sink_description}"',
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                self._audio_sink_name = sink_name
                logger.info(f"[{self._instance_id}] Created virtual audio sink: {sink_name}")
                logger.info(f"[{self._instance_id}] To listen: pactl set-default-source {sink_name}.monitor")
                return True
            else:
                logger.warning(f"[{self._instance_id}] Failed to create audio sink: {result.stderr}")
                return False

        except Exception as e:
            logger.warning(f"[{self._instance_id}] Could not create virtual audio sink: {e}")
            return False

    async def _remove_virtual_audio_sink(self) -> None:
        """Remove the virtual audio sink when done."""
        import subprocess

        if not self._audio_sink_name:
            return

        try:
            # Find the module index for our sink
            result = subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True)

            for line in result.stdout.strip().split("\n"):
                if self._audio_sink_name in line:
                    module_index = line.split()[0]
                    subprocess.run(["pactl", "unload-module", module_index])
                    logger.info(f"[{self._instance_id}] Removed virtual audio sink: {self._audio_sink_name}")
                    break

            self._audio_sink_name = None
        except Exception as e:
            logger.warning(f"[{self._instance_id}] Could not remove virtual audio sink: {e}")

    def get_audio_sink_name(self) -> Optional[str]:
        """Get the name of the virtual audio sink for this instance.

        To listen to meeting audio:
            pactl set-default-source <sink_name>.monitor
            # Or use pavucontrol to route the monitor to your headphones
        """
        return self._audio_sink_name

    def get_audio_devices(self) -> Optional[InstanceDevices]:
        """Get the per-instance audio devices for this controller.

        Returns:
            InstanceDevices with sink_name, source_name, pipe_path, etc.
            None if devices weren't created (legacy mode).
        """
        return self._devices

    def get_monitor_source(self) -> Optional[str]:
        """Get the monitor source name for capturing meeting audio.

        This is the source that captures all audio going to the sink.
        Use with parec or other audio capture tools.

        Returns:
            Monitor source name (e.g., "meet_bot_abc123.monitor")
        """
        if self._device_manager:
            return self._device_manager.get_monitor_source()
        elif self._audio_sink_name:
            return f"{self._audio_sink_name}.monitor"
        return None

    def get_pipe_path(self) -> Optional[Path]:
        """Get the named pipe path for TTS audio injection.

        Write PCM audio (16kHz, 16-bit, mono) to this pipe to inject
        audio as the Chrome microphone input.

        Returns:
            Path to the named pipe, or None if not available.
        """
        if self._devices and self._devices.pipe_path:
            return self._devices.pipe_path
        return None

    async def _route_browser_audio_to_sink(self) -> None:
        """Route Chrome's audio output to our virtual sink.

        This runs in the background and periodically checks for Chrome audio streams,
        moving them to our virtual sink so meeting audio doesn't play on speakers.
        """
        import subprocess

        if not self._audio_sink_name:
            return

        logger.info(f"[{self._instance_id}] Starting audio routing monitor...")

        streams_routed = 0

        # Wait for meeting to be joined (up to 60 seconds)
        for _ in range(60):
            if self.state and self.state.joined:
                break
            await asyncio.sleep(1)

        if not self.state or not self.state.joined:
            logger.warning(f"[{self._instance_id}] Audio routing: meeting not joined, giving up")
            return

        logger.info(f"[{self._instance_id}] Meeting joined, starting audio routing...")

        # Keep checking for new audio streams while in the meeting
        while self.state and self.state.joined:
            await asyncio.sleep(3)  # Check every 3 seconds

            try:
                # Get detailed info about all sink inputs
                result = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True)

                # Parse sink inputs and find Chrome/Chromium ones not on our sink
                # IMPORTANT: Only route OUR browser instance, not user's regular Chrome
                current_input_id = None
                current_sink = None
                is_chrome = False
                current_pid = None

                for line in result.stdout.split("\n"):
                    line = line.strip()

                    if line.startswith("Sink Input #"):
                        # Save previous input if it was CONFIRMED our browser and not on our sink
                        if (
                            current_input_id
                            and is_chrome
                            and current_sink
                            and self._audio_sink_name not in current_sink
                        ):
                            # Only route if it's our browser PID (or we don't have PID yet)
                            if not self._browser_pid or current_pid == str(self._browser_pid):
                                self._move_sink_input(current_input_id)
                                streams_routed += 1
                            else:
                                logger.debug(
                                    f"[{self._instance_id}] Skipping audio stream {current_input_id} (PID {current_pid} != our PID {self._browser_pid})"
                                )

                        # Start new input
                        current_input_id = line.split("#")[1]
                        current_sink = None
                        is_chrome = False
                        current_pid = None

                    elif "Sink:" in line and current_input_id:
                        # Check which sink this stream is on
                        current_sink = line.split(":")[-1].strip()

                    elif "application.name" in line.lower():
                        # Only match if application.name explicitly contains chrome/chromium
                        app_name = line.split("=")[-1].strip().strip('"').lower()
                        if app_name in ["google chrome", "chromium", "chrome"]:
                            is_chrome = True
                            logger.debug(f"[{self._instance_id}] Found Chrome audio stream: {current_input_id}")

                    elif "application.process.id" in line.lower():
                        current_pid = line.split("=")[-1].strip().strip('"')

                # Don't forget the last one
                if current_input_id and is_chrome and current_sink and self._audio_sink_name not in current_sink:
                    if not self._browser_pid or current_pid == str(self._browser_pid):
                        self._move_sink_input(current_input_id)
                        streams_routed += 1

            except Exception as e:
                logger.debug(f"[{self._instance_id}] Audio routing check failed: {e}")

        if streams_routed > 0:
            logger.info(f"[{self._instance_id}] Audio routing monitor stopped (routed {streams_routed} streams)")
        else:
            logger.info(f"[{self._instance_id}] Audio routing monitor stopped")

    def _move_sink_input(self, sink_input_id: str) -> bool:
        """Move a sink input to our virtual audio sink."""
        import subprocess

        if not self._audio_sink_name:
            return False

        try:
            result = subprocess.run(
                ["pactl", "move-sink-input", sink_input_id, self._audio_sink_name], capture_output=True, text=True
            )
            if result.returncode == 0:
                logger.info(f"[{self._instance_id}] Routed audio stream {sink_input_id} to virtual sink")
                return True
            else:
                logger.debug(f"Failed to move sink-input {sink_input_id}: {result.stderr}")
                return False
        except Exception as e:
            logger.debug(f"Failed to move sink-input {sink_input_id}: {e}")
            return False

    def _get_chrome_sink_inputs(self, only_our_browser: bool = True) -> list[str]:
        """Get Chrome/Chromium sink input IDs.

        Args:
            only_our_browser: If True, only return sink inputs from our browser PID.
                            If False, return all Chrome/Chromium sink inputs.
        """
        import subprocess

        sink_inputs = []
        try:
            result = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True)

            current_input_id = None
            is_chrome = False
            current_pid = None

            for line in result.stdout.split("\n"):
                line = line.strip()

                if line.startswith("Sink Input #"):
                    # Check if previous input matches our criteria
                    if current_input_id and is_chrome:
                        if not only_our_browser or (self._browser_pid and current_pid == str(self._browser_pid)):
                            sink_inputs.append(current_input_id)
                        elif only_our_browser and not self._browser_pid:
                            # If we don't have browser PID yet, include all Chrome inputs
                            sink_inputs.append(current_input_id)
                    current_input_id = line.split("#")[1]
                    is_chrome = False
                    current_pid = None
                elif "application.name" in line.lower():
                    app_name = line.split("=")[1].strip().strip('"').lower()
                    if app_name in ["google chrome", "chromium", "chrome"]:
                        is_chrome = True
                elif "application.process.id" in line.lower():
                    current_pid = line.split("=")[1].strip().strip('"')

            # Don't forget the last one
            if current_input_id and is_chrome:
                if not only_our_browser or (self._browser_pid and current_pid == str(self._browser_pid)):
                    sink_inputs.append(current_input_id)
                elif only_our_browser and not self._browser_pid:
                    sink_inputs.append(current_input_id)

        except Exception as e:
            logger.debug(f"Failed to get Chrome sink inputs: {e}")

        return sink_inputs

    def unmute_audio(self) -> bool:
        """Move meeting audio to default output so user can hear it.

        Returns:
            True if audio was successfully unmuted.
        """
        import subprocess

        try:
            # Get the default sink
            result = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True)
            default_sink = result.stdout.strip()

            if not default_sink:
                logger.warning("Could not determine default audio sink")
                return False

            # Get Chrome sink inputs and move them to default
            sink_inputs = self._get_chrome_sink_inputs()
            if not sink_inputs:
                logger.warning("No Chrome audio streams found to unmute")
                return False

            success = False
            for sink_input_id in sink_inputs:
                result = subprocess.run(
                    ["pactl", "move-sink-input", sink_input_id, default_sink], capture_output=True, text=True
                )
                if result.returncode == 0:
                    logger.info(f"[{self._instance_id}] Unmuted: moved stream {sink_input_id} to {default_sink}")
                    success = True

            return success

        except Exception as e:
            logger.error(f"Failed to unmute audio: {e}")
            return False

    def mute_audio(self) -> bool:
        """Move meeting audio back to null sink so user can't hear it.

        Returns:
            True if audio was successfully muted.
        """
        import subprocess

        if not self._audio_sink_name:
            logger.warning("No virtual audio sink available for muting")
            return False

        try:
            # Get Chrome sink inputs and move them to our null sink
            sink_inputs = self._get_chrome_sink_inputs()
            if not sink_inputs:
                logger.warning("No Chrome audio streams found to mute")
                return False

            success = False
            for sink_input_id in sink_inputs:
                result = subprocess.run(
                    ["pactl", "move-sink-input", sink_input_id, self._audio_sink_name], capture_output=True, text=True
                )
                if result.returncode == 0:
                    logger.info(f"[{self._instance_id}] Muted: moved stream {sink_input_id} to {self._audio_sink_name}")
                    success = True

            return success

        except Exception as e:
            logger.error(f"Failed to mute audio: {e}")
            return False

    def is_audio_muted(self) -> bool:
        """Check if meeting audio is currently muted (routed to null sink).

        Returns:
            True if audio is muted (on null sink), False if audible.
        """
        import subprocess

        if not self._audio_sink_name:
            return False

        try:
            result = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True)

            current_input_id = None
            is_chrome = False
            current_sink = None

            for line in result.stdout.split("\n"):
                line = line.strip()

                if line.startswith("Sink Input #"):
                    if current_input_id and is_chrome:
                        # Check if this Chrome stream is on our null sink
                        if current_sink and self._audio_sink_name in current_sink:
                            return True  # Found at least one muted stream
                    current_input_id = line.split("#")[1]
                    is_chrome = False
                    current_sink = None
                elif line.startswith("Sink:"):
                    current_sink = line.split(":")[1].strip()
                elif "application.name" in line.lower():
                    app_name = line.split("=")[1].strip().strip('"').lower()
                    if app_name in ["google chrome", "chromium", "chrome"]:
                        is_chrome = True

            # Check the last one
            if current_input_id and is_chrome and current_sink:
                if self._audio_sink_name in current_sink:
                    return True

            return False

        except Exception as e:
            logger.debug(f"Failed to check audio mute state: {e}")
            return False

    async def _restore_user_default_source(self) -> None:
        """
        Restore the user's original microphone as the default audio source.

        PipeWire/Chrome may switch the default source to our virtual mic when
        Chrome connects to it. This method ONLY restores the system default -
        it does NOT move any browser streams.

        Why no stream moving?
        1. The bot's Chrome uses PULSE_SOURCE env var - it's already routed correctly
        2. The user's Chrome should stay on whatever source it was using
        3. Moving streams is error-prone and can break user's audio

        This works with ANY audio device - built-in mic, USB headset, Bluetooth, etc.
        """
        import subprocess

        # Wait for Chrome to fully initialize and potentially mess with defaults
        await asyncio.sleep(2)

        try:
            # First, check what the current default is
            result = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True)
            current_default = result.stdout.strip()

            # If current default is already NOT a meetbot source, we're good
            if current_default and "meet_bot" not in current_default.lower():
                logger.info(f"[{self._instance_id}] Default source is already user's device: {current_default}")
                return

            # Current default is meetbot - need to find and restore user's source
            # Get all available sources
            result = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True)

            # Find a non-meetbot, non-monitor source (user's actual mic/headset)
            user_source = None
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    source_name = parts[1]
                    # Skip monitors and meetbot sources
                    if ".monitor" not in source_name and "meet_bot" not in source_name.lower():
                        user_source = source_name
                        # Don't break - keep looking in case there's a USB/Bluetooth device
                        # USB/Bluetooth devices typically have "usb" or "bluez" in the name
                        if "usb" in source_name.lower() or "bluez" in source_name.lower():
                            break  # Prefer external devices

            if user_source:
                # Use pw-metadata for persistent default (pactl gets overridden by PipeWire)
                subprocess.run(
                    ["pw-metadata", "-n", "default", "0", "default.audio.source", f'{{"name":"{user_source}"}}'],
                    capture_output=True,
                )
                logger.info(f"[{self._instance_id}] Restored default source via pw-metadata: {user_source}")
            else:
                logger.warning(f"[{self._instance_id}] No user audio source found to restore")

        except Exception as e:
            logger.warning(f"[{self._instance_id}] Failed to restore default source: {e}")

    async def _move_user_browser_to_original_source(self, target_source: str) -> None:
        """
        DEPRECATED: This function is no longer used.

        We no longer move browser streams because:
        1. The bot's Chrome uses PULSE_SOURCE env var - already routed correctly
        2. The user's Chrome should stay on whatever source it was using
        3. Moving streams is error-prone and breaks user's audio

        Keeping this function stub for backwards compatibility.
        """
        logger.debug(f"[{self._instance_id}] _move_user_browser_to_original_source called but disabled")
        return

        # DISABLED CODE BELOW - kept for reference
        import subprocess

        try:
            # Get the index for the target source
            result = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True)

            target_index = None
            for line in result.stdout.strip().split("\n"):
                if target_source in line:
                    target_index = line.split("\t")[0]
                    break

            if not target_index:
                logger.warning(f"[{self._instance_id}] Could not find index for source: {target_source}")
                return

            # Get all source outputs
            result = subprocess.run(["pactl", "list", "source-outputs"], capture_output=True, text=True)

            # Helper to check if a PID belongs to our browser (including child processes)
            def is_our_browser_pid(audio_pid: str) -> bool:
                """Check if audio_pid is our browser or a child of our browser."""
                if not self._browser_pid or not audio_pid:
                    return False

                try:
                    audio_pid_int = int(audio_pid)

                    # Direct match
                    if audio_pid_int == self._browser_pid:
                        return True

                    # Check if audio process is a child of our browser
                    # Chrome's audio service runs as a subprocess with our browser as parent
                    try:
                        import psutil

                        proc = psutil.Process(audio_pid_int)
                        # Check parent chain (up to 3 levels)
                        for _ in range(3):
                            parent = proc.parent()
                            if parent is None:
                                break
                            if parent.pid == self._browser_pid:
                                return True
                            proc = parent
                    except (psutil.NoSuchProcess, psutil.AccessDenied, ImportError):
                        pass

                    # Fallback: check via /proc filesystem
                    try:
                        with open(f"/proc/{audio_pid}/stat", "r") as f:
                            stat = f.read().split()
                            ppid = int(stat[3])  # Parent PID is field 4 (0-indexed: 3)
                            if ppid == self._browser_pid:
                                return True
                    except (FileNotFoundError, IndexError, ValueError):
                        pass

                except (ValueError, TypeError):
                    pass

                return False

            current_output_id = None
            current_source = None
            current_pid = None
            is_browser = False

            for line in result.stdout.split("\n"):
                line = line.strip()

                if line.startswith("Source Output #"):
                    # Process previous output
                    if current_output_id and is_browser and current_source:
                        if "meet_bot" in str(current_source).lower():
                            # This browser is on meetbot mic - check if it's ours
                            if not is_our_browser_pid(current_pid):
                                # This is user's browser - move to their source
                                subprocess.run(
                                    ["pactl", "move-source-output", current_output_id, target_index],
                                    capture_output=True,
                                )
                                logger.info(
                                    f"[{self._instance_id}] Moved user browser stream {current_output_id} "
                                    f"(PID {current_pid}) to {target_source}"
                                )
                            else:
                                logger.debug(
                                    f"[{self._instance_id}] Keeping our browser stream {current_output_id} "
                                    f"(PID {current_pid}, parent {self._browser_pid}) on meetbot mic"
                                )

                    # Start new output
                    current_output_id = line.split("#")[1]
                    current_source = None
                    current_pid = None
                    is_browser = False

                elif "Source:" in line:
                    current_source = line.split(":", 1)[1].strip() if ":" in line else ""

                elif "application.name" in line.lower():
                    app = line.lower()
                    if "chrome" in app or "chromium" in app or "firefox" in app:
                        is_browser = True

                elif "application.process.id" in line.lower():
                    try:
                        current_pid = line.split("=")[1].strip().strip('"')
                    except (IndexError, ValueError):
                        pass

            # Don't forget last output
            if current_output_id and is_browser and current_source:
                if "meet_bot" in str(current_source).lower():
                    if not is_our_browser_pid(current_pid):
                        subprocess.run(
                            ["pactl", "move-source-output", current_output_id, target_index], capture_output=True
                        )
                        logger.info(
                            f"[{self._instance_id}] Moved user browser stream {current_output_id} "
                            f"(PID {current_pid}) to {target_source}"
                        )

        except Exception as e:
            logger.warning(f"[{self._instance_id}] Failed to move browser streams: {e}")

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

    async def initialize(self) -> bool:
        """Initialize the browser with stealth settings."""
        import subprocess

        try:
            from playwright.async_api import async_playwright

            # Check DISPLAY is set (required for headless=False)
            display = os.environ.get("DISPLAY")
            if not display:
                logger.error("DISPLAY environment variable not set - cannot launch visible browser")
                if self.state:
                    self.state.errors.append("DISPLAY not set - browser requires X11 display")
                return False

            logger.info(f"Starting browser with DISPLAY={display}")

            # ========== AUDIO PRE-ROUTING ==========
            # Create per-instance audio devices BEFORE launching Chrome
            # This ensures audio is routed correctly from the moment Chrome starts
            logger.info(f"[{self._instance_id}] Creating per-instance audio devices...")
            self._device_manager = InstanceDeviceManager(self._instance_id)
            self._devices = await self._device_manager.create_all()

            if self._devices:
                self._audio_sink_name = self._devices.sink_name
                logger.info(f"[{self._instance_id}] Audio devices ready:")
                logger.info(f"[{self._instance_id}]   Sink: {self._devices.sink_name} (Chrome output)")
                logger.info(f"[{self._instance_id}]   Source: {self._devices.source_name} (Chrome mic input)")
                logger.info(f"[{self._instance_id}]   Pipe: {self._devices.pipe_path}")
            else:
                logger.warning(f"[{self._instance_id}] Failed to create audio devices, falling back to legacy method")

            # Start virtual camera feed - Chrome needs video data to recognize the device
            # Use per-instance video device if available, otherwise fall back to shared device
            virtual_camera = None
            if self._devices and self._devices.video_device:
                virtual_camera = self._devices.video_device
                logger.info(f"[{self._instance_id}] Using per-instance video device: {virtual_camera}")
            elif Path(self.config.video.virtual_camera_device).exists():
                virtual_camera = self.config.video.virtual_camera_device
                logger.info(f"[{self._instance_id}] Using shared video device: {virtual_camera}")

            if virtual_camera and Path(virtual_camera).exists():
                logger.info(f"[{self._instance_id}] Starting virtual camera feed on {virtual_camera}...")
                try:
                    # Use pre-rendered idle video if available, otherwise generate it
                    idle_video = self.config.data_dir / "idle_avatar.mp4"
                    avatar_path = Path(self.config.avatar.face_image)

                    # Generate idle video if it doesn't exist but avatar image does
                    if not idle_video.exists() and avatar_path.exists():
                        logger.info(f"[{self._instance_id}] Generating idle avatar video (one-time)...")
                        await self._generate_idle_video(avatar_path, idle_video)

                    if idle_video.exists():
                        # Loop pre-rendered video - extremely low CPU (just file reading)
                        ffmpeg_cmd = [
                            "ffmpeg",
                            "-re",  # Read at native framerate
                            "-stream_loop",
                            "-1",  # Loop video infinitely
                            "-i",
                            str(idle_video),
                            "-f",
                            "v4l2",
                            "-pix_fmt",
                            "yuv420p",
                            virtual_camera,
                        ]
                        logger.info(f"[{self._instance_id}] Using pre-rendered idle video: {idle_video}")
                    else:
                        # Fallback: solid color at 1fps (minimal CPU)
                        ffmpeg_cmd = [
                            "ffmpeg",
                            "-re",
                            "-f",
                            "lavfi",
                            "-i",
                            f"color=c=0x2d2d2d:s={self.config.video.width}x{self.config.video.height}:r=1",
                            "-f",
                            "v4l2",
                            "-pix_fmt",
                            "yuv420p",
                            virtual_camera,
                        ]
                        logger.warning(f"[{self._instance_id}] No idle video or avatar, using solid color")

                    self._ffmpeg_process = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._ffmpeg_pid = self._ffmpeg_process.pid
                    await asyncio.sleep(1)  # Give ffmpeg time to start
                    logger.info(f"[{self._instance_id}] Virtual camera feed started (PID: {self._ffmpeg_pid})")
                except Exception as e:
                    logger.warning(f"[{self._instance_id}] Could not start virtual camera feed: {e}")
            else:
                logger.warning(f"[{self._instance_id}] No video device available, skipping camera feed")

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
            logger.info(f"[{self._instance_id}] Using instance profile: {instance_profile_dir}")

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
                logger.info(f"[{self._instance_id}]   PULSE_SINK={self._devices.sink_name}")
                logger.info(f"[{self._instance_id}]   PULSE_SOURCE={self._devices.source_name}")

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
                ],
                ignore_default_args=["--enable-automation"],
                permissions=["camera", "microphone"],
                env=browser_env,  # Critical: routes audio BEFORE any streams created
            )

            # Try to get browser PID
            try:
                # Playwright doesn't expose PID directly, but we can find it
                import psutil

                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        cmdline = proc.info.get("cmdline") or []
                        if any(self._instance_id in str(arg) for arg in cmdline):
                            self._browser_pid = proc.info["pid"]
                            logger.info(f"[{self._instance_id}] Browser PID: {self._browser_pid}")
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
                logger.info(f"[{self._instance_id}] Using legacy audio routing (no pre-routing)")
                asyncio.create_task(self._route_browser_audio_to_sink())

            # CRITICAL: Restore the user's default audio source
            # PipeWire/Chrome may have switched the default to our virtual source
            # This runs in the background to restore it after Chrome settles
            asyncio.create_task(self._restore_user_default_source())

            self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()

            # Skip stealth scripts - they may break Google Meet UI
            # await self._inject_stealth_scripts()

            # Don't navigate to meet.google.com here - it redirects to product page when not signed in
            # The browser will navigate directly to the meeting URL when join_meeting is called
            # Audio devices will be initialized when we navigate to the actual meeting

            logger.info("Browser initialized successfully (will navigate when joining meeting)")
            return True

        except ImportError as e:
            error_msg = f"Playwright not installed: {e}. Run: pip install playwright && playwright install chromium"
            logger.error(error_msg)
            if self.state:
                self.state.errors.append(error_msg)

            # Clean up any devices that were created before the import error
            if self._device_manager:
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except Exception:
                    pass
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
                logger.info(f"[{self._instance_id}] Cleaning up devices after browser init failure")
                try:
                    await self._device_manager.cleanup(restore_browser_audio=False)
                except Exception as cleanup_err:
                    logger.warning(f"[{self._instance_id}] Device cleanup failed: {cleanup_err}")
                self._device_manager = None
                self._devices = None

            # Also clean up ffmpeg if it was started
            if self._ffmpeg_process:
                try:
                    self._ffmpeg_process.terminate()
                    self._ffmpeg_process.wait(timeout=5)
                except Exception:
                    pass
                self._ffmpeg_process = None
                self._ffmpeg_pid = None

            return False

    async def _generate_idle_video(self, avatar_path: Path, output_path: Path) -> bool:
        """
        Generate a 1-minute idle avatar video for looping.

        This is a one-time operation that creates a pre-rendered video file.
        Looping this file uses ~0.5% CPU vs ~25% for real-time generation.

        Args:
            avatar_path: Path to the avatar image
            output_path: Where to save the generated video

        Returns:
            True if video was generated successfully
        """
        import subprocess

        width = self.config.video.width
        height = self.config.video.height
        fps = 5  # Low fps for idle - saves space and CPU
        duration = 60  # 1 minute loop

        # Build ffmpeg command to create video from static image
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-loop",
            "1",
            "-i",
            str(avatar_path),
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",  # Fast encoding
            "-crf",
            "28",  # Reasonable quality, small file
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-t",
            str(duration),
            str(output_path),
        ]

        try:
            logger.info(f"[{self._instance_id}] Running: {' '.join(ffmpeg_cmd)}")
            result = subprocess.run(
                ffmpeg_cmd, capture_output=True, text=True, timeout=120  # 2 minute timeout for generation
            )

            if result.returncode == 0 and output_path.exists():
                file_size = output_path.stat().st_size / 1024 / 1024  # MB
                logger.info(
                    f"[{self._instance_id}] Generated idle video: {output_path} "
                    f"({file_size:.1f} MB, {duration}s @ {fps}fps)"
                )
                return True
            else:
                logger.error(f"[{self._instance_id}] Failed to generate idle video: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"[{self._instance_id}] Idle video generation timed out")
            return False
        except Exception as e:
            logger.error(f"[{self._instance_id}] Error generating idle video: {e}")
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
                    "#identifierId", timeout=15000  # Specific Google email input ID
                )
                if email_input:
                    logger.info(f"Entering email: {self.config.bot_account.email}")
                    await email_input.fill(self.config.bot_account.email)
                    await asyncio.sleep(1)

                    # Click Next button
                    next_button = await self.page.wait_for_selector("#identifierNext", timeout=5000)
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
                    "#username", timeout=15000  # Red Hat SSO username field
                )
                if saml_username:
                    logger.info("Red Hat SSO page detected - entering credentials")

                    # Enter Kerberos ID (username)
                    await saml_username.fill(username)
                    await asyncio.sleep(0.5)

                    # Enter PIN and token (password)
                    saml_password = await self.page.wait_for_selector("#password", timeout=5000)
                    if saml_password:
                        await saml_password.fill(password)
                        await asyncio.sleep(0.5)

                    # Click "Log in to SSO" submit button
                    submit_button = await self.page.wait_for_selector("#submit", timeout=5000)
                    if submit_button:
                        logger.info("Clicking 'Log in to SSO'...")
                        await submit_button.click()
                        await asyncio.sleep(10)  # Wait for SSO processing and redirect

                    logger.info("SSO login submitted, waiting for redirect to Meet...")

                    # Wait for redirect back to Meet (or intermediate verification page)
                    try:
                        # Wait up to 30s for either Meet or a verification page
                        for _ in range(30):
                            await asyncio.sleep(1)
                            current_url = self.page.url

                            # Check for Google "Verify it's you" / account confirmation page
                            if "speedbump" in current_url or "samlconfirmaccount" in current_url:
                                logger.info("Google verification page detected, clicking Continue...")
                                try:
                                    # The Continue button has nested structure: button > span.VfPpkd-vQzf8d with text
                                    # Try multiple selectors to find the actual clickable button
                                    continue_selectors = [
                                        'button:has(span:text-is("Continue"))',  # Button containing span with exact text
                                        'button.VfPpkd-LgbsSe:has-text("Continue")',  # Google's Material button class
                                        'button[jsname="LgbsSe"]:has-text("Continue")',  # Button with jsname
                                        'span.VfPpkd-vQzf8d:text-is("Continue")',  # The span itself (click it)
                                    ]

                                    clicked = False
                                    for selector in continue_selectors:
                                        try:
                                            btn = self.page.locator(selector).first
                                            if await btn.count() > 0:
                                                logger.info(f"Found Continue button with selector: {selector}")
                                                await btn.click(force=True, timeout=5000)
                                                logger.info("Clicked Continue on verification page")
                                                clicked = True
                                                await asyncio.sleep(3)
                                                break
                                        except Exception as e:
                                            logger.debug(f"Selector {selector} failed: {e}")

                                    if not clicked:
                                        # Last resort: find by role and text
                                        logger.info("Trying role-based selector for Continue...")
                                        await self.page.get_by_role("button", name="Continue").click(timeout=5000)
                                        logger.info("Clicked Continue via role selector")
                                        await asyncio.sleep(3)

                                except Exception as e:
                                    logger.warning(f"Failed to click Continue: {e}")

                            # Check if we're back on Meet
                            if "meet.google.com" in self.page.url:
                                logger.info("Successfully signed in via Red Hat SSO")
                                return True

                        # Timeout - check final state
                        if "meet.google.com" in self.page.url:
                            logger.info("Already on Meet page after SSO")
                            return True
                        raise Exception("Timeout waiting for redirect to Meet")
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
        logger.info(f"[JOIN] ========== Starting join_meeting ==========")
        logger.info(f"[JOIN] URL: {meet_url}")

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
            logger.info(f"[JOIN] Navigating to meeting URL...")
            await self.page.goto(meet_url, wait_until="domcontentloaded", timeout=30000)
            logger.info(f"[JOIN] Navigation complete. Current URL: {self.page.url}")

            # Wait for page to load
            logger.info(f"[JOIN] Waiting 2s for page to settle...")
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
            logger.info(f"[JOIN] Checking for permissions dialog...")
            await self._handle_permissions_dialog()

            # Handle "Got it" dialog if present
            logger.info(f"[JOIN] Checking for 'Got it' dialog...")
            try:
                got_it = await self.page.wait_for_selector(self.SELECTORS["got_it_button"], timeout=3000)
                if got_it:
                    logger.info(f"[JOIN] Found 'Got it' dialog - clicking")
                    await got_it.click()
                    await asyncio.sleep(1)
            except Exception:
                logger.info(f"[JOIN] No 'Got it' dialog found")

            # Check if we need to sign in (look for Sign in button or name input for guest)
            logger.info(f"[JOIN] Checking if sign-in is required...")
            sign_in_button = await self.page.locator('div[role="button"]:has-text("Sign in")').count() > 0
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
                    logger.info(f"[JOIN] Re-navigating to meeting after sign-in (current: {self.page.url})")
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

            # Always turn off camera for notes bot (we don't need video)
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
                            logger.info(f"Found '{btn_text}' button with selector: {selector}")
                            break
                except Exception as e:
                    logger.debug(f"Error finding '{btn_text}': {e}")

            # If no button found, wait and retry once
            if not join_button:
                logger.info("[JOIN] No join button found on first try, waiting 3s and retrying...")

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
                    logger.info(f"[JOIN] Page body text (first 500 chars): {body_text[:500]}")
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
                                logger.info(f"[JOIN] Found '{btn_text}' button on retry")
                                break
                    except Exception:
                        pass

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
                        await self.page.keyboard.press("Escape")
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

                # Brief wait for meeting UI to stabilize
                logger.info("[JOIN] Waiting 2s for meeting UI to stabilize...")
                await asyncio.sleep(2)

                # Dismiss any info popups (like "Others may see your video differently")
                await self._dismiss_info_popups()

                # Check if we're in the meeting
                self.state.joined = True
                logger.info(f"[JOIN] Meeting state set to joined=True")

                # Enable captions if configured
                if self.config.auto_enable_captions:
                    logger.info("[JOIN] Auto-enabling captions...")
                    await self.enable_captions()

                logger.info(f"[JOIN] ========== SUCCESS: Joined meeting {meeting_id} ==========")
                return True
            else:
                logger.error(f"[JOIN] ========== FAILED: Join button not found ==========")
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

        Uses keyboard shortcut 'c' as the fastest and most reliable method.
        """
        if not self.page or not self.state:
            return False

        try:
            logger.info("Enabling captions via keyboard shortcut 'c'...")

            # Method 1: Keyboard shortcut is fastest and most reliable
            # Press 'c' to toggle captions - works immediately
            await self.page.keyboard.press("c")
            await asyncio.sleep(0.3)  # Brief wait for UI to respond

            # Verify captions are enabled by checking for caption container
            for _ in range(5):  # Check up to 5 times over 2.5 seconds
                container = await self.page.query_selector('[aria-label="Captions"], .a4cQT, [jsname="dsyhDe"]')
                if container:
                    self.state.captions_enabled = True
                    logger.info("Captions enabled successfully via keyboard shortcut")
                    return True
                await asyncio.sleep(0.5)

            # Method 2: Try clicking the CC button directly
            logger.info("Keyboard shortcut didn't work, trying CC button...")
            cc_selectors = [
                '[aria-label*="caption" i]',
                '[aria-label*="subtitle" i]',
                '[data-tooltip*="caption" i]',
                'button[aria-label*="Turn on captions"]',
                '[jsname="r8qRAd"]',
            ]

            for selector in cc_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click()
                        await asyncio.sleep(0.5)
                        self.state.captions_enabled = True
                        logger.info(f"Captions enabled via button: {selector}")
                        return True
                except Exception:
                    continue

            # Method 3: Try through the three-dots menu (slowest)
            logger.info("Trying to enable captions via menu...")
            try:
                more_button = self.page.locator('[aria-label="More options"], [aria-label="More actions"]')
                if await more_button.count() > 0:
                    await more_button.first.click()
                    await asyncio.sleep(0.5)

                    captions_option = self.page.locator('li:has-text("captions"), [aria-label*="captions" i]')
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

    async def _toggle_mute(self, mute: bool = True) -> bool:
        """Toggle microphone mute state."""
        if not self.page:
            return False

        try:
            # Find mute button
            mute_button = await self.page.wait_for_selector(self.SELECTORS["mute_button"], timeout=5000)

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

            if "Sign in to Chromium" in page_content or "Sign in to Chrome" in page_content:
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
                    except:
                        pass

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
                await self.page.get_by_role("button", name="Use Chromium without an account").click(timeout=3000)
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

    async def _dismiss_info_popups(self) -> None:
        """Dismiss info popups like 'Others may see your video differently'.

        These popups have a 'Got it' button that needs to be clicked.
        """
        if not self.page:
            return

        try:
            # Common button texts for info popups
            button_texts = [
                "Got it",
                "OK",
                "Dismiss",
                "Close",
            ]

            for text in button_texts:
                try:
                    # Try exact text match
                    button = self.page.locator(f'button:has-text("{text}")')
                    if await button.count() > 0:
                        await button.first.click()
                        logger.info(f"Dismissed popup by clicking '{text}' button")
                        await asyncio.sleep(0.5)
                except Exception:
                    pass

            # Also try aria-label based selectors
            try:
                got_it = self.page.locator('[aria-label="Got it"], [aria-label="Dismiss"]')
                if await got_it.count() > 0:
                    await got_it.first.click()
                    logger.info("Dismissed popup via aria-label")
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Error dismissing info popups: {e}")

    async def start_caption_capture(self, callback: Callable[[CaptionEntry], None]) -> None:
        """
        Start capturing captions via DOM observation.

        Args:
            callback: Function to call with each new caption entry.
        """
        if not self.page or self._caption_observer_running:
            return

        self._caption_callback = callback
        self._caption_observer_running = True

        # Inject DEBOUNCED caption observer with UPDATE-IN-PLACE support
        # Google Meet corrects text in-place, so we:
        # 1. Wait for text to "settle" (800ms no changes)
        # 2. Use UPDATE mode for refinements of the same utterance (not new entries)
        # 3. Only create NEW entries when speaker changes or it's clearly a new sentence
        await self.page.evaluate(
            """
            () => {
                window._meetBotCaptions = [];
                window._meetBotCurrentSpeaker = 'Unknown';
                window._meetBotLastText = '';
                window._meetBotDebounceTimer = null;
                window._meetBotLastEmittedText = '';
                window._meetBotLastEmittedId = null;  // Track ID for updates
                window._meetBotLastSpeakerForText = 'Unknown';
                window._meetBotCaptionIdCounter = 0;

                function findCaptionContainer() {
                    // Try multiple selectors for the caption container
                    return document.querySelector('[aria-label="Captions"]') ||
                           document.querySelector('.a4cQT') ||
                           document.querySelector('[jsname="dsyhDe"]');
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
                    if (!container) return null;

                    // Method 1: Look for speaker name near avatar image
                    const img = container.querySelector('img');
                    if (img) {
                        // Check parent and siblings for name
                        let parent = img.parentElement;
                        for (let i = 0; i < 3 && parent; i++) {
                            const spans = parent.querySelectorAll('span');
                            for (const span of spans) {
                                const t = span.textContent.trim();
                                // Name should be reasonable length, not contain common UI text
                                if (t && t.length > 1 && t.length < 50 &&
                                    !t.includes('Jump') && !t.includes('caption') &&
                                    !t.includes('English') && !t.includes('Live')) {
                                    return t;
                                }
                            }
                            parent = parent.parentElement;
                        }
                    }

                    // Method 2: Look for speaker class patterns
                    const speakerEl = container.querySelector('.zs7s8d, .KcIKyf, [data-speaker-name]');
                    if (speakerEl) {
                        const t = speakerEl.textContent.trim();
                        if (t && t.length > 1 && t.length < 50) return t;
                    }

                    return null;
                }

                // Normalize text for comparison (lowercase, collapse whitespace)
                function normalizeText(text) {
                    return (text || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                }

                // Check if newText is a refinement of oldText (same utterance, just corrected/extended)
                function isRefinement(oldText, newText) {
                    if (!oldText) return false;
                    const oldNorm = normalizeText(oldText);
                    const newNorm = normalizeText(newText);

                    // Same text (case correction only)
                    if (oldNorm === newNorm) return true;

                    // New text starts with old text (extension)
                    if (newNorm.startsWith(oldNorm)) return true;

                    // Old text starts with new text (correction that shortened)
                    if (oldNorm.startsWith(newNorm)) return true;

                    // Check if they share a significant common prefix (>60% of shorter)
                    const minLen = Math.min(oldNorm.length, newNorm.length);
                    let commonLen = 0;
                    for (let i = 0; i < minLen; i++) {
                        if (oldNorm[i] === newNorm[i]) commonLen++;
                        else break;
                    }
                    if (commonLen > minLen * 0.6) return true;

                    return false;
                }

                function emitCaption() {
                    const text = window._meetBotLastText;
                    const speaker = window._meetBotLastSpeakerForText || window._meetBotCurrentSpeaker || 'Unknown';

                    if (!text) return;

                    // Check if this is a refinement of the last emitted caption
                    const lastEmitted = window._meetBotLastEmittedText;
                    const lastId = window._meetBotLastEmittedId;

                    if (lastId !== null && isRefinement(lastEmitted, text)) {
                        // UPDATE existing caption instead of creating new one
                        window._meetBotCaptions.push({
                            id: lastId,
                            speaker: speaker,
                            text: text,
                            ts: Date.now(),
                            isUpdate: true  // Signal to update, not append
                        });
                        console.log('[MeetBot] Caption UPDATED:', speaker, text.substring(0, 50));
                    } else {
                        // NEW caption entry
                        const newId = ++window._meetBotCaptionIdCounter;
                        window._meetBotCaptions.push({
                            id: newId,
                            speaker: speaker,
                            text: text,
                            ts: Date.now(),
                            isUpdate: false
                        });
                        window._meetBotLastEmittedId = newId;
                        console.log('[MeetBot] Caption NEW:', speaker, text.substring(0, 50));
                    }
                    window._meetBotLastEmittedText = text;
                }

                const observer = new MutationObserver((mutations) => {
                    const container = findCaptionContainer();
                    if (!container) return;

                    // Always try to get the current speaker
                    const speaker = getSpeaker(container);
                    if (speaker) {
                        window._meetBotCurrentSpeaker = speaker;
                        // Store the speaker associated with the current text being built
                        window._meetBotLastSpeakerForText = speaker;
                    }

                    const captionDiv = findCaptionTextDiv(container);
                    if (!captionDiv) return;

                    const fullText = (captionDiv.textContent || '').trim();
                    if (!fullText) return;

                    // Detect speaker change - force new caption
                    const lastSpeaker = window._meetBotLastSpeakerForText;
                    if (speaker && lastSpeaker && speaker !== lastSpeaker) {
                        // Speaker changed - emit previous caption and start fresh
                        if (window._meetBotDebounceTimer) {
                            clearTimeout(window._meetBotDebounceTimer);
                            emitCaption();
                        }
                        window._meetBotLastEmittedText = '';
                        window._meetBotLastEmittedId = null;
                        window._meetBotLastSpeakerForText = speaker;
                    }

                    // Text changed - reset debounce timer
                    window._meetBotLastText = fullText;

                    if (window._meetBotDebounceTimer) {
                        clearTimeout(window._meetBotDebounceTimer);
                    }

                    // Wait 400ms of no changes before emitting (allows corrections to settle)
                    // Reduced from 800ms for faster wake word detection
                    window._meetBotDebounceTimer = setTimeout(emitCaption, 400);
                });

                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    characterData: true
                });

                window._meetBotObserver = observer;
                console.log('[MeetBot] Caption observer started (800ms debounce, update-in-place mode)');
            }
        """
        )

        # Start polling for new captions (track task for cleanup)
        self._caption_poll_task = asyncio.create_task(self._poll_captions())
        logger.info("Caption capture started")

    async def _poll_captions(self) -> None:
        """Poll for settled/corrected captions from the JS observer buffer."""
        # Track caption IDs to their index in buffer for updates
        caption_id_to_index: dict[int, int] = {}

        while self._caption_observer_running and self.page:
            try:
                # Fetch and clear the caption buffer - these are already debounced/corrected
                captions = await self.page.evaluate(
                    """
                    () => {
                        const c = window._meetBotCaptions || [];
                        window._meetBotCaptions = [];
                        return c;
                    }
                """
                )

                for cap in captions:
                    speaker = cap.get("speaker", "Unknown")
                    text = cap.get("text", "")
                    ts = cap.get("ts", 0)
                    cap_id = cap.get("id", 0)
                    is_update = cap.get("isUpdate", False)

                    if not text.strip():
                        continue

                    # Determine if this is truly an update (JS says update AND we've seen this ID before)
                    is_true_update = is_update and cap_id in caption_id_to_index

                    entry = CaptionEntry(
                        speaker=speaker,
                        text=text.strip(),
                        timestamp=datetime.fromtimestamp(ts / 1000) if ts else datetime.now(),
                        caption_id=cap_id,
                        is_update=is_true_update,
                    )

                    if entry.is_update:
                        # UPDATE existing caption in buffer
                        idx = caption_id_to_index[cap_id]
                        if self.state and 0 <= idx < len(self.state.caption_buffer):
                            self.state.caption_buffer[idx] = entry
                            logger.debug(f"Caption UPDATE [{speaker}] {text[:50]}...")
                        # Also notify callback with updated entry (for live display)
                        if self._caption_callback:
                            self._caption_callback(entry)
                    else:
                        # NEW caption entry
                        if self.state:
                            caption_id_to_index[cap_id] = len(self.state.caption_buffer)
                            self.state.caption_buffer.append(entry)
                        if self._caption_callback:
                            self._caption_callback(entry)
                        logger.debug(f"Caption NEW [{speaker}] {text[:50]}...")

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

        # Cancel the polling task if it exists
        if self._caption_poll_task and not self._caption_poll_task.done():
            self._caption_poll_task.cancel()
            try:
                await asyncio.wait_for(self._caption_poll_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._caption_poll_task = None

        if self.page:
            try:
                await self.page.evaluate(
                    """
                    () => {
                        if (window._meetBotObserver) {
                            window._meetBotObserver.disconnect();
                        }
                    }
                """
                )
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
            leave_button = await self.page.wait_for_selector(self.SELECTORS["leave_button"], timeout=5000)

            if leave_button:
                await leave_button.click()
                self.state.joined = False
                logger.info("Left meeting")
                return True

        except Exception as e:
            logger.error(f"Failed to leave meeting: {e}")

        return False

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
            "turn off",
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
                    '[role="region"][aria-label="In call"], ' '[role="list"][aria-label="Participants"]',
                    timeout=500,
                )
                if panel and await panel.is_visible():
                    panel_open = True
            except Exception:
                pass

            # If panel not open, click the People button to open it
            if not panel_open:
                # The People button uses stable aria-labels
                people_button_selectors = [
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
                        'more actions', 'turn off', 'turn on', 'present', 'presentation',
                        'screen', 'camera', 'microphone', 'admit', 'deny', 'waiting'
                    ];

                    function isValidName(name) {
                        if (!name || name.length < 2 || name.length > 100) return false;
                        const lower = name.toLowerCase();
                        if (uiKeywords.some(kw => lower.includes(kw))) return false;
                        if (['(you)', 'you', 'me'].includes(lower)) return false;
                        return true;
                    }

                    function cleanName(name) {
                        // Remove "(You)" suffix
                        name = name.replace(/\\s*\\(You\\)\\s*/g, '').trim();
                        return name;
                    }

                    function addParticipant(name, email = null) {
                        name = cleanName(name);
                        if (isValidName(name) && !seen.has(name)) {
                            seen.add(name);
                            participants.push({ name, email });
                        }
                    }

                    // Method 1: Find participant list items by role="listitem" with aria-label
                    // This is the most reliable - Google Meet uses aria-label for accessibility
                    const listItems = document.querySelectorAll('[role="listitem"][aria-label]');
                    listItems.forEach(item => {
                        const name = item.getAttribute('aria-label');
                        if (name) {
                            addParticipant(name);
                        }
                    });

                    // Method 2: Find elements with data-participant-id and extract aria-label
                    if (participants.length === 0) {
                        const participantItems = document.querySelectorAll('[data-participant-id]');
                        participantItems.forEach(item => {
                            // First try aria-label on the item itself
                            let name = item.getAttribute('aria-label');
                            if (!name) {
                                // Look for nested element with aria-label
                                const labeled = item.querySelector('[aria-label]');
                                if (labeled) {
                                    name = labeled.getAttribute('aria-label');
                                }
                            }
                            if (name) {
                                addParticipant(name);
                            }
                        });
                    }

                    // Method 3: Find the participant list region and extract names
                    if (participants.length === 0) {
                        // Look for the "In call" region
                        const region = document.querySelector('[role="region"][aria-label="In call"]');
                        if (region) {
                            // Find all list items within
                            const items = region.querySelectorAll('[role="listitem"]');
                            items.forEach(item => {
                                const name = item.getAttribute('aria-label');
                                if (name) {
                                    addParticipant(name);
                                }
                            });
                        }
                    }

                    // Method 4: Look for participant list by aria-label="Participants"
                    if (participants.length === 0) {
                        const list = document.querySelector('[role="list"][aria-label="Participants"]');
                        if (list) {
                            const items = list.querySelectorAll('[role="listitem"]');
                            items.forEach(item => {
                                const name = item.getAttribute('aria-label');
                                if (name) {
                                    addParticipant(name);
                                }
                            });
                        }
                    }

                    // Method 5: Fallback - find any element with data-participant-id
                    // and look for text content in a structured way
                    if (participants.length === 0) {
                        const items = document.querySelectorAll('[data-participant-id]');
                        items.forEach(item => {
                            // Try to find the name by looking at the DOM structure
                            // Names are typically in a div with specific structure
                            const walker = document.createTreeWalker(
                                item,
                                NodeFilter.SHOW_TEXT,
                                {
                                    acceptNode: (node) => {
                                        const text = node.textContent?.trim();
                                        if (text && text.length > 1 && text.length < 100) {
                                            // Check if parent is not a button or icon
                                            const parent = node.parentElement;
                                            if (parent && !parent.closest('button') &&
                                                !parent.closest('[aria-hidden="true"]')) {
                                                return NodeFilter.FILTER_ACCEPT;
                                            }
                                        }
                                        return NodeFilter.FILTER_REJECT;
                                    }
                                }
                            );

                            const firstText = walker.nextNode();
                            if (firstText) {
                                const name = firstText.textContent?.trim();
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
                logger.debug(f"JavaScript extraction found {len(participants)} participants")

            # Fallback: Try Playwright selectors if JS extraction failed
            if not participants:
                try:
                    # Use role-based selectors
                    elements = await self.page.query_selector_all('[role="listitem"][aria-label]')
                    for el in elements:
                        try:
                            name = await el.get_attribute("aria-label")
                            if name:
                                name = clean_name(name)
                                if is_valid_name(name):
                                    if not any(p["name"] == name for p in participants):
                                        participants.append({"name": name, "email": None})
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Playwright fallback failed: {e}")

            # Secondary fallback: data-participant-id elements
            if not participants:
                try:
                    elements = await self.page.query_selector_all("[data-participant-id]")
                    for el in elements:
                        try:
                            name = await el.get_attribute("aria-label")
                            if name:
                                name = clean_name(name)
                                if is_valid_name(name):
                                    if not any(p["name"] == name for p in participants):
                                        participants.append({"name": name, "email": None})
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
                except Exception:
                    pass

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

    async def close(self, restore_browser_audio: bool = False) -> None:
        """Close the browser and cleanup resources.

        Args:
            restore_browser_audio: If True, restore browser mic connections that were
                                   saved before device creation. Set to True when the
                                   meeting dies unexpectedly (browser crashed, service
                                   restarted, etc.) to ensure user's Chrome keeps mic.
        """
        logger.info(f"[{self._instance_id}] Closing browser controller (restore_audio={restore_browser_audio})...")

        # Stop caption capture first (this cancels the polling task)
        try:
            await asyncio.wait_for(self.stop_caption_capture(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"[{self._instance_id}] Timeout stopping caption capture")

        if self.browser:
            try:
                await asyncio.wait_for(self.browser.close(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{self._instance_id}] Timeout closing browser, forcing...")
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

        # Stop virtual camera feed
        if hasattr(self, "_ffmpeg_process") and self._ffmpeg_process:
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

        # Clean up per-instance audio devices (new method)
        if self._device_manager:
            await self._device_manager.cleanup(restore_browser_audio=restore_browser_audio)
            self._device_manager = None
            self._devices = None
        else:
            # Legacy cleanup
            await self._remove_virtual_audio_sink()

        # Unregister this instance
        if self._instance_id in GoogleMeetController._instances:
            del GoogleMeetController._instances[self._instance_id]

        logger.info(f"[{self._instance_id}] Browser closed")

    async def force_kill(self) -> bool:
        """Force kill this browser instance and its processes.

        This is called when the browser is unresponsive or crashed.
        Always restores browser audio since this is an unexpected termination.
        """
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

            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = proc.info.get("cmdline") or []
                    if any(self._instance_id in str(arg) for arg in cmdline):
                        proc.kill()
                        logger.info(f"[{self._instance_id}] Killed process {proc.info['pid']} by cmdline match")
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
        """Check if the browser has been closed."""
        return getattr(self, "_browser_closed", False)

    async def start_screenshot_loop(self, interval_seconds: int = 10) -> None:
        """
        Start periodic screenshot capture.

        Args:
            interval_seconds: Time between screenshots (default 10s)
        """
        logger.info(f"[{self._instance_id}] Starting screenshot loop (every {interval_seconds}s)")
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
                logger.error(f"[{self._instance_id}] Browser closed - stopping screenshot loop")
                self.state.joined = False
                break
            except Exception as e:
                logger.warning(f"[{self._instance_id}] Screenshot loop error: {e}")
                consecutive_failures += 1

            # If too many consecutive failures, assume browser is dead
            if consecutive_failures >= max_failures:
                logger.error(f"[{self._instance_id}] Too many screenshot failures - browser likely closed")
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
