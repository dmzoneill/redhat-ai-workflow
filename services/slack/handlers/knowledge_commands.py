"""
Knowledge command handlers for @me research, learn, knowledge.

Handles: @me research, @me learn, @me knowledge
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand
    from scripts.common.context_extractor import ConversationContext

logger = logging.getLogger(__name__)


async def _load_yaml(path: Path | str) -> Any:
    """Read and parse a YAML file without blocking the event loop."""
    return yaml.safe_load(await asyncio.to_thread(Path(path).read_text, encoding="utf-8"))


async def _dump_yaml(path: Path | str, data: Any, **kwargs: Any) -> None:
    """Serialise data as YAML and write it without blocking the event loop."""
    text = yaml.dump(data, **kwargs)
    await asyncio.to_thread(Path(path).write_text, text, encoding="utf-8")


# Resolve PROJECT_ROOT the same way daemon.py does
_handler_dir = Path(__file__).resolve().parent  # handlers/
_slack_dir = _handler_dir.parent  # slack/
_services_dir = _slack_dir.parent  # services/
PROJECT_ROOT = _services_dir.parent  # project root
KNOWLEDGE_DIR = PROJECT_ROOT / "memory" / "knowledge" / "slack"

# Failures while analysing or saving knowledge that should become a user-facing error
_KNOWLEDGE_ERRORS = (OSError, yaml.YAMLError, ValueError, RuntimeError)


def _parse_research_args(args: list[str]) -> tuple[str, bool]:
    """Split research args into (topic, deep); "#channel" and a leading "in" are skipped."""
    deep = False
    channel = None
    topic_parts = []
    for arg in args:
        if arg.lower() == "deep":
            deep = True
        elif arg.startswith("#"):
            channel = arg.lstrip("#")
        elif arg.lower() == "in" and channel is None:
            continue  # Skip "in" before channel
        else:
            topic_parts.append(arg)
    return " ".join(topic_parts), deep


def _format_research_messages(topic: str, messages: list[dict[str, Any]]) -> str:
    """Plain listing of found messages, used when no Claude agent is available."""
    lines = [
        f"*\U0001f52c Research: {topic}*\n",
        f"Found {len(messages)} messages:\n",
    ]
    lines.extend(f"\u2022 *#{msg.get('channel_name')}* - {msg.get('text', '')[:80]}..." for msg in messages[:10])
    return "\n".join(lines)


def _research_prompt(topic: str, messages: list[dict[str, Any]]) -> str:
    """Build the Claude prompt that summarises research messages."""
    messages_text = "\n".join(
        [f"[#{m.get('channel_name')}] @{m.get('username')}: {m.get('text', '')}" for m in messages[:30]]
    )
    return f"""Analyze these Slack messages about "{topic}" and create a knowledge summary:

{messages_text}

Create a structured summary with:
1. Key patterns or recurring themes
2. Common causes mentioned
3. Solutions that worked
4. Related Jira issues mentioned
5. Key people involved

Format for Slack (use *bold*, bullet points). Be concise."""


def _search_error_message(result: dict[str, Any]) -> str:
    """User-facing message for a failed SearchMessages D-Bus call."""
    if result.get("rate_limited"):
        return f"\u23f3 Rate limited. {result.get('error', 'Please wait before researching again.')}"
    return f"\u274c Research failed: {result['error']}"


async def handle_research(
    parsed: ParsedCommand,
    _message: Any,
    ctx: HandlerContext,
) -> str:
    """Handle @me research command - research a topic in Slack."""
    if not parsed.args:
        return (
            "\u274c Please provide a topic to research.\n\nUsage:\n"
            "\u2022 `@me research billing errors` - Research a topic\n"
            "\u2022 `@me research deep auth issues` - Deep research with more results"
        )

    topic, deep = _parse_research_args(parsed.args)
    if not topic:
        return "\u274c Please provide a topic to research."

    # Check rate limits via D-Bus
    result = await ctx.call_dbus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SearchMessages",
        [topic, 50 if deep else 30],
    )

    if "error" in result:
        return _search_error_message(result)

    messages = result.get("messages", [])
    if not messages:
        return f"\U0001f50d No Slack messages found for: `{topic}`"

    # Use Claude to analyze the messages
    if not ctx.claude_agent:
        # Fallback: just return the messages
        return _format_research_messages(topic, messages)

    return await _analyze_research(ctx, topic, messages)


async def _analyze_research(ctx: HandlerContext, topic: str, messages: list[dict[str, Any]]) -> str:
    """Summarise research messages with Claude and save the result."""
    prompt = _research_prompt(topic, messages)
    try:
        analysis = await ctx.claude_agent.process_message(prompt, {"purpose": "research"})

        # Save to knowledge base
        await _save_research_knowledge(topic, analysis, messages)

        return f"*\U0001f52c Research: {topic}*\n\n{analysis}\n\n_Knowledge saved to `memory/knowledge/slack/`_"

    except _KNOWLEDGE_ERRORS as e:
        logger.exception("Research analysis failed")
        return f"\u274c Analysis failed: {e!s}"


async def handle_learn(
    parsed: ParsedCommand,
    message: Any,
    ctx: HandlerContext,
) -> str:
    """Handle @me learn command - learn from current thread."""
    # Extract context from thread
    context = await ctx.extract_context(message)

    if not context.is_valid():
        return "\u274c Could not extract context from thread. Please use this command in a thread with discussion."

    # Determine topic from args or infer from context
    topic = " ".join(parsed.args) if parsed.args else context.inferred_type or "general"

    # Use Claude to extract learnings
    if not ctx.claude_agent:
        return "\u274c Claude agent not available for learning"

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
        analysis = await ctx.claude_agent.process_message(prompt, {"purpose": "learning"})

        # Save to knowledge base
        await _save_thread_learning(topic, analysis, context)

        return f"\u2705 Learned from thread about `{topic}`\n\n{analysis[:500]}...\n\n_Saved to knowledge base_"

    except _KNOWLEDGE_ERRORS as e:
        logger.exception("Learning failed")
        return f"\u274c Learning failed: {e!s}"


async def handle_knowledge(parsed: ParsedCommand) -> str:
    """Handle @me knowledge command - query or list knowledge."""
    if not parsed.args:
        return (
            "\u274c Please provide a topic or 'list'.\n\nUsage:\n"
            "\u2022 `@me knowledge billing` - Query knowledge about billing\n"
            "\u2022 `@me knowledge list` - List all knowledge topics"
        )

    subcommand = parsed.args[0].lower()
    if subcommand == "list":
        return _list_knowledge()
    if subcommand == "delete" and len(parsed.args) > 1:
        return _delete_knowledge(parsed.args[1])
    return await _query_knowledge(" ".join(parsed.args))


def _list_knowledge() -> str:
    """List saved Slack knowledge topics."""
    files = sorted(KNOWLEDGE_DIR.glob("*.yaml")) if KNOWLEDGE_DIR.exists() else []
    if not files:
        return "\U0001f4da No Slack knowledge saved yet"
    lines = ["*\U0001f4da Slack Knowledge Base*\n"]
    lines.extend(f"\u2022 `{f.stem}` - {f.stem.replace('-', ' ').title()}" for f in files[:20])
    return "\n".join(lines)


def _delete_knowledge(topic: str) -> str:
    """Delete one saved knowledge topic."""
    knowledge_file = KNOWLEDGE_DIR / f"{topic}.yaml"
    if knowledge_file.exists():
        knowledge_file.unlink()
        return f"\U0001f5d1\ufe0f Deleted knowledge: `{topic}`"
    return f"\u274c Knowledge not found: `{topic}`"


async def _query_knowledge(topic: str) -> str:
    """Show the saved summary, patterns and solutions for a topic."""
    knowledge_file = KNOWLEDGE_DIR / f"{topic.lower().replace(' ', '-')}.yaml"
    if not knowledge_file.exists():
        return f"\u274c No knowledge found for: `{topic}`\n\nUse `@me research {topic}` to gather knowledge."

    data = await _load_yaml(knowledge_file)
    lines = [f"*\U0001f4da Knowledge: {topic}*\n"]
    if data.get("summary"):
        lines.append(data["summary"][:500])
    if data.get("patterns"):
        lines.append("\n*Patterns:*")
        lines.extend(f"\u2022 {p}" for p in data["patterns"][:5])
    if data.get("solutions"):
        lines.append("\n*Solutions:*")
        lines.extend(f"\u2022 {item}" for item in data["solutions"][:5])
    return "\n".join(lines)


async def _save_research_knowledge(topic: str, analysis: str, messages: list) -> None:
    """Save research results to knowledge base."""
    knowledge_dir = KNOWLEDGE_DIR
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = topic.lower().replace(" ", "-")[:50]
    knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

    data = {
        "metadata": {
            "topic": topic,
            "created": datetime.now().astimezone().isoformat(),
            "source": "slack_research",
            "message_count": len(messages),
        },
        "summary": analysis[:1000],
        "patterns": [],
        "solutions": [],
        "sources": [m.get("permalink", "") for m in messages[:10] if m.get("permalink")],
    }

    await _dump_yaml(knowledge_file, data, default_flow_style=False)

    logger.info("Saved research knowledge: %s", knowledge_file)


async def _save_thread_learning(topic: str, analysis: str, context: ConversationContext) -> None:
    """Save thread learning to knowledge base."""
    knowledge_dir = KNOWLEDGE_DIR
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = topic.lower().replace(" ", "-")[:50]
    knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

    data = {
        "metadata": {
            "topic": topic,
            "created": datetime.now().astimezone().isoformat(),
            "source": "thread_learning",
        },
        "summary": analysis[:1000],
        "patterns": [],
        "solutions": [],
        "related_issues": context.jira_issues,
    }

    await _dump_yaml(knowledge_file, data, default_flow_style=False)

    logger.info("Saved thread learning: %s", knowledge_file)
