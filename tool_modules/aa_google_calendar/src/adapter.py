"""
Google Calendar Memory Adapter - Memory source for querying calendar events.

This adapter exposes Google Calendar as a memory source,
allowing the memory abstraction layer to query upcoming events and meetings.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter
from tool_modules.common import get_google_calendar_settings

logger = logging.getLogger(__name__)

TIMEZONE = get_google_calendar_settings()["timezone"]


@memory_adapter(
    name="calendar",
    display_name="Google Calendar",
    capabilities={"query", "search"},
    intent_keywords=[
        "calendar",
        "meeting",
        "event",
        "schedule",
        "appointment",
        "when",
        "today",
        "tomorrow",
        "this week",
        "busy",
        "free",
        "availability",
        "meet",
        "call",
        "standup",
        "sync",
    ],
    priority=55,
    latency_class="slow",  # External Google Calendar API
)
class GoogleCalendarAdapter:
    """
    Adapter for Google Calendar event queries.

    Provides access to upcoming calendar events,
    meeting schedules, and availability.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query Google Calendar for events.

        Args:
            question: Natural language question about calendar/meetings
            filter: Optional filter with limit

        Returns:
            AdapterResult with matching events
        """
        try:
            from tool_modules.aa_google_calendar.src.tools_basic import (
                get_calendar_service,
            )
        except ImportError:
            try:
                from .tools_basic import get_calendar_service
            except ImportError:
                return AdapterResult(
                    source="calendar",
                    found=False,
                    items=[],
                    error="Google Calendar tools not available",
                )

        service, error = get_calendar_service()
        if error:
            return AdapterResult(
                source="calendar",
                found=False,
                items=[],
                error=error,
            )

        try:
            limit = filter.limit if filter else 10
            tz = ZoneInfo(TIMEZONE)
            now = datetime.now(tz)

            # Determine time range based on question
            days_ahead = 7  # Default: next week
            question_lower = question.lower()

            if "today" in question_lower:
                days_ahead = 1
            elif "tomorrow" in question_lower:
                # Start from tomorrow
                now = now + timedelta(days=1)
                days_ahead = 1
            elif "this week" in question_lower:
                days_ahead = 7
            elif "next week" in question_lower:
                now = now + timedelta(days=7)
                days_ahead = 7
            elif "month" in question_lower:
                days_ahead = 30

            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()

            # Get events
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=limit,
                    singleEvents=True,
                    orderBy="startTime",
                    timeZone=TIMEZONE,
                )
                .execute()
            )

            events = events_result.get("items", [])

            if not events:
                return AdapterResult(
                    source="calendar",
                    found=False,
                    items=[],
                )

            items = []
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))
                summary = event.get("summary", "No title")

                # Parse datetime
                try:
                    if "T" in start:
                        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start_dt = start_dt.astimezone(tz)
                        time_str = start_dt.strftime("%a %Y-%m-%d %H:%M")
                    else:
                        time_str = f"{start} (all day)"
                except (ValueError, TypeError):
                    time_str = start

                # Check for Meet link
                meet_link = ""
                if event.get("conferenceData", {}).get("entryPoints"):
                    for entry in event["conferenceData"]["entryPoints"]:
                        if entry.get("entryPointType") == "video":
                            meet_link = entry.get("uri", "")
                            break

                # Get attendees
                attendees = []
                for att in event.get("attendees", [])[:5]:
                    attendees.append(att.get("email", ""))

                summary_text = f"{time_str}: {summary}"

                content_parts = [
                    f"Event: {summary}",
                    f"When: {time_str}",
                ]
                if event.get("location"):
                    content_parts.append(f"Location: {event['location']}")
                if meet_link:
                    content_parts.append(f"Meet: {meet_link}")
                if attendees:
                    content_parts.append(f"Attendees: {', '.join(attendees)}")
                if event.get("description"):
                    desc = event["description"][:200]
                    content_parts.append(f"Description: {desc}")
                content = "\n".join(content_parts) + "\n"

                items.append(
                    MemoryItem(
                        source="calendar",
                        type="event",
                        relevance=0.8,
                        summary=summary_text,
                        content=content,
                        metadata={
                            "event_id": event.get("id"),
                            "title": summary,
                            "start": start,
                            "end": end,
                            "location": event.get("location"),
                            "meet_link": meet_link,
                            "attendees": attendees,
                            "status": event.get("status"),
                        },
                    )
                )

            return AdapterResult(
                source="calendar",
                found=True,
                items=items,
            )

        except Exception as e:
            logger.error(f"Calendar query failed: {e}")
            return AdapterResult(
                source="calendar",
                found=False,
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Semantic search (same as query for Calendar)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Calendar adapter is read-only for memory abstraction."""
        return AdapterResult(
            source="calendar",
            found=False,
            items=[],
            error="Calendar adapter is read-only. Use google_calendar_schedule_meeting to create events.",
        )

    async def health_check(self) -> HealthStatus:
        """Check if Google Calendar is accessible."""
        try:
            from tool_modules.aa_google_calendar.src.tools_basic import (
                get_calendar_service,
            )
        except ImportError:
            try:
                from .tools_basic import get_calendar_service
            except ImportError:
                return HealthStatus(
                    healthy=False,
                    error="Google Calendar tools not available",
                )

        try:
            service, error = get_calendar_service()
            if error:
                return HealthStatus(healthy=False, error=error)

            # Try to get calendar info
            calendar = service.calendars().get(calendarId="primary").execute()

            return HealthStatus(
                healthy=True,
                details={
                    "calendar": calendar.get("summary", "Primary"),
                    "email": calendar.get("id", "unknown"),
                    "timezone": calendar.get("timeZone", TIMEZONE),
                },
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="Google Calendar tools not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))
