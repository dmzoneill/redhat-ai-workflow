"""
Google Meet Audio Routing.

Handles PulseAudio/PipeWire audio routing for the Meet bot:
- Virtual sink/source creation (legacy fallback)
- Audio module loading/unloading
- Audio stream routing (Chrome to virtual sink)
- Mute/unmute of meeting audio
- Default source restoration

Extracted from GoogleMeetController to separate audio concerns.
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
    from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDevices

logger = logging.getLogger(__name__)


class MeetAudio:
    """Handles PulseAudio/PipeWire audio routing for Google Meet.

    Uses composition: receives a reference to the GoogleMeetController
    to access browser PID, state, device manager, and instance ID.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def _instance_id(self):
        return self._controller._instance_id

    @property
    def _audio_sink_name(self) -> Optional[str]:
        return self._controller._audio_sink_name

    @_audio_sink_name.setter
    def _audio_sink_name(self, value: Optional[str]):
        self._controller._audio_sink_name = value

    @property
    def _browser_pid(self) -> Optional[int]:
        return self._controller._browser_pid

    @property
    def _device_manager(self):
        return self._controller._device_manager

    @property
    def _devices(self) -> Optional["InstanceDevices"]:
        return self._controller._devices

    @property
    def state(self):
        return self._controller.state

    async def create_virtual_audio_sink(self) -> bool:
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

    async def remove_virtual_audio_sink(self) -> None:
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

    def get_audio_devices(self) -> Optional["InstanceDevices"]:
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

    async def route_browser_audio_to_sink(self) -> None:
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

    async def restore_user_default_source(self) -> None:
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

    async def move_user_browser_to_original_source(self, target_source: str) -> None:
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
