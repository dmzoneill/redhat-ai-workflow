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
    python -m services.video

    # Test mode (self-contained)
    python -m services.video --test --create-device --flip

    # Control running daemon
    python -m services.video --status
    python -m services.video --stop

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
        VideoReady(device)  # Emitted when video stream is active and device is ready
        StreamingStarted(mode, port)
        StreamingStopped()
        Error(message)
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from scripts.common.video_device import cleanup_device, setup_v4l2_device
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase, get_client
from services.base.sleep_wake import SleepWakeAwareDaemon

logger = logging.getLogger(__name__)


class VideoDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Video generator daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "video"
    description = "Video Generator Daemon"

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
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)
        self.is_running = False  # Set to True in startup()
        self.create_device = create_device  # If True, daemon creates v4l2 device
        self.default_flip = default_flip
        self.test_mode = test_mode  # If True, use default mic/speakers

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
        self._max_slack_cache_size = 200  # Prevent unbounded memory growth

        # Video mode: "black" (idle/disabled), "full" (AI overlay), None (stopped)
        self._video_mode: Optional[str] = None

        # Register D-Bus method handlers
        self.register_handler("start_video", self._handle_start_video)
        self.register_handler("start_black_screen", self._handle_start_black_screen)
        self.register_handler("switch_to_full_video", self._handle_switch_to_full_video)
        self.register_handler("toggle_video", self._handle_toggle_video)
        self.register_handler("update_audio_source", self._handle_update_audio_source)
        self.register_handler("stop_video", self._handle_stop_video)
        self.register_handler("update_attendees", self._handle_update_attendees)
        self.register_handler("get_attendees", self._handle_get_attendees)
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
        sink_input_index: int = -1,
    ) -> dict:
        """
        Start video rendering to the specified device.

        Called by meet_daemon when a meeting starts, or directly for testing.

        Args:
            device: v4l2loopback device path (e.g., /dev/video10)
            audio_input: PulseAudio source for waveform visualization
                        For test mode: "default" uses physical mic
                        For production with sink_input_index: just for logging
            audio_output: PulseAudio source for TTS audio output
                         (e.g., "meet_bot_abc123_mic" or "" for test mode)
            width: Video width (default 1920)
            height: Video height (default 1080)
            flip: Enable horizontal flip for Google Meet mirror compensation
            sink_input_index: If >= 0, use parec --monitor-stream to capture
                             directly from this sink-input. This bypasses broken
                             null-sink monitors in PipeWire. Use -1 to disable.
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

            # Store sink_input_index for monitor-stream capture
            self._sink_input_index = sink_input_index if sink_input_index >= 0 else None

            # Handle audio input (for waveform visualization)
            if audio_input == "default" or (self.test_mode and not audio_input):
                # Test mode: use default microphone (direct source capture)
                self._audio_input = self._get_default_audio_source()
                self._sink_input_index = None  # Don't use monitor-stream in test mode
                logger.info(f"Using default audio input: {self._audio_input}")
            elif audio_input:
                # Production mode: audio_input is for logging, actual capture via sink_input_index
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

    async def _handle_start_black_screen(
        self,
        device: str,
        width: int = 1920,
        height: int = 1080,
    ) -> dict:
        """
        Start rendering a black screen to the video device.

        This is a lightweight mode used when:
        - Video is disabled for the meeting but we need the device active
        - Waiting for the user to enable video
        - Initial state before switching to full video

        The black screen uses minimal CPU/GPU - just writes black YUYV frames.
        Chrome will see the device as an active camera.

        Args:
            device: v4l2loopback device path (e.g., /dev/video10)
            width: Video width (default 1920)
            height: Video height (default 1080)

        Returns:
            dict with success status and device info
        """
        if self._status == "rendering":
            # If already rendering, check if we need to switch modes
            if self._video_mode == "black":
                return {
                    "success": True,
                    "message": "Already rendering black screen",
                    "device": device,
                }
            else:
                # Stop current rendering first
                await self._handle_stop_video()

        try:
            self._current_device = device
            self._width = width
            self._height = height
            self._video_mode = "black"
            self._frames_rendered = 0
            self._render_start_time = time.time()

            # Start the unified render loop (renderer will check _video_mode)
            # Using _render_loop which creates RealtimeVideoRenderer
            # The renderer will render black frames when _video_mode == "black"
            self._render_task = asyncio.create_task(self._render_loop())
            self._status = "rendering"

            # Emit signals
            self.emit_event("RenderingStarted", device)

            logger.info(
                f"Started rendering to {device} ({width}x{height}) in black mode"
            )
            return {
                "success": True,
                "device": device,
                "mode": "black",
                "width": width,
                "height": height,
            }

        except Exception as e:
            self._status = "error"
            logger.error(f"Failed to start black screen: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_switch_to_full_video(
        self,
        audio_input: str = "",
        audio_output: str = "",
        flip: bool = False,
        sink_input_index: int = -1,
    ) -> dict:
        """
        Switch from black screen mode to full AI video overlay.

        Called when user enables video during a meeting.
        The unified render loop keeps running - we just change the mode flag.
        This prevents Chrome from losing the camera connection.

        Args:
            audio_input: PulseAudio source for waveform visualization
                        For test mode: "default" uses physical mic
                        For production with sink_input_index: just for logging
            audio_output: PulseAudio source for TTS audio output
            flip: Enable horizontal flip for Google Meet mirror compensation
            sink_input_index: If >= 0, use parec --monitor-stream to capture
                             directly from this sink-input. Use -1 to disable.

        Returns:
            dict with success status
        """
        if self._status != "rendering":
            return {
                "success": False,
                "error": "Not currently rendering. Call start_black_screen first.",
            }

        if self._video_mode == "full":
            # Already in full mode - just update audio source if needed
            return await self._handle_update_audio_source(sink_input_index)

        try:
            device = self._current_device

            # Update audio settings
            self._flip = flip
            self._sink_input_index = sink_input_index if sink_input_index >= 0 else None

            if audio_input == "default" or (self.test_mode and not audio_input):
                self._audio_input = self._get_default_audio_source()
                self._sink_input_index = None  # Don't use monitor-stream in test mode
            elif audio_input:
                self._audio_input = audio_input
            else:
                self._audio_input = None

            if audio_output == "default" or (self.test_mode and not audio_output):
                self._audio_output = None
            elif audio_output:
                self._audio_output = audio_output
            else:
                self._audio_output = None

            # Set flip environment variable
            if flip:
                os.environ["FLIP"] = "1"
            else:
                os.environ.pop("FLIP", None)

            # Just change the mode flag - the render loop will pick it up
            # No need to cancel/restart the loop!
            old_mode = self._video_mode
            self._video_mode = "full"

            # Also update the renderer's mode if it exists
            if self._renderer and hasattr(self._renderer, "set_video_mode"):
                self._renderer.set_video_mode("full")

            logger.info(f"Switched video mode: {old_mode} -> full (no loop restart)")

            logger.info(f"Switched to full video mode on {device}")
            return {
                "success": True,
                "device": device,
                "mode": "full",
                "audio_input": self._audio_input,
            }

        except Exception as e:
            self._status = "error"
            logger.error(f"Failed to switch to full video: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_toggle_video(self, enabled: bool = True) -> dict:
        """
        Toggle video on (full) or off (black).

        Args:
            enabled: True = show full video, False = show black screen

        The render loop keeps running - we just change the mode flag.
        This prevents Chrome from losing the camera connection.

        Returns:
            dict with success status and current mode
        """
        if self._status != "rendering":
            return {"success": False, "error": "Not currently rendering"}

        new_mode = "full" if enabled else "black"

        if self._video_mode == new_mode:
            return {
                "success": True,
                "mode": new_mode,
                "message": f"Already in {new_mode} mode",
            }

        try:
            old_mode = self._video_mode
            self._video_mode = new_mode

            # Update the renderer's mode
            if self._renderer and hasattr(self._renderer, "set_video_mode"):
                self._renderer.set_video_mode(new_mode)

            logger.info(f"Toggled video: {old_mode} -> {new_mode}")
            return {
                "success": True,
                "device": self._current_device,
                "mode": new_mode,
                "enabled": enabled,
            }

        except Exception as e:
            logger.error(f"Failed to toggle video: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_update_audio_source(
        self,
        sink_input_index: int = -1,
    ) -> dict:
        """
        Update the audio source for waveform visualization without restarting render loop.

        This is called after joining a meeting to provide the Chromium sink-input index
        for monitor-stream capture. Unlike switch_to_full_video, this does NOT restart
        the render loop - it just updates the audio capture.

        Args:
            sink_input_index: Chromium's sink-input index for parec --monitor-stream

        Returns:
            dict with success status
        """
        if self._status != "rendering":
            return {"success": False, "error": "Not currently rendering"}

        if self._video_mode != "full":
            return {"success": False, "error": "Not in full video mode"}

        new_sink_input_index = sink_input_index if sink_input_index >= 0 else None

        if new_sink_input_index == getattr(self, "_sink_input_index", None):
            return {"success": True, "message": "Audio source unchanged"}

        try:
            logger.info(
                "Updating audio source: sink_input_index "
                f"{getattr(self, '_sink_input_index', None)} -> {new_sink_input_index}"
            )
            self._sink_input_index = new_sink_input_index

            # If we have a renderer, update its audio capture
            if self._renderer:
                # Stop existing audio capture
                if (
                    hasattr(self._renderer, "_audio_capture")
                    and self._renderer._audio_capture
                ):
                    await self._renderer._audio_capture.stop()

                # Update the sink_input_index and restart audio capture
                self._renderer._sink_input_index = new_sink_input_index
                if hasattr(self._renderer, "_start_audio_capture"):
                    await self._renderer._start_audio_capture()
                    logger.info(
                        f"Audio capture restarted with sink_input_index={new_sink_input_index}"
                    )

            return {
                "success": True,
                "sink_input_index": new_sink_input_index,
            }

        except Exception as e:
            logger.error(f"Failed to update audio source: {e}")
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
        """Stop video rendering and release all resources."""
        if self._status != "rendering":
            return {"success": True, "message": "Not rendering"}

        try:
            logger.info("Stopping video rendering...")

            # Cancel render task first
            if self._render_task:
                self._render_task.cancel()
                try:
                    await asyncio.wait_for(self._render_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError) as exc:
                    logger.debug("Suppressed error: %s", exc)
                self._render_task = None

            # Clean up renderer - use async stop if available
            if self._renderer:
                try:
                    if hasattr(self._renderer, "stop_async"):
                        await self._renderer.stop_async()
                        logger.info("Renderer stopped (async)")
                    else:
                        self._renderer.stop()
                        logger.info("Renderer stopped (sync)")
                except Exception as e:
                    logger.warning(f"Error stopping renderer: {e}")
                self._renderer = None

            # Reset video mode
            self._video_mode = "black"
            self._status = "idle"
            self._current_device = None
            self._attendees = []

            # Emit signal
            self.emit_event("RenderingStopped", "")

            logger.info("Video rendering stopped - resources released")
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
            logger.info(
                f"Updated attendees: {len(enriched_attendees)} participants, "
                f"{photos_found} with photos"
            )

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

    async def _handle_get_attendees(self) -> dict:
        """Get the current list of attendees."""
        return {
            "success": True,
            "count": len(self._attendees),
            "attendees": self._attendees,
        }

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
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)

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
                from services.slack.dbus import SlackAgentClient

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
                    f"Resolved '{name}' -> Slack user {result['slack_id']} "
                    f"(score: {result['match_score']:.2f})"
                )

            # Cache the result (even if empty to avoid repeated lookups)
            # Enforce cache size limit
            if len(self._slack_cache) >= self._max_slack_cache_size:
                # Remove oldest entry
                oldest_key = next(iter(self._slack_cache))
                del self._slack_cache[oldest_key]
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
        """
        Main rendering loop - delegates to RealtimeVideoRenderer.

        The renderer handles everything:
        - Opens and manages the v4l2 device
        - Checks _video_mode to render black or full content
        - Mode can be changed at runtime without restarting
        """
        try:
            from tool_modules.aa_meet_bot.src.video_generator import (
                Attendee,
                RealtimeVideoRenderer,
                VideoConfig,
            )

            # Create config
            if self._width == 1280 and self._height == 720:
                config = VideoConfig.hd_720p()
            else:
                config = VideoConfig()  # Default 1080p

            # Create renderer with audio source for waveform
            sink_input_idx = getattr(self, "_sink_input_index", None)
            self._renderer = RealtimeVideoRenderer(
                config=config,
                audio_source=self._audio_input,
                sink_input_index=sink_input_idx,
            )

            # Set initial video mode
            self._renderer.set_video_mode(self._video_mode)

            logger.info(
                f"Starting render loop to {self._current_device} "
                f"(mode={self._video_mode}, audio_input={self._audio_input}, "
                f"sink_input_index={sink_input_idx})"
            )

            # Get initial attendees
            attendee_objs = [
                Attendee(name=a.get("name", "Unknown")) for a in self._attendees
            ]
            if not attendee_objs:
                attendee_objs = [Attendee(name="Waiting for participants...")]

            # Signal that video is ready
            self.emit_event("VideoReady", self._current_device)
            logger.info(f"Video ready on {self._current_device}")

            # Run the renderer's main loop - it handles v4l2, mode switching, everything
            await self._renderer.stream_realtime(
                attendees=attendee_objs,
                video_device=self._current_device,
                loop=True,
            )

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
                except Exception as exc:
                    logger.debug("Suppressed error: %s", exc)
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
            checks["device_exists"] = (
                self._current_device and Path(self._current_device).exists()
            )

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
            await self._handle_stop_video()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

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

        self.is_running = True
        logger.info(
            f"Video daemon ready (flip={self._flip}, create_device={self.create_device})"
        )
        logger.info("Waiting for D-Bus commands...")

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
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

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Video daemon shutting down...")

        # Stop rendering
        await self._handle_stop_video()

        # Stop D-Bus
        if self.enable_dbus:
            await self.stop_dbus()

        # Clean up device
        cleanup_device()

        self.is_running = False
        await super().shutdown()
        logger.info("Video daemon stopped")


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
                "start_video",
                [device, audio_input or "", audio_output or "", 1920, 1080, flip],
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


if __name__ == "__main__":
    VideoDaemon.main()
