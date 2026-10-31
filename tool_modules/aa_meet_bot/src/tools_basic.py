"""
Meet Bot MCP Tools.

Provides tools for:
- Managing meeting approvals
- Joining/leaving meetings
- Monitoring meeting state
- Testing virtual devices
"""

import asyncio
import logging

from fastmcp import FastMCP

# Meet Bot modules import tool_modules.common (which sets up sys.path) before any server import.
from tool_modules.aa_meet_bot.src.meet_bot_core_tools import (
    _meet_bot_approve_meeting_impl,
    _meet_bot_ask_llm_impl,
    _meet_bot_full_response_impl,
    _meet_bot_generate_video_impl,
    _meet_bot_get_captions_impl,
    _meet_bot_join_meeting_impl,
    _meet_bot_leave_meeting_impl,
    _meet_bot_preload_jira_impl,
    _meet_bot_respond_impl,
    _meet_bot_setup_devices_impl,
    _meet_bot_status_impl,
    _meet_bot_synthesize_speech_impl,
    _meet_bot_test_avatar_impl,
)
from tool_modules.aa_meet_bot.src.meet_notes_export import (
    _meet_notes_export_state_impl,
    _meet_send_message_impl,
    _meet_voice_pipeline_status_impl,
    _run_startup_cleanup,
    _start_periodic_cleanup,
)
from tool_modules.aa_meet_bot.src.meet_notes_maintenance import (
    _meet_notes_cleanup_all_devices_impl,
    _meet_notes_cleanup_audio_impl,
    _meet_notes_cleanup_impl,
    _meet_notes_force_cleanup_impl,
    _meet_notes_get_transcript_impl,
    _meet_notes_list_meetings_impl,
    _meet_notes_search_impl,
    _meet_notes_stats_impl,
)
from tool_modules.aa_meet_bot.src.meet_notes_tools import (
    _meet_notes_active_meetings_impl,
    _meet_notes_add_calendar_impl,
    _meet_notes_join_now_impl,
    _meet_notes_leave_all_impl,
    _meet_notes_leave_impl,
    _meet_notes_list_calendars_impl,
    _meet_notes_remove_calendar_impl,
    _meet_notes_scheduler_status_impl,
    _meet_notes_start_scheduler_impl,
    _meet_notes_stop_scheduler_impl,
)
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


# ==================== TOOL REGISTRATION ====================


def _register_bot_tools(registry: ToolRegistry) -> None:
    """Register the meeting bot tools (devices, joining, captions, avatar, voice)."""

    @registry.tool()
    async def meet_bot_status() -> str:
        """
        Get current status of the Meet Bot system.

        Shows:
        - Configuration
        - Virtual device status
        - Current meeting status
        - Approved meetings
        """
        return await _meet_bot_status_impl()

    @registry.tool()
    async def meet_bot_setup_devices() -> str:
        """
        Set up virtual audio and video devices.

        Creates:
        - PulseAudio virtual sink for capturing meeting audio
        - PulseAudio virtual source for bot voice output
        - v4l2loopback virtual camera for avatar video

        Run this before joining a meeting.
        """
        return await _meet_bot_setup_devices_impl()

    @registry.tool()
    async def meet_bot_approve_meeting(
        meeting_url: str,
        title: str = "",
        start_time: str = "",
    ) -> str:
        """
        Approve a meeting for the bot to join.

        The bot will only join pre-approved meetings for security.

        Args:
            meeting_url: Google Meet URL (e.g., https://meet.google.com/xxx-xxxx-xxx)
            title: Optional meeting title for display
            start_time: Optional start time (ISO format)
        """
        return await _meet_bot_approve_meeting_impl(meeting_url, title, start_time)

    @registry.tool()
    async def meet_bot_join_meeting(
        meeting_url: str = "",
        meeting_id: str = "",
    ) -> str:
        """
        Join a Google Meet meeting.

        The meeting must be pre-approved using meet_bot_approve_meeting.

        Args:
            meeting_url: Full Google Meet URL
            meeting_id: Or just the meeting ID (xxx-xxxx-xxx)
        """
        return await _meet_bot_join_meeting_impl(meeting_url, meeting_id)

    @registry.tool()
    async def meet_bot_leave_meeting() -> str:
        """Leave the current meeting."""
        return await _meet_bot_leave_meeting_impl()

    @registry.tool()
    async def meet_bot_get_captions(
        last_n: int = 20,
    ) -> str:
        """
        Get recent captions from the meeting.

        Args:
            last_n: Number of recent captions to return (default: 20)
        """
        return await _meet_bot_get_captions_impl(last_n)

    @registry.tool()
    async def meet_bot_test_avatar() -> str:
        """
        Test that the avatar image is valid for lip-sync.

        Checks:
        - Image exists
        - Resolution is sufficient
        - Aspect ratio is suitable
        """
        return await _meet_bot_test_avatar_impl()

    @registry.tool()
    async def meet_bot_synthesize_speech(
        text: str,
        output_filename: str = "",
    ) -> str:
        """
        Synthesize speech using GPT-SoVITS voice cloning.

        Uses the trained "dave" voice model to generate speech.

        Args:
            text: Text to synthesize
            output_filename: Optional output filename (auto-generated if not provided)
        """
        return await _meet_bot_synthesize_speech_impl(text, output_filename)

    @registry.tool()
    async def meet_bot_generate_video(
        audio_path: str,
        output_filename: str = "",
    ) -> str:
        """
        Generate lip-sync avatar video from audio.

        Uses Wav2Lip for real-time lip-sync, or falls back to static image.

        Args:
            audio_path: Path to audio file
            output_filename: Optional output filename
        """
        return await _meet_bot_generate_video_impl(audio_path, output_filename)

    @registry.tool()
    async def meet_bot_respond(
        text: str,
    ) -> str:
        """
        Generate a complete response (TTS + video) and play it.

        This is the main response function that:
        1. Synthesizes speech from text using GPT-SoVITS
        2. Generates lip-sync video using Wav2Lip
        3. Plays the video through the virtual camera

        Args:
            text: Response text to speak
        """
        return await _meet_bot_respond_impl(text)

    @registry.tool()
    async def meet_bot_preload_jira(
        project: str = "AAP",
    ) -> str:
        """
        Preload Jira context for the current sprint.

        Call this before joining a meeting to enable fast Jira-related responses.

        Args:
            project: Jira project key (default: AAP)
        """
        return await _meet_bot_preload_jira_impl(project)

    @registry.tool()
    async def meet_bot_ask_llm(
        question: str,
        speaker: str = "Someone",
    ) -> str:
        """
        Ask the LLM a question (for testing).

        Tests the LLM response generation without TTS/video.

        Args:
            question: The question to ask
            speaker: Who is asking (for context)
        """
        return await _meet_bot_ask_llm_impl(question, speaker)

    @registry.tool()
    async def meet_bot_full_response(
        question: str,
        speaker: str = "Someone",
    ) -> str:
        """
        Full pipeline: LLM → TTS → Video.

        Simulates what happens when someone says "David, [question]".
        Goes through the complete response pipeline.

        Args:
            question: The question/command
            speaker: Who asked
        """
        return await _meet_bot_full_response_impl(question, speaker)


def _register_notes_tools(registry: ToolRegistry) -> None:
    """Register the notes bot tools (scheduler, calendars, sessions)."""

    @registry.tool()
    async def meet_notes_start_scheduler() -> str:
        """
        Start the meeting scheduler service.

        The scheduler monitors your calendars and automatically joins
        meetings to capture notes. It runs in the background.

        Configure which calendars to monitor with meet_notes_add_calendar.
        """
        return await _meet_notes_start_scheduler_impl()

    @registry.tool()
    async def meet_notes_stop_scheduler() -> str:
        """Stop the meeting scheduler service."""
        return await _meet_notes_stop_scheduler_impl()

    @registry.tool()
    async def meet_notes_scheduler_status() -> str:
        """
        Get the status of the meeting scheduler.

        Shows:
        - Whether the scheduler is running
        - Current meeting (if any)
        - Upcoming meetings to be joined
        - Recent activity
        """
        return await _meet_notes_scheduler_status_impl()

    @registry.tool()
    async def meet_notes_add_calendar(
        calendar_id: str,
        name: str = "",
        auto_join: bool = True,
    ) -> str:
        """
        Add a calendar to monitor for meetings.

        The scheduler will automatically join meetings from this calendar
        to capture notes.

        Args:
            calendar_id: Google Calendar ID (use google_calendar_list_calendars to find IDs)
            name: Display name for the calendar
            auto_join: Whether to automatically join meetings (default: True)

        Examples:
            # Add your primary calendar
            meet_notes_add_calendar("primary")

            # Add a shared team calendar
            meet_notes_add_calendar(
                "ansible-engineering@redhat.com",
                "Ansible Engineering"
            )
        """
        return await _meet_notes_add_calendar_impl(calendar_id, name, auto_join)

    @registry.tool()
    async def meet_notes_remove_calendar(calendar_id: str) -> str:
        """
        Remove a calendar from monitoring.

        Args:
            calendar_id: Calendar ID to remove
        """
        return await _meet_notes_remove_calendar_impl(calendar_id)

    @registry.tool()
    async def meet_notes_list_calendars() -> str:
        """
        List all calendars being monitored for meetings.

        Shows which calendars the bot will auto-join meetings from.
        """
        return await _meet_notes_list_calendars_impl()

    @registry.tool()
    async def meet_notes_join_now(
        meet_url: str,
        title: str = "",
        duration_minutes: int = 0,
        grace_period_minutes: int = 5,
    ) -> str:
        """
        Join a meeting immediately to capture notes.

        This is for manually joining a meeting without waiting for
        the scheduler. The bot will capture captions and save them.

        Supports multiple concurrent meetings - you can join overlapping
        meetings and each will capture its own captions.

        Args:
            meet_url: Google Meet URL
            title: Optional meeting title
            duration_minutes: Expected duration - bot will auto-leave after this (0 = no auto-leave)
            grace_period_minutes: Extra minutes to stay after duration (default 5)
        """
        return await _meet_notes_join_now_impl(
            meet_url,
            title,
            duration_minutes=duration_minutes,
            grace_period_minutes=grace_period_minutes,
        )

    @registry.tool()
    async def meet_notes_leave(session_id: str = "") -> str:
        """
        Leave a meeting and save notes.

        Supports multiple concurrent meetings. If session_id is not provided:
        - If only one meeting is active, leaves that meeting
        - If multiple meetings are active, lists them so you can choose

        Args:
            session_id: Session ID of the meeting to leave (from join response)
        """
        return await _meet_notes_leave_impl(session_id)

    @registry.tool()
    async def meet_notes_leave_all() -> str:
        """
        Leave all active meetings.

        Use this to quickly exit all concurrent meetings at once.
        """
        return await _meet_notes_leave_all_impl()

    @registry.tool()
    async def meet_notes_active() -> str:
        """
        List all currently active meetings.

        Shows all meetings the bot is currently capturing notes for,
        with session IDs needed to leave specific meetings.
        """
        return await _meet_notes_active_meetings_impl()


def _register_maintenance_tools(registry: ToolRegistry) -> None:
    """Register cleanup, history, export and messaging tools."""

    @registry.tool()
    async def meet_notes_cleanup() -> str:
        """
        Check status of all browser instances.

        Shows which browser instances are active, their PIDs, and
        identifies any that may be hung (no activity for 30+ min).
        """
        return await _meet_notes_cleanup_impl()

    @registry.tool()
    async def meet_notes_force_cleanup() -> str:
        """
        Force kill all hung browser instances.

        Use this if browsers are stuck and not responding.
        Only kills instances that have been inactive for 30+ minutes.
        """
        return await _meet_notes_force_cleanup_impl()

    @registry.tool()
    async def meet_notes_cleanup_audio() -> str:
        """
        Clean up orphaned MeetBot audio devices.

        Removes PulseAudio sinks, sources, and named pipes that were
        created by MeetBot but not properly cleaned up (e.g., due to
        crashes or force kills).

        Also restores the default audio source if it was set to a
        MeetBot virtual device.

        This runs automatically every 5 minutes when meetings are active,
        but can be called manually if needed.
        """
        return await _meet_notes_cleanup_audio_impl()

    @registry.tool()
    async def meet_notes_cleanup_all_devices() -> str:
        """
        Force cleanup ALL MeetBot audio/video devices.

        ⚠️ WARNING: This removes ALL devices, including any that may be
        in use by active meetings! Use this when:

        - The MCP server was restarted and lost track of active sessions
        - Devices are stuck and normal cleanup doesn't work
        - You want to start fresh with no MeetBot devices

        For normal cleanup that preserves active meetings, use
        `meet_notes_cleanup_audio()` instead.
        """
        return await _meet_notes_cleanup_all_devices_impl()

    @registry.tool()
    async def meet_notes_list_meetings(
        days: int = 7,
        calendar_id: str = "",
    ) -> str:
        """
        List recent meeting notes.

        Args:
            days: Number of days to look back (default: 7)
            calendar_id: Filter by calendar (optional)
        """
        return await _meet_notes_list_meetings_impl(days, calendar_id)

    @registry.tool()
    async def meet_notes_get_transcript(
        meeting_id: int,
    ) -> str:
        """
        Get the full transcript for a meeting.

        Args:
            meeting_id: Meeting ID from meet_notes_list_meetings
        """
        return await _meet_notes_get_transcript_impl(meeting_id)

    @registry.tool()
    async def meet_notes_search(
        query: str,
        meeting_id: int = 0,
    ) -> str:
        """
        Search meeting transcripts.

        Full-text search across all captured meeting notes.

        Args:
            query: Search query
            meeting_id: Limit search to specific meeting (optional)
        """
        return await _meet_notes_search_impl(query, meeting_id)

    @registry.tool()
    async def meet_notes_stats() -> str:
        """
        Get meeting notes statistics.

        Shows:
        - Number of meetings captured
        - Total transcript entries
        - Database size
        - Calendars monitored
        """
        return await _meet_notes_stats_impl()

    @registry.tool()
    async def meet_notes_export_state() -> str:
        """
        Export current state to JSON for the VS Code extension UI.

        This updates the state file that the Meetings tab reads from.
        Call this to refresh the UI with current data.

        Returns:
            Confirmation and preview of exported state
        """
        return await _meet_notes_export_state_impl()

    # ==================== VOICE PIPELINE TOOLS ====================

    @registry.tool()
    async def meet_send_message(
        text: str,
        session_id: str = "",
    ) -> str:
        """
        Send a typed message to an active meeting via text-to-speech.

        This allows you to type a message and have it spoken in the meeting
        using the Piper TTS engine. The audio is played through the virtual
        microphone that Chrome is using.

        Args:
            text: The message to speak in the meeting
            session_id: Optional meeting session ID (uses first active meeting if empty)

        Examples:
            meet_send_message("I'll be right back")
            meet_send_message("Can you repeat that?", session_id="abc123")
        """
        return await _meet_send_message_impl(text, session_id)

    @registry.tool()
    async def meet_voice_pipeline_status() -> str:
        """
        Get status of voice interaction pipelines.

        Shows statistics for active voice pipelines including:
        - Number of utterances processed
        - Wake word detections
        - Response latency metrics
        - Error counts
        """
        return await _meet_voice_pipeline_status_impl()


def register_tools(server: FastMCP) -> int:
    """Register Meet Bot tools with the MCP server."""
    registry = ToolRegistry(server)

    # Schedule startup cleanup to run in the background
    # This ensures orphaned devices from previous sessions are cleaned up
    asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(_run_startup_cleanup()))

    # Start periodic cleanup task
    _start_periodic_cleanup()

    _register_bot_tools(registry)
    _register_notes_tools(registry)
    _register_maintenance_tools(registry)

    return registry.count
