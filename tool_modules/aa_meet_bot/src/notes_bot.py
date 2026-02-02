"""
Notes Bot - Meeting note-taking mode with optional wake word detection.

A bot that:
- Joins Google Meet meetings
- Captures captions/transcription
- Saves to the meeting notes database
- Optionally detects wake words and can respond via LLM/TTS

This is the primary mode for the meeting scheduler.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.browser_controller import CaptionEntry, GoogleMeetController
from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.llm_responder import LLMResponder
from tool_modules.aa_meet_bot.src.notes_database import MeetingNote, MeetingNotesDB, TranscriptEntry, init_notes_db
from tool_modules.aa_meet_bot.src.wake_word import WakeWordEvent, WakeWordManager

# D-Bus client for video daemon communication
_video_dbus_available = False
try:
    from scripts.common.dbus_base import get_client

    _video_dbus_available = True
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dataclass
class NotesBotState:
    """Current state of the notes bot."""

    meeting_id: Optional[int] = None  # Database meeting ID
    meet_url: str = ""
    title: str = ""
    calendar_id: str = ""
    event_id: str = ""

    # Status
    status: str = "idle"  # idle, joining, capturing, leaving, error
    joined_at: Optional[datetime] = None

    # Transcript buffer (for batching writes)
    transcript_buffer: list[TranscriptEntry] = field(default_factory=list)
    buffer_flush_interval: float = 10.0  # Flush every 10 seconds
    last_flush: Optional[datetime] = None

    # Caption ID tracking for update-in-place
    caption_id_to_index: dict[int, int] = field(default_factory=dict)

    # Stats
    captions_captured: int = 0
    wake_word_triggers: int = 0
    errors: list[str] = field(default_factory=list)


class NotesBot:
    """
    Simple meeting note-taking bot.

    Joins meetings and captures transcripts without AI interaction.
    """

    def __init__(self, db: Optional[MeetingNotesDB] = None):
        """
        Initialize the notes bot.

        Args:
            db: Database instance. If None, uses global instance.
        """
        self.config = get_config()
        self.db = db
        self._controller: Optional[GoogleMeetController] = None
        self.state = NotesBotState()
        self._flush_task: Optional[asyncio.Task] = None
        self._screenshot_task: Optional[asyncio.Task] = None
        self._browser_monitor_task: Optional[asyncio.Task] = None
        self._on_caption_callback: Optional[Callable[[TranscriptEntry], None]] = None

        # Wake word detection
        self._wake_word_manager: Optional[WakeWordManager] = None
        self._on_wake_word_callback: Optional[Callable[[WakeWordEvent], None]] = None
        self._enable_wake_word: bool = True  # Enable by default
        self._wake_word_check_task: Optional[asyncio.Task] = None
        self._pending_wake_event: Optional[WakeWordEvent] = None

        # Interactive mode components
        self._llm_responder: Optional[LLMResponder] = None
        self._interactive_mode: bool = False
        self._responding: bool = False  # Prevent overlapping responses

        # NPU STT pipeline (alternative to Google Meet captions)
        self._npu_stt_pipeline = None
        self._use_npu_stt: bool = True  # Use NPU STT by default in interactive mode

        # Video daemon integration via D-Bus
        self._video_daemon_active: bool = False
        self._participant_poll_task: Optional[asyncio.Task] = None
        self._enable_video_integration: bool = _video_dbus_available

    async def initialize(self) -> bool:
        """Initialize the bot and database.

        Note: Browser is NOT started here - it's started lazily when joining a meeting.
        This allows the daemon to start quickly and sit idle without consuming resources.

        IMPORTANT: Runs cleanup on startup to remove any orphaned devices from previous sessions.
        """
        try:
            logger.info("=" * 60)
            logger.info("INIT: Initializing notes bot...")
            logger.info("=" * 60)

            # FIRST: Clean up any orphaned devices from previous sessions
            # This ensures we start with a clean slate
            logger.info("INIT: Running startup cleanup for orphaned devices...")
            await self._run_orphan_cleanup("INIT")

            # Initialize database
            if self.db is None:
                self.db = await init_notes_db()

            # Initialize wake word manager
            if self._enable_wake_word:
                self._wake_word_manager = WakeWordManager()
                await self._wake_word_manager.initialize()
                logger.info(f'Wake word detection enabled (wake word: "{self.config.wake_word}")')

            # Don't initialize browser here - do it lazily when joining a meeting
            # This prevents the daemon from opening Chrome on startup
            logger.info("INIT: Notes bot initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize notes bot: {e}")
            self.state.errors.append(str(e))
            return False

    async def _run_orphan_cleanup(self, context: str = "") -> dict:
        """Run comprehensive orphan cleanup.

        This is called at multiple points:
        - On bot initialization (startup)
        - Before joining a meeting
        - After leaving a meeting
        - When browser window closes
        - On bot shutdown

        Args:
            context: Label for logging (e.g., "INIT", "PRE-JOIN", "POST-LEAVE")

        Returns:
            Cleanup results dict
        """
        results = {
            "audio_captures_killed": 0,
            "modules_removed": 0,
            "processes_killed": 0,
            "pipes_removed": 0,
            "video_devices_removed": 0,
            "errors": [],
        }

        prefix = f"{context}: " if context else ""

        # 1. Kill any orphaned audio capture processes from our tracking
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            results["audio_captures_killed"] = killed
            if killed > 0:
                logger.info(f"{prefix}Killed {killed} tracked audio capture processes")
        except Exception as e:
            results["errors"].append(f"Audio capture cleanup: {e}")

        # 2. Run comprehensive orphan cleanup (modules, parec, pipes, video)
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices

            cleanup_results = await cleanup_orphaned_meetbot_devices(active_instance_ids=set())

            results["modules_removed"] = len(cleanup_results.get("removed_modules", []))
            results["processes_killed"] = len(cleanup_results.get("killed_processes", []))
            results["pipes_removed"] = len(cleanup_results.get("removed_pipes", []))
            results["video_devices_removed"] = len(cleanup_results.get("removed_video_devices", []))
            results["errors"].extend(cleanup_results.get("errors", []))

            total = (
                results["modules_removed"]
                + results["processes_killed"]
                + results["pipes_removed"]
                + results["video_devices_removed"]
            )

            if total > 0:
                logger.info(
                    f"{prefix}Orphan cleanup: "
                    f"{results['modules_removed']} modules, "
                    f"{results['processes_killed']} processes, "
                    f"{results['pipes_removed']} pipes, "
                    f"{results['video_devices_removed']} video devices"
                )
            else:
                logger.info(f"{prefix}Orphan cleanup: No orphaned devices found")

        except Exception as e:
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning(f"{prefix}Error during orphan cleanup: {e}")

        return results

    async def _ensure_browser(self, video_enabled: bool = False) -> bool:
        """Ensure browser controller is initialized (lazy initialization).

        Called before joining a meeting to start the browser if needed.

        Args:
            video_enabled: If True, start full AI video overlay. If False, start black screen.
        """
        if self._controller is not None:
            return True

        try:
            self._controller = GoogleMeetController()
            if not await self._controller.initialize(video_enabled=video_enabled):
                logger.error("Failed to initialize browser controller")
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append("Browser controller initialization failed")
                self._controller = None
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            self.state.errors.append(str(e))
            self._controller = None
            return False

    async def join_meeting(
        self,
        meet_url: str,
        title: str = "",
        calendar_id: str = "",
        event_id: str = "",
        description: str = "",
        organizer: str = "",
        attendees: Optional[list[str]] = None,
        mode: str = "notes",
        use_npu_stt: bool = True,  # Enable NPU STT by default for local transcription
        video_enabled: bool = False,  # Show full AI video overlay (default: black screen)
    ) -> bool:
        """
        Join a meeting and start capturing notes.

        Args:
            meet_url: Google Meet URL
            title: Meeting title
            calendar_id: Source calendar ID
            event_id: Google Calendar event ID
            description: Meeting description
            organizer: Meeting organizer email
            attendees: List of attendee emails
            mode: "notes" for passive capture, "interactive" for wake word + voice responses
            use_npu_stt: Use NPU-based STT instead of Google Meet captions (faster, local)
            video_enabled: If True, show full AI video overlay. If False, show black screen.

        Returns:
            True if successfully joined
        """
        logger.info("=" * 60)
        logger.info(f"JOIN: Starting to join meeting: {title or meet_url}")
        logger.info("=" * 60)

        # FIRST: Run cleanup before joining to ensure clean state
        # This catches any orphaned devices from previous sessions or crashes
        logger.info("JOIN: Running pre-join cleanup...")
        await self._run_orphan_cleanup("PRE-JOIN")

        # Set NPU STT flag and video flag
        self._use_npu_stt = use_npu_stt
        self._video_enabled = video_enabled
        logger.info(
            f"JOIN: NPU STT: {'enabled' if use_npu_stt else 'disabled'}, "
            f"Video: {'enabled' if video_enabled else 'disabled'}"
        )

        # Ensure browser is initialized (lazy initialization)
        # Pass video_enabled so the browser controller can start the correct video mode
        if not await self._ensure_browser(video_enabled=video_enabled):
            logger.error("JOIN: Failed to initialize browser for meeting")
            return False

        if self.state.status == "capturing":
            # Check if browser is still alive
            if self._controller and self._controller.is_browser_closed():
                logger.warning("JOIN: Browser was closed - cleaning up stale meeting state")
                await self._cleanup_stale_meeting()
            else:
                logger.warning("JOIN: Already in a meeting")
                return False

        self.state.status = "joining"
        self.state.meet_url = meet_url
        self.state.title = title or self._extract_meeting_id(meet_url)
        self.state.calendar_id = calendar_id
        self.state.event_id = event_id
        self.state.errors = []

        try:
            # Create meeting record in database
            if self.db:
                meeting = MeetingNote(
                    title=self.state.title,
                    calendar_id=calendar_id,
                    meet_url=meet_url,
                    event_id=event_id,
                    description=description,
                    organizer=organizer,
                    attendees=attendees or [],
                    status="in_progress",
                    bot_mode=mode,
                    actual_start=datetime.now(),
                )
                self.state.meeting_id = await self.db.create_meeting(meeting)
                logger.info(f"Created meeting record: {self.state.meeting_id} (mode={mode})")

            # START NPU STT IMMEDIATELY - audio devices are already created during browser init
            # This ensures we're listening from the moment Chrome connects to the meeting
            # Don't wait for UI automation (captions, popups, etc.)
            if self._use_npu_stt:
                logger.info("🧠 Starting NPU STT early (before UI automation)...")
                asyncio.create_task(self._setup_npu_stt())

            # Join the meeting (this does UI automation - can take 10+ seconds)
            success = await self._controller.join_meeting(meet_url)

            if not success:
                self.state.status = "error"
                # Get errors from controller state if available
                if self._controller.state and self._controller.state.errors:
                    self.state.errors.extend(self._controller.state.errors)
                else:
                    self.state.errors.append("Failed to join meeting - check browser controller logs")
                return False

            # Start caption capture
            await self._controller.start_caption_capture(self._on_caption)

            self.state.status = "capturing"
            self.state.joined_at = datetime.now()
            self.state.last_flush = datetime.now()

            # Emit toast notification for meeting joined
            try:
                from tool_modules.aa_workflow.src.notification_emitter import notify_meeting_joined

                notify_meeting_joined(self.state.title, mode)
            except Exception:
                pass

            # Start buffer flush task
            self._flush_task = asyncio.create_task(self._flush_loop())

            # Start screenshot capture loop (every 10 seconds)
            self._screenshot_task = asyncio.create_task(self._controller.start_screenshot_loop(interval_seconds=10))

            # Start browser health monitor (checks if browser was closed)
            self._browser_monitor_task = asyncio.create_task(self._monitor_browser_health())

            # NPU STT was already started early (before UI automation)
            # No need to start it again here

            # Initialize interactive mode components if requested
            if mode == "interactive":
                self._interactive_mode = True
                await self._setup_interactive_mode()
                logger.info(f"Joined meeting in INTERACTIVE mode: {self.state.title}")
            else:
                logger.info(f"Joined meeting in NOTES mode: {self.state.title}")

            # Start video daemon integration via D-Bus
            if self._enable_video_integration:
                await self._start_video_integration()

            return True

        except Exception as e:
            logger.error(f"Failed to join meeting: {e}")
            self.state.status = "error"
            self.state.errors.append(str(e))
            return False

    def _on_caption(self, entry: CaptionEntry) -> None:
        """Handle incoming caption (new or update)."""
        transcript_entry = TranscriptEntry(
            speaker=entry.speaker,
            text=entry.text,
            timestamp=entry.timestamp,
        )

        cap_id = entry.caption_id

        # Check if this is an update to an existing caption (by ID)
        if cap_id and cap_id in self.state.caption_id_to_index:
            # UPDATE: Replace the entry at the tracked index
            idx = self.state.caption_id_to_index[cap_id]
            if 0 <= idx < len(self.state.transcript_buffer):
                self.state.transcript_buffer[idx] = transcript_entry
                logger.debug(f"Caption UPDATE (id={cap_id}): [{entry.speaker}] {entry.text[:50]}...")
            else:
                # Index out of range (shouldn't happen), treat as new
                self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
                self.state.transcript_buffer.append(transcript_entry)
                self.state.captions_captured += 1
                logger.debug(f"Caption NEW (idx invalid): [{entry.speaker}] {entry.text[:50]}...")
        elif entry.is_update and self.state.transcript_buffer:
            # Fallback: is_update flag set but no ID tracking - replace last if same speaker
            last_entry = self.state.transcript_buffer[-1]
            if last_entry.speaker == entry.speaker:
                self.state.transcript_buffer[-1] = transcript_entry
                if cap_id:
                    # Track this ID for future updates
                    self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer) - 1
                logger.debug(f"Caption UPDATE (fallback): [{entry.speaker}] {entry.text[:50]}...")
            else:
                # Speaker changed, treat as new
                if cap_id:
                    self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
                self.state.transcript_buffer.append(transcript_entry)
                self.state.captions_captured += 1
                logger.debug(f"Caption NEW (speaker changed): [{entry.speaker}] {entry.text[:50]}...")
        else:
            # NEW caption
            if cap_id:
                self.state.caption_id_to_index[cap_id] = len(self.state.transcript_buffer)
            self.state.transcript_buffer.append(transcript_entry)
            self.state.captions_captured += 1
            logger.debug(f"Caption NEW (id={cap_id}): [{entry.speaker}] {entry.text[:50]}...")

        # Update activity timestamp to show we're not hung
        if self._controller:
            self._controller.update_activity()

        # NOTE: Wake word detection is now handled by NPU STT (_on_npu_transcription)
        # Google Meet captions are only used for transcript/notes, not wake word detection
        # This avoids duplicate processing and the NPU STT is faster/more accurate

        # Call external callback if set
        if self._on_caption_callback:
            self._on_caption_callback(transcript_entry)

    async def _check_wake_word_pause(self) -> None:
        """Check for pause after wake word to determine complete command."""
        if not self._wake_word_manager:
            return

        detector = self._wake_word_manager.text_detector
        logger.info(f"🎯 Pause checker started - waiting for speech pause...")

        # Wait for pause (check every 200ms for faster response)
        check_count = 0
        while detector.listening_for_command:
            await asyncio.sleep(0.2)  # Reduced from 500ms
            check_count += 1

            # Check if there's been a pause (uses WakeWordManager's method)
            event = self._wake_word_manager.check_pause()
            if event and event.command_text.strip():
                self.state.wake_word_triggers += 1
                logger.info(f"🔔 WAKE WORD + PAUSE DETECTED from {event.speaker}: {event.command_text}")

                # Handle wake word in interactive mode
                if self._interactive_mode:
                    logger.info(f"🎤 Sending to LLM: {event.command_text}")
                    # Don't use create_task - await it so we stay in this flow
                    await self._handle_wake_word_command(event)

                if self._on_wake_word_callback:
                    self._on_wake_word_callback(event)

                break

            # Log progress every 2 seconds
            if check_count % 4 == 0:
                buffer_text = " ".join(detector.command_buffer) if detector.command_buffer else "(empty)"
                logger.debug(f"🎯 Still listening... buffer: {buffer_text[:50]}...")

            # Check for timeout (10 seconds)
            if detector.command_start_time:
                elapsed = datetime.now() - detector.command_start_time
                if elapsed.total_seconds() > 10:
                    logger.info("Wake word command timeout - no pause detected in 10s")
                    detector._reset_command_state()
                    break

    async def _setup_interactive_mode(self) -> None:
        """Set up interactive mode with LLM and TTS.

        Creates an LLM responder with meeting context for conversation tracking.
        Optionally sets up NPU STT for real-time transcription.
        """
        try:
            # Create meeting ID from database ID or generate one
            meeting_id = str(self.state.meeting_id) if self.state.meeting_id else f"meet-{id(self)}"
            meeting_title = self.state.title or "Untitled Meeting"

            # Initialize LLM responder with meeting context
            self._llm_responder = LLMResponder(meeting_id=meeting_id)
            self._llm_responder.set_meeting_context(meeting_id, meeting_title)
            await self._llm_responder.initialize()

            logger.info(
                f"🎤 Interactive mode: LLM responder initialized for meeting '{meeting_title}' (ID: {meeting_id})"
            )
            logger.info(f"🎤 Interactive mode: Conversation history will be maintained throughout this meeting")

            # Set up wake word callback for voice responses
            logger.info(f"🎤 Interactive mode: Listening for wake word '{self.config.wake_word}'")

        except Exception as e:
            logger.error(f"Failed to set up interactive mode: {e}")
            self._interactive_mode = False

    async def _start_video_integration(self) -> None:
        """Start or upgrade video daemon integration via D-Bus.

        The video daemon is already streaming (black screen) before the browser
        launched. This method:
        - Switches from black screen to full AI video overlay
        - Finds Chromium's sink-input index for audio capture
        - Starts polling for participant updates
        - Sends participant updates via D-Bus

        If video was disabled for this meeting, this is a no-op (keeps black screen).
        """
        if not _video_dbus_available:
            logger.debug("Video D-Bus integration not available")
            return

        try:
            # Get device info from the controller
            video_device = None
            audio_source = None
            sink_name = None
            if self._controller:
                devices = self._controller.get_audio_devices()
                if devices:
                    video_device = devices.video_device
                    sink_name = devices.sink_name
                    # Audio source is the sink's monitor (for logging - actual capture via sink-input)
                    audio_source = f"{devices.sink_name}.monitor" if devices.sink_name else None
                    logger.info(f"📺 Device info: video={video_device}, audio={audio_source}")

            if not video_device:
                logger.warning("📺 No video device available, skipping video integration")
                return

            # Find Chromium's sink-input index for monitor-stream capture
            # This bypasses broken null-sink monitors in PipeWire
            sink_input_index = await self._find_chromium_sink_input(sink_name)
            if sink_input_index is not None:
                logger.info(f"📺 Found Chromium sink-input index: {sink_input_index}")
            else:
                logger.warning("📺 Could not find Chromium sink-input, waveform may not work")

            # Update audio source on the video daemon
            # The video daemon is already rendering - just update the audio capture
            # to use the Chromium sink-input for monitor-stream capture
            client = get_client("video")
            if await client.connect():
                # First try update_audio_source (doesn't restart render loop)
                result = await client.call_method(
                    "update_audio_source",
                    [sink_input_index if sink_input_index is not None else -1],
                )

                if not result or not result.get("success"):
                    # Fall back to switch_to_full_video if update_audio_source fails
                    # (e.g., if in black screen mode)
                    logger.info(f"📺 update_audio_source failed ({result}), trying switch_to_full_video...")
                    result = await client.call_method(
                        "switch_to_full_video",
                        [audio_source or "", "", False, sink_input_index if sink_input_index is not None else -1],
                    )

                await client.disconnect()

                if result and result.get("success"):
                    self._video_daemon_active = True
                    logger.info(f"📺 Video integration active on {video_device}")

                    # Start participant polling task
                    self._participant_poll_task = asyncio.create_task(self._poll_participants())
                else:
                    # May fail if video was disabled - that's OK, keep black screen
                    logger.info(f"📺 Video result: {result}")
                    # Still mark as active for cleanup purposes
                    self._video_daemon_active = True
            else:
                logger.warning("📺 Could not connect to video daemon D-Bus service")

        except Exception as e:
            logger.warning(f"📺 Failed to start video integration: {e}")

    async def _find_chromium_sink_input(self, target_sink: Optional[str]) -> Optional[int]:
        """Find Chromium's sink-input index for monitor-stream capture.

        PipeWire's null-sink monitors don't work properly (output zeros).
        Instead, we use parec --monitor-stream=<index> to capture directly
        from Chromium's audio stream.

        Args:
            target_sink: The sink name Chromium should be connected to

        Returns:
            Sink-input index if found, None otherwise
        """
        import asyncio

        try:
            # First, get sink ID to name mapping
            sink_id_to_name = {}
            proc = await asyncio.create_subprocess_exec(
                "pactl",
                "list",
                "sinks",
                "short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            for line in stdout.decode().strip().split("\n"):
                if line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        sink_id_to_name[parts[0]] = parts[1]

            # Run pactl to list sink-inputs
            proc = await asyncio.create_subprocess_exec(
                "pactl",
                "list",
                "sink-inputs",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()

            # Parse the output to find Chromium's sink-input
            current_index = None
            current_sink_id = None
            is_chromium = False
            chromium_candidates = []  # Store all Chromium sink-inputs

            for line in output.split("\n"):
                line = line.strip()

                if line.startswith("Sink Input #"):
                    # Save previous if it was Chromium
                    if is_chromium and current_index is not None:
                        sink_name = sink_id_to_name.get(current_sink_id, current_sink_id)
                        chromium_candidates.append((current_index, sink_name))

                    # Start new sink-input
                    current_index = int(line.split("#")[1])
                    current_sink_id = None
                    is_chromium = False

                elif line.startswith("Sink:"):
                    # Get sink ID
                    current_sink_id = line.split(":", 1)[1].strip()

                elif "application.name" in line.lower():
                    app_name = line.split("=", 1)[1].strip().strip('"').lower()
                    if "chromium" in app_name or "chrome" in app_name:
                        is_chromium = True

                elif "application.process.binary" in line.lower():
                    binary = line.split("=", 1)[1].strip().strip('"').lower()
                    if "chromium" in binary or "chrome" in binary:
                        is_chromium = True

            # Check the last one
            if is_chromium and current_index is not None:
                sink_name = sink_id_to_name.get(current_sink_id, current_sink_id)
                chromium_candidates.append((current_index, sink_name))

            logger.info(f"📺 Found {len(chromium_candidates)} Chromium sink-inputs: {chromium_candidates}")

            # Find the one connected to our target sink
            for idx, sink_name in chromium_candidates:
                if target_sink and target_sink in sink_name:
                    logger.info(f"📺 Selected Chromium sink-input {idx} (connected to {sink_name})")
                    return idx

            # If no match but we have candidates, return the last one (most recent)
            # This handles cases where Playwright Chromium might be named differently
            if chromium_candidates:
                idx, sink_name = chromium_candidates[-1]
                logger.info(f"📺 Using last Chromium sink-input {idx} (connected to {sink_name})")
                return idx

            return None

        except Exception as e:
            logger.warning(f"📺 Error finding Chromium sink-input: {e}")
            return None

    async def _poll_participants(self) -> None:
        """Poll Google Meet for participant updates.

        Does rapid initial polls (every 2s for first 10s) to quickly get
        participants, then slows to every 15 seconds (matching video rotation).
        """
        import json

        poll_count = 0
        rapid_poll_count = 5  # First 5 polls are rapid (every 2s = 10s total)
        rapid_interval = 2.0  # Fast polling at start
        normal_interval = 15.0  # Match video rotation interval

        while self.state.status == "capturing" and self._controller and self._video_daemon_active:
            try:
                # Get participants from Google Meet
                participants = await self._controller.get_participants()

                if participants:
                    # Send to video daemon via D-Bus
                    await self._update_video_attendees(participants)
                    if poll_count == 0:
                        logger.info(f"📺 Initial participant poll: {len(participants)} participants")
                    else:
                        logger.debug(f"📺 Sent {len(participants)} participants to video daemon")

            except Exception as e:
                logger.debug(f"Participant poll error: {e}")

            poll_count += 1

            # Use rapid polling for first few polls, then slow down
            if poll_count < rapid_poll_count:
                await asyncio.sleep(rapid_interval)
            else:
                await asyncio.sleep(normal_interval)

        logger.info("Participant polling stopped")

    async def _update_video_attendees(self, participants: list[dict]) -> None:
        """Send participant updates to video daemon via D-Bus.

        Args:
            participants: List of participant dicts with 'name' and optionally 'email'
        """
        import json

        try:
            client = get_client("video")
            if await client.connect():
                # Convert to JSON for D-Bus
                attendees_json = json.dumps(participants)
                result = await client.call_method("update_attendees", [attendees_json])
                await client.disconnect()

                if not (result and result.get("success")):
                    logger.debug(f"📺 update_attendees returned: {result}")
        except Exception as e:
            logger.debug(f"📺 Failed to update attendees: {e}")

    async def _stop_video_integration(self) -> None:
        """Stop video daemon integration."""
        # Cancel polling task
        if self._participant_poll_task:
            self._participant_poll_task.cancel()
            try:
                await self._participant_poll_task
            except asyncio.CancelledError:
                pass
            self._participant_poll_task = None

        # Stop video daemon rendering via D-Bus
        if self._video_daemon_active:
            try:
                client = get_client("video")
                if await client.connect():
                    result = await client.call_method("stop_video", [])
                    await client.disconnect()

                    if result and result.get("success"):
                        logger.info("📺 Video daemon stopped rendering")
                    else:
                        logger.debug(f"📺 stop_video returned: {result}")
            except Exception as e:
                logger.debug(f"📺 Failed to stop video daemon: {e}")

            self._video_daemon_active = False

        logger.info("📺 Video integration stopped")

    async def _setup_npu_stt(self) -> None:
        """Set up NPU-based real-time STT pipeline.

        This captures audio from the meeting's virtual sink and transcribes
        it locally on the NPU, providing an alternative to Google Meet captions.

        Benefits:
        - Lower latency (local processing)
        - Works even if Meet captions are disabled
        - More accurate for technical terms (can be fine-tuned)
        - Privacy - audio never leaves the machine
        """
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import RealtimeSTTPipeline

            # Get the instance ID from the controller
            if not self._controller:
                logger.warning("No controller - cannot set up NPU STT")
                return

            # Use _instance_id (string) and _devices (InstanceDeviceManager result)
            instance_id = getattr(self._controller, "_instance_id", None)
            devices = getattr(self._controller, "_devices", None)

            if devices and hasattr(devices, "sink_name"):
                # Use the device manager's sink monitor
                monitor_source = f"{devices.sink_name}.monitor"
                logger.info(f"🧠 NPU STT: Using device manager sink: {monitor_source}")
            elif instance_id:
                # Fallback to constructed name from instance_id
                safe_id = instance_id.replace("-", "_")
                monitor_source = f"meet_bot_{safe_id}.monitor"
                logger.info(f"🧠 NPU STT: Using constructed sink name: {monitor_source}")
            else:
                logger.warning("No instance_id or devices - cannot set up NPU STT")
                return

            logger.info(f"🧠 Setting up NPU STT pipeline from: {monitor_source}")

            # Create the STT pipeline
            self._npu_stt_pipeline = RealtimeSTTPipeline(
                source_name=monitor_source,
                on_transcription=self._on_npu_transcription,
                sample_rate=16000,
                vad_threshold=0.01,
                silence_duration=0.8,
                min_speech_duration=0.3,
                max_speech_duration=15.0,
            )

            # Start the pipeline
            if await self._npu_stt_pipeline.start():
                logger.info("🧠 NPU STT pipeline started - real-time transcription active")
            else:
                logger.error("🧠 Failed to start NPU STT pipeline")
                self._npu_stt_pipeline = None

        except ImportError as e:
            logger.warning(f"NPU STT not available: {e}")
        except Exception as e:
            logger.error(f"Failed to set up NPU STT: {e}")

    def _on_npu_transcription(self, text: str, is_final: bool) -> None:
        """Handle transcription from NPU STT.

        This is called when the NPU STT pipeline produces a transcription.
        We treat it like a caption from Google Meet.

        IMPORTANT: We ignore transcriptions while the bot is speaking to avoid
        detecting our own TTS output as wake words.
        """
        if not text.strip():
            return

        # CRITICAL: Ignore transcriptions while bot is responding
        # Otherwise we detect our own TTS output as wake words
        if self._responding:
            logger.debug(f"🧠 NPU (ignored - bot speaking): '{text}'")
            return

        logger.info(f"🧠 NPU→WakeWord {'[FINAL]' if is_final else '[partial]'}: '{text}'")

        # Create a transcript entry (speaker is "Meeting" since we can't identify)
        transcript_entry = TranscriptEntry(
            speaker="Meeting Audio",  # NPU STT doesn't know who's speaking
            text=text.strip(),
            timestamp=datetime.now(),
        )

        # Add to buffer
        self.state.transcript_buffer.append(transcript_entry)
        self.state.captions_captured += 1

        # Process for wake word detection
        if self._wake_word_manager and is_final:
            # Create a mock CaptionEntry for wake word processing
            from tool_modules.aa_meet_bot.src.browser_controller import CaptionEntry

            mock_caption = CaptionEntry(
                speaker="Meeting Audio",
                text=text.strip(),
                timestamp=datetime.now(),
                is_update=False,
                caption_id=None,
            )
            # Feed to wake word manager via the normal caption handler
            self._process_caption_for_wake_word(mock_caption)

    def _process_caption_for_wake_word(self, entry) -> None:
        """Process a caption entry for wake word detection."""
        if not self._wake_word_manager:
            logger.debug("No wake word manager - skipping wake word check")
            return

        logger.debug(f"🔍 Checking for wake word in: '{entry.text}' (speaker: {entry.speaker})")

        event = self._wake_word_manager.process_caption(
            speaker=entry.speaker,
            text=entry.text,
        )

        if event:
            # Complete command detected - handle it immediately!
            logger.info(f"🔔 COMPLETE COMMAND from {event.speaker}: {event.command_text}")
            self.state.wake_word_triggers += 1

            if self._interactive_mode:
                # Handle immediately - don't wait for pause
                asyncio.create_task(self._handle_wake_word_command(event))

            if self._on_wake_word_callback:
                self._on_wake_word_callback(event)

        elif self._wake_word_manager.text_detector.listening_for_command:
            # Wake word detected but waiting for more input - start pause checker
            if not self._wake_word_check_task or self._wake_word_check_task.done():
                logger.info("🎯 Wake word detected, starting pause checker...")
                self._wake_word_check_task = asyncio.create_task(self._check_wake_word_pause())

    async def _handle_wake_word_command(self, event: WakeWordEvent) -> None:
        """Handle a wake word command in interactive mode.

        Flow:
        1. Unmute mic immediately (so user knows bot is listening)
        2. Send command to LLM
        3. Synthesize and speak response
        4. Wait for response to finish + buffer time
        5. Check if new wake word detected, if not, mute
        """
        if self._responding:
            logger.warning("Already responding to a command, ignoring new wake word")
            return

        if not self._llm_responder:
            logger.warning("LLM responder not initialized")
            return

        command = event.command_text.strip()
        if not command:
            logger.debug("Empty command after wake word, ignoring")
            return

        self._responding = True
        try:
            logger.info(f"🎤 Processing command: {command}")

            # Get recent context from transcript buffer (as list of strings)
            context_entries = self.state.transcript_buffer[-10:]
            context_before = [f"{e.speaker}: {e.text}" for e in context_entries]

            # Check if streaming is enabled for Ollama
            from tool_modules.aa_meet_bot.src.llm_responder import OLLAMA_STREAMING

            if self._llm_responder.backend == "ollama" and OLLAMA_STREAMING:
                # Streaming mode - speak sentences as they arrive
                await self._stream_and_speak(command, event.speaker, context_before)
            else:
                # Non-streaming - get full response then speak
                llm_response = await self._llm_responder.generate_response(
                    command=command,
                    speaker=event.speaker,
                    context_before=context_before,
                )

                if llm_response and llm_response.text:
                    logger.info(f"🎤 Response: {llm_response.text[:100]}...")
                    await self._speak_response(llm_response.text)
                else:
                    logger.warning("No response generated")

        except Exception as e:
            logger.error(f"Error handling wake word command: {e}")
        finally:
            self._responding = False
            # Reset wake word detector to clear old buffered captions
            # This prevents re-triggering on stale text
            if self._wake_word_manager:
                self._wake_word_manager.text_detector.reset()
                logger.debug("Wake word detector reset after response")

    async def _stream_and_speak(self, command: str, speaker: str, context_before: list) -> None:
        """Stream LLM response and speak sentences as they arrive.

        This reduces perceived latency by starting TTS as soon as the first
        sentence is complete, rather than waiting for the full response.

        Note: The bot's mic is a virtual pipe - it stays unmuted permanently.
        No mute/unmute needed since it only produces sound when we write to it.
        """
        from tool_modules.aa_meet_bot.src.tts_engine import TTSEngine

        tts = TTSEngine()
        if not await tts.initialize():
            logger.error("Failed to initialize TTS for streaming")
            return

        pipe_path = self._controller.get_pipe_path() if self._controller else None
        if not pipe_path:
            logger.warning("No pipe path for streaming TTS")
            return

        # Build messages for Ollama
        messages = self._llm_responder._build_messages(command, speaker, context_before)

        sentence_count = 0
        full_response = []

        async for sentence in self._llm_responder.stream_ollama_sentences(messages):
            sentence_count += 1
            full_response.append(sentence)
            logger.info(f"🔊 Streaming sentence {sentence_count}: {sentence[:50]}...")

            # Speak this sentence immediately
            duration = await tts.speak_to_pipe(sentence, pipe_path)
            if duration > 0:
                # Wait for this sentence to finish before next
                await asyncio.sleep(duration + 0.1)

        if full_response:
            # Add to conversation history
            self._llm_responder.conversation_history.append({"role": "user", "content": command})
            self._llm_responder.conversation_history.append({"role": "assistant", "content": " ".join(full_response)})
            logger.info(f"🎤 Streamed {sentence_count} sentences")
        else:
            logger.warning("No response from streaming")

    async def _speak_response(self, text: str) -> None:
        """Speak a response using TTS.

        The bot's microphone is a virtual pipe - it only produces sound when
        we write audio to it. No mute/unmute needed.
        """
        if not self._controller:
            logger.warning("No controller available for TTS")
            return

        try:
            await self._speak_response_audio_only(text)
        except Exception as e:
            logger.error(f"TTS error: {e}")
            import traceback

            traceback.print_exc()

    async def _speak_response_audio_only(self, text: str) -> None:
        """Speak a response using TTS by writing audio to the virtual pipe.

        The bot's mic is a virtual pipe - no physical microphone is connected.
        Audio written here goes directly to the meeting.
        """
        if not self._controller:
            logger.warning("No controller available for TTS")
            return

        try:
            from tool_modules.aa_meet_bot.src.tts_engine import TTSEngine

            tts = TTSEngine()
            if not await tts.initialize():
                logger.error("Failed to initialize TTS engine")
                return

            # Get the pipe path for audio output
            pipe_path = self._controller.get_pipe_path()
            if not pipe_path:
                logger.warning("No pipe path available for TTS")
                return

            # Synthesize and write to pipe - returns actual duration
            logger.info(f"🔊 Synthesizing: {text[:50]}...")
            duration = await tts.speak_to_pipe(text, pipe_path)

            if duration > 0:
                # Wait for audio to actually play through PulseAudio
                # The duration includes silence padding (500ms lead-in, 800ms tail)
                # plus extra buffer for PulseAudio latency and stream flushing
                wait_time = duration + 0.5  # Extra 500ms for PA latency
                logger.info(f"🔊 Playing audio ({duration:.1f}s), waiting {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
                logger.info(f"🔊 Finished speaking")
            else:
                logger.warning("Failed to write audio to pipe")

        except Exception as e:
            logger.error(f"TTS error: {e}")
            import traceback

            traceback.print_exc()

    async def _flush_loop(self) -> None:
        """Periodically flush transcript buffer to database."""
        while self.state.status == "capturing":
            await asyncio.sleep(self.state.buffer_flush_interval)
            await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        """Flush transcript buffer to database."""
        if not self.db or not self.state.meeting_id:
            return

        if not self.state.transcript_buffer:
            return

        try:
            # Copy and clear buffer
            entries = self.state.transcript_buffer.copy()
            self.state.transcript_buffer = []

            # Clear caption ID tracking to prevent unbounded memory growth
            # IDs are only used for update-in-place within the buffer
            self.state.caption_id_to_index.clear()

            # Write to database
            await self.db.add_transcript_entries(self.state.meeting_id, entries)
            self.state.last_flush = datetime.now()

            logger.debug(f"Flushed {len(entries)} transcript entries")

        except Exception as e:
            logger.error(f"Failed to flush transcript buffer: {e}")
            # Put entries back in buffer
            self.state.transcript_buffer = entries + self.state.transcript_buffer

    async def _monitor_browser_health(self) -> None:
        """Monitor browser health and trigger cleanup if browser closes."""
        logger.info("Browser health monitor started")
        consecutive_failures = 0
        max_failures = 3  # Trigger cleanup after 3 consecutive failures

        while self.state.status == "capturing":
            await asyncio.sleep(1)  # Check every 1 second for faster detection

            # Check if controller reports browser closed (now actively checks browser state)
            if self._controller and self._controller.is_browser_closed():
                logger.warning("Browser health monitor: Browser closed detected!")
                await self._cleanup_stale_meeting()
                break

            # Also check if controller state shows not joined
            if self._controller and self._controller.state and not self._controller.state.joined:
                logger.warning("Browser health monitor: Meeting ended (not joined)")
                await self._cleanup_stale_meeting()
                break

            # Additional check: verify page is responsive by checking URL
            if self._controller and self._controller.page:
                try:
                    # Quick check - if this throws, browser is dead
                    _ = self._controller.page.url
                    consecutive_failures = 0  # Reset on success
                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(
                        f"Browser health monitor: Page check failed ({consecutive_failures}/{max_failures}): {e}"
                    )
                    if consecutive_failures >= max_failures:
                        logger.warning("Browser health monitor: Page unresponsive - triggering cleanup")
                        await self._cleanup_stale_meeting()
                        break

            # Check if browser process is still alive (belt and suspenders)
            if self._controller and self._controller.browser:
                try:
                    # Check if browser is still connected
                    if not self._controller.browser.is_connected():
                        logger.warning("Browser health monitor: Browser disconnected")
                        await self._cleanup_stale_meeting()
                        break
                except Exception as e:
                    logger.warning(f"Browser health monitor: Browser check failed: {e}")
                    # Don't cleanup on exception - could be a transient error
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        logger.warning("Browser health monitor: Too many browser check failures - triggering cleanup")
                        await self._cleanup_stale_meeting()
                        break

        logger.info("Browser health monitor stopped")

    async def _cleanup_stale_meeting(self) -> None:
        """Clean up state from a meeting where the browser was closed unexpectedly.

        This is called when:
        - Browser window is closed by user
        - Browser crashes
        - Meeting ends unexpectedly
        - Health monitor detects browser is unresponsive

        CRITICAL: This must clean up ALL resources to prevent orphaned:
        - PulseAudio modules (sinks/sources)
        - Named pipes
        - parec processes
        - Video devices
        - Background tasks
        """
        logger.info("=" * 60)
        logger.info("CLEANUP: Starting stale meeting cleanup...")
        logger.info("=" * 60)

        # Track what we're cleaning up
        cleanup_errors = []

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # This MUST happen before closing the controller to ensure the parec
        # process is killed while we still have the PID reference
        if self._npu_stt_pipeline:
            logger.info("CLEANUP: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
                logger.info("CLEANUP: NPU STT pipeline stopped successfully")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout stopping NPU STT pipeline")
                cleanup_errors.append("NPU STT timeout")
            except Exception as e:
                logger.warning(f"CLEANUP: Error stopping NPU STT: {e}")
                cleanup_errors.append(f"NPU STT error: {e}")
            finally:
                self._npu_stt_pipeline = None

        # 2. Kill any remaining audio capture processes from this session
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"CLEANUP: Force-killed {killed} orphaned audio capture processes")
        except Exception as e:
            logger.warning(f"CLEANUP: Error killing audio captures: {e}")
            cleanup_errors.append(f"Audio capture kill error: {e}")

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("wake_word_check_task", getattr(self, "_wake_word_check_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for task_name, task in tasks_to_cancel:
            if task and not task.done():
                logger.info(f"CLEANUP: Cancelling {task_name}...")
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    cleanup_errors.append(f"{task_name} cancel error: {e}")

        # Clear task references
        self._flush_task = None
        self._screenshot_task = None
        self._browser_monitor_task = None
        if hasattr(self, "_wake_word_check_task"):
            self._wake_word_check_task = None
        if hasattr(self, "_participant_poll_task"):
            self._participant_poll_task = None

        # 4. Stop video daemon integration
        if self._video_daemon_active:
            logger.info("CLEANUP: Stopping video daemon integration...")
            try:
                await asyncio.wait_for(self._stop_video_integration(), timeout=5.0)
                logger.info("CLEANUP: Video daemon stopped")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout stopping video daemon")
                cleanup_errors.append("Video daemon timeout")
            except Exception as e:
                logger.warning(f"CLEANUP: Error stopping video integration: {e}")
                cleanup_errors.append(f"Video daemon error: {e}")

        # 5. Flush any remaining transcript buffer
        try:
            await self._flush_buffer()
        except Exception as e:
            logger.warning(f"CLEANUP: Failed to flush buffer: {e}")

        # 6. Update meeting record as ended
        if self.db and self.state.meeting_id:
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=datetime.now(),
                )
                logger.info(f"CLEANUP: Meeting {self.state.meeting_id} marked as completed")
            except Exception as e:
                logger.warning(f"CLEANUP: Failed to update meeting record: {e}")

        # 7. Close the browser controller - this cleans up per-instance audio devices
        # restore_browser_audio=True because the meeting died unexpectedly
        if self._controller:
            logger.info("CLEANUP: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=True), timeout=10.0)
                logger.info("CLEANUP: Browser controller closed")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"CLEANUP: Error closing controller: {e}")
                cleanup_errors.append(f"Controller close error: {e}")
            finally:
                self._controller = None

        # 8. FINAL: Clean up ANY remaining orphaned devices system-wide
        # This is the safety net that catches anything we missed
        cleanup_result = await self._run_orphan_cleanup("CLEANUP")
        if cleanup_result.get("errors"):
            cleanup_errors.extend(cleanup_result["errors"])

        # 9. Reset state
        self.state.status = "idle"
        self.state.meeting_id = None
        self.state.meet_url = ""
        self.state.title = ""
        self.state.caption_id_to_index.clear()
        self.state.transcript_buffer.clear()

        # Log summary
        logger.info("=" * 60)
        if cleanup_errors:
            logger.warning(f"CLEANUP: Completed with {len(cleanup_errors)} errors:")
            for err in cleanup_errors:
                logger.warning(f"  - {err}")
        else:
            logger.info("CLEANUP: Completed successfully - all resources released")
        logger.info("CLEANUP: Ready for new meeting")
        logger.info("=" * 60)

    async def leave_meeting(self, generate_summary: bool = True) -> dict:
        """
        Leave the meeting and finalize notes.

        This is the NORMAL exit path (user requested leave).
        For unexpected exits (browser closed), see _cleanup_stale_meeting().

        Args:
            generate_summary: Whether to generate an AI summary (future feature)

        Returns:
            Meeting summary dict
        """
        if self.state.status != "capturing":
            return {"error": "Not in a meeting"}

        logger.info("=" * 60)
        logger.info("LEAVE: Starting graceful meeting exit...")
        logger.info("=" * 60)

        self.state.status = "leaving"

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # Must happen before closing controller to ensure clean shutdown
        if self._npu_stt_pipeline:
            logger.info("LEAVE: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
                logger.info("LEAVE: NPU STT pipeline stopped")
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout stopping NPU STT pipeline")
            except Exception as e:
                logger.warning(f"LEAVE: Error stopping NPU STT: {e}")
            finally:
                self._npu_stt_pipeline = None

        # 2. Kill any remaining audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"LEAVE: Killed {killed} audio capture processes")
        except Exception as e:
            logger.warning(f"LEAVE: Error killing audio captures: {e}")

        # 3. Cancel background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for task_name, task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._flush_task = None
        self._screenshot_task = None
        self._browser_monitor_task = None
        if hasattr(self, "_participant_poll_task"):
            self._participant_poll_task = None

        # 4. Stop video daemon integration
        if self._video_daemon_active:
            logger.info("LEAVE: Stopping video daemon...")
            try:
                await asyncio.wait_for(self._stop_video_integration(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout stopping video daemon")
            except Exception as e:
                logger.warning(f"LEAVE: Error stopping video daemon: {e}")

        # 5. Final buffer flush
        try:
            await self._flush_buffer()
        except Exception as e:
            logger.warning(f"LEAVE: Failed to flush buffer: {e}")

        # 6. Leave the meeting (browser automation)
        if self._controller:
            logger.info("LEAVE: Leaving meeting via browser...")
            try:
                await asyncio.wait_for(self._controller.leave_meeting(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout leaving meeting")
            except Exception as e:
                logger.warning(f"LEAVE: Error leaving meeting: {e}")

        # 7. Build result before cleanup
        result = {
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "duration_minutes": 0,
            "captions_captured": self.state.captions_captured,
        }

        if self.db and self.state.meeting_id:
            now = datetime.now()

            # Calculate duration
            if self.state.joined_at:
                duration = now - self.state.joined_at
                result["duration_minutes"] = round(duration.total_seconds() / 60, 1)

            # Update meeting status
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=now,
                )
            except Exception as e:
                logger.warning(f"LEAVE: Failed to update meeting record: {e}")

        # 8. Close browser controller (this cleans up per-instance devices)
        # restore_browser_audio=False for normal exit (user's Chrome wasn't affected)
        if self._controller:
            logger.info("LEAVE: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=False), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout closing controller")
            except Exception as e:
                logger.warning(f"LEAVE: Error closing controller: {e}")
            finally:
                self._controller = None

        # 9. Emit toast notification
        try:
            from tool_modules.aa_workflow.src.notification_emitter import notify_meeting_left

            notify_meeting_left(
                result.get("title", "Meeting"),
                result.get("duration_minutes", 0),
                result.get("captions_captured", 0),
            )
        except Exception:
            pass

        # 10. FINAL: Clean up any orphaned devices (safety net)
        await self._run_orphan_cleanup("POST-LEAVE")

        # 11. Reset state
        self.state = NotesBotState()

        logger.info("=" * 60)
        logger.info(f"LEAVE: Meeting ended. Captured {result['captions_captured']} captions.")
        logger.info("=" * 60)

        return result

    async def get_status(self) -> dict:
        """Get current bot status."""
        status = {
            "status": self.state.status,
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "meet_url": self.state.meet_url,
            "captions_captured": self.state.captions_captured,
            "wake_word_triggers": self.state.wake_word_triggers,
            "wake_word_enabled": self._enable_wake_word,
            "wake_word": self.config.wake_word if self._enable_wake_word else None,
            "buffer_size": len(self.state.transcript_buffer),
            "errors": self.state.errors,
        }

        if self.state.joined_at:
            duration = datetime.now() - self.state.joined_at
            status["duration_minutes"] = round(duration.total_seconds() / 60, 1)

        return status

    def set_caption_callback(self, callback: Callable[[TranscriptEntry], None]) -> None:
        """Set callback for real-time caption updates."""
        self._on_caption_callback = callback

    def set_wake_word_callback(self, callback: Callable[[WakeWordEvent], None]) -> None:
        """Set callback for wake word detection events."""
        self._on_wake_word_callback = callback

    def enable_wake_word(self, enabled: bool = True) -> None:
        """Enable or disable wake word detection."""
        self._enable_wake_word = enabled
        logger.info(f"Wake word detection {'enabled' if enabled else 'disabled'}")

    async def close(self) -> None:
        """Clean up all resources.

        This is the final cleanup method called when the bot is being destroyed.
        It ensures ALL resources are released, including:
        - Background tasks
        - NPU STT pipeline (and its parec processes)
        - Browser controller (and its audio devices)
        - Any orphaned devices system-wide
        """
        logger.info("=" * 60)
        logger.info("CLOSE: Shutting down notes bot...")
        logger.info("=" * 60)

        # 1. Stop NPU STT pipeline FIRST (kills parec processes)
        if self._npu_stt_pipeline:
            logger.info("CLOSE: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"CLOSE: Error stopping NPU STT: {e}")
            finally:
                self._npu_stt_pipeline = None

        # 2. Kill any remaining audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"CLOSE: Killed {killed} orphaned audio capture processes")
        except Exception as e:
            logger.warning(f"CLOSE: Error killing audio captures: {e}")

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("wake_word_check_task", getattr(self, "_wake_word_check_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for task_name, task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._flush_task = None
        self._screenshot_task = None

        # 4. Leave meeting if in one (this also flushes buffer)
        if self.state.status == "capturing":
            logger.info("CLOSE: Leaving active meeting...")
            try:
                await asyncio.wait_for(self.leave_meeting(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout leaving meeting, forcing cleanup...")
                await self._cleanup_stale_meeting()
            except Exception as e:
                logger.warning(f"CLOSE: Error leaving meeting: {e}")
                await self._cleanup_stale_meeting()

        # 5. Close browser controller if still open
        if self._controller:
            logger.info("CLOSE: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=True), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"CLOSE: Error closing browser controller: {e}")
            finally:
                self._controller = None

        # 6. FINAL: Clean up any remaining orphaned devices system-wide
        await self._run_orphan_cleanup("SHUTDOWN")

        # Note: Don't close the database here - it may be shared
        # The caller (scheduler/manager) is responsible for database cleanup

        logger.info("=" * 60)
        logger.info("CLOSE: Notes bot shutdown complete")
        logger.info("=" * 60)

    def _extract_meeting_id(self, url: str) -> str:
        """Extract meeting ID from URL for use as title."""
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", url)
        if match:
            return f"Meeting {match.group(1)}"
        return "Untitled Meeting"


@dataclass
class MeetingSession:
    """Tracks a meeting session with its bot and metadata."""

    bot: NotesBot
    session_id: str
    meet_url: str
    title: str
    scheduled_end: Optional[datetime] = None
    grace_period_minutes: int = 5  # Stay this long after scheduled end


class NotesBotManager:
    """
    Manages multiple NotesBot instances for concurrent meetings.

    Each meeting gets its own bot with its own browser instance.
    Bots are keyed by a unique session ID (typically the meet URL or a UUID).

    Features:
    - Automatic leave when scheduled end time passes (with grace period)
    - Background monitor task to check for expired meetings
    - Automatic cleanup of orphaned devices on startup and periodically
    """

    def __init__(self):
        """Initialize the bot manager."""
        self._sessions: dict[str, MeetingSession] = {}
        self._bots: dict[str, NotesBot] = {}  # Backward compatibility
        self._db: Optional[MeetingNotesDB] = None
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_interval: int = 60  # Check every 60 seconds
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the manager and run startup cleanup.

        IMPORTANT: This should be called before using the manager.
        It cleans up any orphaned devices from previous sessions.
        """
        if self._initialized:
            return

        logger.info("=" * 60)
        logger.info("MANAGER INIT: Initializing NotesBotManager...")
        logger.info("=" * 60)

        # Run startup cleanup to remove any orphaned devices
        logger.info("MANAGER INIT: Running startup cleanup...")
        await self._run_full_cleanup("MANAGER-INIT")

        self._initialized = True
        logger.info("MANAGER INIT: NotesBotManager initialized")

    async def _run_full_cleanup(self, context: str = "") -> dict:
        """Run comprehensive cleanup of all orphaned resources.

        Args:
            context: Label for logging

        Returns:
            Cleanup results
        """
        results = {
            "audio_captures_killed": 0,
            "modules_removed": 0,
            "processes_killed": 0,
            "pipes_removed": 0,
            "video_devices_removed": 0,
            "errors": [],
        }

        prefix = f"{context}: " if context else ""

        # 1. Kill any tracked audio capture processes
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            results["audio_captures_killed"] = killed
            if killed > 0:
                logger.info(f"{prefix}Killed {killed} tracked audio captures")
        except Exception as e:
            results["errors"].append(f"Audio capture cleanup: {e}")

        # 2. Get active instance IDs (if any sessions exist)
        active_ids = set()
        async with self._lock:
            for session in self._sessions.values():
                if session.bot._controller:
                    active_ids.add(session.bot._controller._instance_id)

        # 3. Run comprehensive orphan cleanup
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices

            cleanup_results = await cleanup_orphaned_meetbot_devices(active_instance_ids=active_ids)

            results["modules_removed"] = len(cleanup_results.get("removed_modules", []))
            results["processes_killed"] = len(cleanup_results.get("killed_processes", []))
            results["pipes_removed"] = len(cleanup_results.get("removed_pipes", []))
            results["video_devices_removed"] = len(cleanup_results.get("removed_video_devices", []))
            results["errors"].extend(cleanup_results.get("errors", []))

            total = (
                results["modules_removed"]
                + results["processes_killed"]
                + results["pipes_removed"]
                + results["video_devices_removed"]
            )

            if total > 0:
                logger.info(
                    f"{prefix}Cleanup: {results['modules_removed']} modules, "
                    f"{results['processes_killed']} processes, "
                    f"{results['pipes_removed']} pipes, "
                    f"{results['video_devices_removed']} video devices"
                )
            else:
                logger.info(f"{prefix}Cleanup: No orphaned devices found")

        except Exception as e:
            results["errors"].append(f"Orphan cleanup: {e}")
            logger.warning(f"{prefix}Error during cleanup: {e}")

        return results

    async def _get_db(self) -> MeetingNotesDB:
        """Get or create shared database instance."""
        if self._db is None:
            self._db = await init_notes_db()
        return self._db

    def _generate_session_id(self, meet_url: str) -> str:
        """Generate a unique session ID from the meet URL."""
        # Extract the meeting code from URL
        match = re.search(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", meet_url)
        if match:
            return match.group(1)
        # Fallback to hash of URL
        import hashlib

        return hashlib.md5(meet_url.encode()).hexdigest()[:12]

    async def _start_monitor(self) -> None:
        """Start the background monitor task if not already running."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Started meeting end-time monitor")

    async def _stop_monitor(self) -> None:
        """Stop the background monitor task."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("Stopped meeting end-time monitor")

    async def _monitor_loop(self) -> None:
        """Background loop to check for meetings that should end and cleanup orphaned devices."""
        cleanup_counter = 0
        cleanup_interval = 5  # Run device cleanup every 5 monitor cycles (5 minutes)

        while True:
            try:
                await asyncio.sleep(self._monitor_interval)
                await self._check_expired_meetings()

                # Periodically clean up orphaned audio devices
                cleanup_counter += 1
                if cleanup_counter >= cleanup_interval:
                    cleanup_counter = 0
                    await self._cleanup_orphaned_audio_devices()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in meeting monitor: {e}")

    async def _cleanup_orphaned_audio_devices(self) -> None:
        """Clean up any orphaned MeetBot audio devices."""
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import (
                cleanup_orphaned_meetbot_devices,
                get_meetbot_device_count,
            )

            # Get active instance IDs
            active_ids = set()
            async with self._lock:
                for session in self._sessions.values():
                    if session.bot._controller:
                        active_ids.add(session.bot._controller._instance_id)

            # Check device count first to avoid unnecessary cleanup calls
            counts = await get_meetbot_device_count()
            expected_modules = len(active_ids) * 2  # Each instance has sink + source

            if counts["module_count"] > expected_modules:
                logger.info(
                    f"Detected potential orphaned devices: {counts['module_count']} modules "
                    f"but only {len(active_ids)} active meetings (expected ~{expected_modules} modules)"
                )
                results = await cleanup_orphaned_meetbot_devices(active_ids)

                if results["removed_modules"]:
                    logger.info(f"Cleaned up {len(results['removed_modules'])} orphaned audio modules")
                if results["removed_pipes"]:
                    logger.info(f"Cleaned up {len(results['removed_pipes'])} orphaned pipes")
                if results["errors"]:
                    for err in results["errors"]:
                        logger.warning(f"Cleanup error: {err}")

        except Exception as e:
            logger.error(f"Error during orphaned device cleanup: {e}")

    async def _check_expired_meetings(self) -> None:
        """Check for and leave any meetings past their end time."""
        now = datetime.now()
        expired_sessions = []
        hung_sessions = []

        async with self._lock:
            for session_id, session in self._sessions.items():
                # Check scheduled end time
                if session.scheduled_end:
                    # Add grace period
                    end_with_grace = session.scheduled_end + timedelta(minutes=session.grace_period_minutes)
                    if now > end_with_grace:
                        expired_sessions.append(session_id)
                        logger.info(
                            f"Meeting '{session.title}' ({session_id}) has passed its end time "
                            f"({session.scheduled_end} + {session.grace_period_minutes}min grace)"
                        )

                # Check for hung bots (no activity for 30+ minutes while supposedly capturing)
                if session.bot._controller:
                    last_activity = session.bot._controller._last_activity
                    inactive_minutes = (now - last_activity).total_seconds() / 60
                    if inactive_minutes > 30 and session.bot.state.status == "capturing":
                        hung_sessions.append((session_id, inactive_minutes))
                        logger.warning(
                            f"Meeting '{session.title}' ({session_id}) appears hung "
                            f"(no activity for {inactive_minutes:.1f} min)"
                        )

        # Leave expired meetings (outside lock to avoid deadlock)
        for session_id in expired_sessions:
            logger.info(f"Auto-leaving expired meeting: {session_id}")
            result = await self.leave_meeting(session_id)
            if "error" not in result:
                logger.info(
                    f"Successfully auto-left meeting {session_id}: {result.get('captions_captured', 0)} captions captured"
                )

        # Force-kill hung sessions
        for session_id, inactive_minutes in hung_sessions:
            logger.warning(f"Force-killing hung meeting: {session_id} (inactive {inactive_minutes:.1f} min)")
            await self._force_kill_session(session_id)

    async def _force_kill_session(self, session_id: str) -> None:
        """Force kill a hung session and clean up all resources."""
        async with self._lock:
            if session_id not in self._sessions:
                return

            session = self._sessions[session_id]
            logger.info(f"Force-killing session {session_id}...")

            # Stop NPU STT pipeline first (kills parec processes)
            if session.bot._npu_stt_pipeline:
                try:
                    await asyncio.wait_for(session.bot._npu_stt_pipeline.stop(), timeout=3.0)
                except (asyncio.TimeoutError, Exception):
                    pass
                session.bot._npu_stt_pipeline = None

            # Kill any audio capture processes
            try:
                from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
                await PulseAudioCapture.kill_all_captures()
            except Exception:
                pass

            # Force kill the browser
            if session.bot._controller:
                await session.bot._controller.force_kill()

            # Clean up session tracking
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]

            logger.info(f"Force-killed session {session_id}")

        # Run orphan cleanup outside the lock
        try:
            from tool_modules.aa_meet_bot.src.virtual_devices import cleanup_orphaned_meetbot_devices
            await cleanup_orphaned_meetbot_devices(active_instance_ids=set())
        except Exception as e:
            logger.warning(f"Error during post-force-kill cleanup: {e}")

    async def join_meeting(
        self,
        meet_url: str,
        title: str = "",
        calendar_id: str = "",
        event_id: str = "",
        description: str = "",
        organizer: str = "",
        attendees: Optional[list[str]] = None,
        scheduled_end: Optional[datetime] = None,
        grace_period_minutes: int = 5,
    ) -> tuple[str, bool, list[str]]:
        """
        Join a meeting, creating a new bot instance.

        Args:
            meet_url: Google Meet URL
            title: Meeting title
            calendar_id: Source calendar ID
            event_id: Google Calendar event ID
            description: Meeting description
            organizer: Meeting organizer email
            attendees: List of attendee emails
            scheduled_end: When the meeting is scheduled to end (auto-leave after this + grace)
            grace_period_minutes: Minutes to stay after scheduled_end (default 5)

        Returns:
            Tuple of (session_id, success, errors)
        """
        # Ensure manager is initialized (runs startup cleanup on first call)
        if not self._initialized:
            await self.initialize()

        session_id = self._generate_session_id(meet_url)

        logger.info("=" * 60)
        logger.info(f"MANAGER JOIN: Joining meeting {session_id}")
        logger.info("=" * 60)

        # Run pre-join cleanup to ensure clean state
        logger.info("MANAGER JOIN: Running pre-join cleanup...")
        await self._run_full_cleanup("PRE-JOIN")

        async with self._lock:
            # Check if already in this meeting
            if session_id in self._sessions:
                existing = self._sessions[session_id]
                if existing.bot.state.status == "capturing":
                    return session_id, False, ["Already in this meeting"]
                else:
                    # Clean up old session
                    logger.info(f"MANAGER JOIN: Cleaning up stale session {session_id}")
                    await existing.bot.close()
                    del self._sessions[session_id]
                    if session_id in self._bots:
                        del self._bots[session_id]

            # Create new bot with shared database
            db = await self._get_db()
            bot = NotesBot(db=db)

            # Initialize the bot (this also runs cleanup)
            if not await bot.initialize():
                errors = bot.state.errors or ["Failed to initialize bot"]
                return session_id, False, errors

            # Join the meeting (this also runs pre-join cleanup)
            success = await bot.join_meeting(
                meet_url=meet_url,
                title=title,
                calendar_id=calendar_id,
                event_id=event_id,
                description=description,
                organizer=organizer,
                attendees=attendees,
            )

            if success:
                # Create session with metadata
                session = MeetingSession(
                    bot=bot,
                    session_id=session_id,
                    meet_url=meet_url,
                    title=title or self._generate_session_id(meet_url),
                    scheduled_end=scheduled_end,
                    grace_period_minutes=grace_period_minutes,
                )
                self._sessions[session_id] = session
                self._bots[session_id] = bot  # Backward compatibility

                # Start monitor if we have scheduled end times
                if scheduled_end:
                    await self._start_monitor()

                end_info = ""
                if scheduled_end:
                    end_info = f" (auto-leave at {scheduled_end.strftime('%H:%M')} + {grace_period_minutes}min)"
                logger.info(f"Joined meeting {session_id}{end_info}. Active meetings: {len(self._sessions)}")
                return session_id, True, []
            else:
                errors = bot.state.errors or ["Failed to join meeting"]
                await bot.close()
                return session_id, False, errors

    async def leave_meeting(self, session_id: str) -> dict:
        """
        Leave a specific meeting.

        Args:
            session_id: The session ID returned from join_meeting

        Returns:
            Meeting summary dict or error
        """
        async with self._lock:
            if session_id not in self._sessions:
                # Try backward compatibility
                if session_id in self._bots:
                    bot = self._bots[session_id]
                    result = await bot.leave_meeting()
                    await bot.close()
                    del self._bots[session_id]
                    return result
                return {"error": f"No active meeting with session ID: {session_id}"}

            session = self._sessions[session_id]
            result = await session.bot.leave_meeting()

            # Clean up
            await session.bot.close()
            del self._sessions[session_id]
            if session_id in self._bots:
                del self._bots[session_id]

            # Stop monitor if no more meetings with scheduled ends
            has_scheduled = any(s.scheduled_end for s in self._sessions.values())
            if not has_scheduled and self._monitor_task:
                await self._stop_monitor()

            logger.info(f"Left meeting {session_id}. Active meetings: {len(self._sessions)}")
            return result

    async def leave_all(self) -> list[dict]:
        """Leave all active meetings."""
        # Stop monitor first
        await self._stop_monitor()

        results = []
        session_ids = list(self._sessions.keys())

        for session_id in session_ids:
            result = await self.leave_meeting(session_id)
            result["session_id"] = session_id
            results.append(result)

        return results

    async def get_status(self, session_id: Optional[str] = None) -> dict:
        """
        Get status of one or all active meetings.

        Args:
            session_id: Specific session to get status for, or None for all

        Returns:
            Status dict or dict of statuses keyed by session_id
        """
        if session_id:
            if session_id not in self._sessions:
                return {"error": f"No active meeting with session ID: {session_id}"}
            session = self._sessions[session_id]
            status = await session.bot.get_status()
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            return status

        # Return all statuses
        statuses = {}
        for sid, session in self._sessions.items():
            status = await session.bot.get_status()
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            statuses[sid] = status
        return statuses

    async def get_all_statuses(self) -> list[dict]:
        """Get status of all active meetings as a list."""
        statuses = []
        for session_id, session in self._sessions.items():
            status = await session.bot.get_status()
            status["session_id"] = session_id
            status["scheduled_end"] = session.scheduled_end.isoformat() if session.scheduled_end else None
            status["grace_period_minutes"] = session.grace_period_minutes
            # Calculate time remaining
            if session.scheduled_end:
                remaining = session.scheduled_end - datetime.now()
                status["time_remaining_minutes"] = max(0, remaining.total_seconds() / 60)
            statuses.append(status)
        return statuses

    def get_active_count(self) -> int:
        """Get number of active meetings."""
        return len(self._sessions)

    def get_active_session_ids(self) -> list[str]:
        """Get list of active session IDs."""
        return list(self._sessions.keys())

    def get_bot(self, session_id: str) -> Optional[NotesBot]:
        """Get a specific bot instance."""
        session = self._sessions.get(session_id)
        return session.bot if session else None

    def get_session(self, session_id: str) -> Optional[MeetingSession]:
        """Get a specific session."""
        return self._sessions.get(session_id)

    async def update_scheduled_end(self, session_id: str, scheduled_end: datetime) -> bool:
        """Update the scheduled end time for a meeting."""
        if session_id not in self._sessions:
            return False
        self._sessions[session_id].scheduled_end = scheduled_end
        # Ensure monitor is running
        await self._start_monitor()
        return True

    async def close(self) -> None:
        """Clean up all resources.

        This is the final shutdown method. It:
        1. Stops the monitor task
        2. Leaves all active meetings
        3. Runs final orphan cleanup
        4. Closes the database
        """
        logger.info("=" * 60)
        logger.info("MANAGER CLOSE: Shutting down bot manager...")
        logger.info("=" * 60)

        # Stop monitor first
        try:
            await asyncio.wait_for(self._stop_monitor(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("MANAGER CLOSE: Timeout stopping monitor")

        # Leave all meetings (each will run its own cleanup)
        try:
            await asyncio.wait_for(self.leave_all(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("MANAGER CLOSE: Timeout leaving all meetings")

        # Kill any remaining audio capture processes
        logger.info("MANAGER CLOSE: Killing any remaining audio captures...")
        try:
            from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info(f"MANAGER CLOSE: Killed {killed} audio capture processes")
        except Exception as e:
            logger.warning(f"MANAGER CLOSE: Error killing audio captures: {e}")

        # Final cleanup of any orphaned devices
        logger.info("MANAGER CLOSE: Running final orphan cleanup...")
        await self._run_full_cleanup("SHUTDOWN")

        # Close database
        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.warning(f"MANAGER CLOSE: Error closing database: {e}")
            self._db = None

        self._initialized = False

        logger.info("=" * 60)
        logger.info("MANAGER CLOSE: Bot manager shutdown complete")
        logger.info("=" * 60)


# Global instances
_notes_bot: Optional[NotesBot] = None
_bot_manager: Optional[NotesBotManager] = None


def get_notes_bot() -> NotesBot:
    """Get the global notes bot instance (legacy single-bot mode)."""
    global _notes_bot
    if _notes_bot is None:
        _notes_bot = NotesBot()
    return _notes_bot


async def init_notes_bot() -> NotesBot:
    """Initialize and return the notes bot (legacy single-bot mode).

    Returns the bot instance. Check bot.state.errors if initialization failed.
    """
    bot = get_notes_bot()
    success = await bot.initialize()
    if not success:
        # Errors are stored in bot.state.errors
        pass
    return bot


def get_bot_manager() -> NotesBotManager:
    """Get the global bot manager instance."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = NotesBotManager()
    return _bot_manager


async def init_bot_manager() -> NotesBotManager:
    """Initialize and return the bot manager.

    This runs startup cleanup to remove any orphaned devices from previous sessions.
    """
    manager = get_bot_manager()
    await manager.initialize()
    return manager
