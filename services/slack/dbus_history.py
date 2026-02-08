"""
Message history tracking for Slack D-Bus daemon.

Extracted from dbus.py to reduce class size. Contains:
- MessageRecord: Dataclass for processed message records
- MessageHistory: In-memory message history with filtering and approval tracking
"""

import json
import time
from dataclasses import asdict, dataclass


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

    def __init__(self, max_size: int = 1000, max_pending: int = 100):
        self.max_size = max_size
        self.max_pending = max_pending  # Prevent unbounded memory growth
        self.messages: list[MessageRecord] = []
        self.pending_approvals: dict[str, MessageRecord] = {}

    def add(self, record: MessageRecord):
        """Add a message record."""
        self.messages.append(record)
        if len(self.messages) > self.max_size:
            self.messages.pop(0)

        if record.status == "pending":
            # Enforce max pending limit - remove oldest pending if over limit
            if len(self.pending_approvals) >= self.max_pending:
                oldest_id = next(iter(self.pending_approvals))
                self.pending_approvals.pop(oldest_id, None)
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
            by_classification[m.classification] = (
                by_classification.get(m.classification, 0) + 1
            )
            by_intent[m.intent] = by_intent.get(m.intent, 0) + 1

        return {
            "total": total,
            "pending_approvals": len(self.pending_approvals),
            "by_status": by_status,
            "by_classification": by_classification,
            "by_intent": by_intent,
        }
