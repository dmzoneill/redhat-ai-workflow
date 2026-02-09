"""Google Calendar Tools - Extra/advanced tools.

This module contains additional calendar tools that are not part of the basic set.
Includes tools for declining meetings, bulk operations, and PTO sync.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Import shared utilities from basic tools
from server.tool_registry import ToolRegistry
from tool_modules.aa_google_calendar.src.tools_basic import (
    TIMEZONE,
    get_calendar_service,
)


async def _google_calendar_decline_event_impl(
    event_id: str,
    message: str = "Unable to attend",
    send_updates: bool = True,
) -> str:
    """Decline a calendar event."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        # Get the event first to verify it exists
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        if not event:
            return f"❌ Event not found: {event_id}"

        title = event.get("summary", "Untitled")

        # Get my email
        try:
            profile = service.calendars().get(calendarId="primary").execute()
            my_email = profile.get("id", "")
        except Exception:
            my_email = ""

        # Find my attendee entry and update response status
        attendees = event.get("attendees", [])
        found_self = False

        for attendee in attendees:
            if (
                attendee.get("self", False)
                or attendee.get("email", "").lower() == my_email.lower()
            ):
                attendee["responseStatus"] = "declined"
                if message:
                    attendee["comment"] = message
                found_self = True
                break

        if not found_self:
            # If we're not in attendees, we might be the organizer
            # Can't decline our own meeting
            if event.get("organizer", {}).get("self", False):
                return (
                    f"❌ Cannot decline **{title}** - you are the organizer.\n\n"
                    f"To cancel this meeting, use `google_calendar_cancel_event(event_id='{event_id}')`"
                )
            return f"❌ Could not find your attendee entry for event: {title}"

        # Update the event
        service.events().patch(
            calendarId="primary",
            eventId=event_id,
            body={"attendees": attendees},
            sendUpdates="all" if send_updates else "none",
        ).execute()

        # Get event time for display
        start = event["start"].get("dateTime", event["start"].get("date"))
        try:
            tz = ZoneInfo(TIMEZONE)
            if "T" in start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz)
                when = dt.strftime("%A %Y-%m-%d %H:%M")
            else:
                when = start
        except (ValueError, TypeError):
            when = start

        lines = [
            "✅ **Meeting Declined**",
            "",
            f"**Title:** {title}",
            f"**When:** {when}",
            f"**Message:** {message}",
        ]

        if send_updates:
            lines.append("")
            lines.append("📧 Organizer has been notified of your decline.")

        return "\n".join(lines)

    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "notFound" in error_str:
            return f"❌ Event not found: {event_id}"
        return f"❌ Failed to decline event: {e}"


async def _google_calendar_decline_meetings_on_date_impl(
    date: str,
    message: str = "On PTO - unable to attend",
    dry_run: bool = True,
    skip_all_day: bool = False,
    skip_organizer_self: bool = True,
) -> str:
    """Decline all meetings on a specific date."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        tz = ZoneInfo(TIMEZONE)

        # Parse the date
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=tz)
        except ValueError:
            return f"❌ Invalid date format: {date}. Use YYYY-MM-DD."

        # Get events for that day
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                timeZone=TIMEZONE,
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return f"📅 No events found on {date}"

        # Get my email for organizer check
        try:
            profile = service.calendars().get(calendarId="primary").execute()
            my_email = profile.get("id", "").lower()
        except Exception:
            my_email = ""

        to_decline = []
        skipped = []

        for event in events:
            event_id = event.get("id", "")
            title = event.get("summary", "Untitled")
            start = event["start"].get("dateTime", event["start"].get("date"))

            # Check if all-day event
            is_all_day = "T" not in start
            if skip_all_day and is_all_day:
                skipped.append({"title": title, "reason": "all-day event"})
                continue

            # Check if I'm the organizer
            is_organizer = event.get("organizer", {}).get("self", False)
            if not is_organizer and my_email:
                organizer_email = event.get("organizer", {}).get("email", "").lower()
                is_organizer = organizer_email == my_email

            if skip_organizer_self and is_organizer:
                skipped.append({"title": title, "reason": "you are organizer"})
                continue

            # Check my response status
            attendees = event.get("attendees", [])
            my_status = None
            for attendee in attendees:
                if (
                    attendee.get("self", False)
                    or attendee.get("email", "").lower() == my_email
                ):
                    my_status = attendee.get("responseStatus", "needsAction")
                    break

            # Skip if already declined
            if my_status == "declined":
                skipped.append({"title": title, "reason": "already declined"})
                continue

            # Format time for display
            try:
                if "T" in start:
                    dt = datetime.fromisoformat(
                        start.replace("Z", "+00:00")
                    ).astimezone(tz)
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "All day"
            except (ValueError, TypeError):
                time_str = start

            to_decline.append(
                {
                    "event_id": event_id,
                    "title": title,
                    "time": time_str,
                    "current_status": my_status,
                }
            )

        # Build output
        lines = [
            f"# 📅 Meetings on {date}",
            "",
        ]

        if dry_run:
            lines.append("## 🧪 Dry Run Mode")
            lines.append("")

        if to_decline:
            lines.append(
                f"## {'Would Decline' if dry_run else 'Declining'} ({len(to_decline)})"
            )
            lines.append("")
            lines.append("| Time | Meeting |")
            lines.append("|------|---------|")
            for m in to_decline:
                lines.append(f"| {m['time']} | {m['title']} |")
            lines.append("")

            if not dry_run:
                # Actually decline the meetings
                declined = []
                failed = []

                for m in to_decline:
                    result = await _google_calendar_decline_event_impl(
                        event_id=m["event_id"],
                        message=message,
                        send_updates=True,
                    )
                    if "✅" in result:
                        declined.append(m["title"])
                    else:
                        failed.append({"title": m["title"], "error": result})

                if declined:
                    lines.append(f"### ✅ Successfully Declined ({len(declined)})")
                    for title in declined:
                        lines.append(f"- {title}")
                    lines.append("")

                if failed:
                    lines.append(f"### ❌ Failed to Decline ({len(failed)})")
                    for f in failed:
                        lines.append(f"- {f['title']}: {f['error']}")
                    lines.append("")
        else:
            lines.append("✅ No meetings to decline on this date")
            lines.append("")

        if skipped:
            lines.append(f"## ⏭️ Skipped ({len(skipped)})")
            lines.append("")
            lines.append("| Meeting | Reason |")
            lines.append("|---------|--------|")
            for s in skipped:
                lines.append(f"| {s['title']} | {s['reason']} |")
            lines.append("")

        if dry_run and to_decline:
            lines.append("---")
            lines.append("")
            lines.append("**To actually decline these meetings:**")
            lines.append("```")
            lines.append(
                f"google_calendar_decline_meetings_on_date(date='{date}', dry_run=False)"
            )
            lines.append("```")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to process events: {e}"


async def _google_calendar_cancel_event_impl(
    event_id: str,
    send_updates: bool = True,
    message: str = "",
) -> str:
    """Cancel/delete a calendar event you organized."""
    service, error = get_calendar_service()

    if error:
        return f"❌ {error}"

    if not service:
        return "❌ Google Calendar service not available"

    try:
        # Get the event first
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        if not event:
            return f"❌ Event not found: {event_id}"

        title = event.get("summary", "Untitled")

        # Verify we're the organizer
        if not event.get("organizer", {}).get("self", False):
            return (
                f"❌ Cannot cancel **{title}** - you are not the organizer.\n\n"
                f"To decline this meeting, use `google_calendar_decline_event(event_id='{event_id}')`"
            )

        # Delete the event
        service.events().delete(
            calendarId="primary",
            eventId=event_id,
            sendUpdates="all" if send_updates else "none",
        ).execute()

        lines = [
            "✅ **Meeting Cancelled**",
            "",
            f"**Title:** {title}",
        ]

        if send_updates:
            attendees = event.get("attendees", [])
            if attendees:
                lines.append(f"**Attendees notified:** {len(attendees)}")

        if message:
            lines.append(f"**Message:** {message}")

        return "\n".join(lines)

    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "notFound" in error_str:
            return f"❌ Event not found: {event_id}"
        return f"❌ Failed to cancel event: {e}"


def register_tools(server: "FastMCP") -> int:
    """Register extra Google Calendar tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @registry.tool()
    async def google_calendar_decline_event(
        event_id: str,
        message: str = "Unable to attend",
        send_updates: bool = True,
    ) -> str:
        """
        Decline a calendar event invitation.

        Use this to decline meetings you've been invited to.
        The organizer will be notified of your decline.

        Args:
            event_id: The event ID (from google_calendar_list_events or event URL)
            message: Optional message to include with decline (default: "Unable to attend")
            send_updates: Whether to notify the organizer (default: True)

        Returns:
            Confirmation of decline or error message
        """
        return await _google_calendar_decline_event_impl(
            event_id, message, send_updates
        )

    @registry.tool()
    async def google_calendar_decline_meetings_on_date(
        date: str,
        message: str = "On PTO - unable to attend",
        dry_run: bool = True,
        skip_all_day: bool = False,
        skip_organizer_self: bool = True,
    ) -> str:
        """
        Decline all meetings on a specific date (useful for PTO).

        This tool finds all meetings on the specified date and declines them.
        Use dry_run=True first to preview what would be declined.

        Args:
            date: Date in YYYY-MM-DD format (e.g., "2024-01-15")
            message: Message to include with decline (default: "On PTO - unable to attend")
            dry_run: If True, only show what would be declined without actually declining
            skip_all_day: Skip all-day events (holidays, etc.)
            skip_organizer_self: Skip meetings you organized (you should cancel these instead)

        Returns:
            List of declined meetings or preview in dry run mode
        """
        return await _google_calendar_decline_meetings_on_date_impl(
            date, message, dry_run, skip_all_day, skip_organizer_self
        )

    @registry.tool()
    async def google_calendar_cancel_event(
        event_id: str,
        send_updates: bool = True,
        message: str = "",
    ) -> str:
        """
        Cancel/delete a calendar event you organized.

        Use this to cancel meetings you created. All attendees will be notified.
        You must be the organizer to cancel an event.

        Args:
            event_id: The event ID
            send_updates: Whether to notify attendees (default: True)
            message: Optional cancellation message

        Returns:
            Confirmation of cancellation or error message
        """
        return await _google_calendar_cancel_event_impl(event_id, send_updates, message)

    return registry.count
