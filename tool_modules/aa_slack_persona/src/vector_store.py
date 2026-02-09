"""Vector store for Slack messages using LanceDB.

Handles:
- Message embedding generation
- Vector storage and retrieval
- Similarity search for context
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports for heavy dependencies
_lancedb = None
_model = None


def _get_lancedb():
    """Lazy load lancedb."""
    global _lancedb
    if _lancedb is None:
        import lancedb

        _lancedb = lancedb
    return _lancedb


def _get_embedding_model():
    """Lazy load sentence transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded embedding model: all-MiniLM-L6-v2")
    return _model


@dataclass
class SlackMessage:
    """Represents a Slack message for vector storage."""

    id: str  # Unique ID (channel_ts)
    text: str  # Message content
    user_id: str  # Slack user ID
    user_name: str  # Display name
    channel_id: str  # Channel ID
    channel_name: str  # Channel name (if available)
    channel_type: str  # dm, group_dm, channel
    timestamp: str  # Slack ts
    thread_ts: str | None  # Parent thread ts (if reply)
    is_thread_reply: bool  # Is this a thread reply
    datetime_str: str  # Human readable datetime


class SlackVectorStore:
    """Vector store for Slack messages."""

    def __init__(self, db_path: Path | str):
        """Initialize vector store.

        Args:
            db_path: Path to LanceDB database directory
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        self._db = None
        self._table = None
        self.table_name = "slack_messages"

    @property
    def db(self):
        """Lazy load database connection."""
        if self._db is None:
            lancedb = _get_lancedb()
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    @property
    def table(self):
        """Get or create messages table."""
        if self._table is None:
            try:
                self._table = self.db.open_table(self.table_name)
            except Exception:
                # Table doesn't exist, will be created on first insert
                self._table = None
        return self._table

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text."""
        model = _get_embedding_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def _generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        model = _get_embedding_model()
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
        return embeddings.tolist()

    def add_messages(self, messages: list[dict[str, Any]]) -> int:
        """Add messages to vector store.

        Args:
            messages: List of message dicts with required fields

        Returns:
            Number of messages added
        """
        if not messages:
            return 0

        # Generate embeddings in batch
        texts = [m.get("text", "") for m in messages]
        embeddings = self._generate_embeddings_batch(texts)

        # Prepare records
        records = []
        for msg, embedding in zip(messages, embeddings):
            record = {
                "id": msg.get("id", f"{msg.get('channel_id', '')}_{msg.get('ts', '')}"),
                "text": msg.get("text", ""),
                "user_id": msg.get("user_id", ""),
                "user_name": msg.get("user_name", ""),
                "channel_id": msg.get("channel_id", ""),
                "channel_name": msg.get("channel_name", ""),
                "channel_type": msg.get("channel_type", "unknown"),
                "timestamp": msg.get("ts", ""),
                "thread_ts": msg.get("thread_ts", ""),
                "is_thread_reply": msg.get("is_thread_reply", False),
                "datetime_str": msg.get("datetime_str", ""),
                "vector": embedding,
            }
            records.append(record)

        # Add to table
        if self.table is None:
            # Create table with first batch
            self._table = self.db.create_table(self.table_name, records)
        else:
            self._table.add(records)

        logger.info(f"Added {len(records)} messages to vector store")
        return len(records)

    def search(
        self,
        query: str,
        limit: int = 10,
        channel_type: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar messages.

        Args:
            query: Search query text
            limit: Max results to return
            channel_type: Filter by channel type (dm, group_dm, channel)
            user_id: Filter by user ID

        Returns:
            List of matching messages with scores
        """
        if self.table is None:
            return []

        # Generate query embedding
        query_embedding = self._generate_embedding(query)

        # Build search
        search = self.table.search(query_embedding).limit(
            limit * 2
        )  # Get extra for filtering

        # Apply filters if specified
        if channel_type:
            search = search.where(f"channel_type = '{channel_type}'")
        if user_id:
            search = search.where(f"user_id = '{user_id}'")

        # Execute search
        results = search.to_list()

        # Format results
        formatted = []
        for r in results[:limit]:
            formatted.append(
                {
                    "id": r.get("id", ""),
                    "text": r.get("text", ""),
                    "user_id": r.get("user_id", ""),
                    "user_name": r.get("user_name", ""),
                    "channel_id": r.get("channel_id", ""),
                    "channel_name": r.get("channel_name", ""),
                    "channel_type": r.get("channel_type", ""),
                    "timestamp": r.get("timestamp", ""),
                    "datetime_str": r.get("datetime_str", ""),
                    "is_thread_reply": r.get("is_thread_reply", False),
                    "score": float(r.get("_distance", 0)),
                }
            )

        return formatted

    def delete_older_than(self, cutoff_ts: str) -> int:
        """Delete messages older than cutoff timestamp.

        Args:
            cutoff_ts: Slack timestamp string (oldest to keep)

        Returns:
            Number of messages deleted
        """
        if self.table is None:
            return 0

        # Count before
        try:
            count_before = self.table.count_rows()
        except Exception:
            count_before = 0

        # Delete old messages
        self.table.delete(f"timestamp < '{cutoff_ts}'")

        # Count after
        try:
            count_after = self.table.count_rows()
        except Exception:
            count_after = 0

        deleted = count_before - count_after
        logger.info(f"Deleted {deleted} messages older than {cutoff_ts}")
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Get vector store statistics."""
        if self.table is None:
            return {
                "total_messages": 0,
                "db_path": str(self.db_path),
                "table_exists": False,
            }

        try:
            count = self.table.count_rows()
        except Exception:
            count = 0

        # Get disk usage
        db_size = sum(f.stat().st_size for f in self.db_path.rglob("*") if f.is_file())

        return {
            "total_messages": count,
            "db_path": str(self.db_path),
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "table_exists": True,
        }

    def clear(self) -> None:
        """Clear all messages from store."""
        if self.table is not None:
            self.db.drop_table(self.table_name)
            self._table = None
            logger.info("Cleared vector store")
