"""
Attendee Data Service - IPC between Meet Bot and Video Generator.

Provides a Unix socket server that:
- Receives participant updates from the Meet Bot
- Enriches attendee data from app-interface, Slack, etc.
- Broadcasts updates to connected video generator clients

Socket location: ~/.config/aa-workflow/meetbot.sock

Protocol (JSON messages, newline-delimited):
- Server -> Client: {"type": "attendees_update", "attendees": [...], "current_index": 0}
- Server -> Client: {"type": "attendee_enriched", "index": 0, "data": {...}}
- Server -> Client: {"type": "meeting_status", "status": "active|scanning|ended"}
- Client -> Server: {"type": "get_state"}
- Client -> Server: {"type": "set_current_index", "index": 0}
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .attendee_enricher import AttendeeEnricher

logger = logging.getLogger(__name__)

# Socket path - centralized in server.paths
try:
    from server.paths import AA_CONFIG_DIR, MEETBOT_SOCKET

    SOCKET_DIR = AA_CONFIG_DIR
    SOCKET_PATH = MEETBOT_SOCKET
except ImportError:
    # Fallback for standalone usage
    SOCKET_DIR = Path.home() / ".config" / "aa-workflow"
    SOCKET_PATH = SOCKET_DIR / "meetbot.sock"

# Photo cache directory
PHOTO_CACHE_DIR = Path.home() / ".cache" / "aa-workflow" / "photos"


@dataclass
class EnrichedAttendee:
    """Attendee with enriched data from various sources."""

    name: str
    email: Optional[str] = None

    # From app-interface
    github_username: Optional[str] = None
    slack_id: Optional[str] = None
    team: Optional[str] = None
    role: Optional[str] = None

    # From Slack
    photo_path: Optional[str] = None  # Local cached photo path
    display_name: Optional[str] = None

    # Computed
    initials: str = ""
    color_hue: int = 0  # For fallback avatar color

    def __post_init__(self):
        """Compute derived fields."""
        if not self.initials and self.name:
            parts = self.name.split()
            self.initials = "".join(p[0].upper() for p in parts[:2] if p)
        if not self.color_hue:
            # Deterministic color from name
            self.color_hue = hash(self.name) % 360

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class MeetingState:
    """Current state of the meeting for IPC."""

    status: str = "scanning"  # scanning, active, ended
    attendees: list[EnrichedAttendee] = field(default_factory=list)
    current_index: int = 0
    meeting_title: str = ""
    participant_count: int = 0

    # Device paths for video generator to use (set by meetbot)
    video_device: Optional[str] = None  # e.g., "/dev/video11"
    audio_source: Optional[str] = None  # e.g., "meet_bot_abc123.monitor"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "attendees": [a.to_dict() for a in self.attendees],
            "current_index": self.current_index,
            "meeting_title": self.meeting_title,
            "participant_count": self.participant_count,
            "video_device": self.video_device,
            "audio_source": self.audio_source,
        }


class AttendeeDataService:
    """
    Unix socket server for sharing attendee data between processes.

    The Meet Bot updates this service with participant info, and the
    Video Generator connects as a client to receive updates.
    """

    def __init__(self):
        self._server: Optional[asyncio.Server] = None
        self._clients: list[asyncio.StreamWriter] = []
        self._state = MeetingState()
        self._enricher: Optional["AttendeeEnricher"] = None
        self._lock = asyncio.Lock()
        self._running = False

        # Periodic polling configuration
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval: float = 30.0  # seconds between polls
        self._poll_duration: float = 600.0  # 10 minutes total polling duration
        self._poll_callback: Optional[Callable[[], Any]] = None  # Async callback to get participants
        self._poll_start_time: float = 0.0

        # Callbacks for external integration
        self._on_state_change: Optional[Callable[[MeetingState], None]] = None

    async def start(self) -> bool:
        """
        Start the Unix socket server.

        Returns:
            True if server started successfully.
        """
        if self._running:
            logger.warning("AttendeeDataService already running")
            return True

        try:
            # Ensure socket directory exists
            SOCKET_DIR.mkdir(parents=True, exist_ok=True)

            # Remove stale socket file
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()

            # Create Unix socket server
            self._server = await asyncio.start_unix_server(self._handle_client, path=str(SOCKET_PATH))

            # Set socket permissions (readable/writable by user only)
            SOCKET_PATH.chmod(0o600)

            self._running = True
            logger.info(f"AttendeeDataService started on {SOCKET_PATH}")

            # Initialize enricher
            try:
                from .attendee_enricher import AttendeeEnricher

                self._enricher = AttendeeEnricher()
                await self._enricher.initialize()
                logger.info("Attendee enricher initialized")
            except ImportError:
                logger.warning("AttendeeEnricher not available - enrichment disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize enricher: {e}")

            return True

        except Exception as e:
            logger.error(f"Failed to start AttendeeDataService: {e}")
            return False

    async def stop(self) -> None:
        """Stop the server and clean up."""
        self._running = False

        # Close all client connections
        for writer in self._clients:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except Exception:
                pass

        logger.info("AttendeeDataService stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a connected client."""
        peer = writer.get_extra_info("peername") or "unknown"
        logger.info(f"Client connected: {peer}")
        self._clients.append(writer)

        try:
            # Send current state immediately
            await self._send_message(
                writer,
                {
                    "type": "meeting_status",
                    "status": self._state.status,
                },
            )

            if self._state.attendees:
                await self._send_message(
                    writer,
                    {
                        "type": "attendees_update",
                        "attendees": [a.to_dict() for a in self._state.attendees],
                        "current_index": self._state.current_index,
                    },
                )

            # Read client messages
            while self._running:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=30.0)  # Keepalive timeout

                    if not line:
                        break  # Client disconnected

                    await self._handle_message(writer, line.decode().strip())

                except asyncio.TimeoutError:
                    # Send keepalive
                    try:
                        await self._send_message(writer, {"type": "keepalive"})
                    except Exception:
                        break
                except Exception as e:
                    logger.debug(f"Client read error: {e}")
                    break

        except Exception as e:
            logger.debug(f"Client handler error: {e}")
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Client disconnected: {peer}")

    async def _handle_message(self, writer: asyncio.StreamWriter, message: str) -> None:
        """Handle a message from a client."""
        if not message:
            return

        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "get_state":
                # Send full state
                await self._send_message(
                    writer,
                    {
                        "type": "full_state",
                        "state": self._state.to_dict(),
                    },
                )

            elif msg_type == "set_current_index":
                # Update current attendee index
                index = data.get("index", 0)
                async with self._lock:
                    if 0 <= index < len(self._state.attendees):
                        self._state.current_index = index
                        await self._broadcast(
                            {
                                "type": "index_changed",
                                "index": index,
                            }
                        )

            elif msg_type == "ping":
                await self._send_message(writer, {"type": "pong"})

        except json.JSONDecodeError:
            logger.debug(f"Invalid JSON from client: {message[:100]}")
        except Exception as e:
            logger.debug(f"Error handling message: {e}")

    async def _send_message(self, writer: asyncio.StreamWriter, data: dict) -> None:
        """Send a JSON message to a client."""
        try:
            message = json.dumps(data) + "\n"
            writer.write(message.encode())
            await writer.drain()
        except Exception as e:
            logger.debug(f"Failed to send message: {e}")

    async def _broadcast(self, data: dict) -> None:
        """Broadcast a message to all connected clients."""
        message = json.dumps(data) + "\n"
        encoded = message.encode()

        disconnected = []
        for writer in self._clients:
            try:
                writer.write(encoded)
                await writer.drain()
            except Exception:
                disconnected.append(writer)

        # Remove disconnected clients
        for writer in disconnected:
            if writer in self._clients:
                self._clients.remove(writer)

    # ==================== Public API for Meet Bot ====================

    async def set_meeting_status(
        self,
        status: str,
        title: str = "",
        video_device: Optional[str] = None,
        audio_source: Optional[str] = None,
    ) -> None:
        """
        Update the meeting status and device info.

        Args:
            status: "scanning", "active", or "ended"
            title: Meeting title (optional)
            video_device: v4l2loopback device path for video output (e.g., "/dev/video11")
            audio_source: PulseAudio source for audio capture (e.g., "meet_bot_abc123.monitor")
        """
        async with self._lock:
            self._state.status = status
            if title:
                self._state.meeting_title = title
            if video_device:
                self._state.video_device = video_device
            if audio_source:
                self._state.audio_source = audio_source

        await self._broadcast(
            {
                "type": "meeting_status",
                "status": status,
                "title": title,
                "video_device": video_device,
                "audio_source": audio_source,
            }
        )

        if self._on_state_change:
            self._on_state_change(self._state)

    async def update_participants(self, participants: list[dict], enrich: bool = True) -> None:
        """
        Update the participant list from Google Meet.

        Args:
            participants: List of dicts with 'name' and optionally 'email'
            enrich: Whether to enrich with app-interface/Slack data
        """
        async with self._lock:
            # Convert to EnrichedAttendee objects
            new_attendees = []
            for p in participants:
                attendee = EnrichedAttendee(
                    name=p.get("name", "Unknown"),
                    email=p.get("email"),
                )
                new_attendees.append(attendee)

            # Preserve enrichment data for existing attendees
            existing_by_name = {a.name: a for a in self._state.attendees}
            for attendee in new_attendees:
                if attendee.name in existing_by_name:
                    old = existing_by_name[attendee.name]
                    attendee.github_username = old.github_username
                    attendee.slack_id = old.slack_id
                    attendee.team = old.team
                    attendee.role = old.role
                    attendee.photo_path = old.photo_path
                    attendee.display_name = old.display_name

            self._state.attendees = new_attendees
            self._state.participant_count = len(new_attendees)

            # Update status if we have participants
            if new_attendees and self._state.status == "scanning":
                self._state.status = "active"

        # Broadcast update
        await self._broadcast(
            {
                "type": "attendees_update",
                "attendees": [a.to_dict() for a in self._state.attendees],
                "current_index": self._state.current_index,
                "status": self._state.status,
            }
        )

        # Enrich in background
        if enrich and self._enricher:
            asyncio.create_task(self._enrich_attendees())

        if self._on_state_change:
            self._on_state_change(self._state)

    async def _enrich_attendees(self) -> None:
        """Enrich attendees with data from external sources."""
        if not self._enricher:
            return

        for i, attendee in enumerate(self._state.attendees):
            try:
                enriched = await self._enricher.enrich(attendee)

                async with self._lock:
                    if i < len(self._state.attendees):
                        self._state.attendees[i] = enriched

                # Broadcast individual enrichment
                await self._broadcast(
                    {
                        "type": "attendee_enriched",
                        "index": i,
                        "data": enriched.to_dict(),
                    }
                )

            except Exception as e:
                logger.debug(f"Failed to enrich {attendee.name}: {e}")

    # ==================== Periodic Polling ====================

    async def start_periodic_polling(
        self,
        poll_callback: Callable[[], Any],
        interval: float = 30.0,
        duration: float = 600.0,
    ) -> None:
        """
        Start periodic polling for new attendees.

        This polls for new participants at regular intervals for a fixed duration,
        useful for detecting new people joining the meeting in the first 10 minutes.

        Args:
            poll_callback: Async function that returns list[dict] with participant data
                          (same format as update_participants expects)
            interval: Seconds between polls (default 30)
            duration: Total duration to poll in seconds (default 600 = 10 minutes)
        """
        # Stop any existing polling
        await self.stop_periodic_polling()

        self._poll_callback = poll_callback
        self._poll_interval = interval
        self._poll_duration = duration
        self._poll_start_time = time.time()

        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info(f"Started periodic attendee polling: every {interval}s for {duration}s")

    async def stop_periodic_polling(self) -> None:
        """Stop periodic polling if running."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            logger.info("Stopped periodic attendee polling")

    async def _polling_loop(self) -> None:
        """Internal polling loop."""
        try:
            while self._running:
                # Check if we've exceeded the duration
                elapsed = time.time() - self._poll_start_time
                if elapsed >= self._poll_duration:
                    logger.info(f"Periodic polling completed after {elapsed:.0f}s")
                    break

                # Wait for the interval
                try:
                    await asyncio.sleep(self._poll_interval)
                except asyncio.CancelledError:
                    break

                # Check again after sleep
                if not self._running:
                    break

                # Call the poll callback
                if self._poll_callback:
                    try:
                        participants = await self._poll_callback()
                        if participants:
                            # Check for new participants
                            existing_names = {a.name for a in self._state.attendees}
                            new_count = sum(1 for p in participants if p.get("name") not in existing_names)

                            if new_count > 0:
                                logger.info(f"Polling detected {new_count} new participant(s)")

                            # Update participants (will broadcast changes)
                            await self.update_participants(participants)

                    except Exception as e:
                        logger.warning(f"Polling callback error: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
        finally:
            self._poll_task = None

    def is_polling(self) -> bool:
        """Check if periodic polling is active."""
        return self._poll_task is not None and not self._poll_task.done()

    def get_polling_status(self) -> dict:
        """Get current polling status."""
        if not self.is_polling():
            return {
                "active": False,
                "elapsed": 0,
                "remaining": 0,
            }

        elapsed = time.time() - self._poll_start_time
        remaining = max(0, self._poll_duration - elapsed)
        return {
            "active": True,
            "elapsed": elapsed,
            "remaining": remaining,
            "interval": self._poll_interval,
            "duration": self._poll_duration,
        }

    def get_state(self) -> MeetingState:
        """Get current meeting state (for local access)."""
        return self._state

    def set_state_change_callback(self, callback: Callable[[MeetingState], None]) -> None:
        """Set callback for state changes."""
        self._on_state_change = callback


class AttendeeDataClient:
    """
    Client for connecting to the AttendeeDataService.

    Used by the Video Generator to receive attendee updates.
    """

    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._state = MeetingState()
        self._lock = asyncio.Lock()
        self._receive_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_attendees_update: Optional[Callable[[list[EnrichedAttendee]], None]] = None
        self._on_status_change: Optional[Callable[[str], None]] = None
        self._on_attendee_enriched: Optional[Callable[[int, EnrichedAttendee], None]] = None

    async def connect(self, timeout: float = 5.0) -> bool:
        """
        Connect to the AttendeeDataService.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connected successfully.
        """
        if self._connected:
            return True

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(SOCKET_PATH)), timeout=timeout
            )
            self._connected = True

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            logger.info(f"Connected to AttendeeDataService at {SOCKET_PATH}")
            return True

        except FileNotFoundError:
            logger.debug(f"Socket not found: {SOCKET_PATH}")
            return False
        except asyncio.TimeoutError:
            logger.debug("Connection timeout")
            return False
        except Exception as e:
            logger.debug(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the service."""
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        logger.info("Disconnected from AttendeeDataService")

    async def _receive_loop(self) -> None:
        """Receive and process messages from the server."""
        while self._connected and self._reader:
            try:
                line = await self._reader.readline()
                if not line:
                    break

                await self._handle_message(line.decode().strip())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Receive error: {e}")
                break

        self._connected = False

    async def _handle_message(self, message: str) -> None:
        """Handle a message from the server."""
        if not message:
            return

        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "attendees_update":
                attendees = [EnrichedAttendee(**a) for a in data.get("attendees", [])]
                async with self._lock:
                    self._state.attendees = attendees
                    self._state.current_index = data.get("current_index", 0)
                    if "status" in data:
                        self._state.status = data["status"]

                if self._on_attendees_update:
                    self._on_attendees_update(attendees)

            elif msg_type == "meeting_status":
                status = data.get("status", "scanning")
                async with self._lock:
                    self._state.status = status
                    if "title" in data:
                        self._state.meeting_title = data["title"]
                    if "video_device" in data and data["video_device"]:
                        self._state.video_device = data["video_device"]
                    if "audio_source" in data and data["audio_source"]:
                        self._state.audio_source = data["audio_source"]

                if self._on_status_change:
                    self._on_status_change(status)

            elif msg_type == "attendee_enriched":
                index = data.get("index", 0)
                attendee_data = data.get("data", {})
                attendee = EnrichedAttendee(**attendee_data)

                async with self._lock:
                    if 0 <= index < len(self._state.attendees):
                        self._state.attendees[index] = attendee

                if self._on_attendee_enriched:
                    self._on_attendee_enriched(index, attendee)

            elif msg_type == "full_state":
                state_data = data.get("state", {})
                async with self._lock:
                    self._state.status = state_data.get("status", "scanning")
                    self._state.current_index = state_data.get("current_index", 0)
                    self._state.meeting_title = state_data.get("meeting_title", "")
                    self._state.attendees = [EnrichedAttendee(**a) for a in state_data.get("attendees", [])]
                    self._state.video_device = state_data.get("video_device")
                    self._state.audio_source = state_data.get("audio_source")

            elif msg_type == "keepalive" or msg_type == "pong":
                pass  # Ignore keepalives

        except json.JSONDecodeError:
            logger.debug(f"Invalid JSON from server: {message[:100]}")
        except Exception as e:
            logger.debug(f"Error handling server message: {e}")

    async def request_state(self) -> None:
        """Request full state from server."""
        await self._send({"type": "get_state"})

    async def set_current_index(self, index: int) -> None:
        """Tell server which attendee is currently displayed."""
        await self._send({"type": "set_current_index", "index": index})

    async def _send(self, data: dict) -> None:
        """Send a message to the server."""
        if not self._connected or not self._writer:
            return

        try:
            message = json.dumps(data) + "\n"
            self._writer.write(message.encode())
            await self._writer.drain()
        except Exception as e:
            logger.debug(f"Send failed: {e}")

    def get_state(self) -> MeetingState:
        """Get current state (local copy)."""
        return self._state

    def get_attendees(self) -> list[EnrichedAttendee]:
        """Get current attendee list."""
        return self._state.attendees

    def get_current_attendee(self) -> Optional[EnrichedAttendee]:
        """Get the currently displayed attendee."""
        if self._state.attendees and 0 <= self._state.current_index < len(self._state.attendees):
            return self._state.attendees[self._state.current_index]
        return None

    def get_video_device(self) -> Optional[str]:
        """Get the video device path from the meetbot."""
        return self._state.video_device

    def get_audio_source(self) -> Optional[str]:
        """Get the audio source name from the meetbot."""
        return self._state.audio_source

    def is_connected(self) -> bool:
        """Check if connected to service."""
        return self._connected

    # Callback setters
    def on_attendees_update(self, callback: Callable[[list[EnrichedAttendee]], None]) -> None:
        """Set callback for attendee list updates."""
        self._on_attendees_update = callback

    def on_status_change(self, callback: Callable[[str], None]) -> None:
        """Set callback for meeting status changes."""
        self._on_status_change = callback

    def on_attendee_enriched(self, callback: Callable[[int, EnrichedAttendee], None]) -> None:
        """Set callback for individual attendee enrichment."""
        self._on_attendee_enriched = callback


# Global service instance
_service: Optional[AttendeeDataService] = None


async def get_service() -> AttendeeDataService:
    """Get or create the global AttendeeDataService instance."""
    global _service
    if _service is None:
        _service = AttendeeDataService()
    return _service


async def start_service() -> AttendeeDataService:
    """Start the global AttendeeDataService."""
    service = await get_service()
    await service.start()
    return service
