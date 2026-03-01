"""Shared utilities for stats collectors (gdrive_collector, meeting_collector).

Provides rate limiting, exponential backoff retry, and JSON cache load/save
with TTL - extracted from duplicate patterns in gdrive_collector and meeting_collector.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

SECONDS_PER_HOUR = 3600

STOP_WORDS = {
    "the",
    "and",
    "for",
    "are",
    "with",
    "this",
    "that",
    "from",
    "not",
    "has",
    "was",
    "will",
    "can",
    "all",
    "been",
    "have",
    "into",
    "new",
    "use",
    "its",
    "may",
    "our",
    "but",
    "also",
    "any",
    "each",
    "than",
    "issue",
    "issues",
    "work",
    "working",
    "support",
    "supports",
    "supported",
    "update",
    "updates",
    "updated",
    "service",
    "services",
    "system",
    "systems",
    "data",
    "process",
    "processing",
    "ensure",
    "enable",
    "enabled",
    "current",
    "currently",
    "using",
    "used",
    "based",
    "need",
    "needs",
    "required",
    "provide",
    "provides",
    "allow",
    "allows",
    "including",
    "include",
    "includes",
    "across",
    "related",
    "should",
    "would",
    "could",
    "available",
    "within",
    "between",
    "about",
    "being",
    "make",
    "made",
    "more",
    "other",
    "when",
    "which",
    "what",
    "some",
    "only",
    "them",
    "their",
    "then",
    "these",
    "those",
    "such",
    "well",
    "like",
    "just",
    "over",
    "after",
    "before",
}

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class _RateLimiter:
    def __init__(self) -> None:
        self._last_request_time: float = 0.0

    def wait(self, min_interval: float) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()


_rate_limiter = _RateLimiter()


def rate_limited_call(
    func: Callable[..., T],
    *args: Any,
    min_interval: float = 0.5,
    **kwargs: Any,
) -> T:
    """Execute a call with minimum interval between invocations.

    Uses module-level state to enforce spacing across all callers.
    """
    _rate_limiter.wait(min_interval)
    return func(*args, **kwargs)


# ---------------------------------------------------------------------------
# API call with exponential backoff retry
# ---------------------------------------------------------------------------

_RETRYABLE_PATTERNS = ("429", "500", "503", "rateLimitExceeded")


def api_call_with_backoff(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> T:
    """Execute an API call with exponential backoff on retryable errors.

    Retries on 429, 500, 503, or rateLimitExceeded. Delay is base_delay * (2 ** attempt).
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            err_str = str(e)
            is_retryable = any(p in err_str for p in _RETRYABLE_PATTERNS)
            if not is_retryable or attempt >= max_retries:
                raise
            wait = (2**attempt) * base_delay
            logger.warning(
                "API retryable error (attempt %d/%d), waiting %.1fs: %s",
                attempt + 1,
                max_retries,
                wait,
                err_str[:100],
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def rate_limited_api_call(
    func: Callable[..., T],
    *args: Any,
    min_interval: float = 0.1,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> T:
    """Execute an API call with rate limiting and exponential backoff.

    Combines rate_limited_call and api_call_with_backoff for Google API usage.
    """

    def _wrapped() -> T:
        return rate_limited_call(func, *args, min_interval=min_interval, **kwargs)

    return api_call_with_backoff(
        _wrapped,
        max_retries=max_retries,
        base_delay=base_delay,
    )


# ---------------------------------------------------------------------------
# JSON cache with TTL
# ---------------------------------------------------------------------------


def load_json_cache(path: Path | str, ttl_hours: float = 24) -> dict | None:
    """Load a JSON cache file if it exists and has not expired.

    Expects the JSON to have a "cached_at" ISO timestamp. Returns None if
    the file does not exist, is invalid, or is older than ttl_hours.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            cached_dt = datetime.fromisoformat(cached_at)
            age_hours = (datetime.now() - cached_dt).total_seconds() / SECONDS_PER_HOUR
            if age_hours > ttl_hours:
                logger.info("Cache expired (%.1f hours old): %s", age_hours, path)
                return None
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to load cache %s: %s", path, e)
        return None


def save_json_cache(path: Path | str, data: dict) -> None:
    """Save data to a JSON cache file with a cached_at timestamp.

    Creates parent directories if needed. Merges cached_at into data before saving.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache_data = {**data, "cached_at": datetime.now().isoformat()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
    except OSError as e:
        logger.warning("Failed to save cache %s: %s", path, e)
