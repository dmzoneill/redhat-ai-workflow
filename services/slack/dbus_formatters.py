"""
Formatting and rendering helpers for Slack D-Bus interface.

Extracted from dbus.py to reduce class size. Contains pure functions
that take data and return formatted dicts/strings -- no D-Bus or daemon
state dependencies.
"""

import time
from pathlib import Path

# ==================== Photo Path Helpers ====================

PHOTO_CACHE_DIR = Path.home() / ".cache" / "aa-workflow" / "photos"


def get_cached_photo_path(user_id: str) -> str:
    """
    Get the local file path to a cached Slack user's profile photo.

    Returns the path as a string if the file exists, empty string otherwise.
    """
    photo_path = PHOTO_CACHE_DIR / f"{user_id}.jpg"
    return str(photo_path) if photo_path.exists() else ""


def format_photo_path_response(user_id: str) -> dict:
    """Build a JSON-serializable response for photo path queries."""
    photo_path = PHOTO_CACHE_DIR / f"{user_id}.jpg"
    exists = photo_path.exists()
    return {
        "success": True,
        "user_id": user_id,
        "photo_path": str(photo_path) if exists else "",
        "exists": exists,
    }


# ==================== User Formatting ====================


def format_user_with_photo(user: dict) -> dict:
    """
    Format a user dict with cached photo path included.

    Takes a raw user dict (from state_db) and adds photo_path field.
    """
    return {
        "user_id": user["user_id"],
        "user_name": user["user_name"],
        "display_name": user["display_name"],
        "real_name": user["real_name"],
        "email": user["email"],
        "avatar_url": user["avatar_url"],
        "photo_path": get_cached_photo_path(user["user_id"]),
    }


def format_user_match_with_photo(user: dict) -> dict:
    """
    Format a fuzzy-matched user dict with photo path and match score.
    """
    result = format_user_with_photo(user)
    result["match_score"] = user.get("match_score", 0)
    return result


def format_email_lookup_found(user: dict) -> dict:
    """Format a successful email lookup response."""
    return {
        "success": True,
        "found": True,
        **format_user_with_photo(user),
    }


def format_email_lookup_not_found(email: str) -> dict:
    """Format a not-found email lookup response."""
    return {
        "success": True,
        "found": False,
        "email": email,
    }


# ==================== Rate Limiting ====================

# Rate limiting constants
SECONDS_PER_DAY = 86400
SEARCH_COOLDOWN_SECONDS = 5
DAILY_SEARCH_LIMIT = 20


def check_search_rate_limit(rate_limit: dict) -> dict | None:
    """
    Check search rate limits and return an error response if limited.

    Args:
        rate_limit: Dict with keys: last_search, daily_count, daily_reset

    Returns:
        Error response dict if rate limited, None if OK.
        Also updates rate_limit dict in-place (resets daily count if needed).
    """
    now = time.time()

    # Reset daily count if it's a new day
    if now - rate_limit["daily_reset"] > SECONDS_PER_DAY:
        rate_limit["daily_count"] = 0
        rate_limit["daily_reset"] = now

    # Check per-search rate limit
    if now - rate_limit["last_search"] < SEARCH_COOLDOWN_SECONDS:
        wait_time = SEARCH_COOLDOWN_SECONDS - (now - rate_limit["last_search"])
        return {
            "success": False,
            "error": f"Rate limited. Please wait {wait_time:.1f} seconds.",
            "rate_limited": True,
            "wait_seconds": wait_time,
            "messages": [],
        }

    # Check daily limit
    if rate_limit["daily_count"] >= DAILY_SEARCH_LIMIT:
        return {
            "success": False,
            "error": f"Daily search limit ({DAILY_SEARCH_LIMIT}) reached. Try again tomorrow.",
            "rate_limited": True,
            "daily_limit_reached": True,
            "messages": [],
        }

    return None


def record_search(rate_limit: dict) -> None:
    """Record that a search was performed (update rate limit tracking)."""
    rate_limit["last_search"] = time.time()
    rate_limit["daily_count"] += 1


def format_search_results(query: str, results: dict, daily_count: int) -> dict:
    """Format Slack message search results."""
    messages = results.get("messages", {}).get("matches", [])
    return {
        "success": True,
        "query": query,
        "count": len(messages),
        "total": results.get("messages", {}).get("total", 0),
        "messages": [
            {
                "text": m.get("text", ""),
                "user": m.get("user", ""),
                "username": m.get("username", ""),
                "channel_id": m.get("channel", {}).get("id", ""),
                "channel_name": m.get("channel", {}).get("name", ""),
                "ts": m.get("ts", ""),
                "permalink": m.get("permalink", ""),
            }
            for m in messages
        ],
        "searches_remaining_today": DAILY_SEARCH_LIMIT - daily_count,
    }


# ==================== Persona Test Formatting ====================


def format_persona_test_result(query: str, context) -> dict:
    """
    Format the result of a context injection persona test.

    Args:
        query: The test query string
        context: ContextResult object from ContextInjector.gather_context()

    Returns:
        Dict ready for json.dumps()
    """
    slack_source = context.get_source("slack")
    code_source = context.get_source("code")
    inscope_source = context.get_source("inscope")

    return {
        "query": query,
        "elapsed_ms": context.total_latency_ms,
        "total_results": context.total_results,
        "formatted": context.formatted,
        "sources": [
            {
                "source": s.source,
                "found": s.found,
                "count": s.count,
                "error": s.error,
                "latency_ms": s.latency_ms,
                "results": (s.results[:3] if s.results else []),  # Limit results for UI
            }
            for s in context.sources
        ],
        "sources_used": [s.source for s in context.sources if s.found],
        "status": {
            "slack_persona": {
                "synced": slack_source.found if slack_source else False,
                "total_messages": (slack_source.count if slack_source else 0),
                "error": slack_source.error if slack_source else None,
            },
            "code_search": {
                "indexed": code_source.found if code_source else False,
                "chunks": code_source.count if code_source else 0,
                "error": code_source.error if code_source else None,
            },
            "inscope": {
                "authenticated": (inscope_source.found if inscope_source else False),
                "assistants": (20 if inscope_source and inscope_source.found else 0),
                "error": (inscope_source.error if inscope_source else None),
            },
        },
        "project": "automation-analytics-backend",
    }


def format_persona_test_error(query: str, error: str) -> dict:
    """
    Format an error response for persona test failures.

    Args:
        query: The test query string
        error: Error message string

    Returns:
        Dict ready for json.dumps()
    """
    return {
        "query": query,
        "error": error,
        "elapsed_ms": 0,
        "total_results": 0,
        "sources": [],
        "sources_used": [],
        "status": {
            "slack_persona": {"synced": False, "error": error},
            "code_search": {"indexed": False, "error": error},
            "inscope": {"authenticated": False, "error": error},
        },
    }


# ==================== Config Formatting ====================


def format_slack_config(config: dict) -> dict:
    """
    Extract and format relevant Slack daemon configuration sections.

    Args:
        config: Full config dict from load_config()

    Returns:
        Dict with relevant config sections
    """
    slack_config = config.get("slack", {})
    return {
        "listener": slack_config.get("listener", {}),
        "watched_channels": slack_config.get("listener", {}).get(
            "watched_channels", []
        ),
        "alert_channels": slack_config.get("listener", {}).get("alert_channels", {}),
        "user_classification": slack_config.get("user_classification", {}),
        "commands": slack_config.get("commands", {}),
        "research": slack_config.get("research", {}),
        "debug_mode": slack_config.get("debug_mode", False),
    }


# ==================== Command List Formatting ====================


def format_command_list(commands) -> list[dict]:
    """
    Format a list of command objects for API response.

    Args:
        commands: List of command objects from CommandRegistry.list_commands()

    Returns:
        List of dicts with command info
    """
    return [
        {
            "name": cmd.name,
            "description": cmd.description,
            "type": cmd.command_type.value,
            "category": cmd.category,
            "contextual": cmd.contextual,
            "examples": cmd.examples[:3] if cmd.examples else [],
            "inputs": cmd.inputs[:5] if cmd.inputs else [],
        }
        for cmd in commands
    ]
