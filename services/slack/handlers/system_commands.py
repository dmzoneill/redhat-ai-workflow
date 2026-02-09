"""
System command handlers for @me help, status, list, watch, cron.

Handles: @me help, @me status, @me list, @me watch, @me cron
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand
    from scripts.common.command_registry import CommandRegistry

logger = logging.getLogger(__name__)


async def handle_help(
    parsed: "ParsedCommand",
    parser: Any,
    registry: "CommandRegistry",
) -> str:
    """Handle help command."""
    target = parser.get_help_target(parsed)

    if target:
        # Help for specific command
        help_info = registry.get_command_help(target)
        if help_info:
            return help_info.format_slack()
        return f"\u274c Unknown command: `{target}`\n\nUse `@me help` to list available commands."

    # General help
    commands = registry.list_commands()
    return registry.format_list(commands, "slack")


async def handle_status(
    registry: "CommandRegistry",
    contextual_skills: set[str],
    claude_agent: Any,
) -> str:
    """Handle status command."""
    from scripts.common.command_registry import CommandType

    lines = ["*\U0001f916 Bot Status*\n"]

    # Count available commands
    skills = registry.list_commands(command_type=CommandType.SKILL)
    tools = registry.list_commands(command_type=CommandType.TOOL)

    lines.append(f"\u2022 *Skills available:* {len(skills)}")
    lines.append(f"\u2022 *Tools available:* {len(tools)}")
    lines.append(f"\u2022 *Contextual skills:* {', '.join(sorted(contextual_skills))}")

    if claude_agent:
        lines.append("\u2022 *Claude:* \u2705 Connected")
    else:
        lines.append("\u2022 *Claude:* \u274c Not connected")

    lines.append("\n_Use `@me help` to see available commands_")

    return "\n".join(lines)


async def handle_list(
    parsed: "ParsedCommand",
    registry: "CommandRegistry",
) -> str:
    """Handle list command."""
    from scripts.common.command_registry import CommandType

    filter_type = None
    if parsed.args:
        arg = parsed.args[0].lower()
        if arg in ("skill", "skills"):
            filter_type = CommandType.SKILL
        elif arg in ("tool", "tools"):
            filter_type = CommandType.TOOL

    commands = registry.list_commands(command_type=filter_type)
    return registry.format_list(commands, "slack")


async def handle_watch(
    message: Any,
    get_slack_config_fn: Any,
) -> str:
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
    watched = get_slack_config_fn("listener.watched_channels", [])
    is_watched = channel_id in watched

    lines = ["*\U0001f4e1 Channel Info*\n"]
    lines.append(f"\u2022 *Channel ID:* `{channel_id}`")
    lines.append(f"\u2022 *Type:* {channel_type}")
    watched_status = "\u2705 Yes" if is_watched else "\u274c No"
    lines.append(f"\u2022 *Currently watched:* {watched_status}")

    if not is_watched:
        lines.append("\n*To watch this channel:*")
        lines.append(
            f'Add `"{channel_id}"` to `slack.listener.watched_channels` in `config.json`'
        )

    return "\n".join(lines)


async def handle_cron(parsed: "ParsedCommand", ctx: HandlerContext) -> str:
    """Handle @me cron command - control the cron scheduler."""
    if not parsed.args:
        return (
            "\u274c Please provide a subcommand.\n\nUsage:\n"
            "\u2022 `@me cron list` - List scheduled jobs\n"
            "\u2022 `@me cron run <job>` - Run a job now\n"
            "\u2022 `@me cron history` - Show recent job history"
        )

    subcommand = parsed.args[0].lower()

    if subcommand in ("list", "jobs"):
        result = await ctx.call_dbus(
            "com.aiworkflow.BotCron",
            "/com/aiworkflow/BotCron",
            "com.aiworkflow.BotCron",
            "list_jobs",
        )

        if "error" in result:
            return f"\u274c Failed to list jobs: {result['error']}"

        jobs = result.get("jobs", [])
        if not jobs:
            return "\U0001f4c5 No scheduled jobs"

        lines = ["*\U0001f4c5 Scheduled Jobs*\n"]
        for job in jobs:
            enabled = "\u2705" if job.get("enabled") else "\u23f8\ufe0f"
            lines.append(
                f"{enabled} *{job.get('name')}* - {job.get('description', '')[:40]}"
            )
            lines.append(f"  Schedule: `{job.get('cron', 'unknown')}`")

        return "\n".join(lines)

    elif subcommand == "run" and len(parsed.args) > 1:
        job_name = parsed.args[1]
        result = await ctx.call_dbus(
            "com.aiworkflow.BotCron",
            "/com/aiworkflow/BotCron",
            "com.aiworkflow.BotCron",
            "run_job",
            [job_name],
        )

        if "error" in result:
            return f"\u274c Failed to run job: {result['error']}"

        return f"\u2705 Started job: `{job_name}`"

    elif subcommand == "history":
        result = await ctx.call_dbus(
            "com.aiworkflow.BotCron",
            "/com/aiworkflow/BotCron",
            "com.aiworkflow.BotCron",
            "get_history",
        )

        if "error" in result:
            return f"\u274c Failed to get history: {result['error']}"

        history = result.get("history", [])
        if not history:
            return "\U0001f4dc No job history"

        lines = ["*\U0001f4dc Recent Job History*\n"]
        for entry in history[:10]:
            status = "\u2705" if entry.get("success") else "\u274c"
            lines.append(
                f"{status} *{entry.get('job_name')}* - {entry.get('timestamp', '')}"
            )

        return "\n".join(lines)

    else:
        return f"\u274c Unknown cron command: `{subcommand}`\n\nUse `@me help cron` for usage."
