"""
Real-time Audio Capture for NPU STT.

Zero-copy pipeline from PulseAudio/PipeWire sink monitor to NPU Whisper.
Uses shared memory ring buffer for minimal latency.
"""

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Shared memory for zero-copy audio transfer
SHM_SIZE = 16000 * 4 * 30  # 30 seconds of float32 audio at 16kHz


@dataclass
class AudioChunk:
    """A chunk of audio data with metadata."""

    data: np.ndarray
    timestamp: float
    sample_rate: int = 16000
    is_speech: bool = True  # VAD result


class RingBuffer:
    """
    Lock-free ring buffer for audio samples.

    Uses numpy for zero-copy slicing operations.
    """

    def __init__(self, max_seconds: float = 30.0, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.max_samples = int(max_seconds * sample_rate)
        self.buffer = np.zeros(self.max_samples, dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
        self._lock = asyncio.Lock()

    async def write(self, data: np.ndarray) -> int:
        """Write audio data to buffer. Returns samples written."""
        async with self._lock:
            n = len(data)
            if n > self.max_samples:
                # Only keep the last max_samples
                data = data[-self.max_samples :]
                n = len(data)

            # Handle wrap-around
            end_pos = self.write_pos + n
            if end_pos <= self.max_samples:
                self.buffer[self.write_pos : end_pos] = data
            else:
                # Split write
                first_part = self.max_samples - self.write_pos
                self.buffer[self.write_pos :] = data[:first_part]
                self.buffer[: n - first_part] = data[first_part:]

            self.write_pos = end_pos % self.max_samples
            return n

    async def read(self, n_samples: int) -> np.ndarray:
        """Read n samples from buffer."""
        async with self._lock:
            available = self.available()
            n = min(n_samples, available)
            if n == 0:
                return np.array([], dtype=np.float32)

            end_pos = self.read_pos + n
            if end_pos <= self.max_samples:
                data = self.buffer[self.read_pos : end_pos].copy()
            else:
                # Split read
                first_part = self.max_samples - self.read_pos
                data = np.concatenate([self.buffer[self.read_pos :], self.buffer[: n - first_part]])

            self.read_pos = end_pos % self.max_samples
            return data

    async def peek(self, n_samples: int) -> np.ndarray:
        """Peek at n samples without consuming them."""
        async with self._lock:
            available = self.available()
            n = min(n_samples, available)
            if n == 0:
                return np.array([], dtype=np.float32)

            end_pos = self.read_pos + n
            if end_pos <= self.max_samples:
                return self.buffer[self.read_pos : end_pos].copy()
            else:
                first_part = self.max_samples - self.read_pos
                return np.concatenate([self.buffer[self.read_pos :], self.buffer[: n - first_part]])

    def available(self) -> int:
        """Return number of samples available to read."""
        if self.write_pos >= self.read_pos:
            return self.write_pos - self.read_pos
        return self.max_samples - self.read_pos + self.write_pos

    async def clear(self):
        """Clear the buffer."""
        async with self._lock:
            self.read_pos = self.write_pos


class PulseAudioCapture:
    """
    Captures audio from a PulseAudio/PipeWire source.

    Supports two capture methods:
    1. Direct source capture (for testing with physical mic)
    2. Monitor-stream capture (for production - captures from app's sink-input)

    The monitor-stream method is required because PipeWire's null-sink monitors
    don't work properly (they output zeros). Instead, we capture directly from
    the application's audio stream using parec --monitor-stream=<sink_input_index>.
    """

    # Class-level tracking of all active capture processes for cleanup
    _active_captures: dict[int, "PulseAudioCapture"] = {}

    def __init__(
        self,
        source_name: str,
        sample_rate: int = 16000,
        chunk_ms: int = 100,  # 100ms chunks for low latency
        sink_input_index: Optional[int] = None,  # For monitor-stream method
    ):
        """
        Initialize audio capture.

        Args:
            source_name: PulseAudio source name (e.g., "alsa_input..." for mic)
                        For monitor-stream method, this is just for logging.
            sample_rate: Target sample rate (will resample if needed)
            chunk_ms: Chunk size in milliseconds
            sink_input_index: If provided, use parec --monitor-stream to capture
                             directly from this sink-input (bypasses broken monitors)
        """
        self.source_name = source_name
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.chunk_samples = int(sample_rate * chunk_ms / 1000)
        self.sink_input_index = sink_input_index

        self._process: Optional[asyncio.subprocess.Process] = None
        self._process_pid: Optional[int] = None  # Track PID for cleanup
        self._running = False
        self._buffer = RingBuffer(max_seconds=30.0, sample_rate=sample_rate)
        self._read_task: Optional[asyncio.Task] = None  # Track the read loop task

    async def start(self) -> bool:
        """Start audio capture."""
        if self._running:
            return True

        try:
            # Choose capture method based on whether we have a sink-input index
            if self.sink_input_index is not None:
                # Method 1: Monitor-stream (for production - captures from app stream)
                # This bypasses the broken null-sink monitor in PipeWire
                cmd = [
                    "parec",
                    f"--monitor-stream={self.sink_input_index}",
                    "--rate",
                    str(self.sample_rate),
                    "--channels",
                    "1",
                    "--format",
                    "float32le",
                    "--latency-msec",
                    str(self.chunk_ms),
                ]
                logger.info(f"Using monitor-stream capture from sink-input {self.sink_input_index}")
            else:
                # Method 2: Direct source capture (for testing with physical mic)
                # Use parec with --device for direct source capture
                # pw-record doesn't work well with stdout in some cases
                cmd = [
                    "parec",
                    "--device",
                    self.source_name,
                    "--rate",
                    str(self.sample_rate),
                    "--channels",
                    "1",
                    "--format",
                    "float32le",
                    "--latency-msec",
                    str(self.chunk_ms),
                ]
                logger.info(f"Using direct source capture from {self.source_name}")

            logger.info(f"Starting audio capture: {' '.join(cmd)}")

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Track the PID for cleanup
            self._process_pid = self._process.pid
            if self._process_pid:
                PulseAudioCapture._active_captures[self._process_pid] = self
                logger.info(f"Audio capture process started with PID {self._process_pid}")

            self._running = True

            # Start reader task (track it for cleanup)
            self._read_task = asyncio.create_task(self._read_loop())

            logger.info("Audio capture started")
            return True

        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            return False

    async def _check_command(self, cmd: str) -> bool:
        """Check if a command is available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "which",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    async def _read_loop(self):
        """Read audio data from parec and write to ring buffer."""
        bytes_per_sample = 4  # float32
        chunk_bytes = self.chunk_samples * bytes_per_sample

        try:
            while self._running and self._process:
                data = await self._process.stdout.read(chunk_bytes)
                if not data:
                    if self._running:
                        logger.warning("Audio capture ended unexpectedly")
                    break

                # Convert to numpy (zero-copy view)
                audio = np.frombuffer(data, dtype=np.float32)
                await self._buffer.write(audio)

        except Exception as e:
            logger.error(f"Audio read error: {e}")
        finally:
            self._running = False

    async def stop(self):
        """Stop audio capture and ensure process is fully terminated."""
        logger.info(f"Stopping audio capture (PID: {self._process_pid})")
        self._running = False

        # Cancel the read task first
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await asyncio.wait_for(self._read_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._read_task = None

        # Terminate the process
        if self._process:
            pid = self._process_pid
            try:
                # Try graceful termination first
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                    logger.info(f"Audio capture process {pid} terminated gracefully")
                except asyncio.TimeoutError:
                    # Force kill if terminate didn't work
                    logger.warning(f"Audio capture process {pid} didn't terminate, killing...")
                    self._process.kill()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Last resort: use os.kill directly
                        if pid:
                            try:
                                import signal

                                os.kill(pid, signal.SIGKILL)
                                logger.info(f"Sent SIGKILL to process {pid}")
                            except (ProcessLookupError, PermissionError):
                                pass  # Process already gone
            except Exception as e:
                logger.warning(f"Error stopping audio capture process: {e}")
            finally:
                self._process = None

        # Remove from active captures tracking
        if self._process_pid and self._process_pid in PulseAudioCapture._active_captures:
            del PulseAudioCapture._active_captures[self._process_pid]
            logger.info(f"Removed PID {self._process_pid} from active captures")

        self._process_pid = None

    @classmethod
    async def kill_all_captures(cls) -> int:
        """Kill all active audio capture processes. Returns count killed."""
        killed = 0
        pids_to_remove = list(cls._active_captures.keys())

        for pid in pids_to_remove:
            try:
                import signal

                os.kill(pid, signal.SIGKILL)
                logger.info(f"Force-killed orphaned audio capture PID {pid}")
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass  # Process already gone

            if pid in cls._active_captures:
                del cls._active_captures[pid]

        return killed

    @classmethod
    def get_active_pids(cls) -> list[int]:
        """Get list of active capture process PIDs."""
        return list(cls._active_captures.keys())

    async def read_chunk(self) -> Optional[AudioChunk]:
        """Read a chunk of audio."""
        if not self._running:
            return None

        # Wait for enough data with timeout
        timeout = 2.0  # 2 second timeout for audio data
        start_time = time.time()
        while self._buffer.available() < self.chunk_samples:
            if not self._running:
                return None
            if time.time() - start_time > timeout:
                # Timeout waiting for audio data - source may be gone
                logger.debug("Timeout waiting for audio chunk")
                return None
            await asyncio.sleep(0.01)

        data = await self._buffer.read(self.chunk_samples)
        return AudioChunk(
            data=data,
            timestamp=time.time(),
            sample_rate=self.sample_rate,
        )

    async def read_seconds(self, seconds: float) -> Optional[np.ndarray]:
        """Read a specific duration of audio."""
        n_samples = int(seconds * self.sample_rate)

        # Wait for enough data
        timeout = seconds + 1.0
        start = time.time()
        while self._buffer.available() < n_samples:
            if not self._running or (time.time() - start) > timeout:
                return None
            await asyncio.sleep(0.01)

        return await self._buffer.read(n_samples)

    def get_buffer(self) -> RingBuffer:
        """Get the ring buffer for direct access."""
        return self._buffer

    @property
    def is_running(self) -> bool:
        return self._running


class RealtimeSTTPipeline:
    """
    Real-time Speech-to-Text pipeline.

    Connects PulseAudio capture directly to NPU Whisper for
    streaming transcription with minimal latency.

    Architecture:
        PulseAudio Monitor → Ring Buffer → VAD → NPU Whisper → Text Callback

    Features:
    - Zero-copy audio transfer via numpy views
    - Voice Activity Detection for smart chunking
    - Streaming partial results
    - Automatic silence detection and segmentation
    """

    def __init__(
        self,
        source_name: str,
        on_transcription: Callable[[str, bool], None],
        on_partial: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
        vad_threshold: float = 0.01,
        silence_duration: float = 0.8,
        min_speech_duration: float = 0.3,
        max_speech_duration: float = 15.0,
    ):
        """
        Initialize the STT pipeline.

        Args:
            source_name: PulseAudio source to capture from
            on_transcription: Callback for final transcriptions (text, is_final)
            on_partial: Optional callback for partial results
            sample_rate: Audio sample rate
            vad_threshold: RMS threshold for voice detection
            silence_duration: Seconds of silence to trigger transcription
            min_speech_duration: Minimum speech to transcribe
            max_speech_duration: Maximum speech before forced transcription
        """
        self.source_name = source_name
        self.on_transcription = on_transcription
        self.on_partial = on_partial
        self.sample_rate = sample_rate
        self.vad_threshold = vad_threshold
        self.silence_duration = silence_duration
        self.min_speech_duration = min_speech_duration
        self.max_speech_duration = max_speech_duration

        self._capture: Optional[PulseAudioCapture] = None
        self._stt = None  # Lazy load
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Speech detection state
        self._speech_buffer: deque = deque()
        self._speech_start_time: Optional[float] = None
        self._last_speech_time: float = 0
        self._in_speech = False

    async def start(self) -> bool:
        """Start the STT pipeline."""
        if self._running:
            return True

        try:
            # Initialize STT engine
            from tool_modules.aa_meet_bot.src.stt_engine import NPUWhisperSTT

            self._stt = NPUWhisperSTT(device="NPU")
            if not await self._stt.initialize():
                logger.error("Failed to initialize NPU STT")
                return False

            logger.info(f"STT initialized on {self._stt.get_device_info()['actual_device']}")

            # Start audio capture
            self._capture = PulseAudioCapture(
                source_name=self.source_name,
                sample_rate=self.sample_rate,
                chunk_ms=100,  # 100ms chunks
            )

            if not await self._capture.start():
                logger.error("Failed to start audio capture")
                return False

            self._running = True
            self._task = asyncio.create_task(self._process_loop())

            logger.info(f"STT pipeline started: {self.source_name} → NPU")
            return True

        except Exception as e:
            logger.error(f"Failed to start STT pipeline: {e}")
            return False

    async def stop(self):
        """Stop the STT pipeline and ensure all resources are cleaned up."""
        logger.info("Stopping STT pipeline...")
        self._running = False

        # Stop capture FIRST to ensure the parec process is killed
        # This is critical - if we cancel the task first, the capture might not get stopped
        if self._capture:
            try:
                await asyncio.wait_for(self._capture.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Timeout stopping audio capture, forcing...")
                # Force kill if stop times out
                if self._capture._process_pid:
                    try:
                        import signal

                        os.kill(self._capture._process_pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            except Exception as e:
                logger.warning(f"Error stopping audio capture: {e}")
            finally:
                self._capture = None

        # Now cancel the processing task
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        logger.info("STT pipeline stopped")

    def _is_speech(self, audio: np.ndarray) -> bool:
        """Simple VAD based on RMS energy."""
        rms = np.sqrt(np.mean(audio**2))
        return rms > self.vad_threshold

    async def _process_loop(self):
        """Main processing loop."""
        chunk_count = 0
        speech_chunk_count = 0
        last_log_time = time.time()

        try:
            logger.info(f"🎧 NPU STT: Starting audio processing loop (VAD threshold: {self.vad_threshold})")

            consecutive_none_chunks = 0
            max_none_chunks = 50  # ~5 seconds of no data = audio source gone

            while self._running:
                chunk = await self._capture.read_chunk()
                if chunk is None:
                    consecutive_none_chunks += 1
                    if consecutive_none_chunks >= max_none_chunks:
                        logger.warning("🎧 NPU STT: Audio source appears to be gone (too many empty chunks)")
                        self._running = False
                        break
                    await asyncio.sleep(0.1)  # Brief wait before retry
                    continue
                consecutive_none_chunks = 0  # Reset on successful read

                chunk_count += 1
                rms = np.sqrt(np.mean(chunk.data**2))
                is_speech = rms > self.vad_threshold
                now = time.time()

                # Log audio levels periodically (every 5 seconds)
                if now - last_log_time >= 5.0:
                    logger.info(
                        f"🎧 NPU STT: Audio stats - chunks: {chunk_count}, "
                        f"speech chunks: {speech_chunk_count}, "
                        f"current RMS: {rms:.4f}, threshold: {self.vad_threshold}"
                    )
                    last_log_time = now

                if is_speech:
                    speech_chunk_count += 1
                    # Speech detected
                    if not self._in_speech:
                        # Speech started
                        self._in_speech = True
                        self._speech_start_time = now
                        self._speech_buffer.clear()
                        logger.info(f"🎧 NPU STT: 🎤 Speech STARTED (RMS: {rms:.4f})")

                    self._speech_buffer.append(chunk.data)
                    self._last_speech_time = now

                    # Check max duration
                    speech_duration = now - self._speech_start_time
                    if speech_duration >= self.max_speech_duration:
                        logger.info(f"🎧 NPU STT: Max duration reached ({speech_duration:.1f}s), transcribing...")
                        await self._transcribe_buffer(is_final=False)
                        self._speech_buffer.clear()
                        self._speech_start_time = now

                else:
                    # Silence
                    if self._in_speech:
                        self._speech_buffer.append(chunk.data)  # Include trailing silence

                        silence_time = now - self._last_speech_time
                        if silence_time >= self.silence_duration:
                            # End of speech segment
                            speech_duration = self._last_speech_time - self._speech_start_time

                            logger.info(
                                f"🎧 NPU STT: 🔇 Speech ENDED after {speech_duration:.1f}s "
                                f"(silence: {silence_time:.1f}s)"
                            )

                            if speech_duration >= self.min_speech_duration:
                                await self._transcribe_buffer(is_final=True)
                            else:
                                logger.info(
                                    f"🎧 NPU STT: Skipping short speech"
                                    f" ({speech_duration:.1f}s < {self.min_speech_duration}s)"
                                )

                            self._in_speech = False
                            self._speech_buffer.clear()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"🎧 NPU STT: Processing error: {e}")
            import traceback

            traceback.print_exc()

    async def _transcribe_buffer(self, is_final: bool = True):
        """Transcribe the current speech buffer."""
        if not self._speech_buffer:
            return

        # Concatenate all chunks
        audio = np.concatenate(list(self._speech_buffer))
        duration = len(audio) / self.sample_rate

        logger.info(f"🎧 NPU STT: 🔄 Transcribing {duration:.1f}s of audio (final={is_final})...")

        # Transcribe on NPU
        start = time.time()
        result = await self._stt.transcribe(audio, self.sample_rate)
        elapsed = time.time() - start

        if result.text:
            rtf = elapsed / duration if duration > 0 else 0
            # Log the full transcription prominently
            logger.info(f'🎧 NPU STT: ✅ [{elapsed:.2f}s, RTF:{rtf:.2f}] "{result.text}"')

            # Call callback with the transcription
            self.on_transcription(result.text, is_final)

            if not is_final and self.on_partial:
                self.on_partial(result.text)
        else:
            logger.info(f"🎧 NPU STT: ⚠️ No text from {duration:.1f}s audio")


async def create_meeting_stt_pipeline(
    instance_id: str,
    on_transcription: Callable[[str, bool], None],
) -> Optional[RealtimeSTTPipeline]:
    """
    Create an STT pipeline for a meeting instance.

    Args:
        instance_id: Meeting instance ID (used to find the audio sink)
        on_transcription: Callback for transcriptions

    Returns:
        RealtimeSTTPipeline or None if failed
    """
    # Construct the monitor source name
    safe_id = instance_id.replace("-", "_")
    monitor_source = f"meet_bot_{safe_id}.monitor"

    # Verify the source exists
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "list",
        "sources",
        "short",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if monitor_source not in stdout.decode():
        logger.error(f"Monitor source not found: {monitor_source}")
        logger.info("Available sources:")
        for line in stdout.decode().strip().split("\n"):
            logger.info(f"  {line}")
        return None

    pipeline = RealtimeSTTPipeline(
        source_name=monitor_source,
        on_transcription=on_transcription,
    )

    return pipeline


# ==================== BACKWARD COMPATIBILITY ====================
# Aliases for old class names used in voice_pipeline.py

# AudioCapture is now PulseAudioCapture
AudioCapture = PulseAudioCapture

# AudioBuffer is now RingBuffer
AudioBuffer = RingBuffer
