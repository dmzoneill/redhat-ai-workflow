"""
Meeting Scheduler Service.

Monitors calendars and automatically joins meetings to capture notes.

Features:
- Polls configured calendars for upcoming meetings
- Automatically joins meetings with Google Meet links
- Supports multiple calendars (personal, shared, team)
- Configurable join buffer (join X minutes before start)
- Handles meeting end detection
- Persists user status overrides (skipped/approved) across restarts
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

# Import centralized paths
try:
    from server.paths import MEETBOT_SCREENSHOTS_DIR
except ImportError:
    # Fallback for standalone usage
    from pathlib import Path

    MEETBOT_SCREENSHOTS_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot" / "screenshots"

from server.state_manager import state as state_manager
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
    status: str = "scheduled"  # scheduled, joining, active, completed, skipped, failed
    join_attempts: int = 0  # Track number of join attempts
    max_join_attempts: int = 3  # Maximum join attempts before giving up


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
        self.poll_interval = 300  # Poll calendars every 5 minutes (300 seconds)
        self.join_buffer_minutes = 1  # Join 1 minute before start
        self.leave_buffer_minutes = 1  # Leave 1 minute after end

        # Status overrides - persists user decisions across restarts via StateManager
        self._status_overrides: dict[str, dict] = {}  # meet_key -> {status, timestamp}

        # Background tasks
        self._poll_task: Optional[asyncio.Task] = None
        self._meeting_check_task: Optional[asyncio.Task] = None
        self._meeting_task: Optional[asyncio.Task] = None

    def _load_status_overrides(self) -> None:
        """Load persisted status overrides from StateManager."""
        try:
            data = state_manager.get("meetings", "overrides", {})
            # Clean up old entries (older than 24 hours)
            now = datetime.now().timestamp()
            cutoff = now - (24 * 60 * 60)  # 24 hours ago
            self._status_overrides = {
                k: v for k, v in data.items() if isinstance(v, dict) and v.get("timestamp", 0) > cutoff
            }
            # Save cleaned data back if we removed any
            if len(self._status_overrides) != len(data):
                self._save_status_overrides()
            logger.info(f"Loaded {len(self._status_overrides)} status overrides from state.json")
        except Exception as e:
            logger.warning(f"Failed to load status overrides: {e}")
            self._status_overrides = {}

    def _save_status_overrides(self) -> None:
        """Save status overrides to StateManager."""
        try:
            state_manager.set("meetings", "overrides", self._status_overrides, flush=True)
        except Exception as e:
            logger.warning(f"Failed to save status overrides: {e}")

    def _set_status_override(self, meet_url: str, status: str) -> None:
        """Set a persistent status override for a meeting.

        Uses meet_url as the key since event_id can change across calendar syncs.
        """
        # Extract the meeting code from the URL for a stable key
        key = self._get_meet_key(meet_url)
        if not key:
            logger.warning(f"Cannot persist status - invalid meet URL: {meet_url}")
            return

        self._status_overrides[key] = {"status": status, "timestamp": datetime.now().timestamp()}
        self._save_status_overrides()
        logger.info(f"Persisted status override: {key} -> {status}")

    def _get_status_override(self, meet_url: str) -> Optional[str]:
        """Get a persisted status override for a meeting."""
        key = self._get_meet_key(meet_url)
        if not key:
            return None
        override = self._status_overrides.get(key)
        if isinstance(override, dict):
            return override.get("status")
        return None

    def _clear_status_override(self, meet_url: str) -> None:
        """Clear a status override (when meeting is completed/joined)."""
        key = self._get_meet_key(meet_url)
        if key and key in self._status_overrides:
            del self._status_overrides[key]
            self._save_status_overrides()

    def _get_meet_key(self, meet_url: str) -> Optional[str]:
        """Extract a stable key from a Google Meet URL.

        The meeting code (e.g., 'abc-defg-hij') is stable across calendar syncs.
        """
        if not meet_url:
            return None
        import re

        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        return match.group(1) if match else None

    async def initialize(self) -> bool:
        """Initialize the scheduler."""
        try:
            # Load persisted status overrides first
            self._load_status_overrides()

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

        # Do initial poll before starting background loop
        # This ensures we have meeting data immediately on startup
        try:
            await self._poll_calendars()
        except Exception as e:
            logger.warning(f"Initial calendar poll failed: {e}")

        self._poll_task = asyncio.create_task(self._poll_loop())
        self._meeting_check_task = asyncio.create_task(self._meeting_check_loop())
        logger.info("Meeting scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        logger.info("Stopping meeting scheduler...")
        self.state.running = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await asyncio.wait_for(self._poll_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._poll_task = None

        if self._meeting_check_task:
            self._meeting_check_task.cancel()
            try:
                await asyncio.wait_for(self._meeting_check_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._meeting_check_task = None

        if self._meeting_task:
            self._meeting_task.cancel()
            try:
                await asyncio.wait_for(self._meeting_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._meeting_task = None

        # Close the notes bot (this handles leaving meeting + cleanup)
        if self.notes_bot:
            try:
                await asyncio.wait_for(self.notes_bot.close(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("Timeout closing notes bot during shutdown")
            except Exception as e:
                logger.warning(f"Error closing notes bot: {e}")
            self.notes_bot = None

        # Close database connection
        if self.db:
            try:
                await self.db.close()
            except Exception as e:
                logger.warning(f"Error closing database: {e}")
            self.db = None

        logger.info("Meeting scheduler stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop for calendar updates."""
        while self.state.running:
            try:
                await self._poll_calendars()
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
                self.state.errors.append(str(e))

            await asyncio.sleep(self.poll_interval)

    async def _meeting_check_loop(self) -> None:
        """Frequent loop to check if it's time to join/leave meetings.

        Runs every 30 seconds to ensure we don't miss the join window.
        """
        while self.state.running:
            try:
                await self._check_meeting_times()
            except Exception as e:
                logger.error(f"Meeting check loop error: {e}")

            await asyncio.sleep(30)  # Check every 30 seconds

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
                        (
                            m
                            for m in self.state.upcoming_meetings
                            if m.event_id == event["event_id"] and m.calendar_id == calendar.calendar_id
                        ),
                        None,
                    )

                    if not existing and event.get("meet_url"):
                        # Check for persisted status override first (survives daemon restarts)
                        # Use meet_url as key since event_id can change across calendar syncs
                        persisted_status = self._get_status_override(event["meet_url"])
                        if persisted_status:
                            initial_status = persisted_status
                            logger.info(f"Using persisted status '{persisted_status}' for: {event['title']}")
                        elif calendar.auto_join:
                            # If calendar has auto_join=True, pre-approve the meeting
                            initial_status = "approved"
                        else:
                            # Otherwise it stays "scheduled" and requires manual approval
                            initial_status = "scheduled"

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
                            status=initial_status,
                        )
                        new_meetings.append(meeting)
                        if initial_status == "approved" and not persisted_status:
                            logger.info(f"Auto-approved meeting: {event['title']} (calendar: {calendar.name})")

            except Exception as e:
                logger.error(f"Failed to poll calendar {calendar.calendar_id}: {e}")

        # Add new meetings to upcoming list
        if new_meetings:
            self.state.upcoming_meetings.extend(new_meetings)
            # Sort by start time
            self.state.upcoming_meetings.sort(key=lambda m: m.start_time)
            logger.info(f"Found {len(new_meetings)} new meetings to join")

        # Clean up past meetings (ended more than 30 minutes ago)
        cutoff = now - timedelta(minutes=30)
        self.state.upcoming_meetings = [
            m for m in self.state.upcoming_meetings if m.end_time > cutoff or m.status == "active"
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
            from tool_modules.aa_google_calendar.src.tools_basic import (
                get_calendar_service,
            )

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

                events.append(
                    {
                        "event_id": event.get("id", ""),
                        "title": event.get("summary", "Untitled"),
                        "meet_url": meet_url,
                        "start": start_dt,
                        "end": end_dt,
                        "organizer": event.get("organizer", {}).get("email", ""),
                        "attendees": [a.get("email", "") for a in event.get("attendees", [])],
                        "description": event.get("description", ""),
                    }
                )

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
        # Only auto-join meetings that have been pre-approved (status = "approved")
        # Meetings with status "scheduled" require manual approval via UI
        if not self.state.current_meeting:
            for meeting in self.state.upcoming_meetings:
                # Only join if explicitly approved (not just scheduled)
                if meeting.status != "approved":
                    continue

                # Calculate join window: from (start - buffer) to (start + late_join_window)
                # Allow joining meetings up to 10 minutes after they've started
                join_time = meeting.start_time - timedelta(minutes=self.join_buffer_minutes)
                late_join_cutoff = meeting.start_time + timedelta(minutes=10)

                # Join if we're in the window (2 min before to 10 min after start)
                if now >= join_time and now < late_join_cutoff:
                    # Check if we've exceeded max join attempts
                    if meeting.join_attempts >= meeting.max_join_attempts:
                        logger.warning(
                            f"Meeting '{meeting.title}' exceeded max join attempts "
                            f"({meeting.max_join_attempts}), marking as failed"
                        )
                        meeting.status = "failed"
                        continue

                    logger.info(
                        f"Time to join pre-approved meeting: {meeting.title} "
                        f"(attempt {meeting.join_attempts + 1}/{meeting.max_join_attempts})"
                    )
                    meeting.status = "joining"
                    meeting.join_attempts += 1

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
                        # If failed but still have attempts left, set back to approved
                        if meeting.join_attempts < meeting.max_join_attempts:
                            meeting.status = "approved"
                            logger.warning(
                                f"Failed to join meeting: {meeting.title}, "
                                f"will retry ({meeting.join_attempts}/{meeting.max_join_attempts})"
                            )
                        else:
                            meeting.status = "failed"
                            logger.error(
                                f"Failed to join meeting after {meeting.max_join_attempts} attempts: "
                                f"{meeting.title}"
                            )

                    break  # Only try one meeting at a time

                # If meeting started more than 10 minutes ago, mark as missed
                elif now >= meeting.start_time + timedelta(minutes=10):
                    logger.info(
                        f"Meeting '{meeting.title}' started more than 10 minutes ago, "
                        f"marking as missed (started at {meeting.start_time})"
                    )
                    meeting.status = "missed"

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
                # Persist the skip so it survives daemon restarts
                # Persist using meet_url as key (stable across calendar syncs)
                self._set_status_override(meeting.meet_url, "skipped")
                logger.info(f"Skipped meeting: {meeting.title}")
                return True
        return False

    async def unapprove_meeting(self, event_id: str) -> bool:
        """Un-approve a meeting (change from approved back to skipped).

        This is used when the user clicks on an approved meeting to skip it.
        """
        for meeting in self.state.upcoming_meetings:
            if meeting.event_id == event_id:
                if meeting.status == "approved":
                    meeting.status = "skipped"
                    # Persist using meet_url as key (stable across calendar syncs)
                    self._set_status_override(meeting.meet_url, "skipped")
                    logger.info(f"Un-approved meeting (now skipped): {meeting.title}")
                    return True
                else:
                    logger.warning(f"Meeting found but status is '{meeting.status}', not 'approved'. Cannot unapprove.")
                    return False
        logger.warning(f"No meeting found with event_id={event_id}")
        return False

    async def approve_meeting(self, event_id: str, mode: str = "notes") -> bool:
        """Pre-approve a meeting for auto-join when it starts.

        Args:
            event_id: The calendar event ID
            mode: Bot mode - "notes" or "interactive"
        """
        logger.info(f"approve_meeting called: event_id={event_id}, mode={mode}")
        logger.info(f"Upcoming meetings count: {len(self.state.upcoming_meetings)}")

        for meeting in self.state.upcoming_meetings:
            logger.debug(
                f"  Checking meeting: event_id={meeting.event_id}, status={meeting.status}, title={meeting.title}"
            )
            if meeting.event_id == event_id:
                # Allow approving from scheduled, skipped, or failed states
                if meeting.status in ("scheduled", "skipped", "failed"):
                    meeting.status = "approved"
                    meeting.bot_mode = mode
                    # Persist using meet_url as key (stable across calendar syncs)
                    self._set_status_override(meeting.meet_url, "approved")
                    logger.info(f"Pre-approved meeting: {meeting.title} (mode: {mode}, was: {meeting.status})")
                    return True
                elif meeting.status == "approved":
                    # Already approved, just update mode if different
                    meeting.bot_mode = mode
                    logger.info(f"Meeting already approved, updated mode: {meeting.title} (mode: {mode})")
                    return True
                else:
                    logger.warning(f"Meeting found but status is '{meeting.status}', cannot approve.")
                    return False

        logger.warning(f"No meeting found with event_id={event_id}")
        # Log available event IDs for debugging
        available_ids = [m.event_id for m in self.state.upcoming_meetings[:5]]
        logger.warning(f"Available event_ids (first 5): {available_ids}")
        return False

    async def set_meeting_mode(self, event_id: str, mode: str) -> bool:
        """Set the bot mode for a meeting.

        Args:
            event_id: The calendar event ID
            mode: Bot mode - "notes" or "interactive"
        """
        for meeting in self.state.upcoming_meetings:
            if meeting.event_id == event_id:
                meeting.bot_mode = mode
                logger.info(f"Set mode for {meeting.title}: {mode}")
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

    async def join_meeting_url(
        self,
        meet_url: str,
        title: str = "Manual Join",
        mode: str = "notes",
        video_enabled: bool = False,
    ) -> bool:
        """Join a meeting directly by URL (quick join / manual join).

        Args:
            meet_url: Google Meet URL
            title: Meeting title for display
            mode: "notes" or "interactive"
            video_enabled: If True, show full AI video overlay. If False, show black screen.
        """
        if not self.notes_bot:
            logger.error("Cannot join meeting: notes_bot not initialized")
            return False

        # Create a temporary meeting entry for tracking
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)
        event_id = f"manual_{int(now.timestamp())}"

        meeting = ScheduledMeeting(
            event_id=event_id,
            calendar_id="manual",
            title=title,
            meet_url=meet_url,
            start_time=now,
            end_time=now + timedelta(hours=2),  # Default 2 hour duration
            organizer="manual",
            attendees=[],
            description="Manually joined meeting",
            status="joining",
            bot_mode=mode,
        )

        # Add to upcoming meetings for tracking
        self.state.upcoming_meetings.append(meeting)

        logger.info(f"Quick join: {title} at {meet_url} (mode={mode}, video_enabled={video_enabled})")

        success = await self.notes_bot.join_meeting(
            meet_url=meet_url,
            title=title,
            calendar_id="manual",
            event_id=event_id,
            description="Manually joined meeting",
            organizer="manual",
            attendees=[],
            mode=mode,
            video_enabled=video_enabled,
        )

        if success:
            meeting.status = "active"
            self.state.current_meeting = meeting
            logger.info(f"Successfully joined meeting: {title}")
            return True
        else:
            meeting.status = "skipped"
            logger.error(f"Failed to join meeting: {title}")
            return False

    async def get_status(self) -> dict:
        """Get scheduler status."""
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)

        # Filter to show:
        # - Active meetings: start_time <= now < end_time (currently happening)
        # - Future meetings: start_time > now (not started yet)
        # Include skipped meetings so users can re-approve them
        # Exclude only completed meetings
        future_meetings = [m for m in self.state.upcoming_meetings if m.end_time > now and m.status != "completed"]

        # Get current meeting info with screenshot
        current_meeting_info = None
        current_meetings = []
        if self.state.current_meeting and self.notes_bot:
            meeting = self.state.current_meeting
            # Get screenshot path using the URL-based meeting ID (e.g., qvb-dhaj-osf)
            # The browser controller saves screenshots with this ID, not the event_id
            url_meeting_id = self._extract_meeting_id_from_url(meeting.meet_url)
            screenshot_path = self._get_screenshot_path(url_meeting_id or meeting.event_id)
            meeting_info = {
                "event_id": meeting.event_id,
                "title": meeting.title,
                "start": meeting.start_time.isoformat(),
                "end": meeting.end_time.isoformat(),
                "status": meeting.status,
                "bot_mode": meeting.bot_mode,
                "meet_url": meeting.meet_url,
                "organizer": meeting.organizer,
                "screenshot_path": str(screenshot_path) if screenshot_path else None,
                "screenshot_updated": (
                    screenshot_path.stat().st_mtime if screenshot_path and screenshot_path.exists() else None
                ),
            }
            current_meeting_info = meeting.title
            current_meetings.append(meeting_info)

        return {
            "running": self.state.running,
            "current_meeting": current_meeting_info,
            "current_meetings": current_meetings,
            "upcoming_count": len([m for m in future_meetings if m.status in ("scheduled", "approved")]),
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
                    "calendar_id": m.calendar_id,
                    "meet_url": m.meet_url,
                    "organizer": m.organizer,
                }
                for m in future_meetings[:10]
            ],
            "errors": self.state.errors[-5:],  # Last 5 errors
        }

    def _get_screenshot_path(self, meeting_id: str) -> Optional[Path]:
        """Get the screenshot path for a meeting if it exists."""
        screenshot_path = MEETBOT_SCREENSHOTS_DIR / f"{meeting_id}.png"
        return screenshot_path if screenshot_path.exists() else None

    def _extract_meeting_id_from_url(self, meet_url: str) -> Optional[str]:
        """Extract the meeting ID from a Google Meet URL (e.g., qvb-dhaj-osf)."""
        import re

        if not meet_url:
            return None
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        return match.group(1) if match else None


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
