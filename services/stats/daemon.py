#!/usr/bin/env python3
"""
Stats Daemon - Serves agent statistics via D-Bus

This daemon provides D-Bus access to agent statistics files:
- agent_stats.json: Tool calls, skill executions, memory ops
- inference_stats.json: LLM inference statistics
- skill_execution.json: Current skill execution state

The daemon watches these files for changes and serves them via D-Bus,
allowing the VS Code extension to read stats without direct file access.

D-Bus Service: com.aiworkflow.BotStats
Object Path: /com/aiworkflow/BotStats

Usage:
    python -m services.stats           # Run daemon
    python -m services.stats --status  # Check if running
    python -m services.stats --dbus    # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-stats
    systemctl --user status bot-stats
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from server.paths import (
    AA_CONFIG_DIR,
    AGENT_STATS_FILE,
    INFERENCE_STATS_FILE,
    SKILL_EXECUTION_FILE,
)
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.stats.collector import DataCollector
from services.stats.email_parser import (
    get_executive_emails_dir,
    get_executive_senders,
    parse_email_text,
)
from services.stats.scorer import (
    COMPETENCY_DEFS,
    SCORING_CONFIG_FILE,
    get_competency_meta,
    get_effective_defs,
    get_gap_suggestions,
    get_merged_config,
    load_scoring_config,
    map_competencies,
    save_scoring_config,
)
from services.stats.strategy import build_strategy_alignment


def get_performance_summary_path() -> Path:
    """Get current quarter's performance summary file path."""
    now = datetime.now()
    year = now.year
    quarter = (now.month - 1) // 3 + 1
    return (
        AA_CONFIG_DIR
        / "performance"
        / str(year)
        / f"q{quarter}"
        / "performance"
        / "summary.json"
    )


logger = logging.getLogger(__name__)


class StatsDaemon(DaemonDBusBase, BaseDaemon):
    """Stats daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "stats"
    description = "Stats Daemon - Agent statistics via D-Bus"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotStats"
    object_path = "/com/aiworkflow/BotStats"
    interface_name = "com.aiworkflow.BotStats"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        self._stats_cache: dict[str, Any] = {}
        self._last_modified: dict[str, float] = {}
        self._collector = DataCollector()

        # Register D-Bus handlers
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("get_agent_stats", self._handle_get_agent_stats)
        self.register_handler("get_inference_stats", self._handle_get_inference_stats)
        self.register_handler("get_skill_execution", self._handle_get_skill_execution)

        # Performance / QC handlers
        self.register_handler("collect_daily", self._handle_collect_daily)
        self.register_handler("backfill", self._handle_backfill)
        self.register_handler("evaluate_all", self._handle_evaluate_all)
        self.register_handler("get_scoring_config", self._handle_get_scoring_config)
        self.register_handler("set_scoring_config", self._handle_set_scoring_config)
        self.register_handler("reset_scoring_config", self._handle_reset_scoring_config)
        self.register_handler("get_captured_days", self._handle_get_captured_days)
        self.register_handler("get_issue_hierarchy", self._handle_get_issue_hierarchy)
        self.register_handler("export_report", self._handle_export_report)
        self.register_handler("get_day_detail", self._handle_get_day_detail)
        self.register_handler(
            "get_competency_evidence", self._handle_get_competency_evidence
        )

        # Executive strategy mapping handlers
        self.register_handler(
            "parse_executive_email", self._handle_parse_executive_email
        )
        self.register_handler("map_deliverables", self._handle_map_deliverables)
        self.register_handler(
            "list_executive_emails", self._handle_list_executive_emails
        )
        self.register_handler(
            "delete_executive_email", self._handle_delete_executive_email
        )
        self.register_handler(
            "search_executive_gmail", self._handle_search_executive_gmail
        )
        self.register_handler("read_gmail_message", self._handle_read_gmail_message)
        self.register_handler(
            "backfill_executive_emails", self._handle_backfill_executive_emails
        )

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return stats-specific statistics."""
        return {
            "files_watched": 4,
            "cache_entries": len(self._stats_cache),
            "last_refresh": datetime.now().isoformat(),
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        return {
            "status": "running",
            "files": {
                "agent_stats": str(AGENT_STATS_FILE),
                "inference_stats": str(INFERENCE_STATS_FILE),
                "skill_execution": str(SKILL_EXECUTION_FILE),
                "performance_summary": str(get_performance_summary_path()),
            },
            "cache_age": {
                k: datetime.now().timestamp() - v
                for k, v in self._last_modified.items()
            },
        }

    # ==================== D-Bus Handlers ====================

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full stats state for UI."""
        perf_summary = self._load_file(get_performance_summary_path())
        performance_data = None
        if perf_summary:
            now = datetime.now()
            quarter = (now.month - 1) // 3 + 1
            quarter_start = datetime(now.year, (quarter - 1) * 3 + 1, 1)
            day_of_quarter = (now - quarter_start).days + 1

            performance_data = {
                "last_updated": perf_summary.get("last_updated", now.isoformat()),
                "quarter": f"Q{quarter} {now.year}",
                "day_of_quarter": day_of_quarter,
                "overall_percentage": perf_summary.get("overall_percentage", 0),
                "competencies": {
                    k: {
                        "points": perf_summary.get("cumulative_points", {}).get(k, 0),
                        "percentage": v,
                    }
                    for k, v in perf_summary.get("cumulative_percentage", {}).items()
                },
                "highlights": perf_summary.get("highlights", []),
                "gaps": perf_summary.get("gaps", []),
                "questions_summary": perf_summary.get("questions_summary"),
                "strategy_alignment": perf_summary.get("strategy_alignment"),
            }

        return {
            "success": True,
            "state": {
                "agent_stats": self._load_file(AGENT_STATS_FILE),
                "inference_stats": self._load_file(INFERENCE_STATS_FILE),
                "skill_execution": self._load_file(SKILL_EXECUTION_FILE),
                "performance": performance_data,
                "updated_at": datetime.now().isoformat(),
            },
        }

    async def _handle_get_agent_stats(self, **kwargs) -> dict:
        """Get agent statistics (tool calls, skill executions, etc.)."""
        stats = self._load_file(AGENT_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Agent stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_inference_stats(self, **kwargs) -> dict:
        """Get inference statistics (LLM usage, tokens, etc.)."""
        stats = self._load_file(INFERENCE_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Inference stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_skill_execution(self, **kwargs) -> dict:
        """Get current skill execution state."""
        state = self._load_file(SKILL_EXECUTION_FILE)
        if state is None:
            return {"success": False, "error": "Skill execution file not found"}
        return {"success": True, "execution": state}

    # ==================== Performance / QC ====================

    def _get_perf_dir(
        self, year: int | None = None, quarter: int | None = None
    ) -> Path:
        return self._collector.get_perf_dir(year, quarter)

    def _get_daily_dir(
        self, year: int | None = None, quarter: int | None = None
    ) -> Path:
        return self._collector.get_daily_dir(year, quarter)

    def _get_executive_emails_dir(
        self, year: int | None = None, quarter: int | None = None
    ) -> Path:
        return get_executive_emails_dir(self._get_perf_dir(year, quarter))

    def _update_summary(
        self, year: int | None = None, quarter: int | None = None
    ) -> dict:
        """Recalculate and update the quarter summary from all daily files."""
        daily_dir = self._get_daily_dir(year, quarter)
        if not daily_dir.exists():
            return {}

        cumulative_points: dict[str, int] = {}
        total_events = 0
        highlights: list[str] = []

        for daily_file in sorted(daily_dir.glob("*.json")):
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                total_events += len(data.get("events", []))
                for ev in data.get("events", [])[:3]:
                    if ev.get("title") and len(highlights) < 10:
                        highlights.append(ev["title"][:80])
            except Exception:
                continue

        _, _, _, target_per_competency = get_effective_defs()
        cumulative_pct = {
            k: min(round(v / target_per_competency * 100), 100)
            for k, v in cumulative_points.items()
        }
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))

        gaps = [k for k, v in cumulative_pct.items() if v < 25]

        now = datetime.now()
        y = year or now.year
        q = quarter or ((now.month - 1) // 3 + 1)
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts[q]
        day_of_quarter = (now.date() - date(y, sm, sd)).days + 1

        perf_dir = self._get_perf_dir(year, quarter)
        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_alignment = build_strategy_alignment(
            y,
            q,
            cumulative_points,
            perf_dir,
            emails_dir,
        )

        summary = {
            "year": y,
            "quarter": q,
            "day_of_quarter": day_of_quarter,
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": overall,
            "total_events": total_events,
            "highlights": highlights,
            "gaps": gaps,
            "strategy_alignment": strategy_alignment,
            "last_updated": now.isoformat(),
        }

        perf_dir.mkdir(parents=True, exist_ok=True)
        summary_file = perf_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        self._stats_cache.pop(str(summary_file), None)
        self._last_modified.pop(str(summary_file), None)

        return summary

    async def _handle_collect_daily(self, **kwargs) -> dict:
        """Collect daily performance data for a given date."""
        date_str = kwargs.get("date", "")
        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        try:
            loop = asyncio.get_event_loop()
            daily_data = await loop.run_in_executor(
                None,
                self._collector.collect_for_date,
                target,
            )
            await loop.run_in_executor(None, self._update_summary)
            return {
                "success": True,
                "event_count": len(daily_data.get("events", [])),
                "daily_total": daily_data.get("daily_total", 0),
                "date": target.isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to collect daily data: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_backfill(self, **kwargs) -> dict:
        """Re-collect ALL weekdays in the current quarter."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts[quarter]
        quarter_start = date(year, sm, sd)

        all_weekdays: list[date] = []
        current = quarter_start
        today = date.today()
        while current <= today:
            if current.weekday() < 5:
                all_weekdays.append(current)
            current += timedelta(days=1)

        results = []
        loop = asyncio.get_event_loop()

        for d in all_weekdays:
            try:
                daily_data = await loop.run_in_executor(
                    None,
                    self._collector.collect_for_date,
                    d,
                )
                results.append(
                    {
                        "date": d.isoformat(),
                        "success": True,
                        "events": len(daily_data.get("events", [])),
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "date": d.isoformat(),
                        "success": False,
                        "error": str(e),
                    }
                )

        if all_weekdays:
            await loop.run_in_executor(None, self._update_summary)

        return {
            "success": True,
            "processed": len(all_weekdays),
            "remaining": 0,
            "results": results,
            "days_processed": len(all_weekdays),
        }

    async def _handle_evaluate_all(self, **kwargs) -> dict:
        """Re-score every event in the quarter using current scoring config."""
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        daily_dir = self._get_daily_dir(year, quarter)

        if not daily_dir.exists():
            return {"success": True, "files_updated": 0}

        loop = asyncio.get_event_loop()

        def _rescore() -> int:
            _, _, daily_cap, _ = get_effective_defs()
            updated = 0
            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                events = data.get("events", [])
                for ev in events:
                    ev["points"] = map_competencies(
                        ev.get("title", ""),
                        ev.get("source", ""),
                        ev.get("type", ""),
                    )

                daily_points: dict[str, int] = {}
                for ev in events:
                    for comp_id, pts in ev.get("points", {}).items():
                        current = daily_points.get(comp_id, 0)
                        daily_points[comp_id] = min(current + pts, daily_cap)

                data["daily_points"] = daily_points
                data["daily_total"] = sum(daily_points.values())
                data["re_evaluated_at"] = datetime.now().isoformat()

                with open(daily_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                updated += 1

            return updated

        files_updated = await loop.run_in_executor(None, _rescore)
        await loop.run_in_executor(None, self._update_summary, year, quarter)

        return {
            "success": True,
            "files_updated": files_updated,
            "quarter": f"Q{quarter} {year}",
        }

    async def _handle_get_scoring_config(self, **kwargs) -> dict:
        """Return the full merged scoring config (defaults + user overrides)."""
        cfg = get_merged_config()
        for comp_id, comp_cfg in cfg.get("competencies", {}).items():
            defn = COMPETENCY_DEFS.get(comp_id, {})
            comp_cfg["name"] = defn.get("name", comp_id)
            comp_cfg["category"] = defn.get("category", "Other")
        return {"success": True, "config": cfg}

    async def _handle_set_scoring_config(self, **kwargs) -> dict:
        """Update scoring config with partial overrides, save, and re-evaluate."""
        try:
            current = load_scoring_config()

            for key in ("min_signals", "daily_cap", "target_per_competency"):
                if key in kwargs:
                    current[key] = int(kwargs[key])

            comp_updates = kwargs.get("competencies")
            if comp_updates and isinstance(comp_updates, dict):
                if "competencies" not in current:
                    current["competencies"] = {}
                for comp_id, updates in comp_updates.items():
                    if comp_id not in COMPETENCY_DEFS:
                        continue
                    if comp_id not in current["competencies"]:
                        current["competencies"][comp_id] = {}
                    for field in ("base_points", "phrases", "keywords", "event_types"):
                        if field in updates:
                            val = updates[field]
                            if field == "base_points":
                                val = int(val)
                            current["competencies"][comp_id][field] = val

            save_scoring_config(current)

            result = await self._handle_evaluate_all(**kwargs)
            return {
                "success": True,
                "config_saved": True,
                "re_evaluated": result.get("files_updated", 0),
            }
        except Exception as e:
            logger.error(f"Failed to set scoring config: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_reset_scoring_config(self, **kwargs) -> dict:
        """Delete user overrides and re-evaluate with defaults."""
        try:
            if SCORING_CONFIG_FILE.exists():
                SCORING_CONFIG_FILE.unlink()
            result = await self._handle_evaluate_all(**kwargs)
            return {
                "success": True,
                "reset": True,
                "re_evaluated": result.get("files_updated", 0),
            }
        except Exception as e:
            logger.error(f"Failed to reset scoring config: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_captured_days(self, **kwargs) -> dict:
        """Return list of captured days with basic stats for the quarter."""
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        daily_dir = self._get_daily_dir(year, quarter)
        days: list[dict] = []

        cat_map: dict[str, str] = {}
        for cid, defn in COMPETENCY_DEFS.items():
            cat_map[cid] = defn.get("category", "Other")

        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    sources = set()
                    for ev in data.get("events", []):
                        sources.add(ev.get("source", "unknown"))

                    cat_points: dict[str, int] = {}
                    for cid, pts in data.get("daily_points", {}).items():
                        cat = cat_map.get(cid, "Other")
                        cat_points[cat] = cat_points.get(cat, 0) + pts

                    days.append(
                        {
                            "date": data.get("date", f.stem),
                            "event_count": len(data.get("events", [])),
                            "total_points": data.get("daily_total", 0),
                            "sources": list(sources),
                            "category_points": cat_points,
                        }
                    )
                except Exception:
                    days.append(
                        {
                            "date": f.stem,
                            "event_count": 0,
                            "total_points": 0,
                            "sources": [],
                            "category_points": {},
                        }
                    )

        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts[quarter]
        q_start = date(year, sm, sd)
        today = date.today()
        q_end_month = sm + 2
        q_end = date(year, q_end_month, 1) + timedelta(days=31)
        q_end = q_end.replace(day=1) - timedelta(days=1)
        end_date = min(today, q_end)

        total_weekdays = 0
        current = q_start
        while current <= end_date:
            if current.weekday() < 5:
                total_weekdays += 1
            current += timedelta(days=1)

        captured = len(days)
        pct = round(captured / max(total_weekdays, 1) * 100)

        return {
            "success": True,
            "days": days,
            "year": year,
            "quarter": quarter,
            "coverage": {
                "total_weekdays": total_weekdays,
                "captured": captured,
                "percentage": pct,
            },
        }

    async def _handle_get_issue_hierarchy(self, **kwargs) -> dict:
        """Extract issue keys from daily data and build hierarchy tree."""
        import subprocess

        refresh = kwargs.get("refresh_from_jira", False)
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1

        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = self._get_daily_dir(year, quarter)
        cache_file = perf_dir / "jira_hierarchy_cache.json"

        issue_keys: dict[str, dict] = {}
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        title = ev.get("title", "")
                        pts = sum(ev.get("points", {}).values())
                        keys_in_title = re.findall(r"((?:AAP|ANSTRAT)-\d+)", title)
                        for key in keys_in_title:
                            if key not in issue_keys:
                                issue_keys[key] = {
                                    "points": 0,
                                    "titles": [],
                                    "event_count": 0,
                                }
                            issue_keys[key]["points"] += pts
                            issue_keys[key]["event_count"] += 1
                            if title not in issue_keys[key]["titles"]:
                                issue_keys[key]["titles"].append(title[:120])
                except Exception:
                    continue

        def extract_keywords(titles: list[str]) -> list[str]:
            kw_patterns = [
                "billing",
                "mock",
                "test",
                "ci/cd",
                "pipeline",
                "deploy",
                "api",
                "fix",
                "feat",
                "refactor",
                "config",
                "auth",
                "grafana",
                "monitoring",
                "alert",
                "release",
                "review",
                "docs",
                "migration",
                "performance",
                "security",
                "integration",
            ]
            found = set()
            for t in titles:
                t_lower = t.lower()
                for kw in kw_patterns:
                    if kw in t_lower:
                        found.add(kw)
            return sorted(found)

        cached: dict = {}
        if cache_file.exists() and not refresh:
            try:
                with open(cache_file, encoding="utf-8") as fh:
                    cached = json.load(fh)
            except Exception:
                pass

        issue_info: dict[str, dict] = cached.get("issues", {})

        if refresh and issue_keys:
            rh_env = {**os.environ, "HOME": str(Path.home())}
            aap_keys = [k for k in issue_keys if k.startswith("AAP-")]

            for key in aap_keys[:30]:
                try:
                    result = subprocess.check_output(
                        ["rh-issue", "view-issue", key],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                        env=rh_env,
                    )
                    info: dict[str, str] = {"key": key, "type": "story"}
                    for line in result.split("\n"):
                        m = re.match(
                            r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                            line.strip(),
                            re.IGNORECASE,
                        )
                        if m:
                            field = m.group(1).strip().lower().replace(" ", "_")
                            val = m.group(2).strip()
                            if field in (
                                "summary",
                                "status",
                                "issue_type",
                                "issuetype",
                            ):
                                info[field.replace("issuetype", "issue_type")] = val
                            if field in ("epic_link", "epic", "parent"):
                                info["epic"] = val
                            if field == "component/s":
                                info["component"] = val
                    if "summary" not in info:
                        for line in result.split("\n"):
                            if key in line:
                                info["summary"] = line.split(key)[-1].strip(": ")[:100]
                                break
                    issue_info[key] = info
                except Exception as e:
                    logger.debug(f"Failed to fetch {key}: {e}")

            epic_keys_set: set[str] = set()
            for info in issue_info.values():
                epic_key = info.get("epic", "")
                if epic_key and epic_key.startswith("AAP-"):
                    epic_keys_set.add(epic_key)

            for epic_key in epic_keys_set:
                if epic_key not in issue_info:
                    try:
                        result = subprocess.check_output(
                            ["rh-issue", "view-issue", epic_key],
                            text=True,
                            stderr=subprocess.DEVNULL,
                            timeout=15,
                            env=rh_env,
                        )
                        einfo: dict[str, str] = {"key": epic_key, "issue_type": "Epic"}
                        for line in result.split("\n"):
                            m = re.match(
                                r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                                line.strip(),
                                re.IGNORECASE,
                            )
                            if m:
                                field = m.group(1).strip().lower().replace(" ", "_")
                                val = m.group(2).strip()
                                if field == "summary":
                                    einfo["summary"] = val
                                if field == "component/s":
                                    einfo["component"] = val
                        issue_info[epic_key] = einfo
                    except Exception as e:
                        logger.debug(f"Failed to fetch epic {epic_key}: {e}")

            if epic_keys_set:
                component = None
                for info in issue_info.values():
                    c = info.get("component", "")
                    if c and c != "None":
                        component = c
                        break

                anstrat_keys: list[str] = []
                try:
                    jql = (
                        f'project = ANSTRAT AND component = "{component}"'
                        if component
                        else 'project = ANSTRAT AND summary ~ "Automation Analytics"'
                    )
                    result = subprocess.check_output(
                        ["rh-issue", "search", jql, "--max-results", "50"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        timeout=30,
                        env=rh_env,
                    )
                    anstrat_keys = re.findall(r"(ANSTRAT-\d+)", result)
                    for line in result.split("\n"):
                        for ak in anstrat_keys:
                            if ak in line and ak not in issue_info:
                                parts = line.split("|")
                                if len(parts) >= 5:
                                    issue_info[ak] = {
                                        "key": ak,
                                        "issue_type": (
                                            parts[1].strip()
                                            if len(parts) > 1
                                            else "Initiative"
                                        ),
                                        "summary": (
                                            parts[4].strip()[:100]
                                            if len(parts) > 4
                                            else ak
                                        ),
                                    }
                except Exception as e:
                    logger.debug(f"Failed to search ANSTRATs: {e}")

                unmapped_epics = {
                    k
                    for k in epic_keys_set
                    if not issue_info.get(k, {}).get("parent_initiative")
                }
                epic_list_str = ", ".join(sorted(epic_keys_set))
                for anstrat_key in anstrat_keys:
                    if not unmapped_epics:
                        break
                    try:
                        jql = (
                            f'"Parent Link" = {anstrat_key}'
                            f" AND key in ({epic_list_str})"
                        )
                        result = subprocess.check_output(
                            ["rh-issue", "search", jql, "--max-results", "20"],
                            text=True,
                            stderr=subprocess.DEVNULL,
                            timeout=20,
                            env=rh_env,
                        )
                        child_epics = re.findall(r"(AAP-\d+)", result)
                        for ce in child_epics:
                            if ce in issue_info:
                                issue_info[ce]["parent_initiative"] = anstrat_key
                            else:
                                issue_info[ce] = {
                                    "key": ce,
                                    "parent_initiative": anstrat_key,
                                }
                            unmapped_epics.discard(ce)
                    except Exception as e:
                        logger.debug(f"Failed to query children of {anstrat_key}: {e}")

            perf_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {"issues": issue_info, "updated": datetime.now().isoformat()}
            with open(cache_file, "w", encoding="utf-8") as fh:
                json.dump(cache_data, fh, indent=2)

        # Build the tree: ANSTRAT -> Epic -> Issue
        strategies: dict[str, dict] = {}
        epics: dict[str, dict] = {}
        uncategorized: list[dict] = []

        for key, data in issue_keys.items():
            node = {
                "key": key,
                "summary": issue_info.get(key, {}).get("summary", ""),
                "type": issue_info.get(key, {}).get("issue_type", "story").lower(),
                "points": data["points"],
                "event_count": data["event_count"],
                "keywords": extract_keywords(data["titles"]),
                "children": [],
            }
            if key.startswith("ANSTRAT-"):
                strategies[key] = node
                node["type"] = "strategy"
            else:
                epic_key = issue_info.get(key, {}).get("epic", "")
                if epic_key:
                    if epic_key not in epics:
                        epics[epic_key] = {
                            "key": epic_key,
                            "summary": issue_info.get(epic_key, {}).get(
                                "summary", epic_key
                            ),
                            "type": "epic",
                            "points": 0,
                            "event_count": 0,
                            "keywords": [],
                            "children": [],
                        }
                    epics[epic_key]["children"].append(node)
                    epics[epic_key]["points"] += node["points"]
                else:
                    uncategorized.append(node)

        unattached_epics = []
        for epic_key, epic_node in epics.items():
            attached = False
            epic_info = issue_info.get(epic_key, {})
            parent = epic_info.get("parent_initiative", "")
            if not parent:
                parent = epic_info.get("epic", "") or epic_info.get("parent", "")
            if parent and parent.startswith("ANSTRAT-"):
                if parent not in strategies:
                    anstrat_info = issue_info.get(parent, {})
                    strategies[parent] = {
                        "key": parent,
                        "summary": anstrat_info.get("summary", parent),
                        "type": "strategy",
                        "points": 0,
                        "event_count": 0,
                        "keywords": [],
                        "children": [],
                    }
                strategies[parent]["children"].append(epic_node)
                strategies[parent]["points"] += epic_node["points"]
                attached = True
            if not attached:
                unattached_epics.append(epic_node)

        strat_list = sorted(strategies.values(), key=lambda x: -x["points"])
        for s in strat_list:
            s["children"] = sorted(s["children"], key=lambda x: -x["points"])
            for e in s["children"]:
                e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        unattached_epics = sorted(unattached_epics, key=lambda x: -x["points"])
        for e in unattached_epics:
            e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        uncategorized = sorted(uncategorized, key=lambda x: -x["points"])

        return {
            "success": True,
            "strategies": strat_list,
            "unattached_epics": unattached_epics,
            "uncategorized": uncategorized,
            "total_issues": len(issue_keys),
            "cached": not refresh and bool(cached),
        }

    # ==================== Report Export ====================

    async def _handle_export_report(self, **kwargs) -> dict:
        """Generate and export a quarterly performance report."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        fmt = kwargs.get("format", "markdown")

        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = self._get_daily_dir(year, quarter)

        summary = self._load_file(perf_dir / "summary.json") or {}

        all_events: list[dict] = []
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    all_events.extend(data.get("events", []))
                except Exception:
                    continue

        if fmt == "json":
            report = {
                "quarter": f"Q{quarter} {year}",
                "summary": summary,
                "total_events": len(all_events),
                "events": all_events,
            }
            report_file = perf_dir / f"report_q{quarter}_{year}.json"
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

        elif fmt == "pdf":
            return await self._export_pdf_report(
                year,
                quarter,
                now,
                perf_dir,
                summary,
                all_events,
            )

        else:
            lines = [
                f"# Q{quarter} {year} Quarterly Connection Report",
                "",
                f"**Generated:** {now.strftime('%Y-%m-%d %H:%M')}",
                f"**Overall Score:** {summary.get('overall_percentage', 0)}%",
                f"**Total Events:** {len(all_events)}",
                "",
                "## Competency Progress",
                "",
            ]
            for comp, pct in sorted(
                summary.get("cumulative_percentage", {}).items(),
                key=lambda x: -x[1],
            ):
                name = comp.replace("_", " ").title()
                pts = summary.get("cumulative_points", {}).get(comp, 0)
                lines.append(f"- **{name}**: {pct}% ({pts} pts)")

            if summary.get("gaps"):
                lines.append("\n## Areas Needing Attention\n")
                for gap in summary["gaps"]:
                    lines.append(f"- {gap.replace('_', ' ').title()}")

            if summary.get("highlights"):
                lines.append("\n## Highlights\n")
                for h in summary["highlights"]:
                    lines.append(f"- {h}")

            lines.append("")
            report_file = perf_dir / f"report_q{quarter}_{year}.md"
            with open(report_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        return {
            "success": True,
            "path": str(report_file),
            "format": fmt,
            "event_count": len(all_events),
        }

    async def _export_pdf_report(
        self,
        year: int,
        quarter: int,
        now: datetime,
        perf_dir: Path,
        summary: dict,
        all_events: list[dict],
    ) -> dict:
        """Gather all data and render the PDF report."""
        from services.stats.report_helpers import (
            generate_calendar_html,
            generate_competency_bars_html,
            generate_mindmap_svg,
            generate_sunburst_svg,
            render_pdf,
            score_color,
        )

        quarter_label = f"Q{quarter} {year}"
        overall_pct = summary.get("overall_percentage", 0)
        competencies = summary.get("cumulative_percentage", {})

        comp_dict: dict[str, dict] = {}
        for comp_id, pct in competencies.items():
            pts = summary.get("cumulative_points", {}).get(comp_id, 0)
            comp_dict[comp_id] = {"percentage": pct, "points": pts}

        hierarchy = None
        try:
            hier_result = await self._handle_get_issue_hierarchy(
                refresh_from_jira=False
            )
            if hier_result.get("strategies") or hier_result.get("unattached_epics"):
                hierarchy = hier_result
        except Exception as e:
            logger.warning(f"Failed to load hierarchy for PDF: {e}")

        comp_evidence: dict = {}
        gap_suggestions_data: dict = {}
        try:
            ev_result = await self._handle_get_competency_evidence()
            comp_evidence = ev_result.get("competency_evidence", {})
            gap_suggestions_data = ev_result.get("gap_suggestions", {})
        except Exception as e:
            logger.warning(f"Failed to load competency evidence for PDF: {e}")

        captured_days: list[dict] = []
        try:
            cap_result = await self._handle_get_captured_days()
            captured_days = cap_result.get("days", [])
        except Exception as e:
            logger.warning(f"Failed to load captured days for PDF: {e}")

        strategy_data: dict | None = None
        try:
            emails_result = await self._handle_list_executive_emails()
            emails = emails_result.get("emails", [])
            if emails:
                latest = emails[0]
                email_id = latest.get("email_id", "")
                emails_dir = self._get_executive_emails_dir()
                cache_file = emails_dir / f"{email_id}.json"
                parsed_email = None
                if cache_file.exists():
                    with open(cache_file, encoding="utf-8") as fh:
                        parsed_email = json.load(fh)

                map_result = await self._handle_map_deliverables(email_id=email_id)

                strategy_data = {
                    "parsed_email": parsed_email,
                    "mappings": map_result.get("mappings", []),
                    "priority_coverage": map_result.get("priority_coverage", []),
                    "coverage_summary": map_result.get("coverage_summary"),
                }
        except Exception as e:
            logger.warning(f"Failed to load strategy data for PDF: {e}")

        questions_summary = summary.get("questions_summary") or []

        sunburst_svg = (
            generate_sunburst_svg(comp_dict, overall_pct) if comp_dict else ""
        )
        mindmap_svg = (
            generate_mindmap_svg(hierarchy, quarter_label) if hierarchy else ""
        )

        calendar_html = generate_calendar_html(captured_days, year, quarter)
        competency_bars_html = generate_competency_bars_html(comp_dict)

        days_captured = len(captured_days)
        total_issues = hierarchy.get("total_issues", 0) if hierarchy else 0

        template_data = {
            "quarter": quarter_label,
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "overall_pct": overall_pct,
            "score_color": score_color(overall_pct),
            "day_of_quarter": summary.get("day_of_quarter", 0),
            "total_events": len(all_events),
            "days_captured": days_captured,
            "total_issues": total_issues,
            "num_competencies": len(comp_dict),
            "sunburst_svg": sunburst_svg,
            "mindmap_svg": mindmap_svg,
            "calendar_html": calendar_html,
            "competency_bars_html": competency_bars_html,
            "competencies": comp_dict,
            "highlights": summary.get("highlights", []),
            "gaps_list": [g.replace("_", " ").title() for g in summary.get("gaps", [])],
            "hierarchy": hierarchy,
            "competency_evidence": comp_evidence,
            "gap_suggestions": gap_suggestions_data,
            "questions_summary": questions_summary,
            "strategy_data": strategy_data,
            "all_events": all_events,
        }

        template_path = Path(__file__).parent / "report_template.html"
        report_file = perf_dir / f"report_q{quarter}_{year}.pdf"

        loop = asyncio.get_event_loop()
        pdf_path = await loop.run_in_executor(
            None,
            render_pdf,
            template_data,
            template_path,
            report_file,
        )

        return {
            "success": True,
            "path": pdf_path,
            "format": "pdf",
            "event_count": len(all_events),
        }

    # ==================== Executive Strategy Mapping ====================

    async def _handle_parse_executive_email(self, **kwargs) -> dict:
        """Parse an executive email and cache the result."""
        text = kwargs.get("text", "")
        email_id = kwargs.get("email_id", "")

        if not text:
            return {"success": False, "error": "No email text provided"}

        parsed = parse_email_text(text)

        if not email_id:
            import hashlib

            email_id = hashlib.sha256(text[:500].encode()).hexdigest()[:12]

        parsed["email_id"] = email_id
        parsed["parsed_at"] = datetime.now().isoformat()
        parsed["text_preview"] = text[:300].replace("\n", " ")

        emails_dir = self._get_executive_emails_dir()
        emails_dir.mkdir(parents=True, exist_ok=True)
        cache_file = emails_dir / f"{email_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)

        return {"success": True, **parsed}

    async def _handle_map_deliverables(self, **kwargs) -> dict:
        """Map user's delivered issues to executive email targets."""
        email_id = kwargs.get("email_id", "")

        emails_dir = self._get_executive_emails_dir()
        if email_id:
            cache_file = emails_dir / f"{email_id}.json"
            if not cache_file.exists():
                return {"success": False, "error": f"Email {email_id} not found"}
            with open(cache_file, encoding="utf-8") as f:
                parsed = json.load(f)
        else:
            if not emails_dir.exists():
                return {"success": False, "error": "No executive emails cached"}
            files = sorted(
                emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if not files:
                return {"success": False, "error": "No executive emails cached"}
            with open(files[0], encoding="utf-8") as f:
                parsed = json.load(f)
            email_id = parsed.get("email_id", files[0].stem)

        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        hierarchy_result = await self._handle_get_issue_hierarchy(
            refresh_from_jira=False
        )

        user_issues: dict[str, dict] = {}

        def collect_issues(nodes: list, parent_anstrat: str = ""):
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                key = node.get("key", "")
                if key:
                    user_issues[key] = {
                        "key": key,
                        "summary": node.get("summary", ""),
                        "type": node.get("type", ""),
                        "points": node.get("points", 0),
                        "keywords": node.get("keywords", []),
                        "parent_anstrat": parent_anstrat,
                    }
                children = node.get("children", [])
                anstrat = parent_anstrat
                if key.startswith("ANSTRAT-"):
                    anstrat = key
                collect_issues(children, anstrat)

        collect_issues(hierarchy_result.get("strategies", []))
        collect_issues(hierarchy_result.get("unattached_epics", []))
        collect_issues(hierarchy_result.get("uncategorized", []))

        email_issue_keys = set(parsed.get("issue_keys", {}).keys())
        email_priorities = parsed.get("priorities", [])
        email_themes = parsed.get("themes", [])

        mappings: list[dict] = []

        direct_matches = email_issue_keys & set(user_issues.keys())
        for key in sorted(direct_matches):
            ui = user_issues[key]
            contexts = parsed.get("issue_keys", {}).get(key, [])
            mappings.append(
                {
                    "match_type": "direct_key",
                    "confidence": "high",
                    "user_issue": key,
                    "user_summary": ui.get("summary", ""),
                    "user_points": ui.get("points", 0),
                    "email_context": contexts[0] if contexts else "",
                    "priority_name": "",
                }
            )

        email_anstrats = {k for k in email_issue_keys if k.startswith("ANSTRAT-")}
        for issue_key, info in user_issues.items():
            if issue_key in direct_matches:
                continue
            parent = info.get("parent_anstrat", "")
            if parent and parent in email_anstrats:
                contexts = parsed.get("issue_keys", {}).get(parent, [])
                mappings.append(
                    {
                        "match_type": "anstrat_link",
                        "confidence": "high",
                        "user_issue": issue_key,
                        "user_summary": info.get("summary", ""),
                        "user_points": info.get("points", 0),
                        "email_context": contexts[0] if contexts else f"Under {parent}",
                        "priority_name": parent,
                    }
                )

        mapped_keys = {m["user_issue"] for m in mappings}
        for issue_key, info in user_issues.items():
            if issue_key in mapped_keys:
                continue
            user_kws = set(info.get("keywords", []))
            if not user_kws:
                continue
            for theme in email_themes:
                theme_kws = set(theme.get("matched_keywords", []))
                overlap = user_kws & theme_kws
                if overlap:
                    mappings.append(
                        {
                            "match_type": "theme",
                            "confidence": "medium",
                            "user_issue": issue_key,
                            "user_summary": info.get("summary", ""),
                            "user_points": info.get("points", 0),
                            "email_context": f"Theme: {theme['name']} (keywords: {', '.join(overlap)})",
                            "priority_name": theme["name"],
                        }
                    )
                    mapped_keys.add(issue_key)
                    break

        priority_coverage: list[dict] = []
        for prio in email_priorities:
            prio_keys = set(prio.get("issue_keys", []))
            prio_name = prio.get("name", "")
            matching = [
                m
                for m in mappings
                if m.get("priority_name") == prio_name
                or any(k in prio_keys for k in [m["user_issue"]])
                or (
                    m.get("priority_name", "").startswith("ANSTRAT-")
                    and m["priority_name"] in prio_keys
                )
            ]
            direct_prio = prio_keys & set(user_issues.keys())
            status = "covered" if (matching or direct_prio) else "gap"
            priority_coverage.append(
                {
                    "name": prio_name,
                    "context": prio.get("context", "")[:150],
                    "issue_keys": list(prio_keys),
                    "status": status,
                    "matching_issues": [m["user_issue"] for m in matching]
                    + list(direct_prio),
                }
            )

        covered = sum(1 for p in priority_coverage if p["status"] == "covered")
        total_priorities = len(priority_coverage)

        return {
            "success": True,
            "email_id": email_id,
            "mappings": mappings,
            "priority_coverage": priority_coverage,
            "coverage_summary": {
                "total_priorities": total_priorities,
                "covered": covered,
                "gaps": total_priorities - covered,
                "coverage_pct": round(covered / max(total_priorities, 1) * 100),
                "total_user_issues": len(user_issues),
                "mapped_issues": len(mapped_keys),
                "unmapped_issues": len(user_issues) - len(mapped_keys),
            },
            "match_counts": {
                "direct_key": sum(
                    1 for m in mappings if m["match_type"] == "direct_key"
                ),
                "anstrat_link": sum(
                    1 for m in mappings if m["match_type"] == "anstrat_link"
                ),
                "theme": sum(1 for m in mappings if m["match_type"] == "theme"),
            },
        }

    async def _handle_list_executive_emails(self, **kwargs) -> dict:
        """List cached parsed executive emails for the quarter."""
        emails_dir = self._get_executive_emails_dir()
        emails: list[dict] = []

        if emails_dir.exists():
            for f in sorted(
                emails_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            ):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    emails.append(
                        {
                            "email_id": data.get("email_id", f.stem),
                            "sender": data.get("sender", "Unknown"),
                            "parsed_at": data.get("parsed_at", ""),
                            "text_preview": data.get("text_preview", "")[:150],
                            "total_priorities": data.get("total_priorities", 0),
                            "total_issue_keys": data.get("total_issue_keys", 0),
                            "total_themes": data.get("total_themes", 0),
                        }
                    )
                except Exception:
                    continue

        return {"success": True, "emails": emails}

    async def _handle_delete_executive_email(self, **kwargs) -> dict:
        """Delete a cached executive email."""
        email_id = kwargs.get("email_id", "")
        if not email_id:
            return {"success": False, "error": "No email_id provided"}

        emails_dir = self._get_executive_emails_dir()
        cache_file = emails_dir / f"{email_id}.json"
        if cache_file.exists():
            cache_file.unlink()
            return {"success": True, "deleted": email_id}
        return {"success": False, "error": f"Email {email_id} not found"}

    async def _handle_search_executive_gmail(self, **kwargs) -> dict:
        """Search Gmail for executive emails."""
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 10)

        if not query:
            return {"success": False, "error": "No search query provided"}

        try:
            from tool_modules.aa_gmail.src.tools_basic import get_gmail_service
        except ImportError:
            return {"success": False, "error": "Gmail module not available"}

        service, error = get_gmail_service()
        if error:
            return {"success": False, "error": error}

        try:
            loop = asyncio.get_event_loop()

            def _search():
                results = (
                    service.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=max_results)
                    .execute()
                )
                messages = results.get("messages", [])
                email_list = []
                for msg in messages:
                    msg_data = (
                        service.users()
                        .messages()
                        .get(
                            userId="me",
                            id=msg["id"],
                            format="metadata",
                            metadataHeaders=["Subject", "From", "Date"],
                        )
                        .execute()
                    )
                    headers = msg_data.get("payload", {}).get("headers", [])
                    header_map = {h["name"]: h["value"] for h in headers}
                    email_list.append(
                        {
                            "message_id": msg["id"],
                            "subject": header_map.get("Subject", "(no subject)"),
                            "from": header_map.get("From", ""),
                            "date": header_map.get("Date", ""),
                            "snippet": msg_data.get("snippet", "")[:150],
                        }
                    )
                return email_list

            email_list = await loop.run_in_executor(None, _search)
            return {"success": True, "emails": email_list, "count": len(email_list)}
        except Exception as e:
            logger.error(f"Gmail search failed: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_read_gmail_message(self, **kwargs) -> dict:
        """Read a Gmail message by ID and return the plain text body."""
        message_id = kwargs.get("message_id", "")
        if not message_id:
            return {"success": False, "error": "No message_id provided"}

        try:
            from tool_modules.aa_gmail.src.tools_basic import get_gmail_service
        except ImportError:
            return {"success": False, "error": "Gmail module not available"}

        service, error = get_gmail_service()
        if error:
            return {"success": False, "error": error}

        try:
            import base64

            loop = asyncio.get_event_loop()

            def _read():
                msg_data = (
                    service.users()
                    .messages()
                    .get(userId="me", id=message_id, format="full")
                    .execute()
                )
                payload = msg_data.get("payload", {})
                headers = payload.get("headers", [])
                header_map = {h["name"]: h["value"] for h in headers}

                body = ""
                parts = payload.get("parts", [])
                if parts:
                    for part in parts:
                        if part.get("mimeType") == "text/plain":
                            data = part.get("body", {}).get("data", "")
                            if data:
                                body = base64.urlsafe_b64decode(data).decode(
                                    "utf-8", errors="replace"
                                )
                                break
                    if not body:
                        for part in parts:
                            if part.get("mimeType") == "text/html":
                                data = part.get("body", {}).get("data", "")
                                if data:
                                    raw = base64.urlsafe_b64decode(data).decode(
                                        "utf-8", errors="replace"
                                    )
                                    body = re.sub(r"<[^>]+>", " ", raw)
                                    body = re.sub(r"\s+", " ", body).strip()
                                    break
                if not body:
                    data = payload.get("body", {}).get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="replace"
                        )

                return {
                    "message_id": message_id,
                    "subject": header_map.get("Subject", ""),
                    "from": header_map.get("From", ""),
                    "to": header_map.get("To", ""),
                    "date": header_map.get("Date", ""),
                    "body": body[:10000],
                }

            result = await loop.run_in_executor(None, _read)
            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Gmail read failed: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_backfill_executive_emails(self, **kwargs) -> dict:
        """Backfill executive emails for the entire current quarter."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts[quarter]
        q_start = date(year, sm, sd)
        q_end = min(now.date(), date(year, sm + 2, 1) + timedelta(days=30))
        next_q = quarter + 1
        if next_q > 4:
            q_end_actual = date(year + 1, 1, 1)
        else:
            nsm = quarter_starts[next_q][0]
            q_end_actual = date(year, nsm, 1)
        q_end = min(now.date() + timedelta(days=1), q_end_actual)

        senders = get_executive_senders()
        if not senders:
            return {
                "success": False,
                "error": "No executive_senders configured in config.json",
            }

        try:
            from tool_modules.aa_gmail.src.tools_basic import get_gmail_service
        except ImportError:
            return {"success": False, "error": "Gmail module not available"}

        service, error = get_gmail_service()
        if error:
            return {"success": False, "error": f"Gmail auth failed: {error}"}

        import base64

        emails_dir = self._get_executive_emails_dir(year, quarter)
        emails_dir.mkdir(parents=True, exist_ok=True)

        existing_gmail_ids: set[str] = set()
        for p in emails_dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as fh:
                    existing_gmail_ids.add(json.load(fh).get("gmail_message_id", ""))
            except Exception:
                pass

        total_new = 0
        total_skipped = 0
        sender_results: list[dict] = []

        def _do_backfill():
            nonlocal total_new, total_skipped
            for sender in senders:
                query = f"from:{sender} after:{q_start.isoformat()} before:{q_end.isoformat()}"
                new_for_sender = 0
                skipped = 0
                try:
                    page_token = None
                    all_messages: list[dict] = []
                    while True:
                        kwargs_api: dict = {
                            "userId": "me",
                            "q": query,
                            "maxResults": 100,
                        }
                        if page_token:
                            kwargs_api["pageToken"] = page_token
                        results = (
                            service.users().messages().list(**kwargs_api).execute()
                        )
                        all_messages.extend(results.get("messages", []))
                        page_token = results.get("nextPageToken")
                        if not page_token:
                            break

                    for msg in all_messages:
                        mid = msg["id"]
                        if mid in existing_gmail_ids:
                            skipped += 1
                            continue

                        msg_data = (
                            service.users()
                            .messages()
                            .get(userId="me", id=mid, format="full")
                            .execute()
                        )
                        payload = msg_data.get("payload", {})
                        headers = payload.get("headers", [])
                        header_map = {h["name"]: h["value"] for h in headers}

                        def _extract_body(part: dict) -> str:
                            mime = part.get("mimeType", "")
                            data = part.get("body", {}).get("data", "")
                            sub_parts = part.get("parts", [])
                            if mime == "text/plain" and data:
                                return base64.urlsafe_b64decode(data).decode(
                                    "utf-8", errors="replace"
                                )
                            if mime == "text/html" and data:
                                raw_html = base64.urlsafe_b64decode(data).decode(
                                    "utf-8", errors="replace"
                                )
                                text = re.sub(r"<[^>]+>", " ", raw_html)
                                return re.sub(r"\s+", " ", text).strip()
                            if sub_parts:
                                for sp in sub_parts:
                                    txt = _extract_body(sp)
                                    if txt:
                                        return txt
                            return ""

                        body = _extract_body(payload)

                        if not body:
                            logger.warning(
                                f"Skipping email from {sender} (mid={mid[:8]}): no extractable body"
                            )
                            continue

                        parsed = parse_email_text(body[:10000])

                        import hashlib

                        eid = hashlib.sha256(f"{mid}:{sender}".encode()).hexdigest()[
                            :12
                        ]

                        parsed["email_id"] = eid
                        parsed["gmail_message_id"] = mid
                        parsed["sender"] = header_map.get("From", sender)
                        parsed["sender_email"] = sender
                        parsed["subject"] = header_map.get("Subject", "")
                        parsed["email_date"] = header_map.get("Date", "")
                        parsed["collected_date"] = now.date().isoformat()
                        parsed["parsed_at"] = datetime.now().isoformat()
                        parsed["text_preview"] = body[:300].replace("\n", " ")

                        cf = emails_dir / f"{eid}.json"
                        with open(cf, "w", encoding="utf-8") as fh:
                            json.dump(parsed, fh, indent=2)

                        new_for_sender += 1
                        existing_gmail_ids.add(mid)
                        logger.info(
                            f"Backfill: cached email from {sender}: {parsed.get('subject', '')[:60]}"
                        )

                    total_new += new_for_sender
                    total_skipped += skipped
                    sender_results.append(
                        {
                            "sender": sender,
                            "found": len(all_messages),
                            "new": new_for_sender,
                            "skipped": skipped,
                        }
                    )
                except Exception as e:
                    logger.error(f"Backfill failed for {sender}: {e}")
                    sender_results.append(
                        {
                            "sender": sender,
                            "error": str(e),
                        }
                    )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_backfill)

        await loop.run_in_executor(None, self._update_summary, year, quarter)

        return {
            "success": True,
            "quarter": f"Q{quarter} {year}",
            "date_range": f"{q_start.isoformat()} to {q_end.isoformat()}",
            "total_new": total_new,
            "total_skipped": total_skipped,
            "senders": sender_results,
        }

    # ==================== Day Detail & Evidence ====================

    async def _handle_get_day_detail(self, **kwargs) -> dict:
        """Return full event list for a specific date."""
        date_str = kwargs.get("date", "")
        if not date_str:
            return {"success": False, "error": "No date provided"}

        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            return {"success": False, "error": f"Invalid date: {date_str}"}

        year = target.year
        quarter = (target.month - 1) // 3 + 1
        daily_dir = self._get_daily_dir(year, quarter)
        daily_file = daily_dir / f"{date_str}.json"

        if not daily_file.exists():
            return {
                "success": True,
                "date": date_str,
                "events": [],
                "daily_points": {},
                "daily_total": 0,
                "has_data": False,
            }

        try:
            with open(daily_file, encoding="utf-8") as fh:
                data = json.load(fh)

            perf_dir = self._get_perf_dir(year, quarter)
            cache_file = perf_dir / "jira_hierarchy_cache.json"
            issue_info: dict[str, dict] = {}
            if cache_file.exists():
                try:
                    with open(cache_file, encoding="utf-8") as cfh:
                        issue_info = json.load(cfh).get("issues", {})
                except Exception:
                    pass

            events = data.get("events", [])
            for ev in events:
                title = ev.get("title", "")
                found_keys = re.findall(r"((?:AAP|ANSTRAT)-\d+)", title)
                ev["issue_keys"] = found_keys

                lineage_list: list[dict] = []
                for ik in found_keys:
                    info = issue_info.get(ik, {})
                    entry: dict = {
                        "key": ik,
                        "summary": info.get("summary", ""),
                    }
                    epic_key = info.get("epic", "")
                    if epic_key:
                        epic_info = issue_info.get(epic_key, {})
                        entry["epic"] = {
                            "key": epic_key,
                            "summary": epic_info.get("summary", ""),
                        }
                        anstrat_key = epic_info.get("parent_initiative", "")
                        if anstrat_key:
                            anstrat_info = issue_info.get(anstrat_key, {})
                            entry["anstrat"] = {
                                "key": anstrat_key,
                                "summary": anstrat_info.get("summary", ""),
                            }
                    lineage_list.append(entry)
                ev["lineage"] = lineage_list

            cat_map: dict[str, str] = {}
            for cid, defn in COMPETENCY_DEFS.items():
                cat_map[cid] = defn.get("category", "Other")
            cat_points: dict[str, int] = {}
            for cid, pts in data.get("daily_points", {}).items():
                cat = cat_map.get(cid, "Other")
                cat_points[cat] = cat_points.get(cat, 0) + pts

            return {
                "success": True,
                "date": date_str,
                "events": events,
                "daily_points": data.get("daily_points", {}),
                "daily_total": data.get("daily_total", 0),
                "category_points": cat_points,
                "has_data": True,
            }
        except Exception as e:
            logger.error(f"Failed to read day detail for {date_str}: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _classify_match_reason(
        title: str, source: str, event_type: str, comp_id: str
    ) -> str:
        """List all signals that matched for this event/competency pair."""
        defn = COMPETENCY_DEFS.get(comp_id, {})
        text = title.lower()
        reasons: list[str] = []

        if event_type in defn.get("event_types", []):
            reasons.append(f"type:{event_type}")

        for phrase in defn.get("phrases", []):
            if phrase in text:
                reasons.append(f'"{phrase}"')

        for kw in defn.get("keywords", []):
            if kw in text:
                reasons.append(f"kw:{kw}")

        if comp_id == "opportunity_recognition" and source == "github":
            reasons.append("src:github")

        if not reasons:
            return "pattern match"
        return " + ".join(reasons[:5])

    async def _handle_get_competency_evidence(self, **kwargs) -> dict:
        """Return per-competency event breakdown with evidence and metadata."""
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        daily_dir = self._get_daily_dir(year, quarter)

        competency_evidence: dict[str, list[dict]] = {}
        competency_totals: dict[str, int] = {}

        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        points_map = ev.get("points", {})
                        ev_source = ev.get("source", "unknown")
                        ev_type = ev.get("type", "unknown")
                        ev_title = ev.get("title", "")
                        for comp_id, pts in points_map.items():
                            if comp_id not in competency_evidence:
                                competency_evidence[comp_id] = []
                                competency_totals[comp_id] = 0
                            competency_totals[comp_id] += pts
                            if len(competency_evidence[comp_id]) < 20:
                                issue_keys = re.findall(
                                    r"((?:AAP|ANSTRAT)-\d+)", ev_title
                                )
                                reason = self._classify_match_reason(
                                    ev_title, ev_source, ev_type, comp_id
                                )
                                competency_evidence[comp_id].append(
                                    {
                                        "date": data.get("date", f.stem),
                                        "title": ev_title[:120],
                                        "source": ev_source,
                                        "type": ev_type,
                                        "points": pts,
                                        "issue_keys": issue_keys,
                                        "url": ev.get("url", ""),
                                        "match_reason": reason,
                                    }
                                )
                except Exception:
                    continue

        all_competencies = list(COMPETENCY_DEFS.keys())
        target_per_competency = 100

        competency_meta: dict[str, dict] = {}
        for comp_id in all_competencies:
            meta = get_competency_meta(comp_id)
            total = competency_totals.get(comp_id, 0)
            pct = min(round(total / target_per_competency * 100), 100)
            competency_meta[comp_id] = {
                **meta,
                "percentage": pct,
                "points": total,
                "target": target_per_competency,
                "evidence_count": len(competency_evidence.get(comp_id, [])),
            }

        gap_suggestions_data: dict[str, dict] = {}
        for comp_id in all_competencies:
            total = competency_totals.get(comp_id, 0)
            pct = min(round(total / target_per_competency * 100), 100)
            if pct < 50:
                suggestions = get_gap_suggestions(comp_id)
                meta = get_competency_meta(comp_id)
                gap_suggestions_data[comp_id] = {
                    "percentage": pct,
                    "points": total,
                    "target": target_per_competency,
                    "deficit": target_per_competency - total,
                    "suggestions": suggestions,
                    "evidence_count": len(competency_evidence.get(comp_id, [])),
                    "goal": meta["goal"],
                    "description": meta["description"],
                    "category": meta["category"],
                }

        return {
            "success": True,
            "competency_evidence": competency_evidence,
            "competency_totals": competency_totals,
            "competency_meta": competency_meta,
            "gap_suggestions": gap_suggestions_data,
        }

    # ==================== File Loading ====================

    def _load_file(self, filepath: Path) -> dict | None:
        """Load and cache a JSON file."""
        key = str(filepath)
        try:
            if not filepath.exists():
                return None

            mtime = filepath.stat().st_mtime
            if key in self._stats_cache and self._last_modified.get(key, 0) >= mtime:
                return self._stats_cache[key]

            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            self._stats_cache[key] = data
            self._last_modified[key] = mtime
            return data

        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
            return self._stats_cache.get(key)

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Stats daemon starting...")

        AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        self._load_file(AGENT_STATS_FILE)
        self._load_file(INFERENCE_STATS_FILE)
        self._load_file(SKILL_EXECUTION_FILE)
        self._load_file(get_performance_summary_path())

        if self.enable_dbus:
            await self.start_dbus()

        self.is_running = True
        logger.info("Stats daemon ready")

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Stats daemon shutting down...")

        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Stats daemon stopped")

    async def health_check(self) -> dict:
        """Perform a health check on the stats daemon."""
        self._last_health_check = time.time()

        checks = {
            "running": self.is_running,
            "config_dir_exists": AA_CONFIG_DIR.exists(),
            "cache_entries": len(self._stats_cache) > 0,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": (
                "Stats daemon is healthy" if healthy else "Stats daemon has issues"
            ),
            "timestamp": self._last_health_check,
        }


if __name__ == "__main__":
    StatsDaemon.main()
