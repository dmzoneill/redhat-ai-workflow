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
import logging
import time
from datetime import date
from pathlib import Path

from server.paths import (
    AA_CONFIG_DIR,
    AGENT_STATS_FILE,
    INFERENCE_STATS_FILE,
    SKILL_EXECUTION_FILE,
)
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.stats.executive_emails import ExecutiveEmailMixin
from services.stats.handler_utils import (
    DATA_ERRORS,
    now_local,
    quarter_of,
    quarter_start,
    read_json,
    today_local,
    weekdays_between,
    write_json,
)
from services.stats.quarter_data import day_of_quarter
from services.stats.report_export import ReportExporter
from services.stats.scorer import (
    COMPETENCY_DEFS,
    SCORING_CONFIG_FILE,
    get_effective_defs,
    get_merged_config,
    load_scoring_config,
    map_competencies,
    save_scoring_config,
)

logger = logging.getLogger(__name__)

_SCORING_INT_KEYS = ("min_signals", "daily_cap", "target_per_competency")
_COMPETENCY_FIELDS = ("base_points", "phrases", "keywords", "event_types")


def get_performance_summary_path() -> Path:
    """Get current quarter's performance summary file path."""
    now = now_local()
    return AA_CONFIG_DIR / "performance" / str(now.year) / f"q{quarter_of(now)}" / "performance" / "summary.json"


def rescore_daily_file(daily_file: Path, daily_cap: int) -> bool:
    """Re-score one daily file with the current scoring config; False if unreadable."""
    try:
        data = read_json(daily_file)
    except (OSError, ValueError):
        return False

    events = data.get("events", [])
    for ev in events:
        ev["points"] = map_competencies(ev.get("title", ""), ev.get("source", ""), ev.get("type", ""))

    daily_points: dict[str, int] = {}
    for ev in events:
        for comp_id, pts in ev.get("points", {}).items():
            daily_points[comp_id] = min(daily_points.get(comp_id, 0) + pts, daily_cap)

    data["daily_points"] = daily_points
    data["daily_total"] = sum(daily_points.values())
    data["re_evaluated_at"] = now_local().isoformat()
    write_json(daily_file, data)
    return True


def rescore_daily_dir(daily_dir: Path) -> int:
    """Re-score every daily file; return how many were rewritten."""
    _, _, daily_cap, _ = get_effective_defs()
    return sum(1 for daily_file in sorted(daily_dir.glob("*.json")) if rescore_daily_file(daily_file, daily_cap))


def apply_scoring_updates(current: dict, updates: dict) -> None:
    """Merge D-Bus scoring overrides into the saved scoring config in place."""
    for key in _SCORING_INT_KEYS:
        if key in updates:
            current[key] = int(updates[key])

    comp_updates = updates.get("competencies")
    if not comp_updates or not isinstance(comp_updates, dict):
        return
    competencies = current.setdefault("competencies", {})
    for comp_id, comp_update in comp_updates.items():
        if comp_id not in COMPETENCY_DEFS:
            continue
        comp_cfg = competencies.setdefault(comp_id, {})
        for field in _COMPETENCY_FIELDS:
            if field in comp_update:
                val = comp_update[field]
                comp_cfg[field] = int(val) if field == "base_points" else val


class StatsDaemon(ExecutiveEmailMixin, DaemonDBusBase, BaseDaemon):
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
        super().__init__()

        handlers = {
            "get_state": self._handle_get_state,
            "get_agent_stats": self._handle_get_agent_stats,
            "get_inference_stats": self._handle_get_inference_stats,
            "get_skill_execution": self._handle_get_skill_execution,
            # Performance / QC handlers
            "collect_daily": self._handle_collect_daily,
            "backfill": self._handle_backfill,
            "evaluate_all": self._handle_evaluate_all,
            "get_scoring_config": self._handle_get_scoring_config,
            "set_scoring_config": self._handle_set_scoring_config,
            "reset_scoring_config": self._handle_reset_scoring_config,
            "get_captured_days": self._handle_get_captured_days,
            "get_issue_hierarchy": self._handle_get_issue_hierarchy,
            "export_report": self._handle_export_report,
            "get_day_detail": self._handle_get_day_detail,
            "get_competency_evidence": self._handle_get_competency_evidence,
            # Executive strategy mapping handlers
            "parse_executive_email": self._handle_parse_executive_email,
            "map_deliverables": self._handle_map_deliverables,
            "list_executive_emails": self._handle_list_executive_emails,
            "delete_executive_email": self._handle_delete_executive_email,
            "search_executive_gmail": self._handle_search_executive_gmail,
            "read_gmail_message": self._handle_read_gmail_message,
            "backfill_executive_emails": self._handle_backfill_executive_emails,
        }
        for method, handler in handlers.items():
            self.register_handler(method, handler)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return stats-specific statistics."""
        return {
            "files_watched": 4,
            "cache_entries": len(self._stats_cache),
            "last_refresh": now_local().isoformat(),
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
            "cache_age": {k: time.time() - v for k, v in self._last_modified.items()},
        }

    # ==================== D-Bus Handlers ====================

    def _performance_state(self) -> dict | None:
        perf_summary = self.load_file(get_performance_summary_path())
        if not perf_summary:
            return None
        now = now_local()
        quarter = quarter_of(now)
        points = perf_summary.get("cumulative_points", {})
        return {
            "last_updated": perf_summary.get("last_updated", now.isoformat()),
            "quarter": f"Q{quarter} {now.year}",
            "day_of_quarter": day_of_quarter(now.date(), now.year, quarter),
            "overall_percentage": perf_summary.get("overall_percentage", 0),
            "competencies": {
                k: {"points": points.get(k, 0), "percentage": v}
                for k, v in perf_summary.get("cumulative_percentage", {}).items()
            },
            "highlights": perf_summary.get("highlights", []),
            "gaps": perf_summary.get("gaps", []),
            "questions_summary": perf_summary.get("questions_summary"),
            "strategy_alignment": perf_summary.get("strategy_alignment"),
        }

    async def _handle_get_state(self, **_kwargs) -> dict:
        """Get full stats state for UI."""
        return {
            "success": True,
            "state": {
                "agent_stats": self.load_file(AGENT_STATS_FILE),
                "inference_stats": self.load_file(INFERENCE_STATS_FILE),
                "skill_execution": self.load_file(SKILL_EXECUTION_FILE),
                "performance": self._performance_state(),
                "updated_at": now_local().isoformat(),
            },
        }

    async def _handle_get_agent_stats(self, **_kwargs) -> dict:
        """Get agent statistics (tool calls, skill executions, etc.)."""
        stats = self.load_file(AGENT_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Agent stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_inference_stats(self, **_kwargs) -> dict:
        """Get inference statistics (LLM usage, tokens, etc.)."""
        stats = self.load_file(INFERENCE_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Inference stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_skill_execution(self, **_kwargs) -> dict:
        """Get current skill execution state."""
        state = self.load_file(SKILL_EXECUTION_FILE)
        if state is None:
            return {"success": False, "error": "Skill execution file not found"}
        return {"success": True, "execution": state}

    # ==================== Performance / QC ====================

    async def _handle_collect_daily(self, **kwargs) -> dict:
        """Collect daily performance data for a given date."""
        date_str = kwargs.get("date", "")
        try:
            target = date.fromisoformat(date_str) if date_str else today_local()
        except ValueError:
            target = today_local()

        try:
            daily_data = await asyncio.to_thread(self._collector.collect_for_date, target)
            await asyncio.to_thread(self.update_summary)
        except DATA_ERRORS as e:
            logger.error("Failed to collect daily data: %s", e)
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "event_count": len(daily_data.get("events", [])),
            "daily_total": daily_data.get("daily_total", 0),
            "date": target.isoformat(),
        }

    async def _collect_day(self, day: date) -> dict:
        try:
            daily_data = await asyncio.to_thread(self._collector.collect_for_date, day)
        except DATA_ERRORS as e:
            return {"date": day.isoformat(), "success": False, "error": str(e)}
        return {"date": day.isoformat(), "success": True, "events": len(daily_data.get("events", []))}

    async def _handle_backfill(self, **_kwargs) -> dict:
        """Re-collect ALL weekdays in the current quarter."""
        today = today_local()
        all_weekdays = weekdays_between(quarter_start(today.year, quarter_of(today)), today)

        results = [await self._collect_day(d) for d in all_weekdays]
        if all_weekdays:
            await asyncio.to_thread(self.update_summary)

        return {
            "success": True,
            "processed": len(all_weekdays),
            "remaining": 0,
            "results": results,
            "days_processed": len(all_weekdays),
        }

    async def _handle_evaluate_all(self, **kwargs) -> dict:
        """Re-score every event in the quarter using current scoring config."""
        now = now_local()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or quarter_of(now)
        daily_dir = self.daily_dir(year, quarter)

        if not daily_dir.exists():
            return {"success": True, "files_updated": 0}

        files_updated = await asyncio.to_thread(rescore_daily_dir, daily_dir)
        await asyncio.to_thread(self.update_summary, year, quarter)

        return {
            "success": True,
            "files_updated": files_updated,
            "quarter": f"Q{quarter} {year}",
        }

    async def _handle_export_report(self, **kwargs) -> dict:
        """Generate and export a quarterly performance report."""
        return await ReportExporter(self).export(kwargs.get("format", "markdown"))

    async def _handle_get_scoring_config(self, **_kwargs) -> dict:
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
            apply_scoring_updates(current, kwargs)
            save_scoring_config(current)
            result = await self._handle_evaluate_all(**kwargs)
        except DATA_ERRORS as e:
            logger.error("Failed to set scoring config: %s", e)
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "config_saved": True,
            "re_evaluated": result.get("files_updated", 0),
        }

    async def _handle_reset_scoring_config(self, **kwargs) -> dict:
        """Delete user overrides and re-evaluate with defaults."""
        try:
            if SCORING_CONFIG_FILE.exists():
                SCORING_CONFIG_FILE.unlink()
            result = await self._handle_evaluate_all(**kwargs)
        except DATA_ERRORS as e:
            logger.error("Failed to reset scoring config: %s", e)
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "reset": True,
            "re_evaluated": result.get("files_updated", 0),
        }

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Stats daemon starting...")

        AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        self.load_file(AGENT_STATS_FILE)
        self.load_file(INFERENCE_STATS_FILE)
        self.load_file(SKILL_EXECUTION_FILE)
        self.load_file(get_performance_summary_path())

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
            "message": ("Stats daemon is healthy" if healthy else "Stats daemon has issues"),
            "timestamp": self._last_health_check,
        }


if __name__ == "__main__":
    StatsDaemon.main()
