"""Slack Persona Vector Search Tools.

MCP tools for:
- slack_persona_sync: Full or incremental sync
- slack_persona_search: Search past conversations
- slack_persona_status: Get sync status
- slack_persona_context: Get context for a query (for persona injection)
"""

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register Slack persona tools.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @server.tool()
    @auto_heal()
    async def slack_persona_sync(
        mode: str = "incremental",
        months: int = 48,
        days: int = 1,
        include_threads: bool = True,
    ) -> str:
        """Sync Slack messages to persona vector store.

        Syncs all messages from all channels, DMs, group chats, and threads
        to a vector database for semantic search.

        Args:
            mode: "full" for complete resync, "incremental" for recent only
            months: Time window in months (for full sync, default 48 = 4 years)
            days: Days to sync (for incremental, default 1)
            include_threads: Include thread replies (default True)

        Returns:
            Sync statistics
        """
        from .sync import SlackPersonaSync

        sync = SlackPersonaSync()

        if mode == "full":

            def progress(current, total, channel_id):
                logger.info(f"Progress: {current}/{total} - {channel_id}")

            result = await sync.full_sync(
                months=months,
                include_threads=include_threads,
                progress_callback=progress,
            )
        else:
            result = await sync.incremental_sync(
                days=days,
                include_threads=include_threads,
            )

        # Format output
        lines = [
            f"## Slack Persona Sync: {mode.title()}",
            "",
            f"**Status:** {result['status']}",
            f"**Messages synced:** {result['messages_synced']:,}",
        ]

        if mode == "full":
            lines.extend(
                [
                    f"**Conversations:** {result['conversations']}",
                    f"**Time window:** {result['months']} months",
                ]
            )
        else:
            lines.extend(
                [
                    f"**Messages pruned:** {result.get('messages_pruned', 0):,}",
                    f"**Days synced:** {result['days']}",
                ]
            )

        lines.extend(
            [
                f"**Elapsed:** {result['elapsed_seconds']}s",
                "",
                "### Vector Store Stats",
                f"- Total messages: {result['vector_stats']['total_messages']:,}",
                f"- Database size: {result['vector_stats']['db_size_mb']} MB",
                f"- Path: `{result['vector_stats']['db_path']}`",
            ]
        )

        return "\n".join(lines)

    @server.tool()
    @auto_heal()
    async def slack_persona_search(
        query: str,
        limit: int = 5,
        channel_type: str = "",
        my_messages_only: bool = False,
    ) -> str:
        """Search past Slack conversations.

        Semantic search across all synced Slack messages to find
        similar past conversations.

        Args:
            query: Search query (natural language)
            limit: Max results to return (default 5)
            channel_type: Filter by type: "dm", "group_dm", "channel", or "" for all
            my_messages_only: Only return your own messages

        Returns:
            Matching messages with context
        """
        from .sync import SlackPersonaSync

        sync = SlackPersonaSync()

        results = sync.search(
            query=query,
            limit=limit,
            channel_type=channel_type or None,
            my_messages_only=my_messages_only,
        )

        if not results:
            return f"No matching messages found for: {query}"

        lines = [
            f"## Search Results for: {query}",
            f"Found {len(results)} matching messages",
            "",
        ]

        for i, msg in enumerate(results, 1):
            score = 1 - msg.get("score", 0)  # Convert distance to similarity
            lines.extend(
                [
                    f"### {i}. {msg['channel_type']} - {msg['datetime_str']}",
                    f"**User:** {msg['user_name'] or msg['user_id']}",
                    f"**Relevance:** {score:.2%}",
                    "",
                    f"> {msg['text'][:500]}{'...' if len(msg['text']) > 500 else ''}",
                    "",
                ]
            )

        return "\n".join(lines)

    @server.tool()
    @auto_heal()
    async def slack_persona_status() -> str:
        """Get Slack persona sync status.

        Shows sync metadata and vector store statistics.

        Returns:
            Status information
        """
        from .sync import SlackPersonaSync

        sync = SlackPersonaSync()
        status = sync.get_status()

        metadata = status.get("metadata", {})
        stats = status.get("vector_stats", {})

        lines = [
            "## Slack Persona Sync Status",
            "",
            "### Sync Metadata",
        ]

        if metadata:
            lines.extend(
                [
                    f"- **Last full sync:** {metadata.get('last_full_sync', 'Never')}",
                    f"- **Time window:** {metadata.get('months', 'N/A')} months",
                    f"- **Total messages:** {metadata.get('total_messages', 0):,}",
                    f"- **Conversations:** {metadata.get('conversations', 0)}",
                    f"- **Include threads:** {metadata.get('include_threads', True)}",
                    f"- **Last incremental:** {metadata.get('last_incremental_sync', 'Never')}",
                ]
            )
        else:
            lines.append("*No sync metadata found. Run a full sync first.*")

        lines.extend(
            [
                "",
                "### Vector Store",
                f"- **Messages indexed:** {stats.get('total_messages', 0):,}",
                f"- **Database size:** {stats.get('db_size_mb', 0)} MB",
                f"- **Path:** `{stats.get('db_path', 'N/A')}`",
            ]
        )

        return "\n".join(lines)

    @server.tool()
    @auto_heal()
    async def slack_persona_context(
        query: str,
        limit: int = 5,
        my_messages_only: bool = False,
        format: str = "prompt",
    ) -> str:
        """Get conversation context for persona response.

        Searches past Slack conversations and formats them as context
        for the AI persona to use when responding. This provides
        KNOWLEDGE context, not style (style is in the persona file).

        Args:
            query: The question/topic to find context for
            limit: Number of relevant messages to include (default 5)
            my_messages_only: If True, only search your messages. Default False
                             because most knowledge comes from OTHERS' responses.
            format: "prompt" for AI context, "raw" for JSON

        Returns:
            Formatted context for persona injection
        """
        from .sync import SlackPersonaSync

        sync = SlackPersonaSync()

        # Search for relevant past conversations
        # NOTE: my_messages_only defaults to False because:
        # - Style is already defined in the persona file (dave.md)
        # - ~90% of knowledge comes from others' responses to questions
        # - Filtering to only my messages throws away most of the knowledge
        results = sync.search(
            query=query,
            limit=limit,
            my_messages_only=my_messages_only,
        )

        if not results:
            return ""

        if format == "raw":
            import json

            return json.dumps(results, indent=2)

        # Format as knowledge context (not style reference)
        lines = [
            "## Relevant Slack Context",
            "",
            "Here's relevant information from past Slack conversations:",
            "",
        ]

        for msg in results:
            user = msg.get("user_name") or msg.get("user_id", "unknown")
            lines.extend(
                [
                    f"**{user}** ({msg['channel_type']}, {msg.get('datetime_str', '')}):",
                    f"> {msg['text']}",
                    "",
                ]
            )

        return "\n".join(lines)

    return registry.count
