"""Peer backfill helpers - progress state, date filtering, and benchmark computation.

Extracted from daemon._run_peer_backfill for reuse. The daemon orchestrates
D-Bus/async parts; this module provides pure business logic.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from services.stats.quarter_utils import QUARTER_STARTS

logger = logging.getLogger(__name__)


@dataclass
class PeerBackfillProgress:
    """Progress state for peer backfill operations.

    Mirrors the dict structure used by daemon._peer_backfill_progress
    so the daemon can update from this or convert to/from dict.
    """

    running: bool = False
    phase: str = ""
    phase_detail: str = ""
    total_peers: int = 0
    completed_peers: int = 0
    current_peer: str = ""
    current_level: str = ""
    total_days: int = 0
    completed_days: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    elapsed_seconds: int = 0
    total_events: int = 0
    cancelled: bool = False
    phases_completed: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    filter_info: str = "all"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for D-Bus / JSON serialization."""
        return {
            "running": self.running,
            "phase": self.phase,
            "phase_detail": self.phase_detail,
            "total_peers": self.total_peers,
            "completed_peers": self.completed_peers,
            "current_peer": self.current_peer,
            "current_level": self.current_level,
            "total_days": self.total_days,
            "completed_days": self.completed_days,
            "errors": self.errors,
            "started_at": self.started_at,
            "elapsed_seconds": self.elapsed_seconds,
            "total_events": self.total_events,
            "cancelled": self.cancelled,
            "phases_completed": self.phases_completed,
            "sources": self.sources,
            "filter_info": self.filter_info,
        }

    @classmethod
    def initial(
        cls, sources: list[str] | None, filter_label: str
    ) -> "PeerBackfillProgress":
        """Create initial progress state for a new backfill run."""
        return cls(
            running=True,
            phase="resolve_github",
            phase_detail="Resolving GitHub usernames...",
            current_peer="resolving GitHub usernames...",
            started_at=datetime.now().isoformat(timespec="seconds"),
            phases_completed=[],
            sources=sources or [],
            filter_info=filter_label or "all",
        )


def build_filter_label(
    sources: list[str] | None,
    usernames: list[str] | None,
    date_start: str,
    date_end: str,
) -> str:
    """Build human-readable filter label for progress display."""
    parts = []
    if sources:
        parts.append(f"sources={sources}")
    if usernames:
        parts.append(f"peers={usernames}")
    if date_start or date_end:
        parts.append(f"range={date_start or 'q-start'}..{date_end or 'today'}")
    return ", ".join(parts) if parts else "all"


def get_weekdays_in_quarter_range(
    year: int,
    quarter: int,
    date_start: str = "",
    date_end: str = "",
) -> list[date]:
    """Return list of weekdays (Mon–Fri) in the quarter, optionally filtered by range."""
    sm, sd = QUARTER_STARTS[quarter]
    quarter_start = date(year, sm, sd)
    today = date.today()
    weekdays: list[date] = []
    current = quarter_start
    while current <= today:
        if current.weekday() < 5:
            weekdays.append(current)
        current += timedelta(days=1)

    if date_start:
        try:
            ds = date.fromisoformat(date_start)
            weekdays = [d for d in weekdays if d >= ds]
        except ValueError:
            pass
    if date_end:
        try:
            de = date.fromisoformat(date_end)
            weekdays = [d for d in weekdays if d <= de]
        except ValueError:
            pass
    return weekdays


def compute_distribution(values: list[float | int]) -> dict[str, float | int]:
    """Compute min/max/median/p25/p75/avg from a list of numeric values."""
    if not values:
        return {
            "min": 0,
            "max": 0,
            "median": 0,
            "p25": 0,
            "p75": 0,
            "avg": 0,
            "count": 0,
        }
    sv = sorted(values)
    n = len(sv)
    return {
        "min": round(sv[0], 1),
        "max": round(sv[-1], 1),
        "median": round(statistics.median(sv), 1),
        "p25": round(sv[max(0, n // 4)], 1),
        "p75": round(sv[min(n - 1, 3 * n // 4)], 1),
        "avg": round(statistics.mean(sv), 1),
        "count": n,
    }


def _load_peer_summaries_for_level(
    peers_dir: Path,
    peer_list: list[dict],
    min_events: int,
    min_days: int,
    blacklist: set[str],
    self_username: str,
) -> tuple[dict[str, Any], int]:
    level_data: dict[str, Any] = {
        "engineers": [],
        "excluded_sparse": [],
        "summaries": [],
        "avg_competency_pct": {},
        "avg_competency_points": {},
        "avg_overall_pct": 0,
        "comparable_avg_competency_pct": {},
        "comparable_avg_overall_pct": 0,
        "comparable_stats_competency": {},
        "comparable_stats_overall": {},
        "avg_daily_events": 0.0,
        "avg_event_counts_by_source": {},
        "avg_days_with_events": 0.0,
        "stats_overall": {},
        "stats_competency": {},
    }
    roster_count = 0
    for peer in peer_list:
        uname = peer.get("username", "")
        if uname == self_username:
            continue
        roster_count += 1
        if uname in blacklist:
            level_data["excluded_sparse"].append(uname)
            continue
        summary_file = peers_dir / uname / "summary.json"
        if summary_file.exists():
            try:
                with open(summary_file, encoding="utf-8") as f:
                    s = json.load(f)
                total_ev = s.get("total_events", 0)
                active_days = s.get("days_with_events", s.get("days_captured", 0))
                if total_ev < min_events or active_days < min_days:
                    level_data["excluded_sparse"].append(uname)
                    continue
                if total_ev > 0:
                    level_data["engineers"].append(uname)
                    level_data["summaries"].append(s)
            except Exception as e:
                logger.warning("Failed to load peer summary %s: %s", summary_file, e)
                continue

    if not level_data["summaries"] and level_data["excluded_sparse"]:
        for uname in list(level_data["excluded_sparse"]):
            if uname in blacklist:
                continue
            summary_file = peers_dir / uname / "summary.json"
            if summary_file.exists():
                try:
                    with open(summary_file, encoding="utf-8") as f:
                        s = json.load(f)
                    if s.get("total_events", 0) > 0:
                        level_data["engineers"].append(uname)
                        level_data["summaries"].append(s)
                        level_data["excluded_sparse"].remove(uname)
                except Exception as e:
                    logger.warning(
                        "Failed to load peer summary %s: %s", summary_file, e
                    )
                    continue

    return level_data, roster_count


def _compute_level_benchmarks(
    level_data: dict[str, Any], roster_count: int
) -> dict[str, Any]:
    n = len(level_data["summaries"])
    if n > 0:
        all_comp_ids: set[str] = set()
        for s in level_data["summaries"]:
            all_comp_ids.update(s.get("cumulative_percentage", {}).keys())

        excluded_comps: set[str] = set()
        for comp_id in all_comp_ids:
            all_zero = all(
                s.get("cumulative_points", {}).get(comp_id, 0) == 0
                for s in level_data["summaries"]
            )
            if all_zero:
                excluded_comps.add(comp_id)

        comparable_comps = all_comp_ids - excluded_comps
        for comp_id in comparable_comps:
            pct_sum = sum(
                s.get("cumulative_percentage", {}).get(comp_id, 0)
                for s in level_data["summaries"]
            )
            pts_sum = sum(
                s.get("cumulative_points", {}).get(comp_id, 0)
                for s in level_data["summaries"]
            )
            level_data["avg_competency_pct"][comp_id] = round(pct_sum / n)
            level_data["avg_competency_points"][comp_id] = round(pts_sum / n)

            comp_values = [
                s.get("cumulative_percentage", {}).get(comp_id, 0)
                for s in level_data["summaries"]
            ]
            level_data["stats_competency"][comp_id] = compute_distribution(comp_values)

            comp_comparable_pct_sum = sum(
                s.get("comparable_percentage", s.get("cumulative_percentage", {})).get(
                    comp_id, 0
                )
                for s in level_data["summaries"]
            )
            level_data["comparable_avg_competency_pct"][comp_id] = round(
                comp_comparable_pct_sum / n
            )

            comp_comparable_values = [
                s.get("comparable_percentage", s.get("cumulative_percentage", {})).get(
                    comp_id, 0
                )
                for s in level_data["summaries"]
            ]
            level_data["comparable_stats_competency"][comp_id] = compute_distribution(
                comp_comparable_values
            )

        level_data["excluded_competencies"] = sorted(excluded_comps)

        overall_values = [
            s.get("overall_percentage", 0) for s in level_data["summaries"]
        ]
        level_data["avg_overall_pct"] = round(sum(overall_values) / n)
        level_data["stats_overall"] = compute_distribution(overall_values)

        comparable_overall_values = [
            s.get("comparable_overall", s.get("overall_percentage", 0))
            for s in level_data["summaries"]
        ]
        level_data["comparable_avg_overall_pct"] = round(
            sum(comparable_overall_values) / n
        )
        level_data["comparable_stats_overall"] = compute_distribution(
            comparable_overall_values
        )

        level_data["avg_daily_events"] = round(
            sum(s.get("avg_daily_events", 0) for s in level_data["summaries"]) / n,
            1,
        )

        level_data["avg_days_with_events"] = round(
            sum(
                s.get("days_with_events", s.get("days_captured", 0))
                for s in level_data["summaries"]
            )
            / n,
            1,
        )

        all_sources: set[str] = set()
        for s in level_data["summaries"]:
            all_sources.update(s.get("event_counts_by_source", {}).keys())
        for src in all_sources:
            level_data["avg_event_counts_by_source"][src] = round(
                sum(
                    s.get("event_counts_by_source", {}).get(src, 0)
                    for s in level_data["summaries"]
                )
                / n,
                1,
            )

    level_data["peer_count"] = n
    level_data["roster_count"] = roster_count
    del level_data["summaries"]
    return level_data


def compute_peer_benchmarks(
    peers_dir: Path,
    peers_config: dict[str, list[dict]],
    config: dict[str, Any],
    self_username: str = "",
) -> dict[str, Any]:
    """Aggregate peer summaries into benchmarks grouped by level.

    Reads summary.json from each peer subdir, applies min_events/min_days
    filters, and computes level-level averages and distributions. Returns
    the benchmarks dict (caller writes to peers_dir/benchmarks.json).

    Config keys: min_peer_events, min_peer_active_days, blacklisted_peers.
    """
    if not peers_dir.exists():
        return {}

    min_events = config.get("min_peer_events", 30)
    min_days = config.get("min_peer_active_days", 15)
    blacklist = set(config.get("blacklisted_peers", []))
    levels: dict[str, dict[str, Any]] = {}

    for level_key, peer_list in peers_config.items():
        level_data, roster_count = _load_peer_summaries_for_level(
            peers_dir, peer_list, min_events, min_days, blacklist, self_username
        )
        levels[level_key] = _compute_level_benchmarks(level_data, roster_count)

    return {
        "levels": levels,
        "last_updated": datetime.now().isoformat(),
    }
