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
2. Download credentials.json to ~/.config/google-calendar/credentials.json
3. Run the server once to complete OAuth flow and save token.json
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import load_config

# Initialize FastMCP
mcp = FastMCP("aa-google-calendar")


def _get_google_calendar_config_dir() -> Path:
    """Get Google Calendar config directory from config.json or default."""
    config = load_config()
    paths_cfg = config.get("paths", {})
    gc_config = paths_cfg.get("google_calendar_config")
    if gc_config:
        return Path(os.path.expanduser(gc_config))
    return Path.home() / ".config" / "google-calendar"


# Config paths - use config.json paths section if available
CONFIG_DIR = _get_google_calendar_config_dir()
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"
SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"

# Scopes required for calendar access (includes freebusy for availability)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# CONSTRAINTS
TIMEZONE = "Europe/Dublin"
MEETING_START_HOUR = 15  # 3pm Irish time
MEETING_END_HOUR = 19  # 7pm Irish time
DEFAULT_DURATION = 30  # minutes


def get_irish_time() -> datetime:
    """Get current time in Irish timezone."""
    return datetime.now(ZoneInfo(TIMEZONE))


def get_calendar_service():
    """
    Get authenticated Google Calendar service.

    Tries OAuth2 first, then service account.
    Returns None if not configured.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return (
            None,
            "Google API libraries not installed. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib",
        )

    creds = None

    # Try token file first (OAuth2)
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception:
            pass

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        except Exception:
            creds = None

    # Try service account
    if not creds and SERVICE_ACCOUNT_FILE.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
            )
        except Exception:
            pass

    # Need to authenticate
    if not creds or not creds.valid:
        if CREDENTIALS_FILE.exists():
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow

                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
                # Save credentials for next run
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                return None, f"OAuth flow failed: {e}"
        else:
            return None, f"No credentials found. Add credentials.json to {CONFIG_DIR}"

    try:
        service = build("calendar", "v3", credentials=creds)
        return service, None
    except Exception as e:
        return None, f"Failed to build calendar service: {e}"


def get_freebusy(service, calendars: list[str], start: datetime, end: datetime) -> dict:
    """
    Query freebusy information for multiple calendars.

    Args:
        service: Google Calendar service
        calendars: List of email addresses to check
        start: Start of time range
        end: End of time range

    Returns:
        Dict mapping email -> list of busy periods
    """
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": TIMEZONE,
        "items": [{"id": email} for email in calendars],
    }

    try:
        result = service.freebusy().query(body=body).execute()
        busy_info = {}

        for email in calendars:
            cal_info = result.get("calendars", {}).get(email, {})

            # Check for errors (user not in domain or calendar not shared)
            if cal_info.get("errors"):
                busy_info[email] = {"error": cal_info["errors"][0].get("reason", "unknown")}
            else:
                busy_info[email] = cal_info.get("busy", [])

        return busy_info
    except Exception as e:
        return {"error": str(e)}


def find_free_slots(
    busy_periods: dict,
    date: datetime,
    duration_minutes: int = 30,
) -> list[dict]:
    """
    Find free slots within the allowed meeting window (15:00-19:00 Irish time).

    Args:
        busy_periods: Dict from get_freebusy (email -> busy list)
        date: The date to find slots for
        duration_minutes: Required meeting duration

    Returns:
        List of free slot dicts with start/end times
    """
    tz = ZoneInfo(TIMEZONE)

    # Set up the meeting window for this date
    window_start = date.replace(
        hour=MEETING_START_HOUR, minute=0, second=0, microsecond=0, tzinfo=tz
    )
    window_end = date.replace(hour=MEETING_END_HOUR, minute=0, second=0, microsecond=0, tzinfo=tz)

    # Collect all busy periods across all attendees
    all_busy = []
    for email, periods in busy_periods.items():
        if isinstance(periods, dict) and "error" in periods:
            continue  # Skip calendars we couldn't access

        for period in periods:
            try:
                start = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(period["end"].replace("Z", "+00:00"))
                # Convert to Irish time
                start = start.astimezone(tz)
                end = end.astimezone(tz)
                all_busy.append((start, end))
            except Exception:
                continue

    # Sort busy periods by start time
    all_busy.sort(key=lambda x: x[0])

    # Find free slots
    free_slots = []
    current = window_start

    for busy_start, busy_end in all_busy:
        # If busy period is outside our window, skip
        if busy_end <= window_start or busy_start >= window_end:
            continue

        # Clip busy period to our window
        busy_start = max(busy_start, window_start)
        busy_end = min(busy_end, window_end)

        # If there's a gap before this busy period, that's a free slot
        if current < busy_start:
            gap_minutes = (busy_start - current).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                free_slots.append(
                    {
                        "start": current,
                        "end": busy_start,
                        "duration_minutes": int(gap_minutes),
                    }
                )

        # Move current pointer past this busy period
        current = max(current, busy_end)

    # Check if there's time left at the end of the window
    if current < window_end:
        gap_minutes = (window_end - current).total_seconds() / 60
        if gap_minutes >= duration_minutes:
            free_slots.append(
                {
                    "start": current,
                    "end": window_end,
                    "duration_minutes": int(gap_minutes),
                }
            )

    # If no busy periods, the whole window is free
    if not all_busy and not free_slots:
        free_slots.append(
            {
                "start": window_start,
                "end": window_end,
                "duration_minutes": int((window_end - window_start).total_seconds() / 60),
            }
        )

    return free_slots


def find_existing_meeting(
    service,
    search_terms: list[str],
    attendee_email: str = "",
    days_back: int = 30,
    days_ahead: int = 30,
) -> dict | None:
    """
    Search for an existing meeting matching the criteria.

    Args:
        service: Google Calendar service
        search_terms: List of terms to search for in event title (e.g., ["!1445", "MR 1445"])
        attendee_email: Optional - also check if this attendee is invited
        days_back: How many days in the past to search
        days_ahead: How many days in the future to search

    Returns:
        Matching event dict or None
    """
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    try:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        for event in events:
            summary = event.get("summary", "").lower()

            # Check if any search term is in the title
            matches_term = any(term.lower() in summary for term in search_terms)

            if not matches_term:
                continue

            # If attendee specified, check if they're invited
            if attendee_email:
                attendees = event.get("attendees", [])
                attendee_emails = [a.get("email", "").lower() for a in attendees]
                if attendee_email.lower() not in attendee_emails:
                    continue

            # Found a matching meeting
            start = event["start"].get("dateTime", event["start"].get("date"))
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    dt = dt.astimezone(tz)
                    when = dt.strftime("%A %Y-%m-%d %H:%M")
                else:
                    when = start
            except (ValueError, TypeError, KeyError):
                when = start

            return {
                "exists": True,
                "event_id": event.get("id"),
                "title": event.get("summary"),
                "when": when,
                "link": event.get("htmlLink"),
                "status": event.get("status"),
            }

        return None

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
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
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    # Build search terms
    search_terms = []

    if mr_id:
        mr_num = mr_id.replace("!", "").replace("MR", "").strip()
        search_terms.extend(
            [
                f"!{mr_num}",
                f"MR {mr_num}",
                f"MR!{mr_num}",
                f"MR-{mr_num}",
            ]
        )

    if jira_key:
        search_terms.append(jira_key.upper())

    if search_text:
        search_terms.append(search_text)

    if not search_terms:
        return "❌ Please provide at least one of: mr_id, jira_key, or search_text"

    result = find_existing_meeting(service, search_terms, attendee_email)

    if result is None:
        lines = [
            "✅ **No existing meeting found**",
            "",
            f"Search terms: {', '.join(search_terms)}",
        ]
        if attendee_email:
            lines.append(f"Attendee: {attendee_email}")
        lines.append("")
        lines.append("You can schedule a new meeting.")
        return "\n".join(lines)

    if "error" in result:
        return f"❌ Error searching calendar: {result['error']}"

    lines = [
        "📅 **Meeting Already Exists**",
        "",
        f"**Title:** {result['title']}",
        f"**When:** {result['when']} Irish time",
        f"**Status:** {result['status']}",
        f"**Link:** {result['link']}",
        "",
        "⚠️ A meeting for this topic already exists. No need to create another.",
    ]

    return "\n".join(lines)


@mcp.tool()
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
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Determine dates to check
    if date:
        try:
            check_dates = [datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)]
        except ValueError:
            return f"❌ Invalid date format: {date}. Use YYYY-MM-DD."
    else:
        # Check next N business days
        check_dates = []
        current = now
        while len(check_dates) < days_ahead:
            current += timedelta(days=1)
            # Skip weekends
            if current.weekday() < 5:
                check_dates.append(current)

    lines = [
        f"# Mutual Availability with {attendee_email}",
        "",
        "📍 **Timezone:** Irish time (Europe/Dublin)",
        f"⏰ **Meeting window:** {MEETING_START_HOUR}:00 - {MEETING_END_HOUR}:00",
        f"⏱️ **Duration needed:** {duration_minutes} minutes",
        "",
    ]

    # Get my email
    try:
        profile = service.calendars().get(calendarId="primary").execute()
        my_email = profile.get("id", "primary")
    except Exception:
        my_email = "primary"

    calendars_to_check = [my_email, attendee_email]
    all_slots = []

    for check_date in check_dates:
        day_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Query freebusy for both calendars
        busy_info = get_freebusy(service, calendars_to_check, day_start, day_end)

        # Check for errors
        attendee_error = None
        if isinstance(busy_info.get(attendee_email), dict) and "error" in busy_info[attendee_email]:
            attendee_error = busy_info[attendee_email]["error"]

        # Find free slots
        free_slots = find_free_slots(busy_info, check_date, duration_minutes)

        if free_slots:
            day_name = check_date.strftime("%A %Y-%m-%d")
            lines.append(f"## {day_name}")

            if attendee_error:
                lines.append(f"⚠️ Could not check {attendee_email}'s calendar: {attendee_error}")
                lines.append("   (Showing your free slots only)")

            for slot in free_slots:
                start_str = slot["start"].strftime("%H:%M")
                end_str = slot["end"].strftime("%H:%M")
                lines.append(
                    f"✅ **{start_str} - {end_str}** ({slot['duration_minutes']} min available)"
                )
                all_slots.append(
                    {
                        "date": check_date.strftime("%Y-%m-%d"),
                        "start": slot["start"].isoformat(),
                        "start_display": f"{check_date.strftime('%A')} {start_str}",
                    }
                )

            lines.append("")

    if not all_slots:
        lines.append("❌ No mutual free slots found in the meeting window (15:00-19:00 Irish time)")
        lines.append("")
        lines.append("Consider:")
        lines.append("- Checking more days ahead")
        lines.append("- Using a shorter duration")
        lines.append("- Scheduling outside the preferred window")
    else:
        lines.append("---")
        lines.append("")
        lines.append("**To schedule the first available slot:**")
        first_slot = all_slots[0]
        lines.append("```")
        lines.append("google_calendar_schedule_meeting(")
        lines.append('    title="Your Meeting Title",')
        lines.append(f'    attendee_email="{attendee_email}",')
        lines.append(f'    start_time="{first_slot["start"]}"')
        lines.append(")")
        lines.append("```")

    return "\n".join(lines)


@mcp.tool()
async def google_calendar_schedule_meeting(
    title: str,
    attendee_email: str,
    start_time: str = "",
    duration_minutes: int = 30,
    description: str = "",
    auto_find_slot: bool = True,
    skip_duplicate_check: bool = False,
) -> str:
    """
    Schedule a meeting with an attendee, enforcing Irish time constraints.

    AUTOMATICALLY checks if a meeting already exists for this topic before creating.

    CONSTRAINTS:
    - All times in Irish time (Europe/Dublin)
    - Meetings only between 15:00-19:00 Irish time
    - Checks attendee availability before scheduling
    - Won't create duplicate meetings for the same topic

    Args:
        title: Meeting title (e.g., "MR !1445 Race Condition Discussion")
        attendee_email: Email of the person to meet with
        start_time: Start time in ISO format, or empty to auto-find a slot
        duration_minutes: Duration in minutes (default: 30)
        description: Meeting agenda/description
        auto_find_slot: If start_time not specified, find next available slot (default: True)
        skip_duplicate_check: Skip the existing meeting check (default: False)

    Returns:
        Event details including Google Meet link
    """
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Check for existing meeting before creating a new one
    if not skip_duplicate_check:
        import re

        # Extract MR ID or Jira key from title
        search_terms = []

        # Look for MR patterns: !1445, MR 1445, MR-1445
        mr_match = re.search(r"[!#]?(\d{3,5})", title)
        if mr_match:
            mr_num = mr_match.group(1)
            search_terms.extend([f"!{mr_num}", f"MR {mr_num}", f"MR-{mr_num}"])

        # Look for Jira patterns: AAP-12345
        jira_match = re.search(r"(AAP-\d+)", title, re.IGNORECASE)
        if jira_match:
            search_terms.append(jira_match.group(1).upper())

        # If we have search terms, check for existing meeting
        if search_terms:
            existing = find_existing_meeting(service, search_terms, attendee_email)

            if existing and "error" not in existing:
                return (
                    f"📅 **Meeting Already Scheduled**\n"
                    f"\n"
                    f"A meeting for this topic already exists:\n"
                    f"\n"
                    f"**Title:** {existing['title']}\n"
                    f"**When:** {existing['when']} Irish time\n"
                    f"**Link:** {existing['link']}\n"
                    f"\n"
                    f"⚠️ No new meeting created to avoid duplicate invites.\n"
                    f"\n"
                    f"If you really need a new meeting, use `skip_duplicate_check=True`."
                )

    # If no start time, find next available slot
    if not start_time and auto_find_slot:
        # Check next 5 business days
        check_dates = []
        current = now
        for _ in range(7):
            current += timedelta(days=1)
            if current.weekday() < 5:  # Skip weekends
                check_dates.append(current)
            if len(check_dates) >= 5:
                break

        # Get my email
        try:
            profile = service.calendars().get(calendarId="primary").execute()
            my_email = profile.get("id", "primary")
        except Exception:
            my_email = "primary"

        calendars_to_check = [my_email, attendee_email]

        # Find first available slot
        for check_date in check_dates:
            day_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            busy_info = get_freebusy(service, calendars_to_check, day_start, day_end)
            free_slots = find_free_slots(busy_info, check_date, duration_minutes)

            if free_slots:
                start_dt = free_slots[0]["start"]
                break
        else:
            return (
                f"❌ No mutual free slots found in the next 5 business days.\n"
                f"📍 Meeting window: 15:00-19:00 Irish time\n"
                f"⏱️ Duration needed: {duration_minutes} minutes\n\n"
                f"Use `google_calendar_check_mutual_availability` to see detailed availability."
            )
    else:
        # Parse provided start time
        try:
            if "T" in start_time:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")

            # Ensure it has timezone
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tz)
            else:
                start_dt = start_dt.astimezone(tz)

        except ValueError:
            return (
                f"❌ Invalid start_time format: {start_time}. Use ISO format or 'YYYY-MM-DD HH:MM'."
            )

    # Validate time is within allowed window
    if start_dt.hour < MEETING_START_HOUR or start_dt.hour >= MEETING_END_HOUR:
        return (
            f"❌ Meeting time {start_dt.strftime('%H:%M')} is outside allowed window.\n"
            f"📍 Meetings must be between {MEETING_START_HOUR}:00 and {MEETING_END_HOUR}:00 Irish time.\n\n"
            f"Use `google_calendar_check_mutual_availability` to find valid slots."
        )

    # Check if end time exceeds window
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    if end_dt.hour > MEETING_END_HOUR or (end_dt.hour == MEETING_END_HOUR and end_dt.minute > 0):
        return (
            f"❌ Meeting would end at {end_dt.strftime('%H:%M')}, past the {MEETING_END_HOUR}:00 cutoff.\n"
            f"Consider a shorter duration or earlier start time."
        )

    # Validate weekend
    if start_dt.weekday() >= 5:
        return "❌ Cannot schedule meetings on weekends. Please choose a weekday."

    try:
        # Build event
        event = {
            "summary": title,
            "description": description or "Meeting scheduled via AI Workflow assistant.",
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": TIMEZONE,
            },
            "attendees": [
                {"email": attendee_email},
            ],
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meet-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        # Create event
        created_event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event,
                conferenceDataVersion=1,
                sendUpdates="all",  # Send invites to attendees
            )
            .execute()
        )

        # Extract Meet link
        meet_link = ""
        if created_event.get("conferenceData", {}).get("entryPoints"):
            for entry in created_event["conferenceData"]["entryPoints"]:
                if entry.get("entryPointType") == "video":
                    meet_link = entry.get("uri", "")
                    break

        event_link = created_event.get("htmlLink", "")

        result = [
            "✅ **Meeting Scheduled**",
            "",
            f"**Title:** {title}",
            f"**When:** {start_dt.strftime('%A %Y-%m-%d %H:%M')} Irish time",
            f"**Duration:** {duration_minutes} minutes",
            f"**Attendee:** {attendee_email} (invite sent ✉️)",
            "",
            f"**Calendar Link:** {event_link}",
        ]

        if meet_link:
            result.append(f"**Google Meet:** {meet_link}")

        return "\n".join(result)

    except Exception as e:
        return f"❌ Failed to create event: {e}"


@mcp.tool()
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
    if when.lower() == "auto":
        # Auto-find next slot
        return await google_calendar_schedule_meeting(
            title=title,
            attendee_email=attendee_email,
            start_time="",
            duration_minutes=duration_minutes,
            auto_find_slot=True,
        )
    else:
        # Parse natural language or specific time
        import re

        tz = ZoneInfo(TIMEZONE)
        now = datetime.now(tz)

        when_lower = when.lower()

        # Extract time component
        time_match = re.search(r"(\d{1,2})[:\.]?(\d{2})?", when)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
        else:
            hour, minute = 15, 0  # Default to 3pm if no time specified

        # Parse date component
        if "tomorrow" in when_lower:
            target_date = now + timedelta(days=1)
        elif "today" in when_lower:
            target_date = now
        elif "monday" in when_lower:
            days_ahead = (0 - now.weekday()) % 7 or 7
            target_date = now + timedelta(days=days_ahead)
        elif "tuesday" in when_lower:
            days_ahead = (1 - now.weekday()) % 7 or 7
            target_date = now + timedelta(days=days_ahead)
        elif "wednesday" in when_lower:
            days_ahead = (2 - now.weekday()) % 7 or 7
            target_date = now + timedelta(days=days_ahead)
        elif "thursday" in when_lower:
            days_ahead = (3 - now.weekday()) % 7 or 7
            target_date = now + timedelta(days=days_ahead)
        elif "friday" in when_lower:
            days_ahead = (4 - now.weekday()) % 7 or 7
            target_date = now + timedelta(days=days_ahead)
        elif re.match(r"\d{4}-\d{2}-\d{2}", when):
            # Full date provided
            try:
                target_date = datetime.strptime(when[:10], "%Y-%m-%d").replace(tzinfo=tz)
            except ValueError:
                target_date = now + timedelta(days=1)
        else:
            target_date = now + timedelta(days=1)  # Default to tomorrow

        # Build datetime
        start_time = target_date.replace(
            hour=hour, minute=minute, second=0, microsecond=0, tzinfo=tz
        )

        return await google_calendar_schedule_meeting(
            title=title,
            attendee_email=attendee_email,
            start_time=start_time.isoformat(),
            duration_minutes=duration_minutes,
            auto_find_slot=False,
        )


@mcp.tool()
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
                calendarId="primary",
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
            return f"📅 No upcoming events in the next {days} days."

        lines = [
            f"📅 **Upcoming Events** (next {days} days)",
            "📍 Times shown in Irish time (Europe/Dublin)",
            "",
        ]

        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = event.get("summary", "No title")

            # Parse and format start time in Irish timezone
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    dt = dt.astimezone(tz)
                    time_str = dt.strftime("%a %Y-%m-%d %H:%M")
                else:
                    time_str = start
            except (ValueError, TypeError, KeyError):
                time_str = start

            # Check for Meet link
            meet_link = ""
            if event.get("conferenceData", {}).get("entryPoints"):
                for entry in event["conferenceData"]["entryPoints"]:
                    if entry.get("entryPointType") == "video":
                        meet_link = " 📹"
                        break

            lines.append(f"- **{time_str}** - {summary}{meet_link}")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list events: {e}"


@mcp.tool()
async def google_calendar_status() -> str:
    """
    Check Google Calendar integration status and configuration.

    Returns:
        Configuration status and setup instructions if needed
    """
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
        except Exception as e:
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


def register_tools(server: FastMCP):
    """Register all Google Calendar tools with a FastMCP server."""
    server.add_tool(google_calendar_schedule_meeting)
    server.add_tool(google_calendar_quick_meeting)
    server.add_tool(google_calendar_check_mutual_availability)
    server.add_tool(google_calendar_find_meeting)
    server.add_tool(google_calendar_list_events)
    server.add_tool(google_calendar_status)


if __name__ == "__main__":
    mcp.run()
