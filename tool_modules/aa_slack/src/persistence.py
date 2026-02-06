"""State Persistence Layer for Slack Listener.

Manages persistent state using SQLite to survive server restarts:
- Last processed message timestamps per channel
- Pending messages queue for LLM processing
- User cache for name resolution
- Channel cache for discovery (knowledge cache)
- Group cache for @team mention resolution
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


def parse_slack_sidebar_html(html_content: str) -> list[dict[str, str]]:
    """
    Parse Slack sidebar HTML to extract channel/DM information.

    This is a fallback for when the Slack API's conversations.list is blocked
    by enterprise restrictions. Users can copy the sidebar HTML from the
    Slack web client and import it.

    Args:
        html_content: Raw HTML from the Slack sidebar

    Returns:
        List of dicts with channel_id, name, and type (channel/dm/group)
    """
    channels = []

    # Pattern to find channel IDs and their names
    # The sidebar HTML has patterns like:
    # data-qa-channel-sidebar-channel-id="C01CPSKFG0P"
    # data-qa="channel_sidebar_name_team-clouddot-automation-analytics"

    # Find all channel IDs
    channel_ids = re.findall(r'data-qa-channel-sidebar-channel-id="([^"]+)"', html_content)  # noqa: F841

    # Find all channel names (they follow a specific pattern)
    name_pattern = r'data-qa="channel_sidebar_name_([^"]+)"'
    names = re.findall(name_pattern, html_content)  # noqa: F841

    # Build a mapping - names appear after their IDs in the HTML
    # We need to correlate them by position in the HTML
    id_positions = [
        (m.start(), m.group(1)) for m in re.finditer(r'data-qa-channel-sidebar-channel-id="([^"]+)"', html_content)
    ]
    name_positions = [
        (m.start(), m.group(1)) for m in re.finditer(r'data-qa="channel_sidebar_name_([^"]+)"', html_content)
    ]

    # For each channel ID, find the next name that appears after it
    for id_pos, channel_id in id_positions:
        # Find the first name that appears after this ID
        channel_name = None
        for name_pos, name in name_positions:
            if name_pos > id_pos:
                # Skip special entries
                if name.startswith("sidebar_add_more") or name in ("you", "all_thread_link"):
                    continue
                if name.startswith("page_"):
                    continue
                channel_name = name
                break

        if channel_name:
            # Determine type based on ID prefix
            if channel_id.startswith("D"):
                channel_type = "dm"
            elif channel_id.startswith("G"):
                channel_type = "group_dm"
            elif channel_id.startswith("C"):
                channel_type = "channel"
            else:
                channel_type = "unknown"

            # Clean up the name (replace dashes with spaces for display)
            display_name = channel_name.replace("-", " ").title() if channel_type == "dm" else channel_name

            channels.append(
                {
                    "channel_id": channel_id,
                    "name": channel_name,
                    "display_name": display_name,
                    "type": channel_type,
                }
            )

    # Deduplicate by channel_id
    seen = set()
    unique_channels = []
    for ch in channels:
        if ch["channel_id"] not in seen:
            seen.add(ch["channel_id"])
            unique_channels.append(ch)

    return unique_channels


def parse_sidebar_file(file_path: str | Path) -> list[dict[str, str]]:
    """
    Parse a sidebar HTML file saved from Slack.

    Args:
        file_path: Path to the HTML file

    Returns:
        List of channel dicts
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Sidebar file not found: {file_path}")

    html_content = path.read_text(encoding="utf-8")
    return parse_slack_sidebar_html(html_content)


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


@dataclass
class CachedChannel:
    """Represents a cached Slack channel for discovery."""

    channel_id: str
    name: str
    display_name: str = ""
    is_private: bool = False
    is_member: bool = False
    purpose: str = ""
    topic: str = ""
    num_members: int = 0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "display_name": self.display_name,
            "is_private": self.is_private,
            "is_member": self.is_member,
            "purpose": self.purpose,
            "topic": self.topic,
            "num_members": self.num_members,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedChannel":
        """Deserialize from dict."""
        return cls(
            channel_id=data["channel_id"],
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            is_private=data.get("is_private", False),
            is_member=data.get("is_member", False),
            purpose=data.get("purpose", ""),
            topic=data.get("topic", ""),
            num_members=data.get("num_members", 0),
            updated_at=data.get("updated_at", 0.0),
        )


@dataclass
class CachedUser:
    """Represents a cached Slack user for discovery."""

    user_id: str
    user_name: str
    display_name: str = ""
    real_name: str = ""
    email: str = ""
    gitlab_username: str = ""
    avatar_url: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "display_name": self.display_name,
            "real_name": self.real_name,
            "email": self.email,
            "gitlab_username": self.gitlab_username,
            "avatar_url": self.avatar_url,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedUser":
        """Deserialize from dict."""
        return cls(
            user_id=data["user_id"],
            user_name=data.get("user_name", ""),
            display_name=data.get("display_name", ""),
            real_name=data.get("real_name", ""),
            email=data.get("email", ""),
            gitlab_username=data.get("gitlab_username", ""),
            avatar_url=data.get("avatar_url", ""),
            updated_at=data.get("updated_at", 0.0),
        )


@dataclass
class CachedGroup:
    """Represents a cached Slack user group for @team mention resolution."""

    group_id: str
    handle: str
    name: str = ""
    description: str = ""
    members: list[str] = field(default_factory=list)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "group_id": self.group_id,
            "handle": self.handle,
            "name": self.name,
            "description": self.description,
            "members": self.members,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedGroup":
        """Deserialize from dict."""
        members = data.get("members", [])
        if isinstance(members, str):
            members = json.loads(members) if members else []
        return cls(
            group_id=data["group_id"],
            handle=data.get("handle", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            members=members,
            updated_at=data.get("updated_at", 0.0),
        )


class SlackStateDB:
    """
    SQLite-based persistence for Slack listener state.

    Stores:
    - Channel state (last processed timestamp per channel)
    - Pending messages queue
    - User cache (user_id -> user_name)
    - Channel cache (for discovery - knowledge cache)
    - Group cache (for @team mention resolution)
    """

    def __init__(self, db_path: str | None = None):
        """
        Initialize the state database.

        Args:
            db_path: Path to SQLite database file.
                     Defaults to SLACK_STATE_DB_PATH env var or ./slack_state.db
        """
        self.db_path = db_path or os.getenv("SLACK_STATE_DB_PATH", os.path.join(os.getcwd(), "slack_state.db"))
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        """Connect to database and create tables (public, acquires lock)."""
        async with self._lock:
            await self._connect_unlocked()

    async def _connect_unlocked(self):
        """Connect to database (internal, caller must hold lock)."""
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
        await self._db.executescript(
            """
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
                email TEXT,
                gitlab_username TEXT,
                avatar_url TEXT,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS listener_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            -- Knowledge Cache: Channel discovery
            CREATE TABLE IF NOT EXISTS channel_cache (
                channel_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                display_name TEXT,
                is_private INTEGER DEFAULT 0,
                is_member INTEGER DEFAULT 0,
                purpose TEXT,
                topic TEXT,
                num_members INTEGER DEFAULT 0,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_channel_cache_name
            ON channel_cache(name);

            CREATE INDEX IF NOT EXISTS idx_channel_cache_member
            ON channel_cache(is_member) WHERE is_member = 1;

            -- Knowledge Cache: User group discovery (for @team mentions)
            CREATE TABLE IF NOT EXISTS group_cache (
                group_id TEXT PRIMARY KEY,
                handle TEXT NOT NULL,
                name TEXT,
                description TEXT,
                members TEXT,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_group_cache_handle
            ON group_cache(handle);

            -- Notification deduplication: track notified messages to prevent spam on restart
            CREATE TABLE IF NOT EXISTS notified_messages (
                message_ts TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                notified_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notified_messages_time
            ON notified_messages(notified_at);
        """
        )
        await self._db.commit()

        # Clean up old notified messages (older than 1 hour)
        try:
            import time

            cutoff = time.time() - 3600  # 1 hour
            await self._db.execute(
                "DELETE FROM notified_messages WHERE notified_at < ?",
                (cutoff,),
            )
            await self._db.commit()
        except Exception:
            pass  # Table might not exist yet on first run

        # Migration: Add avatar_url column to user_cache if it doesn't exist
        try:
            cursor = await self._db.execute("PRAGMA table_info(user_cache)")
            columns = [row[1] for row in await cursor.fetchall()]
            if "avatar_url" not in columns:
                await self._db.execute("ALTER TABLE user_cache ADD COLUMN avatar_url TEXT")
                await self._db.commit()
                logger.info("Migrated user_cache: added avatar_url column")
        except Exception as e:
            logger.debug(f"Migration check for avatar_url: {e}")

    # ==================== Channel State ====================

    async def get_last_processed_ts(self, channel_id: str) -> str | None:
        """Get the last processed message timestamp for a channel."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                "SELECT last_processed_ts FROM channel_state WHERE channel_id = ?",
                (channel_id,),
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
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO channel_state
                (channel_id, last_processed_ts, channel_name, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (channel_id, timestamp, channel_name, time.time()),
            )
            await self._db.commit()

    async def get_all_channel_states(self) -> dict[str, str]:
        """Get all channel states as dict of channel_id -> last_processed_ts."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute("SELECT channel_id, last_processed_ts FROM channel_state")
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    # ==================== Notification Deduplication ====================

    async def was_notified(self, message_ts: str) -> bool:
        """Check if a message was already notified (survives restarts)."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                "SELECT 1 FROM notified_messages WHERE message_ts = ?",
                (message_ts,),
            )
            row = await cursor.fetchone()
            return row is not None

    async def mark_notified(self, message_ts: str, channel_id: str):
        """Mark a message as notified (persisted to survive restarts)."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO notified_messages
                (message_ts, channel_id, notified_at)
                VALUES (?, ?, ?)
                """,
                (message_ts, channel_id, time.time()),
            )
            await self._db.commit()

    # ==================== Pending Messages ====================

    async def add_pending_message(self, message: PendingMessage):
        """Add a message to the pending queue."""
        async with self._lock:
            await self._connect_unlocked()
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
                ),
            )
            await self._db.commit()

    async def get_pending_messages(
        self,
        limit: int = 50,
        channel_id: str | None = None,
    ) -> list[PendingMessage]:
        """Get unprocessed pending messages."""
        async with self._lock:
            await self._connect_unlocked()

            if channel_id:
                cursor = await self._db.execute(
                    """
                    SELECT data FROM pending_messages
                    WHERE processed_at IS NULL AND channel_id = ?
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (channel_id, limit),
                )
            else:
                cursor = await self._db.execute(
                    """
                    SELECT data FROM pending_messages
                    WHERE processed_at IS NULL
                    ORDER BY created_at ASC LIMIT ?
                    """,
                    (limit,),
                )

            rows = await cursor.fetchall()
            return [PendingMessage.from_dict(json.loads(row[0])) for row in rows]

    async def mark_message_processed(self, message_id: str):
        """Mark a message as processed."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                "UPDATE pending_messages SET processed_at = ? WHERE id = ?",
                (time.time(), message_id),
            )
            await self._db.commit()

    async def get_pending_count(self) -> int:
        """Get count of unprocessed messages."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute("SELECT COUNT(*) FROM pending_messages WHERE processed_at IS NULL")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def clear_old_messages(self, older_than_hours: int = 24):
        """Remove processed messages older than specified hours."""
        async with self._lock:
            await self._connect_unlocked()
            cutoff = time.time() - (older_than_hours * 3600)
            await self._db.execute(
                "DELETE FROM pending_messages WHERE processed_at IS NOT NULL AND processed_at < ?",
                (cutoff,),
            )
            await self._db.commit()

    # ==================== User Cache ====================

    async def get_user_name(self, user_id: str) -> str | None:
        """Get cached user name."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute("SELECT user_name FROM user_cache WHERE user_id = ?", (user_id,))
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
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_cache
                (user_id, user_name, display_name, real_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, user_name, display_name, real_name, time.time()),
            )
            await self._db.commit()

    async def get_all_cached_users(self) -> dict[str, dict[str, str]]:
        """Get all cached users."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                "SELECT user_id, user_name, display_name, real_name, avatar_url FROM user_cache"
            )
            rows = await cursor.fetchall()
            return {
                row[0]: {
                    "user_name": row[1],
                    "display_name": row[2] or row[1],
                    "real_name": row[3] or "",
                    "avatar_url": row[4] or "",
                }
                for row in rows
            }

    async def cache_users_bulk(self, users: list[CachedUser]):
        """Cache multiple users at once (more efficient for bulk refresh)."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.executemany(
                """
                INSERT OR REPLACE INTO user_cache
                (user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        u.user_id,
                        u.user_name,
                        u.display_name,
                        u.real_name,
                        u.email,
                        u.gitlab_username,
                        u.avatar_url,
                        time.time(),
                    )
                    for u in users
                ],
            )
            await self._db.commit()

    async def get_user_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the user cache."""
        async with self._lock:
            await self._connect_unlocked()

            cursor = await self._db.execute("SELECT COUNT(*) FROM user_cache")
            total = (await cursor.fetchone())[0]

            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM user_cache WHERE avatar_url IS NOT NULL AND avatar_url != ''"
            )
            with_avatar = (await cursor.fetchone())[0]

            cursor = await self._db.execute("SELECT COUNT(*) FROM user_cache WHERE email IS NOT NULL AND email != ''")
            with_email = (await cursor.fetchone())[0]

            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM user_cache WHERE gitlab_username IS NOT NULL AND gitlab_username != ''"
            )
            with_gitlab = (await cursor.fetchone())[0]

            cursor = await self._db.execute("SELECT MIN(updated_at), MAX(updated_at) FROM user_cache")
            row = await cursor.fetchone()
            oldest = row[0] if row[0] else 0
            newest = row[1] if row[1] else 0

            return {
                "total_users": total,
                "with_avatar": with_avatar,
                "with_email": with_email,
                "with_gitlab": with_gitlab,
                "oldest_entry": oldest,
                "newest_entry": newest,
                "cache_age_seconds": time.time() - newest if newest else None,
            }

    # ==================== Metadata ====================

    async def get_meta(self, key: str, default: str = "") -> str:
        """Get metadata value."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute("SELECT value FROM listener_meta WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row[0] if row else default

    async def set_meta(self, key: str, value: str):
        """Set metadata value."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO listener_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, time.time()),
            )
            await self._db.commit()

    # ==================== Channel Cache (Knowledge) ====================

    async def cache_channel(self, channel: CachedChannel):
        """Cache channel information for discovery."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO channel_cache
                (channel_id, name, display_name, is_private, is_member,
                 purpose, topic, num_members, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel.channel_id,
                    channel.name,
                    channel.display_name,
                    1 if channel.is_private else 0,
                    1 if channel.is_member else 0,
                    channel.purpose,
                    channel.topic,
                    channel.num_members,
                    time.time(),
                ),
            )
            await self._db.commit()

    async def cache_channels_bulk(self, channels: list[CachedChannel]):
        """Cache multiple channels at once (more efficient)."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.executemany(
                """
                INSERT OR REPLACE INTO channel_cache
                (channel_id, name, display_name, is_private, is_member,
                 purpose, topic, num_members, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.channel_id,
                        c.name,
                        c.display_name,
                        1 if c.is_private else 0,
                        1 if c.is_member else 0,
                        c.purpose,
                        c.topic,
                        c.num_members,
                        time.time(),
                    )
                    for c in channels
                ],
            )
            await self._db.commit()

    async def get_cached_channel(self, channel_id: str) -> CachedChannel | None:
        """Get a cached channel by ID."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                """
                SELECT channel_id, name, display_name, is_private, is_member,
                       purpose, topic, num_members, updated_at
                FROM channel_cache WHERE channel_id = ?
                """,
                (channel_id,),
            )
            row = await cursor.fetchone()
            if row:
                return CachedChannel(
                    channel_id=row[0],
                    name=row[1],
                    display_name=row[2] or "",
                    is_private=bool(row[3]),
                    is_member=bool(row[4]),
                    purpose=row[5] or "",
                    topic=row[6] or "",
                    num_members=row[7] or 0,
                    updated_at=row[8],
                )
            return None

    async def find_channels(
        self,
        query: str = "",
        member_only: bool = False,
        limit: int = 50,
    ) -> list[CachedChannel]:
        """
        Find channels matching a query.

        Args:
            query: Search string (matches name, display_name, purpose, topic)
            member_only: Only return channels the bot is a member of
            limit: Maximum results to return

        Returns:
            List of matching CachedChannel objects
        """
        async with self._lock:
            await self._connect_unlocked()

            # Build query based on filters - using predefined SQL patterns
            # to avoid SQL injection (all user input goes through parameters)
            if query and member_only:
                sql = """
                    SELECT channel_id, name, display_name, is_private, is_member,
                           purpose, topic, num_members, updated_at
                    FROM channel_cache
                    WHERE (name LIKE ? OR display_name LIKE ? OR purpose LIKE ? OR topic LIKE ?)
                      AND is_member = 1
                    ORDER BY is_member DESC, num_members DESC, name ASC
                    LIMIT ?
                """
                search_pattern = "%" + query + "%"
                params = [search_pattern, search_pattern, search_pattern, search_pattern, limit]
            elif query:
                sql = """
                    SELECT channel_id, name, display_name, is_private, is_member,
                           purpose, topic, num_members, updated_at
                    FROM channel_cache
                    WHERE name LIKE ? OR display_name LIKE ? OR purpose LIKE ? OR topic LIKE ?
                    ORDER BY is_member DESC, num_members DESC, name ASC
                    LIMIT ?
                """
                search_pattern = "%" + query + "%"
                params = [search_pattern, search_pattern, search_pattern, search_pattern, limit]
            elif member_only:
                sql = """
                    SELECT channel_id, name, display_name, is_private, is_member,
                           purpose, topic, num_members, updated_at
                    FROM channel_cache
                    WHERE is_member = 1
                    ORDER BY is_member DESC, num_members DESC, name ASC
                    LIMIT ?
                """
                params = [limit]
            else:
                sql = """
                    SELECT channel_id, name, display_name, is_private, is_member,
                           purpose, topic, num_members, updated_at
                    FROM channel_cache
                    ORDER BY is_member DESC, num_members DESC, name ASC
                    LIMIT ?
                """
                params = [limit]

            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
            return [
                CachedChannel(
                    channel_id=row[0],
                    name=row[1],
                    display_name=row[2] or "",
                    is_private=bool(row[3]),
                    is_member=bool(row[4]),
                    purpose=row[5] or "",
                    topic=row[6] or "",
                    num_members=row[7] or 0,
                    updated_at=row[8],
                )
                for row in rows
            ]

    async def get_my_channels(self, limit: int = 100) -> list[CachedChannel]:
        """Get all channels the bot is a member of."""
        return await self.find_channels(member_only=True, limit=limit)

    async def get_channel_by_name(self, name: str) -> CachedChannel | None:
        """Get a channel by exact name match."""
        async with self._lock:
            await self._connect_unlocked()
            # Try exact match first, then case-insensitive
            cursor = await self._db.execute(
                """
                SELECT channel_id, name, display_name, is_private, is_member,
                       purpose, topic, num_members, updated_at
                FROM channel_cache
                WHERE name = ? OR name = ? COLLATE NOCASE
                LIMIT 1
                """,
                (name, name),
            )
            row = await cursor.fetchone()
            if row:
                return CachedChannel(
                    channel_id=row[0],
                    name=row[1],
                    display_name=row[2] or "",
                    is_private=bool(row[3]),
                    is_member=bool(row[4]),
                    purpose=row[5] or "",
                    topic=row[6] or "",
                    num_members=row[7] or 0,
                    updated_at=row[8],
                )
            return None

    async def get_channel_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the channel cache."""
        async with self._lock:
            await self._connect_unlocked()

            cursor = await self._db.execute("SELECT COUNT(*) FROM channel_cache")
            total = (await cursor.fetchone())[0]

            cursor = await self._db.execute("SELECT COUNT(*) FROM channel_cache WHERE is_member = 1")
            member_count = (await cursor.fetchone())[0]

            cursor = await self._db.execute("SELECT MIN(updated_at), MAX(updated_at) FROM channel_cache")
            row = await cursor.fetchone()
            oldest = row[0] if row[0] else 0
            newest = row[1] if row[1] else 0

            return {
                "total_channels": total,
                "member_channels": member_count,
                "oldest_entry": oldest,
                "newest_entry": newest,
                "cache_age_seconds": time.time() - newest if newest else None,
            }

    async def import_channels_from_sidebar(self, file_path: str | Path) -> dict[str, Any]:
        """
        Import channels from a Slack sidebar HTML file.

        This is a fallback for when the Slack API's conversations.list is blocked
        by enterprise restrictions. Users can copy the sidebar HTML from the
        Slack web client (Inspect Element on sidebar -> Copy outer HTML).

        Args:
            file_path: Path to the HTML file containing sidebar content

        Returns:
            Dict with import stats (channels_imported, dms_imported, etc.)
        """
        try:
            parsed = parse_sidebar_file(file_path)
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Failed to parse sidebar: {e}"}

        if not parsed:
            return {"success": False, "error": "No channels found in sidebar HTML"}

        # Convert to CachedChannel objects
        channels = []
        dms = []
        for item in parsed:
            if item["type"] == "channel":
                channels.append(
                    CachedChannel(
                        channel_id=item["channel_id"],
                        name=item["name"],
                        display_name=item["display_name"],
                        is_private=False,  # Can't determine from sidebar
                        is_member=True,  # If it's in sidebar, user is a member
                        purpose="",
                        topic="",
                        num_members=0,
                    )
                )
            elif item["type"] in ("dm", "group_dm"):
                dms.append(
                    {
                        "channel_id": item["channel_id"],
                        "name": item["name"],
                        "display_name": item["display_name"],
                        "type": item["type"],
                    }
                )

        # Cache the channels
        if channels:
            await self.cache_channels_bulk(channels)

        # Store DMs in a separate metadata entry for reference
        if dms:
            await self.set_meta("sidebar_dms", json.dumps(dms))

        return {
            "success": True,
            "channels_imported": len(channels),
            "dms_found": len(dms),
            "total_items": len(parsed),
            "source_file": str(file_path),
        }

    async def get_sidebar_dms(self) -> list[dict[str, str]]:
        """Get DMs that were imported from the sidebar."""
        dms_json = await self.get_meta("sidebar_dms", "[]")
        try:
            return json.loads(dms_json)
        except json.JSONDecodeError:
            return []

    # ==================== Group Cache (Knowledge) ====================

    async def cache_group(self, group: CachedGroup):
        """Cache user group information for @team mention resolution."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO group_cache
                (group_id, handle, name, description, members, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    group.group_id,
                    group.handle,
                    group.name,
                    group.description,
                    json.dumps(group.members),
                    time.time(),
                ),
            )
            await self._db.commit()

    async def cache_groups_bulk(self, groups: list[CachedGroup]):
        """Cache multiple groups at once."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.executemany(
                """
                INSERT OR REPLACE INTO group_cache
                (group_id, handle, name, description, members, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        g.group_id,
                        g.handle,
                        g.name,
                        g.description,
                        json.dumps(g.members),
                        time.time(),
                    )
                    for g in groups
                ],
            )
            await self._db.commit()

    async def get_cached_group(self, group_id: str) -> CachedGroup | None:
        """Get a cached group by ID."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                """
                SELECT group_id, handle, name, description, members, updated_at
                FROM group_cache WHERE group_id = ?
                """,
                (group_id,),
            )
            row = await cursor.fetchone()
            if row:
                members = json.loads(row[4]) if row[4] else []
                return CachedGroup(
                    group_id=row[0],
                    handle=row[1],
                    name=row[2] or "",
                    description=row[3] or "",
                    members=members,
                    updated_at=row[5],
                )
            return None

    async def get_group_by_handle(self, handle: str) -> CachedGroup | None:
        """Get a group by handle (e.g., 'aap-analytics-team')."""
        async with self._lock:
            await self._connect_unlocked()
            # Remove @ prefix if present
            handle = handle.lstrip("@")
            cursor = await self._db.execute(
                """
                SELECT group_id, handle, name, description, members, updated_at
                FROM group_cache
                WHERE handle = ? OR handle = ? COLLATE NOCASE
                LIMIT 1
                """,
                (handle, handle),
            )
            row = await cursor.fetchone()
            if row:
                members = json.loads(row[4]) if row[4] else []
                return CachedGroup(
                    group_id=row[0],
                    handle=row[1],
                    name=row[2] or "",
                    description=row[3] or "",
                    members=members,
                    updated_at=row[5],
                )
            return None

    async def find_groups(self, query: str = "", limit: int = 50) -> list[CachedGroup]:
        """
        Find groups matching a query.

        Args:
            query: Search string (matches handle, name, description)
            limit: Maximum results to return

        Returns:
            List of matching CachedGroup objects
        """
        async with self._lock:
            await self._connect_unlocked()

            if query:
                search_pattern = f"%{query}%"
                cursor = await self._db.execute(
                    """
                    SELECT group_id, handle, name, description, members, updated_at
                    FROM group_cache
                    WHERE handle LIKE ? OR name LIKE ? OR description LIKE ?
                    ORDER BY handle ASC
                    LIMIT ?
                    """,
                    (search_pattern, search_pattern, search_pattern, limit),
                )
            else:
                cursor = await self._db.execute(
                    """
                    SELECT group_id, handle, name, description, members, updated_at
                    FROM group_cache
                    ORDER BY handle ASC
                    LIMIT ?
                    """,
                    (limit,),
                )

            rows = await cursor.fetchall()
            return [
                CachedGroup(
                    group_id=row[0],
                    handle=row[1],
                    name=row[2] or "",
                    description=row[3] or "",
                    members=json.loads(row[4]) if row[4] else [],
                    updated_at=row[5],
                )
                for row in rows
            ]

    async def get_all_groups(self) -> list[CachedGroup]:
        """Get all cached groups."""
        return await self.find_groups(limit=1000)

    # ==================== Extended User Cache ====================

    async def cache_user_extended(
        self,
        user_id: str,
        user_name: str,
        display_name: str = "",
        real_name: str = "",
        email: str = "",
        gitlab_username: str = "",
        avatar_url: str = "",
    ):
        """Cache extended user information including email, gitlab username, and avatar."""
        async with self._lock:
            await self._connect_unlocked()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO user_cache
                (user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, time.time()),
            )
            await self._db.commit()

    async def find_users(
        self,
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Find users matching a query.

        Args:
            query: Search string (matches user_name, display_name, real_name, email, gitlab_username)
            limit: Maximum results to return

        Returns:
            List of user dicts with all cached fields
        """
        async with self._lock:
            await self._connect_unlocked()

            if query:
                search_pattern = f"%{query}%"
                cursor = await self._db.execute(
                    """
                    SELECT user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at
                    FROM user_cache
                    WHERE user_name LIKE ? OR display_name LIKE ? OR real_name LIKE ?
                          OR email LIKE ? OR gitlab_username LIKE ?
                    ORDER BY user_name ASC
                    LIMIT ?
                    """,
                    (search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, limit),
                )
            else:
                cursor = await self._db.execute(
                    """
                    SELECT user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at
                    FROM user_cache
                    ORDER BY user_name ASC
                    LIMIT ?
                    """,
                    (limit,),
                )

            rows = await cursor.fetchall()
            return [
                {
                    "user_id": row[0],
                    "user_name": row[1],
                    "display_name": row[2] or row[1],
                    "real_name": row[3] or "",
                    "email": row[4] or "",
                    "gitlab_username": row[5] or "",
                    "avatar_url": row[6] or "",
                    "updated_at": row[7],
                }
                for row in rows
            ]

    async def get_user_by_gitlab_username(self, gitlab_username: str) -> dict[str, Any] | None:
        """Get a user by their GitLab username."""
        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                """
                SELECT user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at
                FROM user_cache
                WHERE gitlab_username = ? OR gitlab_username = ? COLLATE NOCASE
                LIMIT 1
                """,
                (gitlab_username, gitlab_username),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "user_name": row[1],
                    "display_name": row[2] or row[1],
                    "real_name": row[3] or "",
                    "email": row[4] or "",
                    "gitlab_username": row[5] or "",
                    "avatar_url": row[6] or "",
                    "updated_at": row[7],
                }
            return None

    async def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        """
        Find a user by their email address.

        Args:
            email: Email address to search for (case-insensitive)

        Returns:
            User dict with all cached fields, or None if not found
        """
        if not email:
            return None

        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                """
                SELECT user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at
                FROM user_cache
                WHERE email = ? COLLATE NOCASE
                LIMIT 1
                """,
                (email,),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "user_name": row[1],
                    "display_name": row[2] or row[1],
                    "real_name": row[3] or "",
                    "email": row[4] or "",
                    "gitlab_username": row[5] or "",
                    "avatar_url": row[6] or "",
                    "updated_at": row[7],
                }
            return None

    async def find_user_by_name_fuzzy(
        self,
        name: str,
        threshold: float = 0.7,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Find users by fuzzy name matching.

        Compares the input name against real_name, display_name, and user_name
        using SequenceMatcher for fuzzy matching.

        Args:
            name: Name to search for
            threshold: Minimum similarity ratio (0-1, default 0.7)
            limit: Maximum number of results to return

        Returns:
            List of user dicts sorted by match score (best first)
        """
        from difflib import SequenceMatcher

        if not name:
            return []

        name_lower = name.lower().strip()

        async with self._lock:
            await self._connect_unlocked()
            cursor = await self._db.execute(
                """
                SELECT user_id, user_name, display_name, real_name, email, gitlab_username, avatar_url, updated_at
                FROM user_cache
                """
            )
            rows = await cursor.fetchall()

        # Score each user
        scored_users = []
        for row in rows:
            user_name = (row[1] or "").lower()
            display_name = (row[2] or "").lower()
            real_name = (row[3] or "").lower()

            # Calculate best match score across all name fields
            scores = [
                SequenceMatcher(None, name_lower, real_name).ratio() if real_name else 0,
                SequenceMatcher(None, name_lower, display_name).ratio() if display_name else 0,
                SequenceMatcher(None, name_lower, user_name).ratio() if user_name else 0,
            ]
            best_score = max(scores)

            if best_score >= threshold:
                scored_users.append(
                    (
                        best_score,
                        {
                            "user_id": row[0],
                            "user_name": row[1],
                            "display_name": row[2] or row[1],
                            "real_name": row[3] or "",
                            "email": row[4] or "",
                            "gitlab_username": row[5] or "",
                            "avatar_url": row[6] or "",
                            "updated_at": row[7],
                            "match_score": best_score,
                        },
                    )
                )

        # Sort by score (descending) and return top matches
        scored_users.sort(key=lambda x: x[0], reverse=True)
        return [user for _, user in scored_users[:limit]]

    # ==================== Target Resolution ====================

    async def resolve_target(self, target: str) -> dict[str, Any]:
        """
        Resolve a Slack target (channel, user, or group) to its ID.

        Args:
            target: Can be:
                - #channel-name -> resolves to channel ID
                - @username -> resolves to user ID
                - @group-handle -> resolves to group ID
                - Raw ID (C..., U..., S...) -> returns as-is

        Returns:
            Dict with 'type', 'id', 'name', and 'found' keys
        """
        target = target.strip()

        # Already an ID?
        if target.startswith("C") and len(target) > 8:
            return {"type": "channel", "id": target, "name": target, "found": True, "source": "raw_id"}
        if target.startswith("D") and len(target) > 8:
            return {"type": "dm", "id": target, "name": target, "found": True, "source": "raw_id"}
        if target.startswith("U") and len(target) > 8:
            return {"type": "user", "id": target, "name": target, "found": True, "source": "raw_id"}
        if target.startswith("S") and len(target) > 8:
            return {"type": "group", "id": target, "name": target, "found": True, "source": "raw_id"}

        # Channel name?
        if target.startswith("#"):
            channel_name = target[1:]
            channel = await self.get_channel_by_name(channel_name)
            if channel:
                return {
                    "type": "channel",
                    "id": channel.channel_id,
                    "name": channel.name,
                    "found": True,
                    "source": "channel_cache",
                }
            return {"type": "channel", "id": None, "name": channel_name, "found": False, "source": "not_found"}

        # User or group?
        if target.startswith("@"):
            name = target[1:]

            # Try as group first (groups have handles like @team-name)
            group = await self.get_group_by_handle(name)
            if group:
                return {
                    "type": "group",
                    "id": group.group_id,
                    "name": group.handle,
                    "found": True,
                    "source": "group_cache",
                }

            # Try as user
            users = await self.find_users(query=name, limit=1)
            if users:
                user = users[0]
                return {
                    "type": "user",
                    "id": user["user_id"],
                    "name": user["user_name"],
                    "found": True,
                    "source": "user_cache",
                }

            return {"type": "unknown", "id": None, "name": name, "found": False, "source": "not_found"}

        # Plain name - try channel first, then user
        channel = await self.get_channel_by_name(target)
        if channel:
            return {
                "type": "channel",
                "id": channel.channel_id,
                "name": channel.name,
                "found": True,
                "source": "channel_cache",
            }

        users = await self.find_users(query=target, limit=1)
        if users:
            user = users[0]
            return {
                "type": "user",
                "id": user["user_id"],
                "name": user["user_name"],
                "found": True,
                "source": "user_cache",
            }

        return {"type": "unknown", "id": None, "name": target, "found": False, "source": "not_found"}
