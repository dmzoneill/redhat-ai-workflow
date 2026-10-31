"""Quarter data access shared by the stats daemon's handler mixins.

``QuarterDataMixin`` owns the performance directories, the cached JSON file
loader, the quarter summary rebuild and the ``get_captured_days`` D-Bus
handler. The other stats mixins build on it, and ``StatsDaemon`` inherits it
through them.
"""

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

from services.stats.collector import DataCollector
from services.stats.email_parser import get_executive_emails_dir
from services.stats.handler_utils import (
    category_points,
    load_daily_files,
    now_local,
    quarter_end,
    quarter_of,
    quarter_start,
    read_json,
    today_local,
    weekdays_between,
    write_json,
)
from services.stats.scorer import get_effective_defs
from services.stats.strategy import build_strategy_alignment

logger = logging.getLogger(__name__)

GAP_THRESHOLD_PCT = 25
MAX_HIGHLIGHTS = 10


def sum_daily_points(daily_dir: Path) -> tuple[dict[str, int], int, list[str]]:
    """Cumulative points, total event count and highlights across the daily files."""
    cumulative_points: dict[str, int] = {}
    total_events = 0
    highlights: list[str] = []
    for _, data in load_daily_files(daily_dir):
        if data is None:
            continue
        for comp_id, pts in data.get("daily_points", {}).items():
            cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
        events = data.get("events", [])
        total_events += len(events)
        for ev in events[:3]:
            if ev.get("title") and len(highlights) < MAX_HIGHLIGHTS:
                highlights.append(ev["title"][:80])
    return cumulative_points, total_events, highlights


def captured_day(path: Path, data: dict | None) -> dict:
    """Basic stats for one captured day; empty stats if the file was unreadable."""
    if data is None:
        return {
            "date": path.stem,
            "event_count": 0,
            "total_points": 0,
            "sources": [],
            "category_points": {},
        }
    events = data.get("events", [])
    return {
        "date": data.get("date", path.stem),
        "event_count": len(events),
        "total_points": data.get("daily_total", 0),
        "sources": list({ev.get("source", "unknown") for ev in events}),
        "category_points": category_points(data.get("daily_points", {})),
    }


def day_of_quarter(today: date, year: int, quarter: int) -> int:
    """1-based day number of *today* within the quarter."""
    return (today - quarter_start(year, quarter)).days + 1


class QuarterDataMixin:
    """Performance directories, cached file loading and the quarter summary."""

    def __init__(self) -> None:
        self._stats_cache: dict[str, Any] = {}
        self._last_modified: dict[str, float] = {}
        self._collector = DataCollector()

    def perf_dir(self, year: int | None = None, quarter: int | None = None) -> Path:
        """Performance data directory for the quarter (default: current)."""
        return self._collector.get_perf_dir(year, quarter)

    def daily_dir(self, year: int | None = None, quarter: int | None = None) -> Path:
        """Daily data directory for the quarter (default: current)."""
        return self._collector.get_daily_dir(year, quarter)

    def executive_emails_dir(self, year: int | None = None, quarter: int | None = None) -> Path:
        """Cached executive emails directory for the quarter (default: current)."""
        return get_executive_emails_dir(self.perf_dir(year, quarter))

    def load_file(self, filepath: Path) -> dict | None:
        """Load and cache a JSON file; on a read error return the last cached copy."""
        key = str(filepath)
        try:
            if not filepath.exists():
                return None

            mtime = filepath.stat().st_mtime
            if key in self._stats_cache and self._last_modified.get(key, 0) >= mtime:
                cached: dict = self._stats_cache[key]
                return cached

            data: dict = read_json(filepath)
        except (OSError, ValueError) as e:
            logger.error("Failed to load %s: %s", filepath, e)
            stale: dict | None = self._stats_cache.get(key)
            return stale
        self._stats_cache[key] = data
        self._last_modified[key] = mtime
        return data

    def update_summary(self, year: int | None = None, quarter: int | None = None) -> dict:
        """Recalculate and update the quarter summary from all daily files."""
        daily_dir = self.daily_dir(year, quarter)
        if not daily_dir.exists():
            return {}

        cumulative_points, total_events, highlights = sum_daily_points(daily_dir)

        _, _, _, target_per_competency = get_effective_defs()
        cumulative_pct = {k: min(round(v / target_per_competency * 100), 100) for k, v in cumulative_points.items()}

        now = now_local()
        y = year or now.year
        q = quarter or quarter_of(now)
        perf_dir = self.perf_dir(year, quarter)

        summary = {
            "year": y,
            "quarter": q,
            "day_of_quarter": day_of_quarter(now.date(), y, q),
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1)),
            "total_events": total_events,
            "highlights": highlights,
            "gaps": [k for k, v in cumulative_pct.items() if v < GAP_THRESHOLD_PCT],
            "strategy_alignment": build_strategy_alignment(
                y,
                q,
                cumulative_points,
                perf_dir,
                self.executive_emails_dir(year, quarter),
            ),
            "last_updated": now.isoformat(),
        }

        perf_dir.mkdir(parents=True, exist_ok=True)
        summary_file = perf_dir / "summary.json"
        write_json(summary_file, summary)

        self._stats_cache.pop(str(summary_file), None)
        self._last_modified.pop(str(summary_file), None)

        return summary

    async def _handle_get_captured_days(self, **kwargs) -> dict:
        """Return list of captured days with basic stats for the quarter."""
        return await self.captured_days(kwargs.get("year"), kwargs.get("quarter"))

    async def captured_days(self, year: int | None = None, quarter: int | None = None) -> dict:
        """Captured days and weekday coverage for the quarter (default: current)."""
        now = now_local()
        year = year or now.year
        quarter = quarter or quarter_of(now)

        loaded = await asyncio.to_thread(load_daily_files, self.daily_dir(year, quarter))
        days = [captured_day(path, data) for path, data in loaded]

        end_date = min(today_local(), quarter_end(year, quarter))
        total_weekdays = len(weekdays_between(quarter_start(year, quarter), end_date))
        captured = len(days)

        return {
            "success": True,
            "days": days,
            "year": year,
            "quarter": quarter,
            "coverage": {
                "total_weekdays": total_weekdays,
                "captured": captured,
                "percentage": round(captured / max(total_weekdays, 1) * 100),
            },
        }
