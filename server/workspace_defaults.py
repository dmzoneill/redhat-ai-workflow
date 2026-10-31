"""Workspace/session defaults and the per-persona tool count cache."""

import logging
from datetime import datetime, timezone

from server import utils as server_utils
from server.cursor_chat_db import CURSOR_DB_ERRORS

logger = logging.getLogger(__name__)

# Default workspace key when list_roots() is unavailable
DEFAULT_WORKSPACE = "default"

# Default project when none detected
DEFAULT_PROJECT = "redhat-ai-workflow"

# Session stale timeout (hours) - sessions inactive for longer are cleaned up
SESSION_STALE_HOURS = 24

# Maximum entries in tool_filter_cache per session to prevent memory leaks
MAX_FILTER_CACHE_SIZE = 50

# Global cache of tool counts per persona (refreshed on session_start/persona_load)
_persona_tool_counts: dict[str, int] = {}


def now() -> datetime:
    """Current local time, timezone-aware."""
    return datetime.now(tz=timezone.utc).astimezone()


def as_aware(value: datetime) -> datetime:
    """``value`` with a timezone; naive values (older persisted data) are local time."""
    return value if value.tzinfo else value.astimezone()


def from_epoch_ms(timestamp_ms: float) -> datetime:
    """Local, timezone-aware time of a millisecond epoch timestamp (Cursor's format)."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone()


def get_default_persona() -> str:
    """Get the default persona from config, with fallback to 'researcher'.

    This centralizes the default persona logic so it can be changed in one place.
    Reads from config.json agent.default_persona setting.
    """
    try:
        cfg = server_utils.load_config()
        return cfg.get("agent", {}).get("default_persona", "researcher")
    # Best-effort fallback when config.json is missing or malformed.
    except CURSOR_DB_ERRORS:
        return "researcher"


def get_persona_tool_count(persona: str) -> int:
    """Get cached tool count for a persona."""
    return _persona_tool_counts.get(persona, 0)


def update_persona_tool_count(persona: str, count: int) -> None:
    """Update the cached tool count for a persona."""
    _persona_tool_counts[persona] = count
    logger.debug("Updated persona tool count cache: %s = %s", persona, count)


def get_all_persona_tool_counts() -> dict[str, int]:
    """Get all cached persona tool counts."""
    return _persona_tool_counts.copy()
