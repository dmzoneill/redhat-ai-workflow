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

# Setup project path for server imports (must be before server imports)
from tool_modules.common import (  # noqa: E402  # Sets up sys.path
    PROJECT_ROOT,
    get_google_calendar_settings,
)

__project_root__ = PROJECT_ROOT  # Module initialization

from tool_modules.aa_google_slides.src.tools_basic import (
    _build_google_service,
    _shared__try_oauth_flow,
)
from tool_modules.aa_google_slides.src.tools_basic import (
    _try_load_oauth_token as _slides_load_oauth_token,
)
from tool_modules.aa_google_slides.src.tools_basic import (
    _try_refresh_credentials as _slides_refresh_credentials,
)
from tool_modules.aa_google_slides.src.tools_basic import (
    _try_service_account as _slides_service_account,
)

logger = logging.getLogger(__name__)

# Shared Google config (single source of truth in tool_modules.common)
# Calendar-specific settings from config.json google_calendar section
_cal_settings = get_google_calendar_settings()
TIMEZONE = _cal_settings["timezone"]
MEETING_START_HOUR = _cal_settings["meeting_start_hour"]
MEETING_END_HOUR = _cal_settings["meeting_end_hour"]
DEFAULT_DURATION = 30  # minutes


def get_irish_time() -> datetime:
    """Get current time in Irish timezone."""
    return datetime.now(ZoneInfo(TIMEZONE))


def _try_load_oauth_token(credentials_cls, scopes):
    return _slides_load_oauth_token(credentials_cls, scopes)


_try_load_oauth_token.__doc__ = _slides_load_oauth_token.__doc__


def _try_refresh_credentials(creds, request_cls):
    return _slides_refresh_credentials(creds, request_cls)


_try_refresh_credentials.__doc__ = _slides_refresh_credentials.__doc__


def _try_service_account(service_account, scopes):
    return _slides_service_account(service_account, scopes)


_try_service_account.__doc__ = _slides_service_account.__doc__


def get_calendar_service():
    """Get authenticated Google Calendar service."""
    return _build_google_service("calendar", "v3", "calendar")


def _try_oauth_flow(scopes):
    return _shared__try_oauth_flow(scopes)


_try_oauth_flow.__doc__ = _shared__try_oauth_flow.__doc__


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
                busy_info[email] = {
                    "error": cal_info["errors"][0].get("reason", "unknown")
                }
            else:
                busy_info[email] = cal_info.get("busy", [])

        return busy_info
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e)}


def find_free_slots(  # pylint: disable=too-many-locals
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
    window_end = date.replace(
        hour=MEETING_END_HOUR, minute=0, second=0, microsecond=0, tzinfo=tz
    )

    # Collect all busy periods across all attendees
    all_busy = []
    for _email, periods in busy_periods.items():
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
            except Exception:  # pylint: disable=broad-exception-caught
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
                "duration_minutes": int(
                    (window_end - window_start).total_seconds() / 60
                ),
            }
        )

    return free_slots


def find_existing_meeting(  # pylint: disable=too-many-locals
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e)}


# ==================== HELPER FUNCTIONS ====================


def _parse_check_dates(
    date: str, days_ahead: int, tz: ZoneInfo, now: datetime
) -> list[datetime] | str:
    """Parse and return dates to check for availability."""
    if date:
        try:
            return [datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)]
        except ValueError:
            return f"❌ Invalid date format: {date}. Use YYYY-MM-DD."

    # Check next N business days
    check_dates = []
    current = now
    while len(check_dates) < days_ahead:
        current += timedelta(days=1)
        if current.weekday() < 5:
            check_dates.append(current)
    return check_dates


def _process_day_availability(
    service,
    check_date: datetime,
    calendars_to_check: list[str],
    attendee_email: str,
    duration_minutes: int,
) -> tuple[list[dict], str | None]:
    """Process availability for a single day. Returns (free_slots, error_message)."""
    day_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    busy_info = get_freebusy(service, calendars_to_check, day_start, day_end)

    attendee_error = None
    if (
        isinstance(busy_info.get(attendee_email), dict)
        and "error" in busy_info[attendee_email]
    ):
        attendee_error = busy_info[attendee_email]["error"]

    free_slots = find_free_slots(busy_info, check_date, duration_minutes)
    return free_slots, attendee_error


def _format_availability_output(
    lines: list[str],
    all_slots: list[dict],
    attendee_email: str,
) -> None:
    """Format the final availability output."""
    if not all_slots:
        lines.append(
            "❌ No mutual free slots found in the meeting window (15:00-19:00 Irish time)"
        )
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


# ==================== TOOL IMPLEMENTATIONS ====================


async def _google_calendar_check_mutual_availability_impl(  # pylint: disable=too-many-locals
    attendee_email: str,
    date: str = "",
    days_ahead: int = 5,
    duration_minutes: int = 30,
) -> str:
    """Check mutual availability between you and an attendee."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Determine dates to check
    check_dates = _parse_check_dates(date, days_ahead, tz, now)
    if isinstance(check_dates, str):
        return check_dates

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
    except Exception:  # pylint: disable=broad-exception-caught
        my_email = "primary"

    calendars_to_check = [my_email, attendee_email]
    all_slots = []

    for check_date in check_dates:
        free_slots, attendee_error = _process_day_availability(
            service, check_date, calendars_to_check, attendee_email, duration_minutes
        )

        if free_slots:
            day_name = check_date.strftime("%A %Y-%m-%d")
            lines.append(f"## {day_name}")

            if attendee_error:
                lines.append(
                    f"⚠️ Could not check {attendee_email}'s calendar: {attendee_error}"
                )
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

    _format_availability_output(lines, all_slots, attendee_email)
    return "\n".join(lines)


async def _google_calendar_find_meeting_impl(
    mr_id: str = "",
    jira_key: str = "",
    attendee_email: str = "",
    search_text: str = "",
) -> str:
    """Check if a meeting already exists for a specific MR, Jira issue, or topic."""
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


async def _google_calendar_list_events_impl(  # pylint: disable=too-many-locals
    days: int = 7,
    max_results: int = 10,
) -> str:
    """List upcoming calendar events."""
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to list events: {e}"


async def _google_calendar_quick_meeting_impl(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    title: str,
    attendee_email: str,
    when: str = "auto",
    duration_minutes: int = 30,
) -> str:
    """Quickly schedule a meeting - finds the next available slot automatically."""
    if when.lower() == "auto":
        # Auto-find next slot
        return await _google_calendar_schedule_meeting_impl(
            title=title,
            attendee_email=attendee_email,
            start_time="",
            duration_minutes=duration_minutes,
            auto_find_slot=True,
        )
    # Parse natural language or specific time
    import re  # pylint: disable=import-outside-toplevel

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    when_lower = when.lower()

    # Check for ISO format first (e.g., "2026-02-10T15:00:00" or "2026-02-10 15:00")
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}):(\d{2})", when)
    if iso_match:
        # Full ISO datetime - parse directly
        try:
            if "T" in when:
                start_time = datetime.fromisoformat(when.replace("Z", "+00:00"))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=tz)
                else:
                    start_time = start_time.astimezone(tz)
            else:
                start_time = datetime.strptime(when[:16], "%Y-%m-%d %H:%M").replace(
                    tzinfo=tz
                )

            return await _google_calendar_schedule_meeting_impl(
                title=title,
                attendee_email=attendee_email,
                start_time=start_time.isoformat(),
                duration_minutes=duration_minutes,
                auto_find_slot=False,
            )
        except ValueError as exc:
            logger.debug("Invalid value encountered: %s", exc)

    # Extract time component - look for time after T, space, or "at"
    # Patterns: "15:00", "3pm", "3:30pm", "at 15:00"
    time_match = re.search(
        r"(?:T|\s|at\s*)(\d{1,2})[:\.]?(\d{2})?\s*(am|pm)?", when, re.IGNORECASE
    )
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        if ampm:
            if ampm.lower() == "pm" and hour < 12:
                hour += 12
            elif ampm.lower() == "am" and hour == 12:
                hour = 0
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
        # Date provided (YYYY-MM-DD) without full ISO time
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

    return await _google_calendar_schedule_meeting_impl(
        title=title,
        attendee_email=attendee_email,
        start_time=start_time.isoformat(),
        duration_minutes=duration_minutes,
        auto_find_slot=False,
    )


def _check_duplicate_meeting(
    service, title: str, attendee_email: str, skip_duplicate_check: bool
) -> str | None:
    """Check if a meeting for this topic already exists."""
    if skip_duplicate_check:
        return None

    import re  # pylint: disable=import-outside-toplevel

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
                "📅 **Meeting Already Scheduled**\n"
                "\n"
                "A meeting for this topic already exists:\n"
                "\n"
                f"**Title:** {existing['title']}\n"
                f"**When:** {existing['when']} Irish time\n"
                f"**Link:** {existing['link']}\n"
                "\n"
                "⚠️ No new meeting created to avoid duplicate invites.\n"
                "\n"
                "If you really need a new meeting, use `skip_duplicate_check=True`."
            )
    return None


def _find_next_available_slot(service, now, attendee_email: str, duration_minutes: int):
    """Find next available meeting slot."""
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
    except Exception:  # pylint: disable=broad-exception-caught
        my_email = "primary"

    calendars_to_check = [my_email, attendee_email]

    # Find first available slot
    for check_date in check_dates:
        day_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        busy_info = get_freebusy(service, calendars_to_check, day_start, day_end)
        free_slots = find_free_slots(busy_info, check_date, duration_minutes)

        if free_slots:
            return free_slots[0]["start"]

    return None


def _parse_and_validate_start_time(
    start_time: str, now, duration_minutes: int
):  # pylint: disable=unused-argument
    """Parse start time and validate it's within allowed window."""
    tz = ZoneInfo(TIMEZONE)

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
            None,
            f"❌ Invalid start_time format: {start_time}. Use ISO format or 'YYYY-MM-DD HH:MM'.",
        )

    # Validate time is within allowed window
    if start_dt.hour < MEETING_START_HOUR or start_dt.hour >= MEETING_END_HOUR:
        return None, (
            f"❌ Meeting time {start_dt.strftime('%H:%M')} is outside allowed window.\n"
            f"📍 Meetings must be between {MEETING_START_HOUR}:00 "
            f"and {MEETING_END_HOUR}:00 Irish time.\n\n"
            "Use `google_calendar_check_mutual_availability` to find valid slots."
        )

    # Check if end time exceeds window
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    if end_dt.hour > MEETING_END_HOUR or (
        end_dt.hour == MEETING_END_HOUR and end_dt.minute > 0
    ):
        return None, (
            f"❌ Meeting would end at {end_dt.strftime('%H:%M')}, "
            f"past the {MEETING_END_HOUR}:00 cutoff.\n"
            "Consider a shorter duration or earlier start time."
        )

    # Validate weekend
    if start_dt.weekday() >= 5:
        return None, "❌ Cannot schedule meetings on weekends. Please choose a weekday."

    return start_dt, None


async def _google_calendar_schedule_meeting_impl(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,too-many-return-statements
    title: str,
    attendee_email: str,
    start_time: str = "",
    duration_minutes: int = 30,
    description: str = "",
    auto_find_slot: bool = True,
    skip_duplicate_check: bool = False,
) -> str:
    """Schedule a meeting with an attendee, enforcing Irish time constraints."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Check for existing meeting before creating a new one
    duplicate_msg = _check_duplicate_meeting(
        service, title, attendee_email, skip_duplicate_check
    )
    if duplicate_msg:
        return duplicate_msg

    # Determine start time
    if not start_time and auto_find_slot:
        # Find next available slot
        start_dt = _find_next_available_slot(
            service, now, attendee_email, duration_minutes
        )
        if not start_dt:
            return (
                "❌ No mutual free slots found in the next 5 business days.\n"
                "📍 Meeting window: 15:00-19:00 Irish time\n"
                f"⏱️ Duration needed: {duration_minutes} minutes\n\n"
                "Use `google_calendar_check_mutual_availability` to see detailed availability."
            )
    else:
        # Parse and validate provided start time
        start_dt, error_msg = _parse_and_validate_start_time(
            start_time, now, duration_minutes
        )
        if error_msg:
            return error_msg

    # Calculate end time
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    try:
        # Build event
        event = {
            "summary": title,
            "description": description
            or "Meeting scheduled via AI Workflow assistant.",
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        return f"❌ Failed to create event: {e}"
