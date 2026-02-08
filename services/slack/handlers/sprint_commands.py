"""
Sprint command handlers for @me sprint subcommands.

Handles: @me sprint issues, @me sprint approve, @me sprint start, @me sprint skip
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand

logger = logging.getLogger(__name__)


async def handle_sprint(parsed: ParsedCommand, ctx: HandlerContext) -> str:
    """Handle @me sprint command - control the sprint bot."""
    if not parsed.args:
        return (
            "\u274c Please provide a subcommand.\n\nUsage:\n"
            "\u2022 `@me sprint issues` - List sprint issues\n"
            "\u2022 `@me sprint approve AAP-12345` - Approve an issue\n"
            "\u2022 `@me sprint start AAP-12345` - Start work on an issue\n"
            "\u2022 `@me sprint skip AAP-12345` - Skip an issue"
        )

    subcommand = parsed.args[0].lower()
    issue_key = parsed.args[1].upper() if len(parsed.args) > 1 else None

    if subcommand in ("issues", "list"):
        result = await ctx.call_dbus(
            "com.aiworkflow.BotSprint",
            "/com/aiworkflow/BotSprint",
            "com.aiworkflow.BotSprint",
            "list_issues",
        )

        if "error" in result:
            return f"\u274c Failed to list issues: {result['error']}"

        issues = result.get("issues", [])
        if not issues:
            return "\U0001f4cb No sprint issues found"

        lines = ["*\U0001f4cb Sprint Issues*\n"]
        for issue in issues[:15]:
            status = issue.get("approval_status", "pending")
            icon = (
                "\u2705"
                if status == "approved"
                else "\u23f3" if status == "pending" else "\u23ed\ufe0f"
            )
            lines.append(
                f"{icon} *{issue.get('key')}* - {issue.get('summary', '')[:50]}"
            )

        return "\n".join(lines)

    elif subcommand == "approve" and issue_key:
        result = await ctx.call_dbus(
            "com.aiworkflow.BotSprint",
            "/com/aiworkflow/BotSprint",
            "com.aiworkflow.BotSprint",
            "approve_issue",
            [issue_key],
        )

        if "error" in result:
            return f"\u274c Failed to approve: {result['error']}"

        return f"\u2705 Issue {issue_key} approved for sprint bot"

    elif subcommand == "start" and issue_key:
        result = await ctx.call_dbus(
            "com.aiworkflow.BotSprint",
            "/com/aiworkflow/BotSprint",
            "com.aiworkflow.BotSprint",
            "start_issue",
            [issue_key],
        )

        if "error" in result:
            return f"\u274c Failed to start: {result['error']}"

        return f"\u2705 Started work on {issue_key}"

    elif subcommand == "skip" and issue_key:
        result = await ctx.call_dbus(
            "com.aiworkflow.BotSprint",
            "/com/aiworkflow/BotSprint",
            "com.aiworkflow.BotSprint",
            "skip_issue",
            [issue_key],
        )

        if "error" in result:
            return f"\u274c Failed to skip: {result['error']}"

        return f"\u23ed\ufe0f Skipped {issue_key}"

    else:
        return f"\u274c Unknown sprint command: `{subcommand}`\n\nUse `@me help sprint` for usage."
