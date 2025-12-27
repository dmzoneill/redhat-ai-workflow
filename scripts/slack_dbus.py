#!/usr/bin/env python3
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
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Check for dbus availability
try:
    from dbus_next import DBusError, Variant
    from dbus_next.aio import MessageBus
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

    class SlackAgentDBusInterface(ServiceInterface):
        """D-Bus interface for the Slack Agent daemon."""

        def __init__(self, daemon: "SlackDaemonWithDBus"):
            super().__init__(DBUS_INTERFACE_NAME)
            self.daemon = daemon

        # ==================== Properties ====================

        @dbus_property()
        def Running(self) -> "b":
            """Whether the daemon is running."""
            return self.daemon.is_running

        @dbus_property()
        def PendingCount(self) -> "i":
            """Number of messages pending approval."""
            return len(self.daemon.history.pending_approvals)

        @dbus_property()
        def Stats(self) -> "s":
            """JSON stats about the daemon."""
            stats = {
                "running": self.daemon.is_running,
                "uptime": time.time() - self.daemon.start_time if self.daemon.start_time else 0,
                "messages_processed": self.daemon.messages_processed,
                "messages_responded": self.daemon.messages_responded,
                "pending_approvals": len(self.daemon.history.pending_approvals),
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
            loop = asyncio.get_event_loop()
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
            loop = asyncio.get_event_loop()
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
            """Send a message to Slack."""
            loop = asyncio.get_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.daemon.send_direct_message(channel_id, text, thread_ts), loop
            )
            result = future.result(timeout=30)
            return json.dumps(result)

        @method()
        def ReloadConfig(self) -> "s":
            """Reload configuration from config.json."""
            self.daemon.reload_config()
            return json.dumps({"success": True, "message": "Config reloaded"})

        @method()
        def Shutdown(self) -> "s":
            """Gracefully shutdown the daemon."""
            asyncio.get_event_loop().call_soon(self.daemon.request_shutdown)
            return json.dumps({"success": True, "message": "Shutdown initiated"})

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
    """

    def __init__(self):
        self.is_running = False
        self.start_time: float | None = None
        self.messages_processed = 0
        self.messages_responded = 0
        self.history = MessageHistory()

        self._bus: MessageBus | None = None
        self._dbus_interface: SlackAgentDBusInterface | None = None
        self._shutdown_requested = False

        # Will be set when daemon starts
        self.session = None
        self.state_db = None
        self.listener = None
        self.user_classifier = None
        self.channel_permissions = None
        self.response_generator = None

    async def start_dbus(self):
        """Start the D-Bus service."""
        if not DBUS_AVAILABLE:
            logger.warning("D-Bus not available, IPC disabled")
            return

        try:
            self._bus = await MessageBus().connect()
            self._dbus_interface = SlackAgentDBusInterface(self)

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
                    thread_ts=None,  # TODO: store thread_ts in record
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
