"""
Knowledge command handlers for @me research, learn, knowledge.

Handles: @me research, @me learn, @me knowledge
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from services.slack.handlers.base import HandlerContext

if TYPE_CHECKING:
    from scripts.common.command_parser import ParsedCommand
    from scripts.common.context_extractor import ConversationContext

logger = logging.getLogger(__name__)

# Resolve PROJECT_ROOT the same way daemon.py does
_handler_dir = Path(__file__).resolve().parent  # handlers/
_slack_dir = _handler_dir.parent  # slack/
_services_dir = _slack_dir.parent  # services/
PROJECT_ROOT = _services_dir.parent  # project root


async def handle_research(
    parsed: "ParsedCommand",
    message: Any,
    ctx: HandlerContext,
) -> str:
    """Handle @me research command - research a topic in Slack."""
    if not parsed.args:
        return (
            "\u274c Please provide a topic to research.\n\nUsage:\n"
            "\u2022 `@me research billing errors` - Research a topic\n"
            "\u2022 `@me research deep auth issues` - Deep research with more results"
        )

    # Check for modifiers
    deep = False
    channel = None
    topic_parts = []

    for arg in parsed.args:
        if arg.lower() == "deep":
            deep = True
        elif arg.startswith("#"):
            channel = arg.lstrip("#")
        elif arg.lower() == "in" and channel is None:
            continue  # Skip "in" before channel
        else:
            topic_parts.append(arg)

    topic = " ".join(topic_parts)
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
        if result.get("rate_limited"):
            return f"\u23f3 Rate limited. {result.get('error', 'Please wait before researching again.')}"
        return f"\u274c Research failed: {result['error']}"

    messages = result.get("messages", [])
    if not messages:
        return f"\U0001f50d No Slack messages found for: `{topic}`"

    # Use Claude to analyze the messages
    if not ctx.claude_agent:
        # Fallback: just return the messages
        lines = [
            f"*\U0001f52c Research: {topic}*\n",
            f"Found {len(messages)} messages:\n",
        ]
        for msg in messages[:10]:
            lines.append(
                f"\u2022 *#{msg.get('channel_name')}* - {msg.get('text', '')[:80]}..."
            )
        return "\n".join(lines)

    # Build prompt for Claude to analyze

    messages_text = "\n".join(
        [
            f"[#{m.get('channel_name')}] @{m.get('username')}: {m.get('text', '')}"
            for m in messages[:30]
        ]
    )

    prompt = f"""Analyze these Slack messages about "{topic}" and create a knowledge summary:

{messages_text}

Create a structured summary with:
1. Key patterns or recurring themes
2. Common causes mentioned
3. Solutions that worked
4. Related Jira issues mentioned
5. Key people involved

Format for Slack (use *bold*, bullet points). Be concise."""

    try:
        analysis = await ctx.claude_agent.process_message(
            prompt, {"purpose": "research"}
        )

        # Save to knowledge base
        await _save_research_knowledge(topic, analysis, messages)

        return f"*\U0001f52c Research: {topic}*\n\n{analysis}\n\n_Knowledge saved to `memory/knowledge/slack/`_"

    except Exception as e:
        logger.error(f"Research analysis failed: {e}")
        return f"\u274c Analysis failed: {str(e)}"


async def handle_learn(
    parsed: "ParsedCommand",
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
        analysis = await ctx.claude_agent.process_message(
            prompt, {"purpose": "learning"}
        )

        # Save to knowledge base
        await _save_thread_learning(topic, analysis, context)

        return f"\u2705 Learned from thread about `{topic}`\n\n{analysis[:500]}...\n\n_Saved to knowledge base_"

    except Exception as e:
        logger.error(f"Learning failed: {e}")
        return f"\u274c Learning failed: {str(e)}"


async def handle_knowledge(parsed: "ParsedCommand") -> str:
    """Handle @me knowledge command - query or list knowledge."""
    if not parsed.args:
        return (
            "\u274c Please provide a topic or 'list'.\n\nUsage:\n"
            "\u2022 `@me knowledge billing` - Query knowledge about billing\n"
            "\u2022 `@me knowledge list` - List all knowledge topics"
        )

    subcommand = parsed.args[0].lower()

    if subcommand == "list":
        # List knowledge files
        knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
        if not knowledge_dir.exists():
            return "\U0001f4da No Slack knowledge saved yet"

        files = list(knowledge_dir.glob("*.yaml"))
        if not files:
            return "\U0001f4da No Slack knowledge saved yet"

        lines = ["*\U0001f4da Slack Knowledge Base*\n"]
        for f in sorted(files)[:20]:
            topic = f.stem.replace("-", " ").title()
            lines.append(f"\u2022 `{f.stem}` - {topic}")

        return "\n".join(lines)

    elif subcommand == "delete" and len(parsed.args) > 1:
        topic = parsed.args[1]
        knowledge_file = (
            PROJECT_ROOT / "memory" / "knowledge" / "slack" / f"{topic}.yaml"
        )
        if knowledge_file.exists():
            knowledge_file.unlink()
            return f"\U0001f5d1\ufe0f Deleted knowledge: `{topic}`"
        return f"\u274c Knowledge not found: `{topic}`"

    else:
        # Query knowledge
        topic = " ".join(parsed.args)
        topic_slug = topic.lower().replace(" ", "-")
        knowledge_file = (
            PROJECT_ROOT / "memory" / "knowledge" / "slack" / f"{topic_slug}.yaml"
        )

        if knowledge_file.exists():
            import yaml

            with open(knowledge_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            lines = [f"*\U0001f4da Knowledge: {topic}*\n"]
            if data.get("summary"):
                lines.append(data["summary"][:500])
            if data.get("patterns"):
                lines.append("\n*Patterns:*")
                for p in data["patterns"][:5]:
                    lines.append(f"\u2022 {p}")
            if data.get("solutions"):
                lines.append("\n*Solutions:*")
                for s in data["solutions"][:5]:
                    lines.append(f"\u2022 {s}")

            return "\n".join(lines)

        return f"\u274c No knowledge found for: `{topic}`\n\nUse `@me research {topic}` to gather knowledge."


async def _save_research_knowledge(topic: str, analysis: str, messages: list) -> None:
    """Save research results to knowledge base."""
    from datetime import datetime

    import yaml

    knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = topic.lower().replace(" ", "-")[:50]
    knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

    data = {
        "metadata": {
            "topic": topic,
            "created": datetime.now().isoformat(),
            "source": "slack_research",
            "message_count": len(messages),
        },
        "summary": analysis[:1000],
        "patterns": [],
        "solutions": [],
        "sources": [
            m.get("permalink", "") for m in messages[:10] if m.get("permalink")
        ],
    }

    with open(knowledge_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)

    logger.info(f"Saved research knowledge: {knowledge_file}")


async def _save_thread_learning(
    topic: str, analysis: str, context: "ConversationContext"
) -> None:
    """Save thread learning to knowledge base."""
    from datetime import datetime

    import yaml

    knowledge_dir = PROJECT_ROOT / "memory" / "knowledge" / "slack"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    topic_slug = topic.lower().replace(" ", "-")[:50]
    knowledge_file = knowledge_dir / f"{topic_slug}.yaml"

    data = {
        "metadata": {
            "topic": topic,
            "created": datetime.now().isoformat(),
            "source": "thread_learning",
        },
        "summary": analysis[:1000],
        "patterns": [],
        "solutions": [],
        "related_issues": context.jira_issues,
    }

    with open(knowledge_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)

    logger.info(f"Saved thread learning: {knowledge_file}")
