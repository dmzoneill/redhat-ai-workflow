"""
Interactive actions for the Notes Bot.

Handles:
- Interactive mode setup (LLM + TTS)
- Wake word command processing
- Streaming LLM responses with TTS
- Video daemon integration via D-Bus
- Participant polling and attendee updates
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Optional

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.llm_responder import LLMResponder
from tool_modules.aa_meet_bot.src.wake_word import WakeWordEvent, WakeWordManager

# D-Bus client for video daemon communication
_video_dbus_available = False
try:
    from scripts.common.dbus_base import get_client

    _video_dbus_available = True
except ImportError:
    pass

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
    from tool_modules.aa_meet_bot.src.notes_bot import NotesBotState

logger = logging.getLogger(__name__)


class InteractiveActions:
    """Manages interactive mode features for the Notes Bot.

    Handles:
    - LLM responder initialization and meeting context
    - Wake word command processing (command -> LLM -> TTS -> audio pipe)
    - Streaming LLM responses sentence-by-sentence for lower latency
    - Video daemon integration via D-Bus (attendee overlays, audio waveform)
    - Participant polling from Google Meet

    This is a component of NotesBot, composed via dependency injection.
    """

    def __init__(
        self,
        state: "NotesBotState",
        wake_word_manager: Optional[WakeWordManager] = None,
    ):
        self._state = state
        self._wake_word_manager = wake_word_manager
        self.config = get_config()

        # Interactive mode components
        self._llm_responder: Optional[LLMResponder] = None
        self._interactive_mode: bool = False
        self._responding: bool = False  # Prevent overlapping responses

        # Video daemon integration
        self._video_daemon_active: bool = False
        self._participant_poll_task: Optional[asyncio.Task] = None
        self._enable_video_integration: bool = _video_dbus_available

        # Controller reference (set by bot after construction)
        self._controller: Optional["GoogleMeetController"] = None

    @property
    def interactive_mode(self) -> bool:
        return self._interactive_mode

    @interactive_mode.setter
    def interactive_mode(self, value: bool):
        self._interactive_mode = value

    @property
    def responding(self) -> bool:
        return self._responding

    @property
    def video_daemon_active(self) -> bool:
        return self._video_daemon_active

    @property
    def enable_video_integration(self) -> bool:
        return self._enable_video_integration

    async def setup_interactive_mode(self) -> None:
        """Set up interactive mode with LLM and TTS.

        Creates an LLM responder with meeting context for conversation tracking.
        Optionally sets up NPU STT for real-time transcription.
        """
        try:
            # Create meeting ID from database ID or generate one
            meeting_id = (
                str(self._state.meeting_id)
                if self._state.meeting_id
                else f"meet-{id(self)}"
            )
            meeting_title = self._state.title or "Untitled Meeting"

            # Initialize LLM responder with meeting context
            self._llm_responder = LLMResponder(meeting_id=meeting_id)
            self._llm_responder.set_meeting_context(meeting_id, meeting_title)
            await self._llm_responder.initialize()

            logger.info(
                f"🎤 Interactive mode: LLM responder initialized for meeting '{meeting_title}' (ID: {meeting_id})"
            )
            logger.info(
                "🎤 Interactive mode: Conversation history will be maintained throughout this meeting"
            )

            # Set up wake word callback for voice responses
            logger.info(
                f"🎤 Interactive mode: Listening for wake word '{self.config.wake_word}'"
            )

        except Exception as e:
            logger.error(f"Failed to set up interactive mode: {e}")
            self._interactive_mode = False

    async def handle_wake_word_command(self, event: WakeWordEvent) -> None:
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
            context_entries = self._state.transcript_buffer[-10:]
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

    async def _stream_and_speak(
        self, command: str, speaker: str, context_before: list
    ) -> None:
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
            self._llm_responder.conversation_history.append(
                {"role": "user", "content": command}
            )
            self._llm_responder.conversation_history.append(
                {"role": "assistant", "content": " ".join(full_response)}
            )
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
                logger.info(
                    f"🔊 Playing audio ({duration:.1f}s), waiting {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)
                logger.info("🔊 Finished speaking")
            else:
                logger.warning("Failed to write audio to pipe")

        except Exception as e:
            logger.error(f"TTS error: {e}")
            import traceback

            traceback.print_exc()

    # ── Video daemon integration ──────────────────────────────────────────

    async def start_video_integration(self, controller) -> None:
        """Start or upgrade video daemon integration via D-Bus.

        The video daemon is already streaming (black screen) before the browser
        launched. This method:
        - Switches from black screen to full AI video overlay
        - Finds Chromium's sink-input index for audio capture
        - Starts polling for participant updates
        - Sends participant updates via D-Bus

        If video was disabled for this meeting, this is a no-op (keeps black screen).

        Args:
            controller: The GoogleMeetController instance
        """
        if not _video_dbus_available:
            logger.debug("Video D-Bus integration not available")
            return

        try:
            # Get device info from the controller
            video_device = None
            audio_source = None
            sink_name = None
            if controller:
                devices = controller.get_audio_devices()
                if devices:
                    video_device = devices.video_device
                    sink_name = devices.sink_name
                    # Audio source is the sink's monitor (for logging - actual capture via sink-input)
                    audio_source = (
                        f"{devices.sink_name}.monitor" if devices.sink_name else None
                    )
                    logger.info(
                        f"📺 Device info: video={video_device}, audio={audio_source}"
                    )

            if not video_device:
                logger.warning(
                    "📺 No video device available, skipping video integration"
                )
                return

            # Find Chromium's sink-input index for monitor-stream capture
            sink_input_index = await self._find_chromium_sink_input(sink_name)
            if sink_input_index is not None:
                logger.info(f"📺 Found Chromium sink-input index: {sink_input_index}")
            else:
                logger.warning(
                    "📺 Could not find Chromium sink-input, waveform may not work"
                )

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
                    logger.info(
                        f"📺 update_audio_source failed ({result}), trying switch_to_full_video..."
                    )
                    result = await client.call_method(
                        "switch_to_full_video",
                        [
                            audio_source or "",
                            "",
                            False,
                            sink_input_index if sink_input_index is not None else -1,
                        ],
                    )

                await client.disconnect()

                if result and result.get("success"):
                    self._video_daemon_active = True
                    logger.info(f"📺 Video integration active on {video_device}")

                    # Start participant polling task
                    self._participant_poll_task = asyncio.create_task(
                        self._poll_participants(controller)
                    )
                else:
                    # May fail if video was disabled - that's OK, keep black screen
                    logger.info(f"📺 Video result: {result}")
                    # Still mark as active for cleanup purposes
                    self._video_daemon_active = True
            else:
                logger.warning("📺 Could not connect to video daemon D-Bus service")

        except Exception as e:
            logger.warning(f"📺 Failed to start video integration: {e}")

    async def _find_chromium_sink_input(
        self, target_sink: Optional[str]
    ) -> Optional[int]:
        """Find Chromium's sink-input index for monitor-stream capture.

        PipeWire's null-sink monitors don't work properly (output zeros).
        Instead, we use parec --monitor-stream=<index> to capture directly
        from Chromium's audio stream.

        Args:
            target_sink: The sink name Chromium should be connected to

        Returns:
            Sink-input index if found, None otherwise
        """
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
                        sink_name = sink_id_to_name.get(
                            current_sink_id, current_sink_id
                        )
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

            logger.info(
                f"📺 Found {len(chromium_candidates)} Chromium sink-inputs: {chromium_candidates}"
            )

            # Find the one connected to our target sink
            for idx, sink_name in chromium_candidates:
                if target_sink and target_sink in sink_name:
                    logger.info(
                        f"📺 Selected Chromium sink-input {idx} (connected to {sink_name})"
                    )
                    return idx

            # If no match but we have candidates, return the last one (most recent)
            # This handles cases where Playwright Chromium might be named differently
            if chromium_candidates:
                idx, sink_name = chromium_candidates[-1]
                logger.info(
                    f"📺 Using last Chromium sink-input {idx} (connected to {sink_name})"
                )
                return idx

            return None

        except Exception as e:
            logger.warning(f"📺 Error finding Chromium sink-input: {e}")
            return None

    async def _poll_participants(self, controller) -> None:
        """Poll Google Meet for participant updates.

        Does rapid initial polls (every 2s for first 10s) to quickly get
        participants, then slows to every 15 seconds (matching video rotation).

        Args:
            controller: The GoogleMeetController instance
        """
        poll_count = 0
        rapid_poll_count = 5  # First 5 polls are rapid (every 2s = 10s total)
        rapid_interval = 2.0  # Fast polling at start
        normal_interval = 15.0  # Match video rotation interval

        while (
            self._state.status == "capturing"
            and controller
            and self._video_daemon_active
        ):
            try:
                # Get participants from Google Meet
                participants = await controller.get_participants()

                if participants:
                    # Send to video daemon via D-Bus
                    await self._update_video_attendees(participants)
                    if poll_count == 0:
                        logger.info(
                            f"📺 Initial participant poll: {len(participants)} participants"
                        )
                    else:
                        logger.debug(
                            f"📺 Sent {len(participants)} participants to video daemon"
                        )

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

    async def stop_video_integration(self) -> None:
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
