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
    set_executive_senders,
)
from services.stats.scorer import (
    COMPETENCY_DEFS,
    SCORING_CONFIG_FILE,
    get_competency_meta,
    get_effective_defs,
    get_engineering_levels,
    get_gap_suggestions,
    get_level_description,
    get_level_weights,
    get_merged_config,
    get_npu_settings,
    get_scope_multipliers,
    get_strategy_alignment_config,
    load_scoring_config,
    save_scoring_config,
)
from services.stats.strategy import (
    build_strategy_alignment,
    build_strategy_context_index,
)
from tool_modules.aa_performance.src.question_manager import QuestionManager


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
        self.register_handler("add_question", self._handle_add_question)
        self.register_handler("remove_question", self._handle_remove_question)
        self.register_handler("get_question_detail", self._handle_get_question_detail)
        self.register_handler("add_question_note", self._handle_add_question_note)
        self.register_handler("clear_drafts", self._handle_clear_drafts)

        # Peer comparison handlers
        self.register_handler("collect_peers", self._handle_collect_peers)
        self.register_handler("collect_peer", self._handle_collect_peer)
        self.register_handler("get_peer_benchmarks", self._handle_get_peer_benchmarks)

        # AI-powered analysis handlers
        self.register_handler("get_peer_narrative", self._handle_get_peer_narrative)
        self.register_handler(
            "get_peer_differentiators", self._handle_get_peer_differentiators
        )
        self.register_handler("get_overview_digest", self._handle_get_overview_digest)
        self.register_handler("get_gap_coach", self._handle_get_gap_coach)
        self.register_handler(
            "get_promotion_readiness", self._handle_get_promotion_readiness
        )
        self.register_handler(
            "get_calendar_insights", self._handle_get_calendar_insights
        )
        self.register_handler("classify_log_entry", self._handle_classify_log_entry)
        self.register_handler(
            "get_issue_competency_tags", self._handle_get_issue_competency_tags
        )
        self.register_handler(
            "rank_question_evidence", self._handle_rank_question_evidence
        )
        self.register_handler(
            "evaluate_question_local", self._handle_evaluate_question_local
        )
        self.register_handler("ask_ai", self._handle_ask_ai)
        self.register_handler(
            "explain_competency_score", self._handle_explain_competency_score
        )
        self.register_handler("suggest_config_tune", self._handle_suggest_config_tune)
        self.register_handler("get_peer_growth_data", self._handle_get_peer_growth_data)
        self.register_handler(
            "get_activity_patterns", self._handle_get_activity_patterns
        )
        self.register_handler("get_mindmap_clusters", self._handle_get_mindmap_clusters)
        self.register_handler("detect_missing_links", self._handle_detect_missing_links)

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
        self.register_handler(
            "get_executive_senders", self._handle_get_executive_senders
        )
        self.register_handler(
            "set_executive_senders", self._handle_set_executive_senders
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

            questions_summary = self._get_questions_summary()

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
                "questions_summary": questions_summary,
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

    def _get_questions_summary(
        self, year: int | None = None, quarter: int | None = None
    ) -> list[dict] | None:
        """Load questions summary from QuestionManager for the current quarter."""
        try:
            perf_dir = self._get_perf_dir(year, quarter)
            qm = QuestionManager(perf_dir)
            summary = qm.get_questions_summary()
            return summary if summary else None
        except Exception as e:
            logger.debug(f"Failed to load questions summary: {e}")
            return None

    async def _handle_add_question(self, **kwargs) -> dict:
        """Add a new custom question."""
        text = kwargs.get("text", "").strip()
        if not text:
            return {"success": False, "error": "Question text is required"}
        try:
            perf_dir = self._get_perf_dir()
            qm = QuestionManager(perf_dir)
            q_id = text.lower().replace(" ", "_")[:40]
            qm.add_question(question_id=q_id, text=text)
            return {"success": True, "questions_summary": qm.get_questions_summary()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_remove_question(self, **kwargs) -> dict:
        """Remove a question by ID."""
        question_id = kwargs.get("question_id", "").strip()
        if not question_id:
            return {"success": False, "error": "question_id is required"}
        try:
            perf_dir = self._get_perf_dir()
            qm = QuestionManager(perf_dir)
            removed = qm.remove_question(question_id)
            if not removed:
                return {
                    "success": False,
                    "error": f"Question '{question_id}' not found",
                }
            return {"success": True, "questions_summary": qm.get_questions_summary()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_question_detail(self, **kwargs) -> dict:
        """Get full evidence details for a question, sorted by points."""
        question_id = kwargs.get("question_id", "").strip()
        if not question_id:
            return {"success": False, "error": "question_id is required"}
        try:
            perf_dir = self._get_perf_dir()
            daily_dir = self._get_daily_dir()
            qm = QuestionManager(perf_dir)
            question = qm.get_question(question_id)
            if not question:
                return {
                    "success": False,
                    "error": f"Question '{question_id}' not found",
                }

            events = qm.get_evidence_details(question_id, daily_dir)
            sorted_events = sorted(
                events,
                key=lambda e: sum(e.get("points", {}).values()),
                reverse=True,
            )

            evidence = [
                {
                    "id": e.get("id", ""),
                    "title": e.get("title", ""),
                    "source": e.get("source", ""),
                    "date": e.get("date", ""),
                    "points": sum(e.get("points", {}).values()),
                    "competencies": list(e.get("points", {}).keys()),
                }
                for e in sorted_events
            ]

            return {
                "success": True,
                "question_id": question_id,
                "text": question.get("text", ""),
                "evidence": evidence,
                "manual_notes": question.get("manual_notes", []),
                "llm_summary": question.get("llm_summary"),
                "last_evaluated": question.get("last_evaluated"),
                "total_evidence": len(events),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_add_question_note(self, **kwargs) -> dict:
        """Add a manual note to a question."""
        question_id = kwargs.get("question_id", "").strip()
        note = kwargs.get("note", "").strip()
        if not question_id:
            return {"success": False, "error": "question_id is required"}
        if not note:
            return {"success": False, "error": "note is required"}
        try:
            perf_dir = self._get_perf_dir()
            qm = QuestionManager(perf_dir)
            added = qm.add_note(question_id, note)
            if not added:
                return {
                    "success": False,
                    "error": f"Question '{question_id}' not found",
                }
            return {"success": True, "questions_summary": qm.get_questions_summary()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_clear_drafts(self, **kwargs) -> dict:
        """Clear all AI-generated draft summaries from questions."""
        try:
            perf_dir = self._get_perf_dir()
            qm = QuestionManager(perf_dir)
            cleared = qm.clear_all_drafts()
            return {
                "success": True,
                "cleared": cleared,
                "questions_summary": qm.get_questions_summary(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

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

    def _tag_events_to_questions(
        self, perf_dir: Path, daily_data: dict | None = None
    ) -> int:
        """Initialize questions if needed and tag events to them.

        If daily_data is provided, tags only those events.
        If None, scans all daily files to rebuild question evidence.
        """
        qm = QuestionManager(perf_dir)
        tagged_total = 0

        if daily_data:
            for event in daily_data.get("events", []):
                tagged = qm.tag_event_to_questions(event)
                tagged_total += len(tagged)
        else:
            daily_dir = perf_dir / "daily"
            if daily_dir.exists():
                for daily_file in sorted(daily_dir.glob("*.json")):
                    try:
                        with open(daily_file, encoding="utf-8") as f:
                            data = json.load(f)
                        for event in data.get("events", []):
                            tagged = qm.tag_event_to_questions(event)
                            tagged_total += len(tagged)
                    except Exception as exc:
                        logger.debug("Suppressed error tagging events: %s", exc)

        return tagged_total

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
        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = {
            k: min(round(v / effective_target * 100), 100)
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

        questions_summary = self._get_questions_summary(year, quarter)

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
            "questions_summary": questions_summary,
            "effective_target": effective_target,
            "engineering_level": level,
            "last_updated": now.isoformat(),
        }

        perf_dir.mkdir(parents=True, exist_ok=True)
        summary_file = perf_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        self._stats_cache.pop(str(summary_file), None)
        self._last_modified.pop(str(summary_file), None)

        return summary

    def _update_summary_from_data(
        self,
        cumulative_points: dict[str, int],
        total_events: int,
        highlights: list[str],
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Build and write quarter summary from pre-computed scoring data.

        Avoids re-reading daily files when the caller already has the
        aggregated data (e.g. after _rescore).
        """
        _, _, _, target_per_competency = get_effective_defs()
        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = {
            k: min(round(v / effective_target * 100), 100)
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
        questions_summary = self._get_questions_summary(year, quarter)

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
            "questions_summary": questions_summary,
            "effective_target": effective_target,
            "engineering_level": level,
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
            year = target.year
            quarter = (target.month - 1) // 3 + 1
            perf_dir = self._get_perf_dir(year, quarter)
            emails_dir = self._get_executive_emails_dir(year, quarter)

            self._collector.strategy_index = build_strategy_context_index(emails_dir)

            cache_file = perf_dir / "jira_hierarchy_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        self._collector.hierarchy_cache = json.load(f)
                except Exception:
                    self._collector.hierarchy_cache = {}

            loop = asyncio.get_event_loop()
            daily_data = await loop.run_in_executor(
                None,
                self._collector.collect_for_date,
                target,
            )
            await loop.run_in_executor(None, self._update_summary)

            # Tag collected events to quarterly questions
            await loop.run_in_executor(
                None, self._tag_events_to_questions, perf_dir, daily_data
            )

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

            # Rebuild all question evidence from scratch after backfill
            perf_dir = self._get_perf_dir(year, quarter)
            await loop.run_in_executor(
                None, self._tag_events_to_questions, perf_dir, None
            )

        return {
            "success": True,
            "processed": len(all_weekdays),
            "remaining": 0,
            "results": results,
            "days_processed": len(all_weekdays),
        }

    # ==================== Peer Comparison ====================

    def _load_peers_config(self) -> dict[str, list[dict]]:
        """Load the peers roster from config.json."""
        config_paths = [
            Path(__file__).parent.parent.parent / "config.json",
            AA_CONFIG_DIR / "config.json",
        ]
        for cfg_path in config_paths:
            try:
                if cfg_path.exists():
                    with open(cfg_path, encoding="utf-8") as f:
                        config = json.load(f)
                    peers = config.get("peers", {})
                    if peers:
                        return peers
            except Exception:
                continue
        return {}

    def _update_peer_summary(
        self,
        username: str,
        level: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Build summary.json for a single peer from their daily files."""
        perf_dir = self._get_perf_dir(year, quarter)
        peer_daily_dir = perf_dir / "peers" / username / "daily"
        if not peer_daily_dir.exists():
            return {}

        cumulative_points: dict[str, int] = {}
        total_events = 0
        event_counts: dict[str, int] = {}

        for daily_file in sorted(peer_daily_dir.glob("*.json")):
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                day_events = data.get("events", [])
                total_events += len(day_events)
                for ev in day_events:
                    src = ev.get("source", "unknown")
                    event_counts[src] = event_counts.get(src, 0) + 1
            except Exception:
                continue

        _, _, _, target_per_competency = get_effective_defs()
        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = {
            k: min(round(v / effective_target * 100), 100)
            for k, v in cumulative_points.items()
        }
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))

        now = datetime.now()
        y = year or now.year
        q = quarter or ((now.month - 1) // 3 + 1)

        days_captured = len(list(peer_daily_dir.glob("*.json")))
        avg_daily_events = round(total_events / max(days_captured, 1), 1)

        summary = {
            "username": username,
            "level": level,
            "year": y,
            "quarter": q,
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": overall,
            "total_events": total_events,
            "days_captured": days_captured,
            "avg_daily_events": avg_daily_events,
            "event_counts_by_source": event_counts,
            "effective_target": effective_target,
            "last_updated": now.isoformat(),
        }

        peer_dir = perf_dir / "peers" / username
        peer_dir.mkdir(parents=True, exist_ok=True)
        with open(peer_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary

    def _update_peer_benchmarks(
        self,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Aggregate all peer summaries into benchmarks.json grouped by level."""
        perf_dir = self._get_perf_dir(year, quarter)
        peers_dir = perf_dir / "peers"
        if not peers_dir.exists():
            return {}

        peers_config = self._load_peers_config()
        levels: dict[str, dict] = {}

        for level_key, peer_list in peers_config.items():
            level_data: dict[str, Any] = {
                "engineers": [],
                "summaries": [],
                "avg_competency_pct": {},
                "avg_competency_points": {},
                "avg_overall_pct": 0,
                "avg_daily_events": 0.0,
                "avg_event_counts_by_source": {},
            }

            for peer in peer_list:
                uname = peer["username"]
                summary_file = peers_dir / uname / "summary.json"
                if summary_file.exists():
                    try:
                        with open(summary_file, encoding="utf-8") as f:
                            s = json.load(f)
                        level_data["engineers"].append(uname)
                        level_data["summaries"].append(s)
                    except Exception:
                        continue

            n = len(level_data["summaries"])
            if n > 0:
                all_comp_ids: set[str] = set()
                for s in level_data["summaries"]:
                    all_comp_ids.update(s.get("cumulative_percentage", {}).keys())

                for comp_id in all_comp_ids:
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

                level_data["avg_overall_pct"] = round(
                    sum(s.get("overall_percentage", 0) for s in level_data["summaries"])
                    / n
                )
                level_data["avg_daily_events"] = round(
                    sum(s.get("avg_daily_events", 0) for s in level_data["summaries"])
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

            del level_data["summaries"]
            levels[level_key] = level_data

        benchmarks = {
            "levels": levels,
            "last_updated": datetime.now().isoformat(),
        }

        peers_dir.mkdir(parents=True, exist_ok=True)
        with open(peers_dir / "benchmarks.json", "w", encoding="utf-8") as f:
            json.dump(benchmarks, f, indent=2)

        return benchmarks

    async def _handle_collect_peer(self, **kwargs) -> dict:
        """Collect data for a single peer engineer."""
        username = kwargs.get("username", "")
        date_str = kwargs.get("date", "")
        if not username:
            return {"success": False, "error": "username is required"}

        peers_config = self._load_peers_config()
        peer_info = None
        peer_level = ""
        for level_key, peer_list in peers_config.items():
            for peer in peer_list:
                if peer["username"] == username:
                    peer_info = peer
                    peer_level = level_key
                    break
            if peer_info:
                break

        if not peer_info:
            return {"success": False, "error": f"Peer '{username}' not found in config"}

        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        try:
            loop = asyncio.get_event_loop()
            daily_data = await loop.run_in_executor(
                None,
                lambda: self._collector.collect_for_date(
                    target, user_override=peer_info, level_override=peer_level
                ),
            )

            year = target.year
            quarter = (target.month - 1) // 3 + 1
            await loop.run_in_executor(
                None, self._update_peer_summary, username, peer_level, year, quarter
            )

            return {
                "success": True,
                "username": username,
                "level": peer_level,
                "date": target.isoformat(),
                "event_count": len(daily_data.get("events", [])),
                "daily_total": daily_data.get("daily_total", 0),
            }
        except Exception as e:
            logger.error(f"Failed to collect peer data for {username}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_collect_peers(self, **kwargs) -> dict:
        """Collect data for all configured peers for the current quarter."""
        date_str = kwargs.get("date", "")
        backfill = kwargs.get("backfill", False)

        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        peers_config = self._load_peers_config()
        if not peers_config:
            return {"success": False, "error": "No peers configured in config.json"}

        results: list[dict] = []
        loop = asyncio.get_event_loop()

        year = target.year
        quarter = (target.month - 1) // 3 + 1

        if backfill:
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
            dates_to_collect = all_weekdays
        else:
            dates_to_collect = [target]

        for level_key, peer_list in peers_config.items():
            for peer in peer_list:
                username = peer["username"]
                peer_results: list[dict] = []
                for d in dates_to_collect:
                    try:
                        daily_data = await loop.run_in_executor(
                            None,
                            lambda _d=d, _p=peer, _l=level_key: self._collector.collect_for_date(
                                _d, user_override=_p, level_override=_l
                            ),
                        )
                        peer_results.append(
                            {
                                "date": d.isoformat(),
                                "success": True,
                                "events": len(daily_data.get("events", [])),
                            }
                        )
                    except Exception as e:
                        peer_results.append(
                            {
                                "date": d.isoformat(),
                                "success": False,
                                "error": str(e),
                            }
                        )

                await loop.run_in_executor(
                    None, self._update_peer_summary, username, level_key, year, quarter
                )
                results.append(
                    {
                        "username": username,
                        "level": level_key,
                        "days_processed": len(peer_results),
                        "days_succeeded": sum(1 for r in peer_results if r["success"]),
                    }
                )

        await loop.run_in_executor(None, self._update_peer_benchmarks, year, quarter)

        total_peers = sum(len(pl) for pl in peers_config.values())
        return {
            "success": True,
            "peers_processed": total_peers,
            "backfill": backfill,
            "results": results,
        }

    async def _handle_get_peer_benchmarks(self, **kwargs) -> dict:
        """Return aggregated peer benchmarks for the UI."""
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        perf_dir = self._get_perf_dir(year, quarter)
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"

        if benchmarks_file.exists():
            try:
                with open(benchmarks_file, encoding="utf-8") as f:
                    benchmarks = json.load(f)
                return {"success": True, "benchmarks": benchmarks}
            except Exception as e:
                return {"success": False, "error": f"Failed to read benchmarks: {e}"}

        return {
            "success": True,
            "benchmarks": {"levels": {}, "last_updated": None},
        }

    # ==================== AI-Powered Analysis Handlers ====================

    def _get_user_competency_pct(self) -> dict[str, int]:
        """Load user's current competency percentages from summary."""
        summary = self._load_file(get_performance_summary_path())
        if summary:
            return summary.get("cumulative_percentage", {})
        return {}

    def _get_user_event_counts(self) -> dict[str, int]:
        """Count events by source from current quarter's daily files."""
        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        counts: dict[str, int] = {}
        if daily_dir.exists():
            for f in daily_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        src = ev.get("source", "unknown")
                        counts[src] = counts.get(src, 0) + 1
                except Exception:
                    continue
        return counts

    def _load_benchmarks_levels(self) -> dict:
        """Load peer benchmark levels data."""
        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        bf = perf_dir / "peers" / "benchmarks.json"
        if bf.exists():
            try:
                with open(bf, encoding="utf-8") as f:
                    return json.load(f).get("levels", {})
            except Exception:
                pass
        return {}

    async def _handle_get_peer_narrative(self, **kwargs) -> dict:
        """Generate AI narrative comparing user to peer benchmarks."""
        from services.stats.ai_handlers import generate_peer_narrative

        user_pct = self._get_user_competency_pct()
        summary = self._load_file(get_performance_summary_path()) or {}
        user_overall = summary.get("overall_percentage", 0)
        peer_levels = self._load_benchmarks_levels()
        user_events = self._get_user_event_counts()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: generate_peer_narrative(
                user_pct,
                user_overall,
                peer_levels,
                user_events,
                engineering_level=kwargs.get("engineering_level", ""),
            ),
        )

    async def _handle_get_peer_differentiators(self, **kwargs) -> dict:
        """Compute competency differentiators across peer levels."""
        from services.stats.ai_handlers import compute_peer_differentiators

        user_pct = self._get_user_competency_pct()
        peer_levels = self._load_benchmarks_levels()
        target_level = kwargs.get("target_level", "")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: compute_peer_differentiators(user_pct, peer_levels, target_level),
        )

    async def _handle_get_overview_digest(self, **kwargs) -> dict:
        """Generate AI weekly digest for overview tab."""
        from services.stats.ai_handlers import generate_overview_digest

        summary = self._load_file(get_performance_summary_path()) or {}
        peer_levels = self._load_benchmarks_levels()

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        daily_trend = []
        if daily_dir.exists():
            cumulative: dict[str, int] = {}
            day_num = 0
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    day_num += 1
                    for comp_id, pts in data.get("daily_points", {}).items():
                        cumulative[comp_id] = cumulative.get(comp_id, 0) + pts
                    total_pct = sum(cumulative.values())
                    daily_trend.append({"day": day_num, "cumulative_pct": total_pct})
                except Exception:
                    continue

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: generate_overview_digest(summary, daily_trend, peer_levels),
        )

    async def _handle_get_gap_coach(self, **kwargs) -> dict:
        """Generate AI coaching for a specific competency gap."""
        from services.stats.ai_handlers import generate_gap_coach

        comp_id = kwargs.get("competency_id", "")
        if not comp_id:
            return {"success": False, "error": "competency_id is required"}

        comp_name = comp_id.replace("_", " ").title()
        user_pct = self._get_user_competency_pct().get(comp_id, 0)
        peer_levels = self._load_benchmarks_levels()
        target_level = kwargs.get("target_level", "")

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        user_events = []
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        if comp_id in ev.get("points", {}):
                            user_events.append(ev)
                except Exception:
                    continue

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: generate_gap_coach(
                comp_id, comp_name, user_pct, user_events, peer_levels, target_level
            ),
        )

    async def _handle_get_promotion_readiness(self, **kwargs) -> dict:
        """Assess promotion readiness to next level."""
        from services.stats.ai_handlers import generate_promotion_readiness

        user_pct = self._get_user_competency_pct()
        summary = self._load_file(get_performance_summary_path()) or {}
        user_overall = summary.get("overall_percentage", 0)
        peer_levels = self._load_benchmarks_levels()
        current_level = kwargs.get("current_level", "")
        if not current_level:
            cfg = get_merged_config()
            current_level = cfg.get("engineering_level", "sse")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: generate_promotion_readiness(
                user_pct, user_overall, peer_levels, current_level
            ),
        )

    async def _handle_get_calendar_insights(self, **kwargs) -> dict:
        """Get calendar pattern analysis and coverage forecast."""
        from services.stats.ai_handlers import generate_calendar_insights

        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = perf_dir / "daily"

        captured = []
        if daily_dir.exists():
            captured = sorted(f.stem for f in daily_dir.glob("*.json"))

        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        sm, sd = quarter_starts.get(quarter, (1, 1))
        q_start = date(year, sm, sd)
        today = date.today()
        total_weekdays = 0
        current = q_start
        while current <= today:
            if current.weekday() < 5:
                total_weekdays += 1
            current += timedelta(days=1)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: generate_calendar_insights(
                captured, total_weekdays, f"Q{quarter} {year}"
            ),
        )

    async def _handle_classify_log_entry(self, **kwargs) -> dict:
        """Classify a manual log entry into a category."""
        from services.stats.ai_handlers import classify_log_category

        description = kwargs.get("description", "")
        categories = kwargs.get("categories")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: classify_log_category(description, categories),
        )

    async def _handle_get_issue_competency_tags(self, **kwargs) -> dict:
        """Tag an issue with top competency matches."""
        from services.stats.ai_handlers import classify_issue_competencies

        text = kwargs.get("text", "")
        if not text:
            return {"success": False, "error": "text is required"}

        npu = self._collector.npu_classifier
        loop = asyncio.get_event_loop()
        tags = await loop.run_in_executor(
            None,
            lambda: classify_issue_competencies(
                text, npu, top_n=kwargs.get("top_n", 3)
            ),
        )
        return {"success": True, "tags": tags}

    async def _handle_rank_question_evidence(self, **kwargs) -> dict:
        """Rank evidence events by relevance to a question."""
        from services.stats.ai_handlers import rank_evidence_for_question

        question_id = kwargs.get("question_id", "")
        if not question_id:
            return {"success": False, "error": "question_id is required"}

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        qm = QuestionManager(perf_dir)
        detail = qm.get_question_detail(question_id)
        if not detail:
            return {"success": False, "error": f"Question {question_id} not found"}

        question_text = detail.get("text", "") + " " + detail.get("subtext", "")
        daily_dir = perf_dir / "daily"
        evidence = qm.get_evidence_details(question_id, daily_dir)

        npu = self._collector.npu_classifier
        loop = asyncio.get_event_loop()
        ranked = await loop.run_in_executor(
            None,
            lambda: rank_evidence_for_question(question_text, evidence, npu),
        )
        return {"success": True, "ranked_evidence": ranked}

    async def _handle_evaluate_question_local(self, **kwargs) -> dict:
        """Evaluate a question using local LLM (Ollama NVIDIA)."""
        question_id = kwargs.get("question_id", "")
        if not question_id:
            return {"success": False, "error": "question_id is required"}

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        qm = QuestionManager(perf_dir)
        detail = qm.get_question_detail(question_id)
        if not detail:
            return {"success": False, "error": f"Question {question_id} not found"}

        daily_dir = perf_dir / "daily"
        evidence = qm.get_evidence_details(question_id, daily_dir)
        summary = self._load_file(get_performance_summary_path()) or {}
        comp_data = {}
        for comp_id, pct in summary.get("cumulative_percentage", {}).items():
            comp_data[comp_id] = {"percentage": pct}

        try:
            from tool_modules.aa_ollama.src.client import get_available_client

            client = get_available_client(
                primary="nvidia", fallback_chain=["igpu", "cpu"]
            )
            if not client:
                return {
                    "success": False,
                    "error": "No Ollama instance available for evaluation.",
                }

            class _OllamaLLMAdapter:
                """Adapter to match the llm_client.complete() interface."""

                def __init__(self, ollama_client):
                    self._client = ollama_client

                async def complete(self, prompt: str) -> str:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None,
                        lambda: self._client.generate(
                            prompt=prompt,
                            max_tokens=800,
                            temperature=0.3,
                        ),
                    )

            adapter = _OllamaLLMAdapter(client)
            from tool_modules.aa_performance.src.question_manager import (
                evaluate_question_with_llm,
            )

            result_text = await evaluate_question_with_llm(
                question=detail,
                evidence_events=evidence,
                competency_summary=comp_data,
                llm_client=adapter,
            )

            if result_text:
                qm.set_evaluation(question_id, result_text)
                return {
                    "success": True,
                    "summary": result_text,
                    "model": client.default_model,
                    "instance": client.name,
                    "questions_summary": qm.get_questions_summary(),
                }
            return {"success": False, "error": "LLM returned empty response"}

        except ImportError:
            return {"success": False, "error": "Ollama client not available"}
        except Exception as e:
            logger.error(f"Local question evaluation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_ask_ai(self, **kwargs) -> dict:
        """Answer a question about the scoring system."""
        from services.stats.ai_handlers import ask_ai_tutor

        question = kwargs.get("question", "")
        if not question:
            return {"success": False, "error": "question is required"}

        scoring_config = None
        try:
            scoring_config = get_merged_config()
        except Exception:
            pass

        summary = self._load_file(get_performance_summary_path())

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: ask_ai_tutor(question, scoring_config, summary),
        )

    async def _handle_explain_competency_score(self, **kwargs) -> dict:
        """Explain how a competency score was calculated."""
        from services.stats.ai_handlers import explain_competency_score

        comp_id = kwargs.get("competency_id", "")
        if not comp_id:
            return {"success": False, "error": "competency_id is required"}

        comp_name = comp_id.replace("_", " ").title()

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        events = []
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        if comp_id in ev.get("points", {}):
                            events.append(ev)
                except Exception:
                    continue

        scoring_config = None
        try:
            scoring_config = get_merged_config()
        except Exception:
            pass

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: explain_competency_score(
                comp_id, comp_name, events, scoring_config
            ),
        )

    async def _handle_suggest_config_tune(self, **kwargs) -> dict:
        """Suggest scoring config adjustments."""
        from services.stats.ai_handlers import suggest_config_tune

        user_events = self._get_user_event_counts()
        user_pct = self._get_user_competency_pct()
        peer_levels = self._load_benchmarks_levels()
        target_level = kwargs.get("target_level", "")

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: suggest_config_tune(
                user_events, user_pct, peer_levels, target_level
            ),
        )

    async def _handle_get_peer_growth_data(self, **kwargs) -> dict:
        """Get time-series growth data for user and peers."""
        from services.stats.ai_handlers import compute_peer_growth_data

        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        perf_dir = self._get_perf_dir(year, quarter)
        user_daily = perf_dir / "daily"
        peers_dir = perf_dir / "peers"
        peers_config = self._load_peers_config()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: compute_peer_growth_data(user_daily, peers_dir, peers_config),
        )

    async def _handle_get_activity_patterns(self, **kwargs) -> dict:
        """Analyze activity patterns across peer levels."""
        from services.stats.ai_handlers import analyze_activity_patterns

        peer_levels = self._load_benchmarks_levels()
        user_events = self._get_user_event_counts()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: analyze_activity_patterns(peer_levels, user_events),
        )

    async def _handle_get_mindmap_clusters(self, **kwargs) -> dict:
        """Generate AI-based clusters for the mindmap view."""
        npu = self._collector.npu_classifier
        if not npu or not npu.enabled or not npu.model:
            return {"success": False, "error": "NPU classifier not available"}

        now = datetime.now()
        perf_dir = self._get_perf_dir(now.year, (now.month - 1) // 3 + 1)
        daily_dir = perf_dir / "daily"
        events = []
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        text = ev.get("classification_text", "") or ev.get("title", "")
                        if text:
                            events.append(
                                {
                                    "id": ev.get("id", ""),
                                    "title": ev.get("title", ""),
                                    "text": text,
                                    "source": ev.get("source", ""),
                                }
                            )
                except Exception:
                    continue

        if len(events) < 5:
            return {
                "success": True,
                "clusters": [],
                "message": "Not enough events to cluster",
            }

        try:
            from sklearn.cluster import KMeans

            texts = [e["text"] for e in events]
            embeddings = npu.model.encode(texts, normalize_embeddings=True)

            n_clusters = min(max(3, len(events) // 5), 8)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)

            clusters: dict[int, list] = {}
            for i, label in enumerate(labels):
                clusters.setdefault(int(label), []).append(events[i])

            result_clusters = []
            for cluster_id, members in sorted(clusters.items()):
                titles = [m["title"][:60] for m in members[:5]]
                result_clusters.append(
                    {
                        "cluster_id": cluster_id,
                        "size": len(members),
                        "sample_titles": titles,
                        "members": [m["id"] for m in members],
                    }
                )

            return {
                "success": True,
                "clusters": result_clusters,
                "n_clusters": n_clusters,
            }

        except ImportError as e:
            return {"success": False, "error": f"sklearn not available: {e}"}
        except Exception as e:
            logger.error(f"Clustering failed: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_detect_missing_links(self, **kwargs) -> dict:
        """Detect orphan issues that should be linked to an ANSTRAT."""
        from services.stats.ai_handlers import detect_missing_links

        npu = self._collector.npu_classifier
        if not npu or not npu.enabled:
            return {
                "success": False,
                "error": "NPU classifier not available for missing link detection",
            }

        hierarchy_result = await self._handle_get_issue_hierarchy()
        if not hierarchy_result.get("success"):
            return {"success": False, "error": "No issue hierarchy available"}

        anstrats = hierarchy_result.get("anstrats", [])

        linked_keys = set()
        for a in anstrats:
            linked_keys.add(a.get("key", ""))
            for epic in a.get("children", []):
                linked_keys.add(epic.get("key", ""))
                for issue in epic.get("children", []):
                    linked_keys.add(issue.get("key", ""))

        all_keys = hierarchy_result.get("all_issue_keys", [])
        orphans = []
        for k_info in all_keys:
            key = k_info if isinstance(k_info, str) else k_info.get("key", "")
            if key not in linked_keys:
                summary = (
                    k_info.get("summary", key) if isinstance(k_info, dict) else key
                )
                orphans.append({"key": key, "summary": summary})

        if not orphans:
            return {
                "success": True,
                "suggestions": [],
                "message": "No orphan issues found",
            }

        loop = asyncio.get_event_loop()
        suggestions = await loop.run_in_executor(
            None,
            lambda: detect_missing_links(anstrats, orphans, npu),
        )
        return {"success": True, "suggestions": suggestions}

    # ------------------------------------------------------------------
    # Fast re-threshold helpers (avoid full re-enrich when only
    # min_signals / daily_cap changed)
    # ------------------------------------------------------------------

    _FAST_RETHRESHOLD_FIELDS = {"min_signals", "daily_cap"}

    @staticmethod
    def _detect_config_changes(old_cfg: dict, new_cfg: dict) -> set[str]:
        """Return the set of top-level config keys whose values differ."""
        changed: set[str] = set()
        all_keys = set(old_cfg) | set(new_cfg)
        for key in all_keys:
            if old_cfg.get(key) != new_cfg.get(key):
                changed.add(key)
        return changed

    async def _fast_rethreshold(
        self,
        min_sig: int,
        daily_cap: int,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Re-threshold points using cached signal_counts -- no re-enrichment.

        Much faster than _handle_evaluate_all because it skips scope/role
        detection, text matching, NPU classification, and strategy alignment.
        Only usable when the scoring weights have not changed (i.e. only
        min_signals and/or daily_cap differ from the previous config).
        """
        now = datetime.now()
        year = year or now.year
        quarter = quarter or ((now.month - 1) // 3 + 1)
        daily_dir = self._get_daily_dir(year, quarter)

        if not daily_dir.exists():
            return {"success": True, "files_updated": 0}

        loop = asyncio.get_event_loop()

        def _rethreshold() -> tuple[int, dict[str, int], int, list[str]]:
            eff_defs, _, _, _ = get_effective_defs()
            cfg = get_merged_config()
            level = cfg.get("engineering_level", "sse")

            scope_multipliers = cfg.get("scope_multipliers", {})
            lw = get_level_weights(level)
            user_cfg = load_scoring_config()
            user_lw = user_cfg.get("level_weight_overrides", {}).get(level, {})
            if user_lw.get("role_weights"):
                merged_rw = dict(lw.get("role_weights", {}))
                for s, roles in user_lw["role_weights"].items():
                    if isinstance(roles, dict):
                        merged_rw[s] = {**merged_rw.get(s, {}), **roles}
                role_weights_table = merged_rw
            else:
                role_weights_table = lw.get("role_weights", {})
            if user_lw.get("pillar_weights"):
                pillar_weights = {
                    **lw.get("pillar_weights", {}),
                    **user_lw["pillar_weights"],
                }
            else:
                pillar_weights = lw.get("pillar_weights", {})

            strategy_cfg = cfg.get("strategy_alignment", {})

            updated = 0
            cumulative_points: dict[str, int] = {}
            total_events = 0
            highlights: list[str] = []

            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                events = data.get("events", [])
                file_changed = False

                for ev in events:
                    sig_counts = ev.get("signal_counts")
                    if not sig_counts:
                        continue

                    scope = ev.get("scope", "story")
                    role = ev.get("role", "assignee")
                    strategy_aligned = ev.get("strategy_aligned", False)

                    scope_mult = scope_multipliers.get(scope, 1)
                    strategy_bonus = 1.0
                    if strategy_aligned and strategy_cfg.get("enabled", True):
                        strategy_bonus = strategy_cfg.get("bonus_multiplier", 1.5)

                    new_points: dict[str, int] = {}
                    for comp_id, sig_count in sig_counts.items():
                        if sig_count >= min_sig:
                            defn = eff_defs.get(comp_id)
                            if not defn:
                                continue
                            base = defn["base_points"]
                            scope_role_weights = role_weights_table.get(scope, {})
                            role_weight = scope_role_weights.get(role, 1.0)
                            category = defn.get("category", "")
                            pillar_weight = pillar_weights.get(category, 1.0)
                            final = round(
                                base
                                * scope_mult
                                * role_weight
                                * pillar_weight
                                * strategy_bonus
                            )
                            new_points[comp_id] = max(final, 1)

                    if new_points != ev.get("points", {}):
                        ev["points"] = new_points
                        file_changed = True

                daily_points: dict[str, int] = {}
                for ev in events:
                    for comp_id, pts in ev.get("points", {}).items():
                        current = daily_points.get(comp_id, 0)
                        daily_points[comp_id] = min(current + pts, daily_cap)

                old_points = data.get("daily_points", {})
                if daily_points != old_points or file_changed:
                    data["daily_points"] = daily_points
                    data["daily_total"] = sum(daily_points.values())
                    data["re_evaluated_at"] = datetime.now().isoformat()
                    with open(daily_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    updated += 1

                for comp_id, pts in daily_points.items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                total_events += len(events)
                for ev in events[:3]:
                    if ev.get("title") and len(highlights) < 10:
                        highlights.append(ev["title"][:80])

            return updated, cumulative_points, total_events, highlights

        result = await loop.run_in_executor(None, _rethreshold)
        files_updated, cumulative_points, total_events, highlights = result
        await loop.run_in_executor(
            None,
            self._update_summary_from_data,
            cumulative_points,
            total_events,
            highlights,
            year,
            quarter,
        )

        return {
            "success": True,
            "files_updated": files_updated,
            "quarter": f"Q{quarter} {year}",
            "fast_path": True,
        }

    async def _handle_evaluate_all(self, **kwargs) -> dict:
        """Re-score every event in the quarter using current scoring config.

        Builds the strategy context index from cached executive emails,
        loads the hierarchy cache, and re-enriches + re-scores all events
        with scope/role/strategy/level-aware weights.
        """
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        daily_dir = self._get_daily_dir(year, quarter)

        if not daily_dir.exists():
            return {"success": True, "files_updated": 0}

        loop = asyncio.get_event_loop()

        perf_dir = self._get_perf_dir(year, quarter)
        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_index = build_strategy_context_index(emails_dir)

        cache_file = perf_dir / "jira_hierarchy_cache.json"
        hierarchy_cache: dict = {}
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    hierarchy_cache = json.load(f)
            except Exception:
                pass

        self._collector.hierarchy_cache = hierarchy_cache
        self._collector.strategy_index = strategy_index

        def _rescore() -> tuple[int, dict[str, int], int, list[str]]:
            eff_defs, min_sig, daily_cap, _ = get_effective_defs()
            cfg = get_merged_config()
            _level = cfg.get("engineering_level", "sse")  # noqa: F841
            strategy_cfg = get_strategy_alignment_config()
            _min_overlap = strategy_cfg.get("min_text_overlap_words", 3)  # noqa: F841
            updated = 0
            cumulative_points: dict[str, int] = {}
            total_events = 0
            highlights: list[str] = []

            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                events = data.get("events", [])
                for ev in events:
                    self._collector._enrich_event(ev, eff_defs, min_sig)

                daily_points: dict[str, int] = {}
                for ev in events:
                    for comp_id, pts in ev.get("points", {}).items():
                        current = daily_points.get(comp_id, 0)
                        daily_points[comp_id] = min(current + pts, daily_cap)

                old_points = data.get("daily_points", {})
                if daily_points != old_points:
                    data["daily_points"] = daily_points
                    data["daily_total"] = sum(daily_points.values())
                    data["re_evaluated_at"] = datetime.now().isoformat()
                    with open(daily_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    updated += 1

                for comp_id, pts in daily_points.items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                total_events += len(events)
                for ev in events[:3]:
                    if ev.get("title") and len(highlights) < 10:
                        highlights.append(ev["title"][:80])

            return updated, cumulative_points, total_events, highlights

        result = await loop.run_in_executor(None, _rescore)
        files_updated, cumulative_points, total_events, highlights = result
        await loop.run_in_executor(
            None,
            self._update_summary_from_data,
            cumulative_points,
            total_events,
            highlights,
            year,
            quarter,
        )

        # Rebuild question evidence after rescoring (points may have changed)
        perf_dir = self._get_perf_dir(year, quarter)
        await loop.run_in_executor(None, self._tag_events_to_questions, perf_dir, None)

        return {
            "success": True,
            "files_updated": files_updated,
            "quarter": f"Q{quarter} {year}",
        }

    async def _handle_get_scoring_config(self, **kwargs) -> dict:
        """Return the full merged scoring config (defaults + user overrides)."""
        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
        for comp_id, comp_cfg in cfg.get("competencies", {}).items():
            defn = COMPETENCY_DEFS.get(comp_id, {})
            comp_cfg["name"] = defn.get("name", comp_id)
            comp_cfg["category"] = defn.get("category", "Other")
            level_data = get_level_description(comp_id, level)
            if level_data.get("title"):
                comp_cfg["level_title"] = level_data["title"]
            if level_data.get("description"):
                comp_cfg["level_description"] = level_data["description"]
        cfg["engineering_levels"] = get_engineering_levels()

        yaml_level_weights = get_level_weights(level)
        user_cfg = load_scoring_config()
        user_lw = user_cfg.get("level_weight_overrides", {}).get(level, {})
        if user_lw:
            merged_lw = dict(yaml_level_weights)
            for key in ("role_weights", "pillar_weights"):
                if key in user_lw and isinstance(user_lw[key], dict):
                    base = dict(yaml_level_weights.get(key, {}))
                    if key == "role_weights":
                        for scope, roles in user_lw[key].items():
                            if isinstance(roles, dict):
                                base[scope] = {**base.get(scope, {}), **roles}
                    else:
                        base.update(user_lw[key])
                    merged_lw[key] = base
            cfg["level_weights"] = merged_lw
        else:
            cfg["level_weights"] = yaml_level_weights

        cfg["scope_multipliers"] = get_scope_multipliers()
        cfg["strategy_alignment"] = get_strategy_alignment_config()
        cfg["npu_settings"] = get_npu_settings()
        return {"success": True, "config": cfg}

    async def _handle_set_scoring_config(self, **kwargs) -> dict:
        """Update scoring config with partial overrides, save, and re-evaluate.

        Uses a fast re-threshold path when only min_signals and/or daily_cap
        changed, avoiding expensive full re-enrichment of every event.
        """
        try:
            import copy

            old_config = load_scoring_config()
            old_snapshot = copy.deepcopy(old_config)

            current = old_config

            for key in ("min_signals", "daily_cap", "target_per_competency"):
                if key in kwargs:
                    current[key] = int(kwargs[key])

            if "engineering_level" in kwargs:
                current["engineering_level"] = str(kwargs["engineering_level"])

            if "scope_multipliers" in kwargs and isinstance(
                kwargs["scope_multipliers"], dict
            ):
                current["scope_multipliers"] = kwargs["scope_multipliers"]

            if "strategy_alignment" in kwargs and isinstance(
                kwargs["strategy_alignment"], dict
            ):
                if "strategy_alignment" not in current:
                    current["strategy_alignment"] = {}
                current["strategy_alignment"].update(kwargs["strategy_alignment"])

            if "npu_settings" in kwargs and isinstance(kwargs["npu_settings"], dict):
                if "npu_settings" not in current:
                    current["npu_settings"] = {}
                current["npu_settings"].update(kwargs["npu_settings"])

            lw_overrides = kwargs.get("level_weight_overrides")
            if lw_overrides and isinstance(lw_overrides, dict):
                level = current.get(
                    "engineering_level", kwargs.get("engineering_level", "sse")
                )
                if "level_weight_overrides" not in current:
                    current["level_weight_overrides"] = {}
                if level not in current["level_weight_overrides"]:
                    current["level_weight_overrides"][level] = {}
                for key in ("role_weights", "pillar_weights"):
                    if key in lw_overrides and isinstance(lw_overrides[key], dict):
                        current["level_weight_overrides"][level][key] = lw_overrides[
                            key
                        ]

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

            changed = self._detect_config_changes(old_snapshot, current)
            if changed and changed <= self._FAST_RETHRESHOLD_FIELDS:
                result = await self._fast_rethreshold(
                    min_sig=current.get("min_signals", 2),
                    daily_cap=current.get("daily_cap", 25),
                )
            else:
                result = await self._handle_evaluate_all(**kwargs)

            return {
                "success": True,
                "config_saved": True,
                "re_evaluated": result.get("files_updated", 0),
                "fast_path": result.get("fast_path", False),
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

    async def _handle_get_issue_hierarchy(self, **kwargs) -> dict:  # noqa: C901
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
                    desc_lines: list[str] = []
                    in_description = False
                    for line in result.split("\n"):
                        m = re.match(
                            r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$",
                            line.strip(),
                            re.IGNORECASE,
                        )
                        if m:
                            in_description = False
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
                            if field == "reporter":
                                info["reporter"] = val
                            if field in ("assignee", "assigned_to"):
                                info["assignee"] = val
                            if field == "description":
                                in_description = True
                                if val:
                                    desc_lines.append(val)
                        elif in_description:
                            desc_lines.append(line.strip())
                    if desc_lines:
                        info["description"] = " ".join(desc_lines)[:500]
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

        # Load peer benchmarks for comparison section
        peer_benchmarks_data: dict | None = None
        peer_radar_svg = ""
        peer_bars_html = ""
        peer_volume_html = ""
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"
        if benchmarks_file.exists():
            try:
                with open(benchmarks_file, encoding="utf-8") as bf:
                    peer_benchmarks_data = json.load(bf)
                from services.stats.report_helpers import (
                    generate_grouped_bars_html,
                    generate_radar_svg,
                    generate_volume_table_html,
                )

                user_profile = {
                    k: v.get("percentage", 0) if isinstance(v, dict) else 0
                    for k, v in comp_dict.items()
                }
                peer_profiles = {
                    lk: ld.get("avg_competency_pct", {})
                    for lk, ld in peer_benchmarks_data.get("levels", {}).items()
                }
                peer_radar_svg = generate_radar_svg(user_profile, peer_profiles)
                peer_bars_html = generate_grouped_bars_html(
                    comp_dict, peer_benchmarks_data.get("levels", {})
                )
                user_volume: dict[str, int] = {}
                for ev in all_events:
                    src = ev.get("source", "unknown")
                    user_volume[src] = user_volume.get(src, 0) + 1
                peer_volumes = {
                    lk: ld.get("avg_event_counts_by_source", {})
                    for lk, ld in peer_benchmarks_data.get("levels", {}).items()
                }
                peer_volume_html = generate_volume_table_html(user_volume, peer_volumes)
            except Exception as e:
                logger.debug(f"Failed to load peer benchmarks for report: {e}")

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
            "peer_benchmarks": peer_benchmarks_data,
            "peer_radar_svg": peer_radar_svg,
            "peer_bars_html": peer_bars_html,
            "peer_volume_html": peer_volume_html,
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

    async def _handle_get_executive_senders(self, **kwargs) -> dict:
        """Return the configured executive email senders."""
        return {"success": True, "senders": get_executive_senders()}

    async def _handle_set_executive_senders(self, **kwargs) -> dict:
        """Update the executive email senders list in config.json."""
        senders = kwargs.get("senders")
        if senders is None:
            return {"success": False, "error": "No senders provided"}
        if not isinstance(senders, list):
            return {"success": False, "error": "senders must be a list"}
        cleaned = [
            s.strip().lower() for s in senders if isinstance(s, str) and s.strip()
        ]
        if set_executive_senders(cleaned):
            return {"success": True, "senders": cleaned}
        return {"success": False, "error": "Failed to write config.json"}

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

    def _run_clean_migration(self) -> None:
        """Clean break migration: delete old config, write new defaults.

        Runs once on first startup after the scoring redesign.
        """
        if not SCORING_CONFIG_FILE.exists():
            return

        try:
            with open(SCORING_CONFIG_FILE, encoding="utf-8") as f:
                old_cfg = json.load(f)
        except Exception:
            return

        if "scope_multipliers" in old_cfg:
            return

        logger.info("Scoring redesign migration: upgrading scoring_config.json")
        try:
            SCORING_CONFIG_FILE.unlink()
            logger.info("Deleted old scoring_config.json")
        except Exception as e:
            logger.warning(f"Failed to delete old config: {e}")

        new_config: dict = {}
        for k in ("engineering_level",):
            if k in old_cfg:
                new_config[k] = old_cfg[k]
        save_scoring_config(new_config)
        logger.info("Created new scoring_config.json with redesigned schema")

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Stats daemon starting...")

        AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        self._run_clean_migration()

        self._load_file(AGENT_STATS_FILE)
        self._load_file(INFERENCE_STATS_FILE)
        self._load_file(SKILL_EXECUTION_FILE)
        self._load_file(get_performance_summary_path())

        npu_settings = get_npu_settings()
        if npu_settings.get("enabled", False):
            try:
                from services.stats.npu_classifier import NPUCompetencyClassifier

                classifier = NPUCompetencyClassifier(
                    device=npu_settings.get("device", "CPU"),
                    confidence_threshold=npu_settings.get("confidence_threshold", 0.35),
                    bonus_signals=npu_settings.get("bonus_signals", 2),
                )
                cfg = get_merged_config()
                level = cfg.get("engineering_level", "sse")
                success = await classifier.initialize(COMPETENCY_DEFS, level)
                if success:
                    self._collector.npu_classifier = classifier
                    logger.info("NPU classifier initialized successfully")
                else:
                    logger.info("NPU classifier failed to initialize, disabled")
            except Exception as e:
                logger.info(f"NPU classifier unavailable: {e}")

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
