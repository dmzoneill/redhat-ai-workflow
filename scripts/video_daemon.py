#!/usr/bin/env python3
"""
Video Generator Daemon

A systemd service that renders the AI research video overlay to a v4l2loopback
virtual camera. Controlled via D-Bus by the meet_daemon.

Architecture:
    PRODUCTION MODE (meet_daemon orchestrates):
    - meet_daemon creates PipeWire/PulseAudio devices:
        - meet_bot_<id> sink (captures meeting audio → transcription)
        - meet_bot_<id>_mic source (bot TTS → meeting microphone)
        - v4l2loopback device (/dev/videoN)
    - meet_daemon joins Google Meet with these virtual devices
    - meet_daemon calls StartVideo() via D-Bus with device paths
    - video_daemon renders to video device, reads from audio sink monitor

    TEST MODE (video_daemon self-contained):
    - video_daemon creates v4l2loopback device itself (--create-device)
    - Uses default microphone for waveform visualization (--test)
    - Uses default speakers for audio output
    - Useful for development without running meet_daemon

Usage:
    # Production (wait for meet_daemon to call StartVideo)
    python scripts/video_daemon.py

    # Test mode (self-contained)
    python scripts/video_daemon.py --test --create-device --flip

    # Control running daemon
    python scripts/video_daemon.py --status
    python scripts/video_daemon.py --stop
    python scripts/video_daemon.py --start-video /dev/video10 --audio default

Systemd:
    systemctl --user start bot-video
    systemctl --user status bot-video
    systemctl --user stop bot-video

D-Bus Interface (com.aiworkflow.BotVideo):
    Methods:
        StartVideo(device, audio_input, audio_output, width, height, flip) -> success
        StopVideo() -> success
        UpdateAttendees(attendees_json) -> success
        SetFlip(flip) -> success
        StartStreaming(device, mode, port) -> success  # WebRTC/MJPEG preview
        StopStreaming() -> success
        GetRenderStats() -> dict

    Properties:
        Status: "idle" | "rendering" | "error"
        CurrentDevice: str
        AudioInput: str (sink monitor for waveform)
        AudioOutput: str (source for TTS)
        Flip: bool
        FrameRate: float
        StreamingMode: str

    Signals:
        RenderingStarted(device)
        RenderingStopped()
        StreamingStarted(mode, port)
        StreamingStopped()
        Error(message)
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dbus_base import DaemonDBusBase, get_client  # noqa: E402
from scripts.common.video_device import cleanup_device, setup_v4l2_device  # noqa: E402

# Optional: sleep/wake awareness
try:
    from scripts.common.sleep_wake import SleepWakeAwareDaemon

    HAS_SLEEP_WAKE = True
except ImportError:
    HAS_SLEEP_WAKE = False

    class SleepWakeAwareDaemon:
        """Dummy class when sleep_wake not available."""

        pass


LOCK_FILE = Path("/tmp/video-daemon.lock")
PID_FILE = Path("/tmp/video-daemon.pid")

# Configure logging for journalctl
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)


class SingleInstance:
    """Ensures only one instance of the daemon runs at a time."""

    def __init__(self):
        self._lock_file = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock_file = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            PID_FILE.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        self._acquired = False

    def get_running_pid(self) -> Optional[int]:
        """Get PID of running instance, or None if not running."""
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError):
                pass
        return None


# Determine base class
if HAS_SLEEP_WAKE:
    _BaseClass = type("_BaseClass", (SleepWakeAwareDaemon, DaemonDBusBase), {})
else:
    _BaseClass = DaemonDBusBase


class VideoDaemon(_BaseClass):
    """Video generator daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.BotVideo"
    object_path = "/com/aiworkflow/BotVideo"
    interface_name = "com.aiworkflow.BotVideo"

    def __init__(
        self,
        verbose: bool = False,
        enable_dbus: bool = True,
        create_device: bool = False,
        default_flip: bool = False,
        test_mode: bool = False,
    ):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self.create_device = create_device  # If True, daemon creates v4l2 device
        self.default_flip = default_flip
        self.test_mode = test_mode  # If True, use default mic/speakers

        self._shutdown_event = asyncio.Event()

        # Rendering state
        self._status = "idle"  # idle, rendering, error
        self._current_device: Optional[str] = None
        self._audio_input: Optional[str] = None  # Sink monitor for waveform
        self._audio_output: Optional[str] = None  # Source for TTS output
        self._flip = default_flip
        self._width = 1920
        self._height = 1080
        self._frame_rate = 0.0
        self._frames_rendered = 0
        self._render_start_time: Optional[float] = None

        # Streaming state (WebRTC/MJPEG preview)
        self._streaming_mode: Optional[str] = None  # 'webrtc', 'mjpeg', None
        self._streaming_port: int = 8765
        self._streaming_pipeline = None

        # Renderer instance
        self._renderer = None
        self._render_task: Optional[asyncio.Task] = None

        # Attendees data
        self._attendees: list[dict] = []

        # Slack D-Bus client for photo lookups
        self._slack_client = None
        self._slack_cache: dict[str, dict] = {}  # name -> {slack_id, photo_path}

        # Register D-Bus method handlers
        self.register_handler("start_video", self._handle_start_video)
        self.register_handler("stop_video", self._handle_stop_video)
        self.register_handler("update_attendees", self._handle_update_attendees)
        self.register_handler("set_flip", self._handle_set_flip)
        self.register_handler("get_render_stats", self._handle_get_render_stats)
        self.register_handler("start_streaming", self._handle_start_streaming)
        self.register_handler("stop_streaming", self._handle_stop_streaming)

    # =========================================================================
    # D-Bus Method Handlers
    # =========================================================================

    async def _handle_start_video(
        self,
        device: str,
        audio_input: str = "",
        audio_output: str = "",
        width: int = 1920,
        height: int = 1080,
        flip: bool = False,
    ) -> dict:
        """
        Start video rendering to the specified device.

        Called by meet_daemon when a meeting starts, or directly for testing.

        Args:
            device: v4l2loopback device path (e.g., /dev/video10)
            audio_input: PulseAudio sink monitor for waveform visualization
                        (e.g., "meet_bot_abc123.monitor" or "default" for test mode)
            audio_output: PulseAudio source for TTS audio output
                         (e.g., "meet_bot_abc123_mic" or "" for test mode)
            width: Video width (default 1920)
            height: Video height (default 1080)
            flip: Enable horizontal flip for Google Meet mirror compensation
        """
        if self._status == "rendering":
            return {"success": False, "error": "Already rendering"}

        try:
            self._current_device = device
            self._width = width
            self._height = height
            self._flip = flip
            self._frames_rendered = 0
            self._render_start_time = time.time()

            # Handle audio input (for waveform visualization)
            if audio_input == "default" or (self.test_mode and not audio_input):
                # Test mode: use default microphone
                self._audio_input = self._get_default_audio_source()
                logger.info(f"Using default audio input: {self._audio_input}")
            elif audio_input:
                # Production mode: use sink monitor from meet_daemon
                self._audio_input = audio_input
            else:
                self._audio_input = None

            # Handle audio output (for TTS)
            if audio_output == "default" or (self.test_mode and not audio_output):
                # Test mode: use default speakers (no special routing)
                self._audio_output = None
                logger.info("Using default audio output (speakers)")
            elif audio_output:
                # Production mode: use source from meet_daemon
                self._audio_output = audio_output
            else:
                self._audio_output = None

            # Set flip environment variable for renderer
            if flip:
                os.environ["FLIP"] = "1"
            else:
                os.environ.pop("FLIP", None)

            # Start rendering in background task
            self._render_task = asyncio.create_task(self._render_loop())
            self._status = "rendering"

            # Emit signal
            self.emit_event("RenderingStarted", device)

            logger.info(
                f"Started video rendering to {device} ({width}x{height}, "
                f"flip={flip}, audio_in={self._audio_input}, audio_out={self._audio_output})"
            )
            return {
                "success": True,
                "device": device,
                "audio_input": self._audio_input,
                "audio_output": self._audio_output,
            }

        except Exception as e:
            self._status = "error"
            logger.error(f"Failed to start video: {e}")
            return {"success": False, "error": str(e)}

    def _get_default_audio_source(self) -> Optional[str]:
        """Get the default PulseAudio source (microphone) for test mode."""
        import subprocess

        try:
            result = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Failed to get default audio source: {e}")
        return None

    async def _handle_stop_video(self) -> dict:
        """Stop video rendering."""
        if self._status != "rendering":
            return {"success": True, "message": "Not rendering"}

        try:
            # Cancel render task
            if self._render_task:
                self._render_task.cancel()
                try:
                    await self._render_task
                except asyncio.CancelledError:
                    pass
                self._render_task = None

            # Clean up renderer
            if self._renderer:
                try:
                    self._renderer.stop()
                except Exception as e:
                    logger.warning(f"Error stopping renderer: {e}")
                self._renderer = None

            self._status = "idle"
            self._current_device = None

            # Emit signal
            self.emit_event("RenderingStopped", "")

            logger.info("Stopped video rendering")
            return {"success": True}

        except Exception as e:
            logger.error(f"Error stopping video: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_update_attendees(self, attendees_json: str) -> dict:
        """
        Update the list of meeting attendees.

        Enriches attendees with Slack data (photo paths) via D-Bus lookup.

        Args:
            attendees_json: JSON array of attendee objects
                           [{"name": "John Doe", "avatar_url": "..."}, ...]
        """
        try:
            attendees = json.loads(attendees_json)
            if not isinstance(attendees, list):
                return {"success": False, "error": "Expected JSON array"}

            # Enrich with Slack data (photo paths)
            enriched_attendees = await self._enrich_attendees_with_slack(attendees)
            self._attendees = enriched_attendees

            photos_found = sum(1 for a in enriched_attendees if a.get("photo_path"))
            logger.info(f"Updated attendees: {len(enriched_attendees)} participants, " f"{photos_found} with photos")

            # If renderer is running, update it
            if self._renderer and hasattr(self._renderer, "update_attendees"):
                self._renderer.update_attendees(enriched_attendees)

            return {
                "success": True,
                "count": len(enriched_attendees),
                "photos_found": photos_found,
            }

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_set_flip(self, flip: bool) -> dict:
        """Set horizontal flip mode."""
        self._flip = flip

        if flip:
            os.environ["FLIP"] = "1"
        else:
            os.environ.pop("FLIP", None)

        logger.info(f"Set flip mode: {flip}")

        # Note: If currently rendering, the flip change will take effect
        # on the next renderer initialization (requires restart)
        return {"success": True, "flip": flip, "note": "Restart rendering to apply"}

    async def _handle_get_render_stats(self) -> dict:
        """Get detailed rendering statistics."""
        stats = {
            "status": self._status,
            "device": self._current_device,
            "audio_input": self._audio_input,
            "audio_output": self._audio_output,
            "resolution": f"{self._width}x{self._height}",
            "flip": self._flip,
            "frames_rendered": self._frames_rendered,
            "frame_rate": self._frame_rate,
            "attendees_count": len(self._attendees),
            "streaming_mode": self._streaming_mode,
            "streaming_port": self._streaming_port if self._streaming_mode else None,
            "test_mode": self.test_mode,
        }

        if self._render_start_time:
            stats["render_duration"] = time.time() - self._render_start_time

        # Add streaming stats if active
        if self._streaming_pipeline:
            try:
                streaming_stats = self._streaming_pipeline.get_stats()
                stats["streaming"] = streaming_stats
            except Exception:
                pass

        return stats

    async def _handle_start_streaming(
        self,
        device: str = "",
        mode: str = "webrtc",
        port: int = 8765,
    ) -> dict:
        """
        Start WebRTC or MJPEG streaming for preview.

        Args:
            device: Video device to stream from (uses current if empty)
            mode: 'webrtc' or 'mjpeg'
            port: Signaling port (WebRTC) or HTTP port (MJPEG)
        """
        if self._streaming_pipeline:
            return {"success": False, "error": "Streaming already active"}

        try:
            from tool_modules.aa_meet_bot.src.intel_streaming import (
                IntelStreamingPipeline,
                MJPEGStreamServer,
                StreamConfig,
            )

            self._streaming_mode = mode
            self._streaming_port = port

            if mode == "webrtc":
                config = StreamConfig(
                    width=self._width,
                    height=self._height,
                    framerate=30,
                    bitrate=4000,
                    encoder="va",
                    codec="h264",
                    signaling_port=port,
                    flip=self._flip,
                    v4l2_device=device or self._current_device,
                )
                self._streaming_pipeline = IntelStreamingPipeline(config)
                self._streaming_pipeline.start(mode="webrtc")
                logger.info(f"Started WebRTC streaming on port {port}")

            elif mode == "mjpeg":
                self._streaming_pipeline = MJPEGStreamServer(
                    port=port,
                    width=640,
                    height=360,
                )
                await self._streaming_pipeline.start()
                logger.info(f"Started MJPEG streaming on port {port}")

            self.emit_event("StreamingStarted", f"{mode}:{port}")
            return {"success": True, "mode": mode, "port": port}

        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            self._streaming_mode = None
            return {"success": False, "error": str(e)}

    async def _handle_stop_streaming(self) -> dict:
        """Stop WebRTC or MJPEG streaming."""
        if not self._streaming_pipeline:
            return {"success": True, "message": "Not streaming"}

        try:
            self._streaming_pipeline.stop()
            self._streaming_pipeline = None
            self._streaming_mode = None

            self.emit_event("StreamingStopped", "")
            logger.info("Stopped streaming")
            return {"success": True}

        except Exception as e:
            logger.error(f"Failed to stop streaming: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Slack Integration
    # =========================================================================

    async def _get_slack_client(self):
        """Get or create the Slack D-Bus client."""
        if self._slack_client is None:
            try:
                from scripts.slack_dbus import SlackAgentClient

                self._slack_client = SlackAgentClient()
                await self._slack_client.connect()
                logger.info("Connected to Slack D-Bus service")
            except Exception as e:
                logger.warning(f"Could not connect to Slack D-Bus: {e}")
                self._slack_client = None
        return self._slack_client

    async def _resolve_attendee_slack_id(self, name: str) -> dict:
        """
        Resolve an attendee name to their Slack ID and photo path.

        Uses fuzzy name matching against the Slack user cache.

        Args:
            name: Display name from Google Meet (e.g., "John Smith")

        Returns:
            Dict with slack_id, photo_path, and match_score (empty if not found)
        """
        # Check cache first
        if name in self._slack_cache:
            return self._slack_cache[name]

        result = {"slack_id": "", "photo_path": "", "match_score": 0}

        try:
            client = await self._get_slack_client()
            if not client:
                return result

            # Use fuzzy name matching (threshold 0.7 = 70% similarity)
            lookup_result = await client.lookup_user_by_name(name, threshold=0.7)

            if lookup_result.get("success") and lookup_result.get("users"):
                # Take the best match
                best_match = lookup_result["users"][0]
                result = {
                    "slack_id": best_match.get("user_id", ""),
                    "photo_path": best_match.get("photo_path", ""),
                    "match_score": best_match.get("match_score", 0),
                    "display_name": best_match.get("display_name", ""),
                    "real_name": best_match.get("real_name", ""),
                }
                logger.debug(
                    f"Resolved '{name}' -> Slack user {result['slack_id']} " f"(score: {result['match_score']:.2f})"
                )

            # Cache the result (even if empty to avoid repeated lookups)
            self._slack_cache[name] = result

        except Exception as e:
            logger.debug(f"Slack lookup failed for '{name}': {e}")

        return result

    async def _enrich_attendees_with_slack(self, attendees: list[dict]) -> list[dict]:
        """
        Enrich attendees with Slack data (photo paths).

        Args:
            attendees: List of attendee dicts with 'name' key

        Returns:
            Enriched attendees with 'slack_id' and 'photo_path' added
        """
        enriched = []
        for attendee in attendees:
            name = attendee.get("name", "")
            if not name:
                enriched.append(attendee)
                continue

            # Get Slack data
            slack_data = await self._resolve_attendee_slack_id(name)

            # Merge with attendee data
            enriched_attendee = {**attendee}
            if slack_data.get("slack_id"):
                enriched_attendee["slack_id"] = slack_data["slack_id"]
            if slack_data.get("photo_path"):
                enriched_attendee["photo_path"] = slack_data["photo_path"]
            if slack_data.get("display_name"):
                enriched_attendee["slack_display_name"] = slack_data["display_name"]

            enriched.append(enriched_attendee)

        return enriched

    # =========================================================================
    # Rendering
    # =========================================================================

    async def _render_loop(self):
        """Main rendering loop."""
        try:
            # Import renderer here to avoid loading heavy deps at startup
            from tool_modules.aa_meet_bot.src.video_generator import RealtimeVideoRenderer, VideoConfig

            # Create config
            if self._width == 1280 and self._height == 720:
                config = VideoConfig.hd_720p()
            else:
                config = VideoConfig()  # Default 1080p

            # Create renderer with audio source for waveform
            # In production: audio_input is the meet_bot sink monitor
            # In test mode: audio_input is the default microphone
            self._renderer = RealtimeVideoRenderer(
                config=config,
                audio_source=self._audio_input,
            )

            logger.info(f"Starting render loop to {self._current_device} " f"(audio_input={self._audio_input})")

            # Use stream_live which connects to AttendeeDataService
            # or stream_realtime with provided attendees
            if self._attendees:
                # Convert attendees to Attendee objects
                from tool_modules.aa_meet_bot.src.video_generator import Attendee

                attendee_objs = [Attendee(name=a.get("name", "Unknown")) for a in self._attendees]
                await self._renderer.stream_realtime(
                    attendees=attendee_objs,
                    video_device=self._current_device,
                    loop=True,
                )
            else:
                # Use live mode - gets attendees from AttendeeDataService
                await self._renderer.stream_live(self._current_device)

        except asyncio.CancelledError:
            logger.info("Render loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Render loop error: {e}")
            self._status = "error"
            self.emit_event("Error", str(e))
        finally:
            if self._renderer:
                try:
                    await self._renderer.stop_async()
                except Exception:
                    pass
                self._renderer = None

    # =========================================================================
    # DaemonDBusBase Implementation
    # =========================================================================

    async def get_service_stats(self) -> dict:
        """Return service-specific statistics."""
        return {
            "status": self._status,
            "device": self._current_device,
            "audio_input": self._audio_input,
            "audio_output": self._audio_output,
            "flip": self._flip,
            "frame_rate": self._frame_rate,
            "frames_rendered": self._frames_rendered,
            "attendees_count": len(self._attendees),
            "streaming_mode": self._streaming_mode,
            "test_mode": self.test_mode,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        return await self._handle_get_render_stats()

    async def health_check(self) -> dict:
        """Perform health check."""
        checks = {
            "running": self.is_running,
            "dbus_connected": self._bus is not None,
        }

        if self._status == "rendering":
            checks["rendering"] = True
            checks["device_exists"] = self._current_device and Path(self._current_device).exists()

        healthy = checks.get("running", False) and checks.get("dbus_connected", False)

        return {
            "healthy": healthy,
            "checks": checks,
            "message": f"Video daemon {self._status}",
            "timestamp": time.time(),
        }

    async def on_system_wake(self) -> None:
        """Handle system wake from sleep.

        Video daemon doesn't need special handling on wake - it just
        continues waiting for D-Bus commands. If it was rendering before
        sleep, the v4l2 device may need to be re-initialized.
        """
        logger.info("System wake detected")
        # If we were rendering, the device may be stale - stop and let caller restart
        if self._status == "rendering":
            logger.warning("Was rendering before sleep - stopping render")
            await self._stop_render()

    # =========================================================================
    # Main Loop
    # =========================================================================

    async def run(self):
        """Main daemon loop."""
        self.is_running = True
        self.start_time = time.time()

        # Start D-Bus if enabled
        if self.enable_dbus:
            if not await self.start_dbus():
                logger.error("Failed to start D-Bus, continuing without it")

        # If --create-device was specified, create the device now
        if self.create_device:
            try:
                device_path = setup_v4l2_device(self._width, self._height)
                self._current_device = device_path
                logger.info(f"Created video device: {device_path}")
            except Exception as e:
                logger.error(f"Failed to create video device: {e}")

        logger.info(f"Video daemon started (flip={self._flip}, create_device={self.create_device})")
        logger.info("Waiting for D-Bus commands...")

        # Main idle loop - just wait for shutdown
        try:
            while not self._shutdown_requested:
                await asyncio.sleep(1.0)

                # Update frame rate if rendering
                if self._status == "rendering" and self._render_start_time:
                    elapsed = time.time() - self._render_start_time
                    if elapsed > 0:
                        self._frame_rate = self._frames_rendered / elapsed

        except asyncio.CancelledError:
            logger.info("Daemon cancelled")

        # Cleanup
        await self._handle_stop_video()
        await self.stop_dbus()
        cleanup_device()

        self.is_running = False
        logger.info("Video daemon stopped")

    def request_shutdown(self):
        """Request graceful shutdown."""
        self._shutdown_requested = True
        self._shutdown_event.set()


# =============================================================================
# CLI
# =============================================================================


async def check_status():
    """Check if daemon is running and get status."""
    client = get_client("video")
    try:
        if await client.connect():
            status = await client.get_status()
            await client.disconnect()
            print(json.dumps(status, indent=2))
            return True
    except Exception as e:
        print(f"Error: {e}")
    print("Video daemon is not running")
    return False


async def stop_daemon():
    """Stop the running daemon."""
    client = get_client("video")
    try:
        if await client.connect():
            result = await client.shutdown()
            await client.disconnect()
            print(json.dumps(result, indent=2))
            return True
    except Exception as e:
        print(f"Error: {e}")
    print("Video daemon is not running")
    return False


async def start_video_cli(device: str, audio_input: str, audio_output: str, flip: bool):
    """Start video rendering via D-Bus."""
    client = get_client("video")
    try:
        if await client.connect():
            result = await client.call_method(
                "start_video", [device, audio_input or "", audio_output or "", 1920, 1080, flip]
            )
            await client.disconnect()
            print(json.dumps(result, indent=2))
            return True
    except Exception as e:
        print(f"Error: {e}")
    print("Video daemon is not running")
    return False


async def stop_video_cli():
    """Stop video rendering via D-Bus."""
    client = get_client("video")
    try:
        if await client.connect():
            result = await client.call_method("stop_video", [])
            await client.disconnect()
            print(json.dumps(result, indent=2))
            return True
    except Exception as e:
        print(f"Error: {e}")
    print("Video daemon is not running")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Video Generator Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run daemon in production mode (wait for meet_daemon)
  python scripts/video_daemon.py

  # Run in test mode (self-contained, uses default mic/speakers)
  python scripts/video_daemon.py --test --create-device --flip

  # Start video rendering via D-Bus
  python scripts/video_daemon.py --start-video /dev/video10 --audio-input default

  # Check status
  python scripts/video_daemon.py --status
""",
    )
    parser.add_argument("--status", action="store_true", help="Check daemon status")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--no-dbus", action="store_true", help="Disable D-Bus")
    parser.add_argument(
        "--create-device",
        action="store_true",
        help="Create v4l2loopback device (for testing without meet_daemon)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: use default mic/speakers instead of meet_daemon devices",
    )
    parser.add_argument(
        "--flip",
        action="store_true",
        help="Enable horizontal flip (for Google Meet)",
    )

    # D-Bus control commands
    parser.add_argument(
        "--start-video",
        metavar="DEVICE",
        help="Start video rendering to device (e.g., /dev/video10)",
    )
    parser.add_argument(
        "--stop-video",
        action="store_true",
        help="Stop video rendering",
    )
    parser.add_argument(
        "--audio-input",
        metavar="SOURCE",
        help="PulseAudio source for waveform (e.g., meet_bot_sink.monitor or 'default')",
    )
    parser.add_argument(
        "--audio-output",
        metavar="SOURCE",
        help="PulseAudio source for TTS output (e.g., meet_bot_mic or empty for speakers)",
    )

    args = parser.parse_args()

    # Handle CLI commands
    if args.status:
        sys.exit(0 if asyncio.run(check_status()) else 1)

    if args.stop:
        sys.exit(0 if asyncio.run(stop_daemon()) else 1)

    if args.start_video:
        audio_input = args.audio_input or ("default" if args.test else "")
        audio_output = args.audio_output or ""
        sys.exit(0 if asyncio.run(start_video_cli(args.start_video, audio_input, audio_output, args.flip)) else 1)

    if args.stop_video:
        sys.exit(0 if asyncio.run(stop_video_cli()) else 1)

    # Run daemon
    instance = SingleInstance()
    if not instance.acquire():
        pid = instance.get_running_pid()
        print(f"Video daemon already running (PID: {pid})")
        sys.exit(1)

    daemon = VideoDaemon(
        verbose=args.verbose,
        enable_dbus=not args.no_dbus,
        create_device=args.create_device,
        default_flip=args.flip,
        test_mode=args.test,
    )

    # Signal handlers
    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        daemon.request_shutdown()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        asyncio.run(daemon.run())
    finally:
        instance.release()


if __name__ == "__main__":
    main()
