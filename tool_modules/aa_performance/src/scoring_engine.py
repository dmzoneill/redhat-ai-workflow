"""Scoring Engine - Calculate and track performance scores.

Handles:
- Point calculation with daily caps
- Event deduplication
- Cumulative score tracking
- Quarter progress calculation

Performance data is stored in: ~/.config/aa-workflow/performance/
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Performance data directory - centralized in server.paths
try:
    from server.paths import PERFORMANCE_DIR, get_performance_quarter_dir

    _DEFAULT_DATA_DIR = PERFORMANCE_DIR
except ImportError:
    # Fallback for standalone usage
    _DEFAULT_DATA_DIR = Path.home() / ".config" / "aa-workflow" / "performance"


def get_performance_data_dir() -> Path:
    """Get the performance data directory.

    Returns the centralized performance directory from server.paths.
    """
    return _DEFAULT_DATA_DIR


# For backward compatibility
QUARTERLY_DATA_DIR = get_performance_data_dir()


def get_quarter_info(dt: date | None = None) -> tuple[int, int, date, date, int]:
    """Get quarter information for a date.

    Returns:
        Tuple of (year, quarter, start_date, end_date, day_of_quarter)
    """
    if dt is None:
        dt = date.today()

    year = dt.year
    quarter = (dt.month - 1) // 3 + 1

    quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    quarter_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}

    start_month, start_day = quarter_starts[quarter]
    end_month, end_day = quarter_ends[quarter]

    start_date = date(year, start_month, start_day)
    end_date = date(year, end_month, end_day)

    day_of_quarter = (dt - start_date).days + 1

    return year, quarter, start_date, end_date, day_of_quarter


def get_performance_dir(year: int, quarter: int) -> Path:
    """Get the performance data directory for a quarter.

    Uses centralized path from server.paths.
    """
    try:
        return get_performance_quarter_dir(year, quarter)
    except NameError:
        # Fallback for standalone usage
        base_dir = get_performance_data_dir()
        perf_dir = base_dir / str(year) / f"q{quarter}" / "performance"
        perf_dir.mkdir(parents=True, exist_ok=True)
        return perf_dir


class ScoringEngine:
    """Engine for calculating and tracking performance scores."""

    def __init__(
        self,
        year: int | None = None,
        quarter: int | None = None,
        quarter_target: int = 100,
        daily_cap: int = 15,
    ):
        if year is None or quarter is None:
            y, q, _, _, _ = get_quarter_info()
            year = year or y
            quarter = quarter or q

        self.year = year
        self.quarter = quarter
        self.quarter_target = quarter_target
        self.daily_cap = daily_cap

        self.perf_dir = get_performance_dir(year, quarter)
        self.daily_dir = self.perf_dir / "daily"
        self.daily_dir.mkdir(parents=True, exist_ok=True)

        self.seen_events = self._load_seen_events()

    def _load_seen_events(self) -> set[str]:
        """Load all seen event IDs from daily files."""
        seen = set()
        for daily_file in self.daily_dir.glob("*.json"):
            try:
                with open(daily_file) as f:
                    data = json.load(f)
                    for event in data.get("events", []):
                        seen.add(event.get("id", ""))
            except Exception as e:
                logger.warning(f"Failed to load {daily_file}: {e}")
        return seen

    def is_duplicate(self, event_id: str) -> bool:
        """Check if an event has already been recorded."""
        return event_id in self.seen_events

    def add_event(self, event: dict) -> bool:
        """Add an event if not already seen.

        Args:
            event: Event dict with 'id' field

        Returns:
            True if event was new and added, False if duplicate
        """
        event_id = event.get("id", "")
        if not event_id:
            logger.warning("Event missing ID, generating one")
            event_id = f"{event.get('source', 'unknown')}:{event.get('type', 'unknown')}:{datetime.now().isoformat()}"
            event["id"] = event_id

        if event_id in self.seen_events:
            return False

        self.seen_events.add(event_id)
        return True

    def calculate_daily_points(
        self,
        events: list[dict],
        competency_points: dict[str, dict[str, int]],
    ) -> dict[str, int]:
        """Calculate daily points with caps applied.

        Args:
            events: List of events for the day
            competency_points: Dict mapping event_id -> {competency_id -> points}

        Returns:
            Dict of competency_id -> capped daily points
        """
        daily_totals: dict[str, int] = {}

        for event in events:
            event_id = event.get("id", "")
            points = competency_points.get(event_id, {})

            for comp_id, pts in points.items():
                current = daily_totals.get(comp_id, 0)
                # Apply daily cap
                new_total = min(current + pts, self.daily_cap)
                daily_totals[comp_id] = new_total

        return daily_totals

    def save_daily_data(
        self,
        dt: date,
        events: list[dict],
        daily_points: dict[str, int],
    ) -> Path:
        """Save daily performance data.

        Args:
            dt: Date for the data
            events: List of events
            daily_points: Calculated daily points by competency

        Returns:
            Path to saved file
        """
        _, _, start_date, _, day_of_quarter = get_quarter_info(dt)

        daily_file = self.daily_dir / f"{dt.isoformat()}.json"

        data = {
            "date": dt.isoformat(),
            "day_of_quarter": day_of_quarter,
            "events": events,
            "daily_points": daily_points,
            "daily_total": sum(daily_points.values()),
            "saved_at": datetime.now().isoformat(),
        }

        with open(daily_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Saved daily data to {daily_file}")
        return daily_file

    def load_daily_data(self, dt: date) -> dict | None:
        """Load daily data for a specific date."""
        daily_file = self.daily_dir / f"{dt.isoformat()}.json"
        if daily_file.exists():
            with open(daily_file) as f:
                return json.load(f)
        return None

    def calculate_summary(self) -> dict:
        """Calculate cumulative summary for the quarter."""
        cumulative_points: dict[str, int] = {}
        total_events = 0
        daily_trend = []
        all_events = []

        # Process all daily files
        for daily_file in sorted(self.daily_dir.glob("*.json")):
            try:
                with open(daily_file) as f:
                    data = json.load(f)

                daily_points = data.get("daily_points", {})
                for comp_id, pts in daily_points.items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts

                events = data.get("events", [])
                total_events += len(events)
                all_events.extend(events)

                daily_trend.append(
                    {
                        "date": data.get("date"),
                        "total": data.get("daily_total", 0),
                    }
                )

            except Exception as e:
                logger.warning(f"Failed to process {daily_file}: {e}")

        # Calculate percentages
        cumulative_percentage = {
            comp_id: min(100, int(pts / self.quarter_target * 100)) for comp_id, pts in cumulative_points.items()
        }

        # Overall percentage (average of all competencies)
        if cumulative_percentage:
            overall_percentage = sum(cumulative_percentage.values()) // len(cumulative_percentage)
        else:
            overall_percentage = 0

        # Find gaps (competencies below 50%)
        gaps = [comp_id for comp_id, pct in cumulative_percentage.items() if pct < 50]

        # Find highlights (high-point events)
        highlights = self._extract_highlights(all_events)

        _, _, start_date, end_date, day_of_quarter = get_quarter_info()

        summary = {
            "quarter": f"Q{self.quarter} {self.year}",
            "last_updated": datetime.now().isoformat(),
            "day_of_quarter": day_of_quarter,
            "quarter_start": start_date.isoformat(),
            "quarter_end": end_date.isoformat(),
            "total_events": total_events,
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_percentage,
            "overall_percentage": overall_percentage,
            "daily_trend": daily_trend,
            "highlights": highlights,
            "gaps": gaps,
        }

        # Save summary
        summary_file = self.perf_dir / "summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        return summary

    def _extract_highlights(self, events: list[dict], limit: int = 10) -> list[str]:
        """Extract notable highlights from events."""
        highlights = []

        # Sort by total points (sum across competencies)
        scored_events = []
        for event in events:
            points = event.get("points", {})
            total = sum(points.values()) if isinstance(points, dict) else 0
            scored_events.append((total, event))

        scored_events.sort(reverse=True, key=lambda x: x[0])

        for score, event in scored_events[:limit]:
            title = event.get("title", "")
            source = event.get("source", "")
            if title:
                highlights.append(f"{title} ({source})")

        return highlights

    def get_missing_dates(self) -> list[date]:
        """Find weekday dates missing from this quarter."""
        _, _, start_date, end_date, _ = get_quarter_info()
        today = date.today()
        end_check = min(end_date, today)

        existing_dates = set()
        for daily_file in self.daily_dir.glob("*.json"):
            try:
                dt = date.fromisoformat(daily_file.stem)
                existing_dates.add(dt)
            except ValueError:
                pass

        missing = []
        current = start_date
        while current <= end_check:
            # Only check weekdays (Mon=0, Sun=6)
            if current.weekday() < 5 and current not in existing_dates:
                missing.append(current)
            current = (
                date(current.year, current.month, current.day + 1)
                if current.day < 28
                else date(current.year, current.month + 1, 1) if current.month < 12 else date(current.year + 1, 1, 1)
            )
            # Simpler increment
            from datetime import timedelta

            current = start_date + timedelta(days=(current - start_date).days + 1)
            if current > end_check:
                break

        return missing


def generate_event_id(source: str, event_type: str, item_id: str) -> str:
    """Generate a unique event ID.

    Format: {source}:{item_id}:{event_type}
    Examples:
        - jira:AAP-12345:resolved
        - gitlab:mr:1459:merged
        - git:backend:abc123:commit
    """
    return f"{source}:{item_id}:{event_type}"
