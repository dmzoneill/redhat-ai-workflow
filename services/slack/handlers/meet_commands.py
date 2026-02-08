"""
Meet command handlers for @me meet subcommands.

Handles: @me meet list, @me meet join, @me meet leave, @me meet captions
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand

logger = logging.getLogger(__name__)


async def handle_meet(parsed: ParsedCommand, ctx: HandlerContext) -> str:
    """Handle @me meet command - control the meet bot."""
    if not parsed.args:
        return (
            "\u274c Please provide a subcommand.\n\nUsage:\n"
            "\u2022 `@me meet list` - List upcoming meetings\n"
            "\u2022 `@me meet join` - Join current meeting\n"
            "\u2022 `@me meet leave` - Leave meeting\n"
            "\u2022 `@me meet captions` - Get meeting captions"
        )

    subcommand = parsed.args[0].lower()

    if subcommand in ("list", "meetings"):
        result = await ctx.call_dbus(
            "com.aiworkflow.BotMeet",
            "/com/aiworkflow/BotMeet",
            "com.aiworkflow.BotMeet",
            "list_meetings",
        )

        if "error" in result:
            return f"\u274c Failed to list meetings: {result['error']}"

        meetings = result.get("meetings", [])
        if not meetings:
            return "\U0001f4c5 No upcoming meetings"

        lines = ["*\U0001f4c5 Upcoming Meetings*\n"]
        for mtg in meetings[:10]:
            status = mtg.get("status", "pending")
            icon = "\U0001f7e2" if status == "in_progress" else "\u23f3"
            lines.append(f"{icon} *{mtg.get('title', 'Untitled')}*")
            lines.append(f"  Time: {mtg.get('start_time', 'Unknown')}")

        return "\n".join(lines)

    elif subcommand == "join":
        result = await ctx.call_dbus(
            "com.aiworkflow.BotMeet",
            "/com/aiworkflow/BotMeet",
            "com.aiworkflow.BotMeet",
            "join_meeting",
        )

        if "error" in result:
            return f"\u274c Failed to join meeting: {result['error']}"

        return "\u2705 Joining meeting..."

    elif subcommand == "leave":
        result = await ctx.call_dbus(
            "com.aiworkflow.BotMeet",
            "/com/aiworkflow/BotMeet",
            "com.aiworkflow.BotMeet",
            "leave_meeting",
        )

        if "error" in result:
            return f"\u274c Failed to leave meeting: {result['error']}"

        return "\u2705 Left meeting"

    elif subcommand == "captions":
        result = await ctx.call_dbus(
            "com.aiworkflow.BotMeet",
            "/com/aiworkflow/BotMeet",
            "com.aiworkflow.BotMeet",
            "get_captions",
        )

        if "error" in result:
            return f"\u274c Failed to get captions: {result['error']}"

        captions = result.get("captions", "")
        if not captions:
            return "\U0001f4dd No captions available"

        return f"*\U0001f4dd Meeting Captions*\n\n{captions[:2000]}"

    else:
        return f"\u274c Unknown meet command: `{subcommand}`\n\nUse `@me help meet` for usage."
