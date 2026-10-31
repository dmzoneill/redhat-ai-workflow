"""Day detail and competency evidence D-Bus handlers for the stats daemon.

Split out of ``services/stats/daemon.py``; ``StatsDaemon`` mixes
``DayDetailMixin`` in, so the ``get_day_detail`` and
``get_competency_evidence`` D-Bus methods are unchanged.
"""

import asyncio
import logging
from datetime import date
from pathlib import Path

from services.stats.handler_utils import (
    DATA_ERRORS,
    HIERARCHY_CACHE_NAME,
    category_points,
    find_issue_keys,
    load_daily_files,
    load_issue_cache,
    now_local,
    quarter_of,
    read_json,
)
from services.stats.quarter_data import QuarterDataMixin
from services.stats.scorer import COMPETENCY_DEFS, get_competency_meta, get_gap_suggestions

logger = logging.getLogger(__name__)

TARGET_PER_COMPETENCY = 100
MAX_EVIDENCE_PER_COMPETENCY = 20
GAP_THRESHOLD_PCT = 50


def classify_match_reason(title: str, source: str, event_type: str, comp_id: str) -> str:
    """List all signals that matched for this event/competency pair."""
    defn = COMPETENCY_DEFS.get(comp_id, {})
    text = title.lower()
    reasons: list[str] = []

    if event_type in defn.get("event_types", []):
        reasons.append(f"type:{event_type}")
    reasons.extend(f'"{phrase}"' for phrase in defn.get("phrases", []) if phrase in text)
    reasons.extend(f"kw:{kw}" for kw in defn.get("keywords", []) if kw in text)
    if comp_id == "opportunity_recognition" and source == "github":
        reasons.append("src:github")

    if not reasons:
        return "pattern match"
    return " + ".join(reasons[:5])


def issue_lineage(key: str, issue_info: dict[str, dict]) -> dict:
    """Issue -> epic -> ANSTRAT lineage for one issue key."""
    info = issue_info.get(key, {})
    entry: dict = {"key": key, "summary": info.get("summary", "")}
    epic_key = info.get("epic", "")
    if epic_key:
        epic_info = issue_info.get(epic_key, {})
        entry["epic"] = {"key": epic_key, "summary": epic_info.get("summary", "")}
        anstrat_key = epic_info.get("parent_initiative", "")
        if anstrat_key:
            entry["anstrat"] = {
                "key": anstrat_key,
                "summary": issue_info.get(anstrat_key, {}).get("summary", ""),
            }
    return entry


def annotate_events(events: list[dict], issue_info: dict[str, dict]) -> None:
    """Add ``issue_keys`` and ``lineage`` to each event in place."""
    for ev in events:
        found_keys = find_issue_keys(ev.get("title", ""))
        ev["issue_keys"] = found_keys
        ev["lineage"] = [issue_lineage(ik, issue_info) for ik in found_keys]


def collect_evidence(daily_dir: Path) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Per-competency evidence (capped) and point totals from the daily files."""
    evidence: dict[str, list[dict]] = {}
    totals: dict[str, int] = {}
    for path, data in load_daily_files(daily_dir):
        if data is None:
            continue
        for ev in data.get("events", []):
            ev_source = ev.get("source", "unknown")
            ev_type = ev.get("type", "unknown")
            ev_title = ev.get("title", "")
            for comp_id, pts in ev.get("points", {}).items():
                items = evidence.setdefault(comp_id, [])
                totals[comp_id] = totals.get(comp_id, 0) + pts
                if len(items) >= MAX_EVIDENCE_PER_COMPETENCY:
                    continue
                items.append(
                    {
                        "date": data.get("date", path.stem),
                        "title": ev_title[:120],
                        "source": ev_source,
                        "type": ev_type,
                        "points": pts,
                        "issue_keys": find_issue_keys(ev_title),
                        "url": ev.get("url", ""),
                        "match_reason": classify_match_reason(ev_title, ev_source, ev_type, comp_id),
                    }
                )
    return evidence, totals


def _percentage(total: int) -> int:
    return min(round(total / TARGET_PER_COMPETENCY * 100), 100)


def competency_meta(evidence: dict[str, list[dict]], totals: dict[str, int]) -> dict[str, dict]:
    """Metadata, percentage and evidence count for every competency."""
    meta: dict[str, dict] = {}
    for comp_id in COMPETENCY_DEFS:
        total = totals.get(comp_id, 0)
        meta[comp_id] = {
            **get_competency_meta(comp_id),
            "percentage": _percentage(total),
            "points": total,
            "target": TARGET_PER_COMPETENCY,
            "evidence_count": len(evidence.get(comp_id, [])),
        }
    return meta


def gap_suggestions(evidence: dict[str, list[dict]], totals: dict[str, int]) -> dict[str, dict]:
    """Suggestions for every competency below the gap threshold."""
    gaps: dict[str, dict] = {}
    for comp_id in COMPETENCY_DEFS:
        total = totals.get(comp_id, 0)
        pct = _percentage(total)
        if pct >= GAP_THRESHOLD_PCT:
            continue
        meta = get_competency_meta(comp_id)
        gaps[comp_id] = {
            "percentage": pct,
            "points": total,
            "target": TARGET_PER_COMPETENCY,
            "deficit": TARGET_PER_COMPETENCY - total,
            "suggestions": get_gap_suggestions(comp_id),
            "evidence_count": len(evidence.get(comp_id, [])),
            "goal": meta["goal"],
            "description": meta["description"],
            "category": meta["category"],
        }
    return gaps


def _no_data(date_str: str) -> dict:
    return {
        "success": True,
        "date": date_str,
        "events": [],
        "daily_points": {},
        "daily_total": 0,
        "has_data": False,
    }


class DayDetailMixin(QuarterDataMixin):
    """``get_day_detail`` and ``get_competency_evidence`` D-Bus handlers."""

    _classify_match_reason = staticmethod(classify_match_reason)

    async def _handle_get_day_detail(self, **kwargs) -> dict:
        """Return full event list for a specific date."""
        date_str = kwargs.get("date", "")
        if not date_str:
            return {"success": False, "error": "No date provided"}

        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            return {"success": False, "error": f"Invalid date: {date_str}"}

        year, quarter = target.year, quarter_of(target)
        daily_file = self.daily_dir(year, quarter) / f"{date_str}.json"
        if not daily_file.exists():
            return _no_data(date_str)

        try:
            data = await asyncio.to_thread(read_json, daily_file)
            cache_file = self.perf_dir(year, quarter) / HIERARCHY_CACHE_NAME
            issue_info = (await asyncio.to_thread(load_issue_cache, cache_file)).get("issues", {})

            events = data.get("events", [])
            annotate_events(events, issue_info)
            return {
                "success": True,
                "date": date_str,
                "events": events,
                "daily_points": data.get("daily_points", {}),
                "daily_total": data.get("daily_total", 0),
                "category_points": category_points(data.get("daily_points", {})),
                "has_data": True,
            }
        except DATA_ERRORS as e:
            logger.error("Failed to read day detail for %s: %s", date_str, e)
            return {"success": False, "error": str(e)}

    async def _handle_get_competency_evidence(self, **kwargs) -> dict:
        """Return per-competency event breakdown with evidence and metadata."""
        return await self.competency_evidence(kwargs.get("year"), kwargs.get("quarter"))

    async def competency_evidence(self, year: int | None = None, quarter: int | None = None) -> dict:
        """Per-competency evidence, totals, metadata and gap suggestions for the quarter."""
        now = now_local()
        year = year or now.year
        quarter = quarter or quarter_of(now)

        evidence, totals = await asyncio.to_thread(collect_evidence, self.daily_dir(year, quarter))
        return {
            "success": True,
            "competency_evidence": evidence,
            "competency_totals": totals,
            "competency_meta": competency_meta(evidence, totals),
            "gap_suggestions": gap_suggestions(evidence, totals),
        }
