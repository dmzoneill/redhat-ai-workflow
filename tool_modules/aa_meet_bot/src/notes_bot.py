"""
Notes Bot - Simple meeting note-taking mode.

A lightweight bot that:
- Joins Google Meet meetings
- Captures captions/transcription
- Saves to the meeting notes database
- Does NOT use AI voice/video (no wake word, no responses)

This is the "passive observer" mode for capturing meeting notes
without the overhead of the full interactive AI bot.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController, CaptionEntry
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.notes_database import (
    MeetingNotesDB,
    MeetingNote,
    TranscriptEntry,
    init_notes_db,
)

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
    
    # Stats
    captions_captured: int = 0
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
        self._on_caption_callback: Optional[Callable[[TranscriptEntry], None]] = None
    
    async def initialize(self) -> bool:
        """Initialize the bot and database."""
        try:
            # Initialize database
            if self.db is None:
                self.db = await init_notes_db()
            
            # Initialize browser controller
            self._controller = GoogleMeetController()
            if not await self._controller.initialize():
                logger.error("Failed to initialize browser controller")
                # Copy errors from controller
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append("Browser controller initialization failed")
                return False
            
            logger.info("Notes bot initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize notes bot: {e}")
            self.state.errors.append(str(e))
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
        
        Returns:
            True if successfully joined
        """
        if not self._controller:
            logger.error("Bot not initialized")
            return False
        
        if self.state.status == "capturing":
            logger.warning("Already in a meeting")
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
                    bot_mode="notes",
                    actual_start=datetime.now(),
                )
                self.state.meeting_id = await self.db.create_meeting(meeting)
                logger.info(f"Created meeting record: {self.state.meeting_id}")
            
            # Join the meeting
            success = await self._controller.join_meeting(meet_url)
            
            if not success:
                self.state.status = "error"
                # Get errors from controller state if available
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append("Failed to join meeting - check browser controller logs")
                return False
            
            # Start caption capture
            await self._controller.start_caption_capture(self._on_caption)
            
            self.state.status = "capturing"
            self.state.joined_at = datetime.now()
            self.state.last_flush = datetime.now()
            
            # Start buffer flush task
            self._flush_task = asyncio.create_task(self._flush_loop())
            
            logger.info(f"Joined meeting: {self.state.title}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to join meeting: {e}")
            self.state.status = "error"
            self.state.errors.append(str(e))
            return False
    
    def _on_caption(self, entry: CaptionEntry) -> None:
        """Handle incoming caption."""
        transcript_entry = TranscriptEntry(
            speaker=entry.speaker,
            text=entry.text,
            timestamp=entry.timestamp,
        )
        
        self.state.transcript_buffer.append(transcript_entry)
        self.state.captions_captured += 1
        
        # Update activity timestamp to show we're not hung
        if self._controller:
            self._controller.update_activity()
        
        # Call external callback if set
        if self._on_caption_callback:
            self._on_caption_callback(transcript_entry)
        
        logger.debug(f"Caption: [{entry.speaker}] {entry.text[:50]}...")
    
    async def _flush_loop(self) -> None:
        """Periodically flush transcript buffer to database."""
        while self.state.status == "capturing":
            await asyncio.sleep(self.state.buffer_flush_interval)
            await self._flush_buffer()
    
    async def _flush_buffer(self) -> None:
        """Flush transcript buffer to database."""
        if not self.db or not self.state.meeting_id:
            return
        
        if not self.state.transcript_buffer:
            return
        
        try:
            # Copy and clear buffer
            entries = self.state.transcript_buffer.copy()
            self.state.transcript_buffer = []
            
            # Write to database
            await self.db.add_transcript_entries(self.state.meeting_id, entries)
            self.state.last_flush = datetime.now()
            
            logger.debug(f"Flushed {len(entries)} transcript entries")
            
        except Exception as e:
            logger.error(f"Failed to flush transcript buffer: {e}")
            # Put entries back in buffer
            self.state.transcript_buffer = entries + self.state.transcript_buffer
    
    async def leave_meeting(self, generate_summary: bool = True) -> dict:
        """
        Leave the meeting and finalize notes.
        
        Args:
            generate_summary: Whether to generate an AI summary (future feature)
        
        Returns:
            Meeting summary dict
        """
        if self.state.status != "capturing":
            return {"error": "Not in a meeting"}
        
        self.state.status = "leaving"
        
        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final buffer flush
        await self._flush_buffer()
        
        # Leave the meeting
        if self._controller:
            await self._controller.leave_meeting()
        
        # Update meeting record
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
            await self.db.update_meeting(
                self.state.meeting_id,
                status="completed",
                actual_end=now,
            )
            
            # TODO: Generate AI summary if requested
            # if generate_summary:
            #     summary = await self._generate_summary()
            #     await self.db.update_meeting(self.state.meeting_id, summary=summary)
        
        # Reset state
        self.state = NotesBotState()
        
        logger.info(f"Left meeting. Captured {result['captions_captured']} captions.")
        return result
    
    async def get_status(self) -> dict:
        """Get current bot status."""
        status = {
            "status": self.state.status,
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "meet_url": self.state.meet_url,
            "captions_captured": self.state.captions_captured,
            "buffer_size": len(self.state.transcript_buffer),
            "errors": self.state.errors,
        }
        
        if self.state.joined_at:
            duration = datetime.now() - self.state.joined_at
            status["duration_minutes"] = round(duration.total_seconds() / 60, 1)
        
        return status
    
    def set_caption_callback(self, callback: Callable[[TranscriptEntry], None]) -> None:
        """Set callback for real-time caption updates."""
        self._on_caption_callback = callback
    
    async def close(self) -> None:
        """Clean up resources."""
        if self.state.status == "capturing":
            await self.leave_meeting()
        
        if self._controller:
            await self._controller.close()
        
        if self.db:
            await self.db.close()
    
    def _extract_meeting_id(self, url: str) -> str:
        """Extract meeting ID from URL for use as title."""
        match = re.search(r'meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})', url)
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
    """
    
    def __init__(self):
        """Initialize the bot manager."""
        self._sessions: dict[str, MeetingSession] = {}
        self._bots: dict[str, NotesBot] = {}  # Backward compatibility
        self._db: Optional[MeetingNotesDB] = None
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval: int = 60  # Check every 60 seconds
    
    async def _get_db(self) -> MeetingNotesDB:
        """Get or create shared database instance."""
        if self._db is None:
            self._db = await init_notes_db()
        return self._db
    
    def _generate_session_id(self, meet_url: str) -> str:
        """Generate a unique session ID from the meet URL."""
        # Extract the meeting code from URL
        match = re.search(r'meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})', meet_url)
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
        """Background loop to check for meetings that should end."""
        while True:
            try:
                await asyncio.sleep(self._monitor_interval)
                await self._check_expired_meetings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in meeting monitor: {e}")
    
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
                    end_with_grace = session.scheduled_end + timedelta(minutes=session.grace_period_minutes)
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
                    if inactive_minutes > 30 and session.bot.state.status == "capturing":
                        hung_sessions.append((session_id, inactive_minutes))
                        logger.warning(
                            f"Meeting '{session.title}' ({session_id}) appears hung "
                            f"(no activity for {inactive_minutes:.1f} min)"
                        )
        
        # Leave expired meetings (outside lock to avoid deadlock)
        for session_id in expired_sessions:
            logger.info(f"Auto-leaving expired meeting: {session_id}")
            result = await self.leave_meeting(session_id)
            if 'error' not in result:
                logger.info(f"Successfully auto-left meeting {session_id}: {result.get('captions_captured', 0)} captions captured")
        
        # Force-kill hung sessions
        for session_id, inactive_minutes in hung_sessions:
            logger.warning(f"Force-killing hung meeting: {session_id} (inactive {inactive_minutes:.1f} min)")
            await self._force_kill_session(session_id)
    
    async def _force_kill_session(self, session_id: str) -> None:
        """Force kill a hung session."""
        async with self._lock:
            if session_id not in self._sessions:
                return
            
            session = self._sessions[session_id]
            
            # Force kill the browser
            if session.bot._controller:
                await session.bot._controller.force_kill()
            
            # Clean up
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]
            
            logger.info(f"Force-killed session {session_id}")
    
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
        session_id = self._generate_session_id(meet_url)
        
        async with self._lock:
            # Check if already in this meeting
            if session_id in self._sessions:
                existing = self._sessions[session_id]
                if existing.bot.state.status == "capturing":
                    return session_id, False, ["Already in this meeting"]
                else:
                    # Clean up old session
                    await existing.bot.close()
                    del self._sessions[session_id]
                    if session_id in self._bots:
                        del self._bots[session_id]
            
            # Create new bot with shared database
            db = await self._get_db()
            bot = NotesBot(db=db)
            
            # Initialize the bot
            if not await bot.initialize():
                errors = bot.state.errors or ["Failed to initialize bot"]
                return session_id, False, errors
            
            # Join the meeting
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
                logger.info(f"Joined meeting {session_id}{end_info}. Active meetings: {len(self._sessions)}")
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
            
            logger.info(f"Left meeting {session_id}. Active meetings: {len(self._sessions)}")
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
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            return status
        
        # Return all statuses
        statuses = {}
        for sid, session in self._sessions.items():
            status = await session.bot.get_status()
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            statuses[sid] = status
        return statuses
    
    async def get_all_statuses(self) -> list[dict]:
        """Get status of all active meetings as a list."""
        statuses = []
        for session_id, session in self._sessions.items():
            status = await session.bot.get_status()
            status["session_id"] = session_id
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            # Calculate time remaining
            if session.scheduled_end:
                remaining = session.scheduled_end - datetime.now()
                status["time_remaining_minutes"] = max(0, remaining.total_seconds() / 60)
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
    
    async def update_scheduled_end(self, session_id: str, scheduled_end: datetime) -> bool:
        """Update the scheduled end time for a meeting."""
        if session_id not in self._sessions:
            return False
        self._sessions[session_id].scheduled_end = scheduled_end
        # Ensure monitor is running
        await self._start_monitor()
        return True
    
    async def close(self) -> None:
        """Clean up all resources."""
        await self._stop_monitor()
        await self.leave_all()
        if self._db:
            await self._db.close()
            self._db = None


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
    """Initialize and return the bot manager."""
    return get_bot_manager()
