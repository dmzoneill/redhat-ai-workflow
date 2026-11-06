"""Meet notes tool implementations: cleanup, history, transcripts and search."""

import logging
from datetime import timedelta

from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
from tool_modules.aa_meet_bot.src.meet_bot_state import (
    active_controller_ids,
    ensure_notes_db,
    local_now,
)
from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices, get_meetbot_device_count

logger = logging.getLogger(__name__)


async def _meet_notes_cleanup_impl() -> str:
    """Clean up hung browser instances."""

    # Get all controller instances
    instances = GoogleMeetController.get_all_instances()

    if not instances:
        return "✅ No browser instances found."

    lines = [
        f"🔍 **Browser Instance Status ({len(instances)})**",
        "",
    ]

    now = local_now()
    hung_instances = []

    for instance_id, controller in instances.items():
        info = controller.get_instance_info()
        age_minutes = (now - controller.created_at).total_seconds() / 60
        inactive_minutes = (now - controller.last_activity).total_seconds() / 60

        status = "🟢 Active"
        if inactive_minutes > 30:
            status = "🟡 Possibly hung"
            hung_instances.append(instance_id)
        if inactive_minutes > 60:
            status = "🔴 Likely hung"

        lines.append(f"### {instance_id}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Age:** {age_minutes:.1f} min")
        lines.append(f"- **Inactive:** {inactive_minutes:.1f} min")
        lines.append(f"- **Browser PID:** {info.get('browser_pid', 'Unknown')}")
        lines.append(f"- **Meeting:** {info.get('meeting_url', 'None')}")
        lines.append("")

    if hung_instances:
        lines.append("---")
        lines.append("")
        lines.append(f"⚠️ **{len(hung_instances)} potentially hung instance(s) found.**")
        lines.append("")
        lines.append("To force-kill hung instances, run:")
        lines.append("```")
        lines.append("meet_notes_force_cleanup()")
        lines.append("```")

    return "\n".join(lines)


async def _meet_notes_force_cleanup_impl() -> str:
    """Force kill all hung browser instances."""

    # Clean up hung instances (inactive > 30 min)
    killed = await GoogleMeetController.cleanup_hung_instances(max_age_minutes=30)

    if not killed:
        return "✅ No hung instances found to clean up."

    lines = [
        f"🧹 **Cleaned Up {len(killed)} Hung Instance(s)**",
        "",
    ]

    for instance_id in killed:
        lines.append(f"- ✅ Killed: `{instance_id}`")

    return "\n".join(lines)


async def _meet_notes_cleanup_audio_impl() -> str:
    """Clean up orphaned MeetBot audio devices."""

    # Get counts before cleanup
    before = await get_meetbot_device_count()

    # Get active instance IDs from the bot manager
    active_ids = active_controller_ids()

    # Run cleanup
    results = await cleanup_orphaned_meetbot_devices(active_ids)

    # Get counts after cleanup
    after = await get_meetbot_device_count()

    lines = [
        "# 🔊 Audio Device Cleanup",
        "",
        "## Before",
        f"- Modules: {before['module_count']}",
        f"- Sinks: {before['sink_count']}",
        f"- Sources: {before['source_count']}",
        f"- Pipes: {before['pipe_count']}",
        "",
        "## After",
        f"- Modules: {after['module_count']}",
        f"- Sinks: {after['sink_count']}",
        f"- Sources: {after['source_count']}",
        f"- Pipes: {after['pipe_count']}",
        "",
    ]

    if results["removed_modules"]:
        lines.append("## Removed Modules")
        for mod in results["removed_modules"]:
            lines.append(f"- ✅ {mod}")
        lines.append("")

    if results["removed_pipes"]:
        lines.append("## Removed Pipes")
        for pipe in results["removed_pipes"]:
            lines.append(f"- ✅ {pipe}")
        lines.append("")

    if results["skipped_active"]:
        lines.append("## Skipped (Active)")
        for item in results["skipped_active"]:
            lines.append(f"- ⏭️ {item}")
        lines.append("")

    if results["errors"]:
        lines.append("## Errors")
        for err in results["errors"]:
            lines.append(f"- ❌ {err}")
        lines.append("")

    total_removed = len(results["removed_modules"]) + len(results["removed_pipes"])
    if total_removed == 0:
        lines.append("✅ No orphaned devices found.")
    else:
        lines.append(f"✅ Cleaned up {total_removed} orphaned device(s).")

    return "\n".join(lines)


async def _meet_notes_cleanup_all_devices_impl() -> str:
    """Force cleanup ALL MeetBot audio/video devices, ignoring active sessions."""

    # Get counts before cleanup
    before = await get_meetbot_device_count()

    # Force cleanup ALL devices (pass empty set to skip active session check)
    results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

    # Get counts after cleanup
    after = await get_meetbot_device_count()

    lines = [
        "# 🔊 Force Device Cleanup (ALL)",
        "",
        "⚠️ **This removes ALL MeetBot devices, including any active meetings!**",
        "",
        "## Before",
        f"- Modules: {before['module_count']}",
        f"- Sinks: {before['sink_count']}",
        f"- Sources: {before['source_count']}",
        f"- Pipes: {before['pipe_count']}",
        f"- Video devices: {before['video_count']}",
        "",
        "## After",
        f"- Modules: {after['module_count']}",
        f"- Sinks: {after['sink_count']}",
        f"- Sources: {after['source_count']}",
        f"- Pipes: {after['pipe_count']}",
        f"- Video devices: {after['video_count']}",
        "",
    ]

    if results["removed_modules"]:
        lines.append("## Removed Modules")
        for mod in results["removed_modules"]:
            lines.append(f"- ✅ {mod}")
        lines.append("")

    if results["removed_pipes"]:
        lines.append("## Removed Pipes")
        for pipe in results["removed_pipes"]:
            lines.append(f"- ✅ {pipe}")
        lines.append("")

    if results.get("removed_video_devices"):
        lines.append("## Removed Video Devices")
        for vid in results["removed_video_devices"]:
            lines.append(f"- ✅ {vid}")
        lines.append("")

    if results["errors"]:
        lines.append("## Errors")
        for err in results["errors"]:
            lines.append(f"- ❌ {err}")
        lines.append("")

    total_removed = (
        len(results["removed_modules"]) + len(results["removed_pipes"]) + len(results.get("removed_video_devices", []))
    )
    if total_removed == 0:
        lines.append("✅ No devices found to clean up.")
    else:
        lines.append(f"✅ Force cleaned {total_removed} device(s).")

    return "\n".join(lines)


async def _meet_notes_list_meetings_impl(days: int, calendar_id: str) -> str:
    """List recent meetings."""

    db = await ensure_notes_db()

    since = local_now() - timedelta(days=days)
    meetings = await db.list_meetings(
        calendar_id=calendar_id if calendar_id else None,
        since=since,
        limit=20,
    )

    if not meetings:
        return f"📅 No meeting notes in the last {days} days."

    lines = [
        f"# 📝 Meeting Notes (Last {days} Days)",
        "",
    ]

    for m in meetings:
        status_icon = {
            "completed": "✅",
            "in_progress": "🟢",
            "scheduled": "⏳",
            "cancelled": "❌",
        }.get(m.status, "❓")

        lines.append(f"## {status_icon} {m.title}")
        lines.append(f"- **ID:** {m.id}")
        if m.scheduled_start:
            lines.append(f"- **Date:** {m.scheduled_start.strftime('%Y-%m-%d %H:%M')}")
        if m.calendar_name:
            lines.append(f"- **Calendar:** {m.calendar_name}")
        if m.organizer:
            lines.append(f"- **Organizer:** {m.organizer}")

        # Get transcript count
        transcript = await db.get_transcript(m.id) if m.id else []
        lines.append(f"- **Transcript entries:** {len(transcript)}")

        if m.summary:
            lines.append(f"- **Summary:** {m.summary[:100]}...")

        lines.append("")

    lines.append("---")
    lines.append("Use `meet_notes_get_transcript(meeting_id)` to view full transcript.")

    return "\n".join(lines)


async def _meet_notes_get_transcript_impl(meeting_id: int) -> str:
    """Get transcript for a meeting."""
    db = await ensure_notes_db()

    meeting = await db.get_meeting(meeting_id, include_transcript=True)

    if not meeting:
        return f"❌ Meeting not found: {meeting_id}"

    lines = [
        f"# 📝 Transcript: {meeting.title}",
        "",
    ]

    if meeting.scheduled_start:
        lines.append(f"**Date:** {meeting.scheduled_start.strftime('%Y-%m-%d %H:%M')}")
    if meeting.organizer:
        lines.append(f"**Organizer:** {meeting.organizer}")
    if meeting.attendees:
        lines.append(f"**Attendees:** {', '.join(meeting.attendees[:5])}")
        if len(meeting.attendees) > 5:
            lines.append(f"  ... and {len(meeting.attendees) - 5} more")

    lines.append("")
    lines.append("---")
    lines.append("")

    if not meeting.transcript:
        lines.append("*No transcript entries captured.*")
    else:
        lines.append("## Transcript")
        lines.append("")

        current_speaker = None
        for entry in meeting.transcript:
            if entry.speaker != current_speaker:
                current_speaker = entry.speaker
                lines.append(f"\n**{entry.speaker}** ({entry.timestamp.strftime('%H:%M:%S')}):")
            lines.append(f"> {entry.text}")

    if meeting.summary:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Summary")
        lines.append(meeting.summary)

    if meeting.action_items:
        lines.append("")
        lines.append("## Action Items")
        for item in meeting.action_items:
            lines.append(f"- [ ] {item}")

    return "\n".join(lines)


async def _meet_notes_search_impl(query: str, meeting_id: int) -> str:
    """Search transcripts."""
    db = await ensure_notes_db()

    results = await db.search_transcripts(
        query=query,
        meeting_id=meeting_id if meeting_id > 0 else None,
        limit=20,
    )

    if not results:
        return f'🔍 No results found for: "{query}"'

    lines = [
        f'# 🔍 Search Results: "{query}"',
        "",
        f"Found {len(results)} matches:",
        "",
    ]

    # Group by meeting
    by_meeting: dict[int, list] = {}
    for r in results:
        mid = r["meeting_id"]
        if mid not in by_meeting:
            by_meeting[mid] = []
        by_meeting[mid].append(r)

    for matches in by_meeting.values():
        first = matches[0]
        lines.append(f"## {first['meeting_title']}")
        if first["meeting_date"]:
            lines.append(f"*{first['meeting_date']}*")
        lines.append("")

        for m in matches[:5]:  # Limit matches per meeting
            lines.append(f'- **{m["speaker"]}**: "{m["text"]}"')

        if len(matches) > 5:
            lines.append(f"  ... and {len(matches) - 5} more matches")

        lines.append("")

    return "\n".join(lines)


async def _meet_notes_stats_impl() -> str:
    """Get meeting notes statistics."""
    db = await ensure_notes_db()
    stats = await db.get_stats()

    lines = [
        "# 📊 Meeting Notes Statistics",
        "",
        f"**Calendars Monitored:** {stats.get('calendars', 0)}",
        "",
        "## Meetings",
    ]

    meetings = stats.get("meetings", {})
    lines.append(f"- **Total:** {meetings.get('total', 0)}")
    lines.append(f"- **Completed:** {meetings.get('completed', 0)}")
    lines.append(f"- **In Progress:** {meetings.get('in_progress', 0)}")
    lines.append(f"- **Scheduled:** {meetings.get('scheduled', 0)}")

    lines.append("")
    lines.append("## Transcripts")
    lines.append(f"- **Total Entries:** {stats.get('transcript_entries', 0)}")

    lines.append("")
    lines.append("## Storage")
    lines.append(f"- **Database Size:** {stats.get('db_size_kb', 0)} KB")

    return "\n".join(lines)
