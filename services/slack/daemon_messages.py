"""Per-message handling for the Slack daemon: alerts, @me commands and replies."""

import importlib
import logging
import time
from typing import TYPE_CHECKING, Any

from services.slack.daemon_startup import SlackDaemonCore
from services.slack.errors import IMPORT_OR_SLACK_ERRORS, SLACK_ERRORS
from services.slack.slack_config import get_slack_config

if TYPE_CHECKING:
    from src.listener import PendingMessage

    from services.slack.message_processor import UserClassification

logger = logging.getLogger(__name__)

DEBUG_RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
DEFAULT_ALERT_INFO = {
    "environment": "unknown",
    "namespace": "tower-analytics-stage",
    "severity": "medium",
    "auto_investigate": False,
}

_ALERT_PROMPT = """
This is a Prometheus alert from the {env} environment that needs investigation AND a reply.

**Channel:** {channel_id}
**Message TS:** {timestamp}
**Namespace:** {namespace}

**Alert Message:**
{text}

IMPORTANT: After investigating, you MUST use `slack_send_message` to reply:
- channel_id: "{reply_channel}"
- thread_ts: {thread_ts}
- text: {text_prefix}(your investigation summary)

Steps:
1. Check pod status with k8s_get_pods
2. Check events with k8s_get_events
3. Get logs if pods are unhealthy
4. Search for existing Jira issues
5. **REPLY using slack_send_message with your findings** (REQUIRED!)

Do NOT just describe what you found - you MUST call slack_send_message to actually reply to Slack!
"""


def alert_prompt(
    msg: "PendingMessage", alert_info: dict, reply_channel: str, reply_thread_ts: Any, debug_prefix: str
) -> str:
    """Build the Claude prompt that investigates and answers an alert."""
    return _ALERT_PROMPT.format(
        env=alert_info.get("environment", "unknown"),
        channel_id=msg.channel_id,
        timestamp=msg.timestamp,
        namespace=alert_info.get("namespace", "tower-analytics-stage"),
        text=msg.text[:2000],
        reply_channel=reply_channel,
        thread_ts=f'"{reply_thread_ts}"' if reply_thread_ts else "null (no threading)",
        text_prefix=f'"{debug_prefix}" + ' if debug_prefix else "",
    )


def as_alert_info(alert_info: Any) -> dict:
    """Coerce whatever the alert detector returned into an alert-info dict."""
    if isinstance(alert_info, dict):
        return alert_info
    logger.warning("alert_info is %s, converting to dict. Content: %s", type(alert_info), alert_info)
    if isinstance(alert_info, str):
        return {"environment": alert_info}
    return {}


def message_record(msg: "PendingMessage", classification: "UserClassification", response: str, status: str) -> Any:
    """Build the D-Bus history record for a handled message."""
    record_cls = importlib.import_module("services.slack.dbus").MessageRecord
    return record_cls(
        id=msg.id,
        timestamp=msg.timestamp,
        channel_id=msg.channel_id,
        channel_name=msg.channel_name,
        user_id=msg.user_id,
        user_name=msg.user_name,
        text=msg.text,
        intent="claude",
        classification=classification.category.value,
        response=response,
        status=status,
        created_at=time.time(),
        processed_at=time.time(),
    )


def _emit_ide_toast(msg: "PendingMessage") -> None:
    """Emit the IDE toast notification for a new Slack message, if available."""
    try:
        emitter = importlib.import_module("tool_modules.aa_workflow.src.notification_emitter")
        emitter.notify_slack_message(msg.channel_name, msg.user_name, msg.text[:100])
    except IMPORT_OR_SLACK_ERRORS as exc:
        logger.debug("Suppressed error: %s", exc)


class SlackMessageHandling(SlackDaemonCore):
    """Turns pending Slack messages into alert investigations, command replies or Claude replies."""

    def _reply_target(self, msg: "PendingMessage", what: str) -> tuple[str, Any, str]:
        """(channel, thread_ts, debug prefix) for an alert reply."""
        redirect = self.options.debug_redirect_channel
        if self.options.debug_mode and redirect:
            self.parts.ui.print_info("🐛 DEBUG: Alert response will go to self-DM")
            prefix = f"🐛 *DEBUG MODE* - {what} (would go to #{msg.channel_name})\n{DEBUG_RULE}"
            return redirect, None, prefix  # No threading in debug DMs
        return msg.channel_id, msg.timestamp, ""

    async def handle_alert_message(self, msg: "PendingMessage", alert_info: Any) -> None:
        """
        Handle a Prometheus alert message by running the investigate_slack_alert skill.

        Invokes Claude to run the investigation; the skill replies in Slack with
        its findings and a Jira link.
        """
        try:
            info = as_alert_info(alert_info)
            env = info.get("environment", "unknown")
            namespace = info.get("namespace", "tower-analytics-stage")
            self.parts.ui.print_info(f"🚨 Alert detected in {env} ({namespace})")

            reply_channel, reply_thread_ts, debug_prefix = self._reply_target(msg, "Alert response")
            prompt = alert_prompt(msg, info, reply_channel, reply_thread_ts, debug_prefix)

            agent = self.parts.response_generator.claude_agent
            if not agent:
                logger.warning("Claude agent not available for alert investigation")
                return

            logger.info("Invoking Claude for alert investigation in #%s (ts: %s)", msg.channel_id, msg.timestamp)
            response = await agent.process_message(
                prompt,
                context={
                    "is_alert": True,
                    "environment": env,
                    "namespace": namespace,
                    "channel_id": msg.channel_id,
                    "message_ts": msg.timestamp,
                },
                # Use thread_ts for alert conversation tracking
                conversation_id=f"{msg.channel_id}:{msg.timestamp}",
            )
            if response:
                logger.info("Claude alert investigation response: %s...", response[:200])
                self.parts.ui.print_info("✅ Alert investigation complete")
            else:
                logger.warning("Claude alert investigation returned no response for alert in %s", msg.channel_id)
                self.parts.ui.print_info("⚠️ Alert investigation returned no response")

        except SLACK_ERRORS as e:
            logger.error("Error handling alert: %s", e)
            self.parts.ui.print_error(f"Alert handling failed: {e}")

    async def _try_alert(self, msg: "PendingMessage") -> bool:
        """Auto-investigate ``msg`` if it is an alert; True when it was handled."""
        detector = self.parts.alert_detector
        if not detector.is_alert_message(msg.channel_id, msg.user_name, msg.text, msg.raw_message):
            return False

        alert_info = detector.get_alert_info(msg.channel_id)
        # CRITICAL: Always ensure alert_info is a dict
        if not isinstance(alert_info, dict):
            logger.error("alert_info is not a dict! type=%s, content=%s", type(alert_info), alert_info)
            alert_info = dict(DEFAULT_ALERT_INFO)

        if not detector.should_auto_investigate(msg.channel_id):
            logger.debug("Alert detected but auto-investigate disabled for channel %s", msg.channel_id)
            return False

        logger.info("🚨 Alert detected in %s: auto-investigating", alert_info.get("environment", "unknown"))
        await self.handle_alert_message(msg, alert_info)
        await self.conn.state_db.mark_message_processed(msg.id)
        return True

    async def _try_command(self, msg: "PendingMessage", classification: "UserClassification") -> bool:
        """Run ``msg`` as an @me command if it is one; True when it was handled."""
        handler = self.conn.command_handler
        is_self_dm = msg.channel_id == get_slack_config("listener.self_dm_channel", "")
        if not handler or not handler.is_command(msg.text, is_self_dm):
            return False

        logger.info("@me command detected: %s", msg.text[:50])
        self.parts.ui.print_message(msg, "@me command", classification, channel_allowed=True)
        self.parts.ui.messages_processed += 1

        response, should_send = await handler.handle(msg, classification)
        if response:
            await self.send_response_or_skip(msg, response, classification, should_send)

        await self.conn.state_db.mark_message_processed(msg.id)
        return True

    async def _notify_received(self, msg: "PendingMessage", classification: "UserClassification") -> None:
        """Desktop and IDE notification for a new message, once per message across restarts."""
        if await self.conn.state_db.was_notified(msg.timestamp):
            logger.debug("Skipping notification for %s - already notified", msg.timestamp)
            return
        self.parts.notifier.message_received(
            user_name=msg.user_name,
            channel_name=msg.channel_name,
            text=msg.text,
            classification=classification.category.value,
        )
        # Mark as notified so we don't spam on restart
        await self.conn.state_db.mark_notified(msg.timestamp, msg.channel_id)
        _emit_ide_toast(msg)

    async def _skip_not_allowed(self, msg: "PendingMessage", classification: "UserClassification", reason: str) -> None:
        """Record a reply that channel permissions do not allow."""
        ui = self.parts.ui
        print(f"   {ui.COLORS['yellow']}🚫 NOT RESPONDING: {reason}{ui.COLORS['reset']}")
        self.parts.notifier.message_ignored(user_name=msg.user_name, channel_name=msg.channel_name, reason=reason)
        await self.record_dbus_skipped(msg, classification)
        # Still mark as processed
        await self.conn.state_db.mark_message_processed(msg.id)

    async def process_message(self, msg: "PendingMessage") -> None:
        """Process a single pending message."""
        classification = self.parts.user_classifier.classify(msg.user_id, msg.user_name)

        if await self._try_alert(msg) or await self._try_command(msg, classification):
            return

        # Check response rules - should we respond to this message?
        can_respond, permission_reason = self.parts.channel_permissions.should_respond(
            channel_id=msg.channel_id,
            message_text=msg.text,
            is_dm=msg.is_dm,
            is_mention=msg.is_mention,
            mentioned_users=getattr(msg, "mentioned_users", []),
            mentioned_groups=getattr(msg, "mentioned_groups", []),
        )

        self.parts.ui.print_message(msg, "claude", classification, channel_allowed=can_respond)
        self.parts.ui.messages_processed += 1
        await self._notify_received(msg, classification)

        # Generate response using Claude (handles intent, tool calls, everything)
        response, should_send = await self.parts.response_generator.generate(msg, classification)

        # If response is None (error occurred), silently skip - don't respond at all
        if response is None:
            logger.debug("No response generated for message %s - silently skipping", msg.id)
            await self.conn.state_db.mark_message_processed(msg.id)
            return

        if self._dbus_handler:
            self._dbus_handler.messages_processed = self.parts.ui.messages_processed
            self._dbus_handler.session = self.conn.session

        # Handle concerned users - queue for review instead of auto-sending
        if classification.require_review and not self.options.dry_run:
            await self.parts.approval_manager.handle_concerned_user_review(
                msg, response, classification, self.conn.state_db, self.conn.session, self._dbus_handler
            )
            return

        if not can_respond:
            await self._skip_not_allowed(msg, classification, permission_reason)
            return

        await self.send_response_or_skip(msg, response, classification, should_send)

    async def record_dbus_skipped(self, msg: "PendingMessage", classification: "UserClassification") -> None:
        """Record a skipped message in D-Bus history."""
        if self._dbus_handler:
            self._dbus_handler.history.add(message_record(msg, classification, "", "skipped"))

    def _send_target(self, msg: "PendingMessage", response: str) -> tuple[str, Any, str]:
        """(channel, thread_ts, text) for a reply, honouring debug redirection."""
        redirect = self.options.debug_redirect_channel
        if self.options.debug_mode and redirect:
            header = (
                f"🐛 *DEBUG MODE* - Would have sent to #{msg.channel_name} (reply to {msg.user_name})\n{DEBUG_RULE}"
            )
            ui = self.parts.ui
            print(f"   {ui.COLORS['magenta']}🐛 DEBUG: Redirecting to self-DM{ui.COLORS['reset']}")
            return redirect, None, header + response  # No threading in debug DMs
        # In DMs (channel starts with D), don't use threading; in channels reply in thread
        is_dm = msg.channel_id.startswith("D")
        return msg.channel_id, None if is_dm else (msg.thread_ts or msg.timestamp), response

    async def _deliver(self, msg: "PendingMessage", response: str) -> tuple[bool, str]:
        """Send the reply; return (success, text actually sent)."""
        notifier = self.parts.notifier
        notifier.responding(user_name=msg.user_name, channel_name=msg.channel_name, intent="claude")
        try:
            channel, thread_ts, response = self._send_target(msg, response)
            sent_msg = await self.conn.session.send_message(
                channel_id=channel, text=response, thread_ts=thread_ts, typing_delay=True
            )
            # Update last_processed_ts to our sent message so we don't respond to ourselves
            if sent_msg and "ts" in sent_msg:
                await self.conn.state_db.set_last_processed_ts(msg.channel_id, sent_msg["ts"], msg.channel_name)
            self.parts.ui.messages_responded += 1
            if self._dbus_handler:
                self._dbus_handler.messages_responded = self.parts.ui.messages_responded
            notifier.response_sent(user_name=msg.user_name, channel_name=msg.channel_name)
        except SLACK_ERRORS as e:
            self.parts.ui.print_error(f"Failed to send: {e}")
            notifier.error(f"Failed to send: {e}")
            return False, response
        return True, response

    async def send_response_or_skip(
        self,
        msg: "PendingMessage",
        response: str,
        classification: "UserClassification",
        should_send: bool,
    ) -> None:
        """Send response or record as skipped."""
        success, status = True, "sent"
        if not self.options.dry_run and should_send:
            success, response = await self._deliver(msg, response)
            status = "sent" if success else "failed"
        elif not should_send:
            status = "skipped"
            ui = self.parts.ui
            print(f"   {ui.COLORS['dim']}(auto_respond disabled){ui.COLORS['reset']}")

        self.parts.ui.print_response(response, success)

        if self._dbus_handler:
            self._dbus_handler.history.add(message_record(msg, classification, response, status))
            self._dbus_handler.emit_message_processed(msg.id, status)

        await self.conn.state_db.mark_message_processed(msg.id)
