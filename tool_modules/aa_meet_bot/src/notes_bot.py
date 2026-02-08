"""
Notes Bot - Meeting note-taking mode with optional wake word detection.

A bot that:
- Joins Google Meet meetings
- Captures captions/transcription
- Saves to the meeting notes database
- Optionally detects wake words and can respond via LLM/TTS

This is the primary mode for the meeting scheduler.

Architecture:
    NotesBot is the orchestrator that manages meeting lifecycle (join/leave/close).
    Heavy lifting is delegated to composed components:
    - TranscriptionProcessor: caption aggregation, NPU STT, wake word detection, buffer flushing
    - InteractiveActions: LLM responses, TTS, video daemon integration
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.notes_actions import InteractiveActions
from tool_modules.aa_meet_bot.src.notes_database import (
    MeetingNote,
    MeetingNotesDB,
    TranscriptEntry,
    init_notes_db,
)
from tool_modules.aa_meet_bot.src.notes_transcription import TranscriptionProcessor
from tool_modules.aa_meet_bot.src.wake_word import WakeWordEvent, WakeWordManager

logger = logging.getLogger(__name__)


@dataclass
class NotesBotState:
    """Current state of the notes bot."""

    meeting_id: Optional[int] = None  # Database meeting ID
    meet_url: str = ""
    title: str = ""
    calendar_id: str = ""
    event_id: str = ""

    # Status
    status: str = "idle"  # idle, joining, capturing, leaving, error
    joined_at: Optional[datetime] = None

    # Transcript buffer (for batching writes)
    transcript_buffer: list[TranscriptEntry] = field(default_factory=list)
    buffer_flush_interval: float = 10.0  # Flush every 10 seconds
    last_flush: Optional[datetime] = None

    # Caption ID tracking for update-in-place
    caption_id_to_index: dict[int, int] = field(default_factory=dict)

    # Stats
    captions_captured: int = 0
    wake_word_triggers: int = 0
    errors: list[str] = field(default_factory=list)


class NotesBot:
    """
    Simple meeting note-taking bot.

    Joins meetings and captures transcripts without AI interaction.
    """

    def __init__(self, db: Optional[MeetingNotesDB] = None):
        """
        Initialize the notes bot.

        Args:
            db: Database instance. If None, uses global instance.
        """
        self.config = get_config()
        self.db = db
        self._controller: Optional[GoogleMeetController] = None
        self.state = NotesBotState()
        self._flush_task: Optional[asyncio.Task] = None
        self._screenshot_task: Optional[asyncio.Task] = None
        self._browser_monitor_task: Optional[asyncio.Task] = None

        # Wake word detection
        self._wake_word_manager: Optional[WakeWordManager] = None
        self._enable_wake_word: bool = True  # Enable by default

        # NPU STT mode flag
        self._use_npu_stt: bool = True  # Use NPU STT by default in interactive mode

        # Composed components (initialized after wake word manager in initialize())
        self._transcription: Optional[TranscriptionProcessor] = None
        self._actions: Optional[InteractiveActions] = None

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
                    f'Wake word detection enabled (wake word: "{self.config.wake_word}")'
                )

            # Initialize composed components
            self._transcription = TranscriptionProcessor(
                state=self.state,
                db=self.db,
                wake_word_manager=self._wake_word_manager,
            )
            self._actions = InteractiveActions(
                state=self.state,
                wake_word_manager=self._wake_word_manager,
            )

            # Wire cross-component references:
            # Transcription needs to call actions for wake word commands
            self._transcription._on_wake_word_command = (
                self._actions.handle_wake_word_command
            )
            # Transcription needs the responding flag from actions
            # (done dynamically via property bridge in _sync_component_state)

            # Don't initialize browser here - do it lazily when joining a meeting
            # This prevents the daemon from opening Chrome on startup
            logger.info("INIT: Notes bot initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize notes bot: {e}")
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
        results = {
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
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            results["audio_captures_killed"] = killed
            if killed > 0:
                logger.info(f"{prefix}Killed {killed} tracked audio capture processes")
        except Exception as e:
            results["errors"].append(f"Audio capture cleanup: {e}")

        # 2. Run comprehensive orphan cleanup (modules, parec, pipes, video)
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
            )

            cleanup_results = await cleanup_orphaned_meetbot_devices(
                active_instance_ids=set()
            )

            results["modules_removed"] = len(cleanup_results.get("removed_modules", []))
            results["processes_killed"] = len(
                cleanup_results.get("killed_processes", [])
            )
            results["pipes_removed"] = len(cleanup_results.get("removed_pipes", []))
            results["video_devices_removed"] = len(
                cleanup_results.get("removed_video_devices", [])
            )
            results["errors"].extend(cleanup_results.get("errors", []))

            total = (
                results["modules_removed"]
                + results["processes_killed"]
                + results["pipes_removed"]
                + results["video_devices_removed"]
            )

            if total > 0:
                logger.info(
                    f"{prefix}Orphan cleanup: "
                    f"{results['modules_removed']} modules, "
                    f"{results['processes_killed']} processes, "
                    f"{results['pipes_removed']} pipes, "
                    f"{results['video_devices_removed']} video devices"
                )
            else:
                logger.info(f"{prefix}Orphan cleanup: No orphaned devices found")

        except Exception as e:
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning(f"{prefix}Error during orphan cleanup: {e}")

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
            return True
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            self.state.errors.append(str(e))
            self._controller = None
            return False

    async def join_meeting(
        self,
        meet_url: str,
        title: str = "",
        calendar_id: str = "",
        event_id: str = "",
        description: str = "",
        organizer: str = "",
        attendees: Optional[list[str]] = None,
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
        logger.info(f"JOIN: Starting to join meeting: {title or meet_url}")
        logger.info("=" * 60)

        # FIRST: Run cleanup before joining to ensure clean state
        # This catches any orphaned devices from previous sessions or crashes
        logger.info("JOIN: Running pre-join cleanup...")
        await self._run_orphan_cleanup("PRE-JOIN")

        # Set NPU STT flag and video flag
        self._use_npu_stt = use_npu_stt
        self._video_enabled = video_enabled
        logger.info(
            f"JOIN: NPU STT: {'enabled' if use_npu_stt else 'disabled'}, "
            f"Video: {'enabled' if video_enabled else 'disabled'}"
        )

        # Ensure browser is initialized (lazy initialization)
        # Pass video_enabled so the browser controller can start the correct video mode
        if not await self._ensure_browser(video_enabled=video_enabled):
            logger.error("JOIN: Failed to initialize browser for meeting")
            return False

        if self.state.status == "capturing":
            # Check if browser is still alive
            if self._controller and self._controller.is_browser_closed():
                logger.warning(
                    "JOIN: Browser was closed - cleaning up stale meeting state"
                )
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
                    actual_start=datetime.now(),
                )
                self.state.meeting_id = await self.db.create_meeting(meeting)
                logger.info(
                    f"Created meeting record: {self.state.meeting_id} (mode={mode})"
                )

            # START NPU STT IMMEDIATELY - audio devices are already created during browser init
            # This ensures we're listening from the moment Chrome connects to the meeting
            # Don't wait for UI automation (captions, popups, etc.)
            if self._use_npu_stt and self._transcription:
                logger.info("🧠 Starting NPU STT early (before UI automation)...")
                asyncio.create_task(self._transcription.setup_npu_stt(self._controller))

            # Join the meeting (this does UI automation - can take 10+ seconds)
            success = await self._controller.join_meeting(meet_url)

            if not success:
                self.state.status = "error"
                # Get errors from controller state if available
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append(
                        "Failed to join meeting - check browser controller logs"
                    )
                return False

            # Start caption capture (via transcription component)
            await self._controller.start_caption_capture(self._transcription.on_caption)

            self.state.status = "capturing"
            self.state.joined_at = datetime.now()
            self.state.last_flush = datetime.now()

            # Emit toast notification for meeting joined
            try:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_meeting_joined,
                )

                notify_meeting_joined(self.state.title, mode)
            except Exception as e:
                logger.debug(f"Suppressed error in join_meeting (notification): {e}")

            # Start buffer flush task (via transcription component)
            self._flush_task = asyncio.create_task(self._transcription.flush_loop())

            # Start screenshot capture loop (every 10 seconds)
            self._screenshot_task = asyncio.create_task(
                self._controller.start_screenshot_loop(interval_seconds=10)
            )

            # Start browser health monitor (checks if browser was closed)
            self._browser_monitor_task = asyncio.create_task(
                self._monitor_browser_health()
            )

            # NPU STT was already started early (before UI automation)
            # No need to start it again here

            # Sync controller reference to components
            self._sync_component_state()

            # Initialize interactive mode components if requested
            if mode == "interactive" and self._actions:
                self._actions.interactive_mode = True
                if self._transcription:
                    self._transcription._interactive_mode = True
                await self._actions.setup_interactive_mode()
                logger.info(f"Joined meeting in INTERACTIVE mode: {self.state.title}")
            else:
                logger.info(f"Joined meeting in NOTES mode: {self.state.title}")

            # Start video daemon integration via D-Bus
            if self._actions and self._actions.enable_video_integration:
                await self._actions.start_video_integration(self._controller)

            return True

        except Exception as e:
            logger.error(f"Failed to join meeting: {e}")
            self.state.status = "error"
            self.state.errors.append(str(e))
            return False

    def _sync_component_state(self) -> None:
        """Sync controller reference and shared state to composed components.

        Called after the browser controller is initialized and whenever
        component state needs to be refreshed (e.g., after joining a meeting).
        """
        if self._transcription:
            self._transcription._controller = self._controller
            self._transcription._actions_ref = self._actions
        if self._actions:
            self._actions._controller = self._controller

    # (Extracted methods: _start_video_integration, _find_chromium_sink_input,
    #  _poll_participants, _update_video_attendees, _stop_video_integration
    #  are now in InteractiveActions (notes_actions.py).
    #  _setup_npu_stt, _on_npu_transcription, _process_caption_for_wake_word,
    #  _check_wake_word_pause, _on_caption, _flush_loop, _flush_buffer
    #  are now in TranscriptionProcessor (notes_transcription.py).)

    async def _monitor_browser_health(self) -> None:
        """Monitor browser health and trigger cleanup if browser closes."""
        logger.info("Browser health monitor started")
        consecutive_failures = 0
        max_failures = 3  # Trigger cleanup after 3 consecutive failures

        while self.state.status == "capturing":
            await asyncio.sleep(1)  # Check every 1 second for faster detection

            # Check if controller reports browser closed (now actively checks browser state)
            if self._controller and self._controller.is_browser_closed():
                logger.warning("Browser health monitor: Browser closed detected!")
                await self._cleanup_stale_meeting()
                break

            # Also check if controller state shows not joined
            if (
                self._controller
                and self._controller.state
                and not self._controller.state.joined
            ):
                logger.warning("Browser health monitor: Meeting ended (not joined)")
                await self._cleanup_stale_meeting()
                break

            # Additional check: verify page is responsive by checking URL
            if self._controller and self._controller.page:
                try:
                    # Quick check - if this throws, browser is dead
                    _ = self._controller.page.url
                    consecutive_failures = 0  # Reset on success
                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(
                        f"Browser health monitor: Page check failed ({consecutive_failures}/{max_failures}): {e}"
                    )
                    if consecutive_failures >= max_failures:
                        logger.warning(
                            "Browser health monitor: Page unresponsive - triggering cleanup"
                        )
                        await self._cleanup_stale_meeting()
                        break

            # Check if browser process is still alive (belt and suspenders)
            if self._controller and self._controller.browser:
                try:
                    # Check if browser is still connected
                    if not self._controller.browser.is_connected():
                        logger.warning("Browser health monitor: Browser disconnected")
                        await self._cleanup_stale_meeting()
                        break
                except Exception as e:
                    logger.warning(f"Browser health monitor: Browser check failed: {e}")
                    # Don't cleanup on exception - could be a transient error
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        logger.warning(
                            "Browser health monitor: Too many browser check failures - triggering cleanup"
                        )
                        await self._cleanup_stale_meeting()
                        break

        logger.info("Browser health monitor stopped")

    async def _cleanup_stale_meeting(self) -> None:
        """Clean up state from a meeting where the browser was closed unexpectedly.

        This is called when:
        - Browser window is closed by user
        - Browser crashes
        - Meeting ends unexpectedly
        - Health monitor detects browser is unresponsive

        CRITICAL: This must clean up ALL resources to prevent orphaned:
        - PulseAudio modules (sinks/sources)
        - Named pipes
        - parec processes
        - Video devices
        - Background tasks
        """
        logger.info("=" * 60)
        logger.info("CLEANUP: Starting stale meeting cleanup...")
        logger.info("=" * 60)

        # Track what we're cleaning up
        cleanup_errors = []

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # This MUST happen before closing the controller to ensure the parec
        # process is killed while we still have the PID reference
        if self._transcription:
            try:
                await self._transcription.stop_npu_stt("CLEANUP")
            except Exception as e:
                cleanup_errors.append(f"NPU STT error: {e}")

        # 2. Kill any remaining audio capture processes from this session
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(
                    f"CLEANUP: Force-killed {killed} orphaned audio capture processes"
                )
        except Exception as e:
            logger.warning(f"CLEANUP: Error killing audio captures: {e}")
            cleanup_errors.append(f"Audio capture kill error: {e}")

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
        ]

        for task_name, task in tasks_to_cancel:  # noqa: B007
            if task and not task.done():
                logger.info(f"CLEANUP: Cancelling {task_name}...")
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    cleanup_errors.append(f"{task_name} cancel error: {e}")

        # Clear task references
        self._flush_task = None
        self._screenshot_task = None
        self._browser_monitor_task = None

        # Cancel component tasks
        if self._transcription:
            self._transcription.cancel_wake_word_task()

        # 4. Stop video daemon integration (via actions component)
        if self._actions and self._actions.video_daemon_active:
            logger.info("CLEANUP: Stopping video daemon integration...")
            try:
                await asyncio.wait_for(
                    self._actions.stop_video_integration(), timeout=5.0
                )
                logger.info("CLEANUP: Video daemon stopped")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout stopping video daemon")
                cleanup_errors.append("Video daemon timeout")
            except Exception as e:
                logger.warning(f"CLEANUP: Error stopping video integration: {e}")
                cleanup_errors.append(f"Video daemon error: {e}")

        # 5. Flush any remaining transcript buffer
        if self._transcription:
            try:
                await self._transcription.flush_buffer()
            except Exception as e:
                logger.warning(f"CLEANUP: Failed to flush buffer: {e}")

        # 6. Update meeting record as ended
        if self.db and self.state.meeting_id:
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=datetime.now(),
                )
                logger.info(
                    f"CLEANUP: Meeting {self.state.meeting_id} marked as completed"
                )
            except Exception as e:
                logger.warning(f"CLEANUP: Failed to update meeting record: {e}")

        # 7. Close the browser controller - this cleans up per-instance audio devices
        # restore_browser_audio=True because the meeting died unexpectedly
        if self._controller:
            logger.info("CLEANUP: Closing browser controller...")
            try:
                await asyncio.wait_for(
                    self._controller.close(restore_browser_audio=True), timeout=10.0
                )
                logger.info("CLEANUP: Browser controller closed")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in _cleanup_controller (force kill): {e}"
                    )
            except Exception as e:
                logger.warning(f"CLEANUP: Error closing controller: {e}")
                cleanup_errors.append(f"Controller close error: {e}")
            finally:
                self._controller = None

        # 8. FINAL: Clean up ANY remaining orphaned devices system-wide
        # This is the safety net that catches anything we missed
        cleanup_result = await self._run_orphan_cleanup("CLEANUP")
        if cleanup_result.get("errors"):
            cleanup_errors.extend(cleanup_result["errors"])

        # 9. Reset state
        self.state.status = "idle"
        self.state.meeting_id = None
        self.state.meet_url = ""
        self.state.title = ""
        self.state.caption_id_to_index.clear()
        self.state.transcript_buffer.clear()

        # Log summary
        logger.info("=" * 60)
        if cleanup_errors:
            logger.warning(f"CLEANUP: Completed with {len(cleanup_errors)} errors:")
            for err in cleanup_errors:
                logger.warning(f"  - {err}")
        else:
            logger.info("CLEANUP: Completed successfully - all resources released")
        logger.info("CLEANUP: Ready for new meeting")
        logger.info("=" * 60)

    async def leave_meeting(self, generate_summary: bool = True) -> dict:
        """
        Leave the meeting and finalize notes.

        This is the NORMAL exit path (user requested leave).
        For unexpected exits (browser closed), see _cleanup_stale_meeting().

        Args:
            generate_summary: Whether to generate an AI summary (future feature)

        Returns:
            Meeting summary dict
        """
        if self.state.status != "capturing":
            return {"error": "Not in a meeting"}

        logger.info("=" * 60)
        logger.info("LEAVE: Starting graceful meeting exit...")
        logger.info("=" * 60)

        self.state.status = "leaving"

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # Must happen before closing controller to ensure clean shutdown
        if self._transcription:
            await self._transcription.stop_npu_stt("LEAVE")

        # 2. Kill any remaining audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"LEAVE: Killed {killed} audio capture processes")
        except Exception as e:
            logger.warning(f"LEAVE: Error killing audio captures: {e}")

        # 3. Cancel background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
        ]

        for task_name, task in tasks_to_cancel:  # noqa: B007
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._flush_task = None
        self._screenshot_task = None
        self._browser_monitor_task = None

        # 4. Stop video daemon integration (via actions component)
        if self._actions and self._actions.video_daemon_active:
            logger.info("LEAVE: Stopping video daemon...")
            try:
                await asyncio.wait_for(
                    self._actions.stop_video_integration(), timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout stopping video daemon")
            except Exception as e:
                logger.warning(f"LEAVE: Error stopping video daemon: {e}")

        # 5. Final buffer flush (via transcription component)
        if self._transcription:
            try:
                await self._transcription.flush_buffer()
            except Exception as e:
                logger.warning(f"LEAVE: Failed to flush buffer: {e}")

        # 6. Leave the meeting (browser automation)
        if self._controller:
            logger.info("LEAVE: Leaving meeting via browser...")
            try:
                await asyncio.wait_for(self._controller.leave_meeting(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout leaving meeting")
            except Exception as e:
                logger.warning(f"LEAVE: Error leaving meeting: {e}")

        # 7. Build result before cleanup
        result = {
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "duration_minutes": 0,
            "captions_captured": self.state.captions_captured,
        }

        if self.db and self.state.meeting_id:
            now = datetime.now()

            # Calculate duration
            if self.state.joined_at:
                duration = now - self.state.joined_at
                result["duration_minutes"] = round(duration.total_seconds() / 60, 1)

            # Update meeting status
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=now,
                )
            except Exception as e:
                logger.warning(f"LEAVE: Failed to update meeting record: {e}")

        # 8. Close browser controller (this cleans up per-instance devices)
        # restore_browser_audio=False for normal exit (user's Chrome wasn't affected)
        if self._controller:
            logger.info("LEAVE: Closing browser controller...")
            try:
                await asyncio.wait_for(
                    self._controller.close(restore_browser_audio=False), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout closing controller")
            except Exception as e:
                logger.warning(f"LEAVE: Error closing controller: {e}")
            finally:
                self._controller = None

        # 9. Emit toast notification
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (
                notify_meeting_left,
            )

            notify_meeting_left(
                result.get("title", "Meeting"),
                result.get("duration_minutes", 0),
                result.get("captions_captured", 0),
            )
        except Exception as e:
            logger.debug(f"Suppressed error in leave_meeting (notification): {e}")

        # 10. FINAL: Clean up any orphaned devices (safety net)
        await self._run_orphan_cleanup("POST-LEAVE")

        # 11. Reset state
        self.state = NotesBotState()

        logger.info("=" * 60)
        logger.info(
            f"LEAVE: Meeting ended. Captured {result['captions_captured']} captions."
        )
        logger.info("=" * 60)

        return result

    async def get_status(self) -> dict:
        """Get current bot status."""
        status = {
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
            duration = datetime.now() - self.state.joined_at
            status["duration_minutes"] = round(duration.total_seconds() / 60, 1)

        return status

    def set_caption_callback(self, callback: Callable[[TranscriptEntry], None]) -> None:
        """Set callback for real-time caption updates."""
        if self._transcription:
            self._transcription._on_caption_callback = callback

    def set_wake_word_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word detection events."""
        if self._transcription:
            self._transcription._on_wake_word_callback = callback

    def enable_wake_word(self, enabled: bool = True) -> None:
        """Enable or disable wake word detection."""
        self._enable_wake_word = enabled
        logger.info(f"Wake word detection {'enabled' if enabled else 'disabled'}")

    async def close(self) -> None:
        """Clean up all resources.

        This is the final cleanup method called when the bot is being destroyed.
        It ensures ALL resources are released, including:
        - Background tasks
        - NPU STT pipeline (and its parec processes)
        - Browser controller (and its audio devices)
        - Any orphaned devices system-wide
        """
        logger.info("=" * 60)
        logger.info("CLOSE: Shutting down notes bot...")
        logger.info("=" * 60)

        # 1. Stop NPU STT pipeline FIRST (kills parec processes)
        if self._transcription:
            await self._transcription.stop_npu_stt("CLOSE")

        # 2. Kill any remaining audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"CLOSE: Killed {killed} orphaned audio capture processes")
        except Exception as e:
            logger.warning(f"CLOSE: Error killing audio captures: {e}")

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
        ]

        for task_name, task in tasks_to_cancel:  # noqa: B007
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._flush_task = None
        self._screenshot_task = None

        # Cancel component tasks
        if self._transcription:
            self._transcription.cancel_wake_word_task()

        # 4. Leave meeting if in one (this also flushes buffer)
        if self.state.status == "capturing":
            logger.info("CLOSE: Leaving active meeting...")
            try:
                await asyncio.wait_for(self.leave_meeting(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout leaving meeting, forcing cleanup...")
                await self._cleanup_stale_meeting()
            except Exception as e:
                logger.warning(f"CLOSE: Error leaving meeting: {e}")
                await self._cleanup_stale_meeting()

        # 5. Close browser controller if still open
        if self._controller:
            logger.info("CLOSE: Closing browser controller...")
            try:
                await asyncio.wait_for(
                    self._controller.close(restore_browser_audio=True), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception as e:
                    logger.debug(f"Suppressed error in close (force kill): {e}")
            except Exception as e:
                logger.warning(f"CLOSE: Error closing browser controller: {e}")
            finally:
                self._controller = None

        # 6. FINAL: Clean up any remaining orphaned devices system-wide
        await self._run_orphan_cleanup("SHUTDOWN")

        # Note: Don't close the database here - it may be shared
        # The caller (scheduler/manager) is responsible for database cleanup

        logger.info("=" * 60)
        logger.info("CLOSE: Notes bot shutdown complete")
        logger.info("=" * 60)

    def _extract_meeting_id(self, url: str) -> str:
        """Extract meeting ID from URL for use as title."""
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", url)
        if match:
            return f"Meeting {match.group(1)}"
        return "Untitled Meeting"


@dataclass
class MeetingSession:
    """Tracks a meeting session with its bot and metadata."""

    bot: NotesBot
    session_id: str
    meet_url: str
    title: str
    scheduled_end: Optional[datetime] = None
    grace_period_minutes: int = 5  # Stay this long after scheduled end


class NotesBotManager:
    """
    Manages multiple NotesBot instances for concurrent meetings.

    Each meeting gets its own bot with its own browser instance.
    Bots are keyed by a unique session ID (typically the meet URL or a UUID).

    Features:
    - Automatic leave when scheduled end time passes (with grace period)
    - Background monitor task to check for expired meetings
    - Automatic cleanup of orphaned devices on startup and periodically
    """

    def __init__(self):
        """Initialize the bot manager."""
        self._sessions: dict[str, MeetingSession] = {}
        self._bots: dict[str, NotesBot] = {}  # Backward compatibility
        self._db: Optional[MeetingNotesDB] = None
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval: int = 60  # Check every 60 seconds
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the manager and run startup cleanup.

        IMPORTANT: This should be called before using the manager.
        It cleans up any orphaned devices from previous sessions.
        """
        if self._initialized:
            return

        logger.info("=" * 60)
        logger.info("MANAGER INIT: Initializing NotesBotManager...")
        logger.info("=" * 60)

        # Run startup cleanup to remove any orphaned devices
        logger.info("MANAGER INIT: Running startup cleanup...")
        await self._run_full_cleanup("MANAGER-INIT")

        self._initialized = True
        logger.info("MANAGER INIT: NotesBotManager initialized")

    async def _run_full_cleanup(self, context: str = "") -> dict:
        """Run comprehensive cleanup of all orphaned resources.

        Args:
            context: Label for logging

        Returns:
            Cleanup results
        """
        results = {
            "audio_captures_killed": 0,
            "modules_removed": 0,
            "processes_killed": 0,
            "pipes_removed": 0,
            "video_devices_removed": 0,
            "errors": [],
        }

        prefix = f"{context}: " if context else ""

        # 1. Kill any tracked audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            results["audio_captures_killed"] = killed
            if killed > 0:
                logger.info(f"{prefix}Killed {killed} tracked audio captures")
        except Exception as e:
            results["errors"].append(f"Audio capture cleanup: {e}")

        # 2. Get active instance IDs (if any sessions exist)
        active_ids = set()
        async with self._lock:
            for session in self._sessions.values():
                if session.bot._controller:
                    active_ids.add(session.bot._controller._instance_id)

        # 3. Run comprehensive orphan cleanup
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
            )

            cleanup_results = await cleanup_orphaned_meetbot_devices(
                active_instance_ids=active_ids
            )

            results["modules_removed"] = len(cleanup_results.get("removed_modules", []))
            results["processes_killed"] = len(
                cleanup_results.get("killed_processes", [])
            )
            results["pipes_removed"] = len(cleanup_results.get("removed_pipes", []))
            results["video_devices_removed"] = len(
                cleanup_results.get("removed_video_devices", [])
            )
            results["errors"].extend(cleanup_results.get("errors", []))

            total = (
                results["modules_removed"]
                + results["processes_killed"]
                + results["pipes_removed"]
                + results["video_devices_removed"]
            )

            if total > 0:
                logger.info(
                    f"{prefix}Cleanup: {results['modules_removed']} modules, "
                    f"{results['processes_killed']} processes, "
                    f"{results['pipes_removed']} pipes, "
                    f"{results['video_devices_removed']} video devices"
                )
            else:
                logger.info(f"{prefix}Cleanup: No orphaned devices found")

        except Exception as e:
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning(f"{prefix}Error during cleanup: {e}")

        return results

    async def _get_db(self) -> MeetingNotesDB:
        """Get or create shared database instance."""
        if self._db is None:
            self._db = await init_notes_db()
        return self._db

    def _generate_session_id(self, meet_url: str) -> str:
        """Generate a unique session ID from the meet URL."""
        # Extract the meeting code from URL
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        if match:
            return match.group(1)
        # Fallback to hash of URL
        import hashlib

        return hashlib.md5(meet_url.encode()).hexdigest()[:12]

    async def _start_monitor(self) -> None:
        """Start the background monitor task if not already running."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Started meeting end-time monitor")

    async def _stop_monitor(self) -> None:
        """Stop the background monitor task."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("Stopped meeting end-time monitor")

    async def _monitor_loop(self) -> None:
        """Background loop to check for meetings that should end and cleanup orphaned devices."""
        cleanup_counter = 0
        cleanup_interval = 5  # Run device cleanup every 5 monitor cycles (5 minutes)

        while True:
            try:
                await asyncio.sleep(self._monitor_interval)
                await self._check_expired_meetings()

                # Periodically clean up orphaned audio devices
                cleanup_counter += 1
                if cleanup_counter >= cleanup_interval:
                    cleanup_counter = 0
                    await self._cleanup_orphaned_audio_devices()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in meeting monitor: {e}")

    async def _cleanup_orphaned_audio_devices(self) -> None:
        """Clean up any orphaned MeetBot audio devices."""
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
                get_meetbot_device_count,
            )

            # Get active instance IDs
            active_ids = set()
            async with self._lock:
                for session in self._sessions.values():
                    if session.bot._controller:
                        active_ids.add(session.bot._controller._instance_id)

            # Check device count first to avoid unnecessary cleanup calls
            counts = await get_meetbot_device_count()
            expected_modules = len(active_ids) * 2  # Each instance has sink + source

            if counts["module_count"] > expected_modules:
                logger.info(
                    f"Detected potential orphaned devices: {counts['module_count']} modules "
                    f"but only {len(active_ids)} active meetings (expected ~{expected_modules} modules)"
                )
                results = await cleanup_orphaned_meetbot_devices(active_ids)

                if results["removed_modules"]:
                    logger.info(
                        f"Cleaned up {len(results['removed_modules'])} orphaned audio modules"
                    )
                if results["removed_pipes"]:
                    logger.info(
                        f"Cleaned up {len(results['removed_pipes'])} orphaned pipes"
                    )
                if results["errors"]:
                    for err in results["errors"]:
                        logger.warning(f"Cleanup error: {err}")

        except Exception as e:
            logger.error(f"Error during orphaned device cleanup: {e}")

    async def _check_expired_meetings(self) -> None:
        """Check for and leave any meetings past their end time."""
        now = datetime.now()
        expired_sessions = []
        hung_sessions = []

        async with self._lock:
            for session_id, session in self._sessions.items():
                # Check scheduled end time
                if session.scheduled_end:
                    # Add grace period
                    end_with_grace = session.scheduled_end + timedelta(
                        minutes=session.grace_period_minutes
                    )
                    if now > end_with_grace:
                        expired_sessions.append(session_id)
                        logger.info(
                            f"Meeting '{session.title}' ({session_id}) has passed its end time "
                            f"({session.scheduled_end} + {session.grace_period_minutes}min grace)"
                        )

                # Check for hung bots (no activity for 30+ minutes while supposedly capturing)
                if session.bot._controller:
                    last_activity = session.bot._controller._last_activity
                    inactive_minutes = (now - last_activity).total_seconds() / 60
                    if (
                        inactive_minutes > 30
                        and session.bot.state.status == "capturing"
                    ):
                        hung_sessions.append((session_id, inactive_minutes))
                        logger.warning(
                            f"Meeting '{session.title}' ({session_id}) appears hung "
                            f"(no activity for {inactive_minutes:.1f} min)"
                        )

        # Leave expired meetings (outside lock to avoid deadlock)
        for session_id in expired_sessions:
            logger.info(f"Auto-leaving expired meeting: {session_id}")
            result = await self.leave_meeting(session_id)
            if "error" not in result:
                logger.info(
                    f"Successfully auto-left meeting {session_id}:"
                    f" {result.get('captions_captured', 0)} captions captured"
                )

        # Force-kill hung sessions
        for session_id, inactive_minutes in hung_sessions:
            logger.warning(
                f"Force-killing hung meeting: {session_id} (inactive {inactive_minutes:.1f} min)"
            )
            await self._force_kill_session(session_id)

    async def _force_kill_session(self, session_id: str) -> None:
        """Force kill a hung session and clean up all resources."""
        async with self._lock:
            if session_id not in self._sessions:
                return

            session = self._sessions[session_id]
            logger.info(f"Force-killing session {session_id}...")

            # Stop NPU STT pipeline first (kills parec processes)
            if session.bot._transcription:
                try:
                    await asyncio.wait_for(
                        session.bot._transcription.stop_npu_stt("FORCE-KILL"),
                        timeout=3.0,
                    )
                except (asyncio.TimeoutError, Exception):
                    pass

            # Kill any audio capture processes
            try:
                from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

                await PulseAudioCapture.kill_all_captures()
            except Exception as e:
                logger.debug(
                    f"Suppressed error in force_cleanup (kill audio captures): {e}"
                )

            # Force kill the browser
            if session.bot._controller:
                await session.bot._controller.force_kill()

            # Clean up session tracking
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]

            logger.info(f"Force-killed session {session_id}")

        # Run orphan cleanup outside the lock
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
            )

            await cleanup_orphaned_meetbot_devices(active_instance_ids=set())
        except Exception as e:
            logger.warning(f"Error during post-force-kill cleanup: {e}")

    async def join_meeting(
        self,
        meet_url: str,
        title: str = "",
        calendar_id: str = "",
        event_id: str = "",
        description: str = "",
        organizer: str = "",
        attendees: Optional[list[str]] = None,
        scheduled_end: Optional[datetime] = None,
        grace_period_minutes: int = 5,
    ) -> tuple[str, bool, list[str]]:
        """
        Join a meeting, creating a new bot instance.

        Args:
            meet_url: Google Meet URL
            title: Meeting title
            calendar_id: Source calendar ID
            event_id: Google Calendar event ID
            description: Meeting description
            organizer: Meeting organizer email
            attendees: List of attendee emails
            scheduled_end: When the meeting is scheduled to end (auto-leave after this + grace)
            grace_period_minutes: Minutes to stay after scheduled_end (default 5)

        Returns:
            Tuple of (session_id, success, errors)
        """
        # Ensure manager is initialized (runs startup cleanup on first call)
        if not self._initialized:
            await self.initialize()

        session_id = self._generate_session_id(meet_url)

        logger.info("=" * 60)
        logger.info(f"MANAGER JOIN: Joining meeting {session_id}")
        logger.info("=" * 60)

        # Run pre-join cleanup to ensure clean state
        logger.info("MANAGER JOIN: Running pre-join cleanup...")
        await self._run_full_cleanup("PRE-JOIN")

        async with self._lock:
            # Check if already in this meeting
            if session_id in self._sessions:
                existing = self._sessions[session_id]
                if existing.bot.state.status == "capturing":
                    return session_id, False, ["Already in this meeting"]
                else:
                    # Clean up old session
                    logger.info(f"MANAGER JOIN: Cleaning up stale session {session_id}")
                    await existing.bot.close()
                    del self._sessions[session_id]
                    if session_id in self._bots:
                        del self._bots[session_id]

            # Create new bot with shared database
            db = await self._get_db()
            bot = NotesBot(db=db)

            # Initialize the bot (this also runs cleanup)
            if not await bot.initialize():
                errors = bot.state.errors or ["Failed to initialize bot"]
                return session_id, False, errors

            # Join the meeting (this also runs pre-join cleanup)
            success = await bot.join_meeting(
                meet_url=meet_url,
                title=title,
                calendar_id=calendar_id,
                event_id=event_id,
                description=description,
                organizer=organizer,
                attendees=attendees,
            )

            if success:
                # Create session with metadata
                session = MeetingSession(
                    bot=bot,
                    session_id=session_id,
                    meet_url=meet_url,
                    title=title or self._generate_session_id(meet_url),
                    scheduled_end=scheduled_end,
                    grace_period_minutes=grace_period_minutes,
                )
                self._sessions[session_id] = session
                self._bots[session_id] = bot  # Backward compatibility

                # Start monitor if we have scheduled end times
                if scheduled_end:
                    await self._start_monitor()

                end_info = ""
                if scheduled_end:
                    end_info = f" (auto-leave at {scheduled_end.strftime('%H:%M')} + {grace_period_minutes}min)"
                logger.info(
                    f"Joined meeting {session_id}{end_info}. Active meetings: {len(self._sessions)}"
                )
                return session_id, True, []
            else:
                errors = bot.state.errors or ["Failed to join meeting"]
                await bot.close()
                return session_id, False, errors

    async def leave_meeting(self, session_id: str) -> dict:
        """
        Leave a specific meeting.

        Args:
            session_id: The session ID returned from join_meeting

        Returns:
            Meeting summary dict or error
        """
        async with self._lock:
            if session_id not in self._sessions:
                # Try backward compatibility
                if session_id in self._bots:
                    bot = self._bots[session_id]
                    result = await bot.leave_meeting()
                    await bot.close()
                    del self._bots[session_id]
                    return result
                return {"error": f"No active meeting with session ID: {session_id}"}

            session = self._sessions[session_id]
            result = await session.bot.leave_meeting()

            # Clean up
            await session.bot.close()
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]

            # Stop monitor if no more meetings with scheduled ends
            has_scheduled = any(s.scheduled_end for s in self._sessions.values())
            if not has_scheduled and self._monitor_task:
                await self._stop_monitor()

            logger.info(
                f"Left meeting {session_id}. Active meetings: {len(self._sessions)}"
            )
            return result

    async def leave_all(self) -> list[dict]:
        """Leave all active meetings."""
        # Stop monitor first
        await self._stop_monitor()

        results = []
        session_ids = list(self._sessions.keys())

        for session_id in session_ids:
            result = await self.leave_meeting(session_id)
            result["session_id"] = session_id
            results.append(result)

        return results

    async def get_status(self, session_id: Optional[str] = None) -> dict:
        """
        Get status of one or all active meetings.

        Args:
            session_id: Specific session to get status for, or None for all

        Returns:
            Status dict or dict of statuses keyed by session_id
        """
        if session_id:
            if session_id not in self._sessions:
                return {"error": f"No active meeting with session ID: {session_id}"}
            session = self._sessions[session_id]
            status = await session.bot.get_status()
            status["scheduled_end"] = (
                session.scheduled_end.isoformat() if session.scheduled_end else None
            )
            status["grace_period_minutes"] = session.grace_period_minutes
            return status

        # Return all statuses
        statuses = {}
        for sid, session in self._sessions.items():
            status = await session.bot.get_status()
            status["scheduled_end"] = (
                session.scheduled_end.isoformat() if session.scheduled_end else None
            )
            status["grace_period_minutes"] = session.grace_period_minutes
            statuses[sid] = status
        return statuses

    async def get_all_statuses(self) -> list[dict]:
        """Get status of all active meetings as a list."""
        statuses = []
        for session_id, session in self._sessions.items():
            status = await session.bot.get_status()
            status["session_id"] = session_id
            status["scheduled_end"] = (
                session.scheduled_end.isoformat() if session.scheduled_end else None
            )
            status["grace_period_minutes"] = session.grace_period_minutes
            # Calculate time remaining
            if session.scheduled_end:
                remaining = session.scheduled_end - datetime.now()
                status["time_remaining_minutes"] = max(
                    0, remaining.total_seconds() / 60
                )
            statuses.append(status)
        return statuses

    def get_active_count(self) -> int:
        """Get number of active meetings."""
        return len(self._sessions)

    def get_active_session_ids(self) -> list[str]:
        """Get list of active session IDs."""
        return list(self._sessions.keys())

    def get_bot(self, session_id: str) -> Optional[NotesBot]:
        """Get a specific bot instance."""
        session = self._sessions.get(session_id)
        return session.bot if session else None

    def get_session(self, session_id: str) -> Optional[MeetingSession]:
        """Get a specific session."""
        return self._sessions.get(session_id)

    async def update_scheduled_end(
        self, session_id: str, scheduled_end: datetime
    ) -> bool:
        """Update the scheduled end time for a meeting."""
        if session_id not in self._sessions:
            return False
        self._sessions[session_id].scheduled_end = scheduled_end
        # Ensure monitor is running
        await self._start_monitor()
        return True

    async def close(self) -> None:
        """Clean up all resources.

        This is the final shutdown method. It:
        1. Stops the monitor task
        2. Leaves all active meetings
        3. Runs final orphan cleanup
        4. Closes the database
        """
        logger.info("=" * 60)
        logger.info("MANAGER CLOSE: Shutting down bot manager...")
        logger.info("=" * 60)

        # Stop monitor first
        try:
            await asyncio.wait_for(self._stop_monitor(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("MANAGER CLOSE: Timeout stopping monitor")

        # Leave all meetings (each will run its own cleanup)
        try:
            await asyncio.wait_for(self.leave_all(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("MANAGER CLOSE: Timeout leaving all meetings")

        # Kill any remaining audio capture processes
        logger.info("MANAGER CLOSE: Killing any remaining audio captures...")
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture

            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"MANAGER CLOSE: Killed {killed} audio capture processes")
        except Exception as e:
            logger.warning(f"MANAGER CLOSE: Error killing audio captures: {e}")

        # Final cleanup of any orphaned devices
        logger.info("MANAGER CLOSE: Running final orphan cleanup...")
        await self._run_full_cleanup("SHUTDOWN")

        # Close database
        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.warning(f"MANAGER CLOSE: Error closing database: {e}")
            self._db = None

        self._initialized = False

        logger.info("=" * 60)
        logger.info("MANAGER CLOSE: Bot manager shutdown complete")
        logger.info("=" * 60)


# Global instances
_notes_bot: Optional[NotesBot] = None
_bot_manager: Optional[NotesBotManager] = None


def get_notes_bot() -> NotesBot:
    """Get the global notes bot instance (legacy single-bot mode)."""
    global _notes_bot
    if _notes_bot is None:
        _notes_bot = NotesBot()
    return _notes_bot


async def init_notes_bot() -> NotesBot:
    """Initialize and return the notes bot (legacy single-bot mode).

    Returns the bot instance. Check bot.state.errors if initialization failed.
    """
    bot = get_notes_bot()
    success = await bot.initialize()
    if not success:
        # Errors are stored in bot.state.errors
        pass
    return bot


def get_bot_manager() -> NotesBotManager:
    """Get the global bot manager instance."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = NotesBotManager()
    return _bot_manager


async def init_bot_manager() -> NotesBotManager:
    """Initialize and return the bot manager.

    This runs startup cleanup to remove any orphaned devices from previous sessions.
    """
    manager = get_bot_manager()
    await manager.initialize()
    return manager
