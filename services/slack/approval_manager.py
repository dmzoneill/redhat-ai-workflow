"""
Approval workflow manager for the Slack daemon.

Handles:
- Pending message tracking for concerned users
- Approve/reject logic
- Auto-approval rules
- Concerned user notifications
"""

import logging
import time
from typing import TYPE_CHECKING, Any

from scripts.common.config_loader import load_config

if TYPE_CHECKING:
    from services.slack.message_processor import UserClassification
    from services.slack.response_builder import DesktopNotifier

logger = logging.getLogger(__name__)


class ApprovalManager:
    """
    Manages the approval workflow for messages from concerned users.

    When a message is from a "concerned" user (e.g., managers), the response
    is queued for manual review before being sent. This class manages:
    - The pending reviews queue (with bounded size)
    - Recording pending messages in D-Bus history
    - Sending notifications about pending approvals
    - Notifying configured channels about concerned user messages
    """

    def __init__(
        self,
        notifier: "DesktopNotifier | None" = None,
        ui: Any = None,
        max_pending_reviews: int = 50,
    ):
        self.notifier = notifier
        self.ui = ui
        self._pending_reviews: list[dict] = []
        self._max_pending_reviews = max_pending_reviews
        self._slack_config = load_config().get("slack", {})

    @property
    def pending_reviews(self) -> list[dict]:
        """Access the pending reviews list."""
        return self._pending_reviews

    @property
    def pending_count(self) -> int:
        """Number of pending reviews."""
        return len(self._pending_reviews)

    async def handle_concerned_user_review(
        self,
        msg: Any,
        response: str,
        classification: "UserClassification",
        state_db: Any,
        session: Any,
        dbus_handler: Any = None,
    ):
        """
        Handle a message requiring concerned user review.

        Queues the message/response for review, sends desktop notification,
        records in D-Bus history, and optionally notifies a channel.

        Args:
            msg: The PendingMessage
            response: Generated response text
            classification: User classification result
            state_db: The SlackStateDB instance
            session: The SlackSession instance (for sending notifications)
            dbus_handler: Optional D-Bus handler for history recording
        """
        # Enforce max pending reviews to prevent unbounded memory growth
        if len(self._pending_reviews) >= self._max_pending_reviews:
            # Remove oldest review
            self._pending_reviews.pop(0)
            logger.warning(
                f"Pending reviews exceeded limit ({self._max_pending_reviews}), removed oldest"
            )

        self._pending_reviews.append(
            {
                "message": msg,
                "response": response,
                "classification": classification,
                "intent": "claude",
            }
        )

        if self.ui:
            print(
                f"   {self.ui.COLORS['yellow']}⏸️  QUEUED FOR REVIEW (concerned user){self.ui.COLORS['reset']}"
            )
            print(f"   Pending reviews: {len(self._pending_reviews)}")

        # Desktop notification - awaiting approval
        if self.notifier:
            self.notifier.awaiting_approval(
                user_name=msg.user_name,
                channel_name=msg.channel_name,
                text=msg.text,
                pending_count=len(self._pending_reviews),
            )

        # Record pending message in D-Bus history
        if dbus_handler:
            self._record_pending_dbus(msg, dbus_handler)

        # Optionally notify about concerned user message
        await self._notify_concerned_message(msg, response, session)

        # Still mark as processed (we've handled it, just not sent yet)
        await state_db.mark_message_processed(msg.id)

    def _record_pending_dbus(self, msg: Any, dbus_handler: Any):
        """Record a pending message in D-Bus history."""
        try:
            from services.slack.dbus import MessageRecord

            record = MessageRecord(
                id=msg.id,
                timestamp=msg.timestamp,
                channel_id=msg.channel_id,
                channel_name=msg.channel_name,
                user_id=msg.user_id,
                user_name=msg.user_name,
                text=msg.text,
                intent="claude",
                classification="concerned",
                response="",
                status="pending",
                created_at=time.time(),
            )
            dbus_handler.history.add(record)
            dbus_handler.emit_pending_approval(record)

            # Emit toast notification for pending approval
            try:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_slack_pending_approval,
                )

                notify_slack_pending_approval(
                    msg.channel_name, msg.user_name, msg.text[:50]
                )
            except Exception:
                pass

        except ImportError:
            logger.debug("D-Bus not available for pending message recording")

    async def _notify_concerned_message(self, msg: Any, response: str, session: Any):
        """Notify when a concerned user sends a message."""
        notifications = self._slack_config.get("notifications", {})
        if not notifications.get("notify_on_concerned_message", False):
            return

        notify_channel = notifications.get("notification_channel")
        notify_user = notifications.get("notify_user_id")

        if not notify_channel and not notify_user:
            return

        notification = (
            f"⚠️ *Concerned User Message*\n\n"
            f"From: {msg.user_name} in #{msg.channel_name}\n"
            f"Message: {msg.text[:200]}{'...' if len(msg.text) > 200 else ''}\n\n"
            f"Proposed response queued for review."
        )

        try:
            if notify_channel:
                await session.send_message(
                    channel_id=notify_channel,
                    text=notification,
                    typing_delay=False,
                )
            elif notify_user:
                # DM the user
                await session.send_message(
                    channel_id=notify_user,
                    text=notification,
                    typing_delay=False,
                )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
