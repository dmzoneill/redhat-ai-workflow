"""
Audio Output to PulseAudio Pipe Source.

Writes synthesized TTS audio directly to a named pipe that PulseAudio
reads as a microphone source. This allows injecting audio into Chrome
as if it were coming from a real microphone.

Based on Xenith project approach for zero-copy audio output.

Usage:
    writer = AudioPipeWriter(pipe_path)
    writer.open()

    # Write TTS audio (numpy array)
    writer.write(audio_data, sample_rate=16000)

    writer.close()
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

logger = logging.getLogger(__name__)


class AudioPipeWriter:
    """
    Write TTS audio directly to PulseAudio pipe-source.

    The pipe-source module reads from a named pipe and presents
    the audio as a microphone source that Chrome can use.
    """

    def __init__(self, pipe_path: Path, sample_rate: int = 16000):
        """
        Initialize audio pipe writer.

        Args:
            pipe_path: Path to the named pipe (created by InstanceDeviceManager)
            sample_rate: Expected sample rate (default 16kHz for STT compatibility)
        """
        self.pipe_path = pipe_path
        self.sample_rate = sample_rate
        self._fd: Optional[int] = None
        self._is_open = False

    def open(self) -> bool:
        """
        Open the pipe for writing.

        Returns:
            True if opened successfully
        """
        if self._is_open:
            return True

        if not self.pipe_path.exists():
            logger.error(f"Pipe does not exist: {self.pipe_path}")
            return False

        try:
            # Open pipe in non-blocking mode
            # O_NONBLOCK prevents blocking if Chrome isn't reading yet
            self._fd = os.open(str(self.pipe_path), os.O_WRONLY | os.O_NONBLOCK)
            self._is_open = True
            logger.info(f"Opened audio pipe: {self.pipe_path}")
            return True
        except OSError as e:
            if e.errno == 6:  # ENXIO - no reader
                logger.warning(f"No reader on pipe (Chrome not listening?): {self.pipe_path}")
            else:
                logger.error(f"Failed to open pipe: {e}")
            return False

    def write(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bool:
        """
        Write audio directly to pipe - Chrome picks up as mic input.

        Args:
            audio_data: Float32 numpy array (normalized to [-1, 1])
            sample_rate: Sample rate of the audio

        Returns:
            True if written successfully
        """
        if not self._is_open or self._fd is None:
            if not self.open():
                return False

        try:
            # Resample if needed
            if sample_rate != self.sample_rate:
                audio_data = self._resample(audio_data, sample_rate, self.sample_rate)

            # Convert float32 to int16 PCM (what PulseAudio expects)
            # Clip to prevent overflow
            audio_data = np.clip(audio_data, -1.0, 1.0)
            pcm_int16 = (audio_data * 32767).astype(np.int16)

            # Direct write to pipe - no intermediate file!
            os.write(self._fd, pcm_int16.tobytes())
            return True

        except BlockingIOError:
            # Pipe buffer full - Chrome not reading fast enough
            logger.warning("Pipe buffer full, audio may be dropped")
            return False
        except BrokenPipeError:
            # Reader closed
            logger.warning("Pipe reader closed")
            self._is_open = False
            self._fd = None
            return False
        except Exception as e:
            logger.error(f"Failed to write to pipe: {e}")
            return False

    def _resample(
        self,
        audio: np.ndarray,
        from_rate: int,
        to_rate: int,
    ) -> np.ndarray:
        """Simple resampling using linear interpolation."""
        if from_rate == to_rate:
            return audio

        # Calculate new length
        duration = len(audio) / from_rate
        new_length = int(duration * to_rate)

        # Linear interpolation
        old_indices = np.linspace(0, len(audio) - 1, new_length)
        return np.interp(old_indices, np.arange(len(audio)), audio).astype(np.float32)

    def close(self) -> None:
        """Close the pipe."""
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception as e:
                logger.debug(f"Error closing pipe: {e}")
            finally:
                self._fd = None
                self._is_open = False
        logger.info(f"Closed audio pipe: {self.pipe_path}")

    def is_open(self) -> bool:
        """Check if pipe is open."""
        return self._is_open

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class AudioOutputManager:
    """
    Manages audio output for a meeting instance.

    Handles:
    - Opening/closing the pipe
    - Writing TTS audio with proper timing
    - Resampling if needed
    """

    def __init__(self, pipe_path: Path, target_sample_rate: int = 16000):
        """
        Initialize audio output manager.

        Args:
            pipe_path: Path to the named pipe
            target_sample_rate: Sample rate expected by PulseAudio source
        """
        self.pipe_path = pipe_path
        self.target_sample_rate = target_sample_rate
        self._writer = AudioPipeWriter(pipe_path, target_sample_rate)
        self._is_playing = False

    async def play_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int,
        real_time: bool = True,
    ) -> bool:
        """
        Play audio through the pipe.

        Args:
            audio_data: Float32 numpy array
            sample_rate: Sample rate of the audio
            real_time: If True, pace output to match audio duration

        Returns:
            True if played successfully
        """
        if self._is_playing:
            logger.warning("Already playing audio, queuing not supported yet")
            return False

        self._is_playing = True

        try:
            if not self._writer.open():
                return False

            if real_time:
                # Play in chunks to match real-time
                chunk_duration = 0.1  # 100ms chunks
                chunk_samples = int(sample_rate * chunk_duration)

                for i in range(0, len(audio_data), chunk_samples):
                    chunk = audio_data[i : i + chunk_samples]

                    start = time.time()
                    self._writer.write(chunk, sample_rate)

                    # Wait for chunk duration minus processing time
                    elapsed = time.time() - start
                    sleep_time = chunk_duration - elapsed
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
            else:
                # Write all at once (may cause buffer issues)
                self._writer.write(audio_data, sample_rate)

            return True

        finally:
            self._is_playing = False

    async def play_tts_result(self, tts_result) -> bool:
        """
        Play a TTSResult.

        Args:
            tts_result: TTSResult from tts_engine

        Returns:
            True if played successfully
        """
        if tts_result.audio_data is not None:
            # Use in-memory audio data (zero-copy path)
            return await self.play_audio(
                tts_result.audio_data,
                tts_result.sample_rate,
            )
        elif tts_result.audio_path and tts_result.audio_path.exists():
            # Load from file
            import wave

            with wave.open(str(tts_result.audio_path), "rb") as wav:
                frames = wav.readframes(wav.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)
                audio_data = audio_data.astype(np.float32) / 32768.0
                return await self.play_audio(audio_data, wav.getframerate())
        else:
            logger.error("No audio data in TTS result")
            return False

    def close(self) -> None:
        """Close the audio output."""
        self._writer.close()

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._is_playing


async def play_audio_to_meeting(
    pipe_path: Path,
    audio_data: np.ndarray,
    sample_rate: int = 16000,
) -> bool:
    """
    Convenience function to play audio to a meeting.

    Args:
        pipe_path: Path to the meeting's audio pipe
        audio_data: Float32 numpy array
        sample_rate: Sample rate of the audio

    Returns:
        True if played successfully
    """
    manager = AudioOutputManager(pipe_path)
    try:
        return await manager.play_audio(audio_data, sample_rate)
    finally:
        manager.close()
