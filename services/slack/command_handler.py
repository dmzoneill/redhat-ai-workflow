"""@me command dispatch for the Slack daemon.

``CommandHandler`` parses an @me command and routes it to the focused handler
modules in ``services.slack.handlers``. Anything that is not a built-in command
runs as a skill or tool through Claude.
"""

import importlib
import json
import logging
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from scripts.common.command_parser import CommandParser, ParsedCommand
from scripts.common.command_registry import CommandType, get_registry
from scripts.common.context_extractor import ContextExtractor, ConversationContext
from scripts.common.response_router import CommandContext, ResponseFormatter, get_router
from services.slack.errors import IMPORT_OR_SLACK_ERRORS, SLACK_ERRORS
from services.slack.handlers import jira_commands, knowledge_commands, meet_commands, sprint_commands, system_commands
from services.slack.handlers.base import HandlerContext
from services.slack.slack_config import get_slack_config

if TYPE_CHECKING:
    from src.listener import PendingMessage

    from services.slack.message_processor import UserClassification
    from services.slack.response_builder import DesktopNotifier

logger = logging.getLogger(__name__)

Route = Callable[[ParsedCommand, "PendingMessage"], Awaitable[str]]

_SKILL_PROMPT = """Execute the skill `{name}` with these inputs:

```json
{inputs}
```

Use `skill_run("{name}", '{inputs}')` to execute the skill and return the results.
Format the output for Slack (use *bold*, `code`, bullet points).
"""

_TOOL_PROMPT = """Execute the tool `{name}` with these arguments:

```json
{inputs}
```

Call the tool directly and return the results.
Format the output for Slack (use *bold*, `code`, bullet points).
"""


def _parse_dbus_result(result: Any) -> dict:
    """Decode a JSON string reply; wrap anything else as ``{"result": ...}``."""
    if isinstance(result, str):
        try:
            decoded: dict = json.loads(result)
            return decoded
        except json.JSONDecodeError:
            return {"result": result}
    return {"result": result}


async def call_dbus(service: str, path: str, interface: str, method: str, args: list | None = None) -> dict:
    """Call a D-Bus method and return the result (``{"error": ...}`` on failure)."""
    try:
        message_bus = importlib.import_module("dbus_next.aio").MessageBus
        bus = await message_bus().connect()
        introspection = await bus.introspect(service, path)
        proxy = bus.get_proxy_object(service, path, introspection)
        iface = proxy.get_interface(interface)

        method_func = getattr(iface, f"call_{method.lower()}")
        result = await method_func(*args) if args else await method_func()

        bus.disconnect()
        return _parse_dbus_result(result)

    except IMPORT_OR_SLACK_ERRORS as e:
        logger.error("D-Bus call failed: %s.%s: %s", service, method, e)
        return {"error": str(e)}


def format_context_preview(context: ConversationContext) -> str:
    """Format a preview of extracted context."""
    lines = []
    if context.summary:
        lines.append(f"*Summary:* {context.summary}")
    if context.inferred_type:
        lines.append(f"*Type:* {context.inferred_type}")
    if context.jira_issues:
        lines.append(f"*Related:* {', '.join(context.jira_issues)}")
    return "\n".join(lines) if lines else ""


class CommandHandler:
    """
    Handles @me commands from Slack.

    Thin dispatcher that parses commands and routes to focused handler modules
    in services.slack.handlers/.

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

        # Config
        self.config = get_slack_config("commands", {})

    @cached_property
    def formatter(self) -> ResponseFormatter:
        """Response formatter for command output."""
        return ResponseFormatter()

    @property
    def context_limit(self) -> int:
        """How many conversation messages to read when extracting context."""
        limit: int = self.config.get("context_messages_limit", 20)
        return limit

    @cached_property
    def contextual_skills(self) -> set[str]:
        """Skills that take their inputs from the surrounding conversation."""
        return set(self.config.get("contextual_skills", ["create_jira_issue", "investigate_alert"]))

    @cached_property
    def handler_context(self) -> HandlerContext:
        """The HandlerContext passed to extracted handler modules."""
        return HandlerContext(
            call_dbus=self._call_dbus,
            extract_context=self._extract_context,
            run_skill=self._run_skill,
            run_tool=self._run_tool,
            claude_agent=self.claude_agent,
        )

    def is_command(self, text: str, is_self_dm: bool = False) -> bool:
        """Check if a message is an @me command."""
        parsed = self.parser.parse(text, is_self_dm)
        return bool(parsed.is_command)

    def _routes(self) -> dict[str, Route]:
        """Built-in commands, by name, other than help and status."""
        ctx = self.handler_context
        return {
            "list": lambda parsed, _msg: system_commands.handle_list(parsed, self.registry),
            "watch": lambda _parsed, msg: system_commands.handle_watch(msg, get_slack_config),
            "cron": lambda parsed, _msg: system_commands.handle_cron(parsed, ctx),
            "jira": lambda parsed, msg: jira_commands.handle_jira(parsed, msg, ctx),
            "search": lambda parsed, _msg: jira_commands.handle_search(parsed, ctx),
            "who": lambda parsed, _msg: jira_commands.handle_who(parsed, ctx),
            "find": lambda parsed, _msg: jira_commands.handle_find(parsed, ctx),
            "cursor": lambda parsed, msg: jira_commands.handle_cursor(parsed, msg, ctx),
            "sprint": lambda parsed, _msg: sprint_commands.handle_sprint(parsed, ctx),
            "meet": lambda parsed, _msg: meet_commands.handle_meet(parsed, ctx),
            "research": lambda parsed, msg: knowledge_commands.handle_research(parsed, msg, ctx),
            "learn": lambda parsed, msg: knowledge_commands.handle_learn(parsed, msg, ctx),
            "knowledge": lambda parsed, _msg: knowledge_commands.handle_knowledge(parsed),
        }

    async def _dispatch(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Run the handler for ``parsed`` and return its response text."""
        if self.parser.is_help_command(parsed):
            response: str = await system_commands.handle_help(parsed, self.parser, self.registry)
            return response
        if self.parser.is_status_command(parsed):
            status: str = await system_commands.handle_status(self.registry, self.contextual_skills, self.claude_agent)
            return status
        route = self._routes().get(parsed.command)
        if route is not None:
            return await route(parsed, message)
        return await self._handle_skill_or_tool(parsed, message)

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
        self_dm_channel = get_slack_config("listener.self_dm_channel", "")
        is_self_dm = message.channel_id == self_dm_channel

        parsed = self.parser.parse(message.text, is_self_dm)
        if not parsed.is_command:
            return None, False

        logger.info("Processing @me command: %s (type: %s)", parsed.command, parsed.trigger_type.value)

        try:
            response = await self._dispatch(parsed, message)

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
            self.router.route(routing_ctx)

            # Should always send command responses
            return response, classification.auto_respond

        except SLACK_ERRORS as e:
            logger.exception("Error handling command %s", parsed.command)
            return f"\u274c Error: {e!s}", True

    async def _handle_skill_or_tool(self, parsed: ParsedCommand, message: "PendingMessage") -> str:
        """Handle a skill or tool command."""
        cmd_info = self.registry.get_command(parsed.command)

        if not cmd_info:
            return f"\u274c Unknown command: `{parsed.command}`\n\nUse `@me help` to list available commands."

        # Get explicit inputs from parsed command
        inputs = parsed.to_skill_inputs()

        # Contextual skills with no explicit inputs take them from the conversation
        if cmd_info.contextual and not inputs:
            context = await self._extract_context(message)
            if context.is_valid():
                inputs.update(context.to_skill_inputs(parsed.command))
                if format_context_preview(context):
                    logger.info("Extracted context for %s: %s", parsed.command, context.summary[:100])

        if cmd_info.command_type == CommandType.SKILL:
            return await self._run_skill(parsed.command, inputs, message)
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
        return format_context_preview(context)

    async def _ask_claude(self, prompt: str, message: "PendingMessage", context: dict) -> str:
        """Send ``prompt`` to Claude in the message's conversation."""
        conversation_id = f"{message.channel_id}:{message.thread_ts or message.user_id}"
        base = {"user_name": message.user_name, "channel_name": message.channel_name, "is_dm": message.is_dm}
        response: str = await self.claude_agent.process_message(
            prompt, {**base, **context}, conversation_id=conversation_id
        )
        return response

    async def _run_skill(self, skill_name: str, inputs: dict, message: "PendingMessage") -> str:
        """Run a skill via Claude."""
        if not self.claude_agent:
            return "\u274c Claude agent not available"

        inputs_json = json.dumps(inputs) if inputs else "{}"
        prompt = _SKILL_PROMPT.format(name=skill_name, inputs=inputs_json)
        try:
            return await self._ask_claude(prompt, message, {"purpose": "skill_execution", "skill_name": skill_name})
        except SLACK_ERRORS as e:
            logger.error("Failed to run skill %s: %s", skill_name, e)
            return f"\u274c Failed to run skill `{skill_name}`: {e!s}"

    async def _run_tool(self, tool_name: str, inputs: dict, message: "PendingMessage") -> str:
        """Run a tool via Claude."""
        if not self.claude_agent:
            return "\u274c Claude agent not available"

        inputs_json = json.dumps(inputs) if inputs else "{}"
        prompt = _TOOL_PROMPT.format(name=tool_name, inputs=inputs_json)
        try:
            return await self._ask_claude(prompt, message, {"purpose": "tool_execution", "tool_name": tool_name})
        except SLACK_ERRORS as e:
            logger.error("Failed to run tool %s: %s", tool_name, e)
            return f"\u274c Failed to run tool `{tool_name}`: {e!s}"

    # =========================================================================
    # D-BUS SERVICE CALL HELPER
    # =========================================================================

    async def _call_dbus(
        self,
        service: str,
        path: str,
        interface: str,
        method: str,
        args: list | None = None,
    ) -> dict:
        """Call a D-Bus method and return the result."""
        return await call_dbus(service, path, interface, method, args)
