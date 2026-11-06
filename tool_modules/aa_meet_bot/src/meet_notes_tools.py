"""Meet notes tool implementations: scheduler, calendars and meeting sessions."""

import logging
from datetime import datetime, timedelta

from tool_modules.aa_meet_bot.src.meet_bot_state import (
    MEET_ERRORS,
    NOTES,
    ensure_bot_manager,
    ensure_scheduler,
    local_now,
)

logger = logging.getLogger(__name__)


async def _meet_notes_start_scheduler_impl() -> str:
    """Start the meeting scheduler."""
    scheduler = await ensure_scheduler()

    if scheduler.state.running:
        return "⚠️ Scheduler is already running.\n\nUse `meet_notes_scheduler_status` to see current state."

    await scheduler.start()

    calendars = await scheduler.list_calendars()

    lines = [
        "✅ **Meeting Scheduler Started**",
        "",
        "The bot will now automatically join meetings from monitored calendars.",
        "",
    ]

    if calendars:
        lines.append(f"**Monitoring {len(calendars)} calendar(s):**")
        for cal in calendars:
            status = "✅" if cal.enabled else "⏸️"
            auto = "auto-join" if cal.auto_join else "manual"
            lines.append(f"- {status} {cal.name} ({auto})")
    else:
        lines.append("⚠️ No calendars configured yet.")
        lines.append("")
        lines.append("Add a calendar with:")
        lines.append("```")
        lines.append('meet_notes_add_calendar("primary", "My Calendar")')
        lines.append("```")

    return "\n".join(lines)


async def _meet_notes_stop_scheduler_impl() -> str:
    """Stop the meeting scheduler."""

    if NOTES.scheduler is None or not NOTES.scheduler.state.running:
        return "⚠️ Scheduler is not running."

    await NOTES.scheduler.stop()

    return "✅ **Meeting Scheduler Stopped**\n\nThe bot will no longer auto-join meetings."


async def _meet_notes_scheduler_status_impl() -> str:
    """Get scheduler status."""
    scheduler = await ensure_scheduler()
    status = await scheduler.get_status()

    lines = [
        "# 📅 Meeting Scheduler Status",
        "",
        f"**Status:** {'🟢 Running' if status['running'] else '🔴 Stopped'}",
    ]

    if status["current_meeting"]:
        lines.append(f"**Current Meeting:** {status['current_meeting']}")

    lines.append(f"**Completed Today:** {status['completed_today']}")

    if status["last_poll"]:
        lines.append(f"**Last Poll:** {status['last_poll']}")

    lines.append("")

    # Upcoming meetings
    upcoming = status.get("upcoming_meetings", [])
    if upcoming:
        lines.append("## 📋 Upcoming Meetings")
        for m in upcoming:
            status_icon = {
                "scheduled": "⏳",
                "joining": "🔄",
                "active": "🟢",
                "completed": "✅",
                "skipped": "⏭️",
            }.get(m["status"], "❓")
            lines.append(f"- {status_icon} **{m['title']}**")
            lines.append(f"  - Start: {m['start']}")
            lines.append(f"  - Mode: {m['bot_mode']}")
    else:
        lines.append("No upcoming meetings scheduled.")

    # Errors
    if status.get("errors"):
        lines.append("")
        lines.append("## ⚠️ Recent Errors")
        for err in status["errors"]:
            lines.append(f"- {err}")

    return "\n".join(lines)


async def _meet_notes_add_calendar_impl(
    calendar_id: str,
    name: str,
    auto_join: bool,
) -> str:
    """Add a calendar to monitor."""
    scheduler = await ensure_scheduler()

    success = await scheduler.add_calendar(
        calendar_id=calendar_id,
        name=name or calendar_id,
        auto_join=auto_join,
        bot_mode="notes",
    )

    if success:
        lines = [
            f"✅ **Calendar Added:** {name or calendar_id}",
            "",
            f"- **Calendar ID:** `{calendar_id}`",
            f"- **Auto-join:** {'Yes' if auto_join else 'No'}",
            "- **Mode:** Notes (capture only)",
            "",
            "The scheduler will now monitor this calendar for meetings.",
        ]
        return "\n".join(lines)
    return f"❌ Failed to add calendar: {calendar_id}"


async def _meet_notes_remove_calendar_impl(calendar_id: str) -> str:
    """Remove a calendar from monitoring."""
    scheduler = await ensure_scheduler()

    success = await scheduler.remove_calendar(calendar_id)

    if success:
        return f"✅ Calendar removed: `{calendar_id}`"
    return f"❌ Calendar not found: `{calendar_id}`"


async def _meet_notes_list_calendars_impl() -> str:
    """List monitored calendars."""
    scheduler = await ensure_scheduler()
    calendars = await scheduler.list_calendars()

    if not calendars:
        return (
            "📅 **No calendars configured**\n\n"
            "Add a calendar with:\n"
            "```\n"
            'meet_notes_add_calendar("primary", "My Calendar")\n'
            "```\n\n"
            "Use `google_calendar_list_calendars` to see available calendars."
        )

    lines = [
        "# 📅 Monitored Calendars",
        "",
    ]

    for cal in calendars:
        status = "✅" if cal.enabled else "⏸️"
        auto = "auto-join" if cal.auto_join else "manual"
        lines.append(f"## {status} {cal.name}")
        lines.append(f"- **ID:** `{cal.calendar_id}`")
        lines.append(f"- **Auto-join:** {auto}")
        lines.append(f"- **Mode:** {cal.bot_mode}")
        if cal.added_at:
            lines.append(f"- **Added:** {cal.added_at.strftime('%Y-%m-%d')}")
        lines.append("")

    return "\n".join(lines)


async def _meet_notes_join_now_impl(
    meet_url: str,
    title: str,
    scheduled_end: datetime | None = None,
    duration_minutes: int = 0,
    grace_period_minutes: int = 5,
) -> str:
    """Join a meeting immediately (supports multiple concurrent meetings)."""
    try:
        manager = await ensure_bot_manager()
    except MEET_ERRORS as e:
        return f"❌ Failed to initialize bot manager: {e}"

    # Calculate scheduled_end from duration if not provided
    if not scheduled_end and duration_minutes > 0:
        scheduled_end = local_now() + timedelta(minutes=duration_minutes)

    # Join the meeting using the manager
    session_id, success, errors = await manager.join_meeting(
        meet_url=meet_url,
        title=title,
        scheduled_end=scheduled_end,
        grace_period_minutes=grace_period_minutes,
    )

    if success:
        active_count = manager.get_active_count()
        end_info = ""
        if scheduled_end:
            end_info = f"- **Auto-leave:** {scheduled_end.strftime('%H:%M')} (+{grace_period_minutes}min grace)\n"

        return (
            "✅ **Joined Meeting**\n\n"
            f"- **Title:** {title or session_id}\n"
            f"- **URL:** {meet_url}\n"
            f"- **Session ID:** `{session_id}`\n"
            "- **Mode:** Notes (capture only)\n"
            f"{end_info}"
            f"- **Active Meetings:** {active_count}\n\n"
            f"Capturing captions... Use `meet_notes_leave('{session_id}')` when done."
        )
    if not errors:
        errors = ["Unknown error - check browser controller logs"]
    return "❌ Failed to join meeting\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)


async def _meet_notes_leave_impl(session_id: str = "") -> str:
    """Leave a meeting by session ID, or leave all if no ID provided."""

    manager = await ensure_bot_manager()

    if not session_id:
        # If no session ID, check how many active meetings
        active_ids = manager.get_active_session_ids()
        if not active_ids:
            return "⚠️ Not in any meetings."
        if len(active_ids) == 1:
            # Only one meeting, leave it
            session_id = active_ids[0]
        else:
            # Multiple meetings, ask which one
            lines = [
                "⚠️ **Multiple Active Meetings**",
                "",
                "Specify which meeting to leave:",
                "",
            ]
            for sid in active_ids:
                bot = manager.get_bot(sid)
                if bot:
                    lines.append(f"- `meet_notes_leave('{sid}')` - {bot.state.title}")
            lines.append("")
            lines.append("Or leave all: `meet_notes_leave_all()`")
            return "\n".join(lines)

    result = await manager.leave_meeting(session_id)

    if "error" in result:
        return f"❌ {result['error']}"

    active_count = manager.get_active_count()
    return (
        "✅ **Left Meeting**\n\n"
        f"- **Title:** {result.get('title', 'Unknown')}\n"
        f"- **Session ID:** `{session_id}`\n"
        f"- **Duration:** {result.get('duration_minutes', 0)} minutes\n"
        f"- **Captions Captured:** {result.get('captions_captured', 0)}\n"
        f"- **Meeting ID:** {result.get('meeting_id', 'N/A')}\n"
        f"- **Remaining Active:** {active_count}\n\n"
        f"Use `meet_notes_get_transcript({result.get('meeting_id')})` to view the transcript."
    )


async def _meet_notes_leave_all_impl() -> str:
    """Leave all active meetings."""
    manager = await ensure_bot_manager()

    active_count = manager.get_active_count()
    if active_count == 0:
        return "⚠️ Not in any meetings."

    results = await manager.leave_all()

    lines = [
        f"✅ **Left {len(results)} Meeting(s)**",
        "",
    ]

    for result in results:
        if "error" in result:
            lines.append(f"- ❌ {result.get('session_id', 'Unknown')}: {result['error']}")
        else:
            lines.append(f"- ✅ {result.get('title', 'Unknown')} ({result.get('captions_captured', 0)} captions)")

    return "\n".join(lines)


async def _meet_notes_active_meetings_impl() -> str:
    """List all active meetings."""
    manager = await ensure_bot_manager()

    statuses = await manager.get_all_statuses()

    if not statuses:
        return "📭 **No Active Meetings**\n\nUse `meet_notes_join_now(url, title)` to join a meeting."

    lines = [
        f"🎥 **Active Meetings ({len(statuses)})**",
        "",
    ]

    for status in statuses:
        session_id = status.get("session_id", "Unknown")
        title = status.get("title", "Untitled")
        captions = status.get("captions_captured", 0)
        duration = status.get("duration_minutes", 0)
        scheduled_end = status.get("scheduled_end")
        time_remaining = status.get("time_remaining_minutes")

        lines.append(f"### {title}")
        lines.append(f"- **Session ID:** `{session_id}`")
        lines.append(f"- **Duration:** {duration:.1f} min")
        lines.append(f"- **Captions:** {captions}")
        if scheduled_end:
            lines.append(f"- **Scheduled End:** {scheduled_end}")
            if time_remaining is not None:
                lines.append(f"- **Time Remaining:** {time_remaining:.1f} min")
        lines.append(f"- **Leave:** `meet_notes_leave('{session_id}')`")
        lines.append("")

    return "\n".join(lines)
