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

logger = logging.getLogger(__name__)


MAX_CAPTION_BUFFER = 10000


class BrowserClosedError(Exception):
    """Raised when the browser has been closed unexpectedly."""


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
        self._caption_callback: Optional[Callable[[CaptionEntry], None]] = None
        self._caption_observer_running = False
        self._caption_poll_task: Optional[asyncio.Task] = (
            None  # Track caption polling task
        )
        self._playwright = None
        self._audio_sink_name: Optional[str] = (
            None  # Virtual audio sink for meeting output
        )

        # Unique instance tracking
        GoogleMeetController._instance_counter += 1
        self._instance_id = (
            f"meet-bot-{GoogleMeetController._instance_counter}-{id(self)}"
        )
        self._browser_pid: Optional[int] = None
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
            result = subprocess.run(
                ["pactl", "list", "short", "sinks"], capture_output=True, text=True
            )
            if sink_name in result.stdout:
                logger.info(
                    f"[{self._instance_id}] Virtual audio sink already exists: {sink_name}"
                )
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
                logger.info(
                    f"[{self._instance_id}] Created virtual audio sink: {sink_name}"
                )
                logger.info(
                    f"[{self._instance_id}] To listen: pactl set-default-source {sink_name}.monitor"
                )
                return True
            else:
                logger.warning(
                    f"[{self._instance_id}] Failed to create audio sink: {result.stderr}"
                )
                return False

        except Exception as e:
            logger.warning(
                f"[{self._instance_id}] Could not create virtual audio sink: {e}"
            )
            return False

    async def _remove_virtual_audio_sink(self) -> None:
        """Remove the virtual audio sink when done."""
        import subprocess

        if not self._audio_sink_name:
            return

        try:
            # Find the module index for our sink
            result = subprocess.run(
                ["pactl", "list", "short", "modules"], capture_output=True, text=True
            )

            for line in result.stdout.strip().split("\n"):
                if self._audio_sink_name in line:
                    module_index = line.split()[0]
                    subprocess.run(["pactl", "unload-module", module_index])
                    logger.info(
                        f"[{self._instance_id}] Removed virtual audio sink: {self._audio_sink_name}"
                    )
                    break

            self._audio_sink_name = None
        except Exception as e:
            logger.warning(
                f"[{self._instance_id}] Could not remove virtual audio sink: {e}"
            )

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
            logger.warning(
                f"[{self._instance_id}] Audio routing: meeting not joined, giving up"
            )
            return

        logger.info(f"[{self._instance_id}] Meeting joined, starting audio routing...")

        # Keep checking for new audio streams while in the meeting
        while self.state and self.state.joined:
            await asyncio.sleep(3)  # Check every 3 seconds

            try:
                # Get detailed info about all sink inputs
                result = subprocess.run(
                    ["pactl", "list", "sink-inputs"], capture_output=True, text=True
                )

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
                            if not self._browser_pid or current_pid == str(
                                self._browser_pid
                            ):
                                self._move_sink_input(current_input_id)
                                streams_routed += 1
                            else:
                                logger.debug(
                                    f"[{self._instance_id}] Skipping audio stream {current_input_id} "
                                    f"(PID {current_pid} != our PID {self._browser_pid})"
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
                            logger.debug(
                                f"[{self._instance_id}] Found Chrome audio stream: {current_input_id}"
                            )

                    elif "application.process.id" in line.lower():
                        current_pid = line.split("=")[-1].strip().strip('"')

                # Don't forget the last one
                if (
                    current_input_id
                    and is_chrome
                    and current_sink
                    and self._audio_sink_name not in current_sink
                ):
                    if not self._browser_pid or current_pid == str(self._browser_pid):
                        self._move_sink_input(current_input_id)
                        streams_routed += 1

            except Exception as e:
                logger.debug(f"[{self._instance_id}] Audio routing check failed: {e}")

        if streams_routed > 0:
            logger.info(
                f"[{self._instance_id}] Audio routing monitor stopped (routed {streams_routed} streams)"
            )
        else:
            logger.info(f"[{self._instance_id}] Audio routing monitor stopped")

    def _move_sink_input(self, sink_input_id: str) -> bool:
        """Move a sink input to our virtual audio sink."""
        import subprocess

        if not self._audio_sink_name:
            return False

        try:
            result = subprocess.run(
                ["pactl", "move-sink-input", sink_input_id, self._audio_sink_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info(
                    f"[{self._instance_id}] Routed audio stream {sink_input_id} to virtual sink"
                )
                return True
            else:
                logger.debug(
                    f"Failed to move sink-input {sink_input_id}: {result.stderr}"
                )
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
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"], capture_output=True, text=True
            )

            current_input_id = None
            is_chrome = False
            current_pid = None

            for line in result.stdout.split("\n"):
                line = line.strip()

                if line.startswith("Sink Input #"):
                    # Check if previous input matches our criteria
                    if current_input_id and is_chrome:
                        if not only_our_browser or (
                            self._browser_pid and current_pid == str(self._browser_pid)
                        ):
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
                if not only_our_browser or (
                    self._browser_pid and current_pid == str(self._browser_pid)
                ):
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
            result = subprocess.run(
                ["pactl", "get-default-sink"], capture_output=True, text=True
            )
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
                    ["pactl", "move-sink-input", sink_input_id, default_sink],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    logger.info(
                        f"[{self._instance_id}] Unmuted: moved stream {sink_input_id} to {default_sink}"
                    )
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
                    ["pactl", "move-sink-input", sink_input_id, self._audio_sink_name],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    logger.info(
                        f"[{self._instance_id}] Muted: moved stream {sink_input_id} to {self._audio_sink_name}"
                    )
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
            result = subprocess.run(
                ["pactl", "list", "sink-inputs"], capture_output=True, text=True
            )

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
            result = subprocess.run(
                ["pactl", "get-default-source"], capture_output=True, text=True
            )
            current_default = result.stdout.strip()

            # If current default is already NOT a meetbot source, we're good
            if current_default and "meet_bot" not in current_default.lower():
                logger.info(
                    f"[{self._instance_id}] Default source is already user's device: {current_default}"
                )
                return

            # Current default is meetbot - need to find and restore user's source
            # Get all available sources
            result = subprocess.run(
                ["pactl", "list", "sources", "short"], capture_output=True, text=True
            )

            # Find a non-meetbot, non-monitor source (user's actual mic/headset)
            user_source = None
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    source_name = parts[1]
                    # Skip monitors and meetbot sources
                    if (
                        ".monitor" not in source_name
                        and "meet_bot" not in source_name.lower()
                    ):
                        user_source = source_name
                        # Don't break - keep looking in case there's a USB/Bluetooth device
                        # USB/Bluetooth devices typically have "usb" or "bluez" in the name
                        if (
                            "usb" in source_name.lower()
                            or "bluez" in source_name.lower()
                        ):
                            break  # Prefer external devices

            if user_source:
                # Use pw-metadata for persistent default (pactl gets overridden by PipeWire)
                subprocess.run(
                    [
                        "pw-metadata",
                        "-n",
                        "default",
                        "0",
                        "default.audio.source",
                        f'{{"name":"{user_source}"}}',
                    ],
                    capture_output=True,
                )
                logger.info(
                    f"[{self._instance_id}] Restored default source via pw-metadata: {user_source}"
                )
            else:
                logger.warning(
                    f"[{self._instance_id}] No user audio source found to restore"
                )

        except Exception as e:
            logger.warning(
                f"[{self._instance_id}] Failed to restore default source: {e}"
            )

    async def _move_user_browser_to_original_source(self, target_source: str) -> None:
        """
        DEPRECATED: This function is no longer used.

        We no longer move browser streams because:
        1. The bot's Chrome uses PULSE_SOURCE env var - already routed correctly
        2. The user's Chrome should stay on whatever source it was using
        3. Moving streams is error-prone and breaks user's audio

        Keeping this function stub for backwards compatibility.
        """
        logger.debug(
            f"[{self._instance_id}] _move_user_browser_to_original_source called but disabled"
        )
        return

        # DISABLED CODE BELOW - kept for reference
        import subprocess

        try:
            # Get the index for the target source
            result = subprocess.run(
                ["pactl", "list", "sources", "short"], capture_output=True, text=True
            )

            target_index = None
            for line in result.stdout.strip().split("\n"):
                if target_source in line:
                    target_index = line.split("\t")[0]
                    break

            if not target_index:
                logger.warning(
                    f"[{self._instance_id}] Could not find index for source: {target_source}"
                )
                return

            # Get all source outputs
            result = subprocess.run(
                ["pactl", "list", "source-outputs"], capture_output=True, text=True
            )

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
                                    [
                                        "pactl",
                                        "move-source-output",
                                        current_output_id,
                                        target_index,
                                    ],
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
                    current_source = (
                        line.split(":", 1)[1].strip() if ":" in line else ""
                    )

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
                            [
                                "pactl",
                                "move-source-output",
                                current_output_id,
                                target_index,
                            ],
                            capture_output=True,
                        )
                        logger.info(
                            f"[{self._instance_id}] Moved user browser stream {current_output_id} "
                            f"(PID {current_pid}) to {target_source}"
                        )

        except Exception as e:
            logger.warning(f"[{self._instance_id}] Failed to move browser streams: {e}")

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

    async def sign_in_google(self) -> bool:  # noqa: C901
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
            username, password = await get_google_credentials(
                self.config.bot_account.email
            )

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
                    next_button = await self.page.wait_for_selector(
                        "#identifierNext", timeout=5000
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
                    "#username", timeout=15000  # Red Hat SSO username field
                )
                if saml_username:
                    logger.info("Red Hat SSO page detected - using aa_sso helper")

                    # Use the centralized SSO form filler from aa_sso module
                    try:
                        from tool_modules.aa_sso.src.tools_basic import fill_sso_form

                        await fill_sso_form(self.page, username, password)
                    except ImportError:
                        # Fallback to inline implementation if aa_sso not available
                        logger.warning(
                            "aa_sso module not available, using inline SSO form fill"
                        )
                        await saml_username.fill(username)
                        await asyncio.sleep(0.5)
                        saml_password = await self.page.wait_for_selector(
                            "#password", timeout=5000
                        )
                        if saml_password:
                            await saml_password.fill(password)
                            await asyncio.sleep(0.5)
                        submit_button = await self.page.wait_for_selector(
                            "#submit", timeout=5000
                        )
                        if submit_button:
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
                            if (
                                "speedbump" in current_url
                                or "samlconfirmaccount" in current_url
                            ):
                                logger.info(
                                    "Google verification page detected, clicking Continue..."
                                )
                                try:
                                    # The Continue button has nested structure: button > span.VfPpkd-vQzf8d with text
                                    # Try multiple selectors to find the actual clickable button
                                    continue_selectors = [
                                        'button:has(span:text-is("Continue"))',  # Button with span exact text
                                        'button.VfPpkd-LgbsSe:has-text("Continue")',  # Google's Material button class
                                        'button[jsname="LgbsSe"]:has-text("Continue")',  # Button with jsname
                                        'span.VfPpkd-vQzf8d:text-is("Continue")',  # The span itself (click it)
                                    ]

                                    clicked = False
                                    for selector in continue_selectors:
                                        try:
                                            btn = self.page.locator(selector).first
                                            if await btn.count() > 0:
                                                logger.info(
                                                    f"Found Continue button with selector: {selector}"
                                                )
                                                await btn.click(
                                                    force=True, timeout=5000
                                                )
                                                logger.info(
                                                    "Clicked Continue on verification page"
                                                )
                                                clicked = True
                                                await asyncio.sleep(3)
                                                break
                                        except Exception as e:
                                            logger.debug(
                                                f"Selector {selector} failed: {e}"
                                            )

                                    if not clicked:
                                        # Last resort: find by role and text
                                        logger.info(
                                            "Trying role-based selector for Continue..."
                                        )
                                        await self.page.get_by_role(
                                            "button", name="Continue"
                                        ).click(timeout=5000)
                                        logger.info(
                                            "Clicked Continue via role selector"
                                        )
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
                sign_in_link = await self.page.query_selector(
                    self.SELECTORS["sign_in_link"]
                )
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
                        except Exception:
                            pass
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
            except Exception:
                pass

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
                except Exception:
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
            # First, find the device in the browser's device list
            js_find_device = """
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
                    except Exception:
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
                except Exception:
                    pass

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
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Error dismissing info popups: {e}")

    async def start_caption_capture(
        self, callback: Callable[[CaptionEntry], None]
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
                        timestamp=(
                            datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
                        ),
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
                            # Trim old entries when buffer exceeds max size
                            if len(self.state.caption_buffer) > MAX_CAPTION_BUFFER:
                                trim_count = (
                                    len(self.state.caption_buffer) - MAX_CAPTION_BUFFER
                                )
                                self.state.caption_buffer = self.state.caption_buffer[
                                    trim_count:
                                ]
                                # Rebuild index mapping after trim
                                caption_id_to_index = {
                                    e.caption_id: i
                                    for i, e in enumerate(self.state.caption_buffer)
                                }
                        if self._caption_callback:
                            self._caption_callback(entry)
                        logger.debug(f"Caption NEW [{speaker}] {text[:50]}...")

                await asyncio.sleep(0.5)  # Poll every 500ms

            except Exception as e:
                error_msg = str(e)
                # Detect browser/page closure
                if (
                    "Target closed" in error_msg
                    or "Target page, context or browser has been closed" in error_msg
                    or "Browser has been closed" in error_msg
                ):
                    logger.warning(
                        f"[Caption poll] Browser closed detected: {error_msg}"
                    )
                    self._browser_closed = True
                    if self.state:
                        self.state.joined = False
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
            except Exception:
                pass

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
