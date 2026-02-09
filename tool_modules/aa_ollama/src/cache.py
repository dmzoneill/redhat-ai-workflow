"""Caching for tool filter results.

Provides LRU cache with TTL for efficient repeated queries.
The cache is workspace-aware: different workspaces have separate cache entries.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A single cache entry."""

    tools: list[str]
    created_at: datetime
    hits: int = 0


class FilterCache:
    """LRU cache with TTL for tool filter results.

    The cache is workspace-aware: cache keys include workspace_uri to ensure
    different Cursor chats/workspaces have separate cache entries.
    """

    def __init__(self, max_size: int = 500, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live in seconds
        """
        self.max_size = max_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: dict[str, CacheEntry] = {}
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    def _make_key(
        self, message: str, persona: str, workspace_uri: str = "default"
    ) -> str:
        """Create cache key from message, persona, and workspace.

        Args:
            message: User message
            persona: Active persona
            workspace_uri: Workspace URI for isolation

        Returns:
            Cache key string
        """
        # Normalize message: lowercase, truncate, strip whitespace
        normalized = message.lower().strip()[:100]
        # Include workspace in key for isolation
        return f"{workspace_uri}:{persona}:{normalized}"

    def get(
        self, message: str, persona: str, workspace_uri: str = "default"
    ) -> Optional[list[str]]:
        """Get cached tools if valid.

        Args:
            message: User message
            persona: Active persona
            workspace_uri: Workspace URI for isolation

        Returns:
            Cached tool list, or None if not found/expired
        """
        key = self._make_key(message, persona, workspace_uri)
        entry = self._cache.get(key)

        if entry is None:
            self._stats["misses"] += 1
            return None

        # Check TTL
        if datetime.now() - entry.created_at > self.ttl:
            del self._cache[key]
            self._stats["misses"] += 1
            logger.debug(f"Cache entry expired: {key[:30]}...")
            return None

        entry.hits += 1
        self._stats["hits"] += 1
        logger.debug(f"Cache hit: {key[:30]}... (hits: {entry.hits})")
        return entry.tools

    def set(
        self,
        message: str,
        persona: str,
        tools: list[str],
        workspace_uri: str = "default",
    ) -> None:
        """Cache tools for message/persona/workspace.

        Args:
            message: User message
            persona: Active persona
            tools: Tool list to cache
            workspace_uri: Workspace URI for isolation
        """
        key = self._make_key(message, persona, workspace_uri)

        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]
            self._stats["evictions"] += 1
            logger.debug(f"Cache eviction: {oldest_key[:30]}...")

        self._cache[key] = CacheEntry(tools=tools, created_at=datetime.now())
        logger.debug(f"Cache set: {key[:30]}... ({len(tools)} tools)")

    def invalidate(
        self, message: str, persona: str, workspace_uri: str = "default"
    ) -> bool:
        """Invalidate a specific cache entry.

        Args:
            message: User message
            persona: Active persona
            workspace_uri: Workspace URI for isolation

        Returns:
            True if entry was found and removed
        """
        key = self._make_key(message, persona, workspace_uri)
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_workspace(self, workspace_uri: str) -> int:
        """Invalidate all cache entries for a workspace.

        Args:
            workspace_uri: Workspace URI to invalidate

        Returns:
            Number of entries invalidated
        """
        keys_to_remove = [k for k in self._cache if k.startswith(f"{workspace_uri}:")]
        for key in keys_to_remove:
            del self._cache[key]
        if keys_to_remove:
            logger.debug(
                f"Invalidated {len(keys_to_remove)} cache entries for workspace {workspace_uri}"
            )
        return len(keys_to_remove)

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared: {count} entries")
        return count

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate.

        Returns:
            Hit rate as float (0.0 to 1.0)
        """
        total = self._stats["hits"] + self._stats["misses"]
        return self._stats["hits"] / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, hit_rate, size, evictions
        """
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(self.hit_rate, 3),
            "size": self.size,
            "max_size": self.max_size,
            "evictions": self._stats["evictions"],
            "ttl_seconds": self.ttl.total_seconds(),
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
