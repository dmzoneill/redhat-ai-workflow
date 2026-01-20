"""
Command Parser for Slack @me Commands.

Parses @me messages into structured commands with arguments and flags.

Supported trigger patterns:
- @me <command> - Literal @me prefix in any channel
- !<command> or /<command> - In self-DM channel only
- /bot <command> - Slack slash command (future)

Examples:
    @me create_jira_issue           # Contextual - extract from thread
    @me create_jira_issue --type=bug --priority=high  # Explicit args
    @me help                        # List available commands
    @me help create_jira_issue      # Show skill inputs/description
"""

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TriggerType(str, Enum):
    """Type of command trigger detected."""

    AT_ME = "at_me"  # @me command
    BANG = "bang"  # !command (self-DM)
    SLASH = "slash"  # /command (self-DM)
    SLASH_BOT = "slash_bot"  # /bot command (Slack slash command)
    NONE = "none"  # No trigger detected


@dataclass
class ParsedCommand:
    """Result of parsing a command message."""

    # Whether a valid command was detected
    is_command: bool = False

    # Trigger type used
    trigger_type: TriggerType = TriggerType.NONE

    # The command/skill name
    command: str = ""

    # Positional arguments
    args: list[str] = field(default_factory=list)

    # Named arguments (--key=value or --key value)
    kwargs: dict[str, Any] = field(default_factory=dict)

    # Flags (--flag without value)
    flags: set[str] = field(default_factory=set)

    # Original message text
    original_text: str = ""

    # Text after trigger removed (for context)
    remaining_text: str = ""

    # Response routing flags
    reply_dm: bool = False
    reply_thread: bool = True  # Default

    def __post_init__(self):
        # Convert flags to set if it's a list
        if isinstance(self.flags, list):
            self.flags = set(self.flags)

    def to_skill_inputs(self) -> dict[str, Any]:
        """Convert parsed command to skill input format."""
        inputs = dict(self.kwargs)

        # Add positional args if present
        if self.args:
            # First positional arg is often a target/subject
            if len(self.args) == 1:
                inputs["target"] = self.args[0]
            else:
                inputs["args"] = self.args

        return inputs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_command": self.is_command,
            "trigger_type": self.trigger_type.value,
            "command": self.command,
            "args": self.args,
            "kwargs": self.kwargs,
            "flags": list(self.flags),
            "reply_dm": self.reply_dm,
            "reply_thread": self.reply_thread,
        }


class CommandParser:
    """
    Parses Slack messages for @me commands.

    Detects command triggers and extracts command name, arguments, and flags.
    """

    # Trigger patterns
    TRIGGERS = {
        # @me at start of message (case insensitive)
        r"^@me\s+": TriggerType.AT_ME,
        # ! at start (for self-DM)
        r"^!\s*": TriggerType.BANG,
        # / at start followed by word (for self-DM, not Slack slash)
        r"^/(?!bot\s)(\S+)": TriggerType.SLASH,
        # /bot command (Slack slash command style)
        r"^/bot\s+": TriggerType.SLASH_BOT,
    }

    # Built-in commands that don't require skill lookup
    BUILTIN_COMMANDS = {"help", "status", "list", "commands"}

    def __init__(
        self,
        triggers: list[str] | None = None,
        self_dm_only_triggers: list[str] | None = None,
    ):
        """
        Initialize the parser.

        Args:
            triggers: List of trigger prefixes to recognize (default: ["@me"])
            self_dm_only_triggers: Triggers only valid in self-DM (default: ["!", "/"])
        """
        self.triggers = triggers or ["@me"]
        self.self_dm_only_triggers = self_dm_only_triggers or ["!", "/"]

        # Compile regex patterns
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE), trigger_type) for pattern, trigger_type in self.TRIGGERS.items()
        ]

    def parse(self, text: str, is_self_dm: bool = False) -> ParsedCommand:
        """
        Parse a message for command syntax.

        Args:
            text: The message text to parse
            is_self_dm: Whether this message is in the self-DM channel

        Returns:
            ParsedCommand with parsed details
        """
        result = ParsedCommand(original_text=text)

        if not text or not text.strip():
            return result

        text = text.strip()

        # Try to match a trigger pattern
        trigger_type = TriggerType.NONE
        remaining = text

        for pattern, t_type in self._patterns:
            match = pattern.match(text)
            if match:
                # Check if this trigger is valid for current context
                if t_type in (TriggerType.BANG, TriggerType.SLASH) and not is_self_dm:
                    continue  # These triggers only work in self-DM

                trigger_type = t_type
                remaining = text[match.end() :].strip()

                # Special case for /command (not /bot)
                if t_type == TriggerType.SLASH and match.groups():
                    # The command is captured in the regex
                    remaining = match.group(1) + " " + remaining
                break

        if trigger_type == TriggerType.NONE:
            # No valid trigger found
            return result

        result.trigger_type = trigger_type
        result.remaining_text = remaining

        # Parse the command and arguments
        self._parse_command_args(remaining, result)

        return result

    def _parse_command_args(self, text: str, result: ParsedCommand) -> None:
        """Parse command name and arguments from text."""
        if not text:
            return

        try:
            # Use shlex for proper quote handling
            tokens = shlex.split(text)
        except ValueError:
            # Fallback to simple split on parse error
            tokens = text.split()

        if not tokens:
            return

        # First token is the command
        result.command = tokens[0].lower().replace("-", "_")
        result.is_command = True

        # Parse remaining tokens
        i = 1
        while i < len(tokens):
            token = tokens[i]

            if token.startswith("--"):
                # Named argument or flag
                self._parse_option(token, tokens, i, result)
                if "=" in token:
                    i += 1
                elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    i += 2  # Skip value
                else:
                    i += 1  # Just flag
            elif token.startswith("-") and len(token) == 2:
                # Short flag (-f)
                result.flags.add(token[1])
                i += 1
            else:
                # Positional argument
                result.args.append(token)
                i += 1

        # Handle special flags
        if "reply-dm" in result.flags or result.kwargs.get("reply") == "dm":
            result.reply_dm = True
            result.reply_thread = False
        if "reply-thread" in result.flags or result.kwargs.get("reply") == "thread":
            result.reply_thread = True
            result.reply_dm = False

    def _parse_option(self, token: str, tokens: list[str], index: int, result: ParsedCommand) -> None:
        """Parse a --option or --option=value token."""
        # Remove leading --
        option = token[2:]

        if "=" in option:
            # --key=value format
            key, value = option.split("=", 1)
            result.kwargs[key.replace("-", "_")] = self._parse_value(value)
        elif index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            # --key value format
            key = option.replace("-", "_")
            result.kwargs[key] = self._parse_value(tokens[index + 1])
        else:
            # Just a flag
            result.flags.add(option.replace("-", "_"))

    def _parse_value(self, value: str) -> Any:
        """Parse a value string into appropriate type."""
        # Try to parse as boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False

        # Try to parse as integer
        try:
            return int(value)
        except ValueError:
            pass

        # Try to parse as float
        try:
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value

    def is_help_command(self, parsed: ParsedCommand) -> bool:
        """Check if this is a help/list command."""
        return parsed.command in ("help", "list", "commands", "?")

    def is_status_command(self, parsed: ParsedCommand) -> bool:
        """Check if this is a status command."""
        return parsed.command in ("status", "info", "whoami")

    def get_help_target(self, parsed: ParsedCommand) -> str | None:
        """Get the target of a help command (the thing to get help for)."""
        if not self.is_help_command(parsed):
            return None

        if parsed.args:
            return parsed.args[0]

        return None


def parse_command(text: str, is_self_dm: bool = False) -> ParsedCommand:
    """
    Convenience function to parse a command.

    Args:
        text: Message text to parse
        is_self_dm: Whether in self-DM channel

    Returns:
        ParsedCommand result
    """
    parser = CommandParser()
    return parser.parse(text, is_self_dm)
