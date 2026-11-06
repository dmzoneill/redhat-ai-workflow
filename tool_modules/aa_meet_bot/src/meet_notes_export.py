"""Meet notes tool implementations: state export, chat voice and background cleanup."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tool_modules.aa_google_calendar.src.tools_basic import get_calendar_service
from tool_modules.aa_meet_bot.src.audio_output import AudioOutputManager
from tool_modules.aa_meet_bot.src.meet_bot_state import (
    CLEANUP,
    MEET_ERRORS,
    NOTES,
    active_controller_ids,
    ensure_bot_manager,
    ensure_notes_db,
    local_now,
)
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices, get_meetbot_device_count
from tool_modules.aa_meet_bot.src.voice_pipeline import get_pipeline_manager

# Import centralized paths
try:
    from server.paths import MEETBOT_DATA_DIR, MEETBOT_STATE_FILE
except ImportError:
    # Fallback for standalone usage
    MEETBOT_DATA_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot"
    MEETBOT_STATE_FILE = MEETBOT_DATA_DIR / "state.json"

logger = logging.getLogger(__name__)


def _event_meet_url(event: dict) -> str | None:
    """Return the video (Meet) entry point URI of a calendar event, if any."""
    for entry in event.get("conferenceData", {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video":
            return entry.get("uri", "")
    return None


def _calendar_meetings(service, cal, time_min: str, time_max: str) -> list[dict]:
    """Upcoming events with Meet links from one monitored calendar."""
    events_result = (
        service.events()
        .list(
            calendarId=cal.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    meetings = []
    for event in events_result.get("items", []):
        # Only include events with Meet links
        meet_url = _event_meet_url(event)
        if not meet_url:
            continue
        meetings.append(
            {
                "id": event.get("id", ""),
                "title": event.get("summary", "No title"),
                "url": meet_url,
                "startTime": event["start"].get("dateTime", event["start"].get("date")),
                "endTime": event["end"].get("dateTime", event["end"].get("date")),
                "organizer": event.get("organizer", {}).get("email", ""),
                "attendees": [a.get("email", "") for a in event.get("attendees", [])[:5]],
                "status": "pending",
                "calendarName": cal.name,
            }
        )
    return meetings


def fetch_upcoming_meetings(calendars) -> list[dict]:
    """Fetch upcoming Meet events for each enabled calendar, sorted by start time."""
    upcoming: list[dict] = []
    try:
        service, error = get_calendar_service()
    except ImportError:
        logger.debug("Google Calendar not available")
        return upcoming
    if not service or error:
        return upcoming

    now = datetime.now(ZoneInfo("Europe/Dublin"))
    time_min = now.isoformat()
    time_max = (now + timedelta(days=2)).isoformat()  # Next 2 days
    for cal in calendars:
        if not cal.enabled:
            continue
        try:
            upcoming.extend(_calendar_meetings(service, cal, time_min, time_max))
        except MEET_ERRORS as e:
            logger.warning("Failed to fetch events from %s: %s", cal.name, e)

    upcoming.sort(key=lambda x: x.get("startTime", ""))
    return upcoming


def _current_meeting_entry(status: dict) -> dict:
    """UI entry for one capturing meeting session."""
    joined_at = status.get("joined_at")
    return {
        "id": str(status.get("meeting_id", "")),
        "sessionId": status.get("session_id", ""),
        "title": status.get("title", "Unknown"),
        "url": status.get("meet_url", ""),
        "startTime": (joined_at if isinstance(joined_at, datetime) else local_now()).isoformat(),
        "organizer": "",
        "attendees": [],
        "status": "joined",
        "captionsCount": status.get("captions_captured", 0),
        "durationMinutes": status.get("duration_minutes", 0),
        "scheduledEnd": status.get("scheduled_end"),
        "timeRemainingMinutes": status.get("time_remaining_minutes"),
        "gracePeriodMinutes": status.get("grace_period_minutes", 5),
    }


def _session_captions(status: dict) -> list[dict]:
    """The last 30 captions of a meeting session's bot."""
    bot = NOTES.bot_manager.get_bot(status.get("session_id", "")) if NOTES.bot_manager else None
    if not bot or not bot.state.transcript_buffer:
        return []
    return [
        {
            "speaker": entry.speaker,
            "text": entry.text,
            "timestamp": (
                entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else str(entry.timestamp)
            ),
            "sessionId": status.get("session_id", ""),
            "meetingTitle": status.get("title", "Unknown"),
        }
        for entry in bot.state.transcript_buffer[-30:]  # Last 30 per meeting
    ]


async def _current_meetings_and_captions() -> tuple[list[dict], list[dict]]:
    """Capturing meetings (supports multiple concurrent meetings) and their recent captions."""
    current_meetings: list[dict] = []
    all_captions: list[dict] = []
    if NOTES.bot_manager:
        for status in await NOTES.bot_manager.get_all_statuses():
            if status.get("status") == "capturing":
                current_meetings.append(_current_meeting_entry(status))
                all_captions.extend(_session_captions(status))
    return current_meetings, all_captions


def _write_state_file(state: dict) -> None:
    """Write the exported state JSON for the VS Code extension."""
    MEETBOT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEETBOT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


async def _meet_notes_export_state_impl() -> str:
    """Export current state to JSON for the VS Code extension UI."""

    db = await ensure_notes_db()

    # Get calendars
    calendars = await db.get_calendars(enabled_only=False)

    # Get recent meetings from database
    since = local_now() - timedelta(days=7)
    meetings = await db.list_meetings(since=since, limit=10)

    # Fetch upcoming meetings from Google Calendar for each monitored calendar
    upcoming_meetings = fetch_upcoming_meetings(calendars)

    # Get scheduler status
    scheduler_running = NOTES.scheduler is not None and NOTES.scheduler.state.running

    # Get current meetings status (supports multiple concurrent meetings)
    current_meetings, all_captions = await _current_meetings_and_captions()

    # For backward compatibility, also set currentMeeting to first active meeting
    current_meeting = current_meetings[0] if current_meetings else None

    # Build state object matching MeetBotState interface (extended for multi-meeting)
    state = {
        "currentMeeting": current_meeting,  # Backward compatibility
        "currentMeetings": current_meetings,  # New: array of all active meetings
        "activeMeetingCount": len(current_meetings),
        "upcomingMeetings": upcoming_meetings[:20],  # Limit to 20
        "captions": all_captions[-50:],  # Last 50 captions across all meetings
        "isListening": len(current_meetings) > 0,
        "lastWakeWord": None,
        "responseQueue": [],
        "gpuUsage": 0,
        "vramUsage": 0,
        "status": "in_meeting" if current_meetings else "idle",
        "error": None,
        "schedulerRunning": scheduler_running,
        "monitoredCalendars": [
            {
                "id": str(cal.id),
                "calendarId": cal.calendar_id,
                "name": cal.name,
                "autoJoin": cal.auto_join,
                "enabled": cal.enabled,
            }
            for cal in calendars
        ],
        "recentNotes": [
            {
                "id": m.id,
                "title": m.title,
                "date": (m.scheduled_start.strftime("%Y-%m-%d %H:%M") if m.scheduled_start else ""),
                "duration": (
                    int((m.actual_end - m.actual_start).total_seconds() / 60) if m.actual_start and m.actual_end else 0
                ),
                "transcriptCount": len(m.transcript) if m.transcript else 0,
                "status": m.status,
            }
            for m in meetings
        ],
        "botMode": "notes",
    }

    # Write to state file (off the event loop)
    await asyncio.to_thread(_write_state_file, state)

    return (
        f"✅ State exported to {MEETBOT_STATE_FILE}\n\n"
        f"Found {len(upcoming_meetings)} upcoming meetings with Meet links."
    )


# ==================== VOICE PIPELINE IMPLEMENTATIONS ====================


def _target_bot(manager, session_id: str):
    """Return (bot, error) for the given session, or the first active meeting."""
    if session_id:
        bot = manager.get_bot(session_id)
        if not bot:
            return None, f"❌ Meeting session not found: {session_id}"
        return bot, None
    # Use first active meeting
    active_ids = manager.get_active_session_ids()
    if not active_ids:
        return None, "❌ No active meetings. Join a meeting first."
    return manager.get_bot(active_ids[0]), None


async def _speak_in_meeting(controller, pipe_path, text: str) -> str:
    """Synthesize ``text`` and play it into the meeting, unmuting only while speaking."""
    # Synthesize speech first (before unmuting)
    tts = get_tts_engine(backend="piper")
    if not await tts.initialize():
        return "❌ TTS engine not available"

    tts_result = await tts.synthesize(text)

    if not tts_result.success:
        return f"❌ TTS failed: {tts_result.error}"

    # Unmute the microphone before speaking
    await controller.unmute_and_speak()
    logger.info("Unmuted microphone for TTS message")

    try:
        # Play to meeting
        audio_output = AudioOutputManager(pipe_path)
        success = await audio_output.play_tts_result(tts_result)
        audio_output.close()
    finally:
        # Always re-mute after speaking (even if playback fails)
        await controller.mute()
        logger.info("Re-muted microphone after TTS message")

    if success:
        preview = f"{text[:50]}..." if len(text) > 50 else text
        return f'✅ Message sent to meeting: "{preview}"'
    return "❌ Failed to play audio to meeting"


async def _mute_quietly(controller) -> None:
    """Best-effort mute after a failure."""
    try:
        await controller.mute()
    except MEET_ERRORS as e:
        logger.debug("Could not re-mute after failure: %s", e)


async def _meet_send_message_impl(
    text: str,
    session_id: str = "",
) -> str:
    """
    Send a typed message to an active meeting via text-to-speech.

    Args:
        text: The message to speak in the meeting
        session_id: Optional meeting session ID (uses active meeting if empty)

    Returns:
        Confirmation message
    """

    manager = await ensure_bot_manager()

    # Find the target meeting
    bot, error = _target_bot(manager, session_id)
    if error:
        return error

    controller = bot.controller if bot else None
    if not controller:
        return "❌ Meeting controller not available"

    # Get the pipe path for audio output
    pipe_path = controller.get_pipe_path()
    if not pipe_path:
        return "❌ Audio output not available (no pipe path)"

    try:
        return await _speak_in_meeting(controller, pipe_path, text)
    except MEET_ERRORS as e:
        logger.error("Send message failed: %s", e)
        # Try to ensure we're muted even on error
        await _mute_quietly(controller)
        return f"❌ Failed to send message: {e}"


async def _meet_voice_pipeline_status_impl() -> str:
    """Get status of voice pipelines."""
    pipeline_manager = get_pipeline_manager()
    stats = pipeline_manager.get_all_stats()

    if not stats:
        return (
            "📭 **No Voice Pipelines Active**\n\n"
            "Voice pipelines are created when joining meetings with voice interaction enabled."
        )

    lines = [
        f"🎤 **Voice Pipeline Status ({len(stats)} active)**",
        "",
    ]

    for instance_id, stat in stats.items():
        lines.append(f"### {instance_id}")
        lines.append(f"- **Running:** {'Yes' if stat['running'] else 'No'}")
        lines.append(f"- **Processing:** {'Yes' if stat['processing'] else 'No'}")
        lines.append(f"- **Utterances:** {stat['total_utterances']}")
        lines.append(f"- **Wake Words:** {stat['wake_word_triggers']}")
        lines.append(f"- **Responses:** {stat['responses_generated']}")
        if stat["responses_generated"] > 0:
            lines.append(f"- **Avg Latency:** {stat['avg_latency_ms']:.0f}ms")
            lines.append(f"- **Min/Max:** {stat['min_latency_ms']:.0f}ms / {stat['max_latency_ms']:.0f}ms")
        lines.append(f"- **Errors:** {stat['errors']}")
        lines.append("")

    return "\n".join(lines)


# ==================== STARTUP CLEANUP ====================


async def _run_startup_cleanup() -> None:
    """
    Clean up orphaned MeetBot devices on startup.

    This runs once when the MCP server starts to remove any devices
    left over from previous sessions that weren't properly cleaned up.
    """
    if CLEANUP.startup_done:
        return

    CLEANUP.startup_done = True

    try:
        # Check if there are any orphaned devices
        counts = await get_meetbot_device_count()
        total_devices = counts["module_count"] + counts["pipe_count"] + counts["video_count"]

        if total_devices == 0:
            logger.info("🔊 MeetBot startup: No orphaned devices found")
            return

        logger.info(
            "🔊 MeetBot startup: Found %s orphaned devices (modules=%s, pipes=%s, video=%s)",
            total_devices,
            counts["module_count"],
            counts["pipe_count"],
            counts["video_count"],
        )

        # Clean up all orphaned devices (no active sessions on startup)
        results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

        removed_count = (
            len(results.get("removed_modules", []))
            + len(results.get("removed_pipes", []))
            + len(results.get("removed_video_devices", []))
        )

        if removed_count > 0:
            logger.info("🔊 MeetBot startup: Cleaned up %s orphaned devices", removed_count)
        else:
            logger.info("🔊 MeetBot startup: No devices needed cleanup")

        if results.get("errors"):
            for err in results["errors"]:
                logger.warning("🔊 MeetBot startup cleanup error: %s", err)

    except MEET_ERRORS as e:
        logger.error("🔊 MeetBot startup cleanup failed: %s", e)


# One bad cleanup iteration (device, process or Google API/auth failure) must not end the loop;
# asyncio subprocess failures surface as OSError, which MEET_ERRORS already covers.
_CLEANUP_ERRORS: tuple[type[Exception], ...] = MEET_ERRORS


async def periodic_cleanup_task() -> None:
    """
    Background task that periodically cleans up orphaned devices.

    Runs every 5 minutes to catch any devices that weren't properly
    cleaned up due to crashes or unexpected termination.
    """
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes

            # Get active instance IDs from the bot manager
            active_ids = active_controller_ids()

            # Check if cleanup is needed
            counts = await get_meetbot_device_count()
            expected_modules = len(active_ids) * 2  # Each instance has sink + source

            if counts["module_count"] > expected_modules:
                logger.info(
                    "🔊 Periodic cleanup: %s modules but only %s active meetings (expected ~%s)",
                    counts["module_count"],
                    len(active_ids),
                    expected_modules,
                )
                results = await cleanup_orphaned_meetbot_devices(active_ids)

                if results.get("removed_modules") or results.get("removed_pipes"):
                    logger.info(
                        "🔊 Periodic cleanup: Removed %s modules, %s pipes",
                        len(results.get("removed_modules", [])),
                        len(results.get("removed_pipes", [])),
                    )

        except asyncio.CancelledError:
            logger.info("🔊 Periodic cleanup task cancelled")
            raise
        except _CLEANUP_ERRORS as e:
            logger.error("🔊 Periodic cleanup error: %s", e)


def _start_periodic_cleanup() -> None:
    """Start the periodic cleanup background task."""
    if CLEANUP.task is None or CLEANUP.task.done():
        CLEANUP.task = asyncio.create_task(periodic_cleanup_task())
        logger.info("🔊 Started periodic device cleanup task")
