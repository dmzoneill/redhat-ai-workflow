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
from datetime import datetime, timedelta
from typing import Optional

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

# Import centralized paths
try:
    from server.paths import MEETBOT_DATA_DIR, MEETBOT_STATE_FILE
except ImportError:
    # Fallback for standalone usage
    from pathlib import Path

    MEETBOT_DATA_DIR = Path.home() / ".config" / "aa-workflow" / "meet_bot"
    MEETBOT_STATE_FILE = MEETBOT_DATA_DIR / "state.json"

from server.tool_registry import ToolRegistry
from tool_modules.aa_meet_bot.src.audio_output import AudioOutputManager
from tool_modules.aa_meet_bot.src.browser_controller import CaptionEntry, GoogleMeetController
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.jira_preloader import get_jira_preloader
from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder
from tool_modules.aa_meet_bot.src.meeting_scheduler import MeetingScheduler, init_scheduler
from tool_modules.aa_meet_bot.src.notes_bot import NotesBot, NotesBotManager, get_bot_manager
from tool_modules.aa_meet_bot.src.notes_database import MeetingNotesDB, init_notes_db
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.video_generator import get_video_generator
from tool_modules.aa_meet_bot.src.virtual_devices import VirtualDeviceManager
from tool_modules.aa_meet_bot.src.voice_pipeline import get_pipeline_manager
from tool_modules.aa_meet_bot.src.wake_word import WakeWordManager

logger = logging.getLogger(__name__)

# Global state
_controller: Optional[GoogleMeetController] = None
_device_manager: Optional[VirtualDeviceManager] = None
_wake_word_manager: Optional[WakeWordManager] = None
_approved_meetings: dict[str, dict] = {}  # meeting_id -> meeting info
_MAX_APPROVED_MEETINGS = 50  # Prevent unbounded memory growth

# Notes bot state
_notes_bot: Optional[NotesBot] = None  # Legacy single-bot mode
_bot_manager: Optional[NotesBotManager] = None  # Multi-meeting mode
_scheduler: Optional[MeetingScheduler] = None
_notes_db: Optional[MeetingNotesDB] = None


async def _get_controller() -> GoogleMeetController:
    """Get or create the browser controller."""
    global _controller
    if _controller is None:
        _controller = GoogleMeetController()
        await _controller.initialize()
    return _controller


async def _get_device_manager() -> VirtualDeviceManager:
    """Get or create the device manager."""
    global _device_manager
    if _device_manager is None:
        _device_manager = VirtualDeviceManager()
    return _device_manager


async def _get_wake_word_manager() -> WakeWordManager:
    """Get or create the wake word manager."""
    global _wake_word_manager
    if _wake_word_manager is None:
        _wake_word_manager = WakeWordManager()
        await _wake_word_manager.initialize()
    return _wake_word_manager


# ==================== TOOL IMPLEMENTATIONS ====================


async def _meet_bot_status_impl() -> str:
    """Get current status of the Meet Bot system."""
    config = get_config()
    lines = [
        "# Meet Bot Status",
        "",
        "## Configuration",
        f"- **Bot Account:** {config.bot_account.email}",
        f'- **Wake Word:** "{config.wake_word}"',
        f"- **Avatar Image:** {config.avatar.face_image}",
        "",
    ]

    # Virtual device status
    device_manager = await _get_device_manager()
    status = await device_manager.get_status()

    lines.append("## Virtual Devices")
    lines.append(f"- **Audio Sink:** {'✅ Ready' if status.audio_sink_ready else '❌ Not Ready'}")
    lines.append(f"- **Audio Source:** {'✅ Ready' if status.audio_source_ready else '❌ Not Ready'}")
    lines.append(f"- **Virtual Camera:** {'✅ Ready' if status.video_device_ready else '❌ Not Ready'}")
    if status.video_device_path:
        lines.append(f"  - Device: {status.video_device_path}")
    lines.append("")

    # Meeting status
    if _controller and _controller.state and _controller.state.joined:
        state = _controller.state
        lines.append("## Active Meeting")
        lines.append(f"- **Meeting ID:** {state.meeting_id}")
        lines.append(f"- **Captions:** {'✅ Enabled' if state.captions_enabled else '❌ Disabled'}")
        lines.append(f"- **Muted:** {'Yes' if state.muted else 'No'}")
        lines.append(f"- **Captions Captured:** {len(state.caption_buffer)}")
    else:
        lines.append("## Meeting Status")
        lines.append("- Not currently in a meeting")

    # Approved meetings
    lines.append("")
    lines.append("## Approved Meetings")
    if _approved_meetings:
        for meeting_id, info in _approved_meetings.items():
            lines.append(f"- **{info.get('title', meeting_id)}**")
            lines.append(f"  - URL: {info.get('url', 'N/A')}")
            lines.append(f"  - Time: {info.get('start_time', 'N/A')}")
    else:
        lines.append("- No meetings approved")

    return "\n".join(lines)


async def _meet_bot_setup_devices_impl() -> str:
    """Set up virtual audio and video devices."""
    device_manager = await _get_device_manager()
    status = await device_manager.setup_all()

    lines = ["# Virtual Device Setup", ""]

    if status.all_ready:
        lines.append("✅ **All devices ready!**")
        lines.append("")
        lines.append("## Devices Created")
        lines.append(f"- Audio Sink: meet_bot_sink (module {status.audio_sink_id})")
        lines.append(f"- Audio Source: meet_bot_source (module {status.audio_source_id})")
        lines.append(f"- Virtual Camera: {status.video_device_path}")
    else:
        lines.append("⚠️ **Some devices failed to initialize**")
        lines.append("")

        if status.audio_sink_ready:
            lines.append("✅ Audio Sink ready")
        else:
            lines.append("❌ Audio Sink failed")

        if status.audio_source_ready:
            lines.append("✅ Audio Source ready")
        else:
            lines.append("❌ Audio Source failed")

        if status.video_device_ready:
            lines.append(f"✅ Virtual Camera ready ({status.video_device_path})")
        else:
            lines.append("❌ Virtual Camera failed")

        if status.errors:
            lines.append("")
            lines.append("## Errors")
            for error in status.errors:
                lines.append(f"- {error}")

            lines.append("")
            lines.append("## Troubleshooting")
            lines.append("For v4l2loopback, run:")
            lines.append("```bash")
            lines.append("sudo modprobe v4l2loopback devices=1 video_nr=10 card_label=MeetBot_Camera exclusive_caps=1")
            lines.append("```")

    return "\n".join(lines)


async def _meet_bot_approve_meeting_impl(
    meeting_url: str,
    title: str = "",
    start_time: str = "",
) -> str:
    """
    Approve a meeting for the bot to join.

    Args:
        meeting_url: Google Meet URL (e.g., https://meet.google.com/xxx-xxxx-xxx)
        title: Optional meeting title
        start_time: Optional start time (ISO format)
    """
    import re

    # Extract meeting ID
    match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meeting_url)
    if not match:
        return f"❌ Invalid Google Meet URL: {meeting_url}"

    meeting_id = match.group(1)

    # Cleanup old approved meetings if over limit
    if len(_approved_meetings) >= _MAX_APPROVED_MEETINGS:
        # Remove oldest approved meetings
        sorted_meetings = sorted(
            _approved_meetings.items(),
            key=lambda x: x[1].get("approved_at", ""),
        )
        for old_id, _ in sorted_meetings[: len(_approved_meetings) - _MAX_APPROVED_MEETINGS + 1]:
            _approved_meetings.pop(old_id, None)

    _approved_meetings[meeting_id] = {
        "url": meeting_url,
        "title": title or f"Meeting {meeting_id}",
        "start_time": start_time or datetime.now().isoformat(),
        "approved_at": datetime.now().isoformat(),
    }

    return f"✅ Meeting approved: **{title or meeting_id}**\n\nURL: {meeting_url}\n\nThe bot can now join this meeting."


async def _meet_bot_join_meeting_impl(
    meeting_url: str = "",
    meeting_id: str = "",
    enable_voice: bool = True,
) -> str:
    """
    Join a Google Meet meeting.

    Args:
        meeting_url: Full Google Meet URL
        meeting_id: Or just the meeting ID (xxx-xxxx-xxx)
        enable_voice: Enable voice interaction pipeline (STT→LLM→TTS)
    """
    # Determine URL
    if meeting_url:
        url = meeting_url
    elif meeting_id:
        url = f"https://meet.google.com/{meeting_id}"
    else:
        # Check for approved meetings
        if _approved_meetings:
            # Join first approved meeting
            first_id = list(_approved_meetings.keys())[0]
            url = _approved_meetings[first_id]["url"]
        else:
            return "❌ No meeting URL provided and no approved meetings"

    # Extract meeting ID for approval check
    import re

    match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", url)
    if match:
        mid = match.group(1)
        if mid not in _approved_meetings:
            return f"❌ Meeting {mid} not approved. Use `meet_bot_approve_meeting` first."

    # Set up devices first
    device_manager = await _get_device_manager()
    status = await device_manager.get_status()

    if not status.all_ready:
        # Try to set up devices
        status = await device_manager.setup_all()
        if not status.all_ready:
            return "❌ Virtual devices not ready. Run `meet_bot_setup_devices` first."

    # Get controller and join
    controller = await _get_controller()

    # Set up wake word detection (caption-based fallback)
    wake_word_manager = await _get_wake_word_manager()

    def on_caption(entry: CaptionEntry):
        """Process captions for wake word."""
        event = wake_word_manager.process_caption(entry.speaker, entry.text)
        if event:
            logger.info(f"Wake word event from captions: {event}")
            # Note: Voice pipeline handles this if enabled

    success = await controller.join_meeting(url)

    if success:
        # Start caption capture with wake word detection
        await controller.start_caption_capture(on_caption)

        voice_status = "Disabled"
        if enable_voice:
            # Start the voice interaction pipeline
            try:
                from tool_modules.aa_meet_bot.src.voice_pipeline import VoicePipelineConfig, get_pipeline_manager

                config = get_config()
                pipe_path = controller.get_pipe_path()
                sink_name = controller.get_audio_devices().sink_name if controller.get_audio_devices() else None

                if pipe_path and sink_name:
                    pipeline_config = VoicePipelineConfig(
                        wake_word=config.wake_word,
                        stt_model="base",
                        stt_device="NPU",
                        llm_backend="gemini",
                        tts_backend="piper",
                    )

                    pipeline_manager = get_pipeline_manager()
                    instance_id = controller._instance_id
                    await pipeline_manager.create_pipeline(
                        instance_id=instance_id,
                        sink_name=sink_name,
                        pipe_path=pipe_path,
                        config=pipeline_config,
                        controller=controller,
                    )
                    voice_status = f'Enabled (wake word: "{config.wake_word}")'
                    logger.info(f"[VOICE] Voice pipeline started for meeting {controller.state.meeting_id}")
                else:
                    voice_status = "Failed (no audio devices)"
                    logger.warning("[VOICE] Could not start voice pipeline - no audio devices")
            except Exception as e:
                voice_status = f"Failed: {e}"
                logger.error(f"[VOICE] Failed to start voice pipeline: {e}")

        return (
            f"✅ **Joined meeting!**\n\nMeeting ID: {controller.state.meeting_id}\n"
            f"Captions: {'Enabled' if controller.state.captions_enabled else 'Disabled'}\n"
            f"Voice Interaction: {voice_status}\n\nListening for wake word..."
        )
    else:
        errors = controller.state.errors if controller.state else ["Unknown error"]
        return "❌ Failed to join meeting\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)


async def _meet_bot_leave_meeting_impl() -> str:
    """Leave the current meeting."""

    if not _controller or not _controller.state or not _controller.state.joined:
        return "❌ Not currently in a meeting"

    meeting_id = _controller.state.meeting_id
    caption_count = len(_controller.state.caption_buffer)
    instance_id = _controller._instance_id

    # Stop voice pipeline if running
    try:
        from tool_modules.aa_meet_bot.src.voice_pipeline import get_pipeline_manager

        pipeline_manager = get_pipeline_manager()
        await pipeline_manager.stop_pipeline(instance_id)
        logger.info(f"[VOICE] Voice pipeline stopped for meeting {meeting_id}")
    except Exception as e:
        logger.warning(f"[VOICE] Error stopping voice pipeline: {e}")

    success = await _controller.leave_meeting()

    if success:
        return f"✅ Left meeting {meeting_id}\n\nCaptions captured: {caption_count}"
    else:
        return "❌ Failed to leave meeting"


async def _meet_bot_get_captions_impl(
    last_n: int = 20,
) -> str:
    """
    Get recent captions from the meeting.

    Args:
        last_n: Number of recent captions to return
    """

    if not _controller or not _controller.state:
        return "❌ Not in a meeting"

    captions = _controller.state.caption_buffer[-last_n:]

    if not captions:
        return "No captions captured yet"

    lines = [f"# Recent Captions (last {len(captions)})", ""]
    for cap in captions:
        lines.append(f"**{cap.speaker}** ({cap.timestamp.strftime('%H:%M:%S')}): {cap.text}")

    return "\n".join(lines)


async def _meet_bot_test_avatar_impl() -> str:
    """Test that the avatar image is valid for lip-sync."""
    config = get_config()

    if not config.avatar.face_image.exists():
        return f"❌ Avatar image not found: {config.avatar.face_image}"

    try:
        from PIL import Image

        img = Image.open(config.avatar.face_image)
        width, height = img.size

        lines = [
            "# Avatar Image Check",
            "",
            f"✅ **Image found:** {config.avatar.face_image}",
            f"- **Dimensions:** {width}x{height}",
            f"- **Format:** {img.format}",
            f"- **Mode:** {img.mode}",
            "",
        ]

        # Check if dimensions are suitable
        if width >= 256 and height >= 256:
            lines.append("✅ Resolution suitable for lip-sync")
        else:
            lines.append("⚠️ Resolution may be too low for good lip-sync quality")

        # Check aspect ratio
        aspect = width / height
        if 0.8 <= aspect <= 1.2:
            lines.append("✅ Aspect ratio suitable (close to square)")
        else:
            lines.append("⚠️ Image should be closer to square for best results")

        return "\n".join(lines)

    except ImportError:
        return "❌ PIL not installed. Run: uv add pillow"
    except Exception as e:
        return f"❌ Failed to check avatar image: {e}"


async def _meet_bot_synthesize_speech_impl(
    text: str,
    output_filename: str = "",
) -> str:
    """
    Synthesize speech using GPT-SoVITS voice cloning.

    Args:
        text: Text to synthesize
        output_filename: Optional output filename
    """
    engine = get_tts_engine()
    result = await engine.synthesize(text, output_filename or None)

    if result.success:
        return (
            "✅ **Speech synthesized!**\n\n"
            f'- **Text:** "{text}"\n'
            f"- **Output:** `{result.audio_path}`\n"
            f"- **Duration:** {result.duration_seconds:.2f}s\n"
            f"- **Sample Rate:** {result.sample_rate} Hz"
        )
    else:
        return f"❌ TTS failed: {result.error}"


async def _meet_bot_generate_video_impl(
    audio_path: str,
    output_filename: str = "",
) -> str:
    """
    Generate lip-sync avatar video from audio.

    Args:
        audio_path: Path to audio file
        output_filename: Optional output filename
    """
    from pathlib import Path

    audio = Path(audio_path)
    if not audio.exists():
        return f"❌ Audio file not found: {audio_path}"

    generator = get_video_generator()
    result = await generator.generate_video(audio, output_filename or None)

    if result.success:
        return (
            "✅ **Video generated!**\n\n"
            f"- **Source:** {result.source}\n"
            f"- **Output:** `{result.video_path}`\n"
            f"- **Duration:** {result.duration_seconds:.2f}s\n"
            f"- **Resolution:** {result.resolution[0]}x{result.resolution[1]}\n"
            f"- **FPS:** {result.fps}"
        )
    else:
        return f"❌ Video generation failed: {result.error}"


async def _meet_bot_respond_impl(
    text: str,
) -> str:
    """
    Generate a complete response (TTS + video) and play it.

    This is the main response function that:
    1. Synthesizes speech from text
    2. Generates lip-sync video
    3. Plays the video through the virtual camera

    Args:
        text: Response text to speak
    """
    lines = ["# Generating Response", "", f'**Text:** "{text}"', ""]

    # Step 1: TTS
    lines.append("## Step 1: Speech Synthesis")
    tts_engine = get_tts_engine()
    tts_result = await tts_engine.synthesize(text)

    if not tts_result.success:
        return f"❌ TTS failed: {tts_result.error}"

    lines.append(f"✅ Audio: `{tts_result.audio_path}` ({tts_result.duration_seconds:.2f}s)")
    lines.append("")

    # Step 2: Video
    lines.append("## Step 2: Video Generation")
    video_generator = get_video_generator()
    video_result = await video_generator.generate_video(tts_result.audio_path)

    if not video_result.success:
        lines.append(f"⚠️ Video failed: {video_result.error}")
        lines.append("Falling back to audio-only response")
        # TODO: Play audio only
    else:
        lines.append(f"✅ Video: `{video_result.video_path}` ({video_result.source})")
        lines.append("")

        # Step 3: Play (TODO: implement playback through virtual devices)
        lines.append("## Step 3: Playback")
        lines.append("⏳ Ready to play through virtual camera/microphone")
        lines.append(f"- Video: {video_result.video_path}")
        lines.append(f"- Duration: {video_result.duration_seconds:.2f}s")

    return "\n".join(lines)


async def _meet_bot_preload_jira_impl(
    project: str = "AAP",
) -> str:
    """
    Preload Jira context for the current sprint.

    Args:
        project: Jira project key (default: AAP)
    """
    preloader = get_jira_preloader()
    success = await preloader.preload(project)

    if success:
        lines = [
            "# Jira Context Loaded",
            "",
            f"**Project:** {project}",
            f"**My Issues:** {len(preloader.my_issues)}",
            f"**Sprint Issues:** {len(preloader.issues)}",
            "",
            "## Status Summary",
            preloader.get_status_summary(),
            "",
            "## My Issues",
        ]

        for issue in preloader.my_issues[:5]:
            lines.append(f"- **{issue.key}**: {issue.summary[:50]}... ({issue.status})")

        if len(preloader.my_issues) > 5:
            lines.append(f"  ... and {len(preloader.my_issues) - 5} more")

        return "\n".join(lines)
    else:
        return "❌ Failed to load Jira context. Check rh-issue CLI is configured."


async def _meet_bot_ask_llm_impl(
    question: str,
    speaker: str = "Someone",
) -> str:
    """
    Ask the LLM a question (for testing).

    Args:
        question: The question to ask
        speaker: Who is asking
    """
    responder = get_llm_responder()

    # Check Ollama is available
    if not await responder.initialize():
        return "❌ Ollama not available. Make sure it's running: `ollama serve`"

    response = await responder.generate_response(question, speaker)

    if response.success:
        return f"**{speaker} asked:** {question}\n\n**Response:** {response.text}"
    else:
        return f"❌ LLM failed: {response.error}"


async def _meet_bot_full_response_impl(
    question: str,
    speaker: str = "Someone",
) -> str:
    """
    Full pipeline: LLM → TTS → Video.

    This simulates what happens when someone says "David, [question]".

    Args:
        question: The question/command
        speaker: Who asked
    """
    lines = ["# Full Response Pipeline", "", f'**{speaker} asked:** "{question}"', ""]

    # Step 1: LLM
    lines.append("## Step 1: Generate Response (LLM)")
    responder = get_llm_responder()

    if not await responder.initialize():
        return "❌ Ollama not available. Run: `ollama serve`"

    llm_response = await responder.generate_response(question, speaker)

    if not llm_response.success:
        return f"❌ LLM failed: {llm_response.error}"

    lines.append(f'✅ Response: "{llm_response.text}"')
    lines.append("")

    # Step 2: TTS
    lines.append("## Step 2: Speech Synthesis (GPT-SoVITS)")
    tts_engine = get_tts_engine()

    if not await tts_engine.initialize():
        lines.append("❌ TTS not available")
        return "\n".join(lines)

    tts_result = await tts_engine.synthesize(llm_response.text)

    if not tts_result.success:
        lines.append(f"❌ TTS failed: {tts_result.error}")
        return "\n".join(lines)

    lines.append(f"✅ Audio: `{tts_result.audio_path}` ({tts_result.duration_seconds:.2f}s)")
    lines.append("")

    # Step 3: Video
    lines.append("## Step 3: Video Generation")
    video_generator = get_video_generator()
    await video_generator.initialize()

    video_result = await video_generator.generate_video(tts_result.audio_path)

    if video_result.success:
        lines.append(f"✅ Video: `{video_result.video_path}` ({video_result.source})")
    else:
        lines.append(f"⚠️ Video failed: {video_result.error} (audio-only)")

    lines.append("")
    lines.append("## Summary")
    lines.append(f"- **Question:** {question}")
    lines.append(f"- **Response:** {llm_response.text}")
    lines.append(f"- **Audio:** {tts_result.audio_path}")
    if video_result.success:
        lines.append(f"- **Video:** {video_result.video_path}")

    return "\n".join(lines)


# ==================== NOTES BOT IMPLEMENTATIONS ====================


async def _get_notes_db() -> MeetingNotesDB:
    """Get or create the notes database."""
    global _notes_db
    if _notes_db is None:
        _notes_db = await init_notes_db()
    return _notes_db


async def _get_notes_bot() -> NotesBot:
    """Get or create the notes bot (legacy single-bot mode)."""
    global _notes_bot
    if _notes_bot is None:
        bot = NotesBot()
        success = await bot.initialize()
        if not success:
            # Return bot with errors so caller can report them
            _notes_bot = bot
        else:
            _notes_bot = bot
    return _notes_bot


async def _get_bot_manager() -> NotesBotManager:
    """Get or create the bot manager for multi-meeting support."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = get_bot_manager()
    return _bot_manager


async def _get_scheduler() -> MeetingScheduler:
    """Get or create the scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = await init_scheduler()
    return _scheduler


async def _meet_notes_start_scheduler_impl() -> str:
    """Start the meeting scheduler."""
    scheduler = await _get_scheduler()

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

    if _scheduler is None or not _scheduler.state.running:
        return "⚠️ Scheduler is not running."

    await _scheduler.stop()

    return "✅ **Meeting Scheduler Stopped**\n\nThe bot will no longer auto-join meetings."


async def _meet_notes_scheduler_status_impl() -> str:
    """Get scheduler status."""
    scheduler = await _get_scheduler()
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
    scheduler = await _get_scheduler()

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
    else:
        return f"❌ Failed to add calendar: {calendar_id}"


async def _meet_notes_remove_calendar_impl(calendar_id: str) -> str:
    """Remove a calendar from monitoring."""
    scheduler = await _get_scheduler()

    success = await scheduler.remove_calendar(calendar_id)

    if success:
        return f"✅ Calendar removed: `{calendar_id}`"
    else:
        return f"❌ Calendar not found: `{calendar_id}`"


async def _meet_notes_list_calendars_impl() -> str:
    """List monitored calendars."""
    scheduler = await _get_scheduler()
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
    scheduled_end: Optional[datetime] = None,
    duration_minutes: int = 0,
    grace_period_minutes: int = 5,
) -> str:
    """Join a meeting immediately (supports multiple concurrent meetings)."""
    try:
        manager = await _get_bot_manager()
    except Exception as e:
        return f"❌ Failed to initialize bot manager: {e}"

    # Calculate scheduled_end from duration if not provided
    if not scheduled_end and duration_minutes > 0:
        scheduled_end = datetime.now() + timedelta(minutes=duration_minutes)

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
    else:
        if not errors:
            errors = ["Unknown error - check browser controller logs"]
        return "❌ Failed to join meeting\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)


async def _meet_notes_leave_impl(session_id: str = "") -> str:
    """Leave a meeting by session ID, or leave all if no ID provided."""

    manager = await _get_bot_manager()

    if not session_id:
        # If no session ID, check how many active meetings
        active_ids = manager.get_active_session_ids()
        if not active_ids:
            return "⚠️ Not in any meetings."
        elif len(active_ids) == 1:
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
    manager = await _get_bot_manager()

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
            lines.append(f"- ✅ {result.get('title', 'Unknown')} " f"({result.get('captions_captured', 0)} captions)")

    return "\n".join(lines)


async def _meet_notes_active_meetings_impl() -> str:
    """List all active meetings."""
    manager = await _get_bot_manager()

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


async def _meet_notes_cleanup_impl() -> str:
    """Clean up hung browser instances."""
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

    # Get all controller instances
    instances = GoogleMeetController.get_all_instances()

    if not instances:
        return "✅ No browser instances found."

    lines = [
        f"🔍 **Browser Instance Status ({len(instances)})**",
        "",
    ]

    now = datetime.now()
    hung_instances = []

    for instance_id, controller in instances.items():
        info = controller.get_instance_info()
        age_minutes = (now - controller._created_at).total_seconds() / 60
        inactive_minutes = (now - controller._last_activity).total_seconds() / 60

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
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

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
    from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices, get_meetbot_device_count

    # Get counts before cleanup
    before = await get_meetbot_device_count()

    # Get active instance IDs from the bot manager
    active_ids = set()
    if _bot_manager:
        for session in _bot_manager._sessions.values():
            if session.bot._controller:
                active_ids.add(session.bot._controller._instance_id)

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
    from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices, get_meetbot_device_count

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
    from datetime import datetime, timedelta

    db = await _get_notes_db()

    since = datetime.now() - timedelta(days=days)
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
    db = await _get_notes_db()

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
    db = await _get_notes_db()

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

    for _mid, matches in by_meeting.items():
        first = matches[0]
        lines.append(f"## {first['meeting_title']}")
        if first["meeting_date"]:
            lines.append(f"*{first['meeting_date']}*")
        lines.append("")

        for m in matches[:5]:  # Limit matches per meeting
            lines.append(f"- **{m['speaker']}**: \"{m['text']}\"")

        if len(matches) > 5:
            lines.append(f"  ... and {len(matches) - 5} more matches")

        lines.append("")

    return "\n".join(lines)


async def _meet_notes_stats_impl() -> str:
    """Get meeting notes statistics."""
    db = await _get_notes_db()
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


async def _meet_notes_export_state_impl() -> str:
    """Export current state to JSON for the VS Code extension UI."""
    import json
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    db = await _get_notes_db()

    # Get calendars
    calendars = await db.get_calendars(enabled_only=False)

    # Get recent meetings from database
    since = datetime.now() - timedelta(days=7)
    meetings = await db.list_meetings(since=since, limit=10)

    # Fetch upcoming meetings from Google Calendar for each monitored calendar
    upcoming_meetings = []
    try:
        from tool_modules.aa_google_calendar.src.tools_basic import get_calendar_service

        service, error = get_calendar_service()
        if service and not error:
            tz = ZoneInfo("Europe/Dublin")
            now = datetime.now(tz)
            time_min = now.isoformat()
            time_max = (now + timedelta(days=2)).isoformat()  # Next 2 days

            for cal in calendars:
                if not cal.enabled:
                    continue
                try:
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

                    for event in events_result.get("items", []):
                        # Only include events with Meet links
                        meet_url = None
                        if event.get("conferenceData", {}).get("entryPoints"):
                            for entry in event["conferenceData"]["entryPoints"]:
                                if entry.get("entryPointType") == "video":
                                    meet_url = entry.get("uri", "")
                                    break

                        if not meet_url:
                            continue

                        start = event["start"].get("dateTime", event["start"].get("date"))

                        upcoming_meetings.append(
                            {
                                "id": event.get("id", ""),
                                "title": event.get("summary", "No title"),
                                "url": meet_url,
                                "startTime": start,
                                "endTime": event["end"].get("dateTime", event["end"].get("date")),
                                "organizer": event.get("organizer", {}).get("email", ""),
                                "attendees": [a.get("email", "") for a in event.get("attendees", [])[:5]],
                                "status": "pending" if cal.auto_join else "pending",
                                "calendarName": cal.name,
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch events from {cal.name}: {e}")
    except ImportError:
        pass  # Google Calendar not available

    # Sort by start time
    upcoming_meetings.sort(key=lambda x: x.get("startTime", ""))

    # Get scheduler status
    scheduler_running = _scheduler is not None and _scheduler.state.running

    # Get current meetings status (supports multiple concurrent meetings)
    current_meetings = []
    all_captions = []

    if _bot_manager:
        statuses = await _bot_manager.get_all_statuses()
        for status in statuses:
            if status.get("status") == "capturing":
                # Get scheduled end and time remaining
                scheduled_end = status.get("scheduled_end")
                time_remaining = status.get("time_remaining_minutes")

                current_meetings.append(
                    {
                        "id": str(status.get("meeting_id", "")),
                        "sessionId": status.get("session_id", ""),
                        "title": status.get("title", "Unknown"),
                        "url": status.get("meet_url", ""),
                        "startTime": (
                            status.get("joined_at", datetime.now()).isoformat()
                            if isinstance(status.get("joined_at"), datetime)
                            else datetime.now().isoformat()
                        ),
                        "organizer": "",
                        "attendees": [],
                        "status": "joined",
                        "captionsCount": status.get("captions_captured", 0),
                        "durationMinutes": status.get("duration_minutes", 0),
                        "scheduledEnd": scheduled_end,
                        "timeRemainingMinutes": time_remaining,
                        "gracePeriodMinutes": status.get("grace_period_minutes", 5),
                    }
                )

                # Get captions from the bot's buffer
                bot = _bot_manager.get_bot(status.get("session_id", ""))
                if bot and bot.state.transcript_buffer:
                    for entry in bot.state.transcript_buffer[-30:]:  # Last 30 per meeting
                        all_captions.append(
                            {
                                "speaker": entry.speaker,
                                "text": entry.text,
                                "timestamp": (
                                    entry.timestamp.isoformat()
                                    if isinstance(entry.timestamp, datetime)
                                    else str(entry.timestamp)
                                ),
                                "sessionId": status.get("session_id", ""),
                                "meetingTitle": status.get("title", "Unknown"),
                            }
                        )

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
                "date": m.scheduled_start.strftime("%Y-%m-%d %H:%M") if m.scheduled_start else "",
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

    # Write to state file
    MEETBOT_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(MEETBOT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    return (
        f"✅ State exported to {MEETBOT_STATE_FILE}\n\n"
        f"Found {len(upcoming_meetings)} upcoming meetings with Meet links."
    )


# ==================== VOICE PIPELINE IMPLEMENTATIONS ====================


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
    from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine

    manager = await _get_bot_manager()

    # Find the target meeting
    if session_id:
        bot = manager.get_bot(session_id)
        if not bot:
            return f"❌ Meeting session not found: {session_id}"
    else:
        # Use first active meeting
        active_ids = manager.get_active_session_ids()
        if not active_ids:
            return "❌ No active meetings. Join a meeting first."
        session_id = active_ids[0]
        bot = manager.get_bot(session_id)

    if not bot or not bot._controller:
        return "❌ Meeting controller not available"

    # Get the pipe path for audio output
    pipe_path = bot._controller.get_pipe_path()
    if not pipe_path:
        return "❌ Audio output not available (no pipe path)"

    try:
        # Synthesize speech first (before unmuting)
        tts = get_tts_engine(backend="piper")
        if not await tts.initialize():
            return "❌ TTS engine not available"

        tts_result = await tts.synthesize(text)

        if not tts_result.success:
            return f"❌ TTS failed: {tts_result.error}"

        # Unmute the microphone before speaking
        controller = bot._controller
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
            return "✅ Message sent to meeting: \"{text[:50]}{'...' if len(text) > 50 else ''}\""
        else:
            return "❌ Failed to play audio to meeting"

    except Exception as e:
        logger.error(f"Send message failed: {e}")
        # Try to ensure we're muted even on error
        try:
            if bot and bot._controller:
                await bot._controller.mute()
        except Exception:
            pass
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

_startup_cleanup_done = False
_cleanup_task: Optional[asyncio.Task] = None


async def _run_startup_cleanup() -> None:
    """
    Clean up orphaned MeetBot devices on startup.

    This runs once when the MCP server starts to remove any devices
    left over from previous sessions that weren't properly cleaned up.
    """
    global _startup_cleanup_done
    if _startup_cleanup_done:
        return

    _startup_cleanup_done = True

    try:
        from tool_modules.aa_meet_bot.src.virtual_devices import (
            cleanup_orphaned_meetbot_devices,
            get_meetbot_device_count,
        )

        # Check if there are any orphaned devices
        counts = await get_meetbot_device_count()
        total_devices = counts["module_count"] + counts["pipe_count"] + counts["video_count"]

        if total_devices == 0:
            logger.info("🔊 MeetBot startup: No orphaned devices found")
            return

        logger.info(
            f"🔊 MeetBot startup: Found {total_devices} orphaned devices "
            f"(modules={counts['module_count']}, pipes={counts['pipe_count']}, video={counts['video_count']})"
        )

        # Clean up all orphaned devices (no active sessions on startup)
        results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

        removed_count = (
            len(results.get("removed_modules", []))
            + len(results.get("removed_pipes", []))
            + len(results.get("removed_video_devices", []))
        )

        if removed_count > 0:
            logger.info(f"🔊 MeetBot startup: Cleaned up {removed_count} orphaned devices")
        else:
            logger.info("🔊 MeetBot startup: No devices needed cleanup")

        if results.get("errors"):
            for err in results["errors"]:
                logger.warning(f"🔊 MeetBot startup cleanup error: {err}")

    except Exception as e:
        logger.error(f"🔊 MeetBot startup cleanup failed: {e}")


async def _periodic_cleanup_task() -> None:
    """
    Background task that periodically cleans up orphaned devices.

    Runs every 5 minutes to catch any devices that weren't properly
    cleaned up due to crashes or unexpected termination.
    """
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes

            # Get active instance IDs from the bot manager
            active_ids = set()
            if _bot_manager:
                for session in _bot_manager._sessions.values():
                    if session.bot._controller:
                        active_ids.add(session.bot._controller._instance_id)

            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
                get_meetbot_device_count,
            )

            # Check if cleanup is needed
            counts = await get_meetbot_device_count()
            expected_modules = len(active_ids) * 2  # Each instance has sink + source

            if counts["module_count"] > expected_modules:
                logger.info(
                    f"🔊 Periodic cleanup: {counts['module_count']} modules but only "
                    f"{len(active_ids)} active meetings (expected ~{expected_modules})"
                )
                results = await cleanup_orphaned_meetbot_devices(active_ids)

                if results.get("removed_modules") or results.get("removed_pipes"):
                    logger.info(
                        f"🔊 Periodic cleanup: Removed {len(results.get('removed_modules', []))} modules, "
                        f"{len(results.get('removed_pipes', []))} pipes"
                    )

        except asyncio.CancelledError:
            logger.info("🔊 Periodic cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"🔊 Periodic cleanup error: {e}")


def _start_periodic_cleanup() -> None:
    """Start the periodic cleanup background task."""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_periodic_cleanup_task())
        logger.info("🔊 Started periodic device cleanup task")


# ==================== TOOL REGISTRATION ====================


def register_tools(server: FastMCP) -> int:
    """Register Meet Bot tools with the MCP server."""
    registry = ToolRegistry(server)

    # Schedule startup cleanup to run in the background
    # This ensures orphaned devices from previous sessions are cleaned up
    asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(_run_startup_cleanup()))

    # Start periodic cleanup task
    _start_periodic_cleanup()

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

    # ==================== NOTES BOT TOOLS ====================

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

    return registry.count
