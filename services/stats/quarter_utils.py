"""Quarter date utilities.

Provides canonical helpers for quarter start/end dates, current quarter
detection, and day-of-quarter calculations. Replaces 16+ duplicate
quarter_starts = {1: (1,1), 2: (4,1), ...} patterns across the codebase.
"""

from __future__ import annotations

from datetime import date, timedelta

QUARTER_STARTS = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}


def get_quarter_start(year: int, quarter: int) -> date:
    """Return the first day of the given quarter."""
    month, day = QUARTER_STARTS[quarter]
    return date(year, month, day)


def get_quarter_end(year: int, quarter: int) -> date:
    """Return the last day of the given quarter."""
    if quarter < 4:
        next_month, _ = QUARTER_STARTS[quarter + 1]
        return date(year, next_month, 1) - timedelta(days=1)
    return date(year, 12, 31)


def get_quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """Return (start, end) dates for the given quarter."""
    return get_quarter_start(year, quarter), get_quarter_end(year, quarter)


def get_current_quarter() -> tuple[int, int]:
    """Return (year, quarter) for today."""
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return today.year, q


def get_day_of_quarter(d: date | None = None) -> int:
    """Return the 1-based day index within the quarter for the given date."""
    if d is None:
        d = date.today()
    q = (d.month - 1) // 3 + 1
    start = get_quarter_start(d.year, q)
    return (d - start).days + 1
