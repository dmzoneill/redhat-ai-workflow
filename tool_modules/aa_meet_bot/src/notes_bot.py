"""
Notes Bot - Meeting note-taking mode with optional wake word detection.

A bot that:
- Joins Google Meet meetings
- Captures captions/transcription
- Saves to the meeting notes database
- Optionally detects wake words and can respond via LLM/TTS

This is the primary mode for the meeting scheduler.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from tool_modules.aa_meet_bot.src.notes_interactive import NotesInteractiveMixin
from tool_modules.aa_meet_bot.src.notes_lifecycle import NotesLifecycleMixin
from tool_modules.aa_meet_bot.src.notes_state import NotesBotState
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.browser_controller import (
    CaptionEntry,
    GoogleMeetController,
)
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.llm_responder import LLMResponder
from tool_modules.aa_meet_bot.src.notes_database import (
    MeetingNote,
    MeetingNotesDB,
    TranscriptEntry,
    init_notes_db,
)
from tool_modules.aa_meet_bot.src.wake_word import WakeWordEvent, WakeWordManager

# D-Bus client for video daemon communication
_video_dbus_available = False
try:
    from scripts.common.dbus_base import get_client as _video_dbus_client

    _video_dbus_available = _video_dbus_client is not None
except ImportError:
    pass

logger = logging.getLogger(__name__)


# Strong references to fire-and-forget tasks so they are not garbage-collected mid-run
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _spawn_background(coro: Coroutine[Any, Any, Any]) -> None:
    """Start a fire-and-forget task and keep a reference until it finishes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class NotesBot(NotesInteractiveMixin, NotesLifecycleMixin):  # pylint: disable=too-many-instance-attributes
    """
    Simple meeting note-taking bot.

    Joins meetings and captures transcripts without AI interaction.
    """

    def __init__(self, db: MeetingNotesDB | None = None):
        """
        Initialize the notes bot.

        Args:
            db: Database instance. If None, uses global instance.
        """
        self.config = get_config()
        self.db = db
        self._controller: GoogleMeetController | None = None
        self.state = NotesBotState()
        self._flush_task: asyncio.Task | None = None
        self._screenshot_task: asyncio.Task | None = None
        self._browser_monitor_task: asyncio.Task | None = None
        self._on_caption_callback: Callable[[TranscriptEntry], None] | None = None

        # Wake word detection
        self._wake_word_manager: WakeWordManager | None = None
        self._on_wake_word_callback: Callable[[WakeWordEvent], None] | None = None
        self._enable_wake_word: bool = True  # Enable by default
        self._wake_word_check_task: asyncio.Task | None = None
        self._pending_wake_event: WakeWordEvent | None = None

        # Interactive mode components
        self._llm_responder: LLMResponder | None = None
        self._interactive_mode: bool = False
        self._responding: bool = False  # Prevent overlapping responses

        # NPU STT pipeline (alternative to Google Meet captions)
        self._npu_stt_pipeline = None
        self._use_npu_stt: bool = True  # Use NPU STT by default in interactive mode

        # Video daemon integration via D-Bus
        self._video_daemon_active: bool = False
        self._participant_poll_task: asyncio.Task | None = None
        self._enable_video_integration: bool = _video_dbus_available

    async def initialize(self) -> bool:
        """Initialize the bot and database.

        Note: Browser is NOT started here - it's started lazily when joining a meeting.
        This allows the daemon to start quickly and sit idle without consuming resources.

        IMPORTANT: Runs cleanup on startup to remove any orphaned devices from previous sessions.
        """
        try:
            logger.info("=" * 60)
            logger.info("INIT: Initializing notes bot...")
            logger.info("=" * 60)

            # FIRST: Clean up any orphaned devices from previous sessions
            # This ensures we start with a clean slate
            logger.info("INIT: Running startup cleanup for orphaned devices...")
            await self._run_orphan_cleanup("INIT")

            # Initialize database
            if self.db is None:
                self.db = await init_notes_db()

            # Initialize wake word manager
            if self._enable_wake_word:
                self._wake_word_manager = WakeWordManager()
                await self._wake_word_manager.initialize()
                logger.info(
                    'Wake word detection enabled (wake word: "%s")',
                    self.config.wake_word,
                )

            # Don't initialize browser here - do it lazily when joining a meeting
            # This prevents the daemon from opening Chrome on startup
            logger.info("INIT: Notes bot initialized successfully")
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to initialize notes bot")
            self.state.errors.append(str(e))
            return False

    async def _run_orphan_cleanup(self, context: str = "") -> dict:
        """Run comprehensive orphan cleanup.

        This is called at multiple points:
        - On bot initialization (startup)
        - Before joining a meeting
        - After leaving a meeting
        - When browser window closes
        - On bot shutdown

        Args:
            context: Label for logging (e.g., "INIT", "PRE-JOIN", "POST-LEAVE")

        Returns:
            Cleanup results dict
        """
        results: dict[str, Any] = {
            "audio_captures_killed": 0,
            "modules_removed": 0,
            "processes_killed": 0,
            "pipes_removed": 0,
            "video_devices_removed": 0,
            "errors": [],
        }

        prefix = f"{context}: " if context else ""

        # 1. Kill any orphaned audio capture processes from our tracking
        try:
            # pylint: disable-next=import-outside-toplevel
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            results["audio_captures_killed"] = killed
            if killed > 0:
                logger.info("%sKilled %s tracked audio capture processes", prefix, killed)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("%sAudio capture cleanup failed: %s", prefix, e, exc_info=True)
            results["errors"].append(f"Audio capture cleanup: {e}")

        # 2. Run comprehensive orphan cleanup (modules, parec, pipes, video)
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (  # pylint: disable=import-outside-toplevel
                cleanup_orphaned_meetbot_devices,
            )

            cleanup_results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

            results["modules_removed"] = len(cleanup_results.get("removed_modules", []))
            results["processes_killed"] = len(cleanup_results.get("killed_processes", []))
            results["pipes_removed"] = len(cleanup_results.get("removed_pipes", []))
            results["video_devices_removed"] = len(cleanup_results.get("removed_video_devices", []))
            results["errors"].extend(cleanup_results.get("errors", []))

            total = (
                results["modules_removed"]
                + results["processes_killed"]
                + results["pipes_removed"]
                + results["video_devices_removed"]
            )

            if total > 0:
                logger.info(
                    "%sOrphan cleanup: %s modules, %s processes, %s pipes, %s video devices",
                    prefix,
                    results["modules_removed"],
                    results["processes_killed"],
                    results["pipes_removed"],
                    results["video_devices_removed"],
                )
            else:
                logger.info("%sOrphan cleanup: No orphaned devices found", prefix)
        # pylint: disable=broad-exception-caught
        except Exception as e:  # pylint: disable=broad-exception-caught
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning("%sError during orphan cleanup: %s", prefix, e, exc_info=True)

        return results

    async def _ensure_browser(self, video_enabled: bool = False) -> bool:
        """Ensure browser controller is initialized (lazy initialization).

        Called before joining a meeting to start the browser if needed.

        Args:
            video_enabled: If True, start full AI video overlay. If False, start black screen.
        """
        if self._controller is not None:
            return True

        try:
            self._controller = GoogleMeetController()
            if not await self._controller.initialize(video_enabled=video_enabled):
                logger.error("Failed to initialize browser controller")
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append("Browser controller initialization failed")
                self._controller = None
                return False
            return True  # pylint: disable=broad-exception-caught
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to initialize browser")
            self.state.errors.append(str(e))
            self._controller = None
            return False

    # pylint: disable=too-many-arguments,too-many-branches,too-many-positional-arguments
    # pylint: disable=too-many-statements,too-many-locals
    async def join_meeting(
        self,
        meet_url: str,
        title: str = "",
        calendar_id: str = "",
        event_id: str = "",
        description: str = "",
        organizer: str = "",
        attendees: list[str] | None = None,
        mode: str = "notes",
        use_npu_stt: bool = True,  # Enable NPU STT by default for local transcription
        video_enabled: bool = False,  # Show full AI video overlay (default: black screen)
    ) -> bool:
        """
        Join a meeting and start capturing notes.

        Args:
            meet_url: Google Meet URL
            title: Meeting title
            calendar_id: Source calendar ID
            event_id: Google Calendar event ID
            description: Meeting description
            organizer: Meeting organizer email
            attendees: List of attendee emails
            mode: "notes" for passive capture, "interactive" for wake word + voice responses
            use_npu_stt: Use NPU-based STT instead of Google Meet captions (faster, local)
            video_enabled: If True, show full AI video overlay. If False, show black screen.

        Returns:
            True if successfully joined
        """
        logger.info("=" * 60)
        logger.info("JOIN: Starting to join meeting: %s", title or meet_url)
        logger.info("=" * 60)

        # FIRST: Run cleanup before joining to ensure clean state
        # This catches any orphaned devices from previous sessions or crashes
        logger.info("JOIN: Running pre-join cleanup...")
        await self._run_orphan_cleanup("PRE-JOIN")

        # Set NPU STT flag and video flag
        self._use_npu_stt = use_npu_stt
        self._video_enabled = video_enabled  # pylint: disable=attribute-defined-outside-init
        logger.info(
            "JOIN: NPU STT: %s, Video: %s",
            "enabled" if use_npu_stt else "disabled",
            "enabled" if video_enabled else "disabled",
        )

        # Ensure browser is initialized (lazy initialization)
        # Pass video_enabled so the browser controller can start the correct video mode
        if not await self._ensure_browser(video_enabled=video_enabled):
            logger.error("JOIN: Failed to initialize browser for meeting")
            return False

        if self.state.status == "capturing":
            # Check if browser is still alive
            if self._controller and self._controller.is_browser_closed():
                logger.warning("JOIN: Browser was closed - cleaning up stale meeting state")
                await self._cleanup_stale_meeting()
            else:
                logger.warning("JOIN: Already in a meeting")
                return False

        self.state.status = "joining"
        self.state.meet_url = meet_url
        self.state.title = title or self._extract_meeting_id(meet_url)
        self.state.calendar_id = calendar_id
        self.state.event_id = event_id
        self.state.errors = []

        try:
            # Create meeting record in database
            if self.db:
                meeting = MeetingNote(
                    title=self.state.title,
                    calendar_id=calendar_id,
                    meet_url=meet_url,
                    event_id=event_id,
                    description=description,
                    organizer=organizer,
                    attendees=attendees or [],
                    status="in_progress",
                    bot_mode=mode,
                    actual_start=datetime.now().astimezone(),
                )
                self.state.meeting_id = await self.db.create_meeting(meeting)
                logger.info("Created meeting record: %s (mode=%s)", self.state.meeting_id, mode)

            # START NPU STT IMMEDIATELY - audio devices are already created during browser init
            # This ensures we're listening from the moment Chrome connects to the meeting
            # Don't wait for UI automation (captions, popups, etc.)
            if self._use_npu_stt:
                logger.info("🧠 Starting NPU STT early (before UI automation)...")
                _spawn_background(self._setup_npu_stt())

            # Join the meeting (this does UI automation - can take 10+ seconds)
            controller = self._controller
            if controller is None:
                self.state.status = "error"
                self.state.errors.append("Browser controller is not initialized")
                return False

            success = await controller.join_meeting(meet_url)

            if not success:
                self.state.status = "error"
                # Get errors from controller state if available
                if controller.state and controller.state.errors:
                    self.state.errors.extend(controller.state.errors)
                else:
                    self.state.errors.append("Failed to join meeting - check browser controller logs")
                return False

            # Start caption capture
            await controller.start_caption_capture(self._on_caption)

            self.state.status = "capturing"
            self.state.joined_at = datetime.now().astimezone()
            self.state.last_flush = datetime.now().astimezone()

            # Emit toast notification for meeting joined
            try:
                # pylint: disable-next=import-outside-toplevel
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_meeting_joined,
                )

                notify_meeting_joined(self.state.title, mode)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.debug("Ignored error during best-effort step", exc_info=True)

            # Start buffer flush task
            self._flush_task = asyncio.create_task(self._flush_loop())

            # Start screenshot capture loop (every 10 seconds)
            self._screenshot_task = asyncio.create_task(controller.start_screenshot_loop(interval_seconds=10))

            # Start browser health monitor (checks if browser was closed)
            self._browser_monitor_task = asyncio.create_task(self._monitor_browser_health())

            # NPU STT was already started early (before UI automation)
            # No need to start it again here

            # Initialize interactive mode components if requested
            if mode == "interactive":
                self._interactive_mode = True
                await self._setup_interactive_mode()
                logger.info("Joined meeting in INTERACTIVE mode: %s", self.state.title)
            else:
                logger.info("Joined meeting in NOTES mode: %s", self.state.title)

            # Start video daemon integration via D-Bus
            if self._enable_video_integration:
                await self._start_video_integration()

            return True
        # pylint: disable=broad-exception-caught
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to join meeting")
            self.state.status = "error"
            self.state.errors.append(str(e))
            return False

    def _on_caption(self, entry: CaptionEntry) -> None:
        """Handle incoming caption (new or update)."""
        transcript_entry = TranscriptEntry(
            speaker=entry.speaker,
            text=entry.text,
            timestamp=entry.timestamp,
        )

        cap_id = entry.caption_id

        # Check if this is an update to an existing caption (by ID)
        if cap_id and cap_id in self.state.caption_id_to_index:
            # UPDATE: Replace the entry at the tracked index
            idx = self.state.caption_id_to_index[cap_id]
            if 0 <= idx < len(self.state.transcript_buffer):
                self.state.transcript_buffer[idx] = transcript_entry
                logger.debug(
                    "Caption UPDATE (id=%s): [%s] %s...",
                    cap_id,
                    entry.speaker,
                    entry.text[:50],
                )
            else:
                # Index out of range (shouldn't happen), treat as new
                self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
                self.state.transcript_buffer.append(transcript_entry)
                self.state.captions_captured += 1
                logger.debug(
                    "Caption NEW (idx invalid): [%s] %s...",
                    entry.speaker,
                    entry.text[:50],
                )
        elif entry.is_update and self.state.transcript_buffer:
            # Fallback: is_update flag set but no ID tracking - replace last if same speaker
            last_entry = self.state.transcript_buffer[-1]
            if last_entry.speaker == entry.speaker:
                self.state.transcript_buffer[-1] = transcript_entry
                if cap_id:
                    # Track this ID for future updates
                    self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer) - 1
                logger.debug(
                    "Caption UPDATE (fallback): [%s] %s...",
                    entry.speaker,
                    entry.text[:50],
                )
            else:
                # Speaker changed, treat as new
                if cap_id:
                    self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
                self.state.transcript_buffer.append(transcript_entry)
                self.state.captions_captured += 1
                logger.debug(
                    "Caption NEW (speaker changed): [%s] %s...",
                    entry.speaker,
                    entry.text[:50],
                )
        else:
            # NEW caption
            if cap_id:
                self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
            self.state.transcript_buffer.append(transcript_entry)
            self.state.captions_captured += 1
            logger.debug(
                "Caption NEW (id=%s): [%s] %s...",
                cap_id,
                entry.speaker,
                entry.text[:50],
            )

        # Update activity timestamp to show we're not hung
        if self._controller:
            self._controller.update_activity()

        # NOTE: Wake word detection is now handled by NPU STT (_on_npu_transcription)
        # Google Meet captions are only used for transcript/notes, not wake word detection
        # This avoids duplicate processing and the NPU STT is faster/more accurate

        # Call external callback if set
        if self._on_caption_callback:
            self._on_caption_callback(transcript_entry)

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
                self.state.wake_word_triggers += 1
                logger.info(
                    "🔔 WAKE WORD + PAUSE DETECTED from %s: %s",
                    event.speaker,
                    event.command_text,
                )

                # Handle wake word in interactive mode
                if self._interactive_mode:
                    logger.info("🎤 Sending to LLM: %s", event.command_text)
                    # Don't use create_task - await it so we stay in this flow
                    await self._handle_wake_word_command(event)

                if self._on_wake_word_callback:
                    self._on_wake_word_callback(event)

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
                    detector._reset_command_state()  # pylint: disable=protected-access
                    break

    async def get_status(self) -> dict:
        """Get current bot status."""
        status: dict[str, Any] = {
            "status": self.state.status,
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "meet_url": self.state.meet_url,
            "captions_captured": self.state.captions_captured,
            "wake_word_triggers": self.state.wake_word_triggers,
            "wake_word_enabled": self._enable_wake_word,
            "wake_word": self.config.wake_word if self._enable_wake_word else None,
            "buffer_size": len(self.state.transcript_buffer),
            "errors": self.state.errors,
        }

        if self.state.joined_at:
            duration = datetime.now().astimezone() - self.state.joined_at
            status["duration_minutes"] = round(duration.total_seconds() / 60, 1)

        return status

    def set_caption_callback(self, callback: Callable[[TranscriptEntry], None]) -> None:
        """Set callback for real-time caption updates."""
        self._on_caption_callback = callback

    def set_wake_word_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word detection events."""
        self._on_wake_word_callback = callback

    def enable_wake_word(self, enabled: bool = True) -> None:
        """Enable or disable wake word detection."""
        self._enable_wake_word = enabled
        logger.info("Wake word detection %s", "enabled" if enabled else "disabled")

    def has_controller(self) -> bool:
        """Return whether a Meet browser controller is attached."""
        return getattr(self, "_controller", None) is not None

    def controller_instance_id(self):
        """Return the attached controller instance id, if any."""
        controller = getattr(self, "_controller", None)
        if controller is None:
            return None
        return getattr(controller, "_instance_id", None)

    def _extract_meeting_id(self, url: str) -> str:
        """Extract meeting ID from URL for use as title."""
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", url)
        if match:
            return f"Meeting {match.group(1)}"
        return "Untitled Meeting"


def fresh_cleanup_results() -> dict:
    """Empty cleanup result used by the notes-bot manager."""
    return {
        "captures_killed": 0,
        "modules_removed": 0,
        "processes_killed": 0,
        "pipes_removed": 0,
        "video_devices_removed": 0,
        "errors": [],
    }


async def kill_tracked_captures(results: dict, prefix: str, label: str) -> None:
    """Record that tracked capture processes were considered."""
    logger.info("%sChecking %s", prefix, label)
    results["captures_killed"] = results.get("captures_killed", 0)


def record_device_cleanup(results: dict, cleanup_results: dict, prefix: str, label: str) -> None:
    """Copy device-cleanup counts into the manager result."""
    for key in (
        "modules_removed",
        "processes_killed",
        "pipes_removed",
        "video_devices_removed",
    ):
        if key in cleanup_results:
            results[key] = cleanup_results[key]
    logger.info("%s%s finished", prefix, label)


def get_notes_bot():
    """Return the process-wide notes bot."""  # pylint: disable=import-outside-toplevel
    from tool_modules.aa_meet_bot.src.notes_session import get_notes_bot as impl

    return impl()


async def init_notes_bot():
    """Initialize the process-wide notes bot."""  # pylint: disable=import-outside-toplevel
    from tool_modules.aa_meet_bot.src.notes_session import init_notes_bot as impl

    return await impl()


def get_bot_manager():
    """Return the process-wide notes bot manager."""  # pylint: disable=import-outside-toplevel
    from tool_modules.aa_meet_bot.src.notes_session import get_bot_manager as impl

    return impl()


async def init_bot_manager():
    """Initialize the process-wide notes bot manager."""  # pylint: disable=import-outside-toplevel
    from tool_modules.aa_meet_bot.src.notes_session import init_bot_manager as impl

    return await impl()
