"""
Transcription processing for the Notes Bot.

Handles:
- Caption aggregation and update-in-place tracking
- NPU STT pipeline setup and callbacks
- Wake word detection from transcription streams
- Transcript buffer flushing to database
"""

import asyncio
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import aiosqlite

from tool_modules.aa_meet_bot.src.browser_controller import CaptionEntry
from tool_modules.aa_meet_bot.src.notes_database import MeetingNotesDB, TranscriptEntry
from tool_modules.aa_meet_bot.src.wake_word import WakeWordEvent, WakeWordManager

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.notes_bot import NotesBotState

logger = logging.getLogger(__name__)


@dataclass
class _Hooks:
    """Callbacks and references wired in by the bot after construction."""

    on_caption: Callable[[TranscriptEntry], None] | None = None
    on_wake_word: Callable[[WakeWordEvent], None] | None = None
    on_wake_word_command: Callable[[WakeWordEvent], Any] | None = None
    controller: Any = None  # GoogleMeetController reference
    actions_ref: Any = None  # InteractiveActions (for the responding flag)
    interactive_mode: bool = False


class TranscriptionProcessor:
    """Processes captions and NPU STT transcription for meeting notes.

    Manages:
    - Caption aggregation with update-in-place (by caption ID)
    - NPU-based real-time STT pipeline (local transcription)
    - Wake word detection from transcription streams
    - Transcript buffer flushing to database

    This is a component of NotesBot, composed via dependency injection.
    The bot passes its state and dependencies at construction time.
    """

    def __init__(
        self,
        state: "NotesBotState",
        db: MeetingNotesDB | None = None,
        wake_word_manager: WakeWordManager | None = None,
    ):
        self._state = state
        self._db = db
        self._wake_word_manager = wake_word_manager

        # Callbacks and references (set by the bot after construction)
        self.hooks = _Hooks()

        # NPU STT pipeline
        self._npu_stt_pipeline: Any = None

        # Wake word pause checking
        self._wake_word_check_task: asyncio.Task | None = None
        self._command_tasks: set[asyncio.Task] = set()

    @property
    def _responding(self) -> bool:
        """Check if the actions component is currently responding (bot speaking).

        This prevents processing our own TTS output as wake words.
        """
        if self.hooks.actions_ref is not None:
            return bool(self.hooks.actions_ref.responding)
        return False

    @property
    def npu_stt_pipeline(self):
        """Access the NPU STT pipeline (for cleanup by bot)."""
        return self._npu_stt_pipeline

    @npu_stt_pipeline.setter
    def npu_stt_pipeline(self, value):
        self._npu_stt_pipeline = value

    def on_caption(self, entry: CaptionEntry) -> None:
        """Handle incoming caption (new or update).

        Captions arrive from Google Meet's caption system. Each caption has:
        - A caption_id for tracking updates to the same caption
        - A speaker name
        - Text content
        - An is_update flag for fallback update detection

        We use update-in-place to avoid duplicate text when Meet refines
        a caption as the speaker continues talking.
        """
        transcript_entry = TranscriptEntry(
            speaker=entry.speaker,
            text=entry.text,
            timestamp=entry.timestamp,
        )

        cap_id = entry.caption_id

        # Check if this is an update to an existing caption (by ID)
        if cap_id and cap_id in self._state.caption_id_to_index:
            # UPDATE: Replace the entry at the tracked index
            idx = self._state.caption_id_to_index[cap_id]
            if 0 <= idx < len(self._state.transcript_buffer):
                self._state.transcript_buffer[idx] = transcript_entry
                logger.debug("Caption UPDATE (id=%s): [%s] %s...", cap_id, entry.speaker, entry.text[:50])
            else:
                # Index out of range (shouldn't happen), treat as new
                self._state.caption_id_to_index[cap_id] = len(self._state.transcript_buffer)
                self._state.transcript_buffer.append(transcript_entry)
                self._state.captions_captured += 1
                logger.debug("Caption NEW (idx invalid): [%s] %s...", entry.speaker, entry.text[:50])
        elif entry.is_update and self._state.transcript_buffer:
            # Fallback: is_update flag set but no ID tracking - replace last if same speaker
            last_entry = self._state.transcript_buffer[-1]
            if last_entry.speaker == entry.speaker:
                self._state.transcript_buffer[-1] = transcript_entry
                if cap_id:
                    # Track this ID for future updates
                    self._state.caption_id_to_index[cap_id] = len(self._state.transcript_buffer) - 1
                logger.debug("Caption UPDATE (fallback): [%s] %s...", entry.speaker, entry.text[:50])
            else:
                # Speaker changed, treat as new
                if cap_id:
                    self._state.caption_id_to_index[cap_id] = len(self._state.transcript_buffer)
                self._state.transcript_buffer.append(transcript_entry)
                self._state.captions_captured += 1
                logger.debug("Caption NEW (speaker changed): [%s] %s...", entry.speaker, entry.text[:50])
        else:
            # NEW caption
            if cap_id:
                self._state.caption_id_to_index[cap_id] = len(self._state.transcript_buffer)
            self._state.transcript_buffer.append(transcript_entry)
            self._state.captions_captured += 1
            logger.debug("Caption NEW (id=%s): [%s] %s...", cap_id, entry.speaker, entry.text[:50])

        # Update activity timestamp to show we're not hung
        if self.hooks.controller:
            self.hooks.controller.update_activity()

        # NOTE: Wake word detection is now handled by NPU STT (_on_npu_transcription)
        # Google Meet captions are only used for transcript/notes, not wake word detection
        # This avoids duplicate processing and the NPU STT is faster/more accurate

        # Call external callback if set
        on_caption = self.hooks.on_caption
        if on_caption is not None:
            on_caption(transcript_entry)

    def on_npu_transcription(self, text: str, is_final: bool) -> None:
        """Handle transcription from NPU STT.

        This is called when the NPU STT pipeline produces a transcription.
        We treat it like a caption from Google Meet.

        IMPORTANT: We ignore transcriptions while the bot is speaking to avoid
        detecting our own TTS output as wake words.
        """
        if not text.strip():
            return

        # CRITICAL: Ignore transcriptions while bot is responding
        # Otherwise we detect our own TTS output as wake words
        if self._responding:
            logger.debug("🧠 NPU (ignored - bot speaking): '%s'", text)
            return

        logger.info("🧠 NPU→WakeWord %s: '%s'", "[FINAL]" if is_final else "[partial]", text)

        # Create a transcript entry (speaker is "Meeting" since we can't identify)
        transcript_entry = TranscriptEntry(
            speaker="Meeting Audio",  # NPU STT doesn't know who's speaking
            text=text.strip(),
            timestamp=datetime.now().astimezone(),
        )

        # Add to buffer
        self._state.transcript_buffer.append(transcript_entry)
        self._state.captions_captured += 1

        # Process for wake word detection
        if self._wake_word_manager and is_final:
            # Create a mock CaptionEntry for wake word processing
            mock_caption = CaptionEntry(
                speaker="Meeting Audio",
                text=text.strip(),
                timestamp=datetime.now().astimezone(),
                is_update=False,
                caption_id=0,  # NPU STT results have no Meet caption ID
            )
            # Feed to wake word manager via the normal caption handler
            self._process_caption_for_wake_word(mock_caption)

    def _process_caption_for_wake_word(self, entry) -> None:
        """Process a caption entry for wake word detection."""
        if not self._wake_word_manager:
            logger.debug("No wake word manager - skipping wake word check")
            return

        logger.debug("🔍 Checking for wake word in: '%s' (speaker: %s)", entry.text, entry.speaker)

        event = self._wake_word_manager.process_caption(
            speaker=entry.speaker,
            text=entry.text,
        )

        if event:
            # Complete command detected - handle it immediately!
            logger.info("🔔 COMPLETE COMMAND from %s: %s", event.speaker, event.command_text)
            self._state.wake_word_triggers += 1

            self._dispatch_wake_word(event)

        elif self._wake_word_manager.text_detector.listening_for_command:
            # Wake word detected but waiting for more input - start pause checker
            if not self._wake_word_check_task or self._wake_word_check_task.done():
                logger.info("🎯 Wake word detected, starting pause checker...")
                self._wake_word_check_task = asyncio.create_task(self._check_wake_word_pause())

    def _dispatch_wake_word(self, event: WakeWordEvent) -> None:
        """Hand a complete wake-word command to the interactive handler and callback."""
        command = self.hooks.on_wake_word_command
        if self.hooks.interactive_mode and command is not None:
            # Handle immediately - don't wait for pause; keep a reference so the task isn't GC'd
            task = asyncio.create_task(command(event))
            self._command_tasks.add(task)
            task.add_done_callback(self._command_tasks.discard)
        on_wake_word = self.hooks.on_wake_word
        if on_wake_word is not None:
            on_wake_word(event)

    async def _check_wake_word_pause(self) -> None:
        """Check for pause after wake word to determine complete command."""
        if not self._wake_word_manager:
            return

        detector = self._wake_word_manager.text_detector
        logger.info("🎯 Pause checker started - waiting for speech pause...")

        # Wait for pause (check every 200ms for faster response)
        check_count = 0
        while detector.listening_for_command:
            await asyncio.sleep(0.2)  # Reduced from 500ms
            check_count += 1

            # Check if there's been a pause (uses WakeWordManager's method)
            event = self._wake_word_manager.check_pause()
            if event and event.command_text.strip():
                self._state.wake_word_triggers += 1
                logger.info("🔔 WAKE WORD + PAUSE DETECTED from %s: %s", event.speaker, event.command_text)

                # Handle wake word in interactive mode (awaited so we stay in this flow)
                command = self.hooks.on_wake_word_command
                if self.hooks.interactive_mode and command is not None:
                    logger.info("🎤 Sending to LLM: %s", event.command_text)
                    await command(event)
                on_wake_word = self.hooks.on_wake_word
                if on_wake_word is not None:
                    on_wake_word(event)

                break

            # Log progress every 2 seconds
            if check_count % 4 == 0:
                buffer_text = " ".join(detector.command_buffer) if detector.command_buffer else "(empty)"
                logger.debug("🎯 Still listening... buffer: %s...", buffer_text[:50])

            # Check for timeout (10 seconds)
            if detector.command_start_time:
                elapsed = datetime.now().astimezone() - detector.command_start_time
                if elapsed.total_seconds() > 10:
                    logger.info("Wake word command timeout - no pause detected in 10s")
                    detector.reset()
                    break

    async def setup_npu_stt(self, controller) -> None:
        """Set up NPU-based real-time STT pipeline.

        This captures audio from the meeting's virtual sink and transcribes
        it locally on the NPU, providing an alternative to Google Meet captions.

        Benefits:
        - Lower latency (local processing)
        - Works even if Meet captions are disabled
        - More accurate for technical terms (can be fine-tuned)
        - Privacy - audio never leaves the machine

        Args:
            controller: The GoogleMeetController instance
        """
        try:
            audio_capture = importlib.import_module("tool_modules.aa_meet_bot.src.audio_capture")

            if not controller:
                logger.warning("No controller - cannot set up NPU STT")
                return

            # Use _instance_id (string) and _devices (InstanceDeviceManager result)
            instance_id = getattr(controller, "_instance_id", None)
            devices = getattr(controller, "_devices", None)

            if devices and hasattr(devices, "sink_name"):
                # Use the device manager's sink monitor
                monitor_source = f"{devices.sink_name}.monitor"
                logger.info("🧠 NPU STT: Using device manager sink: %s", monitor_source)
            elif instance_id:
                # Fallback to constructed name from instance_id
                safe_id = instance_id.replace("-", "_")
                monitor_source = f"meet_bot_{safe_id}.monitor"
                logger.info("🧠 NPU STT: Using constructed sink name: %s", monitor_source)
            else:
                logger.warning("No instance_id or devices - cannot set up NPU STT")
                return

            logger.info("🧠 Setting up NPU STT pipeline from: %s", monitor_source)

            # Create the STT pipeline
            self._npu_stt_pipeline = audio_capture.RealtimeSTTPipeline(
                source_name=monitor_source,
                on_transcription=self.on_npu_transcription,
                sample_rate=16000,
                vad_threshold=0.01,
                silence_duration=0.8,
                min_speech_duration=0.3,
                max_speech_duration=15.0,
            )

            # Start the pipeline
            if await self._npu_stt_pipeline.start():
                logger.info("🧠 NPU STT pipeline started - real-time transcription active")
            else:
                logger.error("🧠 Failed to start NPU STT pipeline")
                self._npu_stt_pipeline = None

        except ImportError as e:
            logger.warning("NPU STT not available: %s", e)
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Failed to set up NPU STT: %s", e)

    async def flush_loop(self) -> None:
        """Periodically flush transcript buffer to database."""
        while self._state.status == "capturing":
            await asyncio.sleep(self._state.buffer_flush_interval)
            await self.flush_buffer()

    async def flush_buffer(self) -> None:
        """Flush transcript buffer to database."""
        if not self._db or not self._state.meeting_id:
            return

        if not self._state.transcript_buffer:
            return

        try:
            # Copy and clear buffer
            entries = self._state.transcript_buffer.copy()
            self._state.transcript_buffer = []

            # Clear caption ID tracking to prevent unbounded memory growth
            # IDs are only used for update-in-place within the buffer
            self._state.caption_id_to_index.clear()

            # Write to database
            await self._db.add_transcript_entries(self._state.meeting_id, entries)
            self._state.last_flush = datetime.now().astimezone()

            logger.debug("Flushed %s transcript entries", len(entries))

        except (aiosqlite.Error, OSError) as e:
            logger.error("Failed to flush transcript buffer: %s", e)
            # Put entries back in buffer
            self._state.transcript_buffer = entries + self._state.transcript_buffer

    async def stop_npu_stt(self, context: str = "") -> None:
        """Stop the NPU STT pipeline.

        Args:
            context: Logging context label (e.g., "LEAVE", "CLEANUP")
        """
        prefix = f"{context}: " if context else ""
        if self._npu_stt_pipeline:
            logger.info("%sStopping NPU STT pipeline...", prefix)
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
                logger.info("%sNPU STT pipeline stopped successfully", prefix)
            except asyncio.TimeoutError:
                logger.warning("%sTimeout stopping NPU STT pipeline", prefix)
            except (OSError, RuntimeError) as e:
                logger.warning("%sError stopping NPU STT: %s", prefix, e)
            finally:
                self._npu_stt_pipeline = None

    def cancel_wake_word_task(self) -> None:
        """Cancel the wake word pause checking task if running."""
        if self._wake_word_check_task and not self._wake_word_check_task.done():
            self._wake_word_check_task.cancel()
        self._wake_word_check_task = None
