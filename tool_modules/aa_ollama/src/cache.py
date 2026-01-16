"""Caching for tool filter results.

Provides LRU cache with TTL for efficient repeated queries.
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
    """LRU cache with TTL for tool filter results."""

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

    def _make_key(self, message: str, persona: str) -> str:
        """Create cache key from message and persona.

        Args:
            message: User message
            persona: Active persona

        Returns:
            Cache key string
        """
        # Normalize message: lowercase, truncate, strip whitespace
        normalized = message.lower().strip()[:100]
        return f"{persona}:{normalized}"

    def get(self, message: str, persona: str) -> Optional[list[str]]:
        """Get cached tools if valid.

        Args:
            message: User message
            persona: Active persona

        Returns:
            Cached tool list, or None if not found/expired
        """
        key = self._make_key(message, persona)
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

    def set(self, message: str, persona: str, tools: list[str]) -> None:
        """Cache tools for message/persona.

        Args:
            message: User message
            persona: Active persona
            tools: Tool list to cache
        """
        key = self._make_key(message, persona)

        # Evict oldest if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]
            self._stats["evictions"] += 1
            logger.debug(f"Cache eviction: {oldest_key[:30]}...")

        self._cache[key] = CacheEntry(tools=tools, created_at=datetime.now())
        logger.debug(f"Cache set: {key[:30]}... ({len(tools)} tools)")

    def invalidate(self, message: str, persona: str) -> bool:
        """Invalidate a specific cache entry.

        Args:
            message: User message
            persona: Active persona

        Returns:
            True if entry was found and removed
        """
        key = self._make_key(message, persona)
        if key in self._cache:
            del self._cache[key]
            return True
        return False

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
