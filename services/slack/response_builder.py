"""
Response generation and formatting components for the Slack daemon.

Contains:
- DesktopNotifier: Desktop notification dispatch via libnotify
- TerminalUI: Rich terminal output for daemon status
- ResponseGenerator: Claude-powered response generation
"""

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from scripts.common.config_loader import load_config

if TYPE_CHECKING:
    from services.slack.message_processor import UserClassification

logger = logging.getLogger(__name__)

# Desktop notifications (optional)
NOTIFY_AVAILABLE = False
try:
    import gi

    gi.require_version("Notify", "0.7")
    from gi.repository import Notify

    NOTIFY_AVAILABLE = True
    # Only init once (may already be initialized by daemon.py)
    if not Notify.is_initted():
        Notify.init("AI Workflow Slack Persona")
except (ImportError, ValueError):
    pass


def _load_configs():
    """Load current config and slack config."""
    config = load_config()
    return config, config.get("slack", {})


# =============================================================================
# DESKTOP NOTIFICATIONS
# =============================================================================


class DesktopNotifier:
    """
    Desktop notifications using libnotify.

    Shows visual alerts for:
    - Message received
    - Response sent
    - Message ignored (channel not allowed)
    - Awaiting approval (concerned user)

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
        self._notification_times = [
            t for t in self._notification_times if now - t < self.RATE_LIMIT_WINDOW
        ]
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

        urgency = (
            self.URGENCY_CRITICAL
            if classification == "concerned"
            else self.URGENCY_NORMAL
        )
        self._send(title, body, self._icons["received"], urgency)

    def responding(self, user_name: str, channel_name: str, intent: str):
        """Notify when responding to a message."""
        title = "✅ Responding"
        body = f"To {user_name} in #{channel_name}\nIntent: {intent}"
        self._send(
            title, body, self._icons["responding"], self.URGENCY_LOW, timeout=3000
        )

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
        msg: Any,
        intent: str,
        classification: "UserClassification | None" = None,
        channel_allowed: bool = True,
    ):
        """Print incoming message."""
        print(
            f"\n{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}"
        )
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
        print(
            f"{self.COLORS['yellow']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{self.COLORS['reset']}"
        )

    def print_error(self, error: str):
        """Print error message."""
        print(f"\n{self.COLORS['red']}❌ Error: {error}{self.COLORS['reset']}")
        self.errors += 1

    def print_shutdown(self, listener_stats: dict | None = None):
        """Print shutdown message."""
        print(
            f"\n\n{self.COLORS['cyan']}Shutting down gracefully...{self.COLORS['reset']}"
        )
        print(f"   📊 Total processed: {self.messages_processed}")
        print(f"   💬 Total responded: {self.messages_responded}")
        # Combine listener errors with daemon errors
        listener_errors = listener_stats.get("errors", 0) if listener_stats else 0
        total_errors = self.errors + listener_errors
        print(f"   ❌ Total errors: {total_errors}")
        print(f"{self.COLORS['green']}Goodbye! 👋{self.COLORS['reset']}\n")


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
        config, slack_config = _load_configs()
        self.templates = slack_config.get("response_templates", {})
        self._config = config
        self.notifier = notifier or DesktopNotifier(enabled=False)
        self._init_claude()

    def _init_claude(self):
        """Initialize Claude agent - REQUIRED for operation."""
        if not ANTHROPIC_AVAILABLE:
            logger.error(
                "anthropic package not installed. Install with: uv add anthropic"
            )
            raise RuntimeError(
                "Claude agent required but anthropic package not available"
            )

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
            agent_config = self._config.get("agent", {})
            model = agent_config.get("model", "claude-sonnet-4-20250514")
            vertex_model = agent_config.get(
                "vertex_model", "claude-sonnet-4-5@20250929"
            )
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
        classification: "UserClassification",
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
        message: Any,
        classification: "UserClassification",
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

            response = await self.claude_agent.process_message(
                message.text, context, conversation_id=conversation_id
            )
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
