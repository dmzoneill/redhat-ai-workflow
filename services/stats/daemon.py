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
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape as html_unescape
from pathlib import Path
from typing import Any

from server.paths import (
    AA_CONFIG_DIR,
    AGENT_STATS_FILE,
    INFERENCE_STATS_FILE,
    SKILL_EXECUTION_FILE,
)
from server.utils import run_cmd_sync
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.stats.anstrat_sync import (
    load_anstrat_ownership,
    load_sender_gdrive_docs,
    load_sender_jira_activity,
    sync_anstrat_ownership,
    sync_sender_gdrive_docs,
    sync_sender_jira_activity,
)
from services.stats.collector import DataCollector
from services.stats.email_parser import (
    get_executive_emails_dir,
    get_executive_senders,
    is_calendar_event,
    parse_email_text,
    set_executive_senders,
)
from services.stats.peer_backfill import (
    build_filter_label,
    compute_peer_benchmarks,
    get_weekdays_in_quarter_range,
)
from services.stats.performance_scoring import (
    compute_competency_percentages,
    compute_daily_points,
    dedup_events_by_jira_key,
    is_personal_repo_event,
    is_primary_only_event,
    normalize_strategy_bonus,
    process_daily_events_for_summary,
)
from services.stats.quarter_utils import QUARTER_STARTS
from services.stats.scorer import (
    COMPETENCY_DEFS,
    DEFAULT_GLOBALS,
    SCORING_CONFIG_FILE,
    get_competency_meta,
    get_effective_defs,
    get_engineering_levels,
    get_gap_suggestions,
    get_level_description,
    get_level_weights,
    get_merged_config,
    get_npu_settings,
    get_peer_comparable_config,
    get_scope_multipliers,
    get_source_daily_caps,
    get_strategy_alignment_config,
    load_scoring_config,
    save_scoring_config,
)
from services.stats.strategy import (
    build_strategy_alignment,
    build_strategy_context_index,
)
from tool_modules.aa_performance.src.question_manager import QuestionManager

MAX_PEER_BACKFILL_ERRORS = 50
TARGET_POINTS_PER_COMPETENCY = 100


@dataclass
class SummaryUpdateContext:
    cumulative_points: dict[str, int]
    total_events: int
    highlights: list[str]
    pc_points: dict[str, int]
    pc_events: int
    counts_by_source: dict[str, int]
    comparable_counts_by_source: dict[str, int]
    ne_points: dict[str, int]
    year: int | None = None
    quarter: int | None = None
    skip_strategy: bool = False


GAP_PERCENTAGE_THRESHOLD = 50
SECONDS_PER_HOUR = 3600
MAX_HIERARCHY_KEYS_PER_BATCH = 30
JIRA_QUERY_TIMEOUT = 30
MAX_DESCRIPTION_LENGTH = 500
MAX_SUMMARY_LENGTH = 100
MAX_TEXT_PREVIEW_LENGTH = 300
GMAIL_MAX_RESULTS = 100


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
        self._peer_backfill_task: asyncio.Task | None = None
        self._peer_backfill_cancelled = False
        self._peer_backfill_progress: dict[str, Any] = {
            "running": False,
            "phase": "",
            "phase_detail": "",
            "total_peers": 0,
            "completed_peers": 0,
            "current_peer": "",
            "current_level": "",
            "total_days": 0,
            "completed_days": 0,
            "errors": [],
            "started_at": "",
            "elapsed_seconds": 0,
            "total_events": 0,
            "cancelled": False,
            "phases_completed": [],
        }
        self._last_collection_time: float = 0.0
        self._last_collection_errors: dict[str, str] = {}
        self._last_collection_date: str = ""
        self._consecutive_collection_failures: int = 0

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
        self.register_handler(
            "get_peer_backfill_progress",
            self._handle_get_peer_backfill_progress,
        )
        self.register_handler("cancel_backfill", self._handle_cancel_backfill)
        self.register_handler("scrub_data", self._handle_scrub_data)
        self.register_handler(
            "resolve_github_usernames", self._handle_resolve_github_usernames
        )
        self.register_handler("rescore_peers", self._handle_rescore_peers)
        self.register_handler("get_org_stats", self._handle_get_org_stats)

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
        self.register_handler(
            "sync_anstrat_ownership", self._handle_sync_anstrat_ownership
        )
        self.register_handler(
            "get_anstrat_ownership", self._handle_get_anstrat_ownership
        )
        self.register_handler(
            "infer_strategy_relationships",
            self._handle_infer_strategy_relationships,
        )
        self.register_handler(
            "sync_sender_sources",
            self._handle_sync_sender_sources,
        )
        self.register_handler(
            "get_sender_sources",
            self._handle_get_sender_sources,
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

            pc_pct = perf_summary.get("peer_comparable_percentage", {})
            pc_pts = perf_summary.get("peer_comparable_points", {})
            ne_pct = perf_summary.get("no_enrichment_percentage", {})
            ne_pts = perf_summary.get("no_enrichment_points", {})

            performance_data = {
                "last_updated": perf_summary.get("last_updated", now.isoformat()),
                "quarter": f"Q{quarter} {now.year}",
                "day_of_quarter": day_of_quarter,
                "overall_percentage": perf_summary.get("overall_percentage", 0),
                "no_enrichment_overall": perf_summary.get("no_enrichment_overall", 0),
                "peer_comparable_overall": perf_summary.get(
                    "peer_comparable_overall", 0
                ),
                "competencies": {
                    k: {
                        "points": perf_summary.get("cumulative_points", {}).get(k, 0),
                        "percentage": v,
                        "no_enrichment_points": ne_pts.get(k, 0),
                        "no_enrichment_percentage": ne_pct.get(k, 0),
                        "peer_comparable_points": pc_pts.get(k, 0),
                        "peer_comparable_percentage": pc_pct.get(k, 0),
                    }
                    for k, v in perf_summary.get("cumulative_percentage", {}).items()
                },
                "highlights": perf_summary.get("highlights", []),
                "gaps": perf_summary.get("gaps", []),
                "questions_summary": questions_summary,
                "strategy_alignment": perf_summary.get("strategy_alignment"),
                "event_counts_by_source": perf_summary.get(
                    "event_counts_by_source", {}
                ),
                "comparable_event_counts_by_source": perf_summary.get(
                    "comparable_event_counts_by_source", {}
                ),
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
            logger.debug("Failed to load questions summary: %s", e)
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
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.debug("Suppressed error tagging events: %s", exc)

        return tagged_total

    def _accumulate_daily_points(
        self,
        daily_dir: Path,
        daily_cap: int,
        source_caps: dict,
        pc_cfg: dict,
        strategy_bonus: float,
    ) -> tuple[
        dict[str, int],
        dict[str, int],
        dict[str, int],
        int,
        int,
        dict[str, int],
        dict[str, int],
        list[str],
    ]:
        cumulative_points: dict[str, int] = {}
        no_enrichment_points: dict[str, int] = {}
        peer_comparable_points: dict[str, int] = {}
        total_events = 0
        peer_comparable_events = 0
        event_counts_by_source: dict[str, int] = {}
        comparable_event_counts_by_source: dict[str, int] = {}
        highlights: list[str] = []

        for daily_file in sorted(daily_dir.glob("*.json")):
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                events = data.get("events", [])

                (
                    ne_daily,
                    pc_daily,
                    pc_events,
                    counts_by_source,
                    comparable_counts_by_source,
                ) = process_daily_events_for_summary(
                    events,
                    daily_cap,
                    source_caps,
                    pc_cfg,
                    strategy_bonus_multiplier=strategy_bonus,
                )
                for comp_id, pts in ne_daily.items():
                    no_enrichment_points[comp_id] = (
                        no_enrichment_points.get(comp_id, 0) + pts
                    )
                for comp_id, pts in pc_daily.items():
                    peer_comparable_points[comp_id] = (
                        peer_comparable_points.get(comp_id, 0) + pts
                    )
                peer_comparable_events += pc_events
                total_events += sum(counts_by_source.values())
                for src, count in counts_by_source.items():
                    event_counts_by_source[src] = (
                        event_counts_by_source.get(src, 0) + count
                    )
                for src, count in comparable_counts_by_source.items():
                    comparable_event_counts_by_source[src] = (
                        comparable_event_counts_by_source.get(src, 0) + count
                    )

                highlights_max = get_merged_config().get(
                    "highlights_max_count",
                    DEFAULT_GLOBALS["highlights_max_count"],
                )
                for ev in events[:3]:
                    if ev.get("title") and len(highlights) < highlights_max:
                        highlights.append(ev["title"][:80])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Failed to read daily file %s during summary update: %s",
                    daily_file,
                    e,
                )
                continue

        return (
            cumulative_points,
            no_enrichment_points,
            peer_comparable_points,
            total_events,
            peer_comparable_events,
            event_counts_by_source,
            comparable_event_counts_by_source,
            highlights,
        )

    def _update_summary(
        self, year: int | None = None, quarter: int | None = None
    ) -> dict:
        """Recalculate and update the quarter summary from all daily files."""
        daily_dir = self._get_daily_dir(year, quarter)
        if not daily_dir.exists():
            return {}

        _, _, daily_cap, target_per_competency = get_effective_defs()
        pc_cfg = get_peer_comparable_config()
        source_caps = get_source_daily_caps()
        strategy_bonus = get_strategy_alignment_config().get("bonus_multiplier", 1.5)

        (
            cumulative_points,
            no_enrichment_points,
            peer_comparable_points,
            total_events,
            peer_comparable_events,
            event_counts_by_source,
            comparable_event_counts_by_source,
            highlights,
        ) = self._accumulate_daily_points(
            daily_dir, daily_cap, source_caps, pc_cfg, strategy_bonus
        )

        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = compute_competency_percentages(
            cumulative_points, effective_target
        )
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))

        ne_pct = compute_competency_percentages(no_enrichment_points, effective_target)
        ne_overall = round(sum(ne_pct.values()) / max(len(ne_pct), 1))

        pc_pct = compute_competency_percentages(
            peer_comparable_points, effective_target
        )
        pc_overall = round(sum(pc_pct.values()) / max(len(pc_pct), 1))

        gaps_threshold = get_merged_config().get(
            "gaps_threshold_pct", DEFAULT_GLOBALS["gaps_threshold_pct"]
        )
        gaps = [k for k, v in cumulative_pct.items() if v < gaps_threshold]

        now = datetime.now()
        y = year or now.year
        q = quarter or ((now.month - 1) // 3 + 1)
        quarter_starts = QUARTER_STARTS
        sm, sd = quarter_starts[q]
        day_of_quarter = (now.date() - date(y, sm, sd)).days + 1

        perf_dir = self._get_perf_dir(year, quarter)
        emails_dir = self._get_executive_emails_dir(year, quarter)

        ownership = load_anstrat_ownership(perf_dir)
        jira_activity = load_sender_jira_activity(perf_dir)
        gdrive_docs = load_sender_gdrive_docs(perf_dir)

        strategy_alignment = build_strategy_alignment(
            y,
            q,
            cumulative_points,
            perf_dir,
            emails_dir,
            ownership=ownership,
            jira_activity=jira_activity,
            gdrive_docs=gdrive_docs,
        )

        questions_summary = self._get_questions_summary(year, quarter)

        summary = {
            "year": y,
            "quarter": q,
            "day_of_quarter": day_of_quarter,
            "cumulative_points": cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": overall,
            "no_enrichment_points": no_enrichment_points,
            "no_enrichment_percentage": ne_pct,
            "no_enrichment_overall": ne_overall,
            "peer_comparable_points": peer_comparable_points,
            "peer_comparable_percentage": pc_pct,
            "peer_comparable_overall": pc_overall,
            "peer_comparable_events": peer_comparable_events,
            "total_events": total_events,
            "event_counts_by_source": event_counts_by_source,
            "comparable_event_counts_by_source": comparable_event_counts_by_source,
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

    def _update_summary_from_data(self, ctx: SummaryUpdateContext) -> dict:
        """Build and write quarter summary from pre-computed scoring data.

        Avoids re-reading daily files when the caller already has the
        aggregated data (e.g. after _rescore). Callers must pass
        pc_points, pc_events, counts_by_source, comparable_counts_by_source,
        and ne_points from the same file scan that produced cumulative_points.

        When skip_strategy=True, reuses the existing strategy_alignment and
        questions_summary from the current summary.json instead of rebuilding
        them.  This is safe when only min_signals/daily_cap changed (strategy
        alignment depends on emails/issues, not scoring thresholds).
        """
        _, _, _, target_per_competency = get_effective_defs()
        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = compute_competency_percentages(
            ctx.cumulative_points, effective_target
        )
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))
        gaps_threshold = get_merged_config().get(
            "gaps_threshold_pct", DEFAULT_GLOBALS["gaps_threshold_pct"]
        )
        gaps = [k for k, v in cumulative_pct.items() if v < gaps_threshold]

        comp_counts_by_source = ctx.comparable_counts_by_source
        pc_pct = compute_competency_percentages(ctx.pc_points, effective_target)
        pc_overall = round(sum(pc_pct.values()) / max(len(pc_pct), 1))

        ne_pct = compute_competency_percentages(ctx.ne_points, effective_target)
        ne_overall = round(sum(ne_pct.values()) / max(len(ne_pct), 1))

        now = datetime.now()
        y = ctx.year or now.year
        q = ctx.quarter or ((now.month - 1) // 3 + 1)
        quarter_starts = QUARTER_STARTS
        sm, sd = quarter_starts[q]
        day_of_quarter = (now.date() - date(y, sm, sd)).days + 1

        perf_dir = self._get_perf_dir(ctx.year, ctx.quarter)

        if ctx.skip_strategy:
            summary_file = perf_dir / "summary.json"
            strategy_alignment = {}
            questions_summary = {}
            if summary_file.exists():
                try:
                    with open(summary_file, encoding="utf-8") as f:
                        prev = json.load(f)
                    strategy_alignment = prev.get("strategy_alignment", {})
                    questions_summary = prev.get("questions_summary", {})
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read existing summary.json: %s", e)
                    pass
        else:
            emails_dir = self._get_executive_emails_dir(ctx.year, ctx.quarter)
            ownership = load_anstrat_ownership(perf_dir)
            jira_activity = load_sender_jira_activity(perf_dir)
            gdrive_docs = load_sender_gdrive_docs(perf_dir)

            strategy_alignment = build_strategy_alignment(
                y,
                q,
                ctx.cumulative_points,
                perf_dir,
                emails_dir,
                ownership=ownership,
                jira_activity=jira_activity,
                gdrive_docs=gdrive_docs,
            )
            questions_summary = self._get_questions_summary(ctx.year, ctx.quarter)

        summary = {
            "year": y,
            "quarter": q,
            "day_of_quarter": day_of_quarter,
            "cumulative_points": ctx.cumulative_points,
            "cumulative_percentage": cumulative_pct,
            "overall_percentage": overall,
            "no_enrichment_points": ctx.ne_points,
            "no_enrichment_percentage": ne_pct,
            "no_enrichment_overall": ne_overall,
            "peer_comparable_points": ctx.pc_points,
            "peer_comparable_percentage": pc_pct,
            "peer_comparable_overall": pc_overall,
            "peer_comparable_events": ctx.pc_events,
            "total_events": ctx.total_events,
            "event_counts_by_source": ctx.counts_by_source,
            "comparable_event_counts_by_source": comp_counts_by_source,
            "highlights": ctx.highlights,
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(
                        "Failed to load hierarchy cache %s: %s", cache_file, e
                    )
                    self._collector.hierarchy_cache = {}

            loop = asyncio.get_event_loop()
            daily_data = await loop.run_in_executor(
                None,
                self._collector.collect_for_date,
                target,
            )
            await loop.run_in_executor(None, self._update_summary)

            await loop.run_in_executor(
                None, self._tag_events_to_questions, perf_dir, daily_data
            )

            source_errors = daily_data.get("source_errors", {})
            self._last_collection_time = time.time()
            self._last_collection_date = target.isoformat()
            self._last_collection_errors = source_errors

            if source_errors:
                self._consecutive_collection_failures += 1
                failed_sources = ", ".join(source_errors.keys())
                logger.error(
                    "Collection for %s completed with %d source failure(s): %s",
                    target.isoformat(),
                    len(source_errors),
                    failed_sources,
                )
                self.emit_event(
                    "collection_failure",
                    json.dumps(
                        {
                            "date": target.isoformat(),
                            "failed_sources": list(source_errors.keys()),
                            "errors": source_errors,
                            "event_count": len(daily_data.get("events", [])),
                            "consecutive_failures": self._consecutive_collection_failures,
                        }
                    ),
                )
            else:
                self._consecutive_collection_failures = 0

            return {
                "success": True,
                "event_count": len(daily_data.get("events", [])),
                "daily_total": daily_data.get("daily_total", 0),
                "date": target.isoformat(),
                "source_errors": source_errors,
                "sources_attempted": daily_data.get("sources_attempted", []),
                "sources_succeeded": daily_data.get("sources_succeeded", []),
            }
        except Exception as e:
            self._consecutive_collection_failures += 1
            self._last_collection_time = time.time()
            self._last_collection_date = target.isoformat()
            self._last_collection_errors = {"_fatal": str(e)}
            logger.error(
                "Failed to collect daily data for %s: %s", target.isoformat(), e
            )
            self.emit_event(
                "collection_failure",
                json.dumps(
                    {
                        "date": target.isoformat(),
                        "fatal_error": str(e),
                        "consecutive_failures": self._consecutive_collection_failures,
                    }
                ),
            )
            return {"success": False, "error": str(e)}

    async def _handle_backfill(self, **kwargs) -> dict:
        """Re-collect ALL weekdays in the current quarter."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        quarter_starts = QUARTER_STARTS
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
        failed_days = []
        all_source_errors: dict[str, list[str]] = {}
        loop = asyncio.get_event_loop()

        for d in all_weekdays:
            try:
                daily_data = await loop.run_in_executor(
                    None,
                    self._collector.collect_for_date,
                    d,
                )
                day_errors = daily_data.get("source_errors", {})
                results.append(
                    {
                        "date": d.isoformat(),
                        "success": True,
                        "events": len(daily_data.get("events", [])),
                        "source_errors": day_errors,
                    }
                )
                for src, err in day_errors.items():
                    all_source_errors.setdefault(src, []).append(
                        f"{d.isoformat()}: {err}"
                    )
            except Exception as e:
                failed_days.append(d.isoformat())
                results.append(
                    {
                        "date": d.isoformat(),
                        "success": False,
                        "error": str(e),
                    }
                )
                logger.error("Backfill failed for %s: %s", d.isoformat(), e)

        if all_weekdays:
            await loop.run_in_executor(None, self._update_summary)

            perf_dir = self._get_perf_dir(year, quarter)
            await loop.run_in_executor(
                None, self._tag_events_to_questions, perf_dir, None
            )

        if failed_days or all_source_errors:
            logger.error(
                "Backfill completed with issues: %d day(s) failed completely, "
                "%d source(s) had errors",
                len(failed_days),
                len(all_source_errors),
            )
            self.emit_event(
                "backfill_errors",
                json.dumps(
                    {
                        "failed_days": failed_days,
                        "source_errors": {
                            src: len(errs) for src, errs in all_source_errors.items()
                        },
                        "total_days": len(all_weekdays),
                    }
                ),
            )

        return {
            "success": len(failed_days) == 0,
            "processed": len(all_weekdays),
            "remaining": 0,
            "results": results,
            "days_processed": len(all_weekdays),
            "failed_days": failed_days,
            "source_error_summary": {
                src: len(errs) for src, errs in all_source_errors.items()
            },
        }

    # ==================== Peer Comparison ====================

    def _load_peers_config(self) -> dict[str, list[dict]]:
        """Load peers roster from org_roster.json (preferred) or config.json."""
        org_roster = AA_CONFIG_DIR / "performance" / "org" / "org_roster.json"
        try:
            if org_roster.exists():
                with open(org_roster, encoding="utf-8") as f:
                    roster = json.load(f)
                peers = roster.get("peers", {})
                if peers:
                    logger.info(
                        "Loaded %d peer levels from org_roster.json",
                        len(peers),
                    )
                    return peers
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load org_roster.json: %s", e)

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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read config file: %s", e)
                continue
        return {}

    async def _handle_get_org_stats(self, **kwargs) -> dict:
        """Return org roster statistics for the Peers overview charts."""
        org_roster = AA_CONFIG_DIR / "performance" / "org" / "org_roster.json"
        try:
            if not org_roster.exists():
                return {"success": True, "data": {"available": False}}
            with open(org_roster, encoding="utf-8") as f:
                roster = json.load(f)
            stats = roster.get("stats", {})
            by_level = stats.get("by_level", {})
            peers = roster.get("peers", {})
            sampled = {lvl: len(p_list) for lvl, p_list in peers.items()}
            return {
                "success": True,
                "data": {
                    "available": True,
                    "total_org_chart": stats.get("total_org_chart", 0),
                    "total_resolved": stats.get("total_resolved", 0),
                    "total_unresolved": stats.get("total_unresolved", 0),
                    "by_level": by_level,
                    "sampled_per_level": sampled,
                    "selected_per_level": stats.get("selected_per_level", 10),
                    "generated": roster.get("generated", ""),
                },
            }
        except Exception as e:
            logger.warning("Failed to load org stats: %s", e)
            return {"success": False, "error": str(e)}

    def _update_peer_summary(
        self,
        username: str,
        level: str,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Build summary.json for a single peer from their daily files.

        Computes both raw cumulative scores and peer-comparable scores
        (strategy bonus stripped) so benchmarks can be built from either.
        """
        perf_dir = self._get_perf_dir(year, quarter)
        peer_daily_dir = perf_dir / "peers" / username / "daily"
        if not peer_daily_dir.exists():
            return {}

        _, _, daily_cap, target_per_competency = get_effective_defs()

        cumulative_points: dict[str, int] = {}
        comparable_points: dict[str, int] = {}
        total_events = 0
        days_with_events = 0
        event_counts: dict[str, int] = {}

        for daily_file in sorted(peer_daily_dir.glob("*.json")):
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                day_events = data.get("events", [])
                total_events += len(day_events)
                if day_events:
                    days_with_events += 1

                pc_daily: dict[str, int] = {}
                for ev in day_events:
                    src = ev.get("source", "unknown")
                    event_counts[src] = event_counts.get(src, 0) + 1

                    if not is_primary_only_event(ev, get_peer_comparable_config()):
                        ev_pts = normalize_strategy_bonus(
                            ev.get("points", {}),
                            ev,
                            bonus_multiplier=get_strategy_alignment_config().get(
                                "bonus_multiplier", 1.5
                            ),
                        )
                        for comp_id, pts in ev_pts.items():
                            current = pc_daily.get(comp_id, 0)
                            pc_daily[comp_id] = min(current + pts, daily_cap)

                for comp_id, pts in pc_daily.items():
                    comparable_points[comp_id] = comparable_points.get(comp_id, 0) + pts
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read peer daily file: %s", e)
                continue

        lw = get_level_weights(level)
        target_scale = lw.get("target_scale", 1.0)
        effective_target = max(round(target_per_competency * target_scale), 1)

        cumulative_pct = compute_competency_percentages(
            cumulative_points, effective_target
        )
        overall = round(sum(cumulative_pct.values()) / max(len(cumulative_pct), 1))

        comparable_pct = compute_competency_percentages(
            comparable_points, effective_target
        )
        comparable_overall = round(
            sum(comparable_pct.values()) / max(len(comparable_pct), 1)
        )

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
            "comparable_points": comparable_points,
            "comparable_percentage": comparable_pct,
            "comparable_overall": comparable_overall,
            "total_events": total_events,
            "days_captured": days_captured,
            "days_with_events": days_with_events,
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

    @staticmethod
    def _compute_distribution(values: list[float | int]) -> dict:
        """Compute min/max/median/p25/p75/avg from a list of numeric values."""
        from services.stats.peer_backfill import compute_distribution

        return compute_distribution(values)

    def _update_peer_benchmarks(
        self,
        year: int | None = None,
        quarter: int | None = None,
    ) -> dict:
        """Aggregate all peer summaries into benchmarks.json grouped by level.

        Produces both raw and comparable (strategy-normalized) benchmark
        stats so the UI can display a fair apples-to-apples comparison.

        Only peers with actual event data (total_events > 0) are included
        in averages and distributions.  The current user is excluded from
        the peer roster to avoid self-comparison bias.
        """
        perf_dir = self._get_perf_dir(year, quarter)
        peers_dir = perf_dir / "peers"
        if not peers_dir.exists():
            return {}

        self_username = self._collector.get_jira_username()
        peers_config = self._load_peers_config()
        pc_cfg = get_peer_comparable_config()

        benchmarks = compute_peer_benchmarks(
            peers_dir,
            peers_config,
            pc_cfg,
            self_username,
        )
        if not benchmarks:
            return {}

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
            logger.error("Failed to collect peer data for %s: %s", username, e)
            return {"success": False, "error": str(e)}

    async def _handle_collect_peers(self, **kwargs) -> dict:
        """Collect data for all configured peers for the current quarter.

        When backfill=True, launches a background task and returns immediately
        so the caller can poll progress via get_peer_backfill_progress.

        Optional filters (only used when backfill=True):
          sources:    list of data sources to collect, e.g. ["jira","gitlab"].
                      None / empty means all sources.
          usernames:  list of peer usernames to limit to.
                      None / empty means all peers.
          date_start: ISO date string for range start (inclusive).
          date_end:   ISO date string for range end (inclusive).
        """
        date_str = kwargs.get("date", "")
        backfill = kwargs.get("backfill", False)

        sources = kwargs.get("sources") or None
        usernames = kwargs.get("usernames") or None
        date_start = kwargs.get("date_start", "")
        date_end = kwargs.get("date_end", "")

        try:
            target = date.fromisoformat(date_str) if date_str else date.today()
        except ValueError:
            target = date.today()

        peers_config = self._load_peers_config()
        if not peers_config:
            return {"success": False, "error": "No peers configured"}

        if backfill:
            if self._peer_backfill_progress["running"]:
                return {
                    "success": False,
                    "error": "Peer backfill already running",
                    "progress": self._peer_backfill_progress,
                }
            self._peer_backfill_task = asyncio.create_task(
                self._run_peer_backfill(
                    peers_config,
                    target,
                    sources=sources,
                    usernames=usernames,
                    date_start=date_start,
                    date_end=date_end,
                )
            )
            label_parts = []
            if sources:
                label_parts.append(f"sources={sources}")
            if usernames:
                label_parts.append(f"peers={usernames}")
            if date_start or date_end:
                label_parts.append(
                    f"range={date_start or 'q-start'}..{date_end or 'today'}"
                )
            scope = ", ".join(label_parts) if label_parts else "all"
            return {
                "success": True,
                "async": True,
                "message": f"Peer backfill started ({scope})",
            }

        return await self._collect_peers_sync(peers_config, [target], sources=sources)

    def _ensure_strategy_and_hierarchy(self, year: int, quarter: int) -> None:
        """Load strategy index and hierarchy cache if not already set."""
        if not self._collector.strategy_index:
            emails_dir = self._get_executive_emails_dir(year, quarter)
            self._collector.strategy_index = build_strategy_context_index(emails_dir)
        if not self._collector.hierarchy_cache:
            perf_dir = self._get_perf_dir(year, quarter)
            cache_file = perf_dir / "jira_hierarchy_cache.json"
            if cache_file.exists():
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        self._collector.hierarchy_cache = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load hierarchy cache: %s", e)
                    self._collector.hierarchy_cache = {}

    async def _collect_peers_sync(
        self,
        peers_config: dict[str, list[dict]],
        dates_to_collect: list[date],
        sources: list[str] | None = None,
    ) -> dict:
        """Synchronous peer collection (for daily / single-date collection)."""
        loop = asyncio.get_event_loop()
        target = dates_to_collect[0]
        year = target.year
        quarter = (target.month - 1) // 3 + 1

        self._ensure_strategy_and_hierarchy(year, quarter)

        results: list[dict] = []
        total_events = 0

        for level_key, peer_list in peers_config.items():
            for peer in peer_list:
                username = peer["username"]
                peer_events = 0
                for d in dates_to_collect:
                    try:
                        daily_data = await loop.run_in_executor(
                            None,
                            lambda _d=d, _p=peer, _l=level_key, _s=sources: self._collector.collect_for_date(
                                _d, user_override=_p, level_override=_l, sources=_s
                            ),
                        )
                        peer_events += len(daily_data.get("events", []))
                    except Exception as e:
                        logger.debug("Peer %s date %s failed: %s", username, d, e)

                await loop.run_in_executor(
                    None, self._update_peer_summary, username, level_key, year, quarter
                )
                total_events += peer_events
                results.append(
                    {
                        "username": username,
                        "level": level_key,
                        "total_events": peer_events,
                    }
                )

        await loop.run_in_executor(None, self._update_peer_benchmarks, year, quarter)

        return {
            "success": True,
            "peers_processed": sum(len(pl) for pl in peers_config.values()),
            "backfill": False,
            "total_events": total_events,
            "results": results,
        }

    async def _run_peer_backfill(  # noqa: C901
        self,
        peers_config: dict[str, list[dict]],
        target: date,
        *,
        sources: list[str] | None = None,
        usernames: list[str] | None = None,
        date_start: str = "",
        date_end: str = "",
    ) -> None:
        """Background task: backfill peer data for the quarter with progress.

        Granular filters let callers re-collect specific slices without a
        full scrub:
          sources   – only re-collect these data sources (git/jira/gitlab/github/gdrive/meeting)
          usernames – only process these peers
          date_start/date_end – restrict to a date range within the quarter
        """
        year = target.year
        quarter = (target.month - 1) // 3 + 1
        loop = asyncio.get_event_loop()
        start_time = time.monotonic()

        src_set = set(sources) if sources else None
        filter_info = build_filter_label(sources, usernames, date_start, date_end)

        self._peer_backfill_cancelled = False
        self._peer_backfill_progress.update(
            {
                "running": True,
                "phase": "resolve_github",
                "phase_detail": "Resolving GitHub usernames...",
                "total_peers": 0,
                "completed_peers": 0,
                "current_peer": "resolving GitHub usernames...",
                "current_level": "",
                "total_days": 0,
                "completed_days": 0,
                "errors": [],
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed_seconds": 0,
                "total_events": 0,
                "cancelled": False,
                "phases_completed": [],
                "sources": sources or [],
                "filter_info": filter_info,
            }
        )

        try:
            from services.stats.org_parser import resolve_github_usernames

            peers_config = await loop.run_in_executor(
                None, resolve_github_usernames, peers_config
            )
            logger.info("GitHub username resolution completed before backfill")
        except Exception as e:
            logger.warning("GitHub username resolution failed (non-blocking): %s", e)

        self._peer_backfill_progress["phases_completed"].append("resolve_github")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        all_weekdays = get_weekdays_in_quarter_range(
            year, quarter, date_start, date_end
        )

        all_peers = [
            (level_key, peer)
            for level_key, peer_list in peers_config.items()
            for peer in peer_list
        ]
        if usernames:
            uname_set = set(usernames)
            all_peers = [(lk, p) for lk, p in all_peers if p["username"] in uname_set]

        total_peers = len(all_peers)
        total_days = len(all_weekdays)

        self._peer_backfill_progress.update(
            {
                "total_peers": total_peers,
                "current_peer": "",
                "total_days": total_days,
            }
        )

        self._ensure_strategy_and_hierarchy(year, quarter)

        perf_dir = self._get_perf_dir(year, quarter)
        for _level_key, peer in all_peers:
            if not src_set or "gitlab" in src_set:
                gl_user = peer.get("gitlab_username", "")
                if gl_user:
                    cache = perf_dir / f"gitlab_event_cache_{gl_user}.json"
                    if cache.exists():
                        with self._collector._gitlab_mem_lock:
                            self._collector._gitlab_mem_cache.pop(str(cache), None)
                        cache.unlink()
            if not src_set or "github" in src_set:
                gh_user = peer.get("github_username", "")
                if gh_user:
                    cache = perf_dir / f"github_cache_{gh_user}.json"
                    if cache.exists():
                        with self._collector._github_mem_lock:
                            self._collector._github_mem_cache.pop(str(cache), None)
                        cache.unlink()

        prefetch_count = 0
        if not src_set or src_set & {"gitlab", "github", "jira"}:
            self._peer_backfill_progress.update(
                {
                    "phase": "prefetch",
                    "phase_detail": "Pre-fetching quarter caches...",
                    "current_peer": "pre-fetching quarter caches...",
                }
            )
            for pf_idx, (_, peer) in enumerate(all_peers):
                if self._peer_backfill_cancelled:
                    self._peer_backfill_progress.update(
                        {"running": False, "cancelled": True, "phase": "cancelled"}
                    )
                    return
                pf_user = peer["username"]
                try:
                    if not src_set or "gitlab" in src_set:
                        gl_u = peer.get("gitlab_username", "")
                        if gl_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=gl_u: self._collector.get_gitlab_cache(
                                    year, quarter, username_override=_u
                                ),
                            )
                    if not src_set or "github" in src_set:
                        gh_u = peer.get("github_username", "")
                        if gh_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=gh_u: self._collector.get_github_cache(
                                    year, quarter, username_override=_u
                                ),
                            )
                    if not src_set or "jira" in src_set:
                        jira_u = peer.get("jira_username", "")
                        if jira_u:
                            await loop.run_in_executor(
                                None,
                                lambda _u=jira_u: self._collector.prefetch_jira_quarter(
                                    _u, year, quarter
                                ),
                            )
                    prefetch_count += 1
                except Exception as e:
                    logger.warning("Pre-fetch failed for %s: %s", pf_user, e)
                self._peer_backfill_progress.update(
                    {
                        "current_peer": f"pre-fetching caches... {pf_idx+1}/{len(all_peers)}",
                        "elapsed_seconds": int(time.monotonic() - start_time),
                    }
                )
            logger.info(
                "Pre-fetched quarter caches for %d/%d peers in %ds",
                prefetch_count,
                len(all_peers),
                int(time.monotonic() - start_time),
            )
            self._peer_backfill_progress["phases_completed"].append("prefetch")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        if not src_set or "gdrive" in src_set:
            self._peer_backfill_progress.update(
                {
                    "phase": "index_gdrive",
                    "phase_detail": "Indexing shared drives...",
                    "current_peer": "indexing shared drives...",
                }
            )
            try:
                from services.stats.gdrive_collector import (
                    _get_shared_drive_ids,
                    ensure_shared_drive_index,
                )

                _drive_ids = _get_shared_drive_ids()
                await loop.run_in_executor(
                    None,
                    lambda: ensure_shared_drive_index(
                        perf_dir=perf_dir,
                        drive_ids=_drive_ids,
                        target=all_weekdays[0] if all_weekdays else date.today(),
                    ),
                )
                logger.info(
                    "Shared drive index built in %ds",
                    int(time.monotonic() - start_time),
                )
            except Exception as e:
                logger.warning("Shared drive index failed (non-blocking): %s", e)
            self._peer_backfill_progress["phases_completed"].append("index_gdrive")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        if not src_set or "meeting" in src_set:
            self._peer_backfill_progress.update(
                {
                    "phase": "index_meetings",
                    "phase_detail": "Indexing meeting attendance...",
                    "current_peer": "indexing meeting attendance...",
                }
            )
            try:
                from services.stats.meeting_collector import ensure_meeting_peer_index

                await loop.run_in_executor(
                    None,
                    lambda: ensure_meeting_peer_index(
                        perf_dir=perf_dir,
                        target=all_weekdays[0] if all_weekdays else date.today(),
                    ),
                )
                logger.info(
                    "Meeting peer index built in %ds",
                    int(time.monotonic() - start_time),
                )
            except Exception as e:
                logger.warning("Meeting peer index failed (non-blocking): %s", e)
            self._peer_backfill_progress["phases_completed"].append("index_meetings")

        if self._peer_backfill_cancelled:
            self._peer_backfill_progress.update(
                {"running": False, "cancelled": True, "phase": "cancelled"}
            )
            return

        self._peer_backfill_progress.update(
            {
                "phase": "collecting",
                "phase_detail": "Collecting peer data...",
            }
        )

        parallel_peers = get_merged_config().get(
            "backfill_parallel_peers",
            DEFAULT_GLOBALS["backfill_parallel_peers"],
        )
        sem = asyncio.Semaphore(parallel_peers)
        completed_peers_count = 0
        total_events = 0
        _progress_lock = asyncio.Lock()

        async def _process_peer(
            peer_idx: int,
            level_key: str,
            peer: dict,
        ) -> int:
            nonlocal completed_peers_count, total_events
            username = peer["username"]

            async with sem:
                if src_set and "jira" in src_set:
                    jira_user = peer.get("jira_username", "")
                    if jira_user:
                        cache_key = f"{jira_user}:{year}:Q{quarter}"
                        with self._collector._jira_quarter_lock:
                            self._collector._jira_quarter_cache.pop(cache_key, None)

                peer_repos = None
                if not src_set or "git" in src_set:
                    peer_repos = await loop.run_in_executor(
                        None,
                        lambda _p=peer: self._collector.prepare_peer_repos(
                            _p, year, quarter
                        ),
                    )

                peer_events = 0
                peers_daily_dir = perf_dir / "peers" / username / "daily"
                for _day_idx, d in enumerate(all_weekdays):
                    if self._peer_backfill_cancelled:
                        return 0

                    existing_file = peers_daily_dir / f"{d.isoformat()}.json"
                    if existing_file.exists():
                        try:
                            with open(existing_file, encoding="utf-8") as _ef:
                                existing = json.load(_ef)
                            if existing.get("events"):
                                peer_events += len(existing["events"])
                                continue
                        except (json.JSONDecodeError, OSError) as exc:
                            logger.debug(
                                "Skipped existing peer daily file due to: %s", exc
                            )
                            pass

                    try:

                        def _collect(
                            _d=d, _p=peer, _l=level_key, _s=sources, _r=peer_repos
                        ):
                            return self._collector.collect_for_date(
                                _d,
                                user_override=_p,
                                level_override=_l,
                                sources=_s,
                                peer_repos=_r,
                            )

                        daily_data = await loop.run_in_executor(None, _collect)
                        peer_events += len(daily_data.get("events", []))
                    except Exception as e:
                        async with _progress_lock:
                            if (
                                len(self._peer_backfill_progress["errors"])
                                < MAX_PEER_BACKFILL_ERRORS
                            ):
                                self._peer_backfill_progress["errors"].append(
                                    f"{username}/{d}: {e}"
                                )

                await loop.run_in_executor(
                    None, self._update_peer_summary, username, level_key, year, quarter
                )

                async with _progress_lock:
                    completed_peers_count += 1
                    total_events += peer_events
                    self._peer_backfill_progress.update(
                        {
                            "completed_peers": completed_peers_count,
                            "total_events": total_events,
                            "current_peer": username,
                            "current_level": level_key,
                            "completed_days": len(all_weekdays),
                            "elapsed_seconds": int(time.monotonic() - start_time),
                        }
                    )

                logger.info(
                    "Peer backfill %d/%d: %s (%s) -- %d events",
                    completed_peers_count,
                    total_peers,
                    username,
                    level_key,
                    peer_events,
                )
                return peer_events

        try:
            tasks = [_process_peer(idx, lk, p) for idx, (lk, p) in enumerate(all_peers)]
            await asyncio.gather(*tasks)

            if self._peer_backfill_cancelled:
                self._peer_backfill_progress.update(
                    {"running": False, "cancelled": True, "phase": "cancelled"}
                )
                return

            self._peer_backfill_progress["phases_completed"].append("collecting")
            self._peer_backfill_progress.update(
                {
                    "phase": "benchmarks",
                    "phase_detail": "Updating benchmarks...",
                }
            )

            await loop.run_in_executor(
                None, self._update_peer_benchmarks, year, quarter
            )
            self._peer_backfill_progress["phases_completed"].append("benchmarks")
            self._peer_backfill_progress["phase"] = "complete"
            logger.info(
                "Peer backfill complete: %d peers, %d events in %ds (filter: %s)",
                total_peers,
                total_events,
                int(time.monotonic() - start_time),
                filter_info,
            )
        except Exception as e:
            logger.error("Peer backfill failed: %s", e)
            self._peer_backfill_progress["errors"].append(f"Fatal: {e}")
            self._peer_backfill_progress["phase"] = "error"
        finally:
            self._peer_backfill_progress["running"] = False
            self._peer_backfill_progress["elapsed_seconds"] = int(
                time.monotonic() - start_time
            )

    async def _handle_get_peer_backfill_progress(self, **kwargs) -> dict:
        """Return current peer backfill progress for the UI."""
        return {"success": True, **self._peer_backfill_progress}

    async def _handle_cancel_backfill(self, **kwargs) -> dict:
        """Cancel a running peer backfill."""
        if not self._peer_backfill_progress.get("running"):
            return {"success": True, "message": "No backfill running"}

        self._peer_backfill_cancelled = True
        if self._peer_backfill_task and not self._peer_backfill_task.done():
            self._peer_backfill_task.cancel()

        self._peer_backfill_progress.update(
            {
                "running": False,
                "cancelled": True,
                "phase": "cancelled",
                "phase_detail": "Cancelled by user",
            }
        )
        logger.info("Peer backfill cancelled by user")
        return {"success": True, "message": "Backfill cancelled"}

    async def _handle_scrub_data(self, **kwargs) -> dict:
        """Scrub all collected performance data for the current quarter.

        Nukes the entire perf_dir and parent quarter caches, resets all
        in-memory caches.  After scrub the UI should show a blank slate.
        """
        import shutil

        if self._peer_backfill_progress.get("running"):
            await self._handle_cancel_backfill()

        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)

        perf_dir = self._get_perf_dir(year, quarter)
        quarter_dir = perf_dir.parent  # e.g. .../2026/q1/

        deleted: dict[str, int] = {}

        # Wipe the entire perf_dir (daily/, peers/, questions.json,
        # summary.json, caches, anstrat, reports, sender files - everything)
        if perf_dir.exists():
            count = sum(1 for _ in perf_dir.rglob("*") if _.is_file())
            shutil.rmtree(perf_dir)
            perf_dir.mkdir(parents=True, exist_ok=True)
            deleted["perf_dir_files"] = count

        # Wipe quarter-level caches that live outside perf_dir
        quarter_cache_patterns = [
            "gdrive_shared_drive_cache.json",
            "gdrive_shared_drive_user_index.json",
            "meeting_contributions_cache.json",
            "meeting_peer_index_cache.json",
        ]
        for pattern in quarter_cache_patterns:
            for f in quarter_dir.glob(pattern):
                f.unlink()
                deleted[f.name] = deleted.get(f.name, 0) + 1

        # Wipe executive emails dir (may be inside or beside perf_dir)
        emails_dir = self._get_executive_emails_dir(year, quarter)
        if emails_dir.exists():
            count = sum(1 for f in emails_dir.glob("*") if f.is_file())
            shutil.rmtree(emails_dir)
            deleted["executive_email_files"] = count

        # Reset ALL in-memory caches
        with self._collector._gitlab_mem_lock:
            self._collector._gitlab_mem_cache.clear()
        with self._collector._github_mem_lock:
            self._collector._github_mem_cache.clear()
        with self._collector._jira_quarter_lock:
            self._collector._jira_quarter_cache.clear()

        self._collector.strategy_index = {}
        self._collector.hierarchy_cache = {}

        # Flush the daemon's own file cache so stale data isn't served
        self._stats_cache.clear()
        self._last_modified.clear()

        total = sum(deleted.values())
        logger.info("Scrubbed %d items from %s Q%d: %s", total, year, quarter, deleted)

        return {
            "success": True,
            "message": f"Scrubbed {total} items from {year} Q{quarter}",
            "deleted": deleted,
            "year": year,
            "quarter": quarter,
        }

    async def _handle_rescore_peers(self, **kwargs) -> dict:
        """Re-enrich and re-score all peer daily files without re-collecting.

        Mirrors evaluate_all but operates on peers/{username}/daily/ dirs.
        Useful after scoring config changes or hierarchy/strategy updates.
        """
        now = datetime.now()
        year = kwargs.get("year") or now.year
        quarter = kwargs.get("quarter") or ((now.month - 1) // 3 + 1)
        usernames_filter = kwargs.get("usernames") or None

        perf_dir = self._get_perf_dir(year, quarter)
        peers_dir = perf_dir / "peers"
        if not peers_dir.exists():
            return {"success": True, "files_updated": 0, "peers_updated": 0}

        loop = asyncio.get_event_loop()

        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_index = build_strategy_context_index(emails_dir)
        cache_file = perf_dir / "jira_hierarchy_cache.json"
        hierarchy_cache: dict = {}
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    hierarchy_cache = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load hierarchy cache: %s", e)
                pass
        self._collector.hierarchy_cache = hierarchy_cache
        self._collector.strategy_index = strategy_index

        def _rescore_peers() -> tuple[int, int]:
            eff_defs, min_sig, daily_cap, _ = get_effective_defs()
            files_updated = 0
            peers_updated = 0

            for peer_path in sorted(peers_dir.iterdir()):
                if not peer_path.is_dir():
                    continue
                username = peer_path.name
                if usernames_filter and username not in usernames_filter:
                    continue
                daily_dir = peer_path / "daily"
                if not daily_dir.exists():
                    continue

                peer_changed = False
                for daily_file in sorted(daily_dir.glob("*.json")):
                    try:
                        with open(daily_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except (json.JSONDecodeError, OSError) as e:
                        logger.warning("Failed to read daily file for rescore: %s", e)
                        continue

                    events = data.get("events", [])
                    for ev in events:
                        self._collector._enrich_event(ev, eff_defs, min_sig)

                    deduped = dedup_events_by_jira_key(
                        events, get_peer_comparable_config()
                    )
                    daily_points = compute_daily_points(
                        deduped, daily_cap, get_source_daily_caps()
                    )

                    data["daily_points"] = daily_points
                    data["daily_total"] = sum(daily_points.values())
                    data["re_evaluated_at"] = datetime.now().isoformat()
                    with open(daily_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    files_updated += 1
                    peer_changed = True

                if peer_changed:
                    peers_updated += 1

            return files_updated, peers_updated

        files_updated, peers_updated = await loop.run_in_executor(None, _rescore_peers)

        peers_config = self._load_peers_config()
        if peers_config:
            for level_key, peer_list in peers_config.items():
                for peer in peer_list:
                    username = peer["username"]
                    if usernames_filter and username not in usernames_filter:
                        continue
                    peer_daily = peers_dir / username / "daily"
                    if peer_daily.exists():
                        await loop.run_in_executor(
                            None,
                            self._update_peer_summary,
                            username,
                            level_key,
                            year,
                            quarter,
                        )

        await loop.run_in_executor(None, self._update_peer_benchmarks, year, quarter)

        return {
            "success": True,
            "files_updated": files_updated,
            "peers_updated": peers_updated,
            "quarter": f"Q{quarter} {year}",
        }

    async def _handle_resolve_github_usernames(self, **kwargs) -> dict:
        """Resolve GitHub usernames for all peers in the roster."""
        try:
            from services.stats.org_parser import resolve_github_usernames

            peers_config = self._load_peers_config()
            if not peers_config:
                return {"success": False, "error": "No peers configured"}
            loop = asyncio.get_event_loop()
            resolved = await loop.run_in_executor(
                None, resolve_github_usernames, peers_config
            )
            total = sum(len(pl) for pl in resolved.values())
            changed = sum(
                1
                for pl in resolved.values()
                for p in pl
                if p["github_username"] != p["username"]
            )
            return {
                "success": True,
                "total_peers": total,
                "resolved_different": changed,
            }
        except Exception as e:
            logger.error("GitHub username resolution failed: %s", e)
            return {"success": False, "error": str(e)}

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
            except (json.JSONDecodeError, OSError) as e:
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for event counts: %s", e)
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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load benchmarks.json: %s", e)
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(
                        "Failed to read daily file for overview digest: %s", e
                    )
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for gap coach: %s", e)
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

        quarter_starts = QUARTER_STARTS
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
            logger.error("Local question evaluation failed: %s", e)
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
        except Exception as e:
            logger.warning("Failed to load scoring config: %s", e)

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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for explain: %s", e)
                    continue

        scoring_config = None
        try:
            scoring_config = get_merged_config()
        except Exception as e:
            logger.warning("Failed to load scoring config: %s", e)

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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for clustering: %s", e)
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
            logger.error("Clustering failed: %s", e)
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

        def _rethreshold() -> tuple[
            int,
            dict[str, int],
            int,
            list[str],
            dict[str, int],
            int,
            dict[str, int],
            dict[str, int],
            dict[str, int],
        ]:
            eff_defs, _, daily_cap, _ = get_effective_defs()
            cfg = get_merged_config()
            level = cfg.get("engineering_level", "sse")
            pc_cfg = get_peer_comparable_config()
            strategy_bonus = get_strategy_alignment_config().get(
                "bonus_multiplier", 1.5
            )

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
            missing_signal_counts = 0
            pc_points: dict[str, int] = {}
            ne_points: dict[str, int] = {}
            pc_events = 0
            counts_by_source: dict[str, int] = {}
            comparable_counts_by_source: dict[str, int] = {}
            source_caps = get_source_daily_caps()

            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for rethreshold: %s", e)
                    continue

                events = data.get("events", [])
                file_changed = False

                for ev in events:
                    sig_counts = ev.get("signal_counts")
                    if not sig_counts:
                        missing_signal_counts += 1
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

                deduped = dedup_events_by_jira_key(events, get_peer_comparable_config())
                daily_points = compute_daily_points(
                    deduped, daily_cap, get_source_daily_caps()
                )

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

                ne_daily, pc_daily, day_pc_events, day_counts, day_comp_counts = (
                    process_daily_events_for_summary(
                        events,
                        daily_cap,
                        source_caps,
                        pc_cfg,
                        strategy_bonus_multiplier=strategy_bonus,
                    )
                )
                for comp_id, pts in ne_daily.items():
                    ne_points[comp_id] = ne_points.get(comp_id, 0) + pts
                for comp_id, pts in pc_daily.items():
                    pc_points[comp_id] = pc_points.get(comp_id, 0) + pts
                pc_events += day_pc_events
                total_events += sum(day_counts.values())
                for src, cnt in day_counts.items():
                    counts_by_source[src] = counts_by_source.get(src, 0) + cnt
                for src, cnt in day_comp_counts.items():
                    comparable_counts_by_source[src] = (
                        comparable_counts_by_source.get(src, 0) + cnt
                    )

                highlights_max = get_merged_config().get(
                    "highlights_max_count",
                    DEFAULT_GLOBALS["highlights_max_count"],
                )
                for ev in events[:3]:
                    if ev.get("title") and len(highlights) < highlights_max:
                        highlights.append(ev["title"][:80])

            return (
                updated,
                cumulative_points,
                total_events,
                highlights,
                missing_signal_counts,
                pc_points,
                pc_events,
                counts_by_source,
                comparable_counts_by_source,
                ne_points,
            )

        result = await loop.run_in_executor(None, _rethreshold)
        (
            files_updated,
            cumulative_points,
            total_events,
            highlights,
            missing_sc,
            pc_points,
            pc_events,
            counts_by_source,
            comparable_counts_by_source,
            ne_points,
        ) = result

        if missing_sc > 0:
            logger.warning(
                "Fast rethreshold found %d events without signal_counts, "
                "falling back to full evaluate_all",
                missing_sc,
            )
            return await self._handle_evaluate_all(year=year, quarter=quarter)
        await loop.run_in_executor(
            None,
            lambda: self._update_summary_from_data(
                SummaryUpdateContext(
                    cumulative_points=cumulative_points,
                    total_events=total_events,
                    highlights=highlights,
                    pc_points=pc_points,
                    pc_events=pc_events,
                    counts_by_source=counts_by_source,
                    comparable_counts_by_source=comparable_counts_by_source,
                    ne_points=ne_points,
                    year=year,
                    quarter=quarter,
                    skip_strategy=True,
                )
            ),
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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load hierarchy cache: %s", e)
                pass

        self._collector.hierarchy_cache = hierarchy_cache
        self._collector.strategy_index = strategy_index

        def _rescore() -> tuple[
            int,
            dict[str, int],
            int,
            list[str],
            dict[str, int],
            int,
            dict[str, int],
            dict[str, int],
            dict[str, int],
        ]:
            eff_defs, min_sig, daily_cap, _ = get_effective_defs()
            cfg = get_merged_config()
            _level = cfg.get("engineering_level", "sse")  # noqa: F841
            strategy_cfg = get_strategy_alignment_config()
            _min_overlap = strategy_cfg.get("min_text_overlap_words", 4)  # noqa: F841
            pc_cfg = get_peer_comparable_config()
            strategy_bonus = strategy_cfg.get("bonus_multiplier", 1.5)
            source_caps = get_source_daily_caps()
            updated = 0
            cumulative_points: dict[str, int] = {}
            total_events = 0
            highlights: list[str] = []
            pc_points: dict[str, int] = {}
            ne_points: dict[str, int] = {}
            pc_events = 0
            counts_by_source: dict[str, int] = {}
            comparable_counts_by_source: dict[str, int] = {}

            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for rescore: %s", e)
                    continue

                events = data.get("events", [])
                for ev in events:
                    self._collector._enrich_event(ev, eff_defs, min_sig)

                work_events = [
                    ev
                    for ev in events
                    if not is_personal_repo_event(ev, get_peer_comparable_config())
                ]
                deduped = dedup_events_by_jira_key(
                    work_events, get_peer_comparable_config()
                )
                daily_points = compute_daily_points(
                    deduped, daily_cap, get_source_daily_caps()
                )

                data["daily_points"] = daily_points
                data["daily_total"] = sum(daily_points.values())
                data["re_evaluated_at"] = datetime.now().isoformat()
                with open(daily_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                updated += 1

                for comp_id, pts in daily_points.items():
                    cumulative_points[comp_id] = cumulative_points.get(comp_id, 0) + pts
                total_events += len(work_events)

                ne_daily, pc_daily, day_pc_events, day_counts, day_comp_counts = (
                    process_daily_events_for_summary(
                        events,
                        daily_cap,
                        source_caps,
                        pc_cfg,
                        strategy_bonus_multiplier=strategy_bonus,
                    )
                )
                for comp_id, pts in ne_daily.items():
                    ne_points[comp_id] = ne_points.get(comp_id, 0) + pts
                for comp_id, pts in pc_daily.items():
                    pc_points[comp_id] = pc_points.get(comp_id, 0) + pts
                pc_events += day_pc_events
                for src, cnt in day_counts.items():
                    counts_by_source[src] = counts_by_source.get(src, 0) + cnt
                for src, cnt in day_comp_counts.items():
                    comparable_counts_by_source[src] = (
                        comparable_counts_by_source.get(src, 0) + cnt
                    )

                highlights_max = get_merged_config().get(
                    "highlights_max_count",
                    DEFAULT_GLOBALS["highlights_max_count"],
                )
                for ev in events[:3]:
                    if ev.get("title") and len(highlights) < highlights_max:
                        highlights.append(ev["title"][:80])

            return (
                updated,
                cumulative_points,
                total_events,
                highlights,
                pc_points,
                pc_events,
                counts_by_source,
                comparable_counts_by_source,
                ne_points,
            )

        result = await loop.run_in_executor(None, _rescore)
        (
            files_updated,
            cumulative_points,
            total_events,
            highlights,
            pc_points,
            pc_events,
            counts_by_source,
            comparable_counts_by_source,
            ne_points,
        ) = result
        await loop.run_in_executor(
            None,
            lambda: self._update_summary_from_data(
                SummaryUpdateContext(
                    cumulative_points=cumulative_points,
                    total_events=total_events,
                    highlights=highlights,
                    pc_points=pc_points,
                    pc_events=pc_events,
                    counts_by_source=counts_by_source,
                    comparable_counts_by_source=comparable_counts_by_source,
                    ne_points=ne_points,
                    year=year,
                    quarter=quarter,
                )
            ),
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
            logger.error("Failed to set scoring config: %s", e)
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
            logger.error("Failed to reset scoring config: %s", e)
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for captured days: %s", e)
                    days.append(
                        {
                            "date": f.stem,
                            "event_count": 0,
                            "total_points": 0,
                            "sources": [],
                            "category_points": {},
                        }
                    )

        quarter_starts = QUARTER_STARTS
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

    @staticmethod
    def _refresh_issue_hierarchy_from_jira(  # noqa: C901
        issue_keys: dict[str, dict],
        issue_info: dict[str, dict],
        perf_dir: Path,
    ) -> dict[str, dict]:
        """Fetch issue metadata from Jira via subprocess (blocking I/O)."""

        def _rh_issue(args: list[str], timeout: int = 15) -> str:
            """Run rh-issue with proper user shell env (bashrc, PATH, JIRA_JPAT)."""
            ok, out = run_cmd_sync(["rh-issue"] + args, timeout=timeout)
            if not ok:
                raise RuntimeError(out)
            return out

        aap_keys = [k for k in issue_keys if k.startswith("AAP-")]

        for key in aap_keys[:MAX_HIERARCHY_KEYS_PER_BATCH]:
            try:
                result = _rh_issue(["view-issue", key])
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
                    info["description"] = " ".join(desc_lines)[:MAX_DESCRIPTION_LENGTH]
                if "summary" not in info:
                    for line in result.split("\n"):
                        if key in line:
                            info["summary"] = line.split(key)[-1].strip(": ")[
                                :MAX_SUMMARY_LENGTH
                            ]
                            break
                if "summary" in info:
                    info["summary"] = html_unescape(info["summary"])
                issue_info[key] = info
            except Exception as e:
                logger.debug("Failed to fetch %s: %s", key, e)

        epic_keys_set: set[str] = set()
        for info_val in issue_info.values():
            epic_key = info_val.get("epic", "")
            if epic_key and epic_key.startswith("AAP-"):
                epic_keys_set.add(epic_key)

        for epic_key in epic_keys_set:
            if epic_key not in issue_info:
                try:
                    result = _rh_issue(["view-issue", epic_key])
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
                                einfo["summary"] = html_unescape(val)
                            if field == "component/s":
                                einfo["component"] = val
                            if field in ("parent", "parent_link"):
                                if val.startswith("ANSTRAT-"):
                                    einfo["parent_initiative"] = val
                    issue_info[epic_key] = einfo
                except Exception as e:
                    logger.debug("Failed to fetch epic %s: %s", epic_key, e)

        # Discover user-assigned ANSTRATs (exclude Closed/Done)
        user_assigned_anstrats: set[str] = set()
        try:
            result = _rh_issue(
                [
                    "search",
                    "project = ANSTRAT AND assignee = currentUser() "
                    "AND status not in (Closed, Done, Resolved) "
                    "ORDER BY updated DESC",
                    "--max-results",
                    "20",
                ],
                timeout=JIRA_QUERY_TIMEOUT,
            )
            for line in result.split("\n"):
                found = re.findall(r"(ANSTRAT-\d+)", line)
                for ak in found:
                    user_assigned_anstrats.add(ak)
                    if ak not in issue_info:
                        parts = line.split("|")
                        if len(parts) >= 5:
                            issue_info[ak] = {
                                "key": ak,
                                "issue_type": (
                                    parts[1].strip() if len(parts) > 1 else "Initiative"
                                ),
                                "summary": html_unescape(
                                    parts[4].strip()[:MAX_SUMMARY_LENGTH]
                                    if len(parts) > 4
                                    else ak
                                ),
                            }
        except Exception as e:
            logger.debug("Failed to search user-assigned ANSTRATs: %s", e)

        # Collect ANSTRATs discovered as parents of user's epics
        hierarchy_anstrats: set[str] = set()
        for info_val in issue_info.values():
            parent = info_val.get("parent_initiative", "")
            if parent.startswith("ANSTRAT-"):
                hierarchy_anstrats.add(parent)

        # For epics still unmapped, query user-assigned ANSTRATs for children
        if epic_keys_set:
            unmapped_epics = {
                k
                for k in epic_keys_set
                if not issue_info.get(k, {}).get("parent_initiative")
            }
            if unmapped_epics:
                epic_list_str = ", ".join(sorted(epic_keys_set))
                for anstrat_key in user_assigned_anstrats:
                    if not unmapped_epics:
                        break
                    try:
                        jql = (
                            f'"Parent Link" = {anstrat_key}'
                            f" AND key in ({epic_list_str})"
                        )
                        result = _rh_issue(
                            ["search", jql, "--max-results", "20"],
                            timeout=20,
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
                            hierarchy_anstrats.add(anstrat_key)
                    except Exception as e:
                        logger.debug(
                            "Failed to query children of %s: %s", anstrat_key, e
                        )

        # Discover child epics assigned to user under user-assigned ANSTRATs
        relevant_anstrats = user_assigned_anstrats | hierarchy_anstrats
        for anstrat_key in relevant_anstrats:
            try:
                jql = f'"Parent Link" = {anstrat_key}' f" AND assignee = currentUser()"
                result = _rh_issue(
                    ["search", jql, "--max-results", "20"],
                    timeout=20,
                )
                for line in result.split("\n"):
                    child_keys = re.findall(r"(AAP-\d+)", line)
                    for ce in child_keys:
                        if ce in issue_info:
                            if not issue_info[ce].get("parent_initiative"):
                                issue_info[ce]["parent_initiative"] = anstrat_key
                        else:
                            parts = line.split("|")
                            issue_info[ce] = {
                                "key": ce,
                                "parent_initiative": anstrat_key,
                                "issue_type": (
                                    parts[1].strip() if len(parts) > 1 else "Epic"
                                ),
                                "summary": (
                                    parts[4].strip()[:MAX_SUMMARY_LENGTH]
                                    if len(parts) > 4
                                    else ce
                                ),
                            }
            except Exception as e:
                logger.debug("Failed to query user children of %s: %s", anstrat_key, e)

        # Track which ANSTRATs are user-relevant for display filtering
        issue_info["_user_relevant_anstrats"] = {
            "keys": sorted(user_assigned_anstrats | hierarchy_anstrats)
        }

        perf_dir.mkdir(parents=True, exist_ok=True)
        cache_file = perf_dir / "jira_hierarchy_cache.json"
        cache_data = {"issues": issue_info, "updated": datetime.now().isoformat()}
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(cache_data, fh, indent=2)

        return issue_info

    async def _handle_get_issue_hierarchy(self, **kwargs) -> dict:  # noqa: C901
        """Extract issue keys from daily data and build hierarchy tree."""
        from services.stats.scorer import COMPETENCY_DEFS

        refresh = kwargs.get("refresh_from_jira", False)
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1

        perf_dir = self._get_perf_dir(year, quarter)
        daily_dir = self._get_daily_dir(year, quarter)
        cache_file = perf_dir / "jira_hierarchy_cache.json"

        comp_to_pillar: dict[str, str] = {}
        pillar_short: dict[str, str] = {
            "Technical Contribution": "technical",
            "Leadership": "leadership",
            "Mentorship": "mentorship",
            "End-to-End Delivery": "delivery",
        }
        for cid, defn in COMPETENCY_DEFS.items():
            cat = defn.get("category", "Technical Contribution")
            comp_to_pillar[cid] = pillar_short.get(cat, "technical")

        emails_dir = self._get_executive_emails_dir(year, quarter)
        strategy_index = build_strategy_context_index(emails_dir)
        strat_issue_keys = strategy_index.get("all_issue_keys", {})

        issue_keys: dict[str, dict] = {}
        if daily_dir.exists():
            for f in sorted(daily_dir.glob("*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                    for ev in data.get("events", []):
                        title = ev.get("title", "")
                        ev_points = ev.get("points", {})
                        pts = sum(ev_points.values())
                        ev_scope = ev.get("scope", "commit")
                        ev_strategy = ev.get("strategy_aligned", False)
                        ev_strat_names = ev.get("strategy_priorities", [])

                        pillar_pts: dict[str, int] = {
                            "technical": 0,
                            "leadership": 0,
                            "mentorship": 0,
                            "delivery": 0,
                        }
                        for comp_id, comp_pts in ev_points.items():
                            pillar = comp_to_pillar.get(comp_id, "technical")
                            pillar_pts[pillar] += comp_pts

                        keys_in_title = re.findall(r"((?:AAP|ANSTRAT)-\d+)", title)
                        for key in keys_in_title:
                            if key not in issue_keys:
                                issue_keys[key] = {
                                    "points": 0,
                                    "titles": [],
                                    "event_count": 0,
                                    "strategy_aligned": False,
                                    "strategy_names": set(),
                                    "pillar_points": {
                                        "technical": 0,
                                        "leadership": 0,
                                        "mentorship": 0,
                                        "delivery": 0,
                                    },
                                    "scope_points": {},
                                }
                            ik = issue_keys[key]
                            ik["points"] += pts
                            ik["event_count"] += 1
                            if title not in ik["titles"]:
                                ik["titles"].append(title[:120])
                            if ev_strategy:
                                ik["strategy_aligned"] = True
                            for sn in ev_strat_names:
                                ik["strategy_names"].add(sn)
                            for p, v in pillar_pts.items():
                                ik["pillar_points"][p] += v
                            ik["scope_points"][ev_scope] = (
                                ik["scope_points"].get(ev_scope, 0) + pts
                            )
                except Exception as e:
                    logger.warning("Failed to process daily event for hierarchy: %s", e)
                    continue

        for key, ik in issue_keys.items():
            if not ik["strategy_aligned"] and key in strat_issue_keys:
                ik["strategy_aligned"] = True
                for sn in strat_issue_keys[key]:
                    ik["strategy_names"].add(sn)
            ik["strategy_names"] = sorted(ik["strategy_names"])

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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load hierarchy cache: %s", e)
                pass

        issue_info: dict[str, dict] = cached.get("issues", {})

        if refresh and issue_keys:
            issue_info = await asyncio.to_thread(
                self._refresh_issue_hierarchy_from_jira,
                issue_keys,
                issue_info,
                perf_dir,
            )

        # Build the tree: ANSTRAT -> Epic -> Issue
        strategies: dict[str, dict] = {}
        epics: dict[str, dict] = {}
        uncategorized: list[dict] = []

        def _empty_pillar() -> dict:
            return {"technical": 0, "leadership": 0, "mentorship": 0, "delivery": 0}

        def _summary_from_titles(titles: list[str], issue_key: str) -> str:
            """Extract a display summary from event titles when Jira summary is missing."""
            for t in titles:
                cleaned = re.sub(r"(?:AAP|ANSTRAT)-\d+\s*[-:]\s*", "", t).strip()
                if cleaned and len(cleaned) > 5:
                    return html_unescape(cleaned[:MAX_SUMMARY_LENGTH])
            return ""

        for key, data in issue_keys.items():
            jira_summary = issue_info.get(key, {}).get("summary", "")
            if jira_summary:
                jira_summary = html_unescape(jira_summary)
            if not jira_summary:
                jira_summary = _summary_from_titles(data.get("titles", []), key)
            node = {
                "key": key,
                "summary": jira_summary,
                "type": issue_info.get(key, {}).get("issue_type", "story").lower(),
                "points": data["points"],
                "event_count": data["event_count"],
                "keywords": extract_keywords(data["titles"]),
                "strategy_aligned": data.get("strategy_aligned", False),
                "strategy_names": data.get("strategy_names", []),
                "pillar_points": data.get("pillar_points", _empty_pillar()),
                "scope_points": data.get("scope_points", {}),
                "children": [],
            }
            if key.startswith("ANSTRAT-"):
                strategies[key] = node
                node["type"] = "strategy"
                node["strategy_aligned"] = True
            else:
                epic_key = issue_info.get(key, {}).get("epic", "")
                if epic_key:
                    if epic_key not in epics:
                        epics[epic_key] = {
                            "key": epic_key,
                            "summary": html_unescape(
                                issue_info.get(epic_key, {}).get("summary", epic_key)
                            ),
                            "type": "epic",
                            "points": 0,
                            "event_count": 0,
                            "keywords": [],
                            "strategy_aligned": False,
                            "strategy_names": [],
                            "pillar_points": _empty_pillar(),
                            "scope_points": {},
                            "children": [],
                        }
                    epics[epic_key]["children"].append(node)
                    epics[epic_key]["points"] += node["points"]
                    if node["strategy_aligned"]:
                        epics[epic_key]["strategy_aligned"] = True
                    for p in ("technical", "leadership", "mentorship", "delivery"):
                        epics[epic_key]["pillar_points"][p] += node[
                            "pillar_points"
                        ].get(p, 0)
                    for sc, sv in node["scope_points"].items():
                        epics[epic_key]["scope_points"][sc] = (
                            epics[epic_key]["scope_points"].get(sc, 0) + sv
                        )
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
                        "summary": html_unescape(anstrat_info.get("summary", parent)),
                        "type": "strategy",
                        "points": 0,
                        "event_count": 0,
                        "keywords": [],
                        "strategy_aligned": True,
                        "strategy_names": [],
                        "pillar_points": _empty_pillar(),
                        "scope_points": {},
                        "children": [],
                    }
                strategies[parent]["children"].append(epic_node)
                strategies[parent]["points"] += epic_node["points"]
                if epic_node.get("strategy_aligned"):
                    strategies[parent]["strategy_aligned"] = True
                for p in ("technical", "leadership", "mentorship", "delivery"):
                    strategies[parent]["pillar_points"][p] += epic_node.get(
                        "pillar_points", {}
                    ).get(p, 0)
                for sc, sv in epic_node.get("scope_points", {}).items():
                    strategies[parent]["scope_points"][sc] = (
                        strategies[parent]["scope_points"].get(sc, 0) + sv
                    )
                attached = True
            if not attached:
                unattached_epics.append(epic_node)

        # Add user-relevant ANSTRATs that have no events yet
        # Only ANSTRATs the user is assigned to or that are parents of user epics
        relevant_set = set(
            issue_info.get("_user_relevant_anstrats", {}).get("keys", [])
        )
        for info_key, info_val in issue_info.items():
            if (
                info_key.startswith("ANSTRAT-")
                and info_key not in strategies
                and info_key in relevant_set
            ):
                strategies[info_key] = {
                    "key": info_key,
                    "summary": info_val.get("summary", info_key),
                    "type": "strategy",
                    "points": 0,
                    "event_count": 0,
                    "keywords": [],
                    "strategy_aligned": True,
                    "strategy_names": [],
                    "pillar_points": _empty_pillar(),
                    "scope_points": {},
                    "children": [],
                }

        strat_list = sorted(strategies.values(), key=lambda x: -x["points"])
        for s in strat_list:
            s["children"] = sorted(s["children"], key=lambda x: -x["points"])
            for e in s["children"]:
                e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        unattached_epics = sorted(unattached_epics, key=lambda x: -x["points"])
        for e in unattached_epics:
            e["children"] = sorted(e["children"], key=lambda x: -x["points"])

        uncategorized = sorted(uncategorized, key=lambda x: -x["points"])

        total_points = sum(ik["points"] for ik in issue_keys.values())
        aligned_points = sum(
            ik["points"] for ik in issue_keys.values() if ik.get("strategy_aligned")
        )
        agg_scope: dict[str, int] = {}
        agg_pillar: dict[str, int] = {
            "technical": 0,
            "leadership": 0,
            "mentorship": 0,
            "delivery": 0,
        }
        agg_tags: dict[str, int] = {}
        for ik in issue_keys.values():
            for sc, sv in ik.get("scope_points", {}).items():
                agg_scope[sc] = agg_scope.get(sc, 0) + sv
            for p in ("technical", "leadership", "mentorship", "delivery"):
                agg_pillar[p] += ik.get("pillar_points", {}).get(p, 0)
            for kw in extract_keywords(ik.get("titles", [])):
                agg_tags[kw] = agg_tags.get(kw, 0) + 1

        return {
            "success": True,
            "strategies": strat_list,
            "unattached_epics": unattached_epics,
            "uncategorized": uncategorized,
            "total_issues": len(issue_keys),
            "cached": not refresh and bool(cached),
            "summary": {
                "total_points": total_points,
                "aligned_points": aligned_points,
                "unaligned_points": total_points - aligned_points,
                "alignment_pct": (
                    round(aligned_points / total_points * 100) if total_points else 0
                ),
                "scope_points": agg_scope,
                "pillar_points": agg_pillar,
                "tag_counts": dict(sorted(agg_tags.items(), key=lambda x: -x[1])),
            },
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read daily file for report: %s", e)
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
            logger.warning("Failed to load hierarchy for PDF: %s", e)

        comp_evidence: dict = {}
        gap_suggestions_data: dict = {}
        try:
            ev_result = await self._handle_get_competency_evidence()
            comp_evidence = ev_result.get("competency_evidence", {})
            gap_suggestions_data = ev_result.get("gap_suggestions", {})
        except Exception as e:
            logger.warning("Failed to load competency evidence for PDF: %s", e)

        captured_days: list[dict] = []
        try:
            cap_result = await self._handle_get_captured_days()
            captured_days = cap_result.get("days", [])
        except Exception as e:
            logger.warning("Failed to load captured days for PDF: %s", e)

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
            logger.warning("Failed to load strategy data for PDF: %s", e)

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
                logger.debug("Failed to load peer benchmarks for report: %s", e)

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

            email_id = hashlib.sha256(
                text[:MAX_DESCRIPTION_LENGTH].encode()
            ).hexdigest()[:12]

        parsed["email_id"] = email_id
        parsed["parsed_at"] = datetime.now().isoformat()
        parsed["text_preview"] = text[:MAX_TEXT_PREVIEW_LENGTH].replace("\n", " ")

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
                            "sender_email": data.get("sender_email", ""),
                            "subject": data.get("subject", ""),
                            "date": data.get("email_date", ""),
                            "parsed_at": data.get("parsed_at", ""),
                            "text_preview": data.get("text_preview", "")[:150],
                            "total_priorities": data.get("total_priorities", 0),
                            "total_issue_keys": data.get("total_issue_keys", 0),
                            "total_themes": data.get("total_themes", 0),
                        }
                    )
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to read executive email cache: %s", e)
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

    async def _handle_sync_anstrat_ownership(self, **kwargs) -> dict:
        """Sync ANSTRAT issue catalog from Jira (passive model, no assignee ownership)."""
        try:
            perf_dir = self._get_perf_dir()
            ownership = await asyncio.to_thread(sync_anstrat_ownership, perf_dir)
            issue_count = len(ownership.get("issues", {}))
            return {
                "success": True,
                "issues": issue_count,
                "last_synced": ownership.get("last_synced"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_anstrat_ownership(self, **kwargs) -> dict:
        """Return the cached ANSTRAT ownership map."""
        try:
            perf_dir = self._get_perf_dir()
            ownership = load_anstrat_ownership(perf_dir)
            return {"success": True, "data": ownership}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_infer_strategy_relationships(self, **kwargs) -> dict:
        """Use LLM to infer non-obvious email-to-ANSTRAT connections."""
        try:
            from services.stats.strategy import infer_relationships_with_llm

            perf_dir = self._get_perf_dir()
            emails_dir = self._get_executive_emails_dir()
            ownership = load_anstrat_ownership(perf_dir)

            cache_file = perf_dir / "jira_hierarchy_cache.json"
            hierarchy_cache: dict = {}
            if cache_file.exists():
                try:
                    with open(cache_file, encoding="utf-8") as fh:
                        hierarchy_cache = json.load(fh)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load hierarchy cache: %s", e)
                    pass

            inferred = await asyncio.to_thread(
                infer_relationships_with_llm,
                emails_dir,
                ownership,
                hierarchy_cache,
            )
            return {"success": True, "relationships": inferred}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_sync_sender_sources(self, **kwargs) -> dict:
        """Sync Jira activity and Google Drive docs for target senders.

        Fetches recent Jira issues (last 90 days) and strategy-related
        Google Drive documents for the executive senders, caching results
        to disk for the relationship builder.

        Runs blocking I/O in a thread to avoid starving the watchdog.
        """
        try:
            perf_dir = self._get_perf_dir()

            jira_result = await asyncio.to_thread(sync_sender_jira_activity, perf_dir)
            jira_count = sum(
                a.get("issue_count", 0)
                for a in jira_result.get("sender_activity", {}).values()
            )

            gdrive_result = await asyncio.to_thread(sync_sender_gdrive_docs, perf_dir)
            doc_count = len(gdrive_result.get("documents", []))

            await asyncio.to_thread(self._update_summary)

            return {
                "success": True,
                "jira_issues": jira_count,
                "jira_senders": len(jira_result.get("sender_activity", {})),
                "gdrive_docs": doc_count,
                "last_synced": jira_result.get("last_synced"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_sender_sources(self, **kwargs) -> dict:
        """Return cached Jira activity and GDrive doc data for senders."""
        try:
            perf_dir = self._get_perf_dir()
            jira_activity = load_sender_jira_activity(perf_dir)
            gdrive_docs = load_sender_gdrive_docs(perf_dir)
            return {
                "success": True,
                "jira_activity": jira_activity,
                "gdrive_docs": gdrive_docs,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

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
            logger.error("Gmail search failed: %s", e)
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
            logger.error("Gmail read failed: %s", e)
            return {"success": False, "error": str(e)}

    async def _handle_backfill_executive_emails(self, **kwargs) -> dict:
        """Backfill executive emails for the entire current quarter."""
        now = datetime.now()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        quarter_starts = QUARTER_STARTS
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
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read existing email cache file: %s", e)
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
                            "maxResults": GMAIL_MAX_RESULTS,
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

                        subject = header_map.get("Subject", "")
                        if is_calendar_event(subject):
                            logger.debug(
                                "Backfill: skipping calendar event from %s: %s",
                                sender,
                                subject[:80],
                            )
                            skipped += 1
                            continue

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
                        parsed["text_preview"] = body[:MAX_TEXT_PREVIEW_LENGTH].replace(
                            "\n", " "
                        )

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
                    logger.error("Backfill failed for %s: %s", sender, e)
                    sender_results.append(
                        {
                            "sender": sender,
                            "error": str(e),
                        }
                    )

                time.sleep(1)

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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(
                        "Failed to load hierarchy cache for day detail: %s", e
                    )
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
            logger.error("Failed to read day detail for %s: %s", date_str, e)
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
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(
                        "Failed to read daily file for competency evidence: %s", e
                    )
                    continue

        all_competencies = list(COMPETENCY_DEFS.keys())
        target_per_competency = TARGET_POINTS_PER_COMPETENCY

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
            if pct < GAP_PERCENTAGE_THRESHOLD:
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
            logger.error("Failed to load %s: %s", filepath, e)
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
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read old scoring config for migration: %s", e)
            return

        if "scope_multipliers" in old_cfg:
            return

        logger.info("Scoring redesign migration: upgrading scoring_config.json")
        try:
            SCORING_CONFIG_FILE.unlink()
            logger.info("Deleted old scoring_config.json")
        except OSError as e:
            logger.warning("Failed to delete old config: %s", e)

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
                success = classifier.initialize(COMPETENCY_DEFS, level)
                if success:
                    self._collector.npu_classifier = classifier
                    logger.info("NPU classifier initialized successfully")
                else:
                    logger.info("NPU classifier failed to initialize, disabled")
            except Exception as e:
                logger.info("NPU classifier unavailable: %s", e)

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

        collection_stale = False
        if self._last_collection_time > 0:
            hours_since = (time.time() - self._last_collection_time) / SECONDS_PER_HOUR
            collection_stale = hours_since > 26

        checks = {
            "running": self.is_running,
            "config_dir_exists": AA_CONFIG_DIR.exists(),
            "collection_recent": not collection_stale,
            "no_consecutive_failures": self._consecutive_collection_failures < 3,
        }

        healthy = all(checks.values())

        messages = []
        if not healthy:
            if collection_stale:
                messages.append(
                    f"Last collection was {hours_since:.1f}h ago "
                    f"(date: {self._last_collection_date})"
                )
            if self._consecutive_collection_failures >= 3:
                messages.append(
                    f"{self._consecutive_collection_failures} consecutive "
                    f"collection failures"
                )
            if self._last_collection_errors:
                messages.append(
                    f"Last errors: {', '.join(self._last_collection_errors.keys())}"
                )

        return {
            "healthy": healthy,
            "checks": checks,
            "message": (
                "Stats daemon is healthy"
                if healthy
                else f"Stats daemon has issues: {'; '.join(messages)}"
            ),
            "timestamp": self._last_health_check,
            "last_collection": {
                "time": self._last_collection_time,
                "date": self._last_collection_date,
                "errors": self._last_collection_errors,
                "consecutive_failures": self._consecutive_collection_failures,
            },
        }


if __name__ == "__main__":
    StatsDaemon.main()
