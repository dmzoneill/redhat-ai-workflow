"""
Response Router for Slack @me Commands.

Determines where responses should be sent based on:
- Command type and context
- User preferences (--reply-dm, --reply-thread flags)
- Configuration defaults

Supports:
- Reply in same thread (default)
- Reply via DM
- Reply in channel (not in thread)
- Configurable per-command defaults
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


class ResponseMode(str, Enum):
    """Where to send the response."""

    THREAD = "thread"  # Reply in the same thread
    CHANNEL = "channel"  # Reply in channel (not threaded)
    DM = "dm"  # Reply via direct message
    EPHEMERAL = "ephemeral"  # Ephemeral message (only visible to user)


@dataclass
class ResponseConfig:
    """Configuration for a response."""

    # Where to send
    mode: ResponseMode = ResponseMode.THREAD

    # Target channel/DM
    channel_id: str = ""

    # Thread timestamp (for thread replies)
    thread_ts: str | None = None

    # User ID (for DM/ephemeral)
    user_id: str = ""

    # Additional formatting options
    use_blocks: bool = False
    unfurl_links: bool = False
    unfurl_media: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Slack API."""
        result = {
            "channel": self.channel_id,
        }

        if self.mode == ResponseMode.THREAD and self.thread_ts:
            result["thread_ts"] = self.thread_ts

        if self.unfurl_links is not None:
            result["unfurl_links"] = self.unfurl_links
        if self.unfurl_media is not None:
            result["unfurl_media"] = self.unfurl_media

        return result


@dataclass
class CommandContext:
    """Context for routing a command response."""

    # Original message info
    channel_id: str = ""
    thread_ts: str | None = None
    message_ts: str = ""
    user_id: str = ""

    # Whether this is a DM channel
    is_dm: bool = False

    # User-specified routing
    reply_dm: bool = False
    reply_thread: bool = True

    # Command name (for command-specific defaults)
    command: str = ""


class ResponseRouter:
    """
    Routes responses to appropriate destinations.

    Considers:
    - User-specified flags (--reply-dm, --reply-thread)
    - Command-specific defaults
    - Global configuration
    - Context (thread, DM, etc.)
    """

    # Commands that default to DM responses (sensitive data)
    DM_DEFAULT_COMMANDS = {
        "secrets",
        "credentials",
        "tokens",
        "api_keys",
    }

    # Commands that default to thread responses
    THREAD_DEFAULT_COMMANDS = {
        "create_jira_issue",
        "investigate_alert",
        "review_pr",
        "start_work",
    }

    def __init__(
        self,
        default_mode: ResponseMode = ResponseMode.THREAD,
        config: dict[str, Any] | None = None,
    ):
        """
        Initialize the router.

        Args:
            default_mode: Default response mode
            config: Configuration overrides
        """
        self.default_mode = default_mode
        self.config = config or {}

        # Load config from file if not provided
        if not self.config:
            self._load_config()

    def _load_config(self) -> None:
        """Load configuration using ConfigManager for thread-safe access."""
        try:
            from server.config_manager import config as config_manager

            slack_config = config_manager.get("slack", default={})
            self.config = slack_config.get("commands", {})
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")

    def route(self, context: CommandContext) -> ResponseConfig:
        """
        Determine where to send the response.

        Priority:
        1. User-specified flags (--reply-dm, --reply-thread)
        2. Command-specific defaults
        3. Context-based routing (if in thread, reply in thread)
        4. Global default

        Args:
            context: Command context

        Returns:
            ResponseConfig with routing details
        """
        response = ResponseConfig(
            channel_id=context.channel_id,
            thread_ts=context.thread_ts or context.message_ts,
            user_id=context.user_id,
        )

        # 1. Check user-specified flags
        if context.reply_dm:
            return self._route_to_dm(context, response)

        # 2. Check command-specific defaults
        if context.command in self.DM_DEFAULT_COMMANDS:
            return self._route_to_dm(context, response)

        # 3. Context-based routing
        if context.is_dm:
            # Already in DM, just reply there
            response.mode = ResponseMode.CHANNEL
            return response

        if context.thread_ts:
            # In a thread, reply in thread
            response.mode = ResponseMode.THREAD
            return response

        # 4. Global default
        default = self.config.get("default_response_mode", self.default_mode.value)
        response.mode = ResponseMode(default)

        # If defaulting to thread but no thread, use channel
        if response.mode == ResponseMode.THREAD and not context.thread_ts:
            response.thread_ts = context.message_ts  # Start a thread from the command

        return response

    def _route_to_dm(self, context: CommandContext, response: ResponseConfig) -> ResponseConfig:
        """Route response to DM."""
        response.mode = ResponseMode.DM
        # DM channel will be opened by the sender
        response.channel_id = ""  # Will be set by sender
        response.user_id = context.user_id
        response.thread_ts = None
        return response

    def get_routing_options(self, command: str) -> dict[str, Any]:
        """
        Get available routing options for a command.

        Args:
            command: Command name

        Returns:
            Dict with available options and defaults
        """
        default = ResponseMode.THREAD

        if command in self.DM_DEFAULT_COMMANDS:
            default = ResponseMode.DM
        elif command in self.THREAD_DEFAULT_COMMANDS:
            default = ResponseMode.THREAD

        return {
            "default": default.value,
            "available": [m.value for m in ResponseMode],
            "flags": {
                "--reply-dm": "Send response via DM",
                "--reply-thread": "Reply in thread (default)",
                "--reply-channel": "Reply in channel (not threaded)",
            },
        }


class ResponseFormatter:
    """
    Formats responses for different output modes.

    Handles Slack-specific formatting, truncation, and structure.
    """

    MAX_MESSAGE_LENGTH = 3000  # Slack's limit is 4000, leave buffer
    TRUNCATION_SUFFIX = "\n\n_...response truncated_"

    def __init__(self, use_blocks: bool = False):
        """
        Initialize the formatter.

        Args:
            use_blocks: Whether to use Slack blocks for formatting
        """
        self.use_blocks = use_blocks

    def format(self, text: str, config: ResponseConfig) -> dict[str, Any]:
        """
        Format a response for sending.

        Args:
            text: Response text
            config: Response configuration

        Returns:
            Dict ready for Slack API
        """
        # Truncate if needed
        if len(text) > self.MAX_MESSAGE_LENGTH:
            text = text[: self.MAX_MESSAGE_LENGTH - len(self.TRUNCATION_SUFFIX)]
            text += self.TRUNCATION_SUFFIX

        result = config.to_dict()
        result["text"] = text

        if self.use_blocks:
            result["blocks"] = self._build_blocks(text)

        return result

    def _build_blocks(self, text: str) -> list[dict[str, Any]]:
        """Build Slack blocks from text."""
        blocks = []

        # Split by headers
        sections = text.split("\n## ")

        for i, section in enumerate(sections):
            if i == 0:
                # First section (before any ##)
                if section.strip():
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": section.strip()},
                        }
                    )
            else:
                # Header + content
                lines = section.split("\n", 1)
                header = lines[0].strip()
                content = lines[1].strip() if len(lines) > 1 else ""

                blocks.append({"type": "header", "text": {"type": "plain_text", "text": header}})

                if content:
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": content[:3000]},
                        }
                    )

        return blocks

    def format_error(self, error: str, command: str = "") -> dict[str, Any]:
        """Format an error response."""
        text = "❌ *Error*"
        if command:
            text += f" running `{command}`"
        text += f"\n\n{error}"

        return {"text": text}

    def format_help(self, help_text: str) -> dict[str, Any]:
        """Format a help response."""
        return {"text": help_text, "unfurl_links": False}


# Singleton router instance
_router: ResponseRouter | None = None


def get_router() -> ResponseRouter:
    """Get the global router instance."""
    global _router
    if _router is None:
        _router = ResponseRouter()
    return _router


def route_response(context: CommandContext) -> ResponseConfig:
    """Convenience function to route a response."""
    return get_router().route(context)
