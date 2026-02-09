"""
Speech-to-Text Engine using OpenVINO on NPU.

Provides real-time streaming transcription using Whisper on Intel NPU.
Falls back to CPU if NPU is unavailable.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Model paths
WHISPER_MODEL_DIR = Path.home() / ".cache" / "openvino" / "whisper-base-ov"


@dataclass
class TranscriptionResult:
    """Result from STT transcription."""

    text: str
    is_partial: bool = False  # True if this is a partial/streaming result
    confidence: float = 1.0
    start_time: float = 0.0  # Start time in audio stream
    end_time: float = 0.0  # End time in audio stream
    processing_time: float = 0.0  # How long transcription took


@dataclass
class StreamingConfig:
    """Configuration for streaming STT."""

    sample_rate: int = 16000
    chunk_duration: float = 0.5  # Process audio in 500ms chunks
    min_audio_length: float = 0.3  # Minimum audio to process
    max_audio_length: float = 30.0  # Maximum audio before forced processing
    silence_threshold: float = 0.01  # RMS threshold for silence detection
    silence_duration: float = 0.8  # Silence duration to trigger processing
    vad_enabled: bool = True  # Voice Activity Detection


@dataclass
class NPUStats:
    """Real-time NPU inference statistics."""

    inference_count: int = 0
    total_inference_time: float = 0.0
    total_audio_duration: float = 0.0
    last_inference_time: float = 0.0
    last_rtf: float = 0.0  # Real-time factor (< 1.0 means faster than real-time)
    avg_rtf: float = 0.0
    samples_processed: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def inferences_per_second(self) -> float:
        """Average inferences per second since start."""
        elapsed = time.time() - self.start_time
        return self.inference_count / elapsed if elapsed > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Average inference latency in milliseconds."""
        if self.inference_count == 0:
            return 0.0
        return (self.total_inference_time / self.inference_count) * 1000


class NPUWhisperSTT:
    """
    Real-time Speech-to-Text using Whisper on Intel NPU.

    Features:
    - Runs on NPU for fast inference (5-60x faster than real-time)
    - Streaming support with chunked processing
    - Voice Activity Detection (VAD) for smart segmentation
    - Automatic fallback to CPU if NPU unavailable
    - Real-time inference statistics tracking
    """

    def __init__(self, device: str = "NPU", model_dir: Optional[Path] = None):
        """
        Initialize STT engine.

        Args:
            device: "NPU" (default) or "CPU"
            model_dir: Path to OpenVINO Whisper model
        """
        self.device = device
        self.model_dir = model_dir or WHISPER_MODEL_DIR
        self._pipeline = None
        self._initialized = False
        self._actual_device = None

        # Streaming state
        self._audio_buffer: deque = deque(maxlen=int(16000 * 30))  # 30s max
        self._last_process_time = 0.0
        self._silence_start = None

        # Real inference statistics
        self.stats = NPUStats()

    async def initialize(self) -> bool:
        """Initialize the Whisper pipeline."""
        if self._initialized:
            return True

        try:
            import openvino_genai as ov_genai

            if not self.model_dir.exists():
                logger.error(f"Whisper model not found at {self.model_dir}")
                logger.info(
                    "Download with: huggingface-cli download OpenVINO/whisper-base-fp16-ov"
                )
                return False

            # Try NPU first, fall back to CPU
            for device in (
                [self.device, "CPU"] if self.device == "NPU" else [self.device]
            ):
                try:
                    logger.info(f"Loading Whisper on {device}...")
                    start = time.time()
                    self._pipeline = ov_genai.WhisperPipeline(
                        str(self.model_dir), device
                    )
                    load_time = time.time() - start
                    self._actual_device = device
                    self._initialized = True
                    logger.info(f"✅ Whisper loaded on {device} in {load_time:.2f}s")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to load on {device}: {e}")
                    if device == "NPU":
                        logger.info("Falling back to CPU...")
                        continue
                    raise

        except ImportError:
            logger.error("openvino_genai not installed. Run: uv add openvino-genai")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize STT: {e}")
            return False

        return False

    async def transcribe(
        self, audio: np.ndarray, sample_rate: int = 16000
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio: Audio samples as float32 array
            sample_rate: Sample rate (will resample to 16kHz if different)

        Returns:
            TranscriptionResult with transcribed text
        """
        if not self._initialized:
            if not await self.initialize():
                return TranscriptionResult(text="", confidence=0.0)

        try:
            # Resample if needed
            if sample_rate != 16000:
                import scipy.signal

                num_samples = int(len(audio) * 16000 / sample_rate)
                audio = scipy.signal.resample(audio, num_samples)

            # Ensure float32
            audio = audio.astype(np.float32)

            # Transcribe
            start = time.time()
            result = self._pipeline.generate(audio)
            processing_time = time.time() - start

            duration = len(audio) / 16000
            rtf = processing_time / duration if duration > 0 else 0

            # Update real statistics
            self.stats.inference_count += 1
            self.stats.total_inference_time += processing_time
            self.stats.total_audio_duration += duration
            self.stats.last_inference_time = processing_time
            self.stats.last_rtf = rtf
            self.stats.samples_processed += len(audio)
            if self.stats.total_audio_duration > 0:
                self.stats.avg_rtf = (
                    self.stats.total_inference_time / self.stats.total_audio_duration
                )

            # Extract text from WhisperDecodedResults
            # The result has a 'texts' attribute which is a list
            if hasattr(result, "texts") and result.texts:
                text = result.texts[0].strip()
            else:
                text = str(result).strip() if result else ""

            logger.debug(
                f"Transcribed {duration:.1f}s in {processing_time:.2f}s"
                f" (RTF: {rtf:.2f}) [inf #{self.stats.inference_count}]"
            )

            return TranscriptionResult(
                text=text,
                is_partial=False,
                confidence=1.0,
                end_time=duration,
                processing_time=processing_time,
            )

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return TranscriptionResult(text="", confidence=0.0)

    def _detect_silence(self, audio: np.ndarray, threshold: float = 0.01) -> bool:
        """Check if audio chunk is silence."""
        rms = np.sqrt(np.mean(audio**2))
        return rms < threshold

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[np.ndarray],
        config: Optional[StreamingConfig] = None,
        on_partial: Optional[Callable[[TranscriptionResult], None]] = None,
        on_final: Optional[Callable[[TranscriptionResult], None]] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """
        Stream transcription from an audio source.

        Processes audio in chunks and yields transcription results.
        Uses VAD to detect speech boundaries.

        Args:
            audio_stream: Async iterator yielding audio chunks
            config: Streaming configuration
            on_partial: Callback for partial results
            on_final: Callback for final results

        Yields:
            TranscriptionResult objects
        """
        if not self._initialized:
            if not await self.initialize():
                return

        config = config or StreamingConfig()
        audio_buffer = []
        total_samples = 0
        silence_samples = 0
        last_speech_time = time.time()

        async for chunk in audio_stream:
            # Add to buffer
            audio_buffer.append(chunk)
            total_samples += len(chunk)

            # Check for silence (VAD)
            if config.vad_enabled:
                is_silence = self._detect_silence(chunk, config.silence_threshold)
                if is_silence:
                    silence_samples += len(chunk)
                else:
                    silence_samples = 0
                    last_speech_time = time.time()  # noqa: F841

            buffer_duration = total_samples / config.sample_rate
            silence_duration = silence_samples / config.sample_rate

            # Decide when to process
            should_process = False
            is_final = False

            # Process if we have enough silence after speech
            if config.vad_enabled and silence_duration >= config.silence_duration:
                if buffer_duration >= config.min_audio_length:
                    should_process = True
                    is_final = True

            # Process if buffer is getting too long
            if buffer_duration >= config.max_audio_length:
                should_process = True
                is_final = True

            # Process periodically for partial results
            if buffer_duration >= config.chunk_duration * 2 and not is_final:
                should_process = True
                is_final = False

            if should_process and audio_buffer:
                # Concatenate buffer
                audio = np.concatenate(audio_buffer)

                # Transcribe
                result = await self.transcribe(audio, config.sample_rate)
                result.is_partial = not is_final
                result.start_time = 0
                result.end_time = buffer_duration

                if result.text:
                    if is_final:
                        if on_final:
                            on_final(result)
                        # Clear buffer after final result
                        audio_buffer = []
                        total_samples = 0
                        silence_samples = 0
                    else:
                        if on_partial:
                            on_partial(result)

                    yield result

    async def transcribe_file(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe an audio file."""
        try:
            import soundfile as sf

            audio, sample_rate = sf.read(str(audio_path))

            # Convert to mono if stereo
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)

            return await self.transcribe(audio, sample_rate)

        except Exception as e:
            logger.error(f"Failed to transcribe file: {e}")
            return TranscriptionResult(text="", confidence=0.0)

    def get_device_info(self) -> dict:
        """Get information about the current device."""
        return {
            "requested_device": self.device,
            "actual_device": self._actual_device,
            "initialized": self._initialized,
            "model_dir": str(self.model_dir),
        }

    def get_stats(self) -> dict:
        """Get real-time inference statistics."""
        return {
            "inference_count": self.stats.inference_count,
            "total_inference_time": self.stats.total_inference_time,
            "total_audio_duration": self.stats.total_audio_duration,
            "samples_processed": self.stats.samples_processed,
            "last_inference_ms": self.stats.last_inference_time * 1000,
            "last_rtf": self.stats.last_rtf,
            "avg_rtf": self.stats.avg_rtf,
            "avg_latency_ms": self.stats.avg_latency_ms,
            "inferences_per_second": self.stats.inferences_per_second,
            "device": self._actual_device or self.device,
        }

    def reset_stats(self):
        """Reset inference statistics."""
        self.stats = NPUStats()


class RealtimeSTT:
    """
    Real-time STT with microphone input.

    Captures audio from a PulseAudio/PipeWire source and provides
    streaming transcription.
    """

    def __init__(self, source_name: Optional[str] = None, device: str = "NPU"):
        """
        Initialize real-time STT.

        Args:
            source_name: PulseAudio source name (None for default)
            device: OpenVINO device ("NPU" or "CPU")
        """
        self.source_name = source_name
        self.stt = NPUWhisperSTT(device=device)
        self._running = False
        self._audio_queue: asyncio.Queue = None

    async def start(
        self,
        on_transcription: Callable[[TranscriptionResult], None],
        config: Optional[StreamingConfig] = None,
    ):
        """
        Start real-time transcription.

        Args:
            on_transcription: Callback for transcription results
            config: Streaming configuration
        """
        if not await self.stt.initialize():
            logger.error("Failed to initialize STT")
            return

        self._running = True
        self._audio_queue = asyncio.Queue()
        config = config or StreamingConfig()

        # Start audio capture task
        capture_task = asyncio.create_task(self._capture_audio(config))

        # Process transcriptions
        try:
            async for result in self.stt.transcribe_stream(
                self._audio_generator(),
                config=config,
            ):
                if result.text:
                    on_transcription(result)
        finally:
            self._running = False
            capture_task.cancel()

    async def _capture_audio(self, config: StreamingConfig):
        """Capture audio from PulseAudio source."""
        try:
            pass

            # Use parec to capture audio
            cmd = [
                "parec",
                "--rate",
                str(config.sample_rate),
                "--channels",
                "1",
                "--format",
                "float32le",
            ]
            if self.source_name:
                cmd.extend(["--device", self.source_name])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            chunk_size = int(
                config.sample_rate * config.chunk_duration * 4
            )  # 4 bytes per float32

            while self._running:
                data = await proc.stdout.read(chunk_size)
                if not data:
                    break

                # Convert to numpy
                audio = np.frombuffer(data, dtype=np.float32)
                await self._audio_queue.put(audio)

            proc.terminate()

        except Exception as e:
            logger.error(f"Audio capture error: {e}")

    async def _audio_generator(self) -> AsyncIterator[np.ndarray]:
        """Generate audio chunks from queue."""
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                yield chunk
            except asyncio.TimeoutError:
                continue

    def stop(self):
        """Stop real-time transcription."""
        self._running = False


# Global instance
_stt_engine: Optional[NPUWhisperSTT] = None


def get_stt_engine(device: str = "NPU") -> NPUWhisperSTT:
    """Get or create the global STT engine."""
    global _stt_engine
    if _stt_engine is None:
        _stt_engine = NPUWhisperSTT(device=device)
    return _stt_engine


async def transcribe_audio(audio: np.ndarray, sample_rate: int = 16000) -> str:
    """
    Convenience function to transcribe audio.

    Args:
        audio: Audio samples
        sample_rate: Sample rate

    Returns:
        Transcribed text
    """
    engine = get_stt_engine()
    result = await engine.transcribe(audio, sample_rate)
    return result.text


# ==================== BACKWARD COMPATIBILITY ====================
# Alias for old class name used in voice_pipeline.py
OpenVINOSTT = NPUWhisperSTT
