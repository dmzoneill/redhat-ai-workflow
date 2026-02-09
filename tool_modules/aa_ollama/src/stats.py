"""Statistics collection for tool filtering.

Tracks filter effectiveness, latency, and provides data for the dashboard.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Stats file location
STATS_FILE = Path.home() / ".config" / "aa-workflow" / "inference_stats.json"


@dataclass
class FilterStats:
    """Track filter effectiveness."""

    total_requests: int = 0
    by_persona: dict[str, dict] = field(default_factory=dict)
    latency_histogram: dict[str, int] = field(
        default_factory=lambda: {"<10ms": 0, "10-100ms": 0, "100-500ms": 0, ">500ms": 0}
    )
    cache_hits: int = 0
    cache_misses: int = 0
    npu_calls: int = 0
    npu_timeouts: int = 0
    fallback_used: int = 0
    recent_history: list[dict] = field(default_factory=list)
    _max_history: int = 20

    def record(self, result: dict) -> None:
        """Record a filter result.

        Args:
            result: Filter result dict with keys:
                - tools: list of tool names
                - tool_count: number of tools
                - reduction_pct: percentage reduction
                - methods: list of methods used
                - persona: persona name
                - skill_detected: detected skill or None
                - latency_ms: filter latency in ms
        """
        self.total_requests += 1

        # Update persona stats
        persona = result.get("persona", "unknown")
        if persona not in self.by_persona:
            self.by_persona[persona] = {
                "requests": 0,
                "tools": [],
                "tier1_only": 0,
                "tier2_skill": 0,
                "tier3_npu": 0,
            }

        persona_stats = self.by_persona[persona]
        persona_stats["requests"] += 1
        persona_stats["tools"].append(result.get("tool_count", 0))
        # Prevent unbounded growth - keep last 1000 tool counts per persona
        if len(persona_stats["tools"]) > 1000:
            persona_stats["tools"] = persona_stats["tools"][-1000:]

        # Track tier usage
        methods = result.get("methods", [])
        if "layer3_skill" in methods:
            persona_stats["tier2_skill"] += 1
        elif any("layer4" in m for m in methods):
            persona_stats["tier3_npu"] += 1
        else:
            persona_stats["tier1_only"] += 1

        # Track NPU usage
        if any("npu" in m.lower() for m in methods):
            self.npu_calls += 1
        if any("fallback" in m.lower() for m in methods):
            self.fallback_used += 1

        # Update latency histogram
        latency = result.get("latency_ms", 0)
        if latency < 10:
            self.latency_histogram["<10ms"] += 1
        elif latency < 100:
            self.latency_histogram["10-100ms"] += 1
        elif latency < 500:
            self.latency_histogram["100-500ms"] += 1
        else:
            self.latency_histogram[">500ms"] += 1

        # Add to recent history (keep last N)
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "message_preview": result.get("message_preview", ""),
            "persona": persona,
            "skill_detected": result.get("skill_detected"),
            "tool_count": result.get("tool_count", 0),
            "reduction_pct": result.get("reduction_pct", 0),
            "methods": methods,
            "latency_ms": latency,
        }
        self.recent_history.append(history_entry)
        if len(self.recent_history) > self._max_history:
            self.recent_history = self.recent_history[-self._max_history :]

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self.cache_misses += 1

    def record_npu_timeout(self) -> None:
        """Record an NPU timeout."""
        self.npu_timeouts += 1

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    def get_persona_stats(self, persona: str) -> dict:
        """Get statistics for a specific persona.

        Args:
            persona: Persona name

        Returns:
            Dict with min, max, mean, median tool counts
        """
        if persona not in self.by_persona:
            return {
                "requests": 0,
                "tools_min": 0,
                "tools_max": 0,
                "tools_mean": 0,
                "tools_median": 0,
            }

        stats = self.by_persona[persona]
        tools = stats["tools"]

        if not tools:
            return {
                "requests": stats["requests"],
                "tools_min": 0,
                "tools_max": 0,
                "tools_mean": 0,
                "tools_median": 0,
            }

        sorted_tools = sorted(tools)
        n = len(sorted_tools)
        median = (
            sorted_tools[n // 2]
            if n % 2 == 1
            else (sorted_tools[n // 2 - 1] + sorted_tools[n // 2]) / 2
        )

        return {
            "requests": stats["requests"],
            "tools_min": min(tools),
            "tools_max": max(tools),
            "tools_mean": round(sum(tools) / len(tools), 1),
            "tools_median": median,
            "tier1_only": stats["tier1_only"],
            "tier2_skill": stats["tier2_skill"],
            "tier3_npu": stats["tier3_npu"],
        }

    def to_dict(self) -> dict:
        """Export stats for dashboard/persistence.

        Returns:
            Dict with all statistics
        """
        return {
            "total_requests": self.total_requests,
            "by_persona": {
                name: self.get_persona_stats(name) for name in self.by_persona
            },
            "latency": self.latency_histogram,
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": round(self.cache_hit_rate, 3),
            },
            "npu": {
                "calls": self.npu_calls,
                "timeouts": self.npu_timeouts,
            },
            "fallback_used": self.fallback_used,
            "recent_history": self.recent_history,
        }

    def save(self, path: Optional[Path] = None) -> None:
        """Save stats to file.

        Args:
            path: Path to save to (defaults to STATS_FILE)
        """
        path = path or STATS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.debug(f"Saved stats to {path}")
        except Exception as e:
            logger.error(f"Failed to save stats: {e}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "FilterStats":
        """Load stats from file.

        Args:
            path: Path to load from (defaults to STATS_FILE)

        Returns:
            Loaded FilterStats instance
        """
        path = path or STATS_FILE

        if not path.exists():
            return cls()

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            stats = cls()
            stats.total_requests = data.get("total_requests", 0)
            stats.latency_histogram = data.get("latency", stats.latency_histogram)
            stats.cache_hits = data.get("cache", {}).get("hits", 0)
            stats.cache_misses = data.get("cache", {}).get("misses", 0)
            stats.npu_calls = data.get("npu", {}).get("calls", 0)
            stats.npu_timeouts = data.get("npu", {}).get("timeouts", 0)
            stats.fallback_used = data.get("fallback_used", 0)
            stats.recent_history = data.get("recent_history", [])

            # Reconstruct by_persona (simplified - loses raw tools list)
            for persona, pstats in data.get("by_persona", {}).items():
                stats.by_persona[persona] = {
                    "requests": pstats.get("requests", 0),
                    "tools": [],  # Can't reconstruct raw list
                    "tier1_only": pstats.get("tier1_only", 0),
                    "tier2_skill": pstats.get("tier2_skill", 0),
                    "tier3_npu": pstats.get("tier3_npu", 0),
                }

            logger.info(f"Loaded stats from {path}: {stats.total_requests} requests")
            return stats

        except Exception as e:
            logger.error(f"Failed to load stats: {e}")
            return cls()

    def reset(self) -> None:
        """Reset all statistics."""
        self.total_requests = 0
        self.by_persona = {}
        self.latency_histogram = {
            "<10ms": 0,
            "10-100ms": 0,
            "100-500ms": 0,
            ">500ms": 0,
        }
        self.cache_hits = 0
        self.cache_misses = 0
        self.npu_calls = 0
        self.npu_timeouts = 0
        self.fallback_used = 0
        self.recent_history = []


# Singleton stats instance
_stats: Optional[FilterStats] = None


def get_stats() -> FilterStats:
    """Get or create the stats instance."""
    global _stats
    if _stats is None:
        _stats = FilterStats.load()
    return _stats


def save_stats() -> None:
    """Save the current stats."""
    if _stats is not None:
        _stats.save()
