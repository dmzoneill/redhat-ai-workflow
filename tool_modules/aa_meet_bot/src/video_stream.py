"""Realtime audio capture and the v4l2 / GPU streaming loops."""

import asyncio
import fcntl
import gc
import logging
import os
import secrets
import struct
import time
from pathlib import Path

import numpy as np

from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
from tool_modules.aa_meet_bot.src.dynamic_fields import DynamicFields
from tool_modules.aa_meet_bot.src.stt_engine import NPUWhisperSTT
from tool_modules.aa_meet_bot.src.video_color import UltraLowCPURenderer
from tool_modules.aa_meet_bot.src.video_config import Attendee
from tool_modules.aa_meet_bot.src.video_theme import (
    FAKE_FINDINGS,
    MEMORY_CRITICAL_MB,
    MEMORY_WARNING_MB,
    RESEARCH_TOOLS,
    THREAT_ASSESSMENTS,
    get_memory_mb,
)

logger = logging.getLogger(__name__)

# Non-cryptographic jitter/variety; SystemRandom avoids the predictable Mersenne Twister flagged by scanners
_RNG = secrets.SystemRandom()


class RealtimeStreamMixin(DynamicFields):  # pylint: disable=too-few-public-methods
    """Private capture and streaming helpers for RealtimeVideoRenderer.

    ``too-few-public-methods`` is disabled because every helper is private.
    """

    async def _start_audio_capture(self) -> bool:
        """Start capturing audio from the PulseAudio source.

        Supports two capture methods:
        1. Direct source capture (for testing with physical mic)
        2. Monitor-stream capture (for production - captures from app's sink-input)
        """
        if not self._audio_source and self._sink_input_index is None:
            return False

        try:
            # Create lock now that we're in async context
            self.__dict__["_audio_lock"] = asyncio.Lock()

            self.__dict__["_audio_capture"] = PulseAudioCapture(
                source_name=self._audio_source or "monitor-stream",
                sample_rate=16000,
                chunk_ms=50,  # 50ms chunks for responsive visualization
                sink_input_index=self._sink_input_index,  # For monitor-stream method
            )

            if await self._audio_capture.start():
                logger.info("Audio capture started from %s", self._audio_source)
                # Set running flag BEFORE starting processing loop
                self.__dict__["_running"] = True
                # Start audio processing task
                asyncio.create_task(self._audio_processing_loop())

                # Initialize STT engine (runs on NPU)
                if self._stt_enabled:
                    asyncio.create_task(self._init_stt_engine())

                # Start NPU stats monitoring (lightweight, every 0.5s)
                asyncio.create_task(self._npu_stats_loop())

                return True
            logger.warning("Failed to start audio capture from %s", self._audio_source)
            return False

        except ImportError:
            logger.warning("audio_capture module not available, using simulated waveform")
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Audio capture error: %s, using simulated waveform", e, exc_info=True)
            return False

    async def _audio_processing_loop(self):
        """Process audio chunks and update the visualization buffer.

        Optimized to reduce CPU overhead:
        - FFT computed at video frame rate (12fps) not audio chunk rate
        - Audio chunks accumulated in buffer, FFT runs periodically
        """

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
                audio_buffer[:-chunk_len] = audio_buffer[chunk_len:]  # Shift left in-place
                audio_buffer[-chunk_len:] = chunk.data  # Add new samples

                # Feed STT buffer (zero-copy write into pre-allocated array)
                if self._stt_enabled and self._stt_engine:
                    chunk_len = len(chunk.data)
                    end_pos = self._stt_write_pos + chunk_len
                    if end_pos <= self._stt_buffer_size:
                        # Direct write, no copy - numpy slice assignment
                        self._stt_buffer[self._stt_write_pos : end_pos] = chunk.data
                        self.__dict__["_stt_write_pos"] = end_pos
                    elif chunk_count % 100 == 0:  # Log occasionally
                        logger.warning(
                            "STT buffer full (%s samples), dropping audio",
                            self._stt_write_pos,
                        )

                # Compute FFT at video frame rate, not audio chunk rate
                now = asyncio.get_event_loop().time()
                if now - last_fft_time >= fft_interval:
                    fft_bars = self._compute_fft_bars(audio_buffer)
                    # Replace NaN with default values
                    if np.isnan(fft_bars).any():
                        fft_bars = np.nan_to_num(fft_bars, nan=0.1)
                    self.__dict__["_audio_buffer"] = fft_bars
                    last_fft_time = now

                # Log periodically
                if now - last_log_time >= 5.0:
                    rms = np.sqrt(np.mean(audio_buffer**2))
                    logger.info(
                        "Audio processing: %s chunks, RMS=%s, buffer set=%s",
                        chunk_count,
                        format(rms, ".4f"),
                        self._audio_buffer is not None,
                    )
                    last_log_time = now

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("Audio processing error: %s", e, exc_info=True)
                await asyncio.sleep(0.01)

    async def _init_stt_engine(self):
        """Initialize the Speech-to-Text engine on NPU."""
        try:
            self.__dict__["_stt_text_lock"] = asyncio.Lock()
            self.__dict__["_stt_engine"] = NPUWhisperSTT(device="NPU")

            if await self._stt_engine.initialize():
                logger.info(
                    "STT engine initialized on %s",
                    getattr(self._stt_engine, "_actual_device", "unknown"),
                )
                # Start STT processing loop
                asyncio.create_task(self._stt_processing_loop())
            else:
                logger.warning("STT engine failed to initialize, transcription disabled")
                self.__dict__["_stt_enabled"] = False

        except ImportError as e:
            logger.warning("STT engine not available: %s", e)
            self.__dict__["_stt_enabled"] = False
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("STT initialization error: %s", e, exc_info=True)
            self.__dict__["_stt_enabled"] = False

    async def _stt_processing_loop(self):
        """Process audio for speech-to-text transcription.

        This loop processes audio from the shared STT buffer that is fed
        by the audio processing loop.
        """

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
                rms = np.sqrt(np.mean(self._stt_buffer[check_start : self._stt_write_pos] ** 2))
                is_silence = rms < 0.01

                # Decide when to transcribe:
                # 1. After silence with at least 1s of audio
                # 2. After 5s of audio (max buffer)
                # 3. HARD CAP at 10s
                should_transcribe = False

                if buffer_duration >= 10.0:
                    should_transcribe = True
                    logger.warning(
                        "STT buffer hit 10s cap (%s samples), forcing transcribe",
                        self._stt_write_pos,
                    )
                elif buffer_duration >= 5.0 or (buffer_duration >= 1.0 and is_silence):
                    should_transcribe = True

                if should_transcribe and self._stt_write_pos > 0:
                    # Pass a VIEW to transcribe - NO COPY
                    # The STT engine must not hold a reference after returning
                    audio_view = self._stt_buffer[: self._stt_write_pos]
                    # Reset write position BEFORE transcribe (so new audio writes to start)
                    self.__dict__["_stt_write_pos"] = 0

                    # Transcribe using the view
                    start = time.time()
                    result = await self._stt_engine.transcribe(audio_view, 16000)
                    proc_time = time.time() - start

                    # Update real STT stats from the engine
                    if hasattr(self._stt_engine, "get_stats"):
                        self.__dict__["_stt_stats"] = self._stt_engine.get_stats()

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
                                self.__dict__["_stt_text"] = text
                                # Add to history (most recent first)
                                self._stt_history.insert(0, text)
                                # Trim history to max size
                                if len(self._stt_history) > self._stt_history_max:
                                    self.__dict__["_stt_history"] = self._stt_history[: self._stt_history_max]
                            logger.info("STT [%ss]: %s", format(proc_time, ".2f"), text)
                            last_transcription = time.time()

                # Clear old text after 5 seconds of no new transcription
                if time.time() - last_transcription > 5.0 and self._stt_text:
                    async with self._stt_text_lock:
                        self.__dict__["_stt_text"] = ""

                await asyncio.sleep(0.2)  # Check every 200ms (reduced from 100ms)

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("STT processing error: %s", e, exc_info=True)
                await asyncio.sleep(0.2)

    async def _npu_stats_loop(self):
        """Read NPU statistics from sysfs every 0.5 seconds.

        This is very lightweight - just reading small text files.
        Results are cached in self._npu_stats for use by frame rendering.
        """

        npu_path = Path("/sys/devices/pci0000:00/0000:00:0b.0")

        logger.info("NPU stats monitoring started")

        while self._running:
            try:
                now = time.time()

                # Read all stats in one batch (minimize syscalls)
                try:
                    freq = int((npu_path / "npu_current_frequency_mhz").read_text().strip())
                    max_freq = int((npu_path / "npu_max_frequency_mhz").read_text().strip())
                    busy_us = int((npu_path / "npu_busy_time_us").read_text().strip())
                    mem_bytes = int((npu_path / "npu_memory_utilization").read_text().strip())
                    power_state = (npu_path / "power_state").read_text().strip()
                    runtime_status = (npu_path / "power" / "runtime_status").read_text().strip()
                    active_ms = int((npu_path / "power" / "runtime_active_time").read_text().strip())

                    # Calculate busy delta for utilization
                    busy_delta = busy_us - self._npu_stats_prev_busy
                    self.__dict__["_npu_stats_prev_busy"] = busy_us

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
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("NPU stats read error: %s", e, exc_info=True)

                await asyncio.sleep(0.5)  # Update every 500ms

            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("NPU stats loop error: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
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

        config = self.config
        self.__dict__["_running"] = True

        logger.info("Starting real-time stream to %s at %sfps", video_device, config.fps)

        # Start audio capture if configured
        if self._audio_source:
            audio_started = await self._start_audio_capture()
            if audio_started:
                logger.info("Audio-reactive waveform enabled from %s", self._audio_source)
                # Wait for audio buffer to be populated (up to 2s)
                # This ensures waveform is ready on first frame
                for i in range(200):  # 200 x 10ms = 2000ms max
                    if self._audio_buffer is not None:
                        logger.info("Audio buffer ready after %sms", i * 10)
                        break
                    await asyncio.sleep(0.01)
                else:
                    logger.warning("Audio buffer not ready after 2s, starting anyway")
            else:
                logger.info("Using simulated waveform (no audio capture)")

        # Reset GPU renderer to ensure clean state on each run
        if hasattr(self, "_ulc_renderer") and self._ulc_renderer is not None:
            logger.info("Resetting GPU renderer for clean state")
            self.__dict__["_ulc_renderer"] = None

        # NOTE: Removed fuser -k call that was killing the video device
        # The video daemon should already have exclusive access to the device
        # Killing processes here was causing the daemon to kill itself!

        # Open v4l2 device
        v4l2_fd = await asyncio.to_thread(os.open, video_device, os.O_RDWR)

        # Set the video format using v4l2 ioctl
        # This is CRITICAL - v4l2loopback uses the format from the first VIDIOC_S_FMT
        vidioc_s_fmt = 0xC0D05605  # _IOWR('V', 5, struct v4l2_format)
        v4l2_buf_type_video_output = 2
        v4l2_pix_fmt_yuyv = 0x56595559  # 'YUYV'
        v4l2_field_none = 1

        width = config.width
        height = config.height
        bytesperline = width * 2  # YUYV = 2 bytes per pixel
        sizeimage = bytesperline * height

        # v4l2_format: type, padding, pix fields, flags, encoding, reserved.
        fmt = struct.pack(
            "IIIIIIIIIIIIII152x",
            v4l2_buf_type_video_output,
            0,
            width,
            height,
            v4l2_pix_fmt_yuyv,
            v4l2_field_none,
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
            fcntl.ioctl(v4l2_fd, vidioc_s_fmt, fmt)
            logger.info("Set v4l2 format: %sx%s YUYV", width, height)
        except OSError as e:
            logger.warning("Failed to set v4l2 format via ioctl: %s", e)

        # Test write to verify device is ready
        test_frame = np.zeros((config.height, config.width * 2), dtype=np.uint8)
        os.write(v4l2_fd, test_frame.tobytes())
        logger.info("v4l2 output initialized")

        # Initialize WebRTC streaming if enabled
        if self._enable_webrtc:
            try:
                # isort: off
                # pylint: disable-next=import-outside-toplevel
                from .intel_streaming import (  # pylint: disable=import-outside-toplevel
                    IntelStreamingPipeline,  # pylint: disable=import-outside-toplevel
                    StreamConfig as StreamingConfig,  # pylint: disable=import-outside-toplevel
                )

                # isort: on

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
                self.__dict__["_webrtc_pipeline"] = IntelStreamingPipeline(stream_config)
                self._webrtc_pipeline.start(mode="webrtc")
                logger.info("WebRTC streaming initialized")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to start WebRTC streaming: %s", e, exc_info=True)
                self.__dict__["_webrtc_pipeline"] = None

        # Pre-create black frame for "black" mode (YUYV format)
        black_frame = np.zeros((config.height, config.width, 2), dtype=np.uint8)
        black_frame[:, :, 0] = 16  # Y (luma) - black
        black_frame[:, :, 1] = 128  # U/V (chroma) - neutral
        black_bytes = black_frame.tobytes()

        try:
            # Use dynamic attendees if available, otherwise use provided list
            current_attendees = self._dynamic_attendees if self._dynamic_attendees else attendees

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
                    self.__dict__["_attendees_updated"] = False
                    logger.info("Attendee list updated: %s participants", len(current_attendees))

                for attendee_idx, attendee in enumerate(current_attendees):
                    if not self._running:
                        break

                    # Check if mode changed to black mid-loop
                    if self._video_mode == "black":
                        break

                    # Check for updates mid-loop
                    if self._attendees_updated and self._dynamic_attendees:
                        current_attendees = self._dynamic_attendees
                        self.__dict__["_attendees_updated"] = False
                        logger.info(
                            "Attendee list updated mid-loop: %s participants",
                            len(current_attendees),
                        )
                        break  # Restart loop with new attendees

                    duration = config.duration_per_person
                    logger.info(
                        "Streaming attendee %s/%s: %s",
                        attendee_idx + 1,
                        len(current_attendees),
                        attendee.name,
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

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
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
                self.__dict__["_ulc_renderer"] = UltraLowCPURenderer(config, use_intel=config.prefer_intel_gpu)
                logger.info(
                    "UltraLowCPU renderer initialized: %s",
                    self._ulc_renderer.device_name,
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Failed to initialize GPU renderer: %s", e)
                raise RuntimeError(f"GPU renderer required but failed to initialize: {e}") from e

        # Pre-compute attendee-specific data
        attendee_data = self._precompute_attendee_data(attendee)

        # Preselect random data for this attendee
        tools = _RNG.sample(RESEARCH_TOOLS, config.num_tools)
        findings = _RNG.sample(FAKE_FINDINGS, config.num_findings)
        assessment = _RNG.choice(THREAT_ASSESSMENTS)

        start_time = asyncio.get_event_loop().time()
        last_npu_update = -1
        last_history_len = 0
        current_history = self._stt_history.copy() if self._stt_enabled else []

        # Pre-render initial base frame
        base_frame = self._create_base_frame(
            attendee=attendee,
            _attendee_idx=attendee_idx,
            _total_attendees=total_attendees,
            tools=tools,
            findings=findings,
            _assessment=assessment,
            attendee_data=attendee_data,
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
                    attendee=attendee,
                    _attendee_idx=attendee_idx,
                    _total_attendees=total_attendees,
                    tools=tools,
                    findings=findings,
                    _assessment=assessment,
                    attendee_data=attendee_data,
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
                    "MEM: %sMB | stt_buf: %s/%s samples | stt_history: %s | frame: %s",
                    format(mem_mb, ".0f"),
                    stt_buf_samples,
                    self._stt_buffer_size,
                    stt_history_len,
                    frame_num,
                )
                # Warn if memory is growing dangerously
                if mem_mb > MEMORY_WARNING_MB:
                    logger.warning("HIGH MEMORY: %sMB - running GC...", format(mem_mb, ".0f"))
                    gc.collect()
                if mem_mb > MEMORY_CRITICAL_MB:
                    logger.error("CRITICAL MEMORY: %sMB - forcing cleanup", format(mem_mb, ".0f"))
                    self.__dict__["_stt_write_pos"] = 0  # Reset STT buffer
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
                        "Audio bars: min=%s, max=%s, mean=%s",
                        format(audio_bars.min(), ".3f"),
                        format(audio_bars.max(), ".3f"),
                        format(audio_bars.mean(), ".3f"),
                    )

            # Render frame with GPU (waveform, progress bar, YUYV conversion)
            yuyv = self._ulc_renderer.render_frame(t, progress, audio_bars)

            # Write to v4l2
            try:
                os.write(v4l2_fd, memoryview(yuyv))
            except OSError as e:
                logger.warning("v4l2 write error: %s", e)
                return False

            # Push to WebRTC if enabled (direct YUYV - zero CPU conversion)
            if self._webrtc_pipeline and self._webrtc_pipeline.is_running:
                try:
                    # Push YUYV directly - VA-API handles YUY2→NV12→H.264 in hardware
                    self._webrtc_pipeline.push_frame_yuyv(yuyv)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    if frame_num % 60 == 0:  # Log every ~5 seconds at 12fps
                        logger.warning("WebRTC push error: %s", e, exc_info=True)

            # Pace output to real-time
            elapsed = asyncio.get_event_loop().time() - start_time
            expected = (frame_num + 1) * frame_time
            if expected > elapsed:
                await asyncio.sleep(expected - elapsed)

        return True
