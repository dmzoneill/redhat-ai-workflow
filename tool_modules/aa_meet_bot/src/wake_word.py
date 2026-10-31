"""
Wake Word Detection.

Primary: Text-based detection from captions (zero processing cost)
Fallback: Audio-based detection using openWakeWord or Porcupine
"""

import importlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, ClassVar

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class WakeWordEvent:
    """Event triggered when wake word is detected."""

    timestamp: datetime
    speaker: str
    context_before: list[str]  # Recent captions before wake word
    command_text: str  # Text after wake word (the command)
    source: str  # "caption" or "audio"

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] Wake word from {self.speaker}: {self.command_text}"


@dataclass
class _CommandState:
    """State of the command currently being collected after a wake word."""

    listening: bool = False
    start_time: datetime | None = None
    speaker: str | None = None
    buffer: list[str] = field(default_factory=list)
    last_processed_text: str = ""


class TextWakeWordDetector:
    """
    Detects wake word "David" from caption text.

    This is the primary detection method - uses Google Meet's built-in
    speech-to-text via captions, so zero local processing required.
    """

    def __init__(self, wake_word: str = "david"):
        self.wake_word = wake_word.lower()
        # Match wake word at word boundaries, case-insensitive
        self.pattern = re.compile(rf"\b{re.escape(self.wake_word)}\b", re.IGNORECASE)

        # Context buffer for recent captions
        # (speaker, text, time)
        self.context_buffer: list[tuple[str, str, datetime]] = []

        # Command collection state
        self._command = _CommandState()

        # Callback
        self._callback: Callable[[WakeWordEvent], None] | None = None

    max_context_entries: ClassVar[int] = 10
    pause_threshold: ClassVar[timedelta] = timedelta(seconds=1.0)  # Reduced from 2s for faster response
    command_timeout: ClassVar[timedelta] = timedelta(seconds=8)  # Max time to wait for command

    @property
    def listening_for_command(self) -> bool:
        """True while collecting command text after a wake word."""
        return self._command.listening

    @listening_for_command.setter
    def listening_for_command(self, value: bool) -> None:
        self._command.listening = value

    @property
    def command_start_time(self) -> datetime | None:
        """When the current command started."""
        return self._command.start_time

    @command_start_time.setter
    def command_start_time(self, value: datetime | None) -> None:
        self._command.start_time = value

    @property
    def command_speaker(self) -> str | None:
        """Speaker of the current command."""
        return self._command.speaker

    @command_speaker.setter
    def command_speaker(self, value: str | None) -> None:
        self._command.speaker = value

    @property
    def command_buffer(self) -> list[str]:
        """Text collected for the current command."""
        return self._command.buffer

    @command_buffer.setter
    def command_buffer(self, value: list[str]) -> None:
        self._command.buffer = value

    def set_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word events."""
        self._callback = callback

    def _update_command_buffer(self, text: str) -> None:
        """Update the command buffer from a (possibly revised) caption while listening."""
        last = self._command.last_processed_text
        if text == last:
            return
        if text.startswith(last):
            # Extract any NEW text beyond what we've seen
            new_text = text[len(last) :].strip()
            if new_text:
                self.command_buffer.append(new_text)
                logger.debug("Added to command buffer: %s...", new_text[:30])
        else:
            # Text changed significantly - might be a correction; take text after the wake word
            match = self.pattern.search(text)
            if match:
                command_text = text[match.end() :].strip()
                self._command.buffer = [command_text] if command_text else []
                logger.debug("Command buffer updated: %s...", command_text[:30] if command_text else "empty")
        self._command.last_processed_text = text

    def process_caption(self, speaker: str, text: str) -> WakeWordEvent | None:
        """
        Process a caption entry and check for wake word.

        Args:
            speaker: Name of the speaker
            text: Caption text

        Returns:
            WakeWordEvent if a complete command is detected, None otherwise.
        """
        now = datetime.now().astimezone()

        # Add to context buffer
        self.context_buffer.append((speaker, text, now))
        if len(self.context_buffer) > self.max_context_entries:
            self.context_buffer.pop(0)

        # If we're already listening for a command, just update the buffer with new text
        # Don't re-trigger wake word detection on caption updates
        if self.listening_for_command:
            self._update_command_buffer(text)
            return None  # Don't re-trigger, just update buffer

        # Check for wake word (only when NOT already listening)
        # IMPORTANT: Ignore if the wake word is just the speaker's name
        # e.g., speaker "David ONeill" saying "How are you?" should NOT trigger
        # Only trigger if "David" is actually spoken as a command/address
        speaker_lower = speaker.lower()

        # Check if wake word appears in text
        match = self.pattern.search(text)
        if match:
            # Check if this is just the speaker's name appearing in the caption
            # Google Meet sometimes includes speaker name in caption text
            wake_word_in_speaker_name = self.wake_word in speaker_lower

            # If the speaker's name contains the wake word, we need to be more careful
            # Only trigger if the wake word appears BEYOND just being part of the name
            if wake_word_in_speaker_name:
                # Count occurrences - if wake word appears more times in text than in speaker name,
                # or if there's text after the wake word that's not just the rest of the name
                speaker_wake_count = speaker_lower.count(self.wake_word)
                text_wake_count = len(self.pattern.findall(text))

                if text_wake_count <= speaker_wake_count:
                    # Wake word only appears as part of the speaker's name, ignore
                    logger.debug("Ignoring wake word in speaker name: %s", speaker)
                    return None

            logger.info("Wake word detected from %s: %s", speaker, text)

            # Extract text after wake word
            command_start = text[match.end() :].strip()

            # Start listening for command - DON'T return immediately!
            # Check if we already have a complete command (ends with ? ! .)
            # This handles cases like "David, how are you?" in a single transcription
            if command_start and command_start.rstrip()[-1:] in ".?!":
                logger.info("🎯 Complete command detected immediately: %s", command_start)
                self._command.buffer = [command_start]
                self._command.speaker = speaker
                self._command.start_time = now
                return self._create_event(speaker)

            # Otherwise wait for a pause to get the complete command.
            self._command.listening = True
            self._command.start_time = now
            self._command.speaker = speaker
            self._command.buffer = [command_start] if command_start else []
            self._command.last_processed_text = text  # Track what we've seen

            logger.info(
                "🎯 Now listening for command after wake word (buffer: %s...)",
                command_start[:50] if command_start else "empty",
            )

        return None

    def check_pause(self, current_time: datetime) -> WakeWordEvent | None:
        """
        Check if there's been a pause indicating command is complete.

        Call this periodically to detect pauses.
        """
        if not self.listening_for_command or not self.command_start_time:
            return None

        # Check if enough time has passed since last caption
        if self.context_buffer:
            _, _, last_time = self.context_buffer[-1]
            if current_time - last_time > self.pause_threshold and self.command_buffer:
                return self._create_event(self.command_speaker or "Unknown")

        return None

    def _create_event(self, speaker: str) -> WakeWordEvent:
        """Create a wake word event from current state."""
        # Get context before wake word
        context = [f"{s}: {t}" for s, t, _ in self.context_buffer[: -len(self.command_buffer) - 1]]

        event = WakeWordEvent(
            timestamp=self.command_start_time or datetime.now().astimezone(),
            speaker=speaker or "Unknown",
            context_before=context[-5:],  # Last 5 context entries
            command_text=" ".join(self.command_buffer),
            source="caption",
        )

        # Reset state
        self._reset_command_state()

        # Call callback if set
        if self._callback:
            self._callback(event)

        logger.info("Command detected: %s", event.command_text)
        return event

    def _reset_command_state(self) -> None:
        """Reset command collection state."""
        self._command = _CommandState()

    def reset(self) -> None:
        """Full reset - clear all state including context buffer.

        Call this after the bot finishes responding to prevent
        old captions from re-triggering wake word detection.
        """
        self._reset_command_state()
        self.context_buffer = []
        logger.debug("Wake word detector fully reset")


class AudioWakeWordDetector:
    """
    Audio-based wake word detection using openWakeWord.

    This is the fallback method when captions aren't available or reliable.
    Runs on NPU via OpenVINO for efficiency.
    """

    def __init__(self, wake_word: str = "david"):
        self.wake_word = wake_word
        self.model: Any = None
        self._np: Any = None
        self.running = False
        self._callback: Callable[[WakeWordEvent], None] | None = None

    async def initialize(self) -> bool:
        """Initialize the wake word model."""
        try:
            # Optional dependencies, loaded lazily
            model_cls = importlib.import_module("openwakeword.model").Model
            self._np = importlib.import_module("numpy")
        except ImportError:
            logger.warning("openwakeword not installed - audio wake word detection disabled")
            return False

        try:
            # Load model - using a pre-trained model that can detect "hey" patterns
            # For custom "David" wake word, we'd need to train a custom model
            self.model = model_cls(
                wakeword_models=["hey_jarvis"],  # Closest pre-trained model
                inference_framework="onnx",  # Can be optimized for OpenVINO
            )
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            logger.error("Failed to initialize audio wake word detector: %s", e)
            return False

        logger.info("Audio wake word detector initialized")
        return True

    def set_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word events."""
        self._callback = callback

    async def process_audio(self, audio_chunk: bytes) -> WakeWordEvent | None:
        """
        Process an audio chunk and check for wake word.

        Args:
            audio_chunk: Raw audio bytes (16kHz, 16-bit, mono)

        Returns:
            WakeWordEvent if wake word detected, None otherwise.
        """
        if not self.model:
            return None

        try:
            audio_data = self._np.frombuffer(audio_chunk, dtype=self._np.int16)
            prediction = self.model.predict(audio_data)
        except (RuntimeError, ValueError, TypeError) as e:
            logger.debug("Audio processing error: %s", e)
            return None

        # Check if any wake word detected
        detected = next(((w, score) for w, score in prediction.items() if score > 0.5), None)  # Confidence threshold
        if detected is None:
            return None

        logger.info("Audio wake word detected: %s (score: %s)", *detected)
        event = WakeWordEvent(
            timestamp=datetime.now().astimezone(),
            speaker="Unknown",  # Can't determine from audio alone
            context_before=[],
            command_text="",  # Will be filled by STT
            source="audio",
        )
        if self._callback:
            self._callback(event)
        return event

    async def cleanup(self) -> None:
        """Clean up resources."""
        self.model = None
        self.running = False


class WakeWordManager:
    """
    Unified wake word detection manager.

    Uses text-based detection as primary (from captions or STT),
    with audio-based detection as fallback.
    """

    def __init__(self) -> None:
        config = get_config()
        self.text_detector = TextWakeWordDetector(wake_word=config.wake_word)
        self.audio_detector = AudioWakeWordDetector(wake_word=config.wake_word)
        self.use_audio_fallback = False
        self._callback: Callable[[WakeWordEvent], None] | None = None

    async def initialize(self, enable_audio_fallback: bool = False) -> bool:
        """Initialize wake word detection."""
        if enable_audio_fallback:
            self.use_audio_fallback = await self.audio_detector.initialize()

        logger.info(
            "Wake word manager initialized (audio fallback: %s)",
            self.use_audio_fallback,
        )
        return True

    def set_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word events."""
        self._callback = callback
        self.text_detector.set_callback(callback)
        if self.use_audio_fallback:
            self.audio_detector.set_callback(callback)

    def process_caption(self, speaker: str, text: str) -> WakeWordEvent | None:
        """Process a caption for wake word detection."""
        return self.text_detector.process_caption(speaker, text)

    def process_stt_result(self, text: str, speaker: str = "Meeting") -> WakeWordEvent | None:
        """
        Process an STT transcription result for wake word detection.

        This is the integration point for the voice pipeline's STT output.

        Args:
            text: Transcribed text from STT engine
            speaker: Speaker identifier (default "Meeting" for audio-based)

        Returns:
            WakeWordEvent if wake word detected, None otherwise
        """
        return self.text_detector.process_caption(speaker, text)

    async def process_audio(self, audio_chunk: bytes) -> WakeWordEvent | None:
        """Process audio for wake word detection (fallback)."""
        if self.use_audio_fallback:
            return await self.audio_detector.process_audio(audio_chunk)
        return None

    def check_pause(self) -> WakeWordEvent | None:
        """Check for command completion due to pause."""
        return self.text_detector.check_pause(datetime.now().astimezone())

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.use_audio_fallback:
            await self.audio_detector.cleanup()


async def process_stt_stream_for_wake_word(
    stt_stream,
    wake_word: str = "david",
    callback: Callable[[WakeWordEvent], None] | None = None,
) -> None:
    """
    Process an STT stream and detect wake words.

    This is a convenience function for integrating STT with wake word detection.

    Args:
        stt_stream: Async iterator of TranscriptionResult from stt_engine
        wake_word: Wake word to detect
        callback: Function to call when wake word is detected
    """
    detector = TextWakeWordDetector(wake_word=wake_word)
    if callback:
        detector.set_callback(callback)

    async for result in stt_stream:
        if result.text:
            event = detector.process_caption("Meeting", result.text)
            if event and callback:
                callback(event)
