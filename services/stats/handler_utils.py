"""Shared helpers for the stats daemon handler mixins.

These keep the file I/O, date arithmetic and issue-key parsing in one place so
the D-Bus handler mixins (``executive_emails``, ``issue_hierarchy``,
``report_export`` and ``day_detail``) share one implementation.
"""

import base64
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from services.stats.scorer import COMPETENCY_DEFS

# Errors a handler may hit while reading or rebuilding cached JSON data.
DATA_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
)

HIERARCHY_CACHE_NAME = "jira_hierarchy_cache.json"
ISSUE_KEY_RE = re.compile(r"((?:AAP|ANSTRAT)-\d+)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}


def now_local() -> datetime:
    """Return the current local time as a timezone-aware datetime."""
    return datetime.now().astimezone()


def today_local() -> date:
    """Return today's local date."""
    return now_local().date()


def quarter_of(moment: datetime | date) -> int:
    """Return the calendar quarter (1-4) of *moment*."""
    return (moment.month - 1) // 3 + 1


def quarter_start(year: int, quarter: int) -> date:
    """Return the first day of *quarter* in *year*."""
    return date(year, _QUARTER_START_MONTH[quarter], 1)


def quarter_end(year: int, quarter: int) -> date:
    """Return the last day of *quarter* in *year*."""
    last_month = _QUARTER_START_MONTH[quarter] + 2
    first_of_next = (date(year, last_month, 1) + timedelta(days=31)).replace(day=1)
    return first_of_next - timedelta(days=1)


def weekdays_between(start: date, end: date) -> list[date]:
    """Return every Monday-Friday date from *start* to *end* inclusive."""
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def read_json(path: Path) -> Any:
    """Load a JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    """Write *data* to *path* as indented JSON."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def write_text(path: Path, text: str) -> None:
    """Write *text* to *path*."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def load_daily_files(daily_dir: Path) -> list[tuple[Path, dict | None]]:
    """Return ``(path, data)`` for each daily JSON file, sorted by name.

    ``data`` is ``None`` when a file cannot be read or parsed.
    """
    if not daily_dir.exists():
        return []
    loaded: list[tuple[Path, dict | None]] = []
    for path in sorted(daily_dir.glob("*.json")):
        try:
            data = read_json(path)
        except (OSError, ValueError):
            data = None
        loaded.append((path, data if isinstance(data, dict) else None))
    return loaded


def load_issue_cache(cache_file: Path) -> dict:
    """Return the cached Jira hierarchy data, or ``{}`` if unavailable."""
    if not cache_file.exists():
        return {}
    try:
        data = read_json(cache_file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_issue_keys(text: str) -> list[str]:
    """Return every AAP/ANSTRAT issue key in *text*."""
    return ISSUE_KEY_RE.findall(text)


def category_points(daily_points: dict[str, int]) -> dict[str, int]:
    """Sum competency points per competency category."""
    totals: dict[str, int] = {}
    for comp_id, pts in daily_points.items():
        category = COMPETENCY_DEFS.get(comp_id, {}).get("category", "Other")
        totals[category] = totals.get(category, 0) + pts
    return totals


def decode_b64(data: str) -> str:
    """Decode Gmail's URL-safe base64 body data to text."""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def html_to_text(raw_html: str) -> str:
    """Strip tags and collapse whitespace in an HTML body."""
    text = _HTML_TAG_RE.sub(" ", raw_html)
    return _WHITESPACE_RE.sub(" ", text).strip()
