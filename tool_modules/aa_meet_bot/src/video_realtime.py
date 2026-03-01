"""
Real-time video renderer for meeting overlay.

Extracted from video_generator.py. Contains RealtimeVideoRenderer class
for dynamic frame generation with GPU pipeline, audio-reactive waveform,
and NPU stats.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import math
import os
import random
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .video_config import (
    FAKE_FINDINGS,
    RESEARCH_TOOLS,
    THREAT_ASSESSMENTS,
    Attendee,
    VideoConfig,
)
from .video_gpu import (
    MEMORY_CRITICAL_MB,
    MEMORY_WARNING_MB,
    UltraLowCPURenderer,
    get_memory_mb,
)

logger = logging.getLogger(__name__)

# OpenCV font settings (much faster than PIL)
CV_FONT = cv2.FONT_HERSHEY_SIMPLEX
CV_FONT_MONO = cv2.FONT_HERSHEY_PLAIN  # More monospace-like
CV_LINE_TYPE = cv2.LINE_8  # Was CV_LINE_TYPE
CV_GREEN = (0, 200, 0)
CV_CYAN = (200, 200, 0)
CV_WHITE = (255, 255, 255)
CV_YELLOW = (0, 255, 255)
CV_RED = (0, 0, 200)
CV_DARK_GREEN = (0, 100, 0)

# Optional GPU text rendering (smooth anti-aliased TrueType fonts)
_gpu_text_available = False
try:
    from .gpu_text import VideoTextRenderer

    _gpu_text_available = True
except ImportError:
    logger.debug("GPU text rendering not available (install PyOpenGL freetype-py glfw)")


class RealtimeVideoRenderer:
    """
    Real-time video renderer using PIL for dynamic frame generation.

    Generates waveform and NPU panels on-the-fly instead of using pre-rendered files.
    This uses more CPU but allows truly dynamic content.

    Audio-Reactive Mode:
        When connected to a PulseAudio source, the waveform displays actual
        audio levels from the meeting in real-time.
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
        self.config = config or VideoConfig()
        self._running = False

        # Video mode: "black" (render black frames) or "full" (render AI overlay)
        # Can be changed at runtime without restarting the render loop
        self._video_mode = "full"

        # WebRTC streaming for preview
        self._enable_webrtc = enable_webrtc
        self._webrtc_pipeline = None

        # Audio capture for reactive waveform
        self._audio_source = audio_source
        self._sink_input_index = sink_input_index  # For monitor-stream capture
        self._audio_capture = None
        self._audio_buffer: Optional[np.ndarray] = None
        # Note: Lock is created lazily in _start_audio_capture since we may not be in async context
        self._audio_lock: Optional[asyncio.Lock] = None

        # Speech-to-text using OpenVINO on NPU
        self._stt_engine = None
        self._stt_text: str = ""  # Current transcription text
        self._stt_text_lock: Optional[asyncio.Lock] = None
        # Pre-allocated contiguous buffer for STT audio (15 seconds max at 16kHz)
        self._stt_buffer_size = 16000 * 15  # 15 seconds = 240000 samples
        self._stt_buffer: np.ndarray = np.zeros(self._stt_buffer_size, dtype=np.float32)
        self._stt_write_pos: int = 0  # Write position (also = number of valid samples)
        self._stt_last_process: float = 0.0
        self._stt_enabled: bool = (
            audio_source is not None
        )  # Enable STT if audio source provided
        self._stt_history: list = []  # History of transcriptions (most recent first)
        self._stt_history_max: int = 6  # Max number of lines to keep

        # Real NPU stats (updated every 0.5s by background task)
        self._npu_stats: dict = {
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
        self._npu_stats_prev_busy: int = 0  # For calculating delta

        # Real STT/inference stats (from the STT engine)
        self._stt_stats: dict = {
            "inference_count": 0,
            "samples_processed": 0,
            "last_inference_ms": 0.0,
            "last_rt": 0.0,
            "avg_rt": 0.0,
            "avg_rtf": 0.0,  # Real-time factor from STT engine
            "avg_latency_ms": 0.0,
            "inferences_per_second": 0.0,
        }

        # Try to load fonts
        try:
            from PIL import ImageFont

            self.font_small = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 14
            )
            self.font_medium = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 18
            )
            self.font_large = ImageFont.truetype(
                "/usr/share/fonts/liberation-mono/LiberationMono-Regular.tt", 24
            )
        except Exception:
            from PIL import ImageFont

            self.font_small = ImageFont.load_default()
            self.font_medium = self.font_small
            self.font_large = self.font_small

        # Waveform config - from native pixel config
        self.wave_width = self.config.wave_w
        self.wave_height = self.config.wave_h
        self.wave_bars = self.config.num_bars

        # NPU panel config - full width at bottom
        self.npu_width = self.config.width
        self.npu_height = 140

        # Pre-compute bar positions for waveform
        self.wave_step = self.wave_width / self.wave_bars
        self.wave_bar_width = max(2, int(self.wave_step) - 1)

        # Random phases for waveform animation (using numpy for speed)
        np.random.seed(42)  # Reproducible
        self.wave_phases = np.random.uniform(0, 6.28, self.wave_bars)
        self.wave_speeds = np.random.uniform(0.8, 1.2, self.wave_bars)
        self.wave_i_arr = np.arange(self.wave_bars)

        # Audio analysis state
        self._fft_smoothing = (
            0.3  # Smoothing factor for FFT (0=no smoothing, 1=max smoothing)
        )
        self._prev_fft_bars: Optional[np.ndarray] = None

        # Dynamic attendee updates (set via update_attendees method)
        self._dynamic_attendees: Optional[list] = None
        self._attendees_updated: bool = False

        # GPU text renderer (smooth anti-aliased TrueType fonts via OpenGL)
        # Font sizes are resolution-dependent: 1080p gets +2pt for readability
        self._gpu_text_renderer: Optional["VideoTextRenderer"] = None
        if _gpu_text_available:
            try:
                # 1080p: larger fonts for readability at higher res
                # 720p: smaller fonts to fit the layout
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

                self._gpu_text_renderer = VideoTextRenderer(
                    self.config.width, self.config.height, font_sizes=font_sizes
                )
                if self._gpu_text_renderer.initialize():
                    logger.info(
                        "GPU text rendering enabled (smooth anti-aliased fonts)"
                    )
                else:
                    raise RuntimeError("GPU text init failed")
            except Exception as e:
                raise RuntimeError(
                    f"GPU text renderer required but not available: {e}"
                ) from e
        else:
            raise RuntimeError(
                "GPU text renderer (OpenGL) is required but not available"
            )

        # Pre-render static elements for performance
        self._static_cache = {}
        self._init_static_cache()

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

        self._dynamic_attendees = attendee_objs
        self._attendees_updated = True
        logger.info(
            f"Updated attendees: {len(attendee_objs)} participants with Slack data"
        )

    def _init_static_cache(self):
        """
        Pre-render static UI elements using OpenCV (much faster than PIL).

        This significantly reduces text rendering overhead by caching:
        - Header text
        - Section headers
        - Static labels
        - UI borders/lines
        """
        config = self.config

        # Create a base frame with OpenCV (BGR format)
        base_frame = np.zeros((config.height, config.width, 3), dtype=np.uint8)

        # Layout constants
        right_col_x = config.width - config.right_column_width
        npu_panel_height = self.npu_height
        bottom_section_y = config.height - npu_panel_height
        padding = 15

        # Font scales for different sizes
        font_small = 0.45
        font_medium = 0.55
        thickness = 1

        # Static header
        cv2.putText(
            base_frame,
            "[ AI RESEARCH MODULE v2.1 ]",
            (padding, 22),
            CV_FONT,
            font_medium,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Right column vertical divider
        cv2.line(
            base_frame, (right_col_x, 50), (right_col_x, bottom_section_y), CV_GREEN, 2
        )

        # "Building Context" heading
        cv2.putText(
            base_frame,
            "BUILDING CONTEXT",
            (right_col_x + 8, 68),
            CV_FONT,
            font_small,
            CV_RED,
            thickness,
            CV_LINE_TYPE,
        )

        # Section headers (static)
        sections_start_y = 75
        section_height = (bottom_section_y - sections_start_y) // 4
        section_headers = ["[ JIRA ]", "[ SLACK ]", "[ SEMANTIC ]", "[ COMMS ]"]
        for i, header in enumerate(section_headers):
            sec_y = sections_start_y + i * section_height + 12
            cv2.putText(
                base_frame,
                header,
                (right_col_x + 8, sec_y),
                CV_FONT,
                font_small,
                CV_CYAN,
                thickness,
                CV_LINE_TYPE,
            )

        # Facial recognition box and label
        silhouette_w = 180
        silhouette_h = 200
        silhouette_x = right_col_x - silhouette_w - 20
        silhouette_y = 55
        cv2.putText(
            base_frame,
            "FACIAL RECOGNITION",
            (silhouette_x + 20, silhouette_y - 5),
            CV_FONT,
            font_small,
            CV_RED,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.rectangle(
            base_frame,
            (silhouette_x, silhouette_y),
            (silhouette_x + silhouette_w, silhouette_y + silhouette_h),
            CV_GREEN,
            2,
        )

        # Silhouette shape (static) - using filled shapes
        head_cx = silhouette_x + silhouette_w // 2
        head_cy = silhouette_y + 50
        cv2.circle(base_frame, (head_cx, head_cy), 28, CV_DARK_GREEN, -1)  # Head
        cv2.rectangle(
            base_frame,
            (head_cx - 40, head_cy + 35),
            (head_cx + 40, head_cy + 145),
            CV_DARK_GREEN,
            -1,
        )  # Body
        cv2.rectangle(
            base_frame,
            (head_cx - 55, head_cy + 35),
            (head_cx + 55, head_cy + 60),
            CV_DARK_GREEN,
            -1,
        )  # Shoulders

        # Waveform box - from native config
        wave_w = config.wave_w
        wave_h = config.wave_h
        wave_x = config.wave_x
        wave_y = config.wave_y
        cv2.rectangle(
            base_frame,
            (wave_x, wave_y),
            (wave_x + wave_w, wave_y + wave_h),
            CV_GREEN,
            2,
        )
        cv2.putText(
            base_frame,
            "ANALYZING SPEECH PATTERNS",
            (wave_x + wave_w - 265, config.assessment_y),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Horizontal line above NPU
        cv2.line(
            base_frame,
            (0, bottom_section_y),
            (config.width, bottom_section_y),
            (0, 180, 0),
            2,
        )

        # Store as BGR (OpenCV native format) to avoid per-frame conversion
        self._static_cache["base_frame_bgr"] = base_frame

        # Cache layout constants
        self._static_cache["right_col_x"] = right_col_x
        self._static_cache["bottom_section_y"] = bottom_section_y
        self._static_cache["sections_start_y"] = sections_start_y
        self._static_cache["section_height"] = section_height
        self._static_cache["silhouette_x"] = silhouette_x
        self._static_cache["silhouette_y"] = silhouette_y
        self._static_cache["silhouette_w"] = silhouette_w
        self._static_cache["silhouette_h"] = silhouette_h
        self._static_cache["wave_x"] = wave_x
        self._static_cache["wave_y"] = wave_y
        self._static_cache["wave_w"] = wave_w
        self._static_cache["wave_h"] = wave_h
        self._static_cache["padding"] = padding

        # Cache font settings
        self._static_cache["font_small"] = font_small
        self._static_cache["font_medium"] = font_medium

        # Pre-compute waveform scaling indices (avoids per-frame computation)
        scale_y = (wave_h - 4) / self.wave_height
        scale_x = (wave_w - 4) / self.wave_width
        self._static_cache["wave_y_indices"] = np.clip(
            (np.arange(wave_h - 4) / scale_y).astype(np.int32), 0, self.wave_height - 1
        )
        self._static_cache["wave_x_indices"] = np.clip(
            (np.arange(wave_w - 4) / scale_x).astype(np.int32), 0, self.wave_width - 1
        )

        # Pre-allocate waveform and NPU buffers
        self._wave_buffer = np.zeros(
            (self.wave_height, self.wave_width, 3), dtype=np.uint8
        )
        self._npu_buffer = np.zeros(
            (self.npu_height, self.npu_width, 3), dtype=np.uint8
        )

        # Pre-allocate FFT computation buffers to avoid per-frame allocations
        self._fft_bar_heights = np.zeros(self.wave_bars, dtype=np.float32)
        self._fft_silence_bars = np.full(self.wave_bars, 0.12, dtype=np.float32)
        self._fft_hanning = None  # Will be created on first use with correct size

        logger.debug("Static element cache initialized (OpenCV)")

    async def _start_audio_capture(self) -> bool:
        """Start capturing audio from the PulseAudio source.

        Supports two capture methods:
        1. Direct source capture (for testing with physical mic)
        2. Monitor-stream capture (for production - captures from app's sink-input)
        """
        if not self._audio_source and self._sink_input_index is None:
            return False

        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            # Create lock now that we're in async context
            self._audio_lock = asyncio.Lock()

            self._audio_capture = PulseAudioCapture(
                source_name=self._audio_source or "monitor-stream",
                sample_rate=16000,
                chunk_ms=50,  # 50ms chunks for responsive visualization
                sink_input_index=self._sink_input_index,  # For monitor-stream method
            )

            if await self._audio_capture.start():
                logger.info(f"Audio capture started from {self._audio_source}")
                # Set running flag BEFORE starting processing loop
                self._running = True
                # Start audio processing task
                asyncio.create_task(self._audio_processing_loop())

                # Initialize STT engine (runs on NPU)
                if self._stt_enabled:
                    asyncio.create_task(self._init_stt_engine())

                # Start NPU stats monitoring (lightweight, every 0.5s)
                asyncio.create_task(self._npu_stats_loop())

                return True
            else:
                logger.warning(
                    f"Failed to start audio capture from {self._audio_source}"
                )
                return False

        except ImportError:
            logger.warning(
                "audio_capture module not available, using simulated waveform"
            )
            return False
        except Exception as e:
            logger.warning(f"Audio capture error: {e}, using simulated waveform")
            return False

    async def _audio_processing_loop(self):
        """Process audio chunks and update the visualization buffer.

        Optimized to reduce CPU overhead:
        - FFT computed at video frame rate (12fps) not audio chunk rate
        - Audio chunks accumulated in buffer, FFT runs periodically
        """
        import numpy as np

        # Buffer to hold recent audio samples for FFT
        # Keep ~100ms of audio for frequency analysis
        buffer_samples = int(16000 * 0.1)  # 100ms at 16kHz
        audio_buffer = np.zeros(buffer_samples, dtype=np.float32)

        chunk_count = 0
        last_log_time = asyncio.get_event_loop().time()
        last_fft_time = 0.0
        fft_interval = 1.0 / 12.0  # Match video frame rate (12fps)

        logger.info("Audio processing loop started")

        while self._running and self._audio_capture and self._audio_capture.is_running:
            try:
                chunk = await self._audio_capture.read_chunk()
                if chunk is None:
                    await asyncio.sleep(0.01)
                    continue

                chunk_count += 1

                # Shift buffer and add new samples (in-place to avoid allocation)
                chunk_len = len(chunk.data)
                audio_buffer[:-chunk_len] = audio_buffer[
                    chunk_len:
                ]  # Shift left in-place
                audio_buffer[-chunk_len:] = chunk.data  # Add new samples

                # Feed STT buffer (zero-copy write into pre-allocated array)
                if self._stt_enabled and self._stt_engine:
                    chunk_len = len(chunk.data)
                    end_pos = self._stt_write_pos + chunk_len
                    if end_pos <= self._stt_buffer_size:
                        # Direct write, no copy - numpy slice assignment
                        self._stt_buffer[self._stt_write_pos : end_pos] = chunk.data
                        self._stt_write_pos = end_pos
                    elif chunk_count % 100 == 0:  # Log occasionally
                        logger.warning(
                            f"STT buffer full ({self._stt_write_pos} samples), dropping audio"
                        )

                # Compute FFT at video frame rate, not audio chunk rate
                now = asyncio.get_event_loop().time()
                if now - last_fft_time >= fft_interval:
                    fft_bars = self._compute_fft_bars(audio_buffer)
                    # Replace NaN with default values
                    if np.isnan(fft_bars).any():
                        fft_bars = np.nan_to_num(fft_bars, nan=0.1)
                    self._audio_buffer = fft_bars
                    last_fft_time = now

                # Log periodically
                if now - last_log_time >= 5.0:
                    rms = np.sqrt(np.mean(audio_buffer**2))
                    logger.info(
                        f"Audio processing: {chunk_count} chunks, RMS={rms:.4f}, "
                        f"buffer set={self._audio_buffer is not None}"
                    )
                    last_log_time = now

            except Exception as e:
                logger.debug(f"Audio processing error: {e}")
                await asyncio.sleep(0.01)

    async def _init_stt_engine(self):
        """Initialize the Speech-to-Text engine on NPU."""
        try:
            from tool_modules.aa_meet_bot.src.stt_engine import NPUWhisperSTT

            self._stt_text_lock = asyncio.Lock()
            self._stt_engine = NPUWhisperSTT(device="NPU")

            if await self._stt_engine.initialize():
                logger.info(
                    f"STT engine initialized on {self._stt_engine._actual_device}"
                )
                # Start STT processing loop
                asyncio.create_task(self._stt_processing_loop())
            else:
                logger.warning(
                    "STT engine failed to initialize, transcription disabled"
                )
                self._stt_enabled = False

        except ImportError as e:
            logger.warning(f"STT engine not available: {e}")
            self._stt_enabled = False
        except Exception as e:
            logger.warning(f"STT initialization error: {e}")
            self._stt_enabled = False

    async def _stt_processing_loop(self):
        """Process audio for speech-to-text transcription.

        This loop processes audio from the shared STT buffer that is fed
        by the audio processing loop.
        """
        import time

        logger.info("STT processing loop started")
        last_transcription = time.time()

        while self._running:
            try:
                # Check if we have enough audio in the STT buffer
                if self._stt_write_pos < 1600:  # Less than 100ms
                    await asyncio.sleep(0.05)
                    continue

                # Calculate buffer duration
                buffer_duration = self._stt_write_pos / 16000

                # Check for silence at the end (last 1600 samples = 100ms) - NO COPY, just a view
                check_start = max(0, self._stt_write_pos - 1600)
                rms = np.sqrt(
                    np.mean(self._stt_buffer[check_start : self._stt_write_pos] ** 2)
                )
                is_silence = rms < 0.01

                # Decide when to transcribe:
                # 1. After silence with at least 1s of audio
                # 2. After 5s of audio (max buffer)
                # 3. HARD CAP at 10s
                should_transcribe = False

                if buffer_duration >= 1.0 and is_silence:
                    should_transcribe = True
                elif buffer_duration >= 5.0:
                    should_transcribe = True
                elif buffer_duration >= 10.0:
                    should_transcribe = True
                    logger.warning(
                        f"STT buffer hit 10s cap ({self._stt_write_pos} samples), forcing transcribe"
                    )

                if should_transcribe and self._stt_write_pos > 0:
                    # Pass a VIEW to transcribe - NO COPY
                    # The STT engine must not hold a reference after returning
                    audio_view = self._stt_buffer[: self._stt_write_pos]
                    # Reset write position BEFORE transcribe (so new audio writes to start)
                    self._stt_write_pos = 0

                    # Transcribe using the view
                    start = time.time()
                    result = await self._stt_engine.transcribe(audio_view, 16000)
                    proc_time = time.time() - start

                    # Update real STT stats from the engine
                    if hasattr(self._stt_engine, "get_stats"):
                        self._stt_stats = self._stt_engine.get_stats()

                    if result.text and len(result.text.strip()) > 3:
                        # Filter out garbage (repeated chars, too short, single words)
                        text = result.text.strip()
                        # Skip if: too few unique chars, lots of punctuation, or single short word
                        is_garbage = (
                            len(set(text)) < 4
                            or text.count("!") > 3
                            or text.lower()
                            in (
                                "you",
                                "the",
                                "a",
                                "i",
                                "to",
                                "and",
                                "is",
                                "it",
                                "thank you.",
                                "thank you",
                            )
                        )
                        if not is_garbage:
                            async with self._stt_text_lock:
                                self._stt_text = text
                                # Add to history (most recent first)
                                self._stt_history.insert(0, text)
                                # Trim history to max size
                                if len(self._stt_history) > self._stt_history_max:
                                    self._stt_history = self._stt_history[
                                        : self._stt_history_max
                                    ]
                            logger.info(f"STT [{proc_time:.2f}s]: {text}")
                            last_transcription = time.time()

                # Clear old text after 5 seconds of no new transcription
                if time.time() - last_transcription > 5.0 and self._stt_text:
                    async with self._stt_text_lock:
                        self._stt_text = ""

                await asyncio.sleep(0.2)  # Check every 200ms (reduced from 100ms)

            except Exception as e:
                logger.debug(f"STT processing error: {e}")
                await asyncio.sleep(0.2)

    async def _npu_stats_loop(self):
        """Read NPU statistics from sysfs every 0.5 seconds.

        This is very lightweight - just reading small text files.
        Results are cached in self._npu_stats for use by frame rendering.
        """
        import time

        npu_path = Path("/sys/devices/pci0000:00/0000:00:0b.0")

        logger.info("NPU stats monitoring started")

        while self._running:
            try:
                now = time.time()

                # Read all stats in one batch (minimize syscalls)
                try:
                    freq = int(
                        (npu_path / "npu_current_frequency_mhz").read_text().strip()
                    )
                    max_freq = int(
                        (npu_path / "npu_max_frequency_mhz").read_text().strip()
                    )
                    busy_us = int((npu_path / "npu_busy_time_us").read_text().strip())
                    mem_bytes = int(
                        (npu_path / "npu_memory_utilization").read_text().strip()
                    )
                    power_state = (npu_path / "power_state").read_text().strip()
                    runtime_status = (
                        (npu_path / "power" / "runtime_status").read_text().strip()
                    )
                    active_ms = int(
                        (npu_path / "power" / "runtime_active_time").read_text().strip()
                    )

                    # Calculate busy delta for utilization
                    busy_delta = busy_us - self._npu_stats_prev_busy
                    self._npu_stats_prev_busy = busy_us

                    # Update cached stats
                    self._npu_stats.update(
                        {
                            "freq_mhz": freq,
                            "max_freq_mhz": max_freq,
                            "busy_us": busy_us,
                            "busy_delta_us": busy_delta,
                            "mem_bytes": mem_bytes,
                            "power_state": power_state,
                            "runtime_status": runtime_status,
                            "active_ms": active_ms,
                            "last_update": now,
                        }
                    )

                except FileNotFoundError:
                    # NPU sysfs not available, use defaults
                    pass
                except Exception as e:
                    logger.debug(f"NPU stats read error: {e}")

                await asyncio.sleep(0.5)  # Update every 500ms

            except Exception as e:
                logger.debug(f"NPU stats loop error: {e}")
                await asyncio.sleep(1.0)

    def _compute_fft_bars(self, audio: np.ndarray) -> np.ndarray:
        """Compute FFT and convert to bar heights for visualization.

        Includes noise gate: when audio RMS is below threshold, returns
        minimal bars to indicate silence/muted mic.
        """
        # Noise gate: check if audio is essentially silent
        rms = np.sqrt(np.mean(audio**2))
        noise_threshold = 0.005  # Below this RMS, consider it silence/muted

        if rms < noise_threshold:
            # Return minimal flat bars for silence (reuse pre-allocated buffer)
            np.copyto(self._fft_bar_heights, self._fft_silence_bars)
            # Add small random variation in-place
            self._fft_bar_heights += np.random.uniform(-0.02, 0.02, self.wave_bars)
            np.clip(self._fft_bar_heights, 0.1, 0.15, out=self._fft_bar_heights)
            if self._prev_fft_bars is None:
                self._prev_fft_bars = self._fft_bar_heights.copy()
            else:
                np.copyto(self._prev_fft_bars, self._fft_bar_heights)
            return self._fft_bar_heights

        # Create/reuse hanning window (only allocate once per audio size)
        if self._fft_hanning is None or len(self._fft_hanning) != len(audio):
            self._fft_hanning = np.hanning(len(audio)).astype(np.float32)

        # Apply window function to reduce spectral leakage (in-place multiply)
        windowed = audio * self._fft_hanning

        # Compute FFT
        fft = np.abs(np.fft.rfft(windowed))

        # We only care about frequencies up to ~8kHz (half of 16kHz sample rate)
        n_fft_bins = len(fft)

        # Use logarithmic frequency scaling - write directly to pre-allocated buffer
        self._fft_bar_heights.fill(0)

        for i in range(self.wave_bars):
            # Logarithmic mapping: more resolution at low frequencies
            low_freq = int(
                n_fft_bins
                * (np.exp(i / self.wave_bars * np.log(n_fft_bins)) - 1)
                / (n_fft_bins - 1)
            )
            high_freq = int(
                n_fft_bins
                * (np.exp((i + 1) / self.wave_bars * np.log(n_fft_bins)) - 1)
                / (n_fft_bins - 1)
            )
            high_freq = max(high_freq, low_freq + 1)

            # Average the FFT bins for this bar
            if high_freq <= n_fft_bins:
                self._fft_bar_heights[i] = np.mean(fft[low_freq:high_freq])

        # Normalize to 0-1 range with some headroom (in-place)
        max_val = np.max(self._fft_bar_heights)
        if max_val > 0:
            self._fft_bar_heights /= max_val

        # Scale by RMS (in-place)
        rms_scale = min(1.0, (rms / 0.02) * 3.0)
        self._fft_bar_heights *= rms_scale

        # Apply smoothing with previous frame (in-place)
        if self._prev_fft_bars is not None:
            self._fft_bar_heights *= 0.7
            self._fft_bar_heights += 0.3 * self._prev_fft_bars

        # Update prev_fft_bars
        if self._prev_fft_bars is None:
            self._prev_fft_bars = self._fft_bar_heights.copy()
        else:
            np.copyto(self._prev_fft_bars, self._fft_bar_heights)

        # Apply final scaling (in-place)
        self._fft_bar_heights *= 0.64
        self._fft_bar_heights += 0.15

        return self._fft_bar_heights

    def _generate_waveform_frame_from_audio(
        self, bar_heights: np.ndarray, out: np.ndarray = None
    ) -> np.ndarray:
        """Generate waveform frame from audio-derived bar heights.

        Args:
            bar_heights: Array of bar heights from FFT analysis
            out: Optional pre-allocated output buffer

        Returns:
            numpy array (wave_height, wave_width, 3)
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            img = np.zeros((self.wave_height, self.wave_width, 3), dtype=np.uint8)
        else:
            img = out
            img.fill(0)

        img[:, :, 1] = 18  # Green channel background

        # Convert normalized bar heights (0-1) to pixel heights
        # bar_heights are now floats 0.1-1.0, convert to pixels
        # Replace NaN/inf with default value to avoid cast warnings
        bar_heights = np.nan_to_num(bar_heights, nan=0.1, posinf=1.0, neginf=0.1)
        pixel_heights = (bar_heights * self.wave_height).astype(np.int32)
        pixel_heights = np.clip(pixel_heights, 4, self.wave_height - 2)

        x_starts = (self.wave_i_arr * self.wave_step).astype(np.int32)
        tops = ((self.wave_height - pixel_heights) // 2).astype(np.int32)
        bottoms = ((self.wave_height + pixel_heights) // 2).astype(np.int32)

        # Draw all bars
        for idx in range(self.wave_bars):
            x = int(x_starts[idx])
            x_end = min(x + self.wave_bar_width, self.wave_width)
            top = int(tops[idx])
            bottom = int(bottoms[idx])
            # Brighter green for audio-reactive mode
            img[top:bottom, x:x_end, 0] = 30
            img[top:bottom, x:x_end, 1] = 220
            img[top:bottom, x:x_end, 2] = 30

        return img

    def _generate_waveform_frame(self, t: float, out: np.ndarray = None) -> np.ndarray:
        """Generate a single waveform frame at time t using numpy (fast).

        Args:
            t: Time in seconds
            out: Optional pre-allocated output buffer (wave_height, wave_width, 3)

        Returns:
            numpy array (wave_height, wave_width, 3) in RGB format
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            img = np.zeros((self.wave_height, self.wave_width, 3), dtype=np.uint8)
        else:
            img = out
            img.fill(0)

        img[:, :, 1] = 18  # Green channel background

        # Vectorized height calculation (use cached arrays)
        i = self.wave_i_arr
        p = self.wave_phases
        s = self.wave_speeds

        heights = (
            45
            + 35 * np.sin(t * 4 * s + i * 0.12 + p)
            + 20 * np.sin(t * 7 * s + i * 0.2 + p * 1.3)
            + 12 * np.sin(t * 11 * s + i * 0.35 + p * 0.7)
            + 15 * np.sin(t * 2.5 * s + i * 0.06)
        )

        # Spike bursts
        st = (t * 3 + i * 0.1) % 4
        spike_mask = st < 0.3
        heights[spike_mask] += np.sin(st[spike_mask] / 0.3 * np.pi) * 25

        heights = np.clip(heights, 6, self.wave_height - 4).astype(np.int32)

        x_starts = (i * self.wave_step).astype(np.int32)
        tops = (self.wave_height - heights) // 2
        bottoms = (self.wave_height + heights) // 2

        # Draw all bars (loop is fast enough for 150 bars)
        for idx in range(self.wave_bars):
            x = x_starts[idx]
            x_end = min(x + self.wave_bar_width, self.wave_width)
            top = tops[idx]
            bottom = bottoms[idx]
            # Green bar (BGR format for OpenCV compatibility)
            img[top:bottom, x:x_end, 0] = 25
            img[top:bottom, x:x_end, 1] = 200
            img[top:bottom, x:x_end, 2] = 25

        return img

    def _generate_npu_frame(
        self, t: float, frame_num: int, out: np.ndarray = None
    ) -> np.ndarray:
        """Generate a single NPU panel frame using OpenCV (much faster than PIL).

        Args:
            t: Time in seconds
            frame_num: Current frame number
            out: Optional pre-allocated output buffer (npu_height, npu_width, 3)

        Returns:
            numpy array (npu_height, npu_width, 3) in BGR format
        """
        # Use pre-allocated buffer or create new one
        if out is None:
            frame = np.zeros((self.npu_height, self.npu_width, 3), dtype=np.uint8)
        else:
            frame = out
            frame.fill(0)

        frame[:, :, 1] = 17  # Dark green background

        font_small = 0.4
        thickness = 1

        # Header
        cv2.putText(
            frame,
            "[ INTEL NPU - METEOR LAKE ]",
            (15, 18),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        y = 35
        line_h = 16

        # Column 1 - NPU stats
        stats1 = [
            "FREQ: 1400 MHz",
            f"BUSY: {t*1.2+17.99:.1f}s",
            "MEM: 65.5 MB",
            f"UTIL: {40+int(30*math.sin(t*0.4))}%",
            f"TEMP: {45+int(10*math.sin(t*0.2))}C",
        ]
        for i, s in enumerate(stats1):
            cv2.putText(
                frame,
                s,
                (15, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 2 - Model info
        stats2 = [
            "MODEL: whisper-int8",
            "PRECISION: INT8",
            "INPUT: 16kHz PCM",
            "TILES: 2/2",
            "CACHE: ENABLED",
        ]
        for i, s in enumerate(stats2):
            cv2.putText(
                frame,
                s,
                (180, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 3 - Counters
        stats3 = [
            f"SAMPLES: {int(t*16000)}",
            f"INFERENCES: {int(t*18)}",
            f"TOKENS: {int(t*45)}",
            f"FRAMES: {frame_num}",
            f"TIME: {int(t) // 60:02d}:{int(t) % 60:02d}.{int((t % 1) * 100):02d}",
        ]
        for i, s in enumerate(stats3):
            cv2.putText(
                frame,
                s,
                (380, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 4 - System stats
        stats4 = [
            f"CPU: {15+int(10*math.sin(t*0.5))}%",
            f"MEM: {65+int(5*math.sin(t*0.3))} MB",
            f"QUEUE: {int((t * 3) % 5)}",
            f"LATENCY: {25+int(8*math.sin(t*2))}ms",
            "STATUS: ACTIVE",
        ]
        for i, s in enumerate(stats4):
            color = CV_CYAN if i == 4 else CV_GREEN
            cv2.putText(
                frame,
                s,
                (560, y + i * line_h),
                CV_FONT,
                font_small,
                color,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 5 - Additional telemetry
        stats5 = [
            f"RATE: {15+int(10*math.sin(t*0.5))} req/s",
            f"THROUGHPUT: {0.8+0.4*math.sin(t*0.3):.2f} TOPS",
            f"POWER: {4.2+0.8*math.sin(t*0.2):.1f}W",
            "DMA: ACTIVE",
            f"IRQ: {146 + int(t) % 10}",
        ]
        for i, s in enumerate(stats5):
            cv2.putText(
                frame,
                s,
                (740, y + i * line_h),
                CV_FONT,
                font_small,
                CV_GREEN,
                thickness,
                CV_LINE_TYPE,
            )

        # Column 6 - Far right
        stats6 = [
            "BATCH: 1",
            "STREAMS: 1",
            f"CONTEXT: {int(t * 100) % 512}",
            "BUFFER: 480ms",
            "RUNTIME: ACTIVE",
        ]
        for i, s in enumerate(stats6):
            color = CV_CYAN if i == 4 else CV_GREEN
            cv2.putText(
                frame,
                s,
                (920, y + i * line_h),
                CV_FONT,
                font_small,
                color,
                thickness,
                CV_LINE_TYPE,
            )

        # Progress bar at bottom
        padding = 15
        bar_max_width = self.npu_width - padding * 2 - 150
        bar_width = int((t % 15) / 15 * bar_max_width)
        bar_y = self.npu_height - 20

        # Outline
        cv2.rectangle(
            frame, (padding, bar_y), (padding + bar_max_width, bar_y + 12), CV_GREEN, 1
        )
        # Fill
        if bar_width > 0:
            cv2.rectangle(
                frame,
                (padding + 2, bar_y + 2),
                (padding + 2 + bar_width, bar_y + 10),
                CV_GREEN,
                -1,
            )
        # Percentage text
        cv2.putText(
            frame,
            f"PROCESSING: {int((t % 15) / 15 * 100)}%",
            (self.npu_width - padding - 130, bar_y + 10),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Return BGR array directly (caller expects BGR for OpenCV compatibility)
        return frame

    def set_video_mode(self, mode: str) -> None:
        """
        Set the video rendering mode without restarting the render loop.

        Args:
            mode: "black" for black screen, "full" for full AI overlay
        """
        if mode not in ("black", "full"):
            logger.warning(f"Invalid video mode: {mode}, ignoring")
            return

        if mode != self._video_mode:
            logger.info(f"Video mode changed: {self._video_mode} -> {mode}")
            self._video_mode = mode

    def get_video_mode(self) -> str:
        """Get the current video rendering mode."""
        return self._video_mode

    async def stream_realtime(
        self,
        attendees: list[Attendee],
        video_device: str,
        loop: bool = True,
    ) -> None:
        """
        Stream video with real-time generated overlays.

        Full GPU pipeline: OpenGL for text/shapes, OpenCL for color conversion.

        If audio_source was provided at init, the waveform will be audio-reactive.
        """
        import fcntl
        import struct

        config = self.config
        self._running = True

        logger.info(f"Starting real-time stream to {video_device} at {config.fps}fps")

        # Start audio capture if configured
        if self._audio_source:
            audio_started = await self._start_audio_capture()
            if audio_started:
                logger.info(
                    f"Audio-reactive waveform enabled from {self._audio_source}"
                )
                # Wait for audio buffer to be populated (up to 2s)
                # This ensures waveform is ready on first frame
                for i in range(200):  # 200 x 10ms = 2000ms max
                    if self._audio_buffer is not None:
                        logger.info(f"Audio buffer ready after {i * 10}ms")
                        break
                    await asyncio.sleep(0.01)
                else:
                    logger.warning("Audio buffer not ready after 2s, starting anyway")
            else:
                logger.info("Using simulated waveform (no audio capture)")

        # Reset GPU renderer to ensure clean state on each run
        if hasattr(self, "_ulc_renderer") and self._ulc_renderer is not None:
            logger.info("Resetting GPU renderer for clean state")
            self._ulc_renderer = None

        # NOTE: Removed fuser -k call that was killing the video device
        # The video daemon should already have exclusive access to the device
        # Killing processes here was causing the daemon to kill itself!

        # Open v4l2 device
        v4l2_fd = os.open(video_device, os.O_RDWR)

        # Set the video format using v4l2 ioctl
        # This is CRITICAL - v4l2loopback uses the format from the first VIDIOC_S_FMT
        VIDIOC_S_FMT = 0xC0D05605  # _IOWR('V', 5, struct v4l2_format)
        V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
        V4L2_PIX_FMT_YUYV = 0x56595559  # 'YUYV'
        V4L2_FIELD_NONE = 1

        width = config.width
        height = config.height
        bytesperline = width * 2  # YUYV = 2 bytes per pixel
        sizeimage = bytesperline * height

        # Build v4l2_format structure (208 bytes total)
        fmt = struct.pack(
            "II"  # type, padding
            + "IIIIIIII"  # width, height, pixelformat, field, bytesperline, sizeimage, colorspace, priv
            + "II"  # flags, ycbcr_enc/hsv_enc
            + "II"  # quantization, xfer_func
            + "152x",  # reserved
            V4L2_BUF_TYPE_VIDEO_OUTPUT,
            0,
            width,
            height,
            V4L2_PIX_FMT_YUYV,
            V4L2_FIELD_NONE,
            bytesperline,
            sizeimage,
            0,
            0,
            0,
            0,
            0,
            0,
        )

        try:
            fcntl.ioctl(v4l2_fd, VIDIOC_S_FMT, fmt)
            logger.info(f"Set v4l2 format: {width}x{height} YUYV")
        except OSError as e:
            logger.warning(f"Failed to set v4l2 format via ioctl: {e}")

        # Test write to verify device is ready
        test_frame = np.zeros((config.height, config.width * 2), dtype=np.uint8)
        os.write(v4l2_fd, test_frame.tobytes())
        logger.info("v4l2 output initialized")

        # Initialize WebRTC streaming if enabled
        if self._enable_webrtc:
            try:
                from .intel_streaming import IntelStreamingPipeline
                from .intel_streaming import StreamConfig as StreamingConfig

                logger.info("Starting WebRTC preview server on ws://localhost:8765")
                logger.info("Using YUYV input format (zero-copy to VA-API encoder)")
                stream_config = StreamingConfig(
                    width=config.width,
                    height=config.height,
                    framerate=config.fps,
                    bitrate=4000,
                    encoder="va",
                    codec="h264",
                    signaling_port=8765,
                    flip=False,
                    v4l2_device=None,  # We push frames via appsrc, not v4l2
                    input_format="yuyv",  # Direct YUYV input - VA-API converts in hardware
                )
                self._webrtc_pipeline = IntelStreamingPipeline(stream_config)
                self._webrtc_pipeline.start(mode="webrtc")
                logger.info("WebRTC streaming initialized")
            except Exception as e:
                logger.warning(f"Failed to start WebRTC streaming: {e}")
                self._webrtc_pipeline = None

        # Pre-create black frame for "black" mode (YUYV format)
        black_frame = np.zeros((config.height, config.width, 2), dtype=np.uint8)
        black_frame[:, :, 0] = 16  # Y (luma) - black
        black_frame[:, :, 1] = 128  # U/V (chroma) - neutral
        black_bytes = black_frame.tobytes()

        try:
            # Use dynamic attendees if available, otherwise use provided list
            current_attendees = (
                self._dynamic_attendees if self._dynamic_attendees else attendees
            )

            while self._running:
                # Check video mode - can switch without restarting loop
                if self._video_mode == "black":
                    # Black screen mode - minimal CPU, ~5fps
                    os.write(v4l2_fd, black_bytes)
                    await asyncio.sleep(0.2)  # 5fps for black screen
                    continue

                # Full video mode below

                # Check for attendee updates
                if self._attendees_updated and self._dynamic_attendees:
                    current_attendees = self._dynamic_attendees
                    self._attendees_updated = False
                    logger.info(
                        f"Attendee list updated: {len(current_attendees)} participants"
                    )

                for attendee_idx, attendee in enumerate(current_attendees):
                    if not self._running:
                        break

                    # Check if mode changed to black mid-loop
                    if self._video_mode == "black":
                        break

                    # Check for updates mid-loop
                    if self._attendees_updated and self._dynamic_attendees:
                        current_attendees = self._dynamic_attendees
                        self._attendees_updated = False
                        logger.info(
                            f"Attendee list updated mid-loop: {len(current_attendees)} participants"
                        )
                        break  # Restart loop with new attendees

                    duration = config.duration_per_person
                    logger.info(
                        f"Streaming attendee {attendee_idx + 1}/{len(current_attendees)}: {attendee.name}"
                    )

                    # Stream frames using full GPU pipeline
                    await self._stream_gpu_pipeline(
                        attendee,
                        attendee_idx,
                        len(current_attendees),
                        duration,
                        v4l2_fd,
                    )

                if not loop:
                    break
        finally:
            # Clean up
            if v4l2_fd is not None:
                os.close(v4l2_fd)

        logger.info("Real-time stream stopped")

    async def _stream_gpu_pipeline(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        duration: float,
        v4l2_fd: int,
    ) -> bool:
        """
        Stream frames using full GPU pipeline.

        Uses UltraLowCPURenderer for efficient GPU-accelerated rendering:
        - OpenGL renders text/shapes to base frame (~1x/second when content changes)
        - OpenCL applies waveform, progress bar, and YUYV conversion (every frame)
        - Target: ~13% CPU without audio, ~30% with audio+STT
        """
        config = self.config
        total_frames = int(duration * config.fps)
        frame_time = 1.0 / config.fps

        # Initialize GPU renderer if needed
        if not hasattr(self, "_ulc_renderer") or self._ulc_renderer is None:
            try:
                self._ulc_renderer = UltraLowCPURenderer(
                    config, use_intel=config.prefer_intel_gpu
                )
                logger.info(
                    f"UltraLowCPU renderer initialized: {self._ulc_renderer.device_name}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize GPU renderer: {e}")
                raise RuntimeError(
                    f"GPU renderer required but failed to initialize: {e}"
                ) from e

        # Pre-compute attendee-specific data
        attendee_data = self._precompute_attendee_data(attendee)

        # Pre-select random data for this attendee
        tools = random.sample(RESEARCH_TOOLS, config.num_tools)
        findings = random.sample(FAKE_FINDINGS, config.num_findings)
        assessment = random.choice(THREAT_ASSESSMENTS)

        start_time = asyncio.get_event_loop().time()
        last_npu_update = -1
        last_history_len = 0
        current_history = self._stt_history.copy() if self._stt_enabled else []

        # Pre-render initial base frame
        base_frame = self._create_base_frame(
            attendee,
            attendee_idx,
            total_attendees,
            tools,
            findings,
            assessment,
            attendee_data,
            t=0.0,
            frame_num=0,
            transcript_history=current_history,
        )
        self._ulc_renderer.upload_base_frame(base_frame)

        for frame_num in range(total_frames):
            if not self._running:
                return False

            t = frame_num / config.fps
            progress = frame_num / total_frames

            # Get current transcript history
            current_history = self._stt_history.copy() if self._stt_enabled else []

            # Check if we need to update base frame (every second or transcript changed)
            current_second = int(t)
            history_changed = len(current_history) != last_history_len
            need_update = current_second != last_npu_update or history_changed

            if need_update:
                last_npu_update = current_second
                last_history_len = len(current_history)
                # Delete old base_frame before creating new one to help GC
                del base_frame
                # Re-render base frame with updated content
                base_frame = self._create_base_frame(
                    attendee,
                    attendee_idx,
                    total_attendees,
                    tools,
                    findings,
                    assessment,
                    attendee_data,
                    t=t,
                    frame_num=frame_num,
                    transcript_history=current_history,
                )
                self._ulc_renderer.upload_base_frame(base_frame)
                # Force GC after frame update to prevent memory buildup
                gc.collect()

            # Get audio bars if available
            audio_bars = None
            if frame_num % 60 == 0:
                # Log memory and state every ~5 seconds
                stt_buf_samples = self._stt_write_pos
                stt_history_len = len(self._stt_history) if self._stt_history else 0
                mem_mb = get_memory_mb()
                logger.info(
                    f"MEM: {mem_mb:.0f}MB | stt_buf: {stt_buf_samples}/{self._stt_buffer_size} samples | "
                    f"stt_history: {stt_history_len} | frame: {frame_num}"
                )
                # Warn if memory is growing dangerously
                if mem_mb > MEMORY_WARNING_MB:
                    logger.warning(f"HIGH MEMORY: {mem_mb:.0f}MB - running GC...")
                    gc.collect()
                if mem_mb > MEMORY_CRITICAL_MB:
                    logger.error(f"CRITICAL MEMORY: {mem_mb:.0f}MB - forcing cleanup")
                    self._stt_write_pos = 0  # Reset STT buffer
                    # Force full GC with all generations
                    gc.collect(0)
                    gc.collect(1)
                    gc.collect(2)
                else:
                    # Periodic GC every 5 seconds
                    gc.collect()
            if self._audio_capture and self._audio_buffer is not None:
                audio_bars = self._audio_buffer  # No copy needed - GPU upload copies it
                if audio_bars.max() <= audio_bars.min():
                    audio_bars = None
                elif frame_num % 60 == 0:
                    logger.info(
                        f"Audio bars: min={audio_bars.min():.3f}, max={audio_bars.max():.3f}, "
                        f"mean={audio_bars.mean():.3f}"
                    )

            # Render frame with GPU (waveform, progress bar, YUYV conversion)
            yuyv = self._ulc_renderer.render_frame(t, progress, audio_bars)

            # Write to v4l2
            try:
                os.write(v4l2_fd, memoryview(yuyv))
            except OSError as e:
                logger.warning(f"v4l2 write error: {e}")
                return False

            # Push to WebRTC if enabled (direct YUYV - zero CPU conversion)
            if self._webrtc_pipeline and self._webrtc_pipeline.is_running:
                try:
                    # Push YUYV directly - VA-API handles YUY2→NV12→H.264 in hardware
                    self._webrtc_pipeline.push_frame_yuyv(yuyv)
                except Exception as e:
                    if frame_num % 60 == 0:  # Log every ~5 seconds at 12fps
                        logger.warning(f"WebRTC push error: {e}")

            # Pace output to real-time
            elapsed = asyncio.get_event_loop().time() - start_time
            expected = (frame_num + 1) * frame_time
            if expected > elapsed:
                await asyncio.sleep(expected - elapsed)

        return True

    def _create_base_frame(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        tools: list,
        findings: list,
        assessment: str,
        attendee_data: dict,
        t: float = 0.0,
        frame_num: int = 0,
        transcript_history: list = None,
    ) -> np.ndarray:
        """
        Create base frame using full GPU pipeline (OpenGL text + shapes).

        All text and shapes are rendered via OpenGL for smooth anti-aliased output.
        Dynamic NPU stats are included and update each second.

        Args:
            t: Time in seconds (for dynamic NPU stats and animations)
            frame_num: Current frame number
            transcript_history: List of recent transcriptions (most recent first)
        """
        transcript_history = transcript_history or []
        if not self._gpu_text_renderer:
            raise RuntimeError(
                "GPU text renderer not initialized - required for video generation"
            )

        c = self.config

        # Build list of text items: (text, x, y, color_name, size_name)
        text_items = []

        # === LEFT SIDE: Target info and tools ===
        text_items.append(
            (
                "[ AI WORKFLOW COMMAND CENTER ]",
                c.left_margin,
                c.title_y,
                "green",
                "large",
            )
        )

        # Name with animated dots (cycles through 1-3 dots) - XLARGE font (+10pt)
        dot_count = (int(t * 2) % 3) + 1  # 1, 2, 3 dots cycling
        name_with_dots = f"{attendee.name} {'.' * dot_count}"
        text_items.append((name_with_dots, c.left_margin, c.name_y, "green", "xlarge"))

        # Tools list - appear one at a time (1 per second) - MEDIUM font (+6pt)
        visible_tools = min(int(t) + 1, 8)  # Show 1 more tool each second, max 8
        for i, tool in enumerate(tools[:visible_tools]):
            y = c.tools_start_y + i * c.tools_line_height
            text_items.append((f"> {tool}", c.left_margin, y, "green", "medium"))

        # Findings
        for i, finding in enumerate(findings[:4]):
            y = c.findings_start_y + i * c.findings_line_height
            text_items.append((f"[+] {finding}", c.left_margin, y, "cyan", "normal"))

        # Assessment - REMOVED per user request
        # text_items.append((assessment, c.left_margin, c.assessment_y, "yellow", "normal"))

        # === WAVEFORM LABEL - above the waveform box, left aligned ===
        text_items.append(
            ("ANALYZING SPEECH PATTERNS", c.wave_x, c.wave_y - 15, "cyan", "medium")
        )  # +6pt

        # === LIVE TRANSCRIPTION STACK (below waveform box) ===
        # Show most recent transcriptions, newest at top
        transcript_start_y = c.wave_y + c.wave_h + 20
        transcript_line_height = 34  # +8px line height per user request
        max_chars = 90  # Max characters per line

        if transcript_history:
            for i, text in enumerate(transcript_history[:6]):  # Show up to 6 lines
                # Truncate long lines
                display_text = text[-max_chars:] if len(text) > max_chars else text
                # Fade older lines (newest is brightest)
                if i == 0:
                    color = "white"  # Most recent - bright white
                elif i == 1:
                    color = "cyan"  # Second most recent
                else:
                    color = "dark_green"  # Older - faded

                y = transcript_start_y + i * transcript_line_height
                text_items.append(
                    (f"> {display_text}", c.wave_x, y, color, "medium")
                )  # +6pt

        # === VOICE PROFILE ANALYSIS - LEFT of facial recognition (top right area) ===
        voice_x = c.voice_profile_x
        voice_y = c.voice_profile_y
        text_items.append(
            ("VOICE PROFILE ANALYSIS", voice_x, voice_y, "green", "large")
        )  # doubled size

        stats = [
            f"Voice Print ID: {attendee_data['voice_print_id']:05d}",
            "",
            f"Freq: 125-4000 Hz | Pitch: {random.randint(150, 220)} Hz",
            f"Cadence: {random.randint(120, 160)} wpm | Conf: {random.uniform(90, 99):.1f}%",
        ]
        for i, stat in enumerate(stats):
            if stat:  # Skip empty lines
                text_items.append(
                    (stat, voice_x, voice_y + 45 + i * 40, "orange", "medium")
                )  # doubled size + line height

        # === FACIAL RECOGNITION - TOP RIGHT === (+10pt bigger text)
        text_items.append(
            ("FACIAL RECOGNITION", c.face_x, c.face_y - 10, "red", "large")
        )

        # Show Slack username below the profile image
        if attendee_data and attendee_data.get("has_slack_data"):
            slack_name = attendee_data.get("slack_display_name", "")
            slack_id = attendee_data.get("slack_id", "")
            # Position below the face box
            slack_info_y = c.face_y + c.face_h + 25
            text_items.append(
                (f"@{slack_name}", c.face_x, slack_info_y, "cyan", "medium")
            )
            text_items.append(
                (f"[{slack_id}]", c.face_x, slack_info_y + 25, "dark_green", "normal")
            )

        # === RIGHT COLUMN REMOVED - no more "BUILDING CONTEXT" ===

        # === NPU STATS (all GPU-rendered for consistent quality) ===
        # LARGER FONT - moved up to give more vertical space
        npu_header_y = c.npu_y + 18
        text_items.append(
            (
                "[ INTEL NPU - METEOR LAKE ]",
                c.left_margin,
                npu_header_y,
                "cyan",
                "normal",
            )
        )

        # NPU stats layout - LARGE font for readability
        npu_stats_y = c.npu_y + 55  # More space after header
        npu_line_h = 38 if c.height >= 1080 else 28  # EVEN LARGER line height
        npu_size = "large"  # GPU text size for NPU stats - DOUBLED from normal

        # Column positions (proportional to width) - 6 columns spread across full width
        # Adjusted: col 1 +50px wider, all others shifted right
        col_x = [
            int(c.width * 0.02),  # Column 1 - FREQ/BUSY/MEM
            int(c.width * 0.17),  # Column 2 - UTIL/POWER/RUNTIME (+50px / ~0.03)
            int(c.width * 0.33),  # Column 3 - MODEL
            int(c.width * 0.53),  # Column 4 - SAMPLES/INFERENCES/FRAMES
            int(c.width * 0.69),  # Column 5 - CPU/GPU/STT
            int(c.width * 0.84),  # Column 6 - RATE/LATENCY/STATUS
        ]

        # Get real NPU stats from cached values (updated every 0.5s by background task)
        npu = self._npu_stats
        busy_sec = npu["busy_us"] / 1_000_000
        mem_mb = npu["mem_bytes"] / (1024 * 1024)
        # Calculate utilization from delta (busy_delta over 500ms = busy_delta/500000 * 100%)
        util_pct = (
            min(100, int(npu["busy_delta_us"] / 5000))
            if npu["busy_delta_us"] > 0
            else 0
        )
        runtime_status = npu["runtime_status"].upper()

        # Distribute stats across 6 columns (fewer items per column = larger text fits)
        # Column 1 - NPU core stats
        col1_stats = [
            f"FREQ: {npu['freq_mhz']}/{npu['max_freq_mhz']} MHz",
            f"BUSY: {busy_sec:.2f}s",
            f"MEM: {mem_mb:.1f} MB",
        ]
        for i, stat in enumerate(col1_stats):
            text_items.append(
                (stat, col_x[0], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 2 - NPU utilization
        col2_stats = [
            f"UTIL: {util_pct}%",
            f"POWER: {npu['power_state']}",
            f"RUNTIME: {runtime_status}",
        ]
        for i, stat in enumerate(col2_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append(
                (stat, col_x[1], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Column 3 - Model info (static but accurate)
        col3_stats = [
            "MODEL: whisper-base",
            "PRECISION: FP16",
            "INPUT: 16kHz PCM",
        ]
        for i, stat in enumerate(col3_stats):
            text_items.append(
                (stat, col_x[2], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 4 - Real inference counters from STT engine
        stt = self._stt_stats
        col4_stats = [
            f"SAMPLES: {stt['samples_processed']}",
            f"INFERENCES: {stt['inference_count']}",
            f"FRAMES: {frame_num}",
        ]
        for i, stat in enumerate(col4_stats):
            text_items.append(
                (stat, col_x[3], npu_stats_y + i * npu_line_h, "green", npu_size)
            )

        # Column 5 - Real inference performance
        rtf_display = f"{stt['avg_rtf']:.2f}" if stt["avg_rt"] > 0 else "---"
        col5_stats = [
            f"RTF: {rtf_display}",  # Real-time factor (< 1.0 = faster than real-time)
            f"DEVICE: {stt.get('device', 'NPU')[:8]}",
            f"STT: {'ON' if self._stt_enabled else 'OFF'}",
        ]
        for i, stat in enumerate(col5_stats):
            color = "cyan" if "ON" in stat or stt["avg_rt"] < 0.5 else "green"
            text_items.append(
                (stat, col_x[4], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Column 6 - Real telemetry from STT engine
        latency_display = (
            f"{stt['avg_latency_ms']:.0f}ms" if stt["avg_latency_ms"] > 0 else "---"
        )
        rate_display = (
            f"{stt['inferences_per_second']:.1f}/s"
            if stt["inferences_per_second"] > 0
            else "---"
        )
        col6_stats = [
            f"RATE: {rate_display}",
            f"LATENCY: {latency_display}",
            f"STATUS: {runtime_status}",
        ]
        for i, stat in enumerate(col6_stats):
            color = "cyan" if "ACTIVE" in stat else "green"
            text_items.append(
                (stat, col_x[5], npu_stats_y + i * npu_line_h, color, npu_size)
            )

        # Build shapes list for GPU rendering
        has_photo = attendee_data and attendee_data.get("photo_bgr") is not None

        shapes = [
            # Waveform box border
            (
                "rect",
                c.wave_x - 3,
                c.wave_y - 3,
                c.wave_w + 6,
                c.wave_h + 6,
                "dark_green",
                1,
            ),
            # NPU divider line
            ("line", 0, c.npu_y, c.width, c.npu_y, "dark_green", 1),
            # Progress bar outline
            (
                "rect",
                c.progress_margin,
                c.progress_y,
                c.width - c.progress_margin * 2,
                c.progress_h,
                "dark_green",
                1,
            ),
        ]

        # Only show face box and silhouette if NO photo available
        if not has_photo:
            # Face box outline
            shapes.append(
                ("rect", c.face_x, c.face_y, c.face_w, c.face_h, "dark_green", 1)
            )
            # Silhouette - sized to match typical photo dimensions
            center_x = c.face_x + c.face_w // 2
            # Make silhouette fit typical photo size (roughly 200x200 centered)
            silhouette_size = 180  # Typical photo is around this size
            head_radius = silhouette_size // 3  # Head is ~1/3 of total height
            center_y = c.face_y + 25 + head_radius + 10  # Below header
            body_width = head_radius  # Body width matches head
            body_top = center_y + head_radius + 15
            body_height = silhouette_size - head_radius * 2 - 25
            # Silhouette head (circle)
            shapes.append(("circle", center_x, center_y, head_radius, "green", 2))
            # Silhouette body (rectangle)
            shapes.append(
                (
                    "rect",
                    center_x - body_width,
                    body_top,
                    body_width * 2,
                    body_height,
                    "green",
                    2,
                )
            )

        # Render all text AND shapes with GPU in single pass
        frame = self._gpu_text_renderer.render_frame(text_items, shapes, (0, 0, 0))

        # Overlay profile photo in face area if available
        if has_photo:
            photo = attendee_data["photo_bgr"]
            ph, pw = photo.shape[:2]
            # Center photo in face box area
            photo_x = c.face_x + (c.face_w - pw) // 2
            photo_y = c.face_y + 25  # Below "FACIAL RECOGNITION" header
            # Ensure we don't go out of bounds
            if photo_y + ph <= c.height and photo_x + pw <= c.width:
                frame[photo_y : photo_y + ph, photo_x : photo_x + pw] = photo

        # NPU section - dark green background tint for Terminator look
        # (This is a pixel operation, keep it in numpy for now)
        npu_bg_y = c.npu_y + 1
        npu_bg_h = c.height - c.npu_y - 1
        frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1] = np.maximum(
            frame[npu_bg_y : npu_bg_y + npu_bg_h, :, 1], 17
        )  # Dark green tint

        return frame

    def _precompute_attendee_data(self, attendee: Attendee) -> dict:
        """Pre-compute attendee-specific data to avoid per-frame string operations.

        Includes real Slack data if available from the attendee object.
        Also loads and resizes the profile photo if available.
        """
        name_parts = attendee.name.split()
        first_name = name_parts[0].lower() if name_parts else "user"
        last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
        username = f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
        email_domain = "redhat.com"

        # Use real Slack data if available
        slack_id = attendee.slack_id or f"U{hash(attendee.name) % 99999999:08d}"
        slack_display_name = attendee.slack_display_name or attendee.name
        photo_path = attendee.photo_path
        email = attendee.email or f"{username}@{email_domain}"

        # Load and resize profile photo if available
        photo_bgr = None
        if photo_path and Path(photo_path).exists():
            try:
                img = cv2.imread(photo_path)
                if img is not None:
                    # Resize to fit in face box (keep aspect ratio)
                    c = self.config
                    target_size = min(c.face_w - 20, c.face_h - 40)  # Leave margin
                    h, w = img.shape[:2]
                    scale = target_size / max(h, w)
                    new_w, new_h = int(w * scale), int(h * scale)
                    photo_bgr = cv2.resize(
                        img, (new_w, new_h), interpolation=cv2.INTER_AREA
                    )
                    logger.debug(
                        f"Loaded photo for {attendee.name}: {photo_path} -> {new_w}x{new_h}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load photo {photo_path}: {e}")

        return {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "email_domain": email_domain,
            "voice_print_id": hash(attendee.name) % 99999,
            # Real Slack data
            "slack_id": slack_id,
            "slack_display_name": slack_display_name,
            "photo_path": photo_path,
            "photo_bgr": photo_bgr,  # Pre-loaded and resized photo
            "email": email,
            "has_slack_data": attendee.slack_id is not None,
            "tools": [
                (
                    f"slack://user/{slack_id}"
                    if attendee.slack_id
                    else f"slack://search?user={first_name}.{last_name}"
                ),
                f"ldap://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={email}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={email}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ],
        }

    def _generate_complete_frame_rgb(
        self,
        t: float,
        frame_num: int,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        tools: list[str],
        findings: list[str],
        assessment: str,
        duration: float,
        attendee_data: dict = None,
        frame_buffer: np.ndarray = None,
    ) -> np.ndarray:
        """
        Generate a complete video frame using OpenCV (2-3x faster than PIL).

        Returns numpy array (H, W, 3) in BGR format for direct YUYV conversion.

        Args:
            frame_buffer: Optional pre-allocated buffer. If provided, copies base
                         frame into it instead of allocating new array.
        """
        config = self.config

        # Use pre-allocated buffer or create new one
        if frame_buffer is not None:
            np.copyto(frame_buffer, self._static_cache["base_frame_bgr"])
            frame = frame_buffer
        else:
            frame = self._static_cache["base_frame_bgr"].copy()

        # Get cached layout constants
        padding = self._static_cache["padding"]
        right_col_x = self._static_cache["right_col_x"]
        bottom_section_y = self._static_cache["bottom_section_y"]
        sections_start_y = self._static_cache["sections_start_y"]
        section_height = self._static_cache["section_height"]
        silhouette_x = self._static_cache["silhouette_x"]
        silhouette_y = self._static_cache["silhouette_y"]
        silhouette_h = self._static_cache["silhouette_h"]
        wave_x = self._static_cache["wave_x"]
        wave_y = self._static_cache["wave_y"]
        wave_w = self._static_cache["wave_w"]
        wave_h = self._static_cache["wave_h"]

        # Font settings
        font_small = self._static_cache["font_small"]
        font_medium = self._static_cache["font_medium"]
        thickness = 1

        # Use pre-computed data if available
        if attendee_data:
            realistic_tools = attendee_data["tools"]
        else:
            # Fallback to computing on the fly
            name_parts = attendee.name.split()
            first_name = name_parts[0].lower() if name_parts else "user"
            last_name = name_parts[-1].lower() if len(name_parts) > 1 else first_name
            username = (
                f"{first_name[0]}{last_name}" if len(name_parts) > 1 else first_name
            )
            email_domain = "redhat.com"
            realistic_tools = [
                f"ldap://query?uid={username}",
                f"jira://search?assignee={username}",
                f"gitlab://commits?author={username}@{email_domain}",
                f"slack://history?user={first_name}.{last_name}",
                f"confluence://pages?author={attendee.name.replace(' ', '+')}",
                f"workday://profile/{username}",
                f"google://calendar?email={username}@{email_domain}",
                f"deepface://match?name={attendee.name.replace(' ', '_')}",
            ]

        # === DYNAMIC ELEMENTS (OpenCV) ===

        # Progress counter (changes per attendee)
        cv2.putText(
            frame,
            f"[{attendee_idx + 1}/{total_attendees}]",
            (config.width - 70, 22),
            CV_FONT,
            font_small,
            CV_CYAN,
            thickness,
            CV_LINE_TYPE,
        )

        # Animated dots (changes per frame)
        dots = "." * (int(t * 3) % 4)
        cv2.putText(
            frame,
            f"ANALYZING{dots}",
            (padding, 45),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Person name (changes per attendee)
        cv2.putText(
            frame,
            attendee.name,
            (padding, 70),
            CV_FONT,
            font_medium,
            CV_WHITE,
            thickness,
            CV_LINE_TYPE,
        )

        # Tools - appear over time (dynamic)
        y_pos = 100
        for j, tool in enumerate(realistic_tools[: config.num_tools]):
            tool_start = j * config.tool_display_time
            if t >= tool_start:
                cv2.putText(
                    frame,
                    f"> {tool}",
                    (padding, y_pos + j * 20),
                    CV_FONT,
                    font_small,
                    CV_GREEN,
                    thickness,
                    CV_LINE_TYPE,
                )

        # Findings - appear after tools (dynamic)
        findings_start = (
            len(realistic_tools[: config.num_tools]) * config.tool_display_time
        )
        findings_y = y_pos + config.num_tools * 20 + 15
        for j, finding in enumerate(findings):
            finding_start = findings_start + j * 1.0
            if t >= finding_start:
                cv2.putText(
                    frame,
                    finding,
                    (padding, findings_y + j * 20),
                    CV_FONT,
                    font_small,
                    CV_YELLOW,
                    thickness,
                    CV_LINE_TYPE,
                )

        # Assessment at end (dynamic)
        if t >= duration - 2:
            cv2.putText(
                frame,
                assessment,
                (padding, findings_y + len(findings) * 20 + 15),
                CV_FONT,
                font_medium,
                CV_CYAN,
                thickness,
                CV_LINE_TYPE,
            )

        # "PROCESSING..." label below silhouette
        cv2.putText(
            frame,
            "PROCESSING...",
            (silhouette_x + 45, silhouette_y + silhouette_h + 18),
            CV_FONT,
            font_small,
            CV_YELLOW,
            thickness,
            CV_LINE_TYPE,
        )

        # Right column dynamic values
        sections_data = [
            ["VEL: 42", "BLOCK: 3", "EPIC: 7"],
            ["CH: 847", "DM: ON", "KW: 12"],
            ["VEC: 4.2M", "COS: 0.85", "LAT: 12ms"],
            ["MAIL: 12K", "CAL: LIVE", "RISK: MED"],
        ]
        for i, items in enumerate(sections_data):
            sec_y = sections_start_y + i * section_height + 28
            for j, item in enumerate(items):
                cv2.putText(
                    frame,
                    item,
                    (right_col_x + 8, sec_y + j * 14),
                    CV_FONT,
                    font_small,
                    CV_GREEN,
                    thickness,
                    CV_LINE_TYPE,
                )

        # === VOICE PROFILE STATS - Below waveform (dynamic) ===
        voice_stats_y = wave_y + wave_h + 18

        audio_data = self._audio_buffer
        has_audio = audio_data is not None

        # Calculate animated stats
        freq_peak = 180 + int(60 * math.sin(t * 0.7))
        formant_f1 = 500 + int(100 * math.sin(t * 0.5))
        formant_f2 = 1500 + int(200 * math.sin(t * 0.3))
        pitch_var = 12 + int(8 * math.sin(t * 0.9))

        # Left stats column
        voice_print_id = (
            attendee_data["voice_print_id"]
            if attendee_data
            else hash(attendee.name) % 99999
        )
        cv2.putText(
            frame,
            f"VOICE PRINT ID: VP-{voice_print_id:05d}",
            (wave_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FREQ PEAK: {freq_peak}Hz",
            (wave_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FORMANT F1: {formant_f1}Hz",
            (wave_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"FORMANT F2: {formant_f2}Hz",
            (wave_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Middle stats column
        mid_x = wave_x + 200
        cv2.putText(
            frame,
            f"PITCH VAR: {pitch_var}%",
            (mid_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"MFCC VECTORS: {int(t * 12)}",
            (mid_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            "SPEAKER MODEL: BUILDING",
            (mid_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_YELLOW,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"CONFIDENCE: {min(99, int(t * 6.5))}%",
            (mid_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )

        # Right stats column
        right_stats_x = wave_x + 420
        cv2.putText(
            frame,
            f"SAMPLES: {int(t * 16000)}",
            (right_stats_x, voice_stats_y),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        cv2.putText(
            frame,
            f"SNR: {25 + int(5 * math.sin(t))}dB",
            (right_stats_x, voice_stats_y + 14),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        vad_text = "VAD: ACTIVE" if int(t * 3) % 2 == 0 else "VAD: SPEECH"
        cv2.putText(
            frame,
            vad_text,
            (right_stats_x, voice_stats_y + 28),
            CV_FONT,
            font_small,
            CV_GREEN,
            thickness,
            CV_LINE_TYPE,
        )
        profile_color = (
            (0, 255, 0) if t > 10 else CV_GREEN
        )  # Bright green when complete
        cv2.putText(
            frame,
            f"PROFILE: {min(100, int(t * 7))}%",
            (right_stats_x, voice_stats_y + 42),
            CV_FONT,
            font_small,
            profile_color,
            thickness,
            CV_LINE_TYPE,
        )

        # Generate waveform into pre-allocated buffer
        if has_audio:
            wave_arr = self._generate_waveform_frame_from_audio(
                audio_data, self._wave_buffer
            )
        else:
            wave_arr = self._generate_waveform_frame(t, self._wave_buffer)

        # Scale waveform using cv2.resize (100x faster than fancy indexing)
        target_h = wave_h - 4
        target_w = wave_w - 4
        scaled_wave = cv2.resize(
            wave_arr, (target_w, target_h), interpolation=cv2.INTER_NEAREST
        )

        # Paste waveform
        frame[
            wave_y + 2 : wave_y + 2 + target_h, wave_x + 2 : wave_x + 2 + target_w
        ] = scaled_wave

        # Generate NPU panel into pre-allocated buffer
        npu_arr = self._generate_npu_frame(t, frame_num, self._npu_buffer)

        # Paste NPU panel at bottom
        npu_y = bottom_section_y
        available_height = config.height - npu_y
        paste_height = min(self.npu_height, available_height)
        frame[npu_y : npu_y + paste_height, 0 : self.npu_width] = npu_arr[:paste_height]

        # Return numpy array for direct YUYV conversion
        return frame

    def _build_base_filters(
        self,
        attendee: Attendee,
        attendee_idx: int,
        total_attendees: int,
        duration: float,
    ) -> list[str]:
        """Build FFmpeg filter list for base elements (used in hybrid mode)."""
        filters = []

        # Header
        filters.append(
            "drawtext=text='[ AI RESEARCH MODULE v2.1 ]':fontsize=32:fontcolor=cyan:x=30:y=15"
        )

        return filters

    async def stop_async(self):
        """Stop the real-time stream (async version)."""
        self._running = False

        # Stop audio capture
        if self._audio_capture:
            await self._audio_capture.stop()
            self._audio_capture = None

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:
                pass
            self._webrtc_pipeline = None

        # Clean up GPU text renderer (CRITICAL: must cleanup GLFW context)
        if hasattr(self, "_gpu_text_renderer") and self._gpu_text_renderer:
            try:
                self._gpu_text_renderer.cleanup()
                logger.info("GPU text renderer cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up GPU text renderer: {e}")
            self._gpu_text_renderer = None

        # Reset state for clean restart
        self._audio_buffer = None
        if hasattr(self, "_ulc_renderer"):
            self._ulc_renderer = None

    def stop(self):
        """Stop the real-time stream."""
        self._running = False

        # Stop WebRTC streaming
        if self._webrtc_pipeline:
            try:
                self._webrtc_pipeline.stop()
            except Exception:
                pass
            self._webrtc_pipeline = None

        # Clean up GPU text renderer (CRITICAL: must cleanup GLFW context)
        if hasattr(self, "_gpu_text_renderer") and self._gpu_text_renderer:
            try:
                self._gpu_text_renderer.cleanup()
                logger.info("GPU text renderer cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up GPU text renderer: {e}")
            self._gpu_text_renderer = None

        # Reset state for clean restart
        self._audio_buffer = None
        if hasattr(self, "_ulc_renderer"):
            self._ulc_renderer = None
