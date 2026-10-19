"""Realtime video renderer facade combining the drawing and stream mixins."""

import logging
from typing import Optional

import numpy as np
import tool_modules.aa_meet_bot.src.video_gl_env  # noqa: F401  # pylint: disable=unused-import
from tool_modules.aa_meet_bot.src.video_config import Attendee, VideoConfig
from tool_modules.aa_meet_bot.src.video_draw import RealtimeDrawMixin
from tool_modules.aa_meet_bot.src.video_frame import RealtimeFrameMixin
from tool_modules.aa_meet_bot.src.video_stream import RealtimeStreamMixin
from tool_modules.aa_meet_bot.src.video_theme import apply_wave_layout

logger = logging.getLogger(__name__)

_gpu_text_available = False
try:
    from tool_modules.aa_meet_bot.src.gpu_text import VideoTextRenderer

    _gpu_text_available = True
except ImportError:
    VideoTextRenderer = None  # type: ignore[misc, assignment]
    logger.debug("GPU text rendering not available (install PyOpenGL freetype-py glfw)")


class RealtimeVideoRenderer(RealtimeDrawMixin, RealtimeFrameMixin, RealtimeStreamMixin):
    """Real-time video renderer using dynamic waveform and NPU panels.

    Audio-reactive mode connects to a PulseAudio source and draws meeting
    audio levels instead of a simulated waveform.
    """

    def __init__(
        self,
        config: Optional[VideoConfig] = None,
        audio_source: Optional[str] = None,
        sink_input_index: Optional[int] = None,
        enable_webrtc: bool = False,
    ):
        """
        Initialize the real-time video renderer.

        Args:
            config: Video configuration
            audio_source: Optional PulseAudio source name for audio-reactive waveform
                         For direct capture: e.g., "alsa_input..." (physical mic)
                         For monitor-stream: just used for logging
            sink_input_index: If provided, use parec --monitor-stream to capture
                             directly from this sink-input index. This bypasses
                             broken null-sink monitors in PipeWire.
            enable_webrtc: Enable WebRTC streaming for preview (port 8765)
        """
        self.__dict__["config"] = config or VideoConfig()
        self.__dict__["_running"] = False

        # Video mode: "black" (render black frames) or "full" (render AI overlay)
        # Can be changed at runtime without restarting the render loop
        self.__dict__["_video_mode"] = "full"

        # WebRTC streaming for preview
        self.__dict__["_enable_webrtc"] = enable_webrtc
        self.__dict__["_webrtc_pipeline"] = None

        # Audio capture for reactive waveform
        self.__dict__["_audio_source"] = audio_source
        self.__dict__["_sink_input_index"] = (
            sink_input_index  # For monitor-stream capture
        )
        self.__dict__["_audio_capture"] = None
        self.__dict__["_audio_buffer"] = None
        # Note: Lock is created lazily in _start_audio_capture since we may not be in async context
        self.__dict__["_audio_lock"] = None

        # Speech-to-text using OpenVINO on NPU
        self.__dict__["_stt_engine"] = None
        self.__dict__["_stt_text"] = ""  # Current transcription text
        self.__dict__["_stt_text_lock"] = None
        # Pre-allocated contiguous buffer for STT audio (15 seconds max at 16kHz)
        self.__dict__["_stt_buffer_size"] = 16000 * 15  # 15 seconds = 240000 samples
        self.__dict__["_stt_buffer"] = np.zeros(self._stt_buffer_size, dtype=np.float32)
        self.__dict__["_stt_write_pos"] = (
            0  # Write position (also = number of valid samples)
        )
        self.__dict__["_stt_last_process"] = 0.0
        self.__dict__["_stt_enabled"] = (
            audio_source is not None
        )  # Enable STT if audio source provided
        # History of transcriptions, most recent first.
        self.__dict__["_stt_history"] = []
        self.__dict__["_stt_history_max"] = 6  # Max number of lines to keep

        # Real NPU stats (updated every 0.5s by background task)
        self.__dict__["_npu_stats"] = {
            "freq_mhz": 0,
            "max_freq_mhz": 1400,
            "busy_us": 0,
            "busy_delta_us": 0,  # Change since last read (for utilization calc)
            "mem_bytes": 0,
            "power_state": "D0",
            "runtime_status": "active",
            "active_ms": 0,
            "last_update": 0.0,
        }
        self.__dict__["_npu_stats_prev_busy"] = 0  # For calculating delta

        # Real STT/inference stats (from the STT engine)
        self.__dict__["_stt_stats"] = {
            "inference_count": 0,
            "samples_processed": 0,
            "last_inference_ms": 0.0,
            "last_rt": 0.0,
            "avg_rt": 0.0,
            "avg_latency_ms": 0.0,
            "inferences_per_second": 0.0,
        }

        # Try to load fonts
        try:
            from PIL import ImageFont  # pylint: disable=import-outside-toplevel

            self.__dict__["font_small"] = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 14
            )
            self.__dict__["font_medium"] = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 18
            )
            self.__dict__["font_large"] = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 24
            )
        except Exception:  # pylint: disable=broad-exception-caught
            from PIL import ImageFont  # pylint: disable=import-outside-toplevel

            self.__dict__["font_small"] = ImageFont.load_default()
            self.__dict__["font_medium"] = self.font_small
            self.__dict__["font_large"] = self.font_small

        apply_wave_layout(self)

        # Dynamic attendee updates (set via update_attendees method)
        self.__dict__["_dynamic_attendees"] = None
        self.__dict__["_attendees_updated"] = False

        self._init_gpu_text()

        # Pre-render static elements for performance
        self.__dict__["_static_cache"] = {}
        self._init_static_cache()

    def _init_gpu_text(self) -> None:
        """Create the OpenGL text renderer required for overlays."""
        self.__dict__["_gpu_text_renderer"] = None
        if not _gpu_text_available:
            raise RuntimeError(
                "GPU text renderer (OpenGL) is required but not available"
            )
        try:
            if self.config.height >= 1080:
                font_sizes = {
                    "xlarge": 36,
                    "large": 26,
                    "medium": 24,
                    "normal": 18,
                    "small": 14,
                    "tiny": 12,
                }
            else:
                font_sizes = {
                    "xlarge": 34,
                    "large": 24,
                    "medium": 22,
                    "normal": 16,
                    "small": 12,
                    "tiny": 10,
                }
            self.__dict__["_gpu_text_renderer"] = VideoTextRenderer(
                self.config.width, self.config.height, font_sizes=font_sizes
            )
            if self._gpu_text_renderer.initialize():
                logger.info("GPU text rendering enabled (smooth anti-aliased fonts)")
            else:
                raise RuntimeError("GPU text init failed")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                f"GPU text renderer required but not available: {exc}"
            ) from exc

    def update_attendees(self, attendees: list) -> None:
        """
        Update the attendee list dynamically during rendering.

        Called by video_daemon when it receives updated attendees via D-Bus.

        Args:
            attendees: List of attendee dicts with 'name' and optionally Slack enrichment:
                       - slack_id: Slack user ID
                       - slack_display_name: Slack display name
                       - photo_path: Path to cached Slack profile photo
                       - email: User email
        """
        # Convert dicts to Attendee objects, preserving all enrichment data
        attendee_objs = []
        for a in attendees:
            if isinstance(a, dict):
                attendee_objs.append(
                    Attendee(
                        name=a.get("name", "Unknown"),
                        slack_id=a.get("slack_id"),
                        slack_display_name=a.get("slack_display_name"),
                        photo_path=a.get("photo_path"),
                        email=a.get("email"),
                    )
                )
            elif hasattr(a, "name"):
                attendee_objs.append(a)
            else:
                attendee_objs.append(Attendee(name=str(a)))

        self.__dict__["_dynamic_attendees"] = attendee_objs
        self.__dict__["_attendees_updated"] = True
        logger.info(
            "Updated attendees: %s participants with Slack data", len(attendee_objs)
        )

    def set_video_mode(self, mode: str) -> None:
        """
        Set the video rendering mode without restarting the render loop.

        Args:
            mode: "black" for black screen, "full" for full AI overlay
        """
        if mode not in ("black", "full"):
            logger.warning("Invalid video mode: %s, ignoring", mode)
            return

        if mode != self._video_mode:
            logger.info("Video mode changed: %s -> %s", self._video_mode, mode)
            self.__dict__["_video_mode"] = mode

    def get_video_mode(self) -> str:
        """Get the current video rendering mode."""
        return self._video_mode

    async def stop_async(self):
        """Stop the real-time stream (async version)."""
        self.__dict__["_running"] = False

        # Stop audio capture
        if self._audio_capture:
            await self._audio_capture.stop()
            self.__dict__["_audio_capture"] = None

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            self.__dict__["_webrtc_pipeline"] = None

        # Clean up GPU text renderer (CRITICAL: must cleanup GLFW context)
        if hasattr(self, "_gpu_text_renderer") and self._gpu_text_renderer:
            try:
                self._gpu_text_renderer.cleanup()
                logger.info("GPU text renderer cleaned up")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Error cleaning up GPU text renderer: %s", e)
            self.__dict__["_gpu_text_renderer"] = None

        # Reset state for clean restart
        self.__dict__["_audio_buffer"] = None
        if hasattr(self, "_ulc_renderer"):
            self.__dict__["_ulc_renderer"] = None

    def stop(self):
        """Stop the real-time stream."""
        self.__dict__["_running"] = False

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            self.__dict__["_webrtc_pipeline"] = None

        # Clean up GPU text renderer (CRITICAL: must cleanup GLFW context)
        if hasattr(self, "_gpu_text_renderer") and self._gpu_text_renderer:
            try:
                self._gpu_text_renderer.cleanup()
                logger.info("GPU text renderer cleaned up")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Error cleaning up GPU text renderer: %s", e)
            self.__dict__["_gpu_text_renderer"] = None

        # Reset state for clean restart
        self.__dict__["_audio_buffer"] = None
        if hasattr(self, "_ulc_renderer"):
            self.__dict__["_ulc_renderer"] = None
