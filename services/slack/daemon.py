#!/usr/bin/env python3
"""
Autonomous Slack Persona Daemon

A standalone process that monitors Slack and responds using Claude + MCP tools.
The daemon is just a Slack interface - all intelligence goes through ClaudeAgent,
which routes to MCP servers (aa_jira, aa_gitlab, aa_k8s, aa_bonfire, etc.)

Requirements:
- Claude API credentials (ANTHROPIC_API_KEY or Vertex AI)
- Slack credentials (config.json or environment variables)

Features:
- Continuous Slack monitoring with configurable poll interval
- Claude-powered message understanding and tool execution
- User classification (safe/concerned/unknown) for response modulation
- Rich terminal UI with status display
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.slack                    # Run with Claude
    python -m services.slack --dry-run          # Process but don't respond
    python -m services.slack --verbose          # Detailed logging
    python -m services.slack --dbus             # Enable D-Bus IPC

Configuration:
    All settings are read from config.json under the "slack" key.
    Environment variables can override config.json values.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Path setup - must happen before other imports
_service_dir = os.path.dirname(os.path.abspath(__file__))
_services_dir = os.path.dirname(_service_dir)  # services/
_PROJECT_ROOT = os.path.dirname(_services_dir)  # project root

# Add tool_modules to path for src imports
import sys

sys.path.insert(0, os.path.join(_PROJECT_ROOT, "tool_modules", "aa_slack"))

from dotenv import load_dotenv

# @me command system imports
from scripts.common.command_parser import CommandParser, ParsedCommand, TriggerType
from scripts.common.command_registry import CommandRegistry, CommandType, get_registry
from scripts.common.config_loader import load_config
from scripts.common.context_extractor import ContextExtractor, ConversationContext
from scripts.common.response_router import CommandContext, ResponseFormatter, ResponseMode, ResponseRouter, get_router
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeMonitor

# Import PROJECT_ROOT after path setup
PROJECT_ROOT = Path(_PROJECT_ROOT)

if TYPE_CHECKING:
    from src.listener import PendingMessage, SlackListener
    from src.persistence import SlackStateDB
    from src.slack_client import SlackSession

# Desktop notifications (optional)
NOTIFY_AVAILABLE = False
try:
    import gi

    gi.require_version("Notify", "0.7")
    from gi.repository import Notify

    NOTIFY_AVAILABLE = True
    Notify.init("AI Workflow Slack Persona")
except (ImportError, ValueError):
    pass


# Setup
load_dotenv(PROJECT_ROOT / "tool_modules" / "aa_slack" / ".env")
load_dotenv()

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG = load_config()
SLACK_CONFIG = CONFIG.get("slack", {})


def get_slack_config(key: str, default: Any = None, env_var: str = None) -> Any:
    """
    Get a Slack config value with environment variable override.

    Priority: Environment variable > config.json > default
    """
    if env_var and os.getenv(env_var):
        return os.getenv(env_var)

    # Navigate nested keys like "auth.xoxc_token"
    keys = key.split(".")
    value = SLACK_CONFIG
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            value = None
            break

    return value if value is not None else default


def refresh_slack_credentials() -> bool:
    """
    Run get_slack_creds.py to refresh credentials from Chrome.

    Returns True if successful, False otherwise.
    """
    import subprocess

    script_path = PROJECT_ROOT / "scripts" / "get_slack_creds.py"
    if not script_path.exists():
        print(f"⚠️  Credential refresh script not found: {script_path}")
        return False

    print("🔄 Attempting to refresh Slack credentials from Chrome...")
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print("✅ Credentials refreshed from Chrome")
            # Reload config to pick up new values
            global CONFIG, SLACK_CONFIG
            CONFIG = load_config()
            SLACK_CONFIG = CONFIG.get("slack", {})
            return True
        else:
            print(f"⚠️  Credential refresh failed: {result.stderr or result.stdout}")
            return False

    except subprocess.TimeoutExpired:
        print("⚠️  Credential refresh timed out")
        return False
    except Exception as e:
        print(f"⚠️  Credential refresh error: {e}")
        return False


# =============================================================================
# USER CLASSIFICATION
# =============================================================================


class UserCategory(Enum):
    """User classification categories."""

    SAFE = "safe"  # Teammates - respond freely
    CONCERNED = "concerned"  # Managers - respond carefully
    UNKNOWN = "unknown"  # Everyone else - professional default


@dataclass
class UserClassification:
    """Classification result for a user."""

    category: UserCategory
    response_style: str  # casual, formal, professional
    auto_respond: bool
    require_review: bool
    include_emojis: bool
    cc_notification: bool
    max_response_length: int | None


class UserClassifier:
    """Classifies users based on config.json lists."""

    def __init__(self):
        self.user_config = SLACK_CONFIG.get("user_classification", {})
        self._load_lists()

    def _load_lists(self):
        """Load user lists from config."""
        safe = self.user_config.get("safe_list", {})
        self.safe_user_ids = set(safe.get("user_ids", []))
        self.safe_user_names = set(u.lower() for u in safe.get("user_names", []))

        concerned = self.user_config.get("concerned_list", {})
        self.concerned_user_ids = set(concerned.get("user_ids", []))
        self.concerned_user_names = set(u.lower() for u in concerned.get("user_names", []))

    def classify(self, user_id: str, user_name: str) -> UserClassification:
        """Classify a user and return response settings."""
        user_name_lower = user_name.lower()

        # Check concerned list first (takes priority)
        if user_id in self.concerned_user_ids or user_name_lower in self.concerned_user_names:
            concerned = self.user_config.get("concerned_list", {})
            return UserClassification(
                category=UserCategory.CONCERNED,
                response_style=concerned.get("response_style", "formal"),
                auto_respond=concerned.get("auto_respond", False),
                require_review=concerned.get("require_review", True),
                include_emojis=concerned.get("include_emojis", False),
                cc_notification=concerned.get("cc_notification", True),
                max_response_length=None,
            )

        # Check safe list
        if user_id in self.safe_user_ids or user_name_lower in self.safe_user_names:
            safe = self.user_config.get("safe_list", {})
            return UserClassification(
                category=UserCategory.SAFE,
                response_style=safe.get("response_style", "casual"),
                auto_respond=safe.get("auto_respond", True),
                require_review=False,
                include_emojis=safe.get("include_emojis", True),
                cc_notification=False,
                max_response_length=None,
            )

        # Default: unknown
        unknown = self.user_config.get("unknown_list", {})
        return UserClassification(
            category=UserCategory.UNKNOWN,
            response_style=unknown.get("response_style", "professional"),
            auto_respond=unknown.get("auto_respond", True),
            require_review=False,
            include_emojis=unknown.get("include_emojis", True),
            cc_notification=False,
            max_response_length=unknown.get("max_response_length", 500),
        )

    def reload(self):
        """Reload lists from config (for hot reload)."""
        global CONFIG, SLACK_CONFIG
        CONFIG = load_config()
        SLACK_CONFIG = CONFIG.get("slack", {})
        self.user_config = SLACK_CONFIG.get("user_classification", {})
        self._load_lists()


# =============================================================================
# ALERT DETECTION
# =============================================================================


class AlertDetector:
    """
    Detects Prometheus alert messages from app-sre-alerts bot.

    Alert messages come from the app-sre-alerts bot in specific channels
    (stage/prod alerts) and contain Prometheus alert information with
    links to Grafana, AlertManager, Runbook, etc.
    """

    def __init__(self):
        self.config = SLACK_CONFIG.get("listener", {})
        self.alert_channels = self.config.get("alert_channels", {})
        self.alert_bot_names = ["app-sre-alerts", "alertmanager"]

    def is_alert_message(
        self,
        channel_id: str,
        user_name: str,
        text: str,
        raw_message: dict | None = None,
    ) -> bool:
        """
        Check if this message is a Prometheus alert.

        An alert message is:
        1. In an alert channel (C01CPSKFG0P or C01L1K82AP5)
        2. From the app-sre-alerts bot
        3. Contains alert indicators (FIRING, Alert:, alertmanager URL)
        """
        # Check if it's an alert channel
        if channel_id not in self.alert_channels:
            return False

        # Check if from alert bot
        user_lower = (user_name or "").lower()

        # If user_name is missing, try to get it from raw_message
        if not user_lower and raw_message:
            user_lower = (raw_message.get("username") or raw_message.get("bot_id") or "").lower()

        is_from_alert_bot = any(bot in user_lower for bot in self.alert_bot_names)

        # Check for alert indicators in text
        text_lower = (text or "").lower()

        # If text is missing, try to get it from attachments in raw_message
        if not text_lower and raw_message and "attachments" in raw_message:
            att_texts = []
            for att in raw_message["attachments"]:
                if isinstance(att, dict):
                    att_texts.append((att.get("text") or att.get("fallback") or "").lower())
                    att_texts.append((att.get("title") or "").lower())
                elif isinstance(att, str):
                    att_texts.append(att.lower())
            text_lower = " ".join(att_texts)

        alert_indicators = [
            "firing",
            "resolved",
            "alert:",
            "alertmanager",
            "prometheus",
        ]
        has_alert_indicator = any(ind in text_lower for ind in alert_indicators)

        is_alert = is_from_alert_bot or (channel_id in self.alert_channels and has_alert_indicator)

        if is_alert:
            logger.info(f"🚨 Alert detected: channel={channel_id}, user={user_name}, text={text[:100]}...")

        return is_alert

    def get_alert_info(self, channel_id: str) -> dict:
        """Get the channel's alert configuration."""
        info = self.alert_channels.get(channel_id)
        if isinstance(info, dict):
            return info

        return {
            "environment": "unknown",
            "namespace": "tower-analytics-stage",
            "severity": "medium",
            "auto_investigate": False,
        }

    def should_auto_investigate(self, channel_id: str) -> bool:
        """Check if this channel has auto-investigate enabled."""
        info = self.get_alert_info(channel_id)
        if isinstance(info, dict):
            return info.get("auto_investigate", False)
        return False


# =============================================================================
# CHANNEL PERMISSIONS
# =============================================================================


class ResponseRules:
    """
    Controls when the agent should respond based on message context.

    Rules:
    1. DMs: Always respond (approval required for concerned users)
    2. Channels: Only respond when mentioned (@username or @group)
    3. Unmentioned channel messages: Ignore
    """

    def __init__(self):
        self.config = SLACK_CONFIG.get("response_rules", {})
        self._load_config()

    def _load_config(self):
        """Load response rules from config."""
        # DM settings
        dm_config = self.config.get("direct_messages", {})
        self.dm_enabled = dm_config.get("enabled", True)

        # Channel mention settings
        mention_config = self.config.get("channel_mentions", {})
        self.mention_enabled = mention_config.get("enabled", True)
        self.trigger_mentions = set(mention_config.get("trigger_mentions", []))
        self.trigger_user_ids = set(mention_config.get("trigger_user_ids", []))
        self.trigger_group_ids = set(mention_config.get("trigger_group_ids", []))

        # Keyword settings (optional)
        keyword_config = self.config.get("channel_keywords", {})
        self.keyword_enabled = keyword_config.get("enabled", False)
        self.trigger_keywords = set(keyword_config.get("keywords", []))

        # General settings
        self.ignore_unmentioned = self.config.get("ignore_unmentioned", True)
        self.blocked_channels = set(self.config.get("blocked_channels", []))

    def _check_user_mentions(self, mentioned_users: list[str]) -> tuple[bool, str]:
        """Check if any trigger users are mentioned."""
        for user_id in mentioned_users:
            if user_id in self.trigger_user_ids:
                return True, f"Trigger user {user_id} mentioned"
        return False, ""

    def _check_group_mentions(self, mentioned_groups: list[str]) -> tuple[bool, str]:
        """Check if any trigger groups are mentioned."""
        for group_id in mentioned_groups:
            if group_id in self.trigger_group_ids:
                return True, f"Trigger group {group_id} mentioned"
        return False, ""

    def _check_text_mentions(self, message_text: str) -> tuple[bool, str]:
        """Check if any trigger mentions appear in text."""
        text_lower = message_text.lower()
        for mention in self.trigger_mentions:
            if mention.lower() in text_lower:
                return True, f"Trigger mention '{mention}' found"
        return False, ""

    def _check_keywords(self, message_text: str) -> tuple[bool, str]:
        """Check if any trigger keywords appear in text."""
        text_lower = message_text.lower()
        for keyword in self.trigger_keywords:
            if keyword.lower() in text_lower:
                return True, f"Trigger keyword '{keyword}' found"
        return False, ""

    def should_respond(
        self,
        channel_id: str,
        message_text: str,
        is_dm: bool = False,
        is_mention: bool = False,
        mentioned_users: list[str] | None = None,
        mentioned_groups: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        Determine if the agent should respond to this message.

        Args:
            channel_id: The channel ID
            message_text: The message text
            is_dm: Whether this is a direct message
            is_mention: Whether the bot was mentioned (from Slack API)
            mentioned_users: List of user IDs mentioned in the message
            mentioned_groups: List of group IDs mentioned in the message

        Returns:
            tuple of (should_respond, reason)
        """
        mentioned_users = mentioned_users or []
        mentioned_groups = mentioned_groups or []

        # Check blocked list first
        if channel_id in self.blocked_channels:
            return False, "Channel is blocked"

        # Rule 1: DMs - always respond if enabled
        if is_dm:
            if self.dm_enabled:
                return True, "DM response enabled"
            return False, "DM responses disabled"

        # Rule 2: Channel mentions - check if we're mentioned
        if self.mention_enabled:
            # Check if bot was directly mentioned (from Slack API)
            if is_mention:
                return True, "Bot was @mentioned"

            # Check trigger user IDs
            should_respond, reason = self._check_user_mentions(mentioned_users)
            if should_respond:
                return True, reason

            # Check trigger group IDs
            should_respond, reason = self._check_group_mentions(mentioned_groups)
            if should_respond:
                return True, reason

            # Check trigger mentions in text
            should_respond, reason = self._check_text_mentions(message_text)
            if should_respond:
                return True, reason

        # Rule 3: Keywords (if enabled)
        if self.keyword_enabled:
            should_respond, reason = self._check_keywords(message_text)
            if should_respond:
                return True, reason

        # Default: ignore unmentioned channel messages
        if self.ignore_unmentioned:
            return False, "Not mentioned in channel"

        return True, "Default allow"

    def reload(self):
        """Reload config (for hot reload)."""
        global CONFIG, SLACK_CONFIG
        CONFIG = load_config()
        SLACK_CONFIG = CONFIG.get("slack", {})
        self.config = SLACK_CONFIG.get("response_rules", {})
        self._load_config()


# Keep ChannelPermissions as alias for backwards compatibility
ChannelPermissions = ResponseRules


# =============================================================================
# DESKTOP NOTIFICATIONS
# =============================================================================


class DesktopNotifier:
    """
    Desktop notifications using libnotify.

    Shows visual alerts for:
    - 📩 Message received
    - ✅ Response sent
    - 🚫 Message ignored (channel not allowed)
    - ⏸️ Awaiting approval (concerned user)

    Includes rate limiting to prevent notification spam during restart cycles.
    """

    # Notification urgency levels
    URGENCY_LOW = 0
    URGENCY_NORMAL = 1
    URGENCY_CRITICAL = 2

    # Rate limiting settings
    RATE_LIMIT_WINDOW = 60.0  # seconds
    RATE_LIMIT_MAX = 10  # max notifications per window
    STOP_NOTIFICATION_COOLDOWN = 120.0  # seconds between "stopped" notifications

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and NOTIFY_AVAILABLE
        self._icons = {
            "received": "mail-unread",
            "responding": "mail-send",
            "sent": "mail-replied",
            "ignored": "dialog-warning",
            "approval": "dialog-question",
            "error": "dialog-error",
        }
        # Rate limiting state
        self._notification_times: list[float] = []
        self._last_stop_notification: float = 0
        self._last_start_notification: float = 0

    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits. Returns True if OK to send."""
        now = time.time()
        # Remove old entries outside the window
        self._notification_times = [t for t in self._notification_times if now - t < self.RATE_LIMIT_WINDOW]
        # Check if we're at the limit
        if len(self._notification_times) >= self.RATE_LIMIT_MAX:
            return False
        # Record this notification
        self._notification_times.append(now)
        return True

    def _send(
        self,
        title: str,
        body: str,
        icon: str = "dialog-information",
        urgency: int = 1,
        timeout: int = 5000,
        bypass_rate_limit: bool = False,
    ):
        """Send a desktop notification."""
        if not self.enabled:
            return

        # Check rate limit (unless bypassed for critical notifications)
        if not bypass_rate_limit and not self._check_rate_limit():
            logger.debug(f"Notification rate limited: {title}")
            return

        try:
            notification = Notify.Notification.new(title, body, icon)
            notification.set_urgency(urgency)
            notification.set_timeout(timeout)
            notification.show()
        except Exception as e:
            logger.debug(f"Notification failed: {e}")

    def message_received(
        self,
        user_name: str,
        channel_name: str,
        text: str,
        classification: str = "unknown",
    ):
        """Notify when a message is received."""
        # Truncate text for notification
        preview = text[:100] + "..." if len(text) > 100 else text

        title = f"📩 Message from {user_name}"
        body = f"#{channel_name}\n{preview}\n\n[{classification}]"

        urgency = self.URGENCY_CRITICAL if classification == "concerned" else self.URGENCY_NORMAL
        self._send(title, body, self._icons["received"], urgency)

    def responding(self, user_name: str, channel_name: str, intent: str):
        """Notify when responding to a message."""
        title = "✅ Responding"
        body = f"To {user_name} in #{channel_name}\nIntent: {intent}"
        self._send(title, body, self._icons["responding"], self.URGENCY_LOW, timeout=3000)

    def response_sent(self, user_name: str, channel_name: str):
        """Notify when response was sent successfully."""
        title = "📤 Response Sent"
        body = f"To {user_name} in #{channel_name}"
        self._send(title, body, self._icons["sent"], self.URGENCY_LOW, timeout=2000)

    def message_ignored(self, user_name: str, channel_name: str, reason: str):
        """Notify when a message is ignored."""
        title = "🚫 Message Ignored"
        body = f"From {user_name} in #{channel_name}\nReason: {reason}"
        self._send(title, body, self._icons["ignored"], self.URGENCY_LOW, timeout=3000)

    def awaiting_approval(
        self,
        user_name: str,
        channel_name: str,
        text: str,
        pending_count: int,
    ):
        """Notify when a message needs approval."""
        preview = text[:80] + "..." if len(text) > 80 else text

        title = f"⏸️ Approval Required ({pending_count} pending)"
        body = f"From {user_name} (concerned user) in #{channel_name}\n\n{preview}\n\nRun: make slack-pending"

        self._send(
            title,
            body,
            self._icons["approval"],
            self.URGENCY_CRITICAL,
            timeout=10000,
        )

    def error(self, message: str):
        """Notify on error."""
        title = "❌ Slack Persona Error"
        self._send(title, message, self._icons["error"], self.URGENCY_CRITICAL)

    def skill_activated(self, skill_name: str, description: str = ""):
        """Notify when a skill/tool is activated."""
        title = f"⚡ Activating: {skill_name}"
        body = description or f"Running {skill_name}..."
        self._send(title, body, "system-run", self.URGENCY_LOW, timeout=3000)

    def skill_completed(self, skill_name: str, success: bool = True):
        """Notify when a skill/tool completes."""
        if success:
            title = f"✅ Completed: {skill_name}"
            icon = "emblem-ok-symbolic"
        else:
            title = f"❌ Failed: {skill_name}"
            icon = "emblem-important-symbolic"
        self._send(title, "", icon, self.URGENCY_LOW, timeout=2000)

    def started(self):
        """Notify when daemon starts."""
        now = time.time()
        # Don't spam start notifications during restart cycles
        if now - self._last_start_notification < self.STOP_NOTIFICATION_COOLDOWN:
            logger.debug("Skipping start notification (cooldown)")
            return
        self._last_start_notification = now

        title = "🤖 Slack Persona Started"
        body = "Monitoring channels for messages..."
        self._send(title, body, "emblem-default", self.URGENCY_LOW, timeout=3000)

    def stopped(self):
        """Notify when daemon stops."""
        now = time.time()
        # Don't spam stop notifications during restart cycles
        if now - self._last_stop_notification < self.STOP_NOTIFICATION_COOLDOWN:
            logger.debug("Skipping stop notification (cooldown)")
            return
        self._last_stop_notification = now

        title = "🛑 Slack Persona Stopped"
        body = "No longer monitoring Slack"
        self._send(title, body, "emblem-important", self.URGENCY_LOW, timeout=3000)


# =============================================================================
# TERMINAL UI
# =============================================================================


class TerminalUI:
    """Rich terminal output for the daemon."""

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.start_time = time.time()
        self.messages_processed = 0
        self.messages_responded = 0
        self.errors = 0

    def clear_line(self):
        """Clear current line."""
        print("\r\033[K", end="")

    def print_header(self, debug_mode: bool = False):
        """Print startup header."""
        cyan = self.COLORS["cyan"]
        bold = self.COLORS["bold"]
        yellow = self.COLORS["yellow"]
        reset = self.COLORS["reset"]

        mode_indicator = f"{yellow}🐛 DEBUG MODE{reset}" if debug_mode else ""

        print(
            f"""
{cyan}╔══════════════════════════════════════════════════════════════════╗
║  {bold}🤖 AI Workflow - Autonomous Slack Persona{reset}{cyan}                          ║
║                                                                    ║
║  Monitoring Slack channels for messages...                         ║
║  Press Ctrl+C to stop                                              ║
╚══════════════════════════════════════════════════════════════════╝{reset}
{mode_indicator}"""
        )

    def print_status(self, listener_stats: dict):
        """Print current status."""
        uptime = time.time() - self.start_time
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)

        status = f"{self.COLORS['dim']}[{hours:02d}:{minutes:02d}:{seconds:02d}]{self.COLORS['reset']} "
        status += f"📊 Polls: {listener_stats.get('polls', 0)} | "
        status += f"📬 Seen: {listener_stats.get('messages_seen', 0)} | "
        status += f"✅ Processed: {self.messages_processed} | "
        status += f"💬 Responded: {self.messages_responded}"

        # Show consecutive errors from listener stats (resets on successful poll)
        consecutive_errors = listener_stats.get("consecutive_errors", 0)
        total_errors = listener_stats.get("errors", 0) + self.errors

        if consecutive_errors > 0:
            status += f" | {self.COLORS['red']}❌ Errors: {consecutive_errors}{self.COLORS['reset']}"
        elif total_errors > 0:
            # Show total errors dimmed if no recent errors
            status += f" | {self.COLORS['dim']}({total_errors} total errors){self.COLORS['reset']}"

        self.clear_line()
        print(status, end="", flush=True)

    def print_info(self, text: str):
        """Print info message."""
        print(f"\n{self.COLORS['cyan']}ℹ️ {text}{self.COLORS['reset']}")

    def print_message(
        self,
        msg: PendingMessage,
        intent: str,
        classification: "UserClassification | None" = None,
        channel_allowed: bool = True,
    ):
        """Print incoming message."""
        print(f"\n{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}")
        print(f"{self.COLORS['bold']}📩 New Message{self.COLORS['reset']}")

        # Show channel with permission indicator
        channel_indicator = "✅" if channel_allowed else "🚫"
        print(f"   Channel: #{msg.channel_name} {channel_indicator}")
        print(f"   From: {msg.user_name}")

        # Show user classification
        if classification:
            cat = classification.category.value
            if cat == "safe":
                cat_display = f"{self.COLORS['green']}✅ SAFE{self.COLORS['reset']}"
            elif cat == "concerned":
                cat_display = f"{self.COLORS['red']}⚠️  CONCERNED{self.COLORS['reset']}"
            else:
                cat_display = f"{self.COLORS['blue']}❓ UNKNOWN{self.COLORS['reset']}"
            print(f"   User: {cat_display} ({classification.response_style})")

        print(f"   Intent: {self.COLORS['cyan']}{intent}{self.COLORS['reset']}")
        print(f"   Text: {msg.text[:100]}{'...' if len(msg.text) > 100 else ''}")

    def print_response(self, response: str, success: bool):
        """Print outgoing response."""
        status = (
            f"{self.COLORS['green']}✅{self.COLORS['reset']}"
            if success
            else f"{self.COLORS['red']}❌{self.COLORS['reset']}"
        )
        print(f"   Response: {status}")
        if self.verbose:
            print(f"   {self.COLORS['dim']}{response[:200]}...{self.COLORS['reset']}")
        print(f"{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}")

    def print_error(self, error: str):
        """Print error message."""
        print(f"\n{self.COLORS['red']}❌ Error: {error}{self.COLORS['reset']}")
        self.errors += 1

    def print_shutdown(self, listener_stats: dict | None = None):
        """Print shutdown message."""
        print(f"\n\n{self.COLORS['cyan']}Shutting down gracefully...{self.COLORS['reset']}")
        print(f"   📊 Total processed: {self.messages_processed}")
        print(f"   💬 Total responded: {self.messages_responded}")
        # Combine listener errors with daemon errors
        listener_errors = listener_stats.get("errors", 0) if listener_stats else 0
        total_errors = self.errors + listener_errors
        print(f"   ❌ Total errors: {total_errors}")
        print(f"{self.COLORS['green']}Goodbye! 👋{self.COLORS['reset']}\n")


# =============================================================================
# INTENT DETECTION
# =============================================================================


# =============================================================================
# NOTE: IntentDetector and ToolExecutor classes have been REMOVED.
#
# All message understanding and tool execution now goes through ClaudeAgent,
# which routes to MCP servers (aa_jira, aa_gitlab, aa_k8s, aa_bonfire, etc.)
#
# The Slack daemon is just a Slack interface - all intelligence is in Claude.
# =============================================================================


# =============================================================================
# COMMAND HANDLER - @me commands
# =============================================================================


class CommandHandler:
    """
    Handles @me commands from Slack.

    Parses commands, extracts context, and routes to appropriate handlers.
    Supports:
    - @me <skill_name> - Run a skill with context from thread
    - @me help - List available commands
    - @me help <command> - Get help for a specific command
    - @me status - Show bot status
    """

    def __init__(
        self,
        slack_client: Any = None,
        claude_agent: Any = None,
        notifier: "DesktopNotifier | None" = None,
    ):
        self.slack_client = slack_client
        self.claude_agent = claude_agent
        self.notifier = notifier

        self.parser = CommandParser()
        self.registry = get_registry()
        self.router = get_router()
        self.formatter = ResponseFormatter()

        # Config
        self.config = get_slack_config("commands", {})
        self.context_limit = self.config.get("context_messages_limit", 20)
        self.contextual_skills = set(self.config.get("contextual_skills", ["create_jira_issue", "investigate_alert"]))

    def is_command(self, text: str, is_self_dm: bool = False) -> bool:
        """Check if a message is an @me command."""
        parsed = self.parser.parse(text, is_self_dm)
        return parsed.is_command

    async def handle(
        self,
        message: "PendingMessage",
        classification: "UserClassification",
    ) -> tuple[str | None, bool]:
        """
        Handle an @me command.

        Args:
            message: The pending message
            classification: User classification

        Returns:
            Tuple of (response_text, should_send)
        """
        # Check if this is in self-DM channel
        self_dm_channel = get_slack_config("listener.self_dm_channel", "")
        is_self_dm = message.channel_id == self_dm_channel

        # Parse the command
        parsed = self.parser.parse(message.text, is_self_dm)

        if not parsed.is_command:
            return None, False

        logger.info(f"Processing @me command: {parsed.command} (type: {parsed.trigger_type.value})")

        # Route the command
        try:
            if self.parser.is_help_command(parsed):
                response = await self._handle_help(parsed)
            elif self.parser.is_status_command(parsed):
                response = await self._handle_status()
            elif parsed.command == "list":
                response = await self._handle_list(parsed)
            elif parsed.command == "watch":
                response = await self._handle_watch(message)
            # D-Bus service commands
            elif parsed.command == "jira":
                response = await self._handle_jira(parsed, message)
            elif parsed.command == "search":
                response = await self._handle_search(parsed)
            elif parsed.command == "who":
                response = await self._handle_who(parsed)
            elif parsed.command == "find":
                response = await self._handle_find(parsed)
            elif parsed.command == "cursor":
                response = await self._handle_cursor(parsed, message)
            elif parsed.command == "sprint":
                response = await self._handle_sprint(parsed)
            elif parsed.command == "meet":
                response = await self._handle_meet(parsed)
            elif parsed.command == "cron":
                response = await self._handle_cron(parsed)
            elif parsed.command == "research":
                response = await self._handle_research(parsed, message)
            elif parsed.command == "learn":
                response = await self._handle_learn(parsed, message)
            elif parsed.command == "knowledge":
                response = await self._handle_knowledge(parsed)
            else:
                response = await self._handle_skill_or_tool(parsed, message)

            # Format response
            routing_ctx = CommandContext(
                channel_id=message.channel_id,
                thread_ts=message.thread_ts,
                message_ts=message.timestamp,
                user_id=message.user_id,
                is_dm=message.is_dm,
                reply_dm=parsed.reply_dm,
                reply_thread=parsed.reply_thread,
                command=parsed.command,
            )

            route_config = self.router.route(routing_ctx)

            # Should always send command responses
            should_send = classification.auto_respond

            return response, should_send

        except Exception as e:
            logger.error(f"Error handling command {parsed.command}: {e}", exc_info=True)
            return f"❌ Error: {str(e)}", True

    async def _handle_help(self, parsed: ParsedCommand) -> str:
        """Handle help command."""
        target = self.parser.get_help_target(parsed)

        if target:
            # Help for specific command
            help_info = self.registry.get_command_help(target)
            if help_info:
                return help_info.format_slack()
            return f"❌ Unknown command: `{target}`\n\nUse `@me help` to list available commands."

        # General help
        commands = self.registry.list_commands()
        return self.registry.format_list(commands, "slack")

    async def _handle_status(self) -> str:
        """Handle status command."""
        lines = ["*🤖 Bot Status*\n"]

        # Count available commands
        skills = self.registry.list_commands(command_type=CommandType.SKILL)
        tools = self.registry.list_commands(command_type=CommandType.TOOL)

        lines.append(f"• *Skills available:* {len(skills)}")
        lines.append(f"• *Tools available:* {len(tools)}")
        lines.append(f"• *Contextual skills:* {', '.join(sorted(self.contextual_skills))}")

        if self.claude_agent:
            lines.append("• *Claude:* ✅ Connected")
        else:
            lines.append("• *Claude:* ❌ Not connected")

        lines.append("\n_Use `@me help` to see available commands_")

        return "\n".join(lines)

    async def _handle_list(self, parsed: ParsedCommand) -> str:
        """Handle list command."""
        filter_type = None
        if parsed.args:
            arg = parsed.args[0].lower()
            if arg in ("skill", "skills"):
                filter_type = CommandType.SKILL
            elif arg in ("tool", "tools"):
                filter_type = CommandType.TOOL

        commands = self.registry.list_commands(command_type=filter_type)
        return self.registry.format_list(commands, "slack")

    async def _handle_watch(self, message: "PendingMessage") -> str:
        """Handle watch command - show channel ID for adding to watch list."""
        channel_id = message.channel_id

        # Determine channel type
        if channel_id.startswith("D"):
            channel_type = "DM (direct message)"
        elif channel_id.startswith("G"):
            channel_type = "MPDM (group DM / private chat)"
        elif channel_id.startswith("C"):
            channel_type = "public channel"
        else:
            channel_type = "channel"

        # Check if already being watched
        watched = get_slack_config("listener.watched_channels", [])
        is_watched = channel_id in watched

        lines = [f"*📡 Channel Info*\n"]
        lines.append(f"• *Channel ID:* `{channel_id}`")
        lines.append(f"• *Type:* {channel_type}")
        lines.append(f"• *Currently watched:* {'✅ Yes' if is_watched else '❌ No'}")

        if not is_watched:
            lines.append("\n*To watch this channel:*")
            lines.append(f'Add `"{channel_id}"` to `slack.listener.watched_channels` in `config.json`')

        return "\n".join(lines)

    async def _handle_skill_or_tool(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle a skill or tool command."""
        cmd_info = self.registry.get_command(parsed.command)

        if not cmd_info:
            return f"❌ Unknown command: `{parsed.command}`\n\n" f"Use `@me help` to list available commands."

        # Get explicit inputs from parsed command
        inputs = parsed.to_skill_inputs()

        # Check if this is a contextual skill and we need to extract context
        if cmd_info.contextual and not inputs:
            context = await self._extract_context(message)
            if context.is_valid():
                # Merge context into inputs
                context_inputs = context.to_skill_inputs(parsed.command)
                inputs.update(context_inputs)

                # Show extracted context to user
                context_preview = self._format_context_preview(context)
                if context_preview:
                    logger.info(f"Extracted context for {parsed.command}: {context.summary[:100]}")

        # Build the request for Claude
        if cmd_info.command_type == CommandType.SKILL:
            return await self._run_skill(parsed.command, inputs, message)
        else:
            return await self._run_tool(parsed.command, inputs, message)

    async def _extract_context(self, message: "PendingMessage") -> ConversationContext:
        """Extract context from the conversation."""
        extractor = ContextExtractor(
            slack_client=self.slack_client,
            claude_agent=self.claude_agent,
            context_messages_limit=self.context_limit,
        )

        return await extractor.extract(
            channel_id=message.channel_id,
            thread_ts=message.thread_ts,
            message_ts=message.timestamp,
            exclude_command_message=True,
        )

    def _format_context_preview(self, context: ConversationContext) -> str:
        """Format a preview of extracted context."""
        lines = []

        if context.summary:
            lines.append(f"*Summary:* {context.summary}")
        if context.inferred_type:
            lines.append(f"*Type:* {context.inferred_type}")
        if context.jira_issues:
            lines.append(f"*Related:* {', '.join(context.jira_issues)}")

        return "\n".join(lines) if lines else ""

    async def _run_skill(self, skill_name: str, inputs: dict, message: "PendingMessage") -> str:
        """Run a skill via Claude."""
        if not self.claude_agent:
            return "❌ Claude agent not available"

        # Build prompt for Claude to run the skill
        import json

        inputs_json = json.dumps(inputs) if inputs else "{}"

        prompt = f"""Execute the skill `{skill_name}` with these inputs:

```json
{inputs_json}
```

Use `skill_run("{skill_name}", '{inputs_json}')` to execute the skill and return the results.
Format the output for Slack (use *bold*, `code`, bullet points).
"""

        try:
            context = {
                "user_name": message.user_name,
                "channel_name": message.channel_name,
                "is_dm": message.is_dm,
                "purpose": "skill_execution",
                "skill_name": skill_name,
            }
            conversation_id = f"{message.channel_id}:{message.thread_ts or message.user_id}"

            response = await self.claude_agent.process_message(prompt, context, conversation_id=conversation_id)
            return response

        except Exception as e:
            logger.error(f"Failed to run skill {skill_name}: {e}")
            return f"❌ Failed to run skill `{skill_name}`: {str(e)}"

    async def _run_tool(self, tool_name: str, inputs: dict, message: "PendingMessage") -> str:
        """Run a tool via Claude."""
        if not self.claude_agent:
            return "❌ Claude agent not available"

        # Build prompt for Claude to run the tool
        import json

        inputs_json = json.dumps(inputs) if inputs else "{}"

        prompt = f"""Execute the tool `{tool_name}` with these arguments:

```json
{inputs_json}
```

Call the tool directly and return the results.
Format the output for Slack (use *bold*, `code`, bullet points).
"""

        try:
            context = {
                "user_name": message.user_name,
                "channel_name": message.channel_name,
                "is_dm": message.is_dm,
                "purpose": "tool_execution",
                "tool_name": tool_name,
            }
            conversation_id = f"{message.channel_id}:{message.thread_ts or message.user_id}"

            response = await self.claude_agent.process_message(prompt, context, conversation_id=conversation_id)
            return response

        except Exception as e:
            logger.error(f"Failed to run tool {tool_name}: {e}")
            return f"❌ Failed to run tool `{tool_name}`: {str(e)}"

    # =========================================================================
    # D-BUS SERVICE COMMAND HANDLERS
    # =========================================================================

    async def _call_dbus(self, service: str, path: str, interface: str, method: str, args: list | None = None) -> dict:
        """Call a D-Bus method and return the result."""
        try:
            from dbus_next import Variant
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            introspection = await bus.introspect(service, path)
            proxy = bus.get_proxy_object(service, path, introspection)
            iface = proxy.get_interface(interface)

            # Call the method
            method_func = getattr(iface, f"call_{method.lower()}")
            if args:
                result = await method_func(*args)
            else:
                result = await method_func()

            bus.disconnect()

            # Parse JSON result if string
            if isinstance(result, str):
                import json

                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"result": result}
            return {"result": result}

        except Exception as e:
            logger.error(f"D-Bus call failed: {service}.{method}: {e}")
            return {"error": str(e)}

    async def _handle_jira(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle @me jira command - create Jira issue from thread context."""
        # Determine issue type from args
        issue_type = "Task"  # default
        parent_key = None

        if parsed.args:
            arg = parsed.args[0].lower()
            if arg == "bug":
                issue_type = "Bug"
            elif arg == "story":
                issue_type = "Story"
            elif arg == "task":
                issue_type = "Task"
            elif arg == "subtask" and len(parsed.args) > 1:
                issue_type = "Sub-task"
                parent_key = parsed.args[1].upper()
            elif arg.startswith("aap-") or arg.startswith("AAP-"):
                # Assume it's a parent key for subtask
                issue_type = "Sub-task"
                parent_key = arg.upper()

        # Extract context from thread
        context = await self._extract_context(message)

        if not context.is_valid():
            return "❌ Could not extract context from thread. Please provide more details."

        # Build inputs for create_jira_issue skill
        inputs = {
            "summary": context.summary[:200] if context.summary else "Issue from Slack thread",
            "description": context.raw_text[:2000] if context.raw_text else "",
            "issue_type": issue_type,
            "slack_format": True,
        }

        if parent_key:
            inputs["parent_key"] = parent_key

        if context.jira_issues:
            inputs["link_to"] = context.jira_issues[0]  # Link to first related issue

        # For Stories, use Claude to generate required fields from context
        if issue_type == "Story" and self.claude_agent:
            story_fields = await self._generate_story_fields(context)
            if story_fields:
                inputs.update(story_fields)

        # Run the skill
        return await self._run_skill("create_jira_issue", inputs, message)

    async def _generate_story_fields(self, context: ConversationContext) -> dict:
        """Use Claude to generate story-specific fields from conversation context."""
        if not self.claude_agent:
            return {}

        prompt = f"""Based on this Slack conversation, generate Jira Story fields.

Conversation:
{context.raw_text[:2000]}

Summary so far: {context.summary}

Generate these fields in JSON format:
{{
    "user_story": "As a [role], I want [feature], so that [benefit]",
    "acceptance_criteria": "- Criterion 1\\n- Criterion 2\\n- Criterion 3",
    "definition_of_done": "- Code reviewed and merged\\n- Tests pass\\n- Documentation updated"
}}

Be concise. Extract the actual requirements from the conversation.
Return ONLY the JSON, no other text."""

        try:
            response = await self.claude_agent.process_message(
                prompt,
                context={"purpose": "story_field_generation"},
            )

            # Parse JSON from response
            import json
            import re

            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                fields = json.loads(json_match.group())
                return {
                    "user_story": fields.get("user_story", ""),
                    "acceptance_criteria": fields.get("acceptance_criteria", ""),
                    "definition_of_done": fields.get("definition_of_done", ""),
                }
        except Exception as e:
            logger.warning(f"Failed to generate story fields: {e}")

        # Return defaults if generation fails
        return {
            "user_story": f"As a user, I want {context.summary}",
            "acceptance_criteria": "- Requirements met\n- Tests pass",
            "definition_of_done": "- Code reviewed and merged\n- Tests pass",
        }

    async def _handle_search(self, parsed: ParsedCommand) -> str:
        """Handle @me search command - search Slack, code, or Jira."""
        if not parsed.args:
            return "❌ Please provide a search query.\n\nUsage:\n• `@me search <query>` - Search Slack\n• `@me search code <query>` - Search code\n• `@me search jira <query>` - Search Jira"

        search_type = "slack"
        query_parts = parsed.args

        # Check for search type prefix
        if parsed.args[0].lower() in ("code", "jira", "slack", "logs"):
            search_type = parsed.args[0].lower()
            query_parts = parsed.args[1:]

        if not query_parts:
            return f"❌ Please provide a search query for {search_type} search."

        query = " ".join(query_parts)

        if search_type == "slack":
            # Use D-Bus to search Slack
            result = await self._call_dbus(
                "com.aiworkflow.BotSlack",
                "/com/aiworkflow/BotSlack",
                "com.aiworkflow.BotSlack",
                "SearchMessages",
                [query, 20],
            )

            if "error" in result:
                return f"❌ Search failed: {result['error']}"

            if result.get("rate_limited"):
                return f"⏳ Rate limited. {result.get('error', 'Please wait before searching again.')}"

            messages = result.get("messages", [])
            if not messages:
                return f"🔍 No results found for: `{query}`"

            lines = [f"*🔍 Slack Search Results* ({len(messages)} of {result.get('total', len(messages))})\n"]
            for msg in messages[:10]:
                channel = msg.get("channel_name", "unknown")
                user = msg.get("username", "unknown")
                text = msg.get("text", "")[:100]
                lines.append(f"• *#{channel}* (@{user}): {text}...")

            remaining = result.get("searches_remaining_today")
            if remaining is not None:
                lines.append(f"\n_({remaining} searches remaining today)_")

            return "\n".join(lines)

        elif search_type == "code":
            # Use Claude to search code
            return await self._run_skill("code_search", {"query": query}, None)

        elif search_type == "jira":
            # Use Claude to search Jira
            return await self._run_tool("jira_search", {"jql": f'text ~ "{query}"', "max_results": 10}, None)

        else:
            return f"❌ Unknown search type: `{search_type}`"

    async def _handle_who(self, parsed: ParsedCommand) -> str:
        """Handle @me who command - look up a Slack user."""
        if not parsed.args:
            return "❌ Please provide a username or email.\n\nUsage: `@me who @username` or `@me who email@example.com`"

        query = parsed.args[0].lstrip("@")

        result = await self._call_dbus(
            "com.aiworkflow.BotSlack", "/com/aiworkflow/BotSlack", "com.aiworkflow.BotSlack", "FindUser", [query]
        )

        if "error" in result:
            return f"❌ Lookup failed: {result['error']}"

        users = result.get("users", [])
        if not users:
            return f"🔍 No users found matching: `{query}`"

        lines = [f"*👤 User Lookup: {query}*\n"]
        for user in users[:5]:
            lines.append(f"• *{user.get('display_name') or user.get('user_name')}*")
            lines.append(f"  ID: `{user.get('user_id')}`")
            if user.get("real_name"):
                lines.append(f"  Name: {user.get('real_name')}")
            if user.get("email"):
                lines.append(f"  Email: {user.get('email')}")
            if user.get("gitlab_username"):
                lines.append(f"  GitLab: @{user.get('gitlab_username')}")
            lines.append("")

        return "\n".join(lines)

    async def _handle_find(self, parsed: ParsedCommand) -> str:
        """Handle @me find command - find a Slack channel."""
        if not parsed.args:
            return "❌ Please provide a channel name.\n\nUsage: `@me find #channel-name` or `@me find alerts`"

        query = parsed.args[0].lstrip("#")

        result = await self._call_dbus(
            "com.aiworkflow.BotSlack", "/com/aiworkflow/BotSlack", "com.aiworkflow.BotSlack", "FindChannel", [query]
        )

        if "error" in result:
            return f"❌ Lookup failed: {result['error']}"

        channels = result.get("channels", [])
        if not channels:
            return f"🔍 No channels found matching: `{query}`"

        lines = [f"*📢 Channel Lookup: {query}*\n"]
        for ch in channels[:10]:
            member = " ✅" if ch.get("is_member") else ""
            private = " 🔒" if ch.get("is_private") else ""
            lines.append(f"• *#{ch.get('name')}*{member}{private}")
            lines.append(f"  ID: `{ch.get('channel_id')}`")
            if ch.get("purpose"):
                lines.append(f"  Purpose: {ch.get('purpose')[:80]}")
            if ch.get("num_members"):
                lines.append(f"  Members: {ch.get('num_members')}")
            lines.append("")

        return "\n".join(lines)

    async def _handle_cursor(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle @me cursor command - create a Cursor chat from thread."""
        # Extract context from thread
        context = await self._extract_context(message)

        # Check for issue key in args
        issue_key = None
        if parsed.args:
            for arg in parsed.args:
                if arg.upper().startswith("AAP-"):
                    issue_key = arg.upper()
                    break

        # Build prompt from context
        prompt = ""
        if context.is_valid():
            prompt = f"Context from Slack thread:\n\n{context.summary}\n\n{context.raw_text[:1000]}"
            if context.jira_issues:
                prompt += f"\n\nRelated issues: {', '.join(context.jira_issues)}"
        elif issue_key:
            prompt = f"Work on issue {issue_key}"
        else:
            return "❌ Could not extract context from thread. Please provide an issue key.\n\nUsage: `@me cursor` (in a thread) or `@me cursor AAP-12345`"

        # Call the Chat D-Bus service
        if issue_key:
            result = await self._call_dbus(
                "com.aiworkflow.Chat",
                "/com/aiworkflow/Chat",
                "com.aiworkflow.Chat",
                "LaunchIssueChatWithPrompt",
                [issue_key, prompt],
            )
        else:
            result = await self._call_dbus(
                "com.aiworkflow.Chat",
                "/com/aiworkflow/Chat",
                "com.aiworkflow.Chat",
                "LaunchIssueChatWithPrompt",
                ["", prompt],
            )

        if "error" in result:
            return f"❌ Failed to launch Cursor chat: {result['error']}"

        return "✅ Cursor chat launched with thread context"

    async def _handle_sprint(self, parsed: ParsedCommand) -> str:
        """Handle @me sprint command - control the sprint bot."""
        if not parsed.args:
            return "❌ Please provide a subcommand.\n\nUsage:\n• `@me sprint issues` - List sprint issues\n• `@me sprint approve AAP-12345` - Approve an issue\n• `@me sprint start AAP-12345` - Start work on an issue\n• `@me sprint skip AAP-12345` - Skip an issue"

        subcommand = parsed.args[0].lower()
        issue_key = parsed.args[1].upper() if len(parsed.args) > 1 else None

        if subcommand in ("issues", "list"):
            result = await self._call_dbus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "list_issues",
            )

            if "error" in result:
                return f"❌ Failed to list issues: {result['error']}"

            issues = result.get("issues", [])
            if not issues:
                return "📋 No sprint issues found"

            lines = ["*📋 Sprint Issues*\n"]
            for issue in issues[:15]:
                status = issue.get("approval_status", "pending")
                icon = "✅" if status == "approved" else "⏳" if status == "pending" else "⏭️"
                lines.append(f"{icon} *{issue.get('key')}* - {issue.get('summary', '')[:50]}")

            return "\n".join(lines)

        elif subcommand == "approve" and issue_key:
            result = await self._call_dbus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "approve_issue",
                [issue_key],
            )

            if "error" in result:
                return f"❌ Failed to approve: {result['error']}"

            return f"✅ Issue {issue_key} approved for sprint bot"

        elif subcommand == "start" and issue_key:
            result = await self._call_dbus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "start_issue",
                [issue_key],
            )

            if "error" in result:
                return f"❌ Failed to start: {result['error']}"

            return f"✅ Started work on {issue_key}"

        elif subcommand == "skip" and issue_key:
            result = await self._call_dbus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "skip_issue",
                [issue_key],
            )

            if "error" in result:
                return f"❌ Failed to skip: {result['error']}"

            return f"⏭️ Skipped {issue_key}"

        else:
            return f"❌ Unknown sprint command: `{subcommand}`\n\nUse `@me help sprint` for usage."

    async def _handle_meet(self, parsed: ParsedCommand) -> str:
        """Handle @me meet command - control the meet bot."""
        if not parsed.args:
            return "❌ Please provide a subcommand.\n\nUsage:\n• `@me meet list` - List upcoming meetings\n• `@me meet join` - Join current meeting\n• `@me meet leave` - Leave meeting\n• `@me meet captions` - Get meeting captions"

        subcommand = parsed.args[0].lower()

        if subcommand in ("list", "meetings"):
            result = await self._call_dbus(
                "com.aiworkflow.BotMeet",
                "/com/aiworkflow/BotMeet",
                "com.aiworkflow.BotMeet",
                "list_meetings",
            )

            if "error" in result:
                return f"❌ Failed to list meetings: {result['error']}"

            meetings = result.get("meetings", [])
            if not meetings:
                return "📅 No upcoming meetings"

            lines = ["*📅 Upcoming Meetings*\n"]
            for mtg in meetings[:10]:
                status = mtg.get("status", "pending")
                icon = "🟢" if status == "in_progress" else "⏳"
                lines.append(f"{icon} *{mtg.get('title', 'Untitled')}*")
                lines.append(f"  Time: {mtg.get('start_time', 'Unknown')}")

            return "\n".join(lines)

        elif subcommand == "join":
            result = await self._call_dbus(
                "com.aiworkflow.BotMeet",
                "/com/aiworkflow/BotMeet",
                "com.aiworkflow.BotMeet",
                "join_meeting",
            )

            if "error" in result:
                return f"❌ Failed to join meeting: {result['error']}"

            return "✅ Joining meeting..."

        elif subcommand == "leave":
            result = await self._call_dbus(
                "com.aiworkflow.BotMeet",
                "/com/aiworkflow/BotMeet",
                "com.aiworkflow.BotMeet",
                "leave_meeting",
            )

            if "error" in result:
                return f"❌ Failed to leave meeting: {result['error']}"

            return "✅ Left meeting"

        elif subcommand == "captions":
            result = await self._call_dbus(
                "com.aiworkflow.BotMeet",
                "/com/aiworkflow/BotMeet",
                "com.aiworkflow.BotMeet",
                "get_captions",
            )

            if "error" in result:
                return f"❌ Failed to get captions: {result['error']}"

            captions = result.get("captions", "")
            if not captions:
                return "📝 No captions available"

            return f"*📝 Meeting Captions*\n\n{captions[:2000]}"

        else:
            return f"❌ Unknown meet command: `{subcommand}`\n\nUse `@me help meet` for usage."

    async def _handle_cron(self, parsed: ParsedCommand) -> str:
        """Handle @me cron command - control the cron scheduler."""
        if not parsed.args:
            return "❌ Please provide a subcommand.\n\nUsage:\n• `@me cron list` - List scheduled jobs\n• `@me cron run <job>` - Run a job now\n• `@me cron history` - Show recent job history"

        subcommand = parsed.args[0].lower()

        if subcommand in ("list", "jobs"):
            result = await self._call_dbus(
                "com.aiworkflow.BotCron",
                "/com/aiworkflow/BotCron",
                "com.aiworkflow.BotCron",
                "list_jobs",
            )

            if "error" in result:
                return f"❌ Failed to list jobs: {result['error']}"

            jobs = result.get("jobs", [])
            if not jobs:
                return "📅 No scheduled jobs"

            lines = ["*📅 Scheduled Jobs*\n"]
            for job in jobs:
                enabled = "✅" if job.get("enabled") else "⏸️"
                lines.append(f"{enabled} *{job.get('name')}* - {job.get('description', '')[:40]}")
                lines.append(f"  Schedule: `{job.get('cron', 'unknown')}`")

            return "\n".join(lines)

        elif subcommand == "run" and len(parsed.args) > 1:
            job_name = parsed.args[1]
            result = await self._call_dbus(
                "com.aiworkflow.BotCron", "/com/aiworkflow/BotCron", "com.aiworkflow.BotCron", "run_job", [job_name]
            )

            if "error" in result:
                return f"❌ Failed to run job: {result['error']}"

            return f"✅ Started job: `{job_name}`"

        elif subcommand == "history":
            result = await self._call_dbus(
                "com.aiworkflow.BotCron",
                "/com/aiworkflow/BotCron",
                "com.aiworkflow.BotCron",
                "get_history",
            )

            if "error" in result:
                return f"❌ Failed to get history: {result['error']}"

            history = result.get("history", [])
            if not history:
                return "📜 No job history"

            lines = ["*📜 Recent Job History*\n"]
            for entry in history[:10]:
                status = "✅" if entry.get("success") else "❌"
                lines.append(f"{status} *{entry.get('job_name')}* - {entry.get('timestamp', '')}")

            return "\n".join(lines)

        else:
            return f"❌ Unknown cron command: `{subcommand}`\n\nUse `@me help cron` for usage."

    async def _handle_research(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle @me research command - research a topic in Slack."""
        if not parsed.args:
            return "❌ Please provide a topic to research.\n\nUsage:\n• `@me research billing errors` - Research a topic\n• `@me research deep auth issues` - Deep research with more results"

        # Check for modifiers
        deep = False
        channel = None
        topic_parts = []

        for arg in parsed.args:
            if arg.lower() == "deep":
                deep = True
            elif arg.startswith("#"):
                channel = arg.lstrip("#")
            elif arg.lower() == "in" and channel is None:
                continue  # Skip "in" before channel
            else:
                topic_parts.append(arg)

        topic = " ".join(topic_parts)
        if not topic:
            return "❌ Please provide a topic to research."

        # Check rate limits via D-Bus
        result = await self._call_dbus(
            "com.aiworkflow.BotSlack",
            "/com/aiworkflow/BotSlack",
            "com.aiworkflow.BotSlack",
            "SearchMessages",
            [topic, 50 if deep else 30],
        )

        if "error" in result:
            if result.get("rate_limited"):
                return f"⏳ Rate limited. {result.get('error', 'Please wait before researching again.')}"
            return f"❌ Research failed: {result['error']}"

        messages = result.get("messages", [])
        if not messages:
            return f"🔍 No Slack messages found for: `{topic}`"

        # Use Claude to analyze the messages
        if not self.claude_agent:
            # Fallback: just return the messages
            lines = [f"*🔬 Research: {topic}*\n", f"Found {len(messages)} messages:\n"]
            for msg in messages[:10]:
                lines.append(f"• *#{msg.get('channel_name')}* - {msg.get('text', '')[:80]}...")
            return "\n".join(lines)

        # Build prompt for Claude to analyze
        import json

        messages_text = "\n".join(
            [f"[#{m.get('channel_name')}] @{m.get('username')}: {m.get('text', '')}" for m in messages[:30]]
        )

        prompt = f"""Analyze these Slack messages about "{topic}" and create a knowledge summary:

{messages_text}

Create a structured summary with:
1. Key patterns or recurring themes
2. Common causes mentioned
3. Solutions that worked
4. Related Jira issues mentioned
5. Key people involved

Format for Slack (use *bold*, bullet points). Be concise."""

        try:
            analysis = await self.claude_agent.process_message(prompt, {"purpose": "research"})

            # Save to knowledge base
            await self._save_research_knowledge(topic, analysis, messages)

            return f"*🔬 Research: {topic}*\n\n{analysis}\n\n_Knowledge saved to `memory/knowledge/slack/`_"

        except Exception as e:
            logger.error(f"Research analysis failed: {e}")
            return f"❌ Analysis failed: {str(e)}"

    async def _handle_learn(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle @me learn command - learn from current thread."""
        # Extract context from thread
        context = await self._extract_context(message)

        if not context.is_valid():
            return "❌ Could not extract context from thread. Please use this command in a thread with discussion."

        # Determine topic from args or infer from context
        topic = " ".join(parsed.args) if parsed.args else context.inferred_type or "general"

        # Use Claude to extract learnings
        if not self.claude_agent:
            return "❌ Claude agent not available for learning"

        prompt = f"""Extract key learnings from this Slack thread about "{topic}":

{context.raw_text[:2000]}

Create a structured knowledge entry with:
1. Topic/title
2. Key patterns or insights
3. Solutions or approaches that worked
4. Things to avoid
5. Related issues or links

Format as YAML for storage."""

        try:
            analysis = await self.claude_agent.process_message(prompt, {"purpose": "learning"})

            # Save to knowledge base
            await self._save_thread_learning(topic, analysis, context)

            return f"✅ Learned from thread about `{topic}`\n\n{analysis[:500]}...\n\n_Saved to knowledge base_"

        except Exception as e:
            logger.error(f"Learning failed: {e}")
            return f"❌ Learning failed: {str(e)}"

    async def _handle_knowledge(self, parsed: ParsedCommand) -> str:
        """Handle @me knowledge command - query or list knowledge."""
        if not parsed.args:
            return "❌ Please provide a topic or 'list'.\n\nUsage:\n• `@me knowledge billing` - Query knowledge about billing\n• `@me knowledge list` - List all knowledge topics"

        subcommand = parsed.args[0].lower()

        if subcommand == "list":
            # List knowledge files
            knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
            if not knowledge_dir.exists():
                return "📚 No Slack knowledge saved yet"

            files = list(knowledge_dir.glob("*.yaml"))
            if not files:
                return "📚 No Slack knowledge saved yet"

            lines = ["*📚 Slack Knowledge Base*\n"]
            for f in sorted(files)[:20]:
                topic = f.stem.replace("-", " ").title()
                lines.append(f"• `{f.stem}` - {topic}")

            return "\n".join(lines)

        elif subcommand == "delete" and len(parsed.args) > 1:
            topic = parsed.args[1]
            knowledge_file = PROJECT_ROOT / "memory" / "knowledge" / "slack" / f"{topic}.yaml"
            if knowledge_file.exists():
                knowledge_file.unlink()
                return f"🗑️ Deleted knowledge: `{topic}`"
            return f"❌ Knowledge not found: `{topic}`"

        else:
            # Query knowledge
            topic = " ".join(parsed.args)
            topic_slug = topic.lower().replace(" ", "-")
            knowledge_file = PROJECT_ROOT / "memory" / "knowledge" / "slack" / f"{topic_slug}.yaml"

            if knowledge_file.exists():
                import yaml

                with open(knowledge_file) as f:
                    data = yaml.safe_load(f)

                lines = [f"*📚 Knowledge: {topic}*\n"]
                if data.get("summary"):
                    lines.append(data["summary"][:500])
                if data.get("patterns"):
                    lines.append("\n*Patterns:*")
                    for p in data["patterns"][:5]:
                        lines.append(f"• {p}")
                if data.get("solutions"):
                    lines.append("\n*Solutions:*")
                    for s in data["solutions"][:5]:
                        lines.append(f"• {s}")

                return "\n".join(lines)

            return f"❌ No knowledge found for: `{topic}`\n\nUse `@me research {topic}` to gather knowledge."

    async def _save_research_knowledge(self, topic: str, analysis: str, messages: list) -> None:
        """Save research results to knowledge base."""
        from datetime import datetime

        import yaml

        knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        topic_slug = topic.lower().replace(" ", "-")[:50]
        knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

        data = {
            "metadata": {
                "topic": topic,
                "created": datetime.now().isoformat(),
                "source": "slack_research",
                "message_count": len(messages),
            },
            "summary": analysis[:1000],
            "patterns": [],
            "solutions": [],
            "sources": [m.get("permalink", "") for m in messages[:10] if m.get("permalink")],
        }

        with open(knowledge_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        logger.info(f"Saved research knowledge: {knowledge_file}")

    async def _save_thread_learning(self, topic: str, analysis: str, context: ConversationContext) -> None:
        """Save thread learning to knowledge base."""
        from datetime import datetime

        import yaml

        knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        topic_slug = topic.lower().replace(" ", "-")[:50]
        knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

        data = {
            "metadata": {
                "topic": topic,
                "created": datetime.now().isoformat(),
                "source": "thread_learning",
            },
            "summary": analysis[:1000],
            "patterns": [],
            "solutions": [],
            "related_issues": context.jira_issues,
        }

        with open(knowledge_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        logger.info(f"Saved thread learning: {knowledge_file}")


# =============================================================================
# RESPONSE GENERATOR
# =============================================================================


# Try to import Claude agent
try:
    from scripts.claude_agent import ANTHROPIC_AVAILABLE, ClaudeAgent
except ImportError:
    ANTHROPIC_AVAILABLE = False
    ClaudeAgent = None


class ResponseGenerator:
    """
    Generates responses for messages using Claude.

    All message understanding and tool execution goes through ClaudeAgent,
    which routes to MCP servers (aa_jira, aa_gitlab, aa_k8s, etc.)

    The Slack daemon is just a Slack interface - all intelligence is in Claude.
    """

    def __init__(
        self,
        notifier: DesktopNotifier | None = None,
    ):
        self.claude_agent = None
        self.templates = SLACK_CONFIG.get("response_templates", {})
        self.notifier = notifier or DesktopNotifier(enabled=False)
        self._init_claude()

    def _init_claude(self):
        """Initialize Claude agent - REQUIRED for operation."""
        if not ANTHROPIC_AVAILABLE:
            logger.error("anthropic package not installed. Install with: uv add anthropic")
            raise RuntimeError("Claude agent required but anthropic package not available")

        # Check for either direct API key or Vertex AI credentials
        use_vertex = os.getenv("CLAUDE_CODE_USE_VERTEX") == "1"
        api_key = os.getenv("ANTHROPIC_API_KEY")
        vertex_project = os.getenv("ANTHROPIC_VERTEX_PROJECT_ID")

        if not api_key and not (use_vertex and vertex_project):
            raise RuntimeError(
                "Claude credentials required. Set ANTHROPIC_API_KEY or "
                "CLAUDE_CODE_USE_VERTEX=1 with ANTHROPIC_VERTEX_PROJECT_ID"
            )

        try:
            # Get model from config
            agent_config = CONFIG.get("agent", {})
            model = agent_config.get("model", "claude-sonnet-4-20250514")
            vertex_model = agent_config.get("vertex_model", "claude-sonnet-4-5@20250929")
            max_tokens = agent_config.get("max_tokens", 4096)
            system_prompt = agent_config.get("system_prompt")

            self.claude_agent = ClaudeAgent(
                model=model,
                vertex_model=vertex_model,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
            if use_vertex:
                logger.info(f"Claude agent initialized via Vertex AI: {vertex_project}")
            else:
                logger.info(f"Claude agent initialized with model: {model}")
        except Exception as e:
            logger.error(f"Failed to initialize Claude agent: {e}")
            raise RuntimeError(f"Claude agent initialization failed: {e}")

    def _modulate_response(
        self,
        response: str,
        user_name: str,
        classification: UserClassification,
    ) -> str:
        """
        Light post-processing of Claude's response.

        Note: Claude now handles tone adjustment directly based on user classification
        passed in context. This just handles truncation and safety-net formatting.
        """
        if response is None:
            return None

        # Truncate if max length specified (unknown users get 500 char limit)
        if classification.max_response_length:
            if len(response) > classification.max_response_length:
                response = response[: classification.max_response_length - 50]
                response += "\n\n_...truncated_"

        return response

    async def generate(
        self,
        message: PendingMessage,
        classification: UserClassification,
    ) -> tuple[str | None, bool]:
        """
        Generate a response for the given message using Claude.

        All requests go through ClaudeAgent which:
        - Understands the user's intent
        - Calls appropriate MCP tools (aa_jira, aa_gitlab, aa_k8s, etc.)
        - Runs skills when needed
        - Formats the response

        Returns:
            tuple of (response_text, should_send)
            response_text is None if an error occurred (silently skip)
            should_send is False if user classification requires review
        """
        self.notifier.skill_activated("claude_agent", "Processing with Claude...")

        try:
            context = {
                "user_name": message.user_name,
                "channel_name": message.channel_name,
                "is_dm": message.is_dm,
                "is_mention": message.is_mention,
                # User classification for tone adjustment
                "user_category": classification.category.value,  # safe, concerned, unknown
                "response_style": classification.response_style,  # casual, formal, professional
                "include_emojis": classification.include_emojis,
            }
            # Build conversation ID for history tracking
            # Use thread_ts if in a thread, otherwise channel:user
            if message.thread_ts:
                conversation_id = f"{message.channel_id}:{message.thread_ts}"
            else:
                conversation_id = f"{message.channel_id}:{message.user_id}"

            response = await self.claude_agent.process_message(message.text, context, conversation_id=conversation_id)
            self.notifier.skill_completed("claude_agent", success=True)
        except Exception as e:
            # Log full error internally - stay completely silent to user
            logger.error(f"Claude agent error: {e}", exc_info=True)
            self.notifier.skill_completed("claude_agent", success=False)
            return None, False  # Don't respond at all on error

        # Modulate response based on user classification
        response = self._modulate_response(response, message.user_name, classification)

        # Determine if we should auto-send
        should_send = classification.auto_respond and not classification.require_review

        return response, should_send


# =============================================================================
# MAIN DAEMON
# =============================================================================


class SlackDaemon(DaemonDBusBase, BaseDaemon):
    """
    Main autonomous Slack agent daemon.

    All message understanding and tool execution goes through ClaudeAgent.
    The daemon is just a Slack interface - all intelligence is in Claude.
    """

    # BaseDaemon configuration
    name = "slack"
    description = "Slack Persona Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSlack"
    object_path = "/com/aiworkflow/BotSlack"
    interface_name = "com.aiworkflow.BotSlack"

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        poll_interval_min: float = 5.0,
        poll_interval_max: float = 15.0,
        enable_dbus: bool = False,
        enable_notify: bool = True,
        debug_mode: bool = False,
    ):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)

        self.dry_run = dry_run
        self.poll_interval_min = poll_interval_min
        self.poll_interval_max = poll_interval_max
        self.enable_notify = enable_notify
        self.debug_mode = debug_mode

        # Debug mode: redirect all messages to self
        self.debug_redirect_channel = get_slack_config("listener.self_dm_channel", "")

        self.ui = TerminalUI(verbose=verbose)
        self.notifier = DesktopNotifier(enabled=enable_notify)

        # Initialize Claude-based response generator (REQUIRED)
        # Will raise RuntimeError if Claude is not available
        self.response_generator = ResponseGenerator(notifier=self.notifier)

        # Initialize @me command handler
        self.command_handler: CommandHandler | None = None  # Initialized after session

        self.user_classifier = UserClassifier()
        self.channel_permissions = ChannelPermissions()
        self.alert_detector = AlertDetector()

        self.session: SlackSession | None = None
        self.state_db: SlackStateDB | None = None
        self.listener: SlackListener | None = None

        self._running = False
        self._pending_reviews: list[dict] = []  # Messages awaiting review
        self._max_pending_reviews = 50  # Prevent unbounded memory growth

        # D-Bus support (legacy handler)
        self._dbus_handler = None
        if enable_dbus:
            try:
                from services.slack.dbus import MessageHistory, SlackDaemonWithDBus

                self._dbus_handler = SlackDaemonWithDBus()
                self._dbus_handler.history = MessageHistory()
                logger.info("D-Bus support enabled")
            except ImportError as e:
                logger.warning(f"D-Bus not available: {e}")

        # Sleep/wake monitor
        self._sleep_monitor: SleepWakeMonitor | None = None

        # Background sync for cache population
        self._background_sync = None

    async def _start_background_sync(self):
        """Start the background sync process for cache population."""
        try:
            from src.background_sync import BackgroundSync, SyncConfig, set_background_sync

            # Check if sync is enabled in config
            sync_config = SLACK_CONFIG.get("background_sync", {})
            if not sync_config.get("enabled", True):
                print("⏸️  Background sync disabled in config")
                return

            # Create sync configuration from config.json
            config = SyncConfig(
                min_delay_seconds=sync_config.get("min_delay_seconds", 1.0),
                max_delay_seconds=sync_config.get("max_delay_seconds", 3.0),
                delay_start_seconds=sync_config.get("delay_start_seconds", 60.0),
                download_photos=sync_config.get("download_photos", True),
                max_members_per_channel=sync_config.get("max_members_per_channel", 200),
                full_sync_interval_hours=sync_config.get("full_sync_interval_hours", 24.0),
            )

            self._background_sync = BackgroundSync(
                slack_client=self.session,
                state_db=self.state_db,
                config=config,
            )
            set_background_sync(self._background_sync)
            await self._background_sync.start()

            print(
                f"✅ Background sync started (delay: {config.delay_start_seconds}s, rate: {config.min_delay_seconds}-{config.max_delay_seconds}s)"
            )
            logger.info(
                f"Background sync started: delay={config.delay_start_seconds}s, "
                f"rate={config.min_delay_seconds}-{config.max_delay_seconds}s/req"
            )

        except ImportError as e:
            logger.warning(f"Background sync module not available: {e}")
            print(f"⚠️  Background sync not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start background sync: {e}")
            print(f"⚠️  Background sync failed to start: {e}")

    async def _stop_background_sync(self):
        """Stop the background sync process."""
        if self._background_sync:
            try:
                await self._background_sync.stop()
                logger.info("Background sync stopped")
            except Exception as e:
                logger.error(f"Error stopping background sync: {e}")

    async def _on_system_wake(self):
        """Handle system wake from sleep."""
        logger.info("System wake detected - refreshing Slack connection...")
        print("\n🌅 System wake detected - refreshing...")

        try:
            # Re-validate Slack session (may have expired during sleep)
            if self.session:
                try:
                    auth = await self.session.validate_session()
                    logger.info(f"Slack session still valid: {auth.get('user', 'unknown')}")
                    print("   ✅ Slack session valid")
                except Exception as e:
                    logger.warning(f"Slack session invalid after wake: {e}")
                    print(f"   ⚠️  Slack session needs refresh: {e}")
                    # Could trigger re-auth here if needed

            print("   ✅ Wake handling complete\n")

        except Exception as e:
            logger.error(f"Error handling system wake: {e}")
            print(f"   ⚠️  Wake handling error: {e}\n")

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return slack-specific statistics."""
        stats = {
            "messages_processed": 0,
            "messages_pending": 0,
            "listener_running": self.listener._running if self.listener else False,
        }

        if self.listener:
            listener_stats = self.listener.stats
            stats["polls"] = listener_stats.get("polls", 0)
            stats["messages_seen"] = listener_stats.get("messages_seen", 0)
            stats["messages_processed"] = listener_stats.get("messages_processed", 0)

        if self.state_db:
            try:
                pending = await self.state_db.get_pending_messages(limit=100)
                stats["messages_pending"] = len(pending)
            except Exception:
                pass

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()
        return {**base, **service}

    # ==================== Lifecycle ====================

    async def start_dbus(self):
        """
        Override base class start_dbus to use the custom SlackPersonaDBusInterface.

        This provides the full Slack-specific D-Bus API (GetMyChannels, GetPending, etc.)
        instead of just the basic daemon methods.
        """
        if self._dbus_handler:
            await self._dbus_handler.start_dbus()
            self._dbus_handler.is_running = True
            self._dbus_handler.start_time = self.start_time
            print("✅ D-Bus IPC enabled (com.aiworkflow.BotSlack)")
            return True
        return False

    async def stop_dbus(self):
        """Override base class stop_dbus to use the custom handler."""
        if self._dbus_handler:
            self._dbus_handler.is_running = False
            await self._dbus_handler.stop_dbus()

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        from src.listener import SlackListener
        from src.persistence import SlackStateDB

        self.ui.print_header(debug_mode=self.debug_mode)

        # Start sleep/wake monitor
        self._sleep_monitor = SleepWakeMonitor(on_wake_callback=self._on_system_wake)
        await self._sleep_monitor.start()
        print("✅ Sleep/wake monitor started")

        # Initialize Slack session with automatic credential refresh
        if not await self._init_slack_auth():
            raise RuntimeError("Failed to initialize Slack authentication")

        # Initialize state database - centralized in server.paths
        try:
            from server.paths import SLACK_STATE_DB_FILE

            db_path = str(SLACK_STATE_DB_FILE)
        except ImportError:
            db_path = get_slack_config("state_db_path", "./slack_state.db")
        self.state_db = SlackStateDB(db_path)
        await self.state_db.connect()
        print("✅ State database connected")

        # Initialize listener configuration (async to discover DMs/MPDMs)
        config = await self._init_listener_config()
        self.listener = SlackListener(self.session, self.state_db, config)

        # Initialize @me command handler with session and Claude agent
        self.command_handler = CommandHandler(
            slack_client=self.session,
            claude_agent=self.response_generator.claude_agent,
            notifier=self.notifier,
        )
        print("✅ @me command handler initialized")

        # Print startup status
        self._print_startup_status(config)

        # Start listener
        await self.listener.start()
        self._running = True

        # Update D-Bus handler with listener reference for health checks
        if self._dbus_handler:
            self._dbus_handler.listener = self.listener
            self._dbus_handler.state_db = self.state_db

        # Start background sync for cache population
        await self._start_background_sync()

        # Desktop notification
        self.notifier.started()

        logger.info("Slack daemon ready")

    async def run_daemon(self):
        """Main daemon loop."""
        await self._main_loop()

    async def health_check(self) -> dict:
        """Perform a health check on the slack daemon."""
        self._last_health_check = time.time()

        checks = {
            "running": self._running,
            "listener_active": self.listener is not None and self.listener._running if self.listener else False,
            "session_valid": self.session is not None,
            "state_db_connected": self.state_db is not None,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": "Slack daemon is healthy" if healthy else "Slack daemon has issues",
            "timestamp": self._last_health_check,
        }

    async def _watchdog_loop_internal(self, interval: float):
        """Periodically notify systemd that the daemon is healthy.

        Verifies D-Bus interface is responding before sending ping.
        """
        from services.base.daemon import sd_notify

        logger.info(f"Watchdog enabled, pinging every {interval:.1f}s")

        while self._running:
            try:
                # Verify D-Bus is working (if enabled)
                healthy = True
                if self._dbus_handler:
                    if not (hasattr(self._dbus_handler, "_bus") and self._dbus_handler._bus):
                        logger.warning("Watchdog: D-Bus not connected")
                        healthy = False

                # Verify listener is running
                if healthy and self.listener:
                    try:
                        stats = self.listener.stats
                        if not stats:
                            logger.warning("Watchdog: Listener not responding")
                            healthy = False
                    except Exception as e:
                        logger.warning(f"Watchdog: Listener check failed: {e}")
                        healthy = False

                if healthy:
                    sd_notify("WATCHDOG=1")
                else:
                    logger.warning("Watchdog: Health check failed, not sending ping")

            except Exception as e:
                logger.error(f"Watchdog loop error: {e}")

            # Wait for next interval
            await asyncio.sleep(interval)

    async def _main_loop(self):
        """Main processing loop."""
        loop_count = 0
        last_poll_count = 0
        while self._running:
            try:
                loop_count += 1
                stats = self.listener.stats

                # Debug: print stats every 10 loops
                if loop_count % 10 == 1:
                    logger.debug(
                        f"Loop {loop_count}: polls={stats.get('polls', 0)}, seen={stats.get('messages_seen', 0)}"
                    )

                # Update status display
                self.ui.print_status(stats)

                # Track successful polls for health monitoring
                current_poll_count = stats.get("polls", 0)
                if self._dbus_handler and current_poll_count > last_poll_count:
                    self._dbus_handler.record_successful_poll()
                    last_poll_count = current_poll_count

                # Check for pending messages
                pending = await self.state_db.get_pending_messages(limit=10)

                for msg in pending:
                    await self._process_message(msg)

                # Wait before next check
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.ui.print_error(str(e))
                # Track failures for health monitoring
                if self._dbus_handler:
                    self._dbus_handler.record_api_failure()
                await asyncio.sleep(5)

    async def _handle_alert_message(self, msg: PendingMessage, alert_info: Any):
        """
        Handle a Prometheus alert message by running the investigate_slack_alert skill.

        This method:
        1. Immediately acknowledges the alert in the thread
        2. Invokes Claude to run the investigation skill
        3. The skill will reply with findings and Jira link
        """
        try:
            # Ensure alert_info is a dict
            if not isinstance(alert_info, dict):
                logger.warning(f"alert_info is {type(alert_info)}, converting to dict. Content: {alert_info}")
                if isinstance(alert_info, str):
                    alert_info = {"environment": alert_info}
                else:
                    alert_info = {}

            env = alert_info.get("environment", "unknown")
            namespace = alert_info.get("namespace", "tower-analytics-stage")

            self.ui.print_info(f"🚨 Alert detected in {env} ({namespace})")

            # DEBUG MODE: Redirect alert responses to self-DM
            if self.debug_mode and self.debug_redirect_channel:
                reply_channel = self.debug_redirect_channel
                reply_thread_ts = None  # No threading in debug DMs
                debug_prefix = (
                    f"🐛 *DEBUG MODE* - Alert response (would go to #{msg.channel_name})\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                )
                self.ui.print_info(f"🐛 DEBUG: Alert response will go to self-DM")
            else:
                reply_channel = msg.channel_id
                reply_thread_ts = msg.timestamp
                debug_prefix = ""

            # Build context for Claude to run the skill
            alert_context = f"""
This is a Prometheus alert from the {env} environment that needs investigation AND a reply.

**Channel:** {msg.channel_id}
**Message TS:** {msg.timestamp}
**Namespace:** {namespace}

**Alert Message:**
{msg.text[:2000]}

IMPORTANT: After investigating, you MUST use `slack_send_message` to reply:
- channel_id: "{reply_channel}"
- thread_ts: {f'"{reply_thread_ts}"' if reply_thread_ts else 'null (no threading)'}
- text: {f'"{debug_prefix}" + ' if debug_prefix else ''}(your investigation summary)

Steps:
1. Check pod status with k8s_get_pods
2. Check events with k8s_get_events
3. Get logs if pods are unhealthy
4. Search for existing Jira issues
5. **REPLY using slack_send_message with your findings** (REQUIRED!)

Do NOT just describe what you found - you MUST call slack_send_message to actually reply to Slack!
"""

            # Use Claude to handle the investigation
            if self.response_generator.claude_agent:
                logger.info(f"Invoking Claude for alert investigation in #{msg.channel_id} (ts: {msg.timestamp})")
                # Use thread_ts for alert conversation tracking
                alert_conversation_id = f"{msg.channel_id}:{msg.timestamp}"
                response = await self.response_generator.claude_agent.process_message(
                    alert_context,
                    context={
                        "is_alert": True,
                        "environment": env,
                        "namespace": namespace,
                        "channel_id": msg.channel_id,
                        "message_ts": msg.timestamp,
                    },
                    conversation_id=alert_conversation_id,
                )

                if response:
                    logger.info(f"Claude alert investigation response: {response[:200]}...")
                    self.ui.print_info("✅ Alert investigation complete")
                else:
                    logger.warning(f"Claude alert investigation returned no response for alert in {msg.channel_id}")
                    self.ui.print_info("⚠️ Alert investigation returned no response")
            else:
                # Fallback: just acknowledge the alert
                logger.warning("Claude agent not available for alert investigation")

        except Exception as e:
            logger.error(f"Error handling alert: {e}")
            self.ui.print_error(f"Alert handling failed: {e}")

    async def _process_message(self, msg: PendingMessage):
        """Process a single pending message."""
        # Classify user
        classification = self.user_classifier.classify(msg.user_id, msg.user_name)

        # ==================== ALERT DETECTION ====================
        # Check if this is a Prometheus alert that should be auto-investigated
        if self.alert_detector.is_alert_message(msg.channel_id, msg.user_name, msg.text, msg.raw_message):
            alert_info = self.alert_detector.get_alert_info(msg.channel_id)

            # CRITICAL: Always ensure alert_info is a dict
            if not isinstance(alert_info, dict):
                logger.error(f"alert_info is not a dict! type={type(alert_info)}, content={alert_info}")
                alert_info = {
                    "environment": "unknown",
                    "namespace": "tower-analytics-stage",
                    "severity": "medium",
                    "auto_investigate": False,
                }

            if self.alert_detector.should_auto_investigate(msg.channel_id):
                logger.info(f"🚨 Alert detected in {alert_info.get('environment', 'unknown')}: auto-investigating")
                await self._handle_alert_message(msg, alert_info)
                await self.state_db.mark_message_processed(msg.id)
                return
            else:
                logger.debug(f"Alert detected but auto-investigate disabled for channel {msg.channel_id}")

        # ==================== @ME COMMAND DETECTION ====================
        # Check if this is an @me command (before normal processing)
        self_dm_channel = get_slack_config("listener.self_dm_channel", "")
        is_self_dm = msg.channel_id == self_dm_channel

        if self.command_handler and self.command_handler.is_command(msg.text, is_self_dm):
            logger.info(f"@me command detected: {msg.text[:50]}")
            self.ui.print_message(msg, "@me command", classification, channel_allowed=True)
            self.ui.messages_processed += 1

            # Handle the command
            response, should_send = await self.command_handler.handle(msg, classification)

            if response:
                # Send the response
                await self._send_response_or_skip(msg, response, classification, should_send)

            await self.state_db.mark_message_processed(msg.id)
            return

        # ==================== NORMAL MESSAGE PROCESSING ====================

        # Check response rules - should we respond to this message?
        can_respond, permission_reason = self.channel_permissions.should_respond(
            channel_id=msg.channel_id,
            message_text=msg.text,
            is_dm=msg.is_dm,
            is_mention=msg.is_mention,
            mentioned_users=getattr(msg, "mentioned_users", []),
            mentioned_groups=getattr(msg, "mentioned_groups", []),
        )

        # Note: Intent detection removed - Claude handles all understanding
        self.ui.print_message(msg, "claude", classification, channel_allowed=can_respond)
        self.ui.messages_processed += 1

        # Desktop notification - message received (with deduplication to prevent spam on restart)
        # Check if we already notified about this message (survives daemon restarts)
        already_notified = await self.state_db.was_notified(msg.timestamp)
        if not already_notified:
            self.notifier.message_received(
                user_name=msg.user_name,
                channel_name=msg.channel_name,
                text=msg.text,
                classification=classification.category.value,
            )
            # Mark as notified so we don't spam on restart
            await self.state_db.mark_notified(msg.timestamp, msg.channel_id)

            # Emit toast notification for IDE
            try:
                from tool_modules.aa_workflow.src.notification_emitter import notify_slack_message

                notify_slack_message(msg.channel_name, msg.user_name, msg.text[:100])
            except Exception:
                pass
        else:
            logger.debug(f"Skipping notification for {msg.timestamp} - already notified")

        # Generate response using Claude (handles intent, tool calls, everything)
        response, should_send = await self.response_generator.generate(msg, classification)

        # If response is None (error occurred), silently skip - don't respond at all
        if response is None:
            logger.debug(f"No response generated for message {msg.id} - silently skipping")
            await self.state_db.mark_message_processed(msg.id)
            return

        # Update D-Bus handler stats
        if self._dbus_handler:
            self._dbus_handler.messages_processed = self.ui.messages_processed
            self._dbus_handler.session = self.session

        # Handle concerned users - queue for review instead of auto-sending
        if classification.require_review and not self.dry_run:
            await self._handle_concerned_user_review(msg, response, classification)
            return

        # Check channel permissions before sending (already computed above)
        if not can_respond:
            print(f"   {self.ui.COLORS['yellow']}🚫 NOT RESPONDING: {permission_reason}{self.ui.COLORS['reset']}")
            # Desktop notification - ignored
            self.notifier.message_ignored(
                user_name=msg.user_name,
                channel_name=msg.channel_name,
                reason=permission_reason,
            )
            # Record skipped message
            await self._record_dbus_skipped(msg, classification)

            # Still mark as processed
            await self.state_db.mark_message_processed(msg.id)
            return

        # Send response (unless dry run or auto_respond is False)
        await self._send_response_or_skip(msg, response, classification, should_send)

    async def _handle_concerned_user_review(
        self, msg: PendingMessage, response: str, classification: UserClassification
    ):
        """Handle message requiring concerned user review."""
        # Enforce max pending reviews to prevent unbounded memory growth
        if len(self._pending_reviews) >= self._max_pending_reviews:
            # Remove oldest review
            self._pending_reviews.pop(0)
            logger.warning(f"Pending reviews exceeded limit ({self._max_pending_reviews}), removed oldest")

        self._pending_reviews.append(
            {
                "message": msg,
                "response": response,
                "classification": classification,
                "intent": "claude",
            }
        )
        print(f"   {self.ui.COLORS['yellow']}⏸️  QUEUED FOR REVIEW (concerned user){self.ui.COLORS['reset']}")
        print(f"   Pending reviews: {len(self._pending_reviews)}")

        # Desktop notification - awaiting approval
        self.notifier.awaiting_approval(
            user_name=msg.user_name,
            channel_name=msg.channel_name,
            text=msg.text,
            pending_count=len(self._pending_reviews),
        )

        # Record pending message in D-Bus history
        if self._dbus_handler:
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
                classification=classification.category.value,
                response=response,
                status="pending",
                created_at=time.time(),
            )
            self._dbus_handler.history.add(record)
            self._dbus_handler.emit_pending_approval(record)

            # Emit toast notification for pending approval
            try:
                from tool_modules.aa_workflow.src.notification_emitter import notify_slack_pending_approval

                notify_slack_pending_approval(msg.channel_name, msg.user_name, msg.text[:50])
            except Exception:
                pass

        # Optionally notify about concerned user message
        await self._notify_concerned_message(msg, response)

        # Still mark as processed (we've handled it, just not sent yet)
        await self.state_db.mark_message_processed(msg.id)

    async def _record_dbus_skipped(self, msg: PendingMessage, classification: UserClassification):
        """Record a skipped message in D-Bus history."""
        if self._dbus_handler:
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
                classification=classification.category.value,
                response="",
                status="skipped",
                created_at=time.time(),
                processed_at=time.time(),
            )
            self._dbus_handler.history.add(record)

    async def _send_response_or_skip(
        self,
        msg: PendingMessage,
        response: str,
        classification: UserClassification,
        should_send: bool,
    ):
        """Send response or record as skipped."""
        success = True
        status = "sent"
        if not self.dry_run and should_send:
            # Desktop notification - responding
            self.notifier.responding(
                user_name=msg.user_name,
                channel_name=msg.channel_name,
                intent="claude",
            )
            try:
                # DEBUG MODE: Redirect all messages to self-DM instead of original recipient
                if self.debug_mode and self.debug_redirect_channel:
                    target_channel = self.debug_redirect_channel
                    # Add debug header to show where the message would have gone
                    debug_header = (
                        f"🐛 *DEBUG MODE* - Would have sent to #{msg.channel_name} "
                        f"(reply to {msg.user_name})\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    )
                    response = debug_header + response
                    thread_ts = None  # No threading in debug DMs
                    print(f"   {self.ui.COLORS['magenta']}🐛 DEBUG: Redirecting to self-DM{self.ui.COLORS['reset']}")
                else:
                    target_channel = msg.channel_id
                    # In DMs (channel starts with D), don't use threading
                    # In channels, reply in thread to keep things organized
                    is_dm = msg.channel_id.startswith("D")
                    thread_ts = None if is_dm else (msg.thread_ts or msg.timestamp)

                sent_msg = await self.session.send_message(
                    channel_id=target_channel,
                    text=response,
                    thread_ts=thread_ts,
                    typing_delay=True,
                )
                # Update last_processed_ts to our sent message so we don't respond to ourselves
                if sent_msg and "ts" in sent_msg:
                    await self.state_db.set_last_processed_ts(msg.channel_id, sent_msg["ts"], msg.channel_name)
                self.ui.messages_responded += 1
                if self._dbus_handler:
                    self._dbus_handler.messages_responded = self.ui.messages_responded
                # Desktop notification - response sent
                self.notifier.response_sent(
                    user_name=msg.user_name,
                    channel_name=msg.channel_name,
                )
            except Exception as e:
                success = False
                status = "failed"
                self.ui.print_error(f"Failed to send: {e}")
                self.notifier.error(f"Failed to send: {e}")
        elif not should_send:
            status = "skipped"
            print(f"   {self.ui.COLORS['dim']}(auto_respond disabled){self.ui.COLORS['reset']}")

        self.ui.print_response(response, success)

        # Record sent message in D-Bus history
        if self._dbus_handler:
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
                classification=classification.category.value,
                response=response,
                status=status,
                created_at=time.time(),
                processed_at=time.time(),
            )
            self._dbus_handler.history.add(record)
            self._dbus_handler.emit_message_processed(msg.id, status)

        # Mark as processed
        await self.state_db.mark_message_processed(msg.id)

    async def _notify_concerned_message(self, msg: PendingMessage, response: str):
        """Notify when a concerned user sends a message."""
        notifications = SLACK_CONFIG.get("notifications", {})
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
                await self.session.send_message(
                    channel_id=notify_channel,
                    text=notification,
                    typing_delay=False,
                )
            elif notify_user:
                # DM the user
                await self.session.send_message(
                    channel_id=notify_user,
                    text=notification,
                    typing_delay=False,
                )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Slack daemon shutting down...")

        self._running = False

        # Desktop notification
        self.notifier.stopped()

        # Stop background sync
        await self._stop_background_sync()

        # Stop sleep/wake monitor
        if self._sleep_monitor:
            try:
                await asyncio.wait_for(self._sleep_monitor.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Sleep monitor stop timed out")

        # D-Bus is stopped by super().shutdown() via stop_dbus() override

        if self.listener:
            await self.listener.stop()

        if self.session:
            await self.session.close()

        if self.state_db:
            await self.state_db.close()

        # Get final listener stats for shutdown summary
        listener_stats = self.listener.stats if self.listener else {}
        self.ui.print_shutdown(listener_stats)

        await super().shutdown()
        logger.info("Slack daemon stopped")

    async def _init_slack_auth(self) -> bool:
        """Initialize Slack session with automatic credential refresh on failure."""
        from src.slack_client import SlackSession

        auth_success = False
        for attempt in range(2):  # Try twice: once with current creds, once after refresh
            try:
                xoxc_token = get_slack_config("auth.xoxc_token", "", "SLACK_XOXC_TOKEN")
                d_cookie = get_slack_config("auth.d_cookie", "", "SLACK_D_COOKIE")
                workspace_id = get_slack_config("auth.workspace_id", "", "SLACK_WORKSPACE_ID")

                if not xoxc_token or not d_cookie:
                    if attempt == 0:
                        print("⚠️  Missing Slack credentials, attempting to refresh from Chrome...")
                        if refresh_slack_credentials():
                            continue  # Retry with refreshed credentials
                    self.ui.print_error(
                        "Missing Slack credentials. Set in config.json or environment:\n"
                        "  SLACK_XOXC_TOKEN and SLACK_D_COOKIE\n"
                        "Or run: python scripts/get_slack_creds.py"
                    )
                    return False

                self.session = SlackSession(
                    xoxc_token=xoxc_token,
                    d_cookie=d_cookie,
                    workspace_id=workspace_id,
                )
                auth = await self.session.validate_session()
                print(f"✅ Authenticated as: {auth.get('user', 'unknown')}")
                auth_success = True

                # Update D-Bus handler with session
                if self._dbus_handler:
                    self._dbus_handler.session = self.session
                break

            except Exception as e:
                if attempt == 0:
                    print(f"⚠️  Authentication failed: {e}")
                    print("   Attempting to refresh credentials from Chrome...")
                    if refresh_slack_credentials():
                        continue  # Retry with refreshed credentials
                self.ui.print_error(
                    f"Slack authentication failed after retry: {e}\n" "Try running: python scripts/get_slack_creds.py"
                )
                return False

        if not auth_success:
            self.ui.print_error("Failed to authenticate with Slack")
            return False

        return True

    async def _init_listener_config(self):
        """Initialize listener configuration from config.json."""
        from src.listener import ListenerConfig

        watched_channels = get_slack_config("listener.watched_channels", [])
        if isinstance(watched_channels, str):
            watched_channels = [c.strip() for c in watched_channels.split(",") if c.strip()]

        # Auto-discover DMs and MPDMs (private group chats)
        auto_watch_dms = get_slack_config("listener.auto_watch_dms", True)
        if auto_watch_dms and self.session:
            discovered = await self._discover_dm_channels()
            # Add discovered channels that aren't already in the list
            existing = set(watched_channels)
            for channel_id in discovered:
                if channel_id not in existing:
                    watched_channels.append(channel_id)

        watched_keywords = get_slack_config("listener.watched_keywords", [])
        if isinstance(watched_keywords, str):
            watched_keywords = [k.strip().lower() for k in watched_keywords.split(",") if k.strip()]

        self_user_id = get_slack_config("listener.self_user_id", "", "SLACK_SELF_USER_ID")
        poll_interval_min = get_slack_config("listener.poll_interval_min", 5.0)
        poll_interval_max = get_slack_config("listener.poll_interval_max", 15.0)

        # Allow command line to override
        if self.poll_interval_min != 5.0:
            poll_interval_min = self.poll_interval_min
        if self.poll_interval_max != 15.0:
            poll_interval_max = self.poll_interval_max

        # Self-DM channel for testing (messages from self in this channel are processed)
        self_dm_channel = get_slack_config("listener.self_dm_channel", "", "SLACK_SELF_DM_CHANNEL")

        # Alert channels (for auto-investigate - all messages in these channels are processed)
        alert_channels = get_slack_config("listener.alert_channels", {})

        return ListenerConfig(
            poll_interval_min=poll_interval_min,
            poll_interval_max=poll_interval_max,
            watched_channels=watched_channels,
            watched_keywords=watched_keywords,
            self_user_id=self_user_id,
            self_dm_channel=self_dm_channel,
            alert_channels=alert_channels,
        )

    async def _discover_dm_channels(self) -> list[str]:
        """Discover all DMs and MPDMs (private group chats) the user is in.

        Uses client.counts API which returns all DMs/MPDMs with unread counts.
        This works on enterprise Slack where other APIs are blocked.

        Returns list of channel IDs for:
        - D*: Direct messages (1:1 DMs)
        - C* (mpim): Multi-person direct messages (group DMs / private chats)
        """
        discovered = []

        # Method 1: Try client.counts API (works on enterprise Slack!)
        try:
            result = await self.session.get_client_counts()
            if result.get("ok"):
                # Get DMs from 'ims' array
                for im in result.get("ims", []):
                    channel_id = im.get("id")
                    if channel_id and channel_id not in discovered:
                        discovered.append(channel_id)

                # Get MPDMs from 'mpims' array
                for mpim in result.get("mpims", []):
                    channel_id = mpim.get("id")
                    if channel_id and channel_id not in discovered:
                        discovered.append(channel_id)

                if discovered:
                    dm_count = sum(1 for c in discovered if c.startswith("D"))
                    mpdm_count = len(discovered) - dm_count
                    logger.info(
                        f"Discovered {len(discovered)} DMs via client.counts ({dm_count} DMs, {mpdm_count} MPDMs)"
                    )
                    return discovered
        except Exception as e:
            logger.debug(f"client.counts failed: {e}")

        # Method 2: Try channel sections API (sidebar) as fallback
        try:
            result = await self.session.get_channel_sections()
            if result.get("ok"):
                for section in result.get("channel_sections", []):
                    for channel_id in section.get("channel_ids_page", {}).get("channel_ids", []):
                        if (channel_id.startswith("D") or channel_id.startswith("G")) and channel_id not in discovered:
                            discovered.append(channel_id)
                if discovered:
                    dm_count = sum(1 for c in discovered if c.startswith("D"))
                    mpdm_count = sum(1 for c in discovered if c.startswith("G"))
                    logger.info(f"Discovered {len(discovered)} DMs from sidebar ({dm_count} DMs, {mpdm_count} MPDMs)")
                    return discovered
        except Exception:
            pass

        # Method 3: Try conversations.list API (usually blocked on enterprise)
        try:
            conversations = await self.session.get_conversations_list(types="im,mpim", limit=200)
            for conv in conversations:
                channel_id = conv.get("id")
                if channel_id and not conv.get("is_archived") and channel_id not in discovered:
                    discovered.append(channel_id)
            if discovered:
                dm_count = sum(1 for c in discovered if c.startswith("D"))
                mpdm_count = sum(1 for c in discovered if c.startswith("G"))
                logger.info(f"Discovered {len(discovered)} DMs ({dm_count} DMs, {mpdm_count} MPDMs)")
        except Exception as e:
            if "enterprise_is_restricted" in str(e):
                logger.info("DM auto-discovery blocked - use @me watch to get channel IDs")

        return discovered

    def _print_startup_status(self, config):
        """Print startup status summary."""
        # Count channel types
        dm_count = sum(1 for c in config.watched_channels if c.startswith("D"))
        mpdm_count = sum(1 for c in config.watched_channels if c.startswith("G"))
        channel_count = len(config.watched_channels) - dm_count - mpdm_count

        print(f"✅ Watching {len(config.watched_channels)} conversations:")
        print(f"   • {channel_count} channels, {dm_count} DMs, {mpdm_count} group DMs (MPDMs)")
        print(f"✅ Keywords: {', '.join(config.watched_keywords) or 'none'}")
        if config.self_dm_channel:
            print(f"✅ Self-DM testing enabled: {config.self_dm_channel}")

        # Show alert channels
        alert_channels = self.alert_detector.alert_channels
        if alert_channels:
            print(f"🚨 Alert channels: {len(alert_channels)} (auto-investigate enabled)")
            for _channel_id, info in alert_channels.items():
                env = info.get("environment", "unknown")
                ns = info.get("namespace", "unknown")
                auto = "✓" if info.get("auto_investigate") else "✗"
                print(f"   • {env}: {ns} [{auto}]")

        # Show user classification summary
        safe_count = len(self.user_classifier.safe_user_ids) + len(self.user_classifier.safe_user_names)
        concerned_count = len(self.user_classifier.concerned_user_ids) + len(self.user_classifier.concerned_user_names)
        print(f"✅ User lists: {safe_count} safe, {concerned_count} concerned")

        # Show response rules
        rules = self.channel_permissions
        print("✅ Response rules:")
        if rules.dm_enabled:
            print("   • DMs: Always respond")
        else:
            print("   • DMs: Disabled")

        if rules.mention_enabled:
            triggers = list(rules.trigger_mentions)[:3]
            trigger_str = ", ".join(triggers) if triggers else "(bot mention)"
            print(f"   • Channels: Only when mentioned ({trigger_str})")
        else:
            print("   • Channels: All messages")

        if rules.blocked_channels:
            print(f"   • Blocked: {len(rules.blocked_channels)} channels")

        # Show notification status
        if self.notifier.enabled:
            print("✅ Desktop notifications: enabled (libnotify)")
        else:
            print("⚠️  Desktop notifications: disabled (install PyGObject)")

        # Show Claude agent status (required for operation)
        agent = self.response_generator.claude_agent
        model = agent.model
        if agent.use_vertex:
            print(f"🧠 Claude Agent: Vertex AI ({model})")
        else:
            print(f"🧠 Claude Agent: Direct API ({model})")

        if self.dry_run:
            print("⚠️  DRY RUN MODE - no responses will be sent")

        if self.debug_mode:
            if self.debug_redirect_channel:
                print(f"🐛 DEBUG MODE - all responses redirected to self-DM ({self.debug_redirect_channel})")
            else:
                print("⚠️  DEBUG MODE enabled but no self_dm_channel configured in config.json!")
                print("   Set slack.listener.self_dm_channel to your DM channel ID")

        print()

    def setup_signal_handlers(self, loop=None):
        """Set up signal handlers for graceful shutdown.

        Args:
            loop: The asyncio event loop. If None, uses get_running_loop().
        """
        if loop is None:
            loop = asyncio.get_running_loop()

        def signal_handler():
            self._running = False
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)


if __name__ == "__main__":
    SlackDaemon.main()
