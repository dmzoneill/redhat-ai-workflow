#!/usr/bin/env python3
"""
Autonomous Slack Agent Daemon

A standalone process that monitors Slack and responds using Claude + MCP tools.
The daemon is just a Slack interface - all intelligence goes through ClaudeAgent,
which routes to MCP servers (aa-jira, aa-gitlab, aa-k8s, aa-bonfire, etc.)

Requirements:
- Claude API credentials (ANTHROPIC_API_KEY or Vertex AI)
- Slack credentials (config.json or environment variables)

Features:
- Continuous Slack monitoring with configurable poll interval
- Claude-powered message understanding and tool execution
- User classification (safe/concerned/unknown) for response modulation
- Rich terminal UI with status display
- Graceful shutdown handling

Usage:
    python scripts/slack_daemon.py                    # Run with Claude
    python scripts/slack_daemon.py --dry-run          # Process but don't respond
    python scripts/slack_daemon.py --verbose          # Detailed logging

Configuration:
    All settings are read from config.json under the "slack" key.
    Environment variables can override config.json values.
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# Add project paths (use resolve() to get absolute paths)
# NOTE: aa-common provides shared utils (src.utils), must be before servers that import from it
# aa-slack must come LAST in inserts so it's FIRST in sys.path
# (because insert(0, x) prepends, so last insert = first in list)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-common"))  # Shared utils first
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-git"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-gitlab"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-jira"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-servers" / "aa-slack"))  # Must be first in path

from dotenv import load_dotenv

# Desktop notifications (optional)
try:
    import gi

    gi.require_version("Notify", "0.7")
    from gi.repository import Notify

    NOTIFY_AVAILABLE = True
    Notify.init("AI Workflow Slack Agent")
except (ImportError, ValueError):
    NOTIFY_AVAILABLE = False

# Single instance lock
import fcntl

LOCK_FILE = Path("/tmp/slack-daemon.lock")
PID_FILE = Path("/tmp/slack-daemon.pid")


class SingleInstance:
    """
    Ensures only one instance of the daemon runs at a time.

    Uses a lock file with fcntl for atomic locking.
    If another instance is running, provides methods to communicate with it.
    """

    def __init__(self):
        self._lock_file = None
        self._acquired = False

    def acquire(self) -> bool:
        """
        Try to acquire the lock.

        Returns True if we got the lock (we're the only instance).
        Returns False if another instance is running.
        """
        try:
            self._lock_file = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write our PID
            PID_FILE.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except OSError:
            # Lock is held by another process
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

        # Clean up files
        try:
            LOCK_FILE.unlink(missing_ok=True)
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        self._acquired = False

    def get_running_pid(self) -> int | None:
        """Get the PID of the running instance, if any."""
        try:
            if PID_FILE.exists():
                pid = int(PID_FILE.read_text().strip())
                # Check if process is actually running
                os.kill(pid, 0)
                return pid
        except (ValueError, OSError):
            pass
        return None

    def is_running(self) -> bool:
        """Check if another instance is running."""
        return self.get_running_pid() is not None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


load_dotenv(PROJECT_ROOT / "mcp-servers" / "aa-slack" / ".env")
load_dotenv()

# Import load_config from aa-common using importlib to avoid module cache conflicts
# (all MCP servers use 'src' as package name, which causes import conflicts)
import importlib.util

_utils_path = PROJECT_ROOT / "mcp-servers" / "aa-common" / "src" / "utils.py"
_spec = importlib.util.spec_from_file_location("aa_common_utils", _utils_path)
_utils_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils_module)
load_config = _utils_module.load_config

from src.listener import ListenerConfig, SlackListener
from src.persistence import PendingMessage, SlackStateDB

# Import Slack components
from src.slack_client import SlackSession

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

    def is_alert_message(self, channel_id: str, user_name: str, text: str) -> bool:
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
        is_from_alert_bot = any(bot in user_lower for bot in self.alert_bot_names)

        # Check for alert indicators in text
        text_lower = (text or "").lower()
        alert_indicators = ["firing", "resolved", "alert:", "alertmanager", "prometheus"]
        has_alert_indicator = any(ind in text_lower for ind in alert_indicators)

        return is_from_alert_bot or (channel_id in self.alert_channels and has_alert_indicator)

    def get_alert_info(self, channel_id: str) -> dict:
        """Get the channel's alert configuration."""
        return self.alert_channels.get(
            channel_id,
            {
                "environment": "unknown",
                "namespace": "tower-analytics-stage",
                "severity": "medium",
                "auto_investigate": False,
            },
        )

    def should_auto_investigate(self, channel_id: str) -> bool:
        """Check if this channel has auto-investigate enabled."""
        info = self.get_alert_info(channel_id)
        return info.get("auto_investigate", False)


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
            for user_id in mentioned_users:
                if user_id in self.trigger_user_ids:
                    return True, f"Trigger user {user_id} mentioned"

            # Check trigger group IDs
            for group_id in mentioned_groups:
                if group_id in self.trigger_group_ids:
                    return True, f"Trigger group {group_id} mentioned"

            # Check trigger mentions in text (e.g., @bitwiseshift)
            text_lower = message_text.lower()
            for mention in self.trigger_mentions:
                if mention.lower() in text_lower:
                    return True, f"Trigger mention '{mention}' found"

        # Rule 3: Keywords (if enabled)
        if self.keyword_enabled:
            text_lower = message_text.lower()
            for keyword in self.trigger_keywords:
                if keyword.lower() in text_lower:
                    return True, f"Trigger keyword '{keyword}' found"

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
    """

    # Notification urgency levels
    URGENCY_LOW = 0
    URGENCY_NORMAL = 1
    URGENCY_CRITICAL = 2

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

    def _send(
        self,
        title: str,
        body: str,
        icon: str = "dialog-information",
        urgency: int = 1,
        timeout: int = 5000,
    ):
        """Send a desktop notification."""
        if not self.enabled:
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
        title = "❌ Slack Agent Error"
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
        title = "🤖 Slack Agent Started"
        body = "Monitoring channels for messages..."
        self._send(title, body, "emblem-default", self.URGENCY_LOW, timeout=3000)

    def stopped(self):
        """Notify when daemon stops."""
        title = "🛑 Slack Agent Stopped"
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

    def print_header(self):
        """Print startup header."""
        cyan = self.COLORS["cyan"]
        bold = self.COLORS["bold"]
        reset = self.COLORS["reset"]
        print(
            f"""
{cyan}╔══════════════════════════════════════════════════════════════════╗
║  {bold}🤖 AI Workflow - Autonomous Slack Agent{reset}{cyan}                          ║
║                                                                    ║
║  Monitoring Slack channels for messages...                         ║
║  Press Ctrl+C to stop                                              ║
╚══════════════════════════════════════════════════════════════════╝{reset}
"""
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
# which routes to MCP servers (aa-jira, aa-gitlab, aa-k8s, aa-bonfire, etc.)
#
# The Slack daemon is just a Slack interface - all intelligence is in Claude.
# =============================================================================


# =============================================================================
# RESPONSE GENERATOR
# =============================================================================


# Try to import Claude agent
try:
    from claude_agent import ANTHROPIC_AVAILABLE, ClaudeAgent
except ImportError:
    ANTHROPIC_AVAILABLE = False
    ClaudeAgent = None


class ResponseGenerator:
    """
    Generates responses for messages using Claude.

    All message understanding and tool execution goes through ClaudeAgent,
    which routes to MCP servers (aa-jira, aa-gitlab, aa-k8s, etc.)

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
            logger.error("anthropic package not installed. Install with: pip install anthropic")
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
        - Calls appropriate MCP tools (aa-jira, aa-gitlab, aa-k8s, etc.)
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


class SlackDaemon:
    """
    Main autonomous Slack agent daemon.

    All message understanding and tool execution goes through ClaudeAgent.
    The daemon is just a Slack interface - all intelligence is in Claude.
    """

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        poll_interval_min: float = 5.0,
        poll_interval_max: float = 15.0,
        enable_dbus: bool = False,
        enable_notify: bool = True,
    ):
        self.dry_run = dry_run
        self.verbose = verbose
        self.poll_interval_min = poll_interval_min
        self.poll_interval_max = poll_interval_max
        self.enable_dbus = enable_dbus
        self.enable_notify = enable_notify

        self.ui = TerminalUI(verbose=verbose)
        self.notifier = DesktopNotifier(enabled=enable_notify)

        # Initialize Claude-based response generator (REQUIRED)
        # Will raise RuntimeError if Claude is not available
        self.response_generator = ResponseGenerator(notifier=self.notifier)

        self.user_classifier = UserClassifier()
        self.channel_permissions = ChannelPermissions()
        self.alert_detector = AlertDetector()

        self.session: SlackSession | None = None
        self.state_db: SlackStateDB | None = None
        self.listener: SlackListener | None = None

        self._running = False
        self._shutdown_event = asyncio.Event()
        self._pending_reviews: list[dict] = []  # Messages awaiting review
        self._start_time: float | None = None

        # D-Bus support
        self._dbus_handler = None
        if enable_dbus:
            try:
                from slack_dbus import MessageHistory, SlackDaemonWithDBus

                self._dbus_handler = SlackDaemonWithDBus()
                self._dbus_handler.history = MessageHistory()
                logger.info("D-Bus support enabled")
            except ImportError as e:
                logger.warning(f"D-Bus not available: {e}")

    async def start(self):
        """Initialize and start the daemon."""
        self.ui.print_header()
        self._start_time = time.time()

        # Initialize D-Bus if enabled
        if self._dbus_handler:
            await self._dbus_handler.start_dbus()
            self._dbus_handler.is_running = True
            self._dbus_handler.start_time = self._start_time
            print("✅ D-Bus IPC enabled (com.aiworkflow.SlackAgent)")

        # Initialize Slack session (config.json with env override)
        # With automatic credential refresh on failure
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
                    return

                self.session = SlackSession(
                    xoxc_token=xoxc_token,
                    d_cookie=d_cookie,
                    workspace_id=workspace_id,
                )
                auth = await self.session.validate_session()
                print(f"✅ Authenticated as: {auth.get('user', 'unknown')}")
                auth_success = True
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
                return

        if not auth_success:
            self.ui.print_error("Failed to authenticate with Slack")
            return

        # Initialize state database
        db_path = get_slack_config("state_db_path", "./slack_state.db")
        self.state_db = SlackStateDB(db_path)
        await self.state_db.connect()
        print("✅ State database connected")

        # Initialize listener with config.json settings
        watched_channels = get_slack_config("listener.watched_channels", [])
        if isinstance(watched_channels, str):
            watched_channels = [c.strip() for c in watched_channels.split(",") if c.strip()]

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

        config = ListenerConfig(
            poll_interval_min=poll_interval_min,
            poll_interval_max=poll_interval_max,
            watched_channels=watched_channels,
            watched_keywords=watched_keywords,
            self_user_id=self_user_id,
            self_dm_channel=self_dm_channel,
            alert_channels=alert_channels,
        )

        self.listener = SlackListener(self.session, self.state_db, config)

        print(f"✅ Watching {len(config.watched_channels)} channels")
        print(f"✅ Keywords: {', '.join(config.watched_keywords) or 'none'}")
        if self_dm_channel:
            print(f"✅ Self-DM testing enabled: {self_dm_channel}")

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

        print()

        # Start listener
        await self.listener.start()
        self._running = True

        # Desktop notification
        self.notifier.started()

        # Main processing loop
        await self._main_loop()

    async def _main_loop(self):
        """Main processing loop."""
        loop_count = 0
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
                await asyncio.sleep(5)

    async def _handle_alert_message(self, msg: PendingMessage, alert_info: dict):
        """
        Handle a Prometheus alert message by running the investigate_slack_alert skill.

        This method:
        1. Immediately acknowledges the alert in the thread
        2. Invokes Claude to run the investigation skill
        3. The skill will reply with findings and Jira link
        """
        try:
            env = alert_info.get("environment", "unknown")
            namespace = alert_info.get("namespace", "unknown")

            self.ui.print_status(f"🚨 Alert detected in {env} ({namespace})")

            # Build context for Claude to run the skill
            alert_context = f"""
This is a Prometheus alert from the {env} environment that needs investigation.

**Channel:** {msg.channel_id}
**Message TS:** {msg.ts}
**Namespace:** {namespace}

**Alert Message:**
{msg.text[:2000]}

Please run the `investigate_slack_alert` skill with these inputs:
- channel_id: "{msg.channel_id}"
- message_ts: "{msg.ts}"
- message_text: (the alert message above)

The skill will:
1. Reply to acknowledge we're looking into it
2. Check pod status and logs
3. Search for or create a Jira issue
4. Reply with findings
"""

            # Use Claude to handle the investigation
            if self.response_generator.claude_agent:
                # Use thread_ts for alert conversation tracking
                alert_conversation_id = f"{msg.channel_id}:{msg.ts}"
                response = await self.response_generator.claude_agent.process_message(
                    alert_context,
                    context={
                        "is_alert": True,
                        "environment": env,
                        "namespace": namespace,
                        "channel_id": msg.channel_id,
                        "message_ts": msg.ts,
                    },
                    conversation_id=alert_conversation_id,
                )

                if response:
                    self.ui.print_status("✅ Alert investigation complete")
                else:
                    self.ui.print_status("⚠️ Alert investigation returned no response")
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
        if self.alert_detector.is_alert_message(msg.channel_id, msg.user_name, msg.text):
            alert_info = self.alert_detector.get_alert_info(msg.channel_id)

            if self.alert_detector.should_auto_investigate(msg.channel_id):
                logger.info(f"🚨 Alert detected in {alert_info.get('environment', 'unknown')}: auto-investigating")
                await self._handle_alert_message(msg, alert_info)
                await self.state_db.mark_message_processed(msg.id)
                return
            else:
                logger.debug(f"Alert detected but auto-investigate disabled for channel {msg.channel_id}")

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

        # Desktop notification - message received
        self.notifier.message_received(
            user_name=msg.user_name,
            channel_name=msg.channel_name,
            text=msg.text,
            classification=classification.category.value,
        )

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
                from slack_dbus import MessageRecord

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

            # Optionally notify about concerned user message
            await self._notify_concerned_message(msg, response)

            # Still mark as processed (we've handled it, just not sent yet)
            await self.state_db.mark_message_processed(msg.id)
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
            if self._dbus_handler:
                from slack_dbus import MessageRecord

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

            # Still mark as processed
            await self.state_db.mark_message_processed(msg.id)
            return

        # Send response (unless dry run or auto_respond is False)
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
                # In DMs (channel starts with D), don't use threading
                # In channels, reply in thread to keep things organized
                is_dm = msg.channel_id.startswith("D")
                thread_ts = None if is_dm else (msg.thread_ts or msg.timestamp)
                sent_msg = await self.session.send_message(
                    channel_id=msg.channel_id,
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
            from slack_dbus import MessageRecord

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

    async def stop(self):
        """Stop the daemon gracefully."""
        self._running = False

        # Desktop notification
        self.notifier.stopped()

        if self._dbus_handler:
            self._dbus_handler.is_running = False
            await self._dbus_handler.stop_dbus()

        if self.listener:
            await self.listener.stop()

        if self.session:
            await self.session.close()

        if self.state_db:
            await self.state_db.close()

        # Get final listener stats for shutdown summary
        listener_stats = self.listener.stats if self.listener else {}
        self.ui.print_shutdown(listener_stats)

    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            self._running = False
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous Slack Agent Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Interaction Methods:
  1. Direct CLI:     python slack_daemon.py [options]
  2. Makefile:       make slack-daemon | make slack-daemon-bg
  3. D-Bus Control:  make slack-status | make slack-pending | make slack-approve ID=xxx
  4. MCP Skill:      skill_run("slack_daemon_control", '{"action": "status"}')

Single Instance:
  Only one daemon can run at a time (uses lock file).
  If already running, commands are redirected to the existing instance via D-Bus.
""",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process messages but don't send responses",
    )
    # NOTE: --llm flag removed - Claude is now REQUIRED for operation
    # The Slack daemon is just a Slack interface; all intelligence is in Claude
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--poll-min",
        type=float,
        default=5.0,
        help="Minimum polling interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--poll-max",
        type=float,
        default=15.0,
        help="Maximum polling interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--dbus",
        action="store_true",
        help="Enable D-Bus IPC interface",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable desktop notifications",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status of running daemon and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop running daemon and exit",
    )

    args = parser.parse_args()

    # Check for single-instance commands first
    instance = SingleInstance()

    # Handle --status: just check if running
    if args.status:
        pid = instance.get_running_pid()
        if pid:
            print(f"✅ Daemon is running (PID: {pid})")
            print(f"   Lock file: {LOCK_FILE}")
            print(f"   PID file: {PID_FILE}")
            print("\nUse 'make slack-status' for detailed stats via D-Bus")
        else:
            print("❌ Daemon is not running")
        return

    # Handle --stop: signal the running daemon
    if args.stop:
        pid = instance.get_running_pid()
        if pid:
            print(f"Stopping daemon (PID: {pid})...")
            try:
                os.kill(pid, signal.SIGTERM)
                print("✅ Stop signal sent")
            except OSError as e:
                print(f"❌ Failed to stop: {e}")
        else:
            print("❌ Daemon is not running")
        return

    # Try to acquire the lock
    if not instance.acquire():
        existing_pid = instance.get_running_pid()
        print(f"⚠️  Another instance is already running (PID: {existing_pid})")
        print()
        print("To interact with the running daemon:")
        print("  make slack-status        # Get status")
        print("  make slack-pending       # List pending messages")
        print("  make slack-approve-all   # Approve all pending")
        print("  make slack-daemon-stop   # Stop the daemon")
        print()
        print("Or use D-Bus directly:")
        print("  python scripts/slack_control.py status")
        return

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Reduce noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    daemon = SlackDaemon(
        dry_run=args.dry_run,
        verbose=args.verbose,
        poll_interval_min=args.poll_min,
        poll_interval_max=args.poll_max,
        enable_dbus=args.dbus,
        enable_notify=not args.no_notify,
    )

    daemon.setup_signal_handlers()

    try:
        await daemon.start()
    except KeyboardInterrupt:
        pass
    finally:
        await daemon.stop()
        instance.release()
        print("🔓 Lock released")


if __name__ == "__main__":
    asyncio.run(main())
