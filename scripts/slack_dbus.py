#!/usr/bin/env python3
# flake8: noqa: F821
# Note: F821 disabled because D-Bus type annotations like "s", "i", "b"
# are valid dbus-next signatures but flake8 misinterprets them as undefined names.
"""
D-Bus Interface for Slack Daemon

Provides IPC communication with the Slack daemon via D-Bus:
- Start/stop/status control
- Send messages
- Approve/reject queued messages
- Query message history
- Real-time notifications

D-Bus Service: com.aiworkflow.SlackAgent
D-Bus Path: /com/aiworkflow/SlackAgent
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# Check for dbus availability
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import PropertyAccess
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.service import signal as dbus_signal

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    print("Warning: dbus-next not installed. Install with: pip install dbus-next")

PROJECT_ROOT = Path(__file__).parent.parent

logger = logging.getLogger(__name__)

# D-Bus configuration
DBUS_SERVICE_NAME = "com.aiworkflow.SlackAgent"
DBUS_OBJECT_PATH = "/com/aiworkflow/SlackAgent"
DBUS_INTERFACE_NAME = "com.aiworkflow.SlackAgent"


@dataclass
class MessageRecord:
    """Record of a processed message."""

    id: str
    timestamp: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str
    intent: str
    classification: str
    response: str
    status: str  # pending, approved, rejected, sent, skipped
    created_at: float
    processed_at: float | None = None
    thread_ts: str | None = None  # Thread timestamp for replies

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class MessageHistory:
    """Stores message history for querying."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.messages: list[MessageRecord] = []
        self.pending_approvals: dict[str, MessageRecord] = {}

    def add(self, record: MessageRecord):
        """Add a message record."""
        self.messages.append(record)
        if len(self.messages) > self.max_size:
            self.messages.pop(0)

        if record.status == "pending":
            self.pending_approvals[record.id] = record

    def get_pending(self) -> list[MessageRecord]:
        """Get messages pending approval."""
        return list(self.pending_approvals.values())

    def approve(self, message_id: str) -> MessageRecord | None:
        """Approve a pending message."""
        if message_id in self.pending_approvals:
            record = self.pending_approvals.pop(message_id)
            record.status = "approved"
            record.processed_at = time.time()
            return record
        return None

    def reject(self, message_id: str) -> MessageRecord | None:
        """Reject a pending message."""
        if message_id in self.pending_approvals:
            record = self.pending_approvals.pop(message_id)
            record.status = "rejected"
            record.processed_at = time.time()
            return record
        return None

    def get_history(
        self,
        limit: int = 50,
        channel_id: str = "",
        user_id: str = "",
        status: str = "",
    ) -> list[MessageRecord]:
        """Get message history with optional filters."""
        result = self.messages.copy()

        if channel_id:
            result = [m for m in result if m.channel_id == channel_id]
        if user_id:
            result = [m for m in result if m.user_id == user_id]
        if status:
            result = [m for m in result if m.status == status]

        return result[-limit:]

    def get_stats(self) -> dict:
        """Get message statistics."""
        total = len(self.messages)
        by_status = {}
        by_classification = {}
        by_intent = {}

        for m in self.messages:
            by_status[m.status] = by_status.get(m.status, 0) + 1
            by_classification[m.classification] = by_classification.get(m.classification, 0) + 1
            by_intent[m.intent] = by_intent.get(m.intent, 0) + 1

        return {
            "total": total,
            "pending_approvals": len(self.pending_approvals),
            "by_status": by_status,
            "by_classification": by_classification,
            "by_intent": by_intent,
        }


if DBUS_AVAILABLE:

    class SlackPersonaDBusInterface(ServiceInterface):
        """D-Bus interface for the Slack Persona daemon."""

        def __init__(self, daemon: "SlackDaemonWithDBus"):
            super().__init__(DBUS_INTERFACE_NAME)
            self.daemon = daemon

        # ==================== Properties ====================

        @dbus_property(access=PropertyAccess.READ)
        def Running(self) -> "b":
            """Whether the daemon is running."""
            return self.daemon.is_running

        @dbus_property(access=PropertyAccess.READ)
        def PendingCount(self) -> "i":
            """Number of messages pending approval."""
            return len(self.daemon.history.pending_approvals)

        @dbus_property(access=PropertyAccess.READ)
        def Stats(self) -> "s":
            """JSON stats about the daemon."""
            # Get listener stats if available (includes polls, errors, etc.)
            listener_stats = {}
            if hasattr(self.daemon, "listener") and self.daemon.listener:
                listener_stats = getattr(self.daemon.listener, "stats", {})

            stats = {
                "running": self.daemon.is_running,
                "uptime": (time.time() - self.daemon.start_time if self.daemon.start_time else 0),
                "messages_processed": self.daemon.messages_processed,
                "messages_responded": self.daemon.messages_responded,
                "pending_approvals": len(self.daemon.history.pending_approvals),
                # Add listener stats for VSCode extension
                "polls": listener_stats.get("polls", 0),
                "errors": listener_stats.get("errors", 0),
                "consecutive_errors": listener_stats.get("consecutive_errors", 0),
                "messages_seen": listener_stats.get("messages_seen", 0),
            }
            return json.dumps(stats)

        # ==================== Methods ====================

        @method()
        def GetStatus(self) -> "s":
            """Get daemon status as JSON."""
            return self.Stats

        @method()
        def GetPending(self) -> "s":
            """Get pending approval messages as JSON array."""
            pending = self.daemon.history.get_pending()
            return json.dumps([m.to_dict() for m in pending])

        @method()
        def ApproveMessage(self, message_id: "s") -> "s":
            """Approve a pending message and send it."""
            loop = self.daemon._event_loop
            future = asyncio.run_coroutine_threadsafe(self.daemon.approve_message(message_id), loop)
            result = future.result(timeout=30)
            return json.dumps(result)

        @method()
        def RejectMessage(self, message_id: "s") -> "s":
            """Reject a pending message."""
            record = self.daemon.history.reject(message_id)
            if record:
                return json.dumps({"success": True, "message_id": message_id})
            return json.dumps({"success": False, "error": "Message not found"})

        @method()
        def ApproveAll(self) -> "s":
            """Approve all pending messages."""
            loop = self.daemon._event_loop
            future = asyncio.run_coroutine_threadsafe(self.daemon.approve_all_pending(), loop)
            result = future.result(timeout=60)
            return json.dumps(result)

        @method()
        def GetHistory(self, limit: "i", channel_id: "s", user_id: "s", status: "s") -> "s":
            """Get message history with optional filters."""
            history = self.daemon.history.get_history(
                limit=limit,
                channel_id=channel_id,
                user_id=user_id,
                status=status,
            )
            return json.dumps([m.to_dict() for m in history])

        @method()
        def SendMessage(self, channel_id: "s", text: "s", thread_ts: "s") -> "s":
            """Send a message to Slack.

            Note: This method schedules the send and returns immediately.
            The actual send happens asynchronously.
            """
            # Schedule the coroutine on the event loop (non-blocking)
            loop = self.daemon._event_loop
            if not loop or not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available"})

            # Create a task to run the send (fire-and-forget for now)
            # We return success immediately since we can't block here
            async def do_send():
                try:
                    result = await self.daemon.session.send_message(
                        channel_id=channel_id,
                        text=text,
                        thread_ts=thread_ts if thread_ts else None,
                        typing_delay=True,
                    )
                    logger.info(f"D-Bus SendMessage completed: ts={result.get('ts', 'unknown')}")
                    return result
                except Exception as e:
                    logger.error(f"D-Bus SendMessage failed: {e}")
                    return {"success": False, "error": str(e)}

            # Schedule the task
            asyncio.run_coroutine_threadsafe(do_send(), loop)

            # Return immediately - the message will be sent asynchronously
            return json.dumps({"success": True, "message": "Message send scheduled", "async": True})

        @method()
        def ReloadConfig(self) -> "s":
            """Reload configuration from config.json."""
            self.daemon.reload_config()
            return json.dumps({"success": True, "message": "Config reloaded"})

        @method()
        def Shutdown(self) -> "s":
            """Gracefully shutdown the daemon."""
            self.daemon._event_loop.call_soon(self.daemon.request_shutdown)
            return json.dumps({"success": True, "message": "Shutdown initiated"})

        @method()
        def HealthCheck(self) -> "s":
            """Perform a comprehensive health check."""
            try:
                # Use synchronous health check to avoid event loop issues
                result = self.daemon.health_check_sync()
                return json.dumps(result)
            except Exception as e:
                return json.dumps(
                    {
                        "healthy": False,
                        "checks": {"health_check_execution": False},
                        "message": f"Health check failed: {e}",
                        "timestamp": time.time(),
                    }
                )

        # ==================== Knowledge Cache Methods ====================

        @method()
        def FindChannel(self, query: "s") -> "s":
            """
            Find channels by name, purpose, or topic.

            Args:
                query: Search string to match against channel name/purpose/topic

            Returns:
                JSON array of matching channels with id, name, purpose, etc.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "channels": []})

            async def do_find():
                try:
                    channels = await self.daemon.state_db.find_channels(query=query, limit=50)
                    return {
                        "success": True,
                        "query": query,
                        "count": len(channels),
                        "channels": [c.to_dict() for c in channels],
                    }
                except Exception as e:
                    logger.error(f"FindChannel error: {e}")
                    return {"success": False, "error": str(e), "channels": []}

            future = asyncio.run_coroutine_threadsafe(do_find(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def FindUser(self, query: "s") -> "s":
            """
            Find users by name, email, or GitLab username.

            Args:
                query: Search string to match against user fields

            Returns:
                JSON array of matching users with id, name, email, etc.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "users": []})

            async def do_find():
                try:
                    users = await self.daemon.state_db.find_users(query=query, limit=50)
                    return {
                        "success": True,
                        "query": query,
                        "count": len(users),
                        "users": users,
                    }
                except Exception as e:
                    logger.error(f"FindUser error: {e}")
                    return {"success": False, "error": str(e), "users": []}

            future = asyncio.run_coroutine_threadsafe(do_find(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def GetMyChannels(self) -> "s":
            """
            Get channels the bot is a member of.

            Returns:
                JSON array of channels with id, name, purpose, etc.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "channels": []})

            async def do_get():
                try:
                    channels = await self.daemon.state_db.get_my_channels(limit=100)
                    return {
                        "success": True,
                        "count": len(channels),
                        "channels": [c.to_dict() for c in channels],
                    }
                except Exception as e:
                    logger.error(f"GetMyChannels error: {e}")
                    return {"success": False, "error": str(e), "channels": []}

            future = asyncio.run_coroutine_threadsafe(do_get(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def GetUserGroups(self) -> "s":
            """
            Get all cached user groups (for @team mentions).

            Returns:
                JSON array of groups with id, handle, name, members.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "groups": []})

            async def do_get():
                try:
                    groups = await self.daemon.state_db.get_all_groups()
                    return {
                        "success": True,
                        "count": len(groups),
                        "groups": [g.to_dict() for g in groups],
                    }
                except Exception as e:
                    logger.error(f"GetUserGroups error: {e}")
                    return {"success": False, "error": str(e), "groups": []}

            future = asyncio.run_coroutine_threadsafe(do_get(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def ResolveTarget(self, target: "s") -> "s":
            """
            Resolve a Slack target to its ID.

            Args:
                target: Can be #channel, @user, @group, or raw ID

            Returns:
                JSON with type, id, name, and found status.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "State DB not available",
                        "type": "unknown",
                        "id": None,
                        "name": target,
                        "found": False,
                    }
                )

            async def do_resolve():
                try:
                    result = await self.daemon.state_db.resolve_target(target)
                    result["success"] = True
                    return result
                except Exception as e:
                    logger.error(f"ResolveTarget error: {e}")
                    return {
                        "success": False,
                        "error": str(e),
                        "type": "unknown",
                        "id": None,
                        "name": target,
                        "found": False,
                    }

            future = asyncio.run_coroutine_threadsafe(do_resolve(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def GetChannelCacheStats(self) -> "s":
            """
            Get statistics about the knowledge cache.

            Returns:
                JSON with cache stats (total channels, member channels, age, etc.)
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            async def do_get():
                try:
                    stats = await self.daemon.state_db.get_channel_cache_stats()
                    stats["success"] = True
                    return stats
                except Exception as e:
                    logger.error(f"GetChannelCacheStats error: {e}")
                    return {"success": False, "error": str(e)}

            future = asyncio.run_coroutine_threadsafe(do_get(), loop)
            result = future.result(timeout=10)
            return json.dumps(result)

        @method()
        def RefreshChannelCache(self) -> "s":
            """
            Trigger a refresh of the channel cache from Slack API.

            Returns:
                JSON with refresh status and count of channels cached.
            """
            loop = self.daemon._event_loop
            if not loop or not self.daemon.session or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "Session or State DB not available"})

            async def do_refresh():
                try:
                    # Import here to avoid circular imports
                    from tool_modules.aa_slack.src.persistence import CachedChannel

                    # Fetch channels from Slack API
                    channels_data = await self.daemon.session.get_conversations_list(
                        types="public_channel,private_channel",
                        limit=1000,
                    )

                    # Convert to CachedChannel objects
                    channels = [
                        CachedChannel(
                            channel_id=c.get("id", ""),
                            name=c.get("name", ""),
                            display_name=c.get("name_normalized", c.get("name", "")),
                            is_private=c.get("is_private", False),
                            is_member=c.get("is_member", False),
                            purpose=c.get("purpose", {}).get("value", ""),
                            topic=c.get("topic", {}).get("value", ""),
                            num_members=c.get("num_members", 0),
                        )
                        for c in channels_data
                        if c.get("id")
                    ]

                    # Bulk cache
                    await self.daemon.state_db.cache_channels_bulk(channels)

                    return {
                        "success": True,
                        "message": "Channel cache refreshed",
                        "channels_cached": len(channels),
                    }
                except Exception as e:
                    logger.error(f"RefreshChannelCache error: {e}")
                    return {"success": False, "error": str(e)}

            future = asyncio.run_coroutine_threadsafe(do_refresh(), loop)
            result = future.result(timeout=60)
            return json.dumps(result)

        # ==================== Signals ====================

        @dbus_signal()
        def MessageReceived(self, message_json: "s") -> None:
            """Emitted when a new message is received."""
            pass

        @dbus_signal()
        def MessageProcessed(self, message_id: "s", status: "s") -> None:
            """Emitted when a message is processed."""
            pass

        @dbus_signal()
        def PendingApproval(self, message_json: "s") -> None:
            """Emitted when a message needs approval."""
            pass


class SlackDaemonWithDBus:
    """
    Extended Slack daemon with D-Bus IPC support.

    Inherits behavior from the base daemon but adds:
    - D-Bus interface for external control
    - Message history tracking
    - Approval queue management
    - Health checking
    """

    def __init__(self):
        self.is_running = False
        self.start_time: float | None = None
        self.messages_processed = 0
        self.messages_responded = 0
        self.history = MessageHistory()

        self._bus: MessageBus | None = None
        self._dbus_interface: SlackPersonaDBusInterface | None = None
        self._shutdown_requested = False

        # Health tracking
        self._last_successful_poll: float = 0
        self._last_successful_api_call: float = 0
        self._consecutive_api_failures: int = 0
        self._last_health_check: float = 0

        # Will be set when daemon starts
        self.session = None
        self.state_db = None
        self.listener = None
        self.user_classifier = None
        self.channel_permissions = None
        self.response_generator = None
        self._event_loop = None  # Set when D-Bus starts

    async def start_dbus(self):
        """Start the D-Bus service."""
        if not DBUS_AVAILABLE:
            logger.warning("D-Bus not available, IPC disabled")
            return

        try:
            # Store the running event loop for D-Bus method handlers
            self._event_loop = asyncio.get_running_loop()

            self._bus = await MessageBus().connect()
            self._dbus_interface = SlackPersonaDBusInterface(self)

            self._bus.export(DBUS_OBJECT_PATH, self._dbus_interface)
            await self._bus.request_name(DBUS_SERVICE_NAME)

            logger.info(f"D-Bus service started: {DBUS_SERVICE_NAME}")
        except Exception as e:
            logger.error(f"Failed to start D-Bus: {e}")

    async def stop_dbus(self):
        """Stop the D-Bus service."""
        if self._bus:
            self._bus.disconnect()
            self._bus = None

    def emit_message_received(self, record: MessageRecord):
        """Emit D-Bus signal for new message."""
        if self._dbus_interface:
            self._dbus_interface.MessageReceived(record.to_json())

    def emit_message_processed(self, message_id: str, status: str):
        """Emit D-Bus signal for processed message."""
        if self._dbus_interface:
            self._dbus_interface.MessageProcessed(message_id, status)

    def emit_pending_approval(self, record: MessageRecord):
        """Emit D-Bus signal for pending approval."""
        if self._dbus_interface:
            self._dbus_interface.PendingApproval(record.to_json())

    async def approve_message(self, message_id: str) -> dict:
        """Approve and send a pending message."""
        record = self.history.approve(message_id)
        if not record:
            return {"success": False, "error": "Message not found"}

        # Send the response
        try:
            if self.session:
                await self.session.send_message(
                    channel_id=record.channel_id,
                    text=record.response,
                    thread_ts=record.thread_ts,
                    typing_delay=True,
                )
                self.messages_responded += 1
                self.emit_message_processed(message_id, "sent")
                return {"success": True, "message_id": message_id, "status": "sent"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {"success": False, "error": "Session not available"}

    async def approve_all_pending(self) -> dict:
        """Approve all pending messages."""
        pending = list(self.history.pending_approvals.keys())
        results = []

        for msg_id in pending:
            result = await self.approve_message(msg_id)
            results.append(result)

        return {
            "total": len(pending),
            "approved": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        }

    async def send_direct_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: str = "",
    ) -> dict:
        """Send a message directly (bypassing intent detection)."""
        if not self.session:
            return {"success": False, "error": "Session not available"}

        try:
            result = await self.session.send_message(
                channel_id=channel_id,
                text=text,
                thread_ts=thread_ts if thread_ts else None,
                typing_delay=True,
            )
            return {"success": True, "ts": result.get("ts", "")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reload_config(self):
        """Reload configuration from config.json."""
        if self.user_classifier:
            self.user_classifier.reload()
        if self.channel_permissions:
            self.channel_permissions.reload()

    def request_shutdown(self):
        """Request graceful shutdown."""
        self._shutdown_requested = True

    def record_successful_poll(self):
        """Record a successful poll (for health tracking)."""
        self._last_successful_poll = time.time()
        self._consecutive_api_failures = 0

    def record_successful_api_call(self):
        """Record a successful API call (for health tracking)."""
        self._last_successful_api_call = time.time()
        self._consecutive_api_failures = 0

    def record_api_failure(self):
        """Record an API failure (for health tracking)."""
        self._consecutive_api_failures += 1

    def health_check_sync(self) -> dict:
        """
        Perform a synchronous health check on the Slack daemon.

        This is a lightweight check that doesn't make API calls.
        For API reachability, rely on the listener's polling stats.

        Checks:
        - Service is running
        - Listener is active and polling
        - No excessive consecutive failures
        """
        self._last_health_check = time.time()
        now = time.time()

        # Core checks (required for health)
        checks = {
            "running": self.is_running,
            "session_valid": self.session is not None,
            "listener_active": self.listener is not None,
        }

        # Check if polling is happening (should poll at least every 60s)
        if self._last_successful_poll > 0:
            poll_age = now - self._last_successful_poll
            checks["polling_recent"] = poll_age < 120  # Last poll within 2 minutes
        else:
            # If we just started, don't fail this check
            if self.start_time and (now - self.start_time) < 60:
                checks["polling_recent"] = True  # Grace period
            else:
                checks["polling_recent"] = False

        # Check consecutive failures
        checks["no_excessive_failures"] = self._consecutive_api_failures < 10

        # Check uptime (at least 10 seconds)
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 10
        else:
            checks["uptime_ok"] = False

        # Get listener stats for additional info
        listener_stats = {}
        if self.listener:
            listener_stats = getattr(self.listener, "stats", {})

        # Overall health based on core checks only
        healthy = all(checks.values())

        # Build message
        if healthy:
            message = "Slack daemon is healthy"
        else:
            failed = [k for k, v in checks.items() if not v]
            message = f"Unhealthy: {', '.join(failed)}"

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": self._last_health_check,
            "consecutive_failures": self._consecutive_api_failures,
            "last_successful_poll": self._last_successful_poll,
            "last_successful_api_call": self._last_successful_api_call,
            "polls": listener_stats.get("polls", 0),
            "errors": listener_stats.get("errors", 0),
        }

    async def health_check(self) -> dict:
        """Async wrapper for health_check_sync (for compatibility)."""
        return self.health_check_sync()


# =============================================================================
# D-Bus CLIENT
# =============================================================================


class SlackAgentClient:
    """Client for communicating with the Slack daemon via D-Bus."""

    def __init__(self):
        self._bus: MessageBus | None = None
        self._proxy = None

    async def connect(self) -> bool:
        """Connect to the D-Bus service."""
        if not DBUS_AVAILABLE:
            print("Error: dbus-next not installed")
            return False

        try:
            self._bus = await MessageBus().connect()
            introspection = await self._bus.introspect(DBUS_SERVICE_NAME, DBUS_OBJECT_PATH)
            self._proxy = self._bus.get_proxy_object(
                DBUS_SERVICE_NAME,
                DBUS_OBJECT_PATH,
                introspection,
            )
            return True
        except Exception as e:
            print(f"Failed to connect to Slack daemon: {e}")
            print("Is the daemon running? Start with: make slack-daemon-bg")
            return False

    async def disconnect(self):
        """Disconnect from D-Bus."""
        if self._bus:
            self._bus.disconnect()

    def _get_interface(self):
        """Get the D-Bus interface."""
        if not self._proxy:
            raise RuntimeError("Not connected")
        return self._proxy.get_interface(DBUS_INTERFACE_NAME)

    async def get_status(self) -> dict:
        """Get daemon status."""
        interface = self._get_interface()
        result = await interface.call_get_status()
        return json.loads(result)

    async def get_pending(self) -> list:
        """Get pending approval messages."""
        interface = self._get_interface()
        result = await interface.call_get_pending()
        return json.loads(result)

    async def approve(self, message_id: str) -> dict:
        """Approve a pending message."""
        interface = self._get_interface()
        result = await interface.call_approve_message(message_id)
        return json.loads(result)

    async def reject(self, message_id: str) -> dict:
        """Reject a pending message."""
        interface = self._get_interface()
        result = await interface.call_reject_message(message_id)
        return json.loads(result)

    async def approve_all(self) -> dict:
        """Approve all pending messages."""
        interface = self._get_interface()
        result = await interface.call_approve_all()
        return json.loads(result)

    async def get_history(
        self,
        limit: int = 50,
        channel_id: str = "",
        user_id: str = "",
        status: str = "",
    ) -> list:
        """Get message history."""
        interface = self._get_interface()
        result = await interface.call_get_history(limit, channel_id, user_id, status)
        return json.loads(result)

    async def send_message(self, channel_id: str, text: str, thread_ts: str = "") -> dict:
        """Send a message to Slack."""
        interface = self._get_interface()
        result = await interface.call_send_message(channel_id, text, thread_ts)
        return json.loads(result)

    async def reload_config(self) -> dict:
        """Reload daemon configuration."""
        interface = self._get_interface()
        result = await interface.call_reload_config()
        return json.loads(result)

    async def shutdown(self) -> dict:
        """Shutdown the daemon."""
        interface = self._get_interface()
        result = await interface.call_shutdown()
        return json.loads(result)

    async def health_check(self) -> dict:
        """Perform a comprehensive health check."""
        interface = self._get_interface()
        result = await interface.call_health_check()
        return json.loads(result)

    # ==================== Knowledge Cache Methods ====================

    async def find_channel(self, query: str) -> dict:
        """Find channels by name, purpose, or topic."""
        interface = self._get_interface()
        result = await interface.call_find_channel(query)
        return json.loads(result)

    async def find_user(self, query: str) -> dict:
        """Find users by name, email, or GitLab username."""
        interface = self._get_interface()
        result = await interface.call_find_user(query)
        return json.loads(result)

    async def get_my_channels(self) -> dict:
        """Get channels the bot is a member of."""
        interface = self._get_interface()
        result = await interface.call_get_my_channels()
        return json.loads(result)

    async def get_user_groups(self) -> dict:
        """Get all cached user groups."""
        interface = self._get_interface()
        result = await interface.call_get_user_groups()
        return json.loads(result)

    async def resolve_target(self, target: str) -> dict:
        """Resolve #channel, @user, or @group to ID."""
        interface = self._get_interface()
        result = await interface.call_resolve_target(target)
        return json.loads(result)

    async def get_channel_cache_stats(self) -> dict:
        """Get knowledge cache statistics."""
        interface = self._get_interface()
        result = await interface.call_get_channel_cache_stats()
        return json.loads(result)

    async def refresh_channel_cache(self) -> dict:
        """Trigger a refresh of the channel cache."""
        interface = self._get_interface()
        result = await interface.call_refresh_channel_cache()
        return json.loads(result)
