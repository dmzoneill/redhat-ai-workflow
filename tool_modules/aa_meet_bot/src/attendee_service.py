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
import importlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

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

# Socket and stream failures (closed peers, broken pipes, bad encodings).
_IO_ERRORS: tuple[type[Exception], ...] = (OSError, RuntimeError, ValueError, asyncio.TimeoutError)
# Sending: I/O failures, or a payload json.dumps cannot serialize.
_SEND_ERRORS: tuple[type[Exception], ...] = (*_IO_ERRORS, TypeError)
# Failures from enrichment and polling callbacks (external lookups, bad data).
_CALLBACK_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    asyncio.TimeoutError,
)
# Malformed protocol messages: bad JSON, non-object payloads, unknown fields.
_MESSAGE_ERRORS: tuple[type[Exception], ...] = (ValueError, TypeError, LookupError, AttributeError)


async def _cancel_and_wait(task: asyncio.Task) -> None:
    """Cancel ``task`` and wait for it to finish without re-raising its cancellation."""
    task.cancel()
    await asyncio.wait({task})


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    """Close a stream writer, ignoring errors from an already-broken connection."""
    try:
        writer.close()
        await writer.wait_closed()
    except _IO_ERRORS as e:
        logger.debug("Error closing stream: %s", e)


@dataclass
class _DirectoryInfo:
    """Attendee details from app-interface."""

    github_username: str | None = None
    slack_id: str | None = None
    team: str | None = None
    role: str | None = None


@dataclass
class _SlackInfo:
    """Attendee details from Slack."""

    photo_path: str | None = None  # Local cached photo path
    display_name: str | None = None


@dataclass
class _Avatar:
    """Computed fallback avatar details."""

    initials: str = ""
    color_hue: int = 0  # For fallback avatar color


def _part_property(part: str, name: str, doc: str) -> property:
    """Expose ``self.<part>.<name>`` as a read/write attribute."""

    def getter(self):
        return getattr(getattr(self, part), name)

    def setter(self, value):
        setattr(getattr(self, part), name, value)

    return property(getter, setter, doc=doc)


class EnrichedAttendee:
    """Attendee with enriched data from various sources.

    Behaves like the former dataclass: the same constructor (positional or
    keyword), attributes, ``to_dict()`` output, equality and repr. The fields
    are stored in three small parts (directory, Slack, avatar).
    """

    FIELDS: tuple[str, ...] = (
        "name",
        "email",
        "github_username",
        "slack_id",
        "team",
        "role",
        "photo_path",
        "display_name",
        "initials",
        "color_hue",
    )

    github_username = _part_property("_directory", "github_username", "GitHub username (app-interface).")
    slack_id = _part_property("_directory", "slack_id", "Slack user ID (app-interface).")
    team = _part_property("_directory", "team", "Team (app-interface).")
    role = _part_property("_directory", "role", "Role (app-interface).")
    photo_path = _part_property("_slack", "photo_path", "Local cached photo path (Slack).")
    display_name = _part_property("_slack", "display_name", "Display name (Slack).")
    initials = _part_property("_avatar", "initials", "Initials for the fallback avatar.")
    color_hue = _part_property("_avatar", "color_hue", "Hue for the fallback avatar.")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        values = self._bind(args, kwargs)
        self.name: str = values["name"]
        self.email: str | None = values.get("email")
        self._directory = _DirectoryInfo(
            github_username=values.get("github_username"),
            slack_id=values.get("slack_id"),
            team=values.get("team"),
            role=values.get("role"),
        )
        self._slack = _SlackInfo(photo_path=values.get("photo_path"), display_name=values.get("display_name"))
        self._avatar = _Avatar(initials=values.get("initials", ""), color_hue=values.get("color_hue", 0))
        self._compute_avatar()

    @classmethod
    def _bind(cls, args: tuple, kwargs: dict) -> dict[str, Any]:
        """Bind constructor arguments to field names, as a dataclass would."""
        if len(args) > len(cls.FIELDS):
            raise TypeError(f"EnrichedAttendee takes at most {len(cls.FIELDS)} positional arguments")
        values = dict(zip(cls.FIELDS, args, strict=False))
        for key, value in kwargs.items():
            if key not in cls.FIELDS:
                raise TypeError(f"EnrichedAttendee got an unexpected keyword argument '{key}'")
            if key in values:
                raise TypeError(f"EnrichedAttendee got multiple values for argument '{key}'")
            values[key] = value
        if "name" not in values:
            raise TypeError("EnrichedAttendee missing 1 required positional argument: 'name'")
        return values

    def _compute_avatar(self) -> None:
        """Compute derived fields."""
        if not self.initials and self.name:
            parts = self.name.split()
            self.initials = "".join(p[0].upper() for p in parts[:2] if p)
        if not self.color_hue:
            # Deterministic color from name
            self.color_hue = hash(self.name) % 360

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {name: getattr(self, name) for name in self.FIELDS}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EnrichedAttendee) or other.__class__ is not self.__class__:
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        # Mutable value object: unhashable, like an eq=True dataclass
        raise TypeError(f"unhashable type: '{self.__class__.__name__}'")

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.FIELDS)
        return f"{self.__class__.__qualname__}({fields})"


@dataclass
class MeetingState:
    """Current state of the meeting for IPC."""

    status: str = "scanning"  # scanning, active, ended
    attendees: list[EnrichedAttendee] = field(default_factory=list)
    current_index: int = 0
    meeting_title: str = ""
    participant_count: int = 0

    # Device paths for video generator to use (set by meetbot)
    video_device: str | None = None  # e.g., "/dev/video11"
    audio_source: str | None = None  # e.g., "meet_bot_abc123.monitor"

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


class _Enricher(Protocol):
    """What the service needs from AttendeeEnricher."""

    async def initialize(self) -> None:
        """Prepare data sources."""

    async def enrich(self, attendee: EnrichedAttendee) -> EnrichedAttendee:
        """Return the attendee with extra details filled in."""


def _load_enricher() -> _Enricher | None:
    """Create an AttendeeEnricher if its module is importable."""
    try:
        module = importlib.import_module(".attendee_enricher", __package__)
    except (ImportError, TypeError):
        return None
    enricher: _Enricher = module.AttendeeEnricher()
    return enricher


def _carry_enrichment(new_attendees: list[EnrichedAttendee], previous: list[EnrichedAttendee]) -> None:
    """Copy enrichment data from previous attendees with the same name."""
    existing_by_name = {a.name: a for a in previous}
    for attendee in new_attendees:
        old = existing_by_name.get(attendee.name)
        if old is not None:
            attendee.github_username = old.github_username
            attendee.slack_id = old.slack_id
            attendee.team = old.team
            attendee.role = old.role
            attendee.photo_path = old.photo_path
            attendee.display_name = old.display_name


@dataclass
class _Polling:
    """Periodic polling configuration and task."""

    task: asyncio.Task | None = None
    interval: float = 30.0  # seconds between polls
    duration: float = 600.0  # 10 minutes total polling duration
    callback: Callable[[], Awaitable[Any]] | None = None  # Async callback to get participants
    start_time: float = 0.0


@dataclass
class _ServerIO:
    """Socket server, its connected clients and whether it is running."""

    server: asyncio.Server | None = None
    clients: list[asyncio.StreamWriter] = field(default_factory=list)
    running: bool = False


class AttendeeDataService:
    """
    Unix socket server for sharing attendee data between processes.

    The Meet Bot updates this service with participant info, and the
    Video Generator connects as a client to receive updates.
    """

    def __init__(self):
        self._io = _ServerIO()
        self._state = MeetingState()
        self._enricher: _Enricher | None = None
        self._lock = asyncio.Lock()
        self._poll = _Polling()
        # Background tasks are kept here so they are not garbage-collected mid-run
        self._tasks: set[asyncio.Task] = set()

        # Callbacks for external integration
        self._on_state_change: Callable[[MeetingState], None] | None = None

    async def start(self) -> bool:
        """
        Start the Unix socket server.

        Returns:
            True if server started successfully.
        """
        if self._io.running:
            logger.warning("AttendeeDataService already running")
            return True

        try:
            # Ensure socket directory exists
            SOCKET_DIR.mkdir(parents=True, exist_ok=True)

            # Remove stale socket file
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()

            # Create Unix socket server
            self._io.server = await asyncio.start_unix_server(self._handle_client, path=str(SOCKET_PATH))

            # Set socket permissions (readable/writable by user only)
            SOCKET_PATH.chmod(0o600)
        except _IO_ERRORS as e:
            logger.error("Failed to start AttendeeDataService: %s", e)
            return False

        self._io.running = True
        logger.info("AttendeeDataService started on %s", SOCKET_PATH)
        await self._init_enricher()
        return True

    async def _init_enricher(self) -> None:
        """Initialize the enricher; enrichment is disabled if it is unavailable."""
        enricher = _load_enricher()
        if enricher is None:
            logger.warning("AttendeeEnricher not available - enrichment disabled")
            return
        self._enricher = enricher
        try:
            await enricher.initialize()
            logger.info("Attendee enricher initialized")
        except _CALLBACK_ERRORS as e:
            logger.warning("Failed to initialize enricher: %s", e)

    async def stop(self) -> None:
        """Stop the server and clean up."""
        self._io.running = False

        # Close all client connections
        for writer in self._io.clients:
            await _close_writer(writer)
        self._io.clients.clear()

        # Close server
        if self._io.server:
            self._io.server.close()
            await self._io.server.wait_closed()
            self._io.server = None

        # Remove socket file
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except OSError as e:
                logger.debug("Could not remove socket file: %s", e)

        logger.info("AttendeeDataService stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a connected client."""
        peer = writer.get_extra_info("peername") or "unknown"
        logger.info("Client connected: %s", peer)
        self._io.clients.append(writer)

        try:
            await self._send_initial_state(writer)
            await self._client_read_loop(reader, writer)
        except _IO_ERRORS as e:
            logger.debug("Client handler error: %s", e)
        finally:
            if writer in self._io.clients:
                self._io.clients.remove(writer)
            await _close_writer(writer)
            logger.info("Client disconnected: %s", peer)

    async def _send_initial_state(self, writer: asyncio.StreamWriter) -> None:
        """Send the current status (and attendees, if any) to a new client."""
        await self._send_message(writer, {"type": "meeting_status", "status": self._state.status})
        if self._state.attendees:
            await self._send_message(
                writer,
                {
                    "type": "attendees_update",
                    "attendees": [a.to_dict() for a in self._state.attendees],
                    "current_index": self._state.current_index,
                },
            )

    async def _client_read_loop(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Read client messages, sending a keepalive after 30s of silence."""
        while self._io.running:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=30.0)  # Keepalive timeout
            except asyncio.TimeoutError:
                if not await self._send_keepalive(writer):
                    break
                continue
            except _IO_ERRORS as e:
                logger.debug("Client read error: %s", e)
                break

            if not line:
                break  # Client disconnected
            await self._handle_message(writer, line.decode().strip())

    async def _send_keepalive(self, writer: asyncio.StreamWriter) -> bool:
        """Send a keepalive; returns False if the client is gone."""
        try:
            await self._send_message(writer, {"type": "keepalive"})
        except _IO_ERRORS:
            return False
        return True

    async def _handle_message(self, writer: asyncio.StreamWriter, message: str) -> None:
        """Handle a message from a client."""
        if not message:
            return

        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "get_state":
                # Send full state
                await self._send_message(writer, {"type": "full_state", "state": self._state.to_dict()})
            elif msg_type == "set_current_index":
                await self._set_current_index(data.get("index", 0))
            elif msg_type == "ping":
                await self._send_message(writer, {"type": "pong"})

        except json.JSONDecodeError:
            logger.debug("Invalid JSON from client: %s", message[:100])
        except _MESSAGE_ERRORS as e:
            logger.debug("Error handling message: %s", e)

    async def _set_current_index(self, index: int) -> None:
        """Update the current attendee index and tell all clients."""
        async with self._lock:
            if 0 <= index < len(self._state.attendees):
                self._state.current_index = index
                await self._broadcast({"type": "index_changed", "index": index})

    async def _send_message(self, writer: asyncio.StreamWriter, data: dict) -> None:
        """Send a JSON message to a client."""
        try:
            message = json.dumps(data) + "\n"
            writer.write(message.encode())
            await writer.drain()
        except _SEND_ERRORS as e:
            logger.debug("Failed to send message: %s", e)

    async def _broadcast(self, data: dict) -> None:
        """Broadcast a message to all connected clients."""
        message = json.dumps(data) + "\n"
        encoded = message.encode()

        disconnected = []
        for writer in self._io.clients:
            try:
                writer.write(encoded)
                await writer.drain()
            except _IO_ERRORS:
                disconnected.append(writer)

        # Remove disconnected clients
        for writer in disconnected:
            if writer in self._io.clients:
                self._io.clients.remove(writer)

    def _spawn(self, coro: Awaitable[None]) -> None:
        """Run ``coro`` in the background, keeping a reference until it finishes."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ==================== Public API for Meet Bot ====================

    async def set_meeting_status(
        self,
        status: str,
        title: str = "",
        video_device: str | None = None,
        audio_source: str | None = None,
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
            new_attendees = [
                EnrichedAttendee(name=p.get("name", "Unknown"), email=p.get("email")) for p in participants
            ]

            # Preserve enrichment data for existing attendees
            _carry_enrichment(new_attendees, self._state.attendees)

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
            self._spawn(self._enrich_attendees())

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
                await self._broadcast({"type": "attendee_enriched", "index": i, "data": enriched.to_dict()})

            except _CALLBACK_ERRORS as e:
                logger.debug("Failed to enrich %s: %s", attendee.name, e)

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

        self._poll.callback = poll_callback
        self._poll.interval = interval
        self._poll.duration = duration
        self._poll.start_time = time.time()

        self._poll.task = asyncio.create_task(self._polling_loop())
        logger.info("Started periodic attendee polling: every %ss for %ss", interval, duration)

    async def stop_periodic_polling(self) -> None:
        """Stop periodic polling if running."""
        if self._poll.task:
            await _cancel_and_wait(self._poll.task)
            self._poll.task = None
            logger.info("Stopped periodic attendee polling")

    async def _polling_loop(self) -> None:
        """Internal polling loop; cancellation (from stop_periodic_polling) propagates."""
        try:
            while self._io.running:
                # Check if we've exceeded the duration
                elapsed = time.time() - self._poll.start_time
                if elapsed >= self._poll.duration:
                    logger.info("Periodic polling completed after %.0fs", elapsed)
                    break

                # Wait for the interval
                await asyncio.sleep(self._poll.interval)

                # Check again after sleep
                if not self._io.running:
                    break

                await self._poll_once()
        finally:
            self._poll.task = None

    async def _poll_once(self) -> None:
        """Fetch participants via the poll callback and apply them."""
        if not self._poll.callback:
            return
        try:
            participants = await self._poll.callback()
            if participants:
                # Check for new participants
                existing_names = {a.name for a in self._state.attendees}
                new_count = sum(1 for p in participants if p.get("name") not in existing_names)

                if new_count > 0:
                    logger.info("Polling detected %s new participant(s)", new_count)

                # Update participants (will broadcast changes)
                await self.update_participants(participants)

        except _CALLBACK_ERRORS as e:
            logger.warning("Polling callback error: %s", e)

    def is_polling(self) -> bool:
        """Check if periodic polling is active."""
        return self._poll.task is not None and not self._poll.task.done()

    def get_polling_status(self) -> dict:
        """Get current polling status."""
        if not self.is_polling():
            return {
                "active": False,
                "elapsed": 0,
                "remaining": 0,
            }

        elapsed = time.time() - self._poll.start_time
        remaining = max(0, self._poll.duration - elapsed)
        return {
            "active": True,
            "elapsed": elapsed,
            "remaining": remaining,
            "interval": self._poll.interval,
            "duration": self._poll.duration,
        }

    def get_state(self) -> MeetingState:
        """Get current meeting state (for local access)."""
        return self._state

    def set_state_change_callback(self, callback: Callable[[MeetingState], None]) -> None:
        """Set callback for state changes."""
        self._on_state_change = callback


@dataclass
class _ClientCallbacks:
    """Callbacks registered by the client's user."""

    attendees_update: Callable[[list[EnrichedAttendee]], None] | None = None
    status_change: Callable[[str], None] | None = None
    attendee_enriched: Callable[[int, EnrichedAttendee], None] | None = None


class AttendeeDataClient:
    """
    Client for connecting to the AttendeeDataService.

    Used by the Video Generator to receive attendee updates.
    """

    def __init__(self):
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._state = MeetingState()
        self._lock = asyncio.Lock()
        self._receive_task: asyncio.Task | None = None
        self._callbacks = _ClientCallbacks()

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
        except FileNotFoundError:
            logger.debug("Socket not found: %s", SOCKET_PATH)
            return False
        except asyncio.TimeoutError:
            logger.debug("Connection timeout")
            return False
        except _IO_ERRORS as e:
            logger.debug("Connection failed: %s", e)
            return False

        self._connected = True

        # Start receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())

        logger.info("Connected to AttendeeDataService at %s", SOCKET_PATH)
        return True

    async def disconnect(self) -> None:
        """Disconnect from the service."""
        self._connected = False

        if self._receive_task:
            await _cancel_and_wait(self._receive_task)
            self._receive_task = None

        if self._writer:
            await _close_writer(self._writer)
            self._writer = None
            self._reader = None

        logger.info("Disconnected from AttendeeDataService")

    async def _receive_loop(self) -> None:
        """Receive and process messages from the server; cancellation propagates."""
        try:
            while self._connected and self._reader:
                try:
                    line = await self._reader.readline()
                except _IO_ERRORS as e:
                    logger.debug("Receive error: %s", e)
                    break
                if not line:
                    break

                await self._handle_message(line.decode().strip())
        finally:
            self._connected = False

    async def _handle_message(self, message: str) -> None:
        """Handle a message from the server."""
        if not message:
            return

        try:
            data = json.loads(message)
            handler = self._MESSAGE_HANDLERS.get(data.get("type"))
            if handler is not None:
                await handler(self, data)
        except json.JSONDecodeError:
            logger.debug("Invalid JSON from server: %s", message[:100])
        except _MESSAGE_ERRORS as e:
            logger.debug("Error handling server message: %s", e)

    async def _on_attendees_update_msg(self, data: dict) -> None:
        """Replace the attendee list."""
        attendees = [EnrichedAttendee(**a) for a in data.get("attendees", [])]
        async with self._lock:
            self._state.attendees = attendees
            self._state.current_index = data.get("current_index", 0)
            if "status" in data:
                self._state.status = data["status"]

        if self._callbacks.attendees_update:
            self._callbacks.attendees_update(attendees)

    async def _on_meeting_status_msg(self, data: dict) -> None:
        """Update meeting status, title and devices."""
        status = data.get("status", "scanning")
        async with self._lock:
            self._state.status = status
            if "title" in data:
                self._state.meeting_title = data["title"]
            if data.get("video_device"):
                self._state.video_device = data["video_device"]
            if data.get("audio_source"):
                self._state.audio_source = data["audio_source"]

        if self._callbacks.status_change:
            self._callbacks.status_change(status)

    async def _on_attendee_enriched_msg(self, data: dict) -> None:
        """Replace one attendee with its enriched version."""
        index = data.get("index", 0)
        attendee = EnrichedAttendee(**data.get("data", {}))

        async with self._lock:
            if 0 <= index < len(self._state.attendees):
                self._state.attendees[index] = attendee

        if self._callbacks.attendee_enriched:
            self._callbacks.attendee_enriched(index, attendee)

    async def _on_full_state_msg(self, data: dict) -> None:
        """Replace the whole local state."""
        state_data = data.get("state", {})
        async with self._lock:
            self._state.status = state_data.get("status", "scanning")
            self._state.current_index = state_data.get("current_index", 0)
            self._state.meeting_title = state_data.get("meeting_title", "")
            self._state.attendees = [EnrichedAttendee(**a) for a in state_data.get("attendees", [])]
            self._state.video_device = state_data.get("video_device")
            self._state.audio_source = state_data.get("audio_source")

    # keepalive/pong and unknown types are ignored
    _MESSAGE_HANDLERS: ClassVar[dict[str, Callable[["AttendeeDataClient", dict], Awaitable[None]]]] = {
        "attendees_update": _on_attendees_update_msg,
        "meeting_status": _on_meeting_status_msg,
        "attendee_enriched": _on_attendee_enriched_msg,
        "full_state": _on_full_state_msg,
    }

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
        except _SEND_ERRORS as e:
            logger.debug("Send failed: %s", e)

    def get_state(self) -> MeetingState:
        """Get current state (local copy)."""
        return self._state

    def get_attendees(self) -> list[EnrichedAttendee]:
        """Get current attendee list."""
        return self._state.attendees

    def get_current_attendee(self) -> EnrichedAttendee | None:
        """Get the currently displayed attendee."""
        if self._state.attendees and 0 <= self._state.current_index < len(self._state.attendees):
            return self._state.attendees[self._state.current_index]
        return None

    def get_video_device(self) -> str | None:
        """Get the video device path from the meetbot."""
        return self._state.video_device

    def get_audio_source(self) -> str | None:
        """Get the audio source name from the meetbot."""
        return self._state.audio_source

    def is_connected(self) -> bool:
        """Check if connected to service."""
        return self._connected

    # Callback setters
    def on_attendees_update(self, callback: Callable[[list[EnrichedAttendee]], None]) -> None:
        """Set callback for attendee list updates."""
        self._callbacks.attendees_update = callback

    def on_status_change(self, callback: Callable[[str], None]) -> None:
        """Set callback for meeting status changes."""
        self._callbacks.status_change = callback

    def on_attendee_enriched(self, callback: Callable[[int, EnrichedAttendee], None]) -> None:
        """Set callback for individual attendee enrichment."""
        self._callbacks.attendee_enriched = callback


# Global service instance (created on first use)
_SERVICE: dict[str, AttendeeDataService] = {}


async def get_service() -> AttendeeDataService:
    """Get or create the global AttendeeDataService instance."""
    if "service" not in _SERVICE:
        _SERVICE["service"] = AttendeeDataService()
    return _SERVICE["service"]


async def start_service() -> AttendeeDataService:
    """Start the global AttendeeDataService."""
    service = await get_service()
    await service.start()
    return service
