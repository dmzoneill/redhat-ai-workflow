"""
Meeting Scheduler Service.

Monitors calendars and automatically joins meetings to capture notes.

Features:
- Polls configured calendars for upcoming meetings
- Automatically joins meetings with Google Meet links
- Supports multiple calendars (personal, shared, team)
- Configurable join buffer (join X minutes before start)
- Handles meeting end detection
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.notes_bot import NotesBot, init_notes_bot
from tool_modules.aa_meet_bot.src.notes_database import (
    MeetingNotesDB,
    MonitoredCalendar,
    init_notes_db,
)

logger = logging.getLogger(__name__)

# Default timezone
TIMEZONE = "Europe/Dublin"


@dataclass
class ScheduledMeeting:
    """A meeting scheduled to be joined."""
    event_id: str
    calendar_id: str
    title: str
    meet_url: str
    start_time: datetime
    end_time: datetime
    organizer: str
    attendees: list[str] = field(default_factory=list)
    description: str = ""
    bot_mode: str = "notes"  # notes or interactive
    status: str = "scheduled"  # scheduled, joining, active, completed, skipped


@dataclass
class SchedulerState:
    """Current state of the scheduler."""
    running: bool = False
    current_meeting: Optional[ScheduledMeeting] = None
    upcoming_meetings: list[ScheduledMeeting] = field(default_factory=list)
    completed_today: int = 0
    last_poll: Optional[datetime] = None
    errors: list[str] = field(default_factory=list)


class MeetingScheduler:
    """
    Service that monitors calendars and auto-joins meetings.
    
    Runs as a background task, polling calendars and joining
    meetings at the appropriate time.
    """
    
    def __init__(
        self,
        db: Optional[MeetingNotesDB] = None,
        notes_bot: Optional[NotesBot] = None,
    ):
        """
        Initialize the scheduler.
        
        Args:
            db: Database instance
            notes_bot: Notes bot instance for joining meetings
        """
        self.config = get_config()
        self.db = db
        self.notes_bot = notes_bot
        self.state = SchedulerState()
        
        # Configuration
        self.poll_interval = 60  # Poll calendars every 60 seconds
        self.join_buffer_minutes = 2  # Join 2 minutes before start
        self.leave_buffer_minutes = 1  # Leave 1 minute after end
        
        # Background tasks
        self._poll_task: Optional[asyncio.Task] = None
        self._meeting_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> bool:
        """Initialize the scheduler."""
        try:
            # Initialize database
            if self.db is None:
                self.db = await init_notes_db()
            
            # Initialize notes bot
            if self.notes_bot is None:
                self.notes_bot = await init_notes_bot()
            
            logger.info("Meeting scheduler initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}")
            self.state.errors.append(str(e))
            return False
    
    async def start(self) -> None:
        """Start the scheduler background tasks."""
        if self.state.running:
            logger.warning("Scheduler already running")
            return
        
        self.state.running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Meeting scheduler started")
    
    async def stop(self) -> None:
        """Stop the scheduler."""
        self.state.running = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        
        if self._meeting_task:
            self._meeting_task.cancel()
            try:
                await self._meeting_task
            except asyncio.CancelledError:
                pass
        
        # Leave current meeting if any
        if self.notes_bot and self.state.current_meeting:
            await self.notes_bot.leave_meeting()
        
        logger.info("Meeting scheduler stopped")
    
    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self.state.running:
            try:
                await self._poll_calendars()
                await self._check_meeting_times()
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                self.state.errors.append(str(e))
            
            await asyncio.sleep(self.poll_interval)
    
    async def _poll_calendars(self) -> None:
        """Poll all monitored calendars for upcoming meetings."""
        if not self.db:
            return
        
        calendars = await self.db.get_calendars(enabled_only=True)
        if not calendars:
            return
        
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)
        
        # Look ahead window (next 24 hours)
        time_min = now
        time_max = now + timedelta(hours=24)
        
        new_meetings = []
        
        for calendar in calendars:
            if not calendar.auto_join:
                continue
            
            try:
                events = await self._get_calendar_events(
                    calendar.calendar_id,
                    time_min,
                    time_max,
                )
                
                for event in events:
                    # Check if we already have this meeting scheduled
                    existing = next(
                        (m for m in self.state.upcoming_meetings 
                         if m.event_id == event["event_id"] and m.calendar_id == calendar.calendar_id),
                        None
                    )
                    
                    if not existing and event.get("meet_url"):
                        meeting = ScheduledMeeting(
                            event_id=event["event_id"],
                            calendar_id=calendar.calendar_id,
                            title=event["title"],
                            meet_url=event["meet_url"],
                            start_time=event["start"],
                            end_time=event["end"],
                            organizer=event.get("organizer", ""),
                            attendees=event.get("attendees", []),
                            description=event.get("description", ""),
                            bot_mode=calendar.bot_mode,
                        )
                        new_meetings.append(meeting)
                
            except Exception as e:
                logger.error(f"Failed to poll calendar {calendar.calendar_id}: {e}")
        
        # Add new meetings to upcoming list
        if new_meetings:
            self.state.upcoming_meetings.extend(new_meetings)
            # Sort by start time
            self.state.upcoming_meetings.sort(key=lambda m: m.start_time)
            logger.info(f"Found {len(new_meetings)} new meetings to join")
        
        # Clean up past meetings
        self.state.upcoming_meetings = [
            m for m in self.state.upcoming_meetings
            if m.end_time > now and m.status in ("scheduled", "joining")
        ]
        
        self.state.last_poll = now
    
    async def _get_calendar_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
    ) -> list[dict]:
        """
        Get events from a calendar.
        
        Uses the Google Calendar API via the aa_google_calendar module.
        """
        try:
            # Import here to avoid circular imports
            from tool_modules.aa_google_calendar.src.tools_basic import get_calendar_service
            
            service, error = get_calendar_service()
            if error or not service:
                logger.error(f"Calendar service error: {error}")
                return []
            
            tz = ZoneInfo(TIMEZONE)
            
            events_result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=50,
                    singleEvents=True,
                    orderBy="startTime",
                    timeZone=TIMEZONE,
                )
                .execute()
            )
            
            events = []
            for event in events_result.get("items", []):
                # Extract Meet URL
                meet_url = None
                if event.get("conferenceData", {}).get("entryPoints"):
                    for entry in event["conferenceData"]["entryPoints"]:
                        if entry.get("entryPointType") == "video":
                            meet_url = entry.get("uri", "")
                            break
                
                if not meet_url:
                    continue  # Skip events without Meet links
                
                # Parse times
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                
                try:
                    if "T" in start:
                        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz)
                        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(tz)
                    else:
                        # All-day event, skip
                        continue
                except (ValueError, TypeError):
                    continue
                
                events.append({
                    "event_id": event.get("id", ""),
                    "title": event.get("summary", "Untitled"),
                    "meet_url": meet_url,
                    "start": start_dt,
                    "end": end_dt,
                    "organizer": event.get("organizer", {}).get("email", ""),
                    "attendees": [a.get("email", "") for a in event.get("attendees", [])],
                    "description": event.get("description", ""),
                })
            
            return events
            
        except Exception as e:
            logger.error(f"Failed to get calendar events: {e}")
            return []
    
    async def _check_meeting_times(self) -> None:
        """Check if it's time to join or leave any meetings."""
        if not self.notes_bot:
            return
        
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)
        
        # Check if we need to leave current meeting
        if self.state.current_meeting:
            meeting = self.state.current_meeting
            leave_time = meeting.end_time + timedelta(minutes=self.leave_buffer_minutes)
            
            if now >= leave_time:
                logger.info(f"Meeting ended: {meeting.title}")
                await self.notes_bot.leave_meeting()
                meeting.status = "completed"
                self.state.current_meeting = None
                self.state.completed_today += 1
        
        # Check if we need to join a meeting
        if not self.state.current_meeting:
            for meeting in self.state.upcoming_meetings:
                if meeting.status != "scheduled":
                    continue
                
                join_time = meeting.start_time - timedelta(minutes=self.join_buffer_minutes)
                
                if now >= join_time and now < meeting.end_time:
                    logger.info(f"Time to join: {meeting.title}")
                    meeting.status = "joining"
                    
                    success = await self.notes_bot.join_meeting(
                        meet_url=meeting.meet_url,
                        title=meeting.title,
                        calendar_id=meeting.calendar_id,
                        event_id=meeting.event_id,
                        description=meeting.description,
                        organizer=meeting.organizer,
                        attendees=meeting.attendees,
                    )
                    
                    if success:
                        meeting.status = "active"
                        self.state.current_meeting = meeting
                        logger.info(f"Joined meeting: {meeting.title}")
                    else:
                        meeting.status = "skipped"
                        logger.error(f"Failed to join meeting: {meeting.title}")
                    
                    break  # Only join one meeting at a time
    
    async def add_calendar(
        self,
        calendar_id: str,
        name: str = "",
        auto_join: bool = True,
        bot_mode: str = "notes",
    ) -> bool:
        """
        Add a calendar to monitor.
        
        Args:
            calendar_id: Google Calendar ID (email or calendar ID)
            name: Display name for the calendar
            auto_join: Whether to automatically join meetings
            bot_mode: "notes" for note-taking only, "interactive" for AI responses
        
        Returns:
            True if added successfully
        """
        if not self.db:
            return False
        
        calendar = MonitoredCalendar(
            calendar_id=calendar_id,
            name=name or calendar_id,
            auto_join=auto_join,
            bot_mode=bot_mode,
            enabled=True,
        )
        
        await self.db.add_calendar(calendar)
        logger.info(f"Added calendar: {name or calendar_id}")
        
        # Trigger immediate poll
        await self._poll_calendars()
        
        return True
    
    async def remove_calendar(self, calendar_id: str) -> bool:
        """Remove a calendar from monitoring."""
        if not self.db:
            return False
        
        success = await self.db.remove_calendar(calendar_id)
        if success:
            logger.info(f"Removed calendar: {calendar_id}")
        return success
    
    async def list_calendars(self) -> list[MonitoredCalendar]:
        """List all monitored calendars."""
        if not self.db:
            return []
        return await self.db.get_calendars(enabled_only=False)
    
    async def skip_meeting(self, event_id: str) -> bool:
        """Skip a scheduled meeting (don't auto-join)."""
        for meeting in self.state.upcoming_meetings:
            if meeting.event_id == event_id:
                meeting.status = "skipped"
                logger.info(f"Skipped meeting: {meeting.title}")
                return True
        return False
    
    async def force_join(self, event_id: str) -> bool:
        """Force join a meeting immediately."""
        if not self.notes_bot:
            return False
        
        for meeting in self.state.upcoming_meetings:
            if meeting.event_id == event_id and meeting.status == "scheduled":
                meeting.status = "joining"
                
                success = await self.notes_bot.join_meeting(
                    meet_url=meeting.meet_url,
                    title=meeting.title,
                    calendar_id=meeting.calendar_id,
                    event_id=meeting.event_id,
                    description=meeting.description,
                    organizer=meeting.organizer,
                    attendees=meeting.attendees,
                )
                
                if success:
                    meeting.status = "active"
                    self.state.current_meeting = meeting
                    return True
                else:
                    meeting.status = "skipped"
        
        return False
    
    async def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "running": self.state.running,
            "current_meeting": self.state.current_meeting.title if self.state.current_meeting else None,
            "upcoming_count": len([m for m in self.state.upcoming_meetings if m.status == "scheduled"]),
            "completed_today": self.state.completed_today,
            "last_poll": self.state.last_poll.isoformat() if self.state.last_poll else None,
            "upcoming_meetings": [
                {
                    "event_id": m.event_id,
                    "title": m.title,
                    "start": m.start_time.isoformat(),
                    "end": m.end_time.isoformat(),
                    "status": m.status,
                    "bot_mode": m.bot_mode,
                }
                for m in self.state.upcoming_meetings[:10]
            ],
            "errors": self.state.errors[-5:],  # Last 5 errors
        }


# Global instance
_scheduler: Optional[MeetingScheduler] = None


def get_scheduler() -> MeetingScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = MeetingScheduler()
    return _scheduler


async def init_scheduler() -> MeetingScheduler:
    """Initialize and return the scheduler."""
    scheduler = get_scheduler()
    await scheduler.initialize()
    return scheduler
