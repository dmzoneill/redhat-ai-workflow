"""State Persistence Layer for Slack Listener.

Manages persistent state using SQLite to survive server restarts:
- Last processed message timestamps per channel
- Pending messages queue for LLM processing
- User cache for name resolution
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class PendingMessage:
    """Represents a message waiting to be processed by the LLM."""
    
    id: str  # Unique message ID (channel_ts)
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str
    timestamp: str  # Slack ts (e.g., "1234567890.123456")
    thread_ts: str | None
    is_mention: bool
    is_dm: bool
    matched_keywords: list[str]
    created_at: float  # Unix timestamp when we detected this
    raw_message: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "text": self.text,
            "timestamp": self.timestamp,
            "thread_ts": self.thread_ts,
            "is_mention": self.is_mention,
            "is_dm": self.is_dm,
            "matched_keywords": self.matched_keywords,
            "created_at": self.created_at,
            "raw_message": self.raw_message,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PendingMessage":
        """Deserialize from dict."""
        return cls(
            id=data["id"],
            channel_id=data["channel_id"],
            channel_name=data.get("channel_name", ""),
            user_id=data["user_id"],
            user_name=data.get("user_name", ""),
            text=data["text"],
            timestamp=data["timestamp"],
            thread_ts=data.get("thread_ts"),
            is_mention=data.get("is_mention", False),
            is_dm=data.get("is_dm", False),
            matched_keywords=data.get("matched_keywords", []),
            created_at=data.get("created_at", time.time()),
            raw_message=data.get("raw_message", {}),
        )


class SlackStateDB:
    """
    SQLite-based persistence for Slack listener state.
    
    Stores:
    - Channel state (last processed timestamp per channel)
    - Pending messages queue
    - User cache (user_id -> user_name)
    """
    
    def __init__(self, db_path: str | None = None):
        """
        Initialize the state database.
        
        Args:
            db_path: Path to SQLite database file.
                     Defaults to SLACK_STATE_DB_PATH env var or ./slack_state.db
        """
        self.db_path = db_path or os.getenv(
            "SLACK_STATE_DB_PATH",
            os.path.join(os.getcwd(), "slack_state.db")
        )
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def connect(self):
        """Connect to database and create tables."""
        async with self._lock:
            if self._db is None:
                self._db = await aiosqlite.connect(self.db_path)
                await self._create_tables()
                logger.info(f"Connected to state database: {self.db_path}")
    
    async def close(self):
        """Close database connection."""
        async with self._lock:
            if self._db:
                await self._db.close()
                self._db = None
    
    async def _create_tables(self):
        """Create database tables if they don't exist."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS channel_state (
                channel_id TEXT PRIMARY KEY,
                last_processed_ts TEXT NOT NULL,
                channel_name TEXT,
                updated_at REAL NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS pending_messages (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at REAL NOT NULL,
                processed_at REAL
            );
            
            CREATE INDEX IF NOT EXISTS idx_pending_unprocessed 
            ON pending_messages(processed_at) WHERE processed_at IS NULL;
            
            CREATE TABLE IF NOT EXISTS user_cache (
                user_id TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                display_name TEXT,
                real_name TEXT,
                updated_at REAL NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS listener_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        await self._db.commit()
    
    # ==================== Channel State ====================
    
    async def get_last_processed_ts(self, channel_id: str) -> str | None:
        """Get the last processed message timestamp for a channel."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT last_processed_ts FROM channel_state WHERE channel_id = ?",
                (channel_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def set_last_processed_ts(
        self,
        channel_id: str,
        timestamp: str,
        channel_name: str = "",
    ):
        """Update the last processed timestamp for a channel."""
        async with self._lock:
            await self.connect()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO channel_state 
                (channel_id, last_processed_ts, channel_name, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, timestamp, channel_name, time.time())
            )
            await self._db.commit()
    
    async def get_all_channel_states(self) -> dict[str, str]:
        """Get all channel states as dict of channel_id -> last_processed_ts."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT channel_id, last_processed_ts FROM channel_state"
            )
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}
    
    # ==================== Pending Messages ====================
    
    async def add_pending_message(self, message: PendingMessage):
        """Add a message to the pending queue."""
        async with self._lock:
            await self.connect()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO pending_messages 
                (id, channel_id, data, created_at, processed_at)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    message.id,
                    message.channel_id,
                    json.dumps(message.to_dict()),
                    message.created_at,
                )
            )
            await self._db.commit()
    
    async def get_pending_messages(
        self,
        limit: int = 50,
        channel_id: str | None = None,
    ) -> list[PendingMessage]:
        """Get unprocessed pending messages."""
        async with self._lock:
            await self.connect()
            
            if channel_id:
                cursor = await self._db.execute(
                    """
                    SELECT data FROM pending_messages 
                    WHERE processed_at IS NULL AND channel_id = ?
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (channel_id, limit)
                )
            else:
                cursor = await self._db.execute(
                    """
                    SELECT data FROM pending_messages 
                    WHERE processed_at IS NULL
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (limit,)
                )
            
            rows = await cursor.fetchall()
            return [PendingMessage.from_dict(json.loads(row[0])) for row in rows]
    
    async def mark_message_processed(self, message_id: str):
        """Mark a message as processed."""
        async with self._lock:
            await self.connect()
            await self._db.execute(
                "UPDATE pending_messages SET processed_at = ? WHERE id = ?",
                (time.time(), message_id)
            )
            await self._db.commit()
    
    async def get_pending_count(self) -> int:
        """Get count of unprocessed messages."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM pending_messages WHERE processed_at IS NULL"
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def clear_old_messages(self, older_than_hours: int = 24):
        """Remove processed messages older than specified hours."""
        async with self._lock:
            await self.connect()
            cutoff = time.time() - (older_than_hours * 3600)
            await self._db.execute(
                "DELETE FROM pending_messages WHERE processed_at IS NOT NULL AND processed_at < ?",
                (cutoff,)
            )
            await self._db.commit()
    
    # ==================== User Cache ====================
    
    async def get_user_name(self, user_id: str) -> str | None:
        """Get cached user name."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT user_name FROM user_cache WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def cache_user(
        self,
        user_id: str,
        user_name: str,
        display_name: str = "",
        real_name: str = "",
    ):
        """Cache user information."""
        async with self._lock:
            await self.connect()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_cache 
                (user_id, user_name, display_name, real_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, user_name, display_name, real_name, time.time())
            )
            await self._db.commit()
    
    async def get_all_cached_users(self) -> dict[str, dict[str, str]]:
        """Get all cached users."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT user_id, user_name, display_name, real_name FROM user_cache"
            )
            rows = await cursor.fetchall()
            return {
                row[0]: {
                    "user_name": row[1],
                    "display_name": row[2] or row[1],
                    "real_name": row[3] or "",
                }
                for row in rows
            }
    
    # ==================== Metadata ====================
    
    async def get_meta(self, key: str, default: str = "") -> str:
        """Get metadata value."""
        async with self._lock:
            await self.connect()
            cursor = await self._db.execute(
                "SELECT value FROM listener_meta WHERE key = ?",
                (key,)
            )
            row = await cursor.fetchone()
            return row[0] if row else default
    
    async def set_meta(self, key: str, value: str):
        """Set metadata value."""
        async with self._lock:
            await self.connect()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO listener_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, time.time())
            )
            await self._db.commit()

