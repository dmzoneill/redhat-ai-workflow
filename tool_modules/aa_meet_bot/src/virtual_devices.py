"""
Virtual Audio/Video Device Management.

Sets up per-meeting-instance:
- PulseAudio virtual sink for capturing Chrome's audio output (meeting audio → STT)
- PulseAudio virtual source for injecting TTS audio (bot voice → Chrome mic)
- Named pipe for zero-copy TTS audio transfer
- v4l2loopback virtual camera for avatar video output (per-instance)

Multi-Meeting Support:
- Each meeting instance gets its own sink/source/pipe/video device
- Chrome is launched with PULSE_SINK/PULSE_SOURCE env vars for pre-routing
- Video devices are created dynamically via v4l2loopback-ctl
- All devices are automatically cleaned up when meeting ends
- Orphan cleanup handles crashed/killed meetings

Device Naming:
- Audio sink: meet_bot_<instance_id>
- Audio source: meet_bot_<instance_id>_mic
- Named pipe: ~/.config/aa-workflow/meet_bot/pipes/<instance_id>.pipe
- Video device: /dev/videoN with card_label "MeetBot_<instance_id>"
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

# Import centralized paths
try:
    from server.paths import MEETBOT_DATA_DIR, MEETBOT_PIPES_DIR
except ImportError:
    # Fallback for standalone usage
    MEETBOT_DATA_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot"
    MEETBOT_PIPES_DIR = MEETBOT_DATA_DIR / "pipes"

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# Data directory for named pipes (use centralized path)
DATA_DIR = MEETBOT_DATA_DIR


@dataclass
class InstanceDevices:
    """Per-meeting-instance virtual audio and video devices."""

    instance_id: str

    # Audio output (meeting audio -> STT)
    sink_name: str  # e.g., "meet_bot_abc123"
    sink_module_id: Optional[int] = None

    # Audio input (TTS -> meeting mic)
    source_name: str = ""  # e.g., "meet_bot_abc123_mic"
    source_module_id: Optional[int] = None
    pipe_path: Optional[Path] = None  # e.g., ~/.config/aa-workflow/meet_bot/pipes/abc123.pipe

    # Video output (avatar -> meeting camera)
    video_device: Optional[str] = None  # e.g., "/dev/video11"
    video_device_name: str = ""  # e.g., "MeetBot_abc123"


@dataclass
class VirtualDeviceStatus:
    """Status of virtual devices."""

    audio_sink_ready: bool = False
    audio_source_ready: bool = False
    video_device_ready: bool = False
    audio_sink_id: Optional[int] = None
    audio_source_id: Optional[int] = None
    video_device_path: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    @property
    def all_ready(self) -> bool:
        # Video is optional for voice pipeline
        return self.audio_sink_ready and self.audio_source_ready


async def run_cmd(cmd: list[str], check: bool = True) -> tuple[bool, str]:
    """Run a command and return success status and output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        success = proc.returncode == 0
        if not success and check:
            logger.warning(f"Command failed: {' '.join(cmd)}\n{output}")
        return success, output
    except Exception as e:
        return False, str(e)


class InstanceDeviceManager:
    """
    Manages virtual audio devices for a single meeting instance.

    Creates:
    - A null sink for capturing Chrome's audio output (meeting audio)
    - A pipe source for injecting TTS audio as Chrome's mic input
    - A named pipe for writing TTS audio data

    Usage:
        manager = InstanceDeviceManager("meeting-123")
        devices = await manager.create_all()

        # Launch Chrome with:
        env["PULSE_SINK"] = devices.sink_name
        env["PULSE_SOURCE"] = devices.source_name

        # When meeting ends:
        await manager.cleanup()
    """

    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        # Sanitize instance_id for PulseAudio names (no hyphens)
        safe_id = instance_id.replace("-", "_")
        self.sink_name = f"meet_bot_{safe_id}"
        self.source_name = f"meet_bot_{safe_id}_mic"
        self.video_device_name = f"MeetBot_{safe_id}"

        # Named pipe for TTS audio
        self.pipe_dir = DATA_DIR / "pipes"
        self.pipe_path = self.pipe_dir / f"{safe_id}.pipe"

        # Track module IDs for cleanup
        self._sink_module_id: Optional[int] = None
        self._source_module_id: Optional[int] = None
        self._video_device: Optional[str] = None
        self._devices: Optional[InstanceDevices] = None

        # Save browser audio connections before we create devices
        # This allows us to restore them if something goes wrong
        self._saved_browser_connections: list[tuple[str, str]] = []  # [(output_id, source_name)]
        self._original_default_source: Optional[str] = None

        # Background task to monitor and restore default source
        self._source_monitor_task: Optional[asyncio.Task] = None

    async def create_all(self) -> InstanceDevices:
        """
        Create all audio and video devices for this instance BEFORE Chrome launches.

        Returns:
            InstanceDevices with sink/source/video for Chrome env vars and ffmpeg
        """
        # CRITICAL: Save browser audio state BEFORE creating any devices
        # This allows us to restore the user's Chrome mic if something goes wrong
        await self._save_browser_audio_state()

        # Ensure pipe directory exists
        self.pipe_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create null sink for Chrome output
        sink_id = await self._create_sink()

        # 2. Create named pipe and pipe-source for TTS -> Chrome mic
        await self._create_pipe()
        source_id = await self._create_source()

        # 3. Create virtual video device for avatar -> Chrome camera
        video_device = await self._create_video_device()

        self._devices = InstanceDevices(
            instance_id=self.instance_id,
            sink_name=self.sink_name,
            sink_module_id=sink_id,
            source_name=self.source_name,
            source_module_id=source_id,
            pipe_path=self.pipe_path,
            video_device=video_device,
            video_device_name=self.video_device_name,
        )

        logger.info(
            f"[{self.instance_id}] Created devices: sink={self.sink_name}, "
            f"source={self.source_name}, video={video_device}"
        )

        # Start background task to monitor and restore default source if WirePlumber changes it
        if self._original_default_source:
            self._source_monitor_task = asyncio.create_task(self._monitor_default_source(self._original_default_source))

        return self._devices

    async def _monitor_default_source(self, original_source: str) -> None:
        """
        Background task that monitors the default source and restores it if changed.

        WirePlumber can sometimes re-evaluate and change the default source after
        we've restored it. This task ensures the user's microphone stays as default.
        """
        check_interval = 10  # Check every 10 seconds
        logger.info(f"[{self.instance_id}] Starting default source monitor (original: {original_source})")

        try:
            while True:
                await asyncio.sleep(check_interval)

                # Check current default source
                success, output = await run_cmd(["pactl", "get-default-source"], check=False)
                if success:
                    current = output.strip()
                    # If it changed to our meetbot source, restore it
                    if "meet_bot" in current.lower() and current != original_source:
                        logger.warning(
                            f"[{self.instance_id}] Default source changed to {current}, "
                            f"restoring to {original_source}"
                        )
                        await self._force_restore_default_source(original_source)
        except asyncio.CancelledError:
            logger.info(f"[{self.instance_id}] Default source monitor stopped")
        except Exception as e:
            logger.warning(f"[{self.instance_id}] Default source monitor error: {e}")

    async def _save_browser_audio_state(self) -> None:
        """
        Save the current browser audio connections BEFORE creating virtual devices.

        This allows us to restore the user's Chrome mic connection if:
        1. PipeWire auto-switches to our new device
        2. The bot crashes or restarts
        3. Cleanup runs unexpectedly
        """
        self._saved_browser_connections = []

        # Save default source
        success, output = await run_cmd(["pactl", "get-default-source"], check=False)
        if success:
            self._original_default_source = output.strip()
            logger.info(f"[{self.instance_id}] Saved original default source: {self._original_default_source}")

        # Save browser source-output connections
        success, output = await run_cmd(["pactl", "list", "source-outputs"], check=False)
        if not success:
            return

        current_output_id = None
        current_source = None
        is_browser = False

        for line in output.split("\n"):
            line = line.strip()

            if line.startswith("Source Output #"):
                # Save previous if it was a browser
                if current_output_id and is_browser and current_source:
                    self._saved_browser_connections.append((current_output_id, current_source))
                    logger.info(
                        f"[{self.instance_id}] Saved browser connection: output {current_output_id} -> {current_source}"
                    )

                current_output_id = line.split("#")[1]
                current_source = None
                is_browser = False

            elif "Source:" in line:
                current_source = line.split(":", 1)[1].strip() if ":" in line else ""

            elif "application.name" in line.lower():
                app = line.lower()
                if "chrome" in app or "chromium" in app or "firefox" in app:
                    is_browser = True

        # Don't forget last one
        if current_output_id and is_browser and current_source:
            self._saved_browser_connections.append((current_output_id, current_source))
            logger.info(
                f"[{self.instance_id}] Saved browser connection: output {current_output_id} -> {current_source}"
            )

        if self._saved_browser_connections:
            logger.info(f"[{self.instance_id}] Saved {len(self._saved_browser_connections)} browser audio connections")

    async def _create_sink(self) -> Optional[int]:
        """Create a null sink for capturing Chrome's audio output."""
        # Check if sink already exists
        success, output = await run_cmd(["pactl", "list", "short", "sinks"], check=False)
        if success and self.sink_name in output:
            logger.info(f"[{self.instance_id}] Sink {self.sink_name} already exists")
            return None

        # Create null sink
        cmd = [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={self.sink_name}",
            f'sink_properties=device.description="MeetBot_{self.instance_id}"',
        ]

        success, output = await run_cmd(cmd)
        if success:
            try:
                self._sink_module_id = int(output.strip())
                logger.info(f"[{self.instance_id}] Created sink {self.sink_name} (module {self._sink_module_id})")
                return self._sink_module_id
            except ValueError:
                logger.warning(f"[{self.instance_id}] Could not parse module ID: {output}")
                return None

        logger.error(f"[{self.instance_id}] Failed to create sink: {output}")
        return None

    async def _create_pipe(self) -> bool:
        """Create the named pipe for TTS audio."""
        if self.pipe_path.exists():
            # Remove stale pipe
            try:
                self.pipe_path.unlink()
            except Exception as e:
                logger.warning(f"[{self.instance_id}] Could not remove stale pipe: {e}")

        try:
            os.mkfifo(str(self.pipe_path))
            logger.info(f"[{self.instance_id}] Created named pipe: {self.pipe_path}")
            return True
        except Exception as e:
            logger.error(f"[{self.instance_id}] Failed to create pipe: {e}")
            return False

    async def _create_source(self) -> Optional[int]:
        """Create a pipe-source for TTS audio injection."""
        # Check if source already exists
        success, output = await run_cmd(["pactl", "list", "short", "sources"], check=False)
        if success and self.source_name in output:
            logger.info(f"[{self.instance_id}] Source {self.source_name} already exists")
            return None

        # IMPORTANT: Save the current default source BEFORE creating our virtual source
        # PipeWire/WirePlumber may auto-switch to new sources, breaking the user's mic
        original_default_source = None
        success, output = await run_cmd(["pactl", "get-default-source"], check=False)
        if success:
            original_default_source = output.strip()
            logger.info(f"[{self.instance_id}] Saving original default source: {original_default_source}")

        config = get_config()

        # Create pipe-source with low priority to prevent WirePlumber from selecting it as default
        # node.priority.session=0 tells WirePlumber this is NOT a preferred device
        cmd = [
            "pactl",
            "load-module",
            "module-pipe-source",
            f"source_name={self.source_name}",
            f"file={self.pipe_path}",
            f"rate={config.audio.sample_rate}",
            "channels=1",
            "format=s16le",
            f'source_properties=device.description="MeetBot_{self.instance_id}_Mic"'
            f" node.priority.session=0"
            f" node.priority.driver=0"
            f" priority.session=0"
            f" priority.driver=0",
        ]

        success, output = await run_cmd(cmd)
        if success:
            try:
                self._source_module_id = int(output.strip())
                logger.info(f"[{self.instance_id}] Created source {self.source_name} (module {self._source_module_id})")

                # CRITICAL: Immediately restore the original default source
                # PipeWire automatically makes new sources the default - we must undo this
                if original_default_source and "meet_bot" not in original_default_source.lower():
                    await self._force_restore_default_source(original_default_source)

                return self._source_module_id
            except ValueError:
                logger.warning(f"[{self.instance_id}] Could not parse module ID: {output}")
                return None

        logger.error(f"[{self.instance_id}] Failed to create source: {output}")
        return None

    async def _force_restore_default_source(self, original_source: str) -> None:
        """
        Lock the system default source to prevent WirePlumber from changing it.

        Uses default.configured.audio.source which is the highest priority setting
        in WirePlumber. This LOCKS the system default but does NOT prevent apps
        from using a different device if manually selected.

        Key insight: The "configured" setting only affects what WirePlumber considers
        the system default. Apps like Chrome can still use any device if the user
        manually selects it in the app's audio settings dropdown.

        This allows:
        - User manually selecting headset in Google Meet dropdown -> works fine
        - MeetBot creating virtual device -> system default stays on physical mic
        - Apps using "Default" device -> get the locked physical mic
        """
        max_attempts = 5

        for attempt in range(max_attempts):
            # Method 1: Lock using default.configured.audio.source (highest priority)
            # This prevents WirePlumber from ever changing the system default
            await run_cmd(
                [
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.configured.audio.source",
                    f'{{"name":"{original_source}"}}',
                ],
                check=False,
            )

            # Method 2: Also set default.audio.source for immediate effect
            await run_cmd(
                [
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.audio.source",
                    f'{{"name":"{original_source}"}}',
                ],
                check=False,
            )

            # Method 3: pactl set-default-source (immediate effect)
            await run_cmd(["pactl", "set-default-source", original_source], check=False)

            # Very short wait - just enough for PipeWire to process
            await asyncio.sleep(0.1)

            # Verify it stuck
            success, current = await run_cmd(["pactl", "get-default-source"], check=False)
            if success:
                current = current.strip()
                if current == original_source:
                    logger.info(f"[{self.instance_id}] Default source LOCKED to {current} " f"(attempt {attempt + 1})")
                    return  # Success!
                elif "meet_bot" not in current.lower():
                    # Different physical source - acceptable (user may have switched)
                    logger.info(
                        f"[{self.instance_id}] Default source is {current} (physical device) "
                        f"(attempt {attempt + 1})"
                    )
                    return
                else:
                    logger.warning(
                        f"[{self.instance_id}] Default source is still {current}, "
                        f"retrying (attempt {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(0.1 * (attempt + 1))

        # Final attempt
        logger.warning(f"[{self.instance_id}] Final lock attempt for {original_source}")
        await run_cmd(
            ["pw-metadata", "-n", "default", "0", "default.configured.audio.source", f'{{"name":"{original_source}"}}'],
            check=False,
        )
        await run_cmd(
            ["pw-metadata", "-n", "default", "0", "default.audio.source", f'{{"name":"{original_source}"}}'],
            check=False,
        )
        await run_cmd(["pactl", "set-default-source", original_source], check=False)

        # Also restore any browser streams that got moved to meetbot devices
        await self._restore_browser_mic_connections(original_source)

    async def _restore_browser_mic_connections(self, original_source: str) -> None:
        """
        Restore browser microphone connections after creating/removing virtual devices.

        This is CRITICAL for ensuring the user's Chrome doesn't lose its mic.

        We:
        1. Find all Chrome/browser source-outputs that are on a meetbot device
        2. Move them back to the original physical microphone
        """
        # Give PipeWire a moment to settle
        await asyncio.sleep(0.3)

        # First restore the default source
        success, current_default = await run_cmd(["pactl", "get-default-source"], check=False)
        if success:
            current_default = current_default.strip()
            if "meet_bot" in current_default.lower():
                logger.warning(
                    f"[{self.instance_id}] Default source is meetbot device, " f"restoring to {original_source}"
                )
                await run_cmd(
                    ["pw-metadata", "-n", "default", "0", "default.audio.source", f'{{"name":"{original_source}"}}'],
                    check=False,
                )

        # Now find and restore any browser streams that got moved to our device
        await self._reconnect_browsers_to_physical_mic(original_source)

    async def _reconnect_browsers_to_physical_mic(self, target_source: str) -> None:
        """
        Find any browser streams connected to meetbot devices and reconnect them
        to the physical microphone.

        This ensures the user's Chrome always has mic access.
        """
        try:
            # Get the source index for the target (physical mic)
            success, output = await run_cmd(["pactl", "list", "sources", "short"], check=False)
            if not success:
                return

            target_index = None
            for line in output.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2 and target_source in parts[1]:
                    target_index = parts[0]
                    break

            if not target_index:
                logger.warning(f"[{self.instance_id}] Could not find index for source: {target_source}")
                return

            # Get all source-outputs and find browsers on meetbot devices
            success, output = await run_cmd(["pactl", "list", "source-outputs"], check=False)
            if not success:
                return

            current_output_id = None
            current_source = None
            is_browser = False

            for line in output.split("\n"):
                line = line.strip()

                if line.startswith("Source Output #"):
                    # Process previous output if it was a browser on meetbot
                    if current_output_id and is_browser and current_source:
                        if "meet_bot" in str(current_source).lower():
                            logger.info(
                                f"[{self.instance_id}] Reconnecting browser stream {current_output_id} "
                                f"from {current_source} to {target_source}"
                            )
                            await run_cmd(["pactl", "move-source-output", current_output_id, target_index], check=False)

                    # Start new output
                    current_output_id = line.split("#")[1]
                    current_source = None
                    is_browser = False

                elif "Source:" in line:
                    current_source = line.split(":", 1)[1].strip() if ":" in line else ""

                elif "application.name" in line.lower():
                    app = line.lower()
                    if "chrome" in app or "chromium" in app or "firefox" in app:
                        is_browser = True

            # Don't forget last output
            if current_output_id and is_browser and current_source:
                if "meet_bot" in str(current_source).lower():
                    logger.info(
                        f"[{self.instance_id}] Reconnecting browser stream {current_output_id} "
                        f"from {current_source} to {target_source}"
                    )
                    await run_cmd(["pactl", "move-source-output", current_output_id, target_index], check=False)

        except Exception as e:
            logger.warning(f"[{self.instance_id}] Failed to reconnect browsers: {e}")

    async def _restore_saved_browser_connections(self) -> None:
        """
        Restore browser audio connections that were saved before device creation.

        This is called during cleanup to ensure the user's Chrome gets its mic back.
        """
        # First restore the default source
        if self._original_default_source and "meet_bot" not in self._original_default_source.lower():
            logger.info(f"[{self.instance_id}] Restoring default source: {self._original_default_source}")
            await run_cmd(
                [
                    "pw-metadata",
                    "-n",
                    "default",
                    "0",
                    "default.audio.source",
                    f'{{"name":"{self._original_default_source}"}}',
                ],
                check=False,
            )

        # If we have saved connections, restore them
        if self._saved_browser_connections:
            # Get source name -> index mapping
            success, output = await run_cmd(["pactl", "list", "sources", "short"], check=False)
            if not success:
                return

            source_indices = {}
            for line in output.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    source_indices[parts[1]] = parts[0]

            # Restore each saved connection
            for output_id, source_name in self._saved_browser_connections:
                # Skip if it was connected to a meetbot device (that's gone now)
                if "meet_bot" in source_name.lower():
                    # Use the original default source instead
                    source_name = self._original_default_source or ""

                if source_name and source_name in source_indices:
                    target_index = source_indices[source_name]
                    logger.info(f"[{self.instance_id}] Restoring browser output {output_id} to {source_name}")
                    await run_cmd(["pactl", "move-source-output", output_id, target_index], check=False)
        else:
            # No saved connections - try to reconnect any browsers on meetbot devices
            if self._original_default_source:
                await self._reconnect_browsers_to_physical_mic(self._original_default_source)

    async def _ensure_user_browser_has_mic(self, target_source: str) -> None:
        """DEPRECATED: Use _restore_saved_browser_connections instead."""
        logger.debug(f"[{self.instance_id}] _ensure_user_browser_has_mic called but deprecated")

    async def _create_video_device(self) -> Optional[str]:
        """Create a v4l2loopback virtual camera device for this instance."""
        # Check if v4l2loopback-ctl is available
        success, _ = await run_cmd(["which", "v4l2loopback-ctl"], check=False)
        if not success:
            logger.warning(f"[{self.instance_id}] v4l2loopback-ctl not found, skipping video device")
            return None

        # Check if v4l2loopback module is loaded with control device
        success, output = await run_cmd(["lsmod"], check=False)
        if not success or "v4l2loopback" not in output:
            # Try to load the module with control device support
            logger.info(f"[{self.instance_id}] Loading v4l2loopback module...")
            load_success = await self._load_v4l2loopback_module()
            if not load_success:
                logger.warning(f"[{self.instance_id}] v4l2loopback module not available, skipping video device")
                return None

        # Check if control device exists (required for dynamic add/delete)
        if not Path("/dev/v4l2loopback").exists():
            logger.warning(f"[{self.instance_id}] v4l2loopback control device not found, trying to reload module")
            await self._reload_v4l2loopback_with_control()
            if not Path("/dev/v4l2loopback").exists():
                logger.warning(f"[{self.instance_id}] Cannot create control device, skipping video device")
                return None

        # Create a new v4l2loopback device dynamically
        # -v for verbose output (returns device path)
        # -x 1 for exclusive_caps=1 (CRITICAL for Chrome detection)
        # With exclusive_caps=1, device shows as OUTPUT when idle, CAPTURE when streaming
        # Chrome ONLY detects devices that show as pure CAPTURE devices
        cmd = [
            "v4l2loopback-ctl",
            "add",
            "-n",
            self.video_device_name,
            "-x",
            "1",  # exclusive_caps=1 - Chrome requires this to detect the device
            "-v",  # verbose - prints device info
        ]

        success, output = await run_cmd(cmd)
        if success:
            # Parse output for device path
            # Verbose output includes: "device: /dev/videoN"
            device_path = None
            for line in output.strip().split("\n"):
                line = line.strip()
                if line.startswith("/dev/video"):
                    device_path = line.split()[0]  # First word is the path
                    break
                elif "device:" in line.lower():
                    parts = line.split(":")
                    if len(parts) > 1:
                        device_path = parts[1].strip().split()[0]
                        break

            if not device_path:
                # Try to find the device by name
                device_path = await self._find_video_device_by_name()

            if device_path and device_path.startswith("/dev/video"):
                self._video_device = device_path
                logger.info(f"[{self.instance_id}] Created video device: {device_path} ({self.video_device_name})")
                return device_path

        logger.error(f"[{self.instance_id}] Failed to create video device: {output}")
        return None

    async def _load_v4l2loopback_module(self) -> bool:
        """Load the v4l2loopback kernel module with control device support."""
        # Try loading without sudo first (in case user has permissions)
        cmd = ["modprobe", "v4l2loopback"]
        success, output = await run_cmd(cmd, check=False)

        if not success:
            # Try with sudo
            cmd = ["sudo", "modprobe", "v4l2loopback"]
            success, output = await run_cmd(cmd, check=False)

        if success:
            logger.info(f"[{self.instance_id}] Loaded v4l2loopback module")
            # Give it a moment to create the control device
            await asyncio.sleep(0.5)
            return True

        logger.warning(f"[{self.instance_id}] Failed to load v4l2loopback: {output}")
        return False

    async def _reload_v4l2loopback_with_control(self) -> bool:
        """Reload v4l2loopback module to ensure control device is created."""
        # This is a last resort - unload and reload the module
        # Only do this if no other meetbot devices exist
        success, output = await run_cmd(["v4l2loopback-ctl", "list"], check=False)
        if success and "MeetBot_" in output:
            logger.warning(f"[{self.instance_id}] Other MeetBot devices exist, cannot reload module")
            return False

        # Unload
        await run_cmd(["sudo", "modprobe", "-r", "v4l2loopback"], check=False)
        await asyncio.sleep(0.3)

        # Reload
        return await self._load_v4l2loopback_module()

    async def _find_video_device_by_name(self) -> Optional[str]:
        """Find the video device path by its name."""
        # Try v4l2loopback-ctl list first
        success, output = await run_cmd(["v4l2loopback-ctl", "list"], check=False)
        if success:
            # Parse output to find our device
            # Format: /dev/videoN    MeetBot_xxx
            for line in output.strip().split("\n"):
                if self.video_device_name in line:
                    parts = line.split()
                    if parts and parts[0].startswith("/dev/video"):
                        return parts[0]

        # Fallback: search /sys/devices for our device name
        try:
            import glob

            for card_path in glob.glob("/sys/devices/virtual/video4linux/video*/name"):
                with open(card_path) as f:
                    name = f.read().strip()
                    if name == self.video_device_name:
                        # Extract video number from path
                        video_dir = Path(card_path).parent.name
                        return f"/dev/{video_dir}"
        except Exception as e:
            logger.debug(f"[{self.instance_id}] Fallback device search failed: {e}")

        return None

    async def _cleanup_video_device(self) -> None:
        """Remove the v4l2loopback video device."""
        if not self._video_device:
            # Try to find by name in case we lost track
            device_path = await self._find_video_device_by_name()
            if device_path:
                self._video_device = device_path
            else:
                return

        # Delete the device
        success, output = await run_cmd(["v4l2loopback-ctl", "delete", self._video_device], check=False)

        if success:
            logger.info(f"[{self.instance_id}] Removed video device: {self._video_device} ({self.video_device_name})")
        else:
            # Try by device number if path failed
            if self._video_device.startswith("/dev/video"):
                video_num = self._video_device.replace("/dev/video", "")
                success2, output2 = await run_cmd(["v4l2loopback-ctl", "delete", video_num], check=False)
                if success2:
                    logger.info(f"[{self.instance_id}] Removed video device by number: {video_num}")
                else:
                    logger.warning(f"[{self.instance_id}] Failed to remove video device {self._video_device}: {output}")
            else:
                logger.warning(f"[{self.instance_id}] Failed to remove video device: {output}")

        self._video_device = None

    async def cleanup(self, restore_browser_audio: bool = False) -> None:
        """Remove all audio and video devices when meeting ends.

        Args:
            restore_browser_audio: If True, restore browser mic connections that were
                                   saved before device creation. Only set this to True
                                   when the meeting dies unexpectedly or the bot crashes.
                                   Normal cleanup should NOT restore connections.

        IMPORTANT: We only remove OUR virtual devices. We never touch the user's
        Chrome or any other application's audio connections (unless restore_browser_audio=True).
        """
        # Stop the source monitor task first
        if self._source_monitor_task and not self._source_monitor_task.done():
            self._source_monitor_task.cancel()
            try:
                await asyncio.wait_for(self._source_monitor_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._source_monitor_task = None

        # Ensure the default source lock is still in place after cleanup
        # We keep the lock (default.configured.audio.source) so new virtual devices
        # created by other bot instances don't hijack the default
        if self._original_default_source:
            success, current = await run_cmd(["pactl", "get-default-source"], check=False)
            if success and "meet_bot" in current.strip().lower():
                logger.info(f"[{self.instance_id}] Restoring default source to {self._original_default_source}")
                # Re-lock to original physical device
                await run_cmd(
                    [
                        "pw-metadata",
                        "-n",
                        "default",
                        "0",
                        "default.configured.audio.source",
                        f'{{"name":"{self._original_default_source}"}}',
                    ],
                    check=False,
                )
                await run_cmd(
                    [
                        "pw-metadata",
                        "-n",
                        "default",
                        "0",
                        "default.audio.source",
                        f'{{"name":"{self._original_default_source}"}}',
                    ],
                    check=False,
                )
                await run_cmd(["pactl", "set-default-source", self._original_default_source], check=False)

        # Check for any streams still connected to our devices before removing
        # This is just for debugging - we still remove our devices regardless
        if self._sink_module_id or self._source_module_id:
            success, output = await run_cmd(["pactl", "list", "source-outputs", "short"], check=False)
            if success and self.source_name:
                for line in output.strip().split("\n"):
                    if self.source_name in line:
                        logger.warning(f"[{self.instance_id}] Stream still connected to our source: {line}")

        # Unload sink module (this is OUR virtual sink, not the user's)
        if self._sink_module_id:
            await run_cmd(["pactl", "unload-module", str(self._sink_module_id)], check=False)
            logger.info(f"[{self.instance_id}] Removed sink module {self._sink_module_id}")
            self._sink_module_id = None

        # Unload source module (this is OUR virtual source/mic, not the user's)
        if self._source_module_id:
            await run_cmd(["pactl", "unload-module", str(self._source_module_id)], check=False)
            logger.info(f"[{self.instance_id}] Removed source module {self._source_module_id}")
            self._source_module_id = None

        # Remove video device
        await self._cleanup_video_device()

        # Remove named pipe
        if self.pipe_path and self.pipe_path.exists():
            try:
                self.pipe_path.unlink()
                logger.info(f"[{self.instance_id}] Removed pipe {self.pipe_path}")
            except Exception as e:
                logger.warning(f"[{self.instance_id}] Could not remove pipe: {e}")

        self._devices = None

        # Only restore browser connections if explicitly requested (meeting died/crashed)
        if restore_browser_audio:
            logger.info(f"[{self.instance_id}] Restoring browser audio connections (meeting died)")
            await self._restore_saved_browser_connections()

        logger.info(f"[{self.instance_id}] Audio device cleanup complete")

    def get_devices(self) -> Optional[InstanceDevices]:
        """Get the created devices (None if not created yet)."""
        return self._devices

    def get_monitor_source(self) -> str:
        """Get the monitor source name for capturing sink audio."""
        return f"{self.sink_name}.monitor"


class VirtualAudioManager:
    """Manages PulseAudio virtual devices for meeting audio."""

    def __init__(self):
        self.config = get_config()
        self.sink_module_id: Optional[int] = None
        self.source_module_id: Optional[int] = None

    async def check_pulseaudio(self) -> bool:
        """Check if PulseAudio is running."""
        success, _ = await run_cmd(["pactl", "info"], check=False)
        return success

    async def create_virtual_sink(self) -> tuple[bool, Optional[int]]:
        """
        Create a virtual sink for capturing meeting audio.

        The meeting audio will be routed to this sink, and we monitor it
        for transcription.
        """
        sink_name = self.config.audio.virtual_sink_name

        # Check if sink already exists
        success, output = await run_cmd(["pactl", "list", "short", "sinks"], check=False)
        if success and sink_name in output:
            logger.info(f"Virtual sink '{sink_name}' already exists")
            # Extract module ID if possible
            return True, None

        # Create null sink (virtual sink)
        cmd = [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={sink_name}",
            "sink_properties=device.description=MeetBot_Audio_Capture",
        ]

        success, output = await run_cmd(cmd)
        if success:
            try:
                self.sink_module_id = int(output.strip())
                logger.info(f"Created virtual sink '{sink_name}' (module {self.sink_module_id})")
                return True, self.sink_module_id
            except ValueError:
                logger.warning(f"Could not parse module ID from: {output}")
                return True, None

        logger.error(f"Failed to create virtual sink: {output}")
        return False, None

    async def create_virtual_source(self) -> tuple[bool, Optional[int]]:
        """
        Create a virtual source for injecting bot audio.

        The bot's synthesized voice will be played through this source,
        which is then used as the microphone input for the meeting.
        """
        source_name = self.config.audio.virtual_source_name

        # Check if source already exists
        success, output = await run_cmd(["pactl", "list", "short", "sources"], check=False)
        if success and source_name in output:
            logger.info(f"Virtual source '{source_name}' already exists")
            return True, None

        # Create virtual source using module-pipe-source
        # This allows us to write audio data directly to a pipe
        pipe_path = self.config.data_dir / "audio_pipe"

        cmd = [
            "pactl",
            "load-module",
            "module-pipe-source",
            f"source_name={source_name}",
            f"file={pipe_path}",
            f"rate={self.config.audio.sample_rate}",
            "channels=1",
            "format=s16le",
            "source_properties=device.description=MeetBot_Voice_Output",
        ]

        success, output = await run_cmd(cmd)
        if success:
            try:
                self.source_module_id = int(output.strip())
                logger.info(f"Created virtual source '{source_name}' (module {self.source_module_id})")
                return True, self.source_module_id
            except ValueError:
                logger.warning(f"Could not parse module ID from: {output}")
                return True, None

        logger.error(f"Failed to create virtual source: {output}")
        return False, None

    async def cleanup(self) -> None:
        """Remove virtual audio devices."""
        if self.sink_module_id:
            await run_cmd(["pactl", "unload-module", str(self.sink_module_id)], check=False)
            self.sink_module_id = None

        if self.source_module_id:
            await run_cmd(["pactl", "unload-module", str(self.source_module_id)], check=False)
            self.source_module_id = None

        logger.info("Cleaned up virtual audio devices")


class VirtualVideoManager:
    """Manages v4l2loopback virtual camera for meeting video."""

    def __init__(self):
        self.config = get_config()
        self.device_path: Optional[str] = None

    async def check_v4l2loopback(self) -> bool:
        """Check if v4l2loopback kernel module is loaded."""
        success, output = await run_cmd(["lsmod"], check=False)
        return success and "v4l2loopback" in output

    async def load_v4l2loopback(self) -> bool:
        """Load v4l2loopback kernel module."""
        # Check if already loaded
        if await self.check_v4l2loopback():
            logger.info("v4l2loopback already loaded")
            return True

        # Try to load module (requires sudo)
        cmd = [
            "sudo",
            "modprobe",
            "v4l2loopback",
            "devices=1",
            "video_nr=10",
            "card_label=MeetBot_Camera",
            "exclusive_caps=1",
        ]

        success, output = await run_cmd(cmd)
        if success:
            logger.info("Loaded v4l2loopback module")
            return True

        logger.error(f"Failed to load v4l2loopback: {output}")
        logger.info(
            "Try running: sudo modprobe v4l2loopback devices=1 "
            "video_nr=10 card_label=MeetBot_Camera exclusive_caps=1"
        )
        return False

    async def find_virtual_camera(self) -> Optional[str]:
        """Find the v4l2loopback virtual camera device."""
        # Check configured device first
        device = self.config.video.virtual_camera_device
        if Path(device).exists():
            self.device_path = device
            return device

        # Search for v4l2loopback devices
        success, output = await run_cmd(["v4l2-ctl", "--list-devices"], check=False)
        if not success:
            return None

        # Parse output to find MeetBot_Camera or v4l2loopback device
        lines = output.split("\n")
        for i, line in enumerate(lines):
            if "MeetBot_Camera" in line or "v4l2loopback" in line.lower():
                # Next line should be the device path
                if i + 1 < len(lines):
                    device = lines[i + 1].strip()
                    if device.startswith("/dev/video"):
                        self.device_path = device
                        return device

        return None

    async def setup(self) -> tuple[bool, Optional[str]]:
        """Set up virtual camera device."""
        # Load module if needed
        if not await self.load_v4l2loopback():
            return False, None

        # Find device
        device = await self.find_virtual_camera()
        if device:
            logger.info(f"Virtual camera ready at {device}")
            return True, device

        logger.error("Could not find virtual camera device")
        return False, None

    async def cleanup(self) -> None:
        """Clean up virtual camera (optional - module stays loaded)."""
        self.device_path = None
        logger.info("Virtual camera cleanup complete")


class VirtualDeviceManager:
    """Unified manager for all virtual devices."""

    def __init__(self):
        self.audio = VirtualAudioManager()
        self.video = VirtualVideoManager()

    async def setup_all(self) -> VirtualDeviceStatus:
        """Set up all virtual devices and return status."""
        status = VirtualDeviceStatus()

        # Check PulseAudio
        if not await self.audio.check_pulseaudio():
            status.errors.append("PulseAudio not running")
            return status

        # Set up audio devices
        sink_ok, sink_id = await self.audio.create_virtual_sink()
        status.audio_sink_ready = sink_ok
        status.audio_sink_id = sink_id
        if not sink_ok:
            status.errors.append("Failed to create virtual audio sink")

        source_ok, source_id = await self.audio.create_virtual_source()
        status.audio_source_ready = source_ok
        status.audio_source_id = source_id
        if not source_ok:
            status.errors.append("Failed to create virtual audio source")

        # Set up video device
        video_ok, video_path = await self.video.setup()
        status.video_device_ready = video_ok
        status.video_device_path = video_path
        if not video_ok:
            status.errors.append("Failed to set up virtual camera")

        return status

    async def cleanup_all(self) -> None:
        """Clean up all virtual devices."""
        await self.audio.cleanup()
        await self.video.cleanup()

    async def get_status(self) -> VirtualDeviceStatus:
        """Get current status of virtual devices."""
        status = VirtualDeviceStatus()

        # Check audio sink
        config = get_config()
        success, output = await run_cmd(["pactl", "list", "short", "sinks"], check=False)
        status.audio_sink_ready = success and config.audio.virtual_sink_name in output

        # Check audio source
        success, output = await run_cmd(["pactl", "list", "short", "sources"], check=False)
        status.audio_source_ready = success and config.audio.virtual_source_name in output

        # Check video device
        status.video_device_ready = Path(config.video.virtual_camera_device).exists()
        if status.video_device_ready:
            status.video_device_path = config.video.virtual_camera_device

        return status


# Orphaned device cleanup
async def cleanup_orphaned_meetbot_devices(active_instance_ids: set[str] | None = None) -> dict:
    """
    Find and remove orphaned MeetBot audio devices.

    This cleans up sinks/sources that were created by MeetBot but weren't
    properly removed (e.g., due to crashes, force kills, or bugs).

    Args:
        active_instance_ids: Set of currently active instance IDs. If None,
                            removes ALL meetbot devices (use with caution).

    Returns:
        Dict with cleanup results: removed_sinks, removed_sources, removed_pipes, errors
    """
    results = {
        "removed_sinks": [],
        "removed_sources": [],
        "removed_modules": [],
        "removed_pipes": [],
        "errors": [],
        "skipped_active": [],
    }

    # Normalize active instance IDs (replace hyphens with underscores to match sink names)
    active_safe_ids = set()
    if active_instance_ids:
        for iid in active_instance_ids:
            active_safe_ids.add(iid.replace("-", "_"))

    # Get all PulseAudio modules
    success, output = await run_cmd(["pactl", "list", "modules", "short"], check=False)
    if not success:
        results["errors"].append(f"Failed to list modules: {output}")
        return results

    # Find meetbot modules to remove
    modules_to_remove = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue

        module_id = parts[0]
        module_type = parts[1]
        module_args = parts[2] if len(parts) > 2 else ""

        # Check if this is a meetbot module
        if "meet_bot" not in module_args.lower():
            continue

        # Extract instance ID from sink/source name
        # Format: sink_name=meet_bot_<instance_id> or source_name=meet_bot_<instance_id>_mic
        instance_id = None
        if "sink_name=meet_bot_" in module_args:
            # Extract: meet_bot_<id> from sink_name=meet_bot_<id>
            start = module_args.find("sink_name=meet_bot_") + len("sink_name=meet_bot_")
            end = module_args.find(" ", start) if " " in module_args[start:] else len(module_args)
            instance_id = module_args[start:end]
        elif "source_name=meet_bot_" in module_args:
            # Extract: meet_bot_<id>_mic -> <id>
            start = module_args.find("source_name=meet_bot_") + len("source_name=meet_bot_")
            end = module_args.find("_mic", start) if "_mic" in module_args[start:] else module_args.find(" ", start)
            if end == -1:
                end = len(module_args)
            instance_id = module_args[start:end]

        # Check if this instance is still active
        if instance_id and active_safe_ids and instance_id in active_safe_ids:
            results["skipped_active"].append(f"module {module_id} (instance {instance_id})")
            continue

        # Mark for removal
        modules_to_remove.append((module_id, module_type, instance_id or "unknown"))

    # Remove orphaned modules
    for module_id, module_type, instance_id in modules_to_remove:
        success, output = await run_cmd(["pactl", "unload-module", module_id], check=False)
        if success:
            results["removed_modules"].append(f"{module_id} ({module_type}, instance: {instance_id})")
            logger.info(f"Removed orphaned module {module_id} ({module_type}) for instance {instance_id}")
        else:
            results["errors"].append(f"Failed to unload module {module_id}: {output}")

    # Clean up orphaned named pipes
    pipe_dir = DATA_DIR / "pipes"
    if pipe_dir.exists():
        for pipe_file in pipe_dir.glob("*.pipe"):
            # Extract instance ID from pipe name
            pipe_instance_id = pipe_file.stem  # e.g., "meet_bot_1_123456" from "meet_bot_1_123456.pipe"

            # Check if this instance is still active
            if active_safe_ids and pipe_instance_id in active_safe_ids:
                results["skipped_active"].append(f"pipe {pipe_file.name}")
                continue

            try:
                pipe_file.unlink()
                results["removed_pipes"].append(str(pipe_file))
                logger.info(f"Removed orphaned pipe: {pipe_file}")
            except Exception as e:
                results["errors"].append(f"Failed to remove pipe {pipe_file}: {e}")

    # Clean up orphaned parec processes targeting MeetBot sinks
    results["killed_processes"] = []
    parec_cleanup = await _cleanup_orphaned_parec_processes(active_safe_ids)
    results["killed_processes"] = parec_cleanup.get("killed", [])
    results["errors"].extend(parec_cleanup.get("errors", []))

    # Clean up orphaned video devices
    results["removed_video_devices"] = []
    video_cleanup = await _cleanup_orphaned_video_devices(active_safe_ids)
    results["removed_video_devices"] = video_cleanup.get("removed", [])
    results["errors"].extend(video_cleanup.get("errors", []))
    results["skipped_active"].extend(video_cleanup.get("skipped", []))

    # Restore default audio source if it was set to a meetbot device
    await _restore_default_audio_source()

    total_removed = len(results["removed_modules"]) + len(results["removed_pipes"]) + len(results["killed_processes"])
    if total_removed > 0:
        logger.info(f"Orphaned device cleanup complete: {total_removed} items removed")

    return results


async def _find_parec_via_pgrep() -> list[tuple[int, str]]:
    """Find parec processes using pgrep."""
    results = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-a", "parec",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0 and stdout:
            for line in stdout.decode().strip().split("\n"):
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    try:
                        results.append((int(parts[0]), parts[1]))
                    except ValueError:
                        continue
    except Exception as e:
        logger.debug(f"pgrep method failed: {e}")
    return results


async def _find_parec_via_ps() -> list[tuple[int, str]]:
    """Find parec processes using ps aux."""
    results = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0 and stdout:
            for line in stdout.decode().strip().split("\n"):
                if "parec" in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) >= 11:
                        try:
                            results.append((int(parts[1]), " ".join(parts[10:])))
                        except ValueError:
                            continue
    except Exception as e:
        logger.debug(f"ps aux method failed: {e}")
    return results


def _find_parec_via_proc(existing_pids: set[int]) -> list[tuple[int, str]]:
    """Find parec processes by scanning /proc."""
    import glob
    results = []
    try:
        for proc_dir in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                with open(proc_dir, "r") as f:
                    cmdline = f.read().replace("\x00", " ").strip()
                    if "parec" in cmdline:
                        pid = int(proc_dir.split("/")[2])
                        if pid not in existing_pids:
                            results.append((pid, cmdline))
            except (IOError, ValueError, IndexError):
                continue
    except Exception as e:
        logger.debug(f"/proc method failed: {e}")
    return results


def _extract_instance_id_from_cmdline(cmd_line: str) -> Optional[str]:
    """Extract MeetBot instance ID from parec command line."""
    if "meet_bot_" not in cmd_line:
        return None

    import re
    match = re.search(r"meet_bot_([a-zA-Z0-9_]+)", cmd_line)
    if match:
        instance_id = match.group(1)
        # Remove trailing .monitor if present
        if instance_id.endswith("_monitor"):
            instance_id = instance_id[:-8]
        return instance_id
    return None


async def _kill_process(pid: int) -> bool:
    """Kill a process with SIGTERM, then SIGKILL if needed. Returns True if killed."""
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(0.1)
        # Check if still alive
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Died from SIGTERM
        return True
    except ProcessLookupError:
        return False  # Already gone
    except PermissionError:
        raise
    except Exception:
        raise


async def _cleanup_orphaned_parec_processes(active_safe_ids: set[str]) -> dict:
    """
    Kill orphaned parec processes that are targeting MeetBot sinks.

    These processes are spawned by the video bot's audio capture and can become
    orphaned if the meeting ends unexpectedly or cleanup fails.

    Args:
        active_safe_ids: Set of active instance IDs (sanitized, with underscores)

    Returns:
        Dict with killed, errors lists
    """
    results = {"killed": [], "errors": []}

    # Collect parec processes from multiple sources
    parec_pids = await _find_parec_via_pgrep()

    if not parec_pids:
        parec_pids = await _find_parec_via_ps()

    # Add any missed processes from /proc
    existing_pids = {p[0] for p in parec_pids}
    parec_pids.extend(_find_parec_via_proc(existing_pids))

    # Process each parec
    for pid, cmd_line in parec_pids:
        # Check if targeting MeetBot
        if "meet_bot" not in cmd_line.lower() and "--monitor-stream" not in cmd_line:
            continue

        instance_id = _extract_instance_id_from_cmdline(cmd_line)

        # Skip if instance is active
        if instance_id and active_safe_ids and instance_id in active_safe_ids:
            logger.debug(f"Skipping active parec process {pid} for instance {instance_id}")
            continue

        # Kill the orphaned process
        try:
            if await _kill_process(pid):
                results["killed"].append(f"parec {pid} (instance: {instance_id or 'unknown'})")
                logger.info(f"Killed orphaned parec process {pid} targeting MeetBot sink")
        except PermissionError as e:
            results["errors"].append(f"Permission denied killing parec {pid}: {e}")
        except Exception as e:
            results["errors"].append(f"Failed to kill parec {pid}: {e}")

    return results


async def _cleanup_orphaned_video_devices(active_safe_ids: set[str]) -> dict:
    """
    Clean up orphaned MeetBot v4l2loopback video devices.

    Args:
        active_safe_ids: Set of active instance IDs (sanitized, with underscores)

    Returns:
        Dict with removed, errors, skipped lists
    """
    results = {"removed": [], "errors": [], "skipped": []}

    # Check if v4l2loopback-ctl is available
    success, _ = await run_cmd(["which", "v4l2loopback-ctl"], check=False)
    if not success:
        return results

    # List all v4l2loopback devices
    success, output = await run_cmd(["v4l2loopback-ctl", "list"], check=False)
    if not success:
        return results

    # Parse output to find MeetBot devices
    # Format: /dev/videoN    DeviceName
    for line in output.strip().split("\n"):
        if not line or "MeetBot_" not in line:
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        device_path = parts[0]
        device_name = parts[1] if len(parts) > 1 else ""

        # Extract instance ID from device name (MeetBot_<instance_id>)
        if device_name.startswith("MeetBot_"):
            instance_id = device_name[len("MeetBot_") :]

            # Check if this instance is still active
            if active_safe_ids and instance_id in active_safe_ids:
                results["skipped"].append(f"video {device_path} ({device_name})")
                continue

            # Delete the orphaned device
            success, del_output = await run_cmd(["v4l2loopback-ctl", "delete", device_path], check=False)

            if success:
                results["removed"].append(f"{device_path} ({device_name})")
                logger.info(f"Removed orphaned video device: {device_path} ({device_name})")
            else:
                results["errors"].append(f"Failed to remove video device {device_path}: {del_output}")

    return results


async def _restore_default_audio_source() -> bool:
    """
    Check if default audio source is a meetbot device and restore to physical mic.

    Returns:
        True if default was changed, False otherwise
    """
    # Get current default source
    success, output = await run_cmd(["pactl", "get-default-source"], check=False)
    if not success:
        return False

    current_default = output.strip()

    # Check if it's a meetbot source
    if "meet_bot" not in current_default.lower():
        return False

    logger.warning(f"Default audio source is a MeetBot device: {current_default}")

    # Find a physical microphone to use instead
    success, output = await run_cmd(["pactl", "list", "sources", "short"], check=False)
    if not success:
        return False

    # Look for ALSA input devices (physical mics)
    physical_mics = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        source_name = parts[1]
        # Physical mics are usually alsa_input.* and not monitors
        if source_name.startswith("alsa_input.") and ".monitor" not in source_name:
            physical_mics.append(source_name)

    if not physical_mics:
        logger.warning("No physical microphones found to restore default")
        return False

    # Use the first physical mic (usually the built-in one)
    new_default = physical_mics[0]
    success, _ = await run_cmd(["pactl", "set-default-source", new_default], check=False)

    if success:
        logger.info(f"Restored default audio source to: {new_default}")

        # Also unmute the physical mic
        await run_cmd(["pactl", "set-source-mute", new_default, "0"], check=False)
        return True

    return False


async def get_meetbot_device_count() -> dict:
    """
    Get count of current MeetBot audio and video devices.

    Returns:
        Dict with sink_count, source_count, pipe_count, video_count, module_count
    """
    result = {
        "sink_count": 0,
        "source_count": 0,
        "pipe_count": 0,
        "video_count": 0,
        "module_count": 0,
    }

    # Count modules
    success, output = await run_cmd(["pactl", "list", "modules", "short"], check=False)
    if success:
        for line in output.strip().split("\n"):
            if "meet_bot" in line.lower():
                result["module_count"] += 1

    # Count sinks
    success, output = await run_cmd(["pactl", "list", "sinks", "short"], check=False)
    if success:
        for line in output.strip().split("\n"):
            if "meet_bot" in line.lower():
                result["sink_count"] += 1

    # Count sources (excluding monitors)
    success, output = await run_cmd(["pactl", "list", "sources", "short"], check=False)
    if success:
        for line in output.strip().split("\n"):
            if "meet_bot" in line.lower() and ".monitor" not in line:
                result["source_count"] += 1

    # Count pipes
    pipe_dir = DATA_DIR / "pipes"
    if pipe_dir.exists():
        result["pipe_count"] = len(list(pipe_dir.glob("*.pipe")))

    # Count video devices
    success, output = await run_cmd(["v4l2loopback-ctl", "list"], check=False)
    if success:
        for line in output.strip().split("\n"):
            if "MeetBot_" in line:
                result["video_count"] += 1

    return result


# Convenience functions
async def setup_virtual_devices() -> VirtualDeviceStatus:
    """Set up all virtual devices."""
    manager = VirtualDeviceManager()
    return await manager.setup_all()


async def get_device_status() -> VirtualDeviceStatus:
    """Get status of virtual devices."""
    manager = VirtualDeviceManager()
    return await manager.get_status()
