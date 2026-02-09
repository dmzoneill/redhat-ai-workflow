"""
Slack Memory Adapter - Memory source for Slack conversation history.

This adapter exposes Slack message vector search as a memory source,
allowing the memory abstraction layer to query past conversations.

It wraps the existing SlackVectorStore functionality.
"""

import logging
from pathlib import Path
from typing import Any

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)

# Default vector store path (matches slack_persona_sync.py)
VECTOR_DB_PATH = Path.home() / ".config" / "aa-workflow" / "vectors" / "slack-persona"


@memory_adapter(
    name="slack",
    display_name="Slack Conversations",
    capabilities={"query", "search"},
    intent_keywords=[
        "slack",
        "message",
        "conversation",
        "discussed",
        "talked about",
        "said",
        "mentioned",
        "chat",
        "thread",
        "dm",
        "channel",
        "last time",
        "before",
        "previously",
        "earlier",
    ],
    priority=50,
    latency_class="fast",  # Local vector search
)
class SlackMemoryAdapter:
    """
    Adapter for Slack conversation vector search.

    Provides semantic search over indexed Slack messages,
    including DMs, group DMs, and channel messages.
    """

    def __init__(self, db_path: Path | str | None = None):
        """
        Initialize the adapter.

        Args:
            db_path: Path to vector database (default: ~/.cache/aa-workflow/slack-vectors)
        """
        self.db_path = Path(db_path) if db_path else VECTOR_DB_PATH
        self._store = None

    @property
    def vector_store(self):
        """Lazy load the vector store."""
        if self._store is None:
            try:
                # Try relative import first (when loaded as package)
                from .vector_store import SlackVectorStore

                self._store = SlackVectorStore(self.db_path)
            except ImportError:
                try:
                    # Fall back to absolute import (when loaded dynamically)
                    from tool_modules.aa_slack_persona.src.vector_store import (
                        SlackVectorStore,
                    )

                    self._store = SlackVectorStore(self.db_path)
                except ImportError as e:
                    logger.warning(f"SlackVectorStore not available: {e}")
                    return None
        return self._store

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query Slack conversations.

        Args:
            question: Natural language question about conversations
            filter: Optional filter with channel_type, user_id, limit

        Returns:
            AdapterResult with matching messages
        """
        if not self.vector_store:
            return AdapterResult(
                source="slack",
                items=[],
                error="Slack vector store not available",
            )

        try:
            # Get filter parameters
            limit = (filter.limit if filter and filter.limit else None) or 5
            channel_type = None
            user_id = None

            if filter and filter.extra:
                channel_type = filter.extra.get("channel_type")
                user_id = filter.extra.get("user_id")

            # Perform search
            results = self.vector_store.search(
                query=question,
                limit=limit,
                channel_type=channel_type,
                user_id=user_id,
            )

            if not results:
                return AdapterResult(
                    source="slack",
                    items=[],
                )

            # Convert to MemoryItems
            items = [self._to_memory_item(r) for r in results]

            return AdapterResult(
                source="slack",
                items=items,
            )

        except Exception as e:
            logger.error(f"Slack search failed: {e}")
            return AdapterResult(
                source="slack",
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Semantic search (same as query for Slack)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Slack adapter is read-only (messages are synced separately)."""
        return AdapterResult(
            source="slack",
            items=[],
            error="Slack adapter is read-only. Use slack_sync to update messages.",
        )

    async def health_check(self) -> HealthStatus:
        """Check if Slack vector store is healthy."""
        if not self.vector_store:
            return HealthStatus(
                healthy=False,
                error="Slack vector store not available",
            )

        try:
            stats = self.vector_store.get_stats()

            return HealthStatus(
                healthy=True,
                details={
                    "total_messages": stats.get("total_messages", 0),
                    "db_path": str(self.db_path),
                    "db_size_mb": stats.get("db_size_mb", 0),
                },
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))

    def _to_memory_item(self, result: dict) -> MemoryItem:
        """Convert Slack search result to MemoryItem."""
        user_name = result.get("user_name", "unknown")
        channel_name = result.get("channel_name", "")
        channel_type = result.get("channel_type", "")
        datetime_str = result.get("datetime_str", "")

        # Build summary
        location = channel_name or channel_type or "Slack"
        summary = f"{user_name} in {location}"
        if datetime_str:
            summary += f" ({datetime_str})"

        # Calculate relevance from distance score
        # LanceDB returns distance (lower is better), convert to similarity
        distance = result.get("score", 1.0)
        relevance = max(0.0, 1.0 - (distance / 2.0))  # Normalize

        return MemoryItem(
            source="slack",
            type="message",
            relevance=relevance,
            summary=summary,
            content=result.get("text", ""),
            metadata={
                "user": user_name,
                "user_id": result.get("user_id", ""),
                "channel": channel_name,
                "channel_id": result.get("channel_id", ""),
                "channel_type": channel_type,
                "datetime": datetime_str,
                "timestamp": result.get("timestamp", ""),
                "is_thread_reply": result.get("is_thread_reply", False),
            },
        )
