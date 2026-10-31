"""Meet Bot core tool implementations: devices, joining, captions, avatar and voice."""

import importlib
import logging
import re
from pathlib import Path

from tool_modules.aa_meet_bot.src.browser_controller import (
    CaptionEntry,
)
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.jira_preloader import get_jira_preloader
from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder
from tool_modules.aa_meet_bot.src.meet_bot_state import (
    BOT,
    MAX_APPROVED_MEETINGS,
    MEET_ERRORS,
    ensure_controller,
    ensure_device_manager,
    ensure_wake_word_manager,
    local_now,
)
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.video_generator import get_video_generator
from tool_modules.aa_meet_bot.src.voice_pipeline import VoicePipelineConfig, get_pipeline_manager

_MEET_ID_RE = re.compile(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")

logger = logging.getLogger(__name__)


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
    device_manager = await ensure_device_manager()
    status = await device_manager.get_status()

    lines.append("## Virtual Devices")
    lines.append(f"- **Audio Sink:** {'✅ Ready' if status.audio_sink_ready else '❌ Not Ready'}")
    lines.append(f"- **Audio Source:** {'✅ Ready' if status.audio_source_ready else '❌ Not Ready'}")
    lines.append(f"- **Virtual Camera:** {'✅ Ready' if status.video_device_ready else '❌ Not Ready'}")
    if status.video_device_path:
        lines.append(f"  - Device: {status.video_device_path}")
    lines.append("")

    # Meeting status
    if BOT.controller and BOT.controller.state and BOT.controller.state.joined:
        state = BOT.controller.state
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
    if BOT.approved_meetings:
        for meeting_id, info in BOT.approved_meetings.items():
            lines.append(f"- **{info.get('title', meeting_id)}**")
            lines.append(f"  - URL: {info.get('url', 'N/A')}")
            lines.append(f"  - Time: {info.get('start_time', 'N/A')}")
    else:
        lines.append("- No meetings approved")

    return "\n".join(lines)


async def _meet_bot_setup_devices_impl() -> str:
    """Set up virtual audio and video devices."""
    device_manager = await ensure_device_manager()
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
    # Extract meeting ID
    match = _MEET_ID_RE.search(meeting_url)
    if not match:
        return f"❌ Invalid Google Meet URL: {meeting_url}"

    meeting_id = match.group(1)

    # Cleanup old approved meetings if over limit
    if len(BOT.approved_meetings) >= MAX_APPROVED_MEETINGS:
        # Remove oldest approved meetings
        sorted_meetings = sorted(
            BOT.approved_meetings.items(),
            key=lambda x: x[1].get("approved_at", ""),
        )
        for old_id, _ in sorted_meetings[: len(BOT.approved_meetings) - MAX_APPROVED_MEETINGS + 1]:
            BOT.approved_meetings.pop(old_id, None)

    BOT.approved_meetings[meeting_id] = {
        "url": meeting_url,
        "title": title or f"Meeting {meeting_id}",
        "start_time": start_time or local_now().isoformat(),
        "approved_at": local_now().isoformat(),
    }

    return f"✅ Meeting approved: **{title or meeting_id}**\n\nURL: {meeting_url}\n\nThe bot can now join this meeting."


def _resolve_join_url(meeting_url: str, meeting_id: str) -> tuple[str, str | None]:
    """Pick the URL to join and check it is approved; returns (url, error)."""
    if meeting_url:
        url = meeting_url
    elif meeting_id:
        url = f"https://meet.google.com/{meeting_id}"
    elif BOT.approved_meetings:
        # Join first approved meeting
        first_id = next(iter(BOT.approved_meetings))
        url = BOT.approved_meetings[first_id]["url"]
    else:
        return "", "❌ No meeting URL provided and no approved meetings"

    # Extract meeting ID for approval check
    match = _MEET_ID_RE.search(url)
    if match and match.group(1) not in BOT.approved_meetings:
        return url, f"❌ Meeting {match.group(1)} not approved. Use `meet_bot_approve_meeting` first."
    return url, None


async def _start_voice_pipeline(controller) -> str:
    """Start the voice interaction pipeline for a joined meeting; returns a status line."""
    try:
        config = get_config()
        pipe_path = controller.get_pipe_path()
        devices = controller.get_audio_devices()
        sink_name = devices.sink_name if devices else None

        if not (pipe_path and sink_name):
            logger.warning("[VOICE] Could not start voice pipeline - no audio devices")
            return "Failed (no audio devices)"

        pipeline_config = VoicePipelineConfig(
            wake_word=config.wake_word,
            stt_model="base",
            stt_device="NPU",
            llm_backend="gemini",
            tts_backend="piper",
        )
        await get_pipeline_manager().create_pipeline(
            instance_id=controller.instance_id,
            sink_name=sink_name,
            pipe_path=pipe_path,
            config=pipeline_config,
            controller=controller,
        )
        logger.info("[VOICE] Voice pipeline started for meeting %s", controller.state.meeting_id)
        return f'Enabled (wake word: "{config.wake_word}")'
    except MEET_ERRORS as e:
        logger.error("[VOICE] Failed to start voice pipeline: %s", e)
        return f"Failed: {e}"


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
    url, error = _resolve_join_url(meeting_url, meeting_id)
    if error:
        return error

    # Set up devices first
    device_manager = await ensure_device_manager()
    status = await device_manager.get_status()

    if not status.all_ready:
        # Try to set up devices
        status = await device_manager.setup_all()
        if not status.all_ready:
            return "❌ Virtual devices not ready. Run `meet_bot_setup_devices` first."

    # Get controller and join
    controller = await ensure_controller()

    # Set up wake word detection (caption-based fallback)
    wake_word_manager = await ensure_wake_word_manager()

    def on_caption(entry: CaptionEntry):
        """Process captions for wake word."""
        event = wake_word_manager.process_caption(entry.speaker, entry.text)
        if event:
            logger.info("Wake word event from captions: %s", event)
            # Note: Voice pipeline handles this if enabled

    success = await controller.join_meeting(url)

    if success:
        # Start caption capture with wake word detection
        await controller.start_caption_capture(on_caption)

        voice_status = await _start_voice_pipeline(controller) if enable_voice else "Disabled"

        return (
            f"✅ **Joined meeting!**\n\nMeeting ID: {controller.state.meeting_id}\n"
            f"Captions: {'Enabled' if controller.state.captions_enabled else 'Disabled'}\n"
            f"Voice Interaction: {voice_status}\n\nListening for wake word..."
        )
    errors = controller.state.errors if controller.state else ["Unknown error"]
    return "❌ Failed to join meeting\n\nErrors:\n" + "\n".join(f"- {e}" for e in errors)


async def _meet_bot_leave_meeting_impl() -> str:
    """Leave the current meeting."""

    if not BOT.controller or not BOT.controller.state or not BOT.controller.state.joined:
        return "❌ Not currently in a meeting"

    meeting_id = BOT.controller.state.meeting_id
    caption_count = len(BOT.controller.state.caption_buffer)
    instance_id = BOT.controller.instance_id

    # Stop voice pipeline if running
    try:
        pipeline_manager = get_pipeline_manager()
        await pipeline_manager.stop_pipeline(instance_id)
        logger.info("[VOICE] Voice pipeline stopped for meeting %s", meeting_id)
    except MEET_ERRORS as e:
        logger.warning("[VOICE] Error stopping voice pipeline: %s", e)

    success = await BOT.controller.leave_meeting()

    if success:
        return f"✅ Left meeting {meeting_id}\n\nCaptions captured: {caption_count}"
    return "❌ Failed to leave meeting"


async def _meet_bot_get_captions_impl(
    last_n: int = 20,
) -> str:
    """
    Get recent captions from the meeting.

    Args:
        last_n: Number of recent captions to return
    """

    if not BOT.controller or not BOT.controller.state:
        return "❌ Not in a meeting"

    captions = BOT.controller.state.caption_buffer[-last_n:]

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
        pil_image = importlib.import_module("PIL.Image")

        img = pil_image.open(config.avatar.face_image)
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
    except MEET_ERRORS as e:
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
        # Audio-only playback is not wired up yet
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
