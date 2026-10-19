# pylint: disable=duplicate-code
"""
Google Calendar MCP Tools

Provides tools for creating Google Calendar events with Google Meet links.

CONSTRAINTS:
- All meetings scheduled in Irish time (Europe/Dublin)
- Meetings only between 15:00-19:00 Irish time
- Checks attendee availability before scheduling
- Finds mutually free slots

Setup:
1. Create OAuth 2.0 credentials in Google Cloud Console
2. Download credentials.json to ~/.config/google_calendar/credentials.json
3. Run the server once to complete OAuth flow and save token.json
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # noqa: E402  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.tool_registry import ToolRegistry  # noqa: E402
from tool_modules.aa_google_slides.src.tools_basic import (  # pylint: disable=ungrouped-imports
    CONFIG_DIR,
    CREDENTIALS_FILE,
    SERVICE_ACCOUNT_FILE,
    TOKEN_FILE,
)

logger = logging.getLogger(__name__)

# pylint: disable-next=wrong-import-position
from tool_modules.aa_google_calendar.src.calendar_tools_impl import (  # noqa: E402
    MEETING_END_HOUR,
    MEETING_START_HOUR,
    TIMEZONE,
    _google_calendar_check_mutual_availability_impl,
    _google_calendar_find_meeting_impl,
    _google_calendar_list_events_impl,
    _google_calendar_quick_meeting_impl,
    get_calendar_service,
)


async def _google_calendar_status_impl() -> str:
    """Check Google Calendar integration status and configuration."""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    lines = [
        "# Google Calendar Integration Status",
        "",
        f"📍 **Timezone:** {TIMEZONE}",
        f"⏰ **Current Irish time:** {now.strftime('%Y-%m-%d %H:%M')}",
        f"🕐 **Meeting window:** {MEETING_START_HOUR}:00 - {MEETING_END_HOUR}:00",
        "",
    ]

    # Check config directory
    lines.append(f"**Config directory:** `{CONFIG_DIR}`")
    lines.append("")

    # Check credentials
    if CREDENTIALS_FILE.exists():
        lines.append("✅ OAuth credentials file found")
    else:
        lines.append("❌ OAuth credentials not found")
        lines.append(f"   Add `credentials.json` to `{CONFIG_DIR}`")

    if SERVICE_ACCOUNT_FILE.exists():
        lines.append("✅ Service account file found")
    else:
        lines.append("⚪ Service account not configured (optional)")

    if TOKEN_FILE.exists():
        lines.append("✅ OAuth token cached (authenticated)")
    else:
        lines.append("⚪ No cached token (will need to authenticate)")

    lines.append("")

    # Try to connect
    service, error = get_calendar_service()

    if service:
        lines.append("✅ **Connected to Google Calendar**")

        # Try to get calendar info
        try:
            calendar = service.calendars().get(calendarId="primary").execute()
            lines.append(f"   Calendar: {calendar.get('summary', 'Primary')}")
            lines.append(f"   Email: {calendar.get('id', 'Unknown')}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            lines.append(f"   (Could not fetch calendar details: {e})")
    else:
        lines.append(f"❌ **Not connected:** {error}")

    lines.append("")
    lines.append("## Setup Instructions")
    lines.append("")
    lines.append("1. Go to [Google Cloud Console](https://console.cloud.google.com/)")
    lines.append("2. Create or select a project")
    lines.append("3. Enable the Google Calendar API")
    lines.append("4. Create OAuth 2.0 credentials (Desktop app)")
    lines.append(f"5. Download and save as `{CREDENTIALS_FILE}`")
    lines.append("6. Run any calendar tool to complete OAuth flow")
    lines.append("")
    lines.append("## Attendee Availability")
    lines.append("")
    lines.append("For checking attendee availability, the attendee must:")
    lines.append("- Be in the same Google Workspace organization (Red Hat), OR")
    lines.append("- Have shared their calendar with you")

    return "\n".join(lines)


# pylint: disable-next=too-many-branches
async def _google_calendar_list_calendars_impl() -> str:
    """List all calendars accessible to your account."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get("items", [])

        if not calendars:
            return "📅 No calendars found."

        lines = [
            "# 📅 Your Calendars",
            "",
            "Use the **Calendar ID** to monitor or query specific calendars.",
            "",
        ]

        # Group by access role
        primary = []
        owned = []
        shared = []

        for cal in calendars:
            cal_info = {
                "id": cal.get("id", ""),
                "name": cal.get("summary", "Unnamed"),
                "description": cal.get("description", ""),
                "access": cal.get("accessRole", "reader"),
                "primary": cal.get("primary", False),
                "color": cal.get("backgroundColor", ""),
            }

            if cal_info["primary"]:
                primary.append(cal_info)
            elif cal_info["access"] == "owner":
                owned.append(cal_info)
            else:
                shared.append(cal_info)

        # Primary calendar
        if primary:
            lines.append("## 🏠 Primary Calendar")
            for cal in primary:
                lines.append(f"- **{cal['name']}**")
                lines.append(f"  - ID: `{cal['id']}`")
                lines.append(f"  - Access: {cal['access']}")
            lines.append("")

        # Owned calendars
        if owned:
            lines.append("## 👤 Your Calendars")
            for cal in owned:
                lines.append(f"- **{cal['name']}**")
                lines.append(f"  - ID: `{cal['id']}`")
                if cal["description"]:
                    lines.append(f"  - Description: {cal['description'][:100]}")
            lines.append("")

        # Shared calendars
        if shared:
            lines.append("## 🤝 Shared Calendars")
            for cal in shared:
                lines.append(f"- **{cal['name']}**")
                lines.append(f"  - ID: `{cal['id']}`")
                lines.append(f"  - Access: {cal['access']}")
                if cal["description"]:
                    lines.append(f"  - Description: {cal['description'][:100]}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("**To list events from a specific calendar:**")
        lines.append("```")
        lines.append(
            'google_calendar_list_events_from(calendar_id="calendar@group.calendar.google.com")'
        )
        lines.append("```")

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to list calendars: {e}"


# pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
async def _google_calendar_list_events_from_impl(
    calendar_id: str,
    days: int = 7,
    max_results: int = 25,
) -> str:
    """List upcoming events from a specific calendar."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)

        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        # Get calendar info first
        try:
            cal_info = service.calendars().get(calendarId=calendar_id).execute()
            cal_name = cal_info.get("summary", calendar_id)
        except Exception:  # pylint: disable=broad-exception-caught
            cal_name = calendar_id

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
                timeZone=TIMEZONE,
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return f"📅 No upcoming events in **{cal_name}** for the next {days} days."

        lines = [
            f"# 📅 Events from: {cal_name}",
            "📍 Times shown in Irish time (Europe/Dublin)",
            f"📆 Next {days} days",
            "",
        ]

        # Group events by day
        events_by_day: dict[str, list] = {}
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = event.get("summary", "No title")

            # Parse start time
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    dt = dt.astimezone(tz)
                    day_key = dt.strftime("%A, %B %d")
                    time_str = dt.strftime("%H:%M")
                else:
                    day_key = start
                    time_str = "All day"
            except (ValueError, TypeError):
                day_key = "Unknown"
                time_str = start

            # Check for Meet link
            meet_link = ""
            meet_url = ""
            if event.get("conferenceData", {}).get("entryPoints"):
                for entry in event["conferenceData"]["entryPoints"]:
                    if entry.get("entryPointType") == "video":
                        meet_link = " 📹"
                        meet_url = entry.get("uri", "")
                        break

            if day_key not in events_by_day:
                events_by_day[day_key] = []

            events_by_day[day_key].append(
                {
                    "time": time_str,
                    "summary": summary,
                    "meet_link": meet_link,
                    "meet_url": meet_url,
                    "event_id": event.get("id", ""),
                    "organizer": event.get("organizer", {}).get("email", ""),
                }
            )

        for day, day_events in events_by_day.items():
            lines.append(f"## {day}")
            for evt in day_events:
                lines.append(
                    f"- **{evt['time']}** - {evt['summary']}{evt['meet_link']}"
                )
                if evt["meet_url"]:
                    lines.append(f"  - Meet: {evt['meet_url']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        error_str = str(e)
        if "404" in error_str or "notFound" in error_str:
            # pylint: disable-next=line-too-long
            return f"❌ Calendar not found: `{calendar_id}`\n\nMake sure the calendar is shared with your account."
        return f"❌ Failed to list events: {e}"


# pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
async def _google_calendar_get_events_with_meet_impl(
    calendar_id: str = "primary",
    days: int = 1,
) -> str:
    """Get upcoming events that have Google Meet links."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)

        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
                timeZone=TIMEZONE,
            )
            .execute()
        )

        events = events_result.get("items", [])

        # Filter to only events with Meet links
        meet_events = []
        for event in events:
            meet_url = None
            if event.get("conferenceData", {}).get("entryPoints"):
                for entry in event["conferenceData"]["entryPoints"]:
                    if entry.get("entryPointType") == "video":
                        meet_url = entry.get("uri", "")
                        break

            if meet_url:
                start = event["start"].get("dateTime", event["start"].get("date"))
                end = event["end"].get("dateTime", event["end"].get("date"))

                try:
                    if "T" in start:
                        start_dt = datetime.fromisoformat(
                            start.replace("Z", "+00:00")
                        ).astimezone(tz)
                        end_dt = datetime.fromisoformat(
                            end.replace("Z", "+00:00")
                        ).astimezone(tz)
                    else:
                        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(
                            tzinfo=tz
                        )
                        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=tz)
                except (ValueError, TypeError):
                    continue

                meet_events.append(
                    {
                        "event_id": event.get("id", ""),
                        "title": event.get("summary", "No title"),
                        "start": start_dt,
                        "end": end_dt,
                        "meet_url": meet_url,
                        "organizer": event.get("organizer", {}).get("email", ""),
                        "attendees": [
                            a.get("email", "") for a in event.get("attendees", [])
                        ],
                        "description": event.get("description", ""),
                    }
                )

        if not meet_events:
            return f"📅 No meetings with Google Meet links in the next {days} day(s)."

        lines = [
            "# 📹 Meetings with Google Meet",
            f"📆 Next {days} day(s)",
            "",
        ]

        for evt in meet_events:
            lines.append(f"## {evt['title']}")
            lines.append(
                f"- **When:** {evt['start'].strftime('%A %H:%M')} - {evt['end'].strftime('%H:%M')}"
            )
            lines.append(f"- **Meet URL:** {evt['meet_url']}")
            lines.append(f"- **Organizer:** {evt['organizer']}")
            if evt["attendees"]:
                lines.append(f"- **Attendees:** {', '.join(evt['attendees'][:5])}")
                if len(evt["attendees"]) > 5:
                    lines.append(f"  ... and {len(evt['attendees']) - 5} more")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("**To have the bot join a meeting:**")
        lines.append("```")
        first_url = meet_events[0]["meet_url"]
        first_title = meet_events[0]["title"]
        lines.append(f'meet_bot_approve_meeting("{first_url}", "{first_title}")')
        lines.append("meet_bot_join_meeting()")
        lines.append("```")

        return "\n".join(lines)

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to get events: {e}"


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register Google Calendar tools with the MCP server.

    Args:
        server: FastMCP server instance to register tools with

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @registry.tool()
    async def google_calendar_check_mutual_availability(
        attendee_email: str,
        date: str = "",
        days_ahead: int = 5,
        duration_minutes: int = 30,
    ) -> str:
        """
        Check mutual availability between you and an attendee.

        Finds free slots within the allowed meeting window (15:00-19:00 Irish time).
        Checks both your calendar and the attendee's calendar.

        Args:
            attendee_email: Email of the person to meet with
            date: Specific date to check (YYYY-MM-DD), or empty to scan next few days
            days_ahead: Number of days to scan if no specific date (default: 5)
            duration_minutes: Required meeting duration (default: 30)

        Returns:
            Available time slots that work for both parties
        """
        return await _google_calendar_check_mutual_availability_impl(
            attendee_email, date, days_ahead, duration_minutes
        )

    @registry.tool()
    async def google_calendar_find_meeting(
        mr_id: str = "",
        jira_key: str = "",
        attendee_email: str = "",
        search_text: str = "",
    ) -> str:
        """
        Check if a meeting already exists for a specific MR, Jira issue, or topic.

        Use this before scheduling to avoid duplicate meeting requests.

        Args:
            mr_id: GitLab MR ID (e.g., "1445" or "!1445")
            jira_key: Jira issue key (e.g., "AAP-60034")
            attendee_email: Optional - also check if this person is invited
            search_text: Custom search text for the meeting title

        Returns:
            Meeting details if found, or confirmation none exists
        """
        return await _google_calendar_find_meeting_impl(
            mr_id, jira_key, attendee_email, search_text
        )

    @registry.tool()
    async def google_calendar_list_events(
        days: int = 7,
        max_results: int = 10,
    ) -> str:
        """
        List upcoming calendar events.

        Args:
            days: Number of days to look ahead (default: 7)
            max_results: Maximum number of events to return (default: 10)

        Returns:
            List of upcoming events (displayed in Irish time)
        """
        return await _google_calendar_list_events_impl(days, max_results)

    @registry.tool()
    async def google_calendar_quick_meeting(
        title: str,
        attendee_email: str,
        when: str = "auto",
        duration_minutes: int = 30,
    ) -> str:
        """
        Quickly schedule a meeting - finds the next available slot automatically.

        This is the easiest way to schedule a meeting. It will:
        1. Check both your and the attendee's calendar
        2. Find the next mutually free slot (15:00-19:00 Irish time)
        3. Create the meeting with a Google Meet link
        4. Send an invite to the attendee

        Args:
            title: Meeting title (e.g., "MR !1445 Race Condition Discussion")
            attendee_email: Email of the person to meet with (e.g., "bthomass@redhat.com")
            when: "auto" to find next available, or "YYYY-MM-DD HH:MM" for specific time
            duration_minutes: Meeting duration (default: 30)

        Returns:
            Meeting details and Google Meet link
        """
        return await _google_calendar_quick_meeting_impl(
            title, attendee_email, when, duration_minutes
        )

    @registry.tool()
    async def google_calendar_status() -> str:
        """
        Check Google Calendar integration status and configuration.

        Returns:
            Configuration status and setup instructions if needed
        """
        return await _google_calendar_status_impl()

    @registry.tool()
    async def google_calendar_list_calendars() -> str:
        """
        List all calendars accessible to your account.

        This includes:
        - Your primary calendar
        - Shared calendars (team calendars, project calendars)
        - Subscribed calendars

        Use this to find calendar IDs for monitoring or scheduling.

        Returns:
            List of calendars with their IDs and access levels
        """
        return await _google_calendar_list_calendars_impl()

    @registry.tool()
    async def google_calendar_list_events_from(
        calendar_id: str,
        days: int = 7,
        max_results: int = 25,
    ) -> str:
        """
        List upcoming events from a specific calendar.

        Use this to view events from shared calendars like team calendars,
        project calendars, or the Ansible Engineering calendar.

        Args:
            calendar_id: The calendar ID (email or calendar ID from google_calendar_list_calendars)
            days: Number of days to look ahead (default: 7)
            max_results: Maximum number of events to return (default: 25)

        Returns:
            List of upcoming events from the specified calendar
        """
        return await _google_calendar_list_events_from_impl(
            calendar_id, days, max_results
        )

    @registry.tool()
    async def google_calendar_get_events_with_meet(
        calendar_id: str = "primary",
        days: int = 1,
    ) -> str:
        """
        Get upcoming events that have Google Meet links.

        This is useful for finding meetings to join with the meet bot.

        Args:
            calendar_id: Calendar ID (default: "primary" for your main calendar)
            days: Number of days to look ahead (default: 1)

        Returns:
            List of events with Google Meet links
        """
        return await _google_calendar_get_events_with_meet_impl(calendar_id, days)

    return registry.count
