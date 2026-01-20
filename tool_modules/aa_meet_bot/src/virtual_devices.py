"""
Virtual Audio/Video Device Management.

Sets up:
- PulseAudio virtual sink/source for audio routing
- v4l2loopback virtual camera for video output
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class VirtualDeviceStatus:
    """Status of virtual devices."""
    audio_sink_ready: bool = False
    audio_source_ready: bool = False
    video_device_ready: bool = False
    audio_sink_id: Optional[int] = None
    audio_source_id: Optional[int] = None
    video_device_path: Optional[str] = None
    errors: list[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    @property
    def all_ready(self) -> bool:
        return self.audio_sink_ready and self.audio_source_ready and self.video_device_ready


async def run_cmd(cmd: list[str], check: bool = True) -> tuple[bool, str]:
    """Run a command and return success status and output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        success = proc.returncode == 0
        if not success and check:
            logger.warning(f"Command failed: {' '.join(cmd)}\n{output}")
        return success, output
    except Exception as e:
        return False, str(e)


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
            "pactl", "load-module", "module-null-sink",
            f"sink_name={sink_name}",
            f"sink_properties=device.description=MeetBot_Audio_Capture"
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
            "pactl", "load-module", "module-pipe-source",
            f"source_name={source_name}",
            f"file={pipe_path}",
            f"rate={self.config.audio.sample_rate}",
            "channels=1",
            "format=s16le",
            f"source_properties=device.description=MeetBot_Voice_Output"
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
            "sudo", "modprobe", "v4l2loopback",
            "devices=1",
            "video_nr=10",
            "card_label=MeetBot_Camera",
            "exclusive_caps=1"
        ]
        
        success, output = await run_cmd(cmd)
        if success:
            logger.info("Loaded v4l2loopback module")
            return True
        
        logger.error(f"Failed to load v4l2loopback: {output}")
        logger.info("Try running: sudo modprobe v4l2loopback devices=1 video_nr=10 card_label=MeetBot_Camera exclusive_caps=1")
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


# Convenience functions
async def setup_virtual_devices() -> VirtualDeviceStatus:
    """Set up all virtual devices."""
    manager = VirtualDeviceManager()
    return await manager.setup_all()


async def get_device_status() -> VirtualDeviceStatus:
    """Get status of virtual devices."""
    manager = VirtualDeviceManager()
    return await manager.get_status()


