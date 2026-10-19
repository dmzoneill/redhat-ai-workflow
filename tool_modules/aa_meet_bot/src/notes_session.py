"""Multi-meeting NotesBot manager."""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
from tool_modules.aa_meet_bot.src.notes_bot import (
    NotesBot,
    fresh_cleanup_results,
    kill_tracked_captures,
    record_device_cleanup,
)
from tool_modules.aa_meet_bot.src.notes_database import MeetingNotesDB, init_notes_db
from tool_modules.aa_meet_bot.src.virtual_devices import (
    cleanup_orphaned_meetbot_devices,
    get_meetbot_device_count,
)

logger = logging.getLogger(__name__)


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
        results = fresh_cleanup_results()
        prefix = f"{context}: " if context else ""
        await kill_tracked_captures(results, prefix, "captures")

        # 2. Get active instance IDs (if any sessions exist)
        active_ids = set()
        async with self._lock:
            for session in self._sessions.values():
                if session.bot.has_controller():
                    active_ids.add(session.bot.controller_instance_id())

        # 3. Run comprehensive orphan cleanup
        try:
            cleanup_results = await cleanup_orphaned_meetbot_devices(
                active_instance_ids=active_ids
            )

            record_device_cleanup(results, cleanup_results, prefix, "Cleanup")

        except Exception as e:  # pylint: disable=broad-exception-caught
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning("%sError during cleanup: %s", prefix, e)

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
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error in meeting monitor: %s", e)

    async def _cleanup_orphaned_audio_devices(self) -> None:
        """Clean up any orphaned MeetBot audio devices."""
        try:
            # Get active instance IDs
            active_ids = set()
            async with self._lock:
                for session in self._sessions.values():
                    if session.bot.has_controller():
                        active_ids.add(session.bot.controller_instance_id())

            # Check device count first to avoid unnecessary cleanup calls
            counts = await get_meetbot_device_count()
            expected_modules = len(active_ids) * 2  # Each instance has sink + source

            if counts["module_count"] > expected_modules:
                logger.info(
                    "Detected potential orphaned devices: %s modules but only "
                    "%s active meetings (expected ~%s modules)",
                    counts["module_count"],
                    len(active_ids),
                    expected_modules,
                )
                results = await cleanup_orphaned_meetbot_devices(active_ids)

                if results["removed_modules"]:
                    logger.info(
                        "Cleaned up %s orphaned audio modules",
                        len(results["removed_modules"]),
                    )
                if results["removed_pipes"]:
                    logger.info(
                        "Cleaned up %s orphaned pipes", len(results["removed_pipes"])
                    )
                if results["errors"]:
                    for err in results["errors"]:
                        logger.warning("Cleanup error: %s", err)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error during orphaned device cleanup: %s", e)

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
                            "Meeting '%s' (%s) has passed its end time (%s + %smin grace)",
                            session.title,
                            session_id,
                            session.scheduled_end,
                            session.grace_period_minutes,
                        )

                # Check for hung bots (no activity for 30+ minutes while supposedly capturing)
                if session.bot.has_controller():
                    last_activity = session.bot.controller_last_activity()
                    inactive_minutes = (now - last_activity).total_seconds() / 60
                    if (
                        inactive_minutes > 30
                        and session.bot.state.status == "capturing"
                    ):
                        hung_sessions.append((session_id, inactive_minutes))
                        logger.warning(
                            "Meeting '%s' (%s) appears hung (no activity for %s min)",
                            session.title,
                            session_id,
                            format(inactive_minutes, ".1f"),
                        )

        # Leave expired meetings (outside lock to avoid deadlock)
        for session_id in expired_sessions:
            logger.info("Auto-leaving expired meeting: %s", session_id)
            result = await self.leave_meeting(session_id)
            if "error" not in result:
                logger.info(
                    "Successfully auto-left meeting %s: %s captions captured",
                    session_id,
                    result.get("captions_captured", 0),
                )

        # Force-kill hung sessions
        for session_id, inactive_minutes in hung_sessions:
            logger.warning(
                "Force-killing hung meeting: %s (inactive %s min)",
                session_id,
                format(inactive_minutes, ".1f"),
            )
            await self._force_kill_session(session_id)

    async def _force_kill_session(self, session_id: str) -> None:
        """Force kill a hung session and clean up all resources."""
        async with self._lock:
            if session_id not in self._sessions:
                return

            session = self._sessions[session_id]
            logger.info("Force-killing session %s...", session_id)

            # Stop NPU STT pipeline first (kills parec processes)
            await session.bot.stop_npu_pipeline()

            # Kill any audio capture processes
            try:
                await PulseAudioCapture.kill_all_captures()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

            # Force kill the browser
            await session.bot.force_kill_controller()

            # Clean up session tracking
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]

            logger.info("Force-killed session %s", session_id)

        # Run orphan cleanup outside the lock
        try:
            await cleanup_orphaned_meetbot_devices(active_instance_ids=set())
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Error during post-force-kill cleanup: %s", e)

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-locals,too-many-arguments,too-many-positional-arguments
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
        logger.info("MANAGER JOIN: Joining meeting %s", session_id)
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
                # Clean up old session
                logger.info("MANAGER JOIN: Cleaning up stale session %s", session_id)
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
                    stamp = scheduled_end.strftime("%H:%M")
                    end_info = f" (auto-leave at {stamp} + {grace_period_minutes}min)"
                logger.info(
                    "Joined meeting %s%s. Active meetings: %s",
                    session_id,
                    end_info,
                    len(self._sessions),
                )
                return session_id, True, []
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
                "Left meeting %s. Active meetings: %s", session_id, len(self._sessions)
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
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info("MANAGER CLOSE: Killed %s audio capture processes", killed)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("MANAGER CLOSE: Error killing audio captures: %s", e)

        # Final cleanup of any orphaned devices
        logger.info("MANAGER CLOSE: Running final orphan cleanup...")
        await self._run_full_cleanup("SHUTDOWN")

        # Close database
        if self._db:
            try:
                await self._db.close()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("MANAGER CLOSE: Error closing database: %s", e)
            self._db = None

        self._initialized = False

        logger.info("=" * 60)
        logger.info("MANAGER CLOSE: Bot manager shutdown complete")
        logger.info("=" * 60)


class _BotSlots:  # pylint: disable=too-few-public-methods
    """Process-wide notes bot and manager, without a global statement."""

    notes_bot: Optional[NotesBot] = None
    bot_manager: Optional["NotesBotManager"] = None


def get_notes_bot() -> NotesBot:
    """Get the global notes bot instance (legacy single-bot mode)."""
    if _BotSlots.notes_bot is None:
        _BotSlots.notes_bot = NotesBot()
    return _BotSlots.notes_bot


async def init_notes_bot() -> NotesBot:
    """Initialize and return the notes bot (legacy single-bot mode).

    Returns the bot instance. Check bot.state.errors if initialization failed.
    """
    bot = get_notes_bot()
    await bot.initialize()
    return bot


def get_bot_manager() -> "NotesBotManager":
    """Get the global bot manager instance."""
    if _BotSlots.bot_manager is None:
        _BotSlots.bot_manager = NotesBotManager()
    return _BotSlots.bot_manager


async def init_bot_manager() -> NotesBotManager:
    """Initialize and return the bot manager.

    This runs startup cleanup to remove any orphaned devices from previous sessions.
    """
    manager = get_bot_manager()
    await manager.initialize()
    return manager
