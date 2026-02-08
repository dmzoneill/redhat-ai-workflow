"""
Jira and lookup command handlers.

Handles: @me jira, @me search, @me who, @me find, @me cursor
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand
    from scripts.common.context_extractor import ConversationContext

logger = logging.getLogger(__name__)


async def handle_jira(
    parsed: "ParsedCommand",
    message: Any,
    ctx: HandlerContext,
) -> str:
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
    context = await ctx.extract_context(message)

    if not context.is_valid():
        return (
            "\u274c Could not extract context from thread. Please provide more details."
        )

    # Build inputs for create_jira_issue skill
    inputs = {
        "summary": (
            context.summary[:200] if context.summary else "Issue from Slack thread"
        ),
        "description": context.raw_text[:2000] if context.raw_text else "",
        "issue_type": issue_type,
        "slack_format": True,
    }

    if parent_key:
        inputs["parent_key"] = parent_key

    if context.jira_issues:
        inputs["link_to"] = context.jira_issues[0]  # Link to first related issue

    # For Stories, use Claude to generate required fields from context
    if issue_type == "Story" and ctx.claude_agent:
        story_fields = await _generate_story_fields(context, ctx)
        if story_fields:
            inputs.update(story_fields)

    # Run the skill
    return await ctx.run_skill("create_jira_issue", inputs, message)


async def _generate_story_fields(
    context: "ConversationContext",
    ctx: HandlerContext,
) -> dict:
    """Use Claude to generate story-specific fields from conversation context."""
    if not ctx.claude_agent:
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
        response = await ctx.claude_agent.process_message(
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


async def handle_search(parsed: "ParsedCommand", ctx: HandlerContext) -> str:
    """Handle @me search command - search Slack, code, or Jira."""
    if not parsed.args:
        return (
            "\u274c Please provide a search query.\n\nUsage:\n"
            "\u2022 `@me search <query>` - Search Slack\n"
            "\u2022 `@me search code <query>` - Search code\n"
            "\u2022 `@me search jira <query>` - Search Jira"
        )

    search_type = "slack"
    query_parts = parsed.args

    # Check for search type prefix
    if parsed.args[0].lower() in ("code", "jira", "slack", "logs"):
        search_type = parsed.args[0].lower()
        query_parts = parsed.args[1:]

    if not query_parts:
        return f"\u274c Please provide a search query for {search_type} search."

    query = " ".join(query_parts)

    if search_type == "slack":
        # Use D-Bus to search Slack
        result = await ctx.call_dbus(
            "com.aiworkflow.BotSlack",
            "/com/aiworkflow/BotSlack",
            "com.aiworkflow.BotSlack",
            "SearchMessages",
            [query, 20],
        )

        if "error" in result:
            return f"\u274c Search failed: {result['error']}"

        if result.get("rate_limited"):
            return f"\u23f3 Rate limited. {result.get('error', 'Please wait before searching again.')}"

        messages = result.get("messages", [])
        if not messages:
            return f"\U0001f50d No results found for: `{query}`"

        lines = [
            f"*\U0001f50d Slack Search Results* ({len(messages)} of {result.get('total', len(messages))})\n"
        ]
        for msg in messages[:10]:
            channel = msg.get("channel_name", "unknown")
            user = msg.get("username", "unknown")
            text = msg.get("text", "")[:100]
            lines.append(f"\u2022 *#{channel}* (@{user}): {text}...")

        remaining = result.get("searches_remaining_today")
        if remaining is not None:
            lines.append(f"\n_({remaining} searches remaining today)_")

        return "\n".join(lines)

    elif search_type == "code":
        # Use Claude to search code
        return await ctx.run_skill("code_search", {"query": query}, None)

    elif search_type == "jira":
        # Use Claude to search Jira
        return await ctx.run_tool(
            "jira_search", {"jql": f'text ~ "{query}"', "max_results": 10}, None
        )

    else:
        return f"\u274c Unknown search type: `{search_type}`"


async def handle_who(parsed: "ParsedCommand", ctx: HandlerContext) -> str:
    """Handle @me who command - look up a Slack user."""
    if not parsed.args:
        return "\u274c Please provide a username or email.\n\nUsage: `@me who @username` or `@me who email@example.com`"

    query = parsed.args[0].lstrip("@")

    result = await ctx.call_dbus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "FindUser",
        [query],
    )

    if "error" in result:
        return f"\u274c Lookup failed: {result['error']}"

    users = result.get("users", [])
    if not users:
        return f"\U0001f50d No users found matching: `{query}`"

    lines = [f"*\U0001f464 User Lookup: {query}*\n"]
    for user in users[:5]:
        lines.append(f"\u2022 *{user.get('display_name') or user.get('user_name')}*")
        lines.append(f"  ID: `{user.get('user_id')}`")
        if user.get("real_name"):
            lines.append(f"  Name: {user.get('real_name')}")
        if user.get("email"):
            lines.append(f"  Email: {user.get('email')}")
        if user.get("gitlab_username"):
            lines.append(f"  GitLab: @{user.get('gitlab_username')}")
        lines.append("")

    return "\n".join(lines)


async def handle_find(parsed: "ParsedCommand", ctx: HandlerContext) -> str:
    """Handle @me find command - find a Slack channel."""
    if not parsed.args:
        return "\u274c Please provide a channel name.\n\nUsage: `@me find #channel-name` or `@me find alerts`"

    query = parsed.args[0].lstrip("#")

    result = await ctx.call_dbus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "FindChannel",
        [query],
    )

    if "error" in result:
        return f"\u274c Lookup failed: {result['error']}"

    channels = result.get("channels", [])
    if not channels:
        return f"\U0001f50d No channels found matching: `{query}`"

    lines = [f"*\U0001f4e2 Channel Lookup: {query}*\n"]
    for ch in channels[:10]:
        member = " \u2705" if ch.get("is_member") else ""
        private = " \U0001f512" if ch.get("is_private") else ""
        lines.append(f"\u2022 *#{ch.get('name')}*{member}{private}")
        lines.append(f"  ID: `{ch.get('channel_id')}`")
        if ch.get("purpose"):
            lines.append(f"  Purpose: {ch.get('purpose')[:80]}")
        if ch.get("num_members"):
            lines.append(f"  Members: {ch.get('num_members')}")
        lines.append("")

    return "\n".join(lines)


async def handle_cursor(
    parsed: "ParsedCommand",
    message: Any,
    ctx: HandlerContext,
) -> str:
    """Handle @me cursor command - create a Cursor chat from thread."""
    # Extract context from thread
    context = await ctx.extract_context(message)

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
        return (
            "\u274c Could not extract context from thread. Please provide an issue key.\n\n"
            "Usage: `@me cursor` (in a thread) or `@me cursor AAP-12345`"
        )

    # Call the Chat D-Bus service
    if issue_key:
        result = await ctx.call_dbus(
            "com.aiworkflow.Chat",
            "/com/aiworkflow/Chat",
            "com.aiworkflow.Chat",
            "LaunchIssueChatWithPrompt",
            [issue_key, prompt],
        )
    else:
        result = await ctx.call_dbus(
            "com.aiworkflow.Chat",
            "/com/aiworkflow/Chat",
            "com.aiworkflow.Chat",
            "LaunchIssueChatWithPrompt",
            ["", prompt],
        )

    if "error" in result:
        return f"\u274c Failed to launch Cursor chat: {result['error']}"

    return "\u2705 Cursor chat launched with thread context"
