"""AI-powered analysis handler mixin for StatsDaemon."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta

from server.paths import get_performance_summary_path
from services.stats.quarter_utils import QUARTER_STARTS
from services.stats.scorer import get_merged_config
from tool_modules.aa_performance.src.question_manager import QuestionManager

logger = logging.getLogger(__name__)


class AIHandlersMixin:
    """Mixin providing AI-powered narrative, coaching, and analysis handlers."""

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
