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
from pathlib import Path
from typing import Any

from server.paths import (
    AA_CONFIG_DIR,
    AGENT_STATS_FILE,
    INFERENCE_STATS_FILE,
    SKILL_EXECUTION_FILE,
    get_performance_summary_path,
)
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.stats.anstrat_sync import (
    load_anstrat_ownership,
    load_sender_gdrive_docs,
    load_sender_jira_activity,
    sync_sender_gdrive_docs,
    sync_sender_jira_activity,
)
from services.stats.collector import DataCollector
from services.stats.daemon_ai import AIHandlersMixin
from services.stats.daemon_hierarchy import MAX_TEXT_PREVIEW_LENGTH, HierarchyMixin
from services.stats.daemon_peers import PeerCollectorMixin
from services.stats.email_parser import (
    get_executive_emails_dir,
    get_executive_senders,
    is_calendar_event,
    parse_email_text,
)
from services.stats.performance_scoring import (
    compute_competency_percentages,
    compute_daily_points,
    dedup_events_by_jira_key,
    is_personal_repo_event,
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
GMAIL_MAX_RESULTS = 100

logger = logging.getLogger(__name__)


class StatsDaemon(
    PeerCollectorMixin, AIHandlersMixin, HierarchyMixin, DaemonDBusBase, BaseDaemon
):
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

    # ==================== AI-Powered Analysis Handlers ====================

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
