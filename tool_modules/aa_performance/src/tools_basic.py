"""Performance MCP Tools - Tools for tracking PSE competency performance.

Provides:
- performance_status: Current quarter progress and scores
- performance_refresh: Collect data for today or specific date
- performance_backfill: Find and fill missing days
- performance_report: Generate performance report
- performance_log_activity: Manual entry for presentations, mentoring, etc.
- performance_history: Daily scores history
- performance_gaps: Competencies needing attention
- performance_highlights: Notable achievements
- performance_questions: List quarterly questions
- performance_question_edit: Edit a question
- performance_question_add: Add custom question
- performance_question_note: Add manual note
- performance_evaluate: Gather evidence and build evaluation prompts
- performance_save_evaluation: Save LLM-generated evaluation for a question
- performance_export: Export quarterly report
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from mcp.types import TextContent

from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_tools(server: "FastMCP") -> int:  # noqa: C901
    """Register performance tracking tools with the MCP server."""
    registry = ToolRegistry(server)

    # Import local modules
    from tool_modules.aa_performance.src.competency_mapper import CompetencyMapper
    from tool_modules.aa_performance.src.question_manager import QuestionManager
    from tool_modules.aa_performance.src.scoring_engine import (
        ScoringEngine,
        get_performance_dir,
        get_quarter_info,
    )

    @registry.tool()
    async def performance_status(quarter: str = "") -> list[TextContent]:
        """
        Show current quarter performance status.

        Displays overall progress, competency scores, gaps, and highlights.

        Args:
            quarter: Optional quarter string like "Q1 2026". Defaults to current quarter.

        Returns:
            Performance status summary with scores and progress.
        """
        # Parse quarter or use current
        if quarter:
            try:
                q_num = int(quarter[1])
                year = int(quarter.split()[1])
            except (IndexError, ValueError):
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Invalid quarter format: {quarter}. Use 'Q1 2026' format.",
                    )
                ]
        else:
            year, q_num, _, _, _ = get_quarter_info()

        engine = ScoringEngine(year=year, quarter=q_num)
        summary = engine.calculate_summary()

        # Build output
        lines = [f"## 📊 Performance Status - Q{q_num} {year}\n"]

        day_of_quarter = summary.get("day_of_quarter", 0)
        overall_pct = summary.get("overall_percentage", 0)

        lines.append(f"**Day {day_of_quarter} of 90** | Overall: **{overall_pct}%**")
        lines.append(
            f"**Period:** {summary.get('quarter_start', '')} to {summary.get('quarter_end', '')}"
        )
        lines.append(f"**Total Events:** {summary.get('total_events', 0)}")
        lines.append("")

        # Competency scores
        lines.append("### 📈 Competency Progress\n")
        comp_pcts = summary.get("cumulative_percentage", {})
        comp_pts = summary.get("cumulative_points", {})

        # Sort by percentage
        sorted_comps = sorted(comp_pcts.items(), key=lambda x: x[1], reverse=True)
        for comp_id, pct in sorted_comps:
            pts = comp_pts.get(comp_id, 0)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            icon = "✓" if pct >= 80 else "⚠" if pct < 50 else ""
            lines.append(f"- **{comp_id}**: {bar} {pct}% ({pts} pts) {icon}")

        # Gaps
        gaps = summary.get("gaps", [])
        if gaps:
            lines.append("\n### ⚠️ Gaps (below 50%)\n")
            for gap in gaps:
                pct = comp_pcts.get(gap, 0)
                lines.append(f"- {gap}: {pct}%")

        # Highlights
        highlights = summary.get("highlights", [])
        if highlights:
            lines.append("\n### ✨ Recent Highlights\n")
            for h in highlights[:5]:
                lines.append(f"- {h}")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_refresh(target_date: str = "") -> list[TextContent]:
        """
        Collect performance data for a specific date.

        Fetches data from Jira, GitLab, GitHub, and local git repositories,
        maps to competencies, and saves to daily file.

        Args:
            target_date: Date to collect data for (YYYY-MM-DD). Defaults to today.

        Returns:
            Summary of collected data.
        """
        # Parse date
        if target_date:
            try:
                dt = date.fromisoformat(target_date)
            except ValueError:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Invalid date format: {target_date}. Use YYYY-MM-DD.",
                    )
                ]
        else:
            dt = date.today()

        year, quarter, _, _, day_of_quarter = get_quarter_info(dt)

        lines = [f"## 🔄 Collecting Performance Data for {dt.isoformat()}\n"]
        lines.append(f"**Quarter:** Q{quarter} {year} (Day {day_of_quarter})")
        lines.append("")

        # TODO: Integrate with actual data fetchers
        # For now, return placeholder indicating manual collection needed
        lines.append("### Data Collection")
        lines.append("")
        lines.append("To collect data, run the `collect_daily` skill which will:")
        lines.append("1. Query Jira for resolved/created issues")
        lines.append("2. Query GitLab for merged MRs and reviews")
        lines.append("3. Query GitHub for merged PRs")
        lines.append("4. Scan local git repos for commits")
        lines.append("")
        lines.append("```")
        lines.append(
            'skill_run("performance_collect_daily", \'{{"date": "{dt.isoformat()}"}}\')'
        )
        lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_backfill() -> list[TextContent]:
        """
        Find and backfill missing days in the current quarter.

        Scans for weekdays without data and reports what needs to be collected.

        Returns:
            List of missing dates and instructions to backfill.
        """
        year, quarter, start_date, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)

        # Find missing weekdays
        today = date.today()
        missing = []
        current = start_date

        existing_files = {f.stem for f in engine.daily_dir.glob("*.json")}

        while current <= today:
            if current.weekday() < 5:  # Weekday
                if current.isoformat() not in existing_files:
                    missing.append(current)
            current += timedelta(days=1)

        lines = [f"## 🔍 Backfill Check - Q{quarter} {year}\n"]

        if not missing:
            lines.append("✅ No missing days found! All weekdays have data.")
        else:
            lines.append(f"Found **{len(missing)}** missing weekday(s):\n")
            for dt in missing[:20]:  # Show first 20
                lines.append(f"- {dt.isoformat()} ({dt.strftime('%A')})")

            if len(missing) > 20:
                lines.append(f"- ... and {len(missing) - 20} more")

            lines.append("")
            lines.append("To backfill, run:")
            lines.append("```")
            lines.append('skill_run("performance_backfill_missing")')
            lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_log_activity(
        category: str,
        description: str,
        points: int = 0,
    ) -> list[TextContent]:
        """
        Log a manual activity (presentation, mentoring, etc.).

        Use this for activities that can't be automatically detected.

        Args:
            category: Activity category (speaking, mentorship, presentation, demo, blog, other)
            description: Description of the activity
            points: Optional points override (auto-calculated if 0)

        Returns:
            Confirmation of logged activity.

        Examples:
            performance_log_activity("presentation", "Demo to PM team on new billing feature")
            performance_log_activity("mentorship", "1:1 mentoring session with junior dev")
            performance_log_activity("blog", "Published blog post on AI workflow automation")
        """
        valid_categories = [
            "speaking",
            "mentorship",
            "presentation",
            "demo",
            "blog",
            "other",
        ]
        if category.lower() not in valid_categories:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Invalid category: {category}\n\nValid categories: {', '.join(valid_categories)}",
                )
            ]

        # Map category to competency and default points
        category_mapping = {
            "speaking": ("speaking_publicity", 10),
            "presentation": ("speaking_publicity", 10),
            "demo": ("speaking_publicity", 4),
            "blog": ("speaking_publicity", 8),
            "mentorship": ("mentorship", 5),
            "other": ("technical_contribution", 2),
        }

        comp_id, default_points = category_mapping.get(category.lower(), ("other", 2))
        actual_points = points if points > 0 else default_points

        # Create event
        event = {
            "id": f"manual:{category}:{datetime.now().isoformat()}",
            "source": "manual",
            "type": category.lower(),
            "title": description,
            "timestamp": datetime.now().isoformat(),
            "points": {comp_id: actual_points},
        }

        # Save to today's file
        year, quarter, _, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)

        # Load or create today's data
        today = date.today()
        daily_file = engine.daily_dir / f"{today.isoformat()}.json"

        if daily_file.exists():
            with open(daily_file, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {
                "date": today.isoformat(),
                "day_of_quarter": get_quarter_info(today)[4],
                "events": [],
                "daily_points": {},
                "daily_total": 0,
            }

        # Add event
        data["events"].append(event)
        data["daily_points"][comp_id] = (
            data["daily_points"].get(comp_id, 0) + actual_points
        )
        data["daily_total"] = sum(data["daily_points"].values())

        with open(daily_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Tag to questions
        question_mgr = QuestionManager(engine.perf_dir)
        tagged = question_mgr.tag_event_to_questions(event)

        lines = [
            "✅ Logged manual activity",
            "",
            f"**Category:** {category}",
            f"**Description:** {description}",
            f"**Competency:** {comp_id}",
            f"**Points:** {actual_points}",
        ]

        if tagged:
            lines.append(f"**Tagged to questions:** {', '.join(tagged)}")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_history(days: int = 7) -> list[TextContent]:
        """
        Show daily performance history.

        Args:
            days: Number of days to show (default 7)

        Returns:
            Daily scores for the specified period.
        """
        year, quarter, _, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)

        lines = [f"## 📅 Performance History (Last {days} Days)\n"]

        # Get recent daily files
        daily_files = sorted(engine.daily_dir.glob("*.json"), reverse=True)[:days]

        if not daily_files:
            lines.append("No data available yet.")
            return [TextContent(type="text", text="\n".join(lines))]

        total_points = 0
        total_events = 0

        for daily_file in daily_files:
            try:
                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)

                dt = data.get("date", daily_file.stem)
                day_total = data.get("daily_total", 0)
                event_count = len(data.get("events", []))

                total_points += day_total
                total_events += event_count

                bar = "█" * min(day_total // 2, 20)
                lines.append(f"**{dt}**: {bar} {day_total} pts ({event_count} events)")

            except Exception:
                lines.append(f"**{daily_file.stem}**: ❌ Error loading")

        lines.append("")
        lines.append(f"**Total:** {total_points} points from {total_events} events")
        lines.append(
            f"**Average:** {total_points // len(daily_files) if daily_files else 0} pts/day"
        )

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_gaps() -> list[TextContent]:
        """
        Show competencies that need attention.

        Identifies competencies below 50% of target and suggests actions.

        Returns:
            List of gaps with suggestions.
        """
        year, quarter, _, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)
        mapper = CompetencyMapper()

        summary = engine.calculate_summary()
        comp_pcts = summary.get("cumulative_percentage", {})

        lines = ["## ⚠️ Competency Gaps\n"]

        # Find gaps (below 50%)
        gaps = [(comp_id, pct) for comp_id, pct in comp_pcts.items() if pct < 50]
        gaps.sort(key=lambda x: x[1])

        if not gaps:
            lines.append(
                "✅ No significant gaps! All competencies are at 50% or above."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        for comp_id, pct in gaps:
            comp_info = mapper.get_competency_info(comp_id)
            name = comp_info.get("name", comp_id) if comp_info else comp_id
            keywords = comp_info.get("keywords", []) if comp_info else []

            lines.append(f"### {name}: {pct}%")
            lines.append("")

            if keywords:
                lines.append(f"**Focus areas:** {', '.join(keywords[:5])}")

            # Suggest actions based on competency
            suggestions = _get_gap_suggestions(comp_id)
            if suggestions:
                lines.append("**Suggestions:**")
                for s in suggestions:
                    lines.append(f"- {s}")

            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_highlights(period: str = "week") -> list[TextContent]:
        """
        Show notable achievements for a period.

        Args:
            period: Time period - "week", "month", or "quarter"

        Returns:
            List of highlights.
        """
        year, quarter, start_date, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)

        # Determine date range
        today = date.today()
        if period == "week":
            since = today - timedelta(days=7)
        elif period == "month":
            since = today - timedelta(days=30)
        else:
            since = start_date

        lines = [f"## ✨ Highlights ({period.title()})\n"]

        # Collect high-value events
        highlights = []
        for daily_file in engine.daily_dir.glob("*.json"):
            try:
                file_date = date.fromisoformat(daily_file.stem)
                if file_date < since:
                    continue

                with open(daily_file, encoding="utf-8") as f:
                    data = json.load(f)

                for event in data.get("events", []):
                    points = event.get("points", {})
                    total = sum(points.values()) if isinstance(points, dict) else 0
                    if total >= 3:  # High-value threshold
                        highlights.append(
                            {
                                "date": data.get("date"),
                                "title": event.get("title", ""),
                                "source": event.get("source", ""),
                                "points": total,
                                "competencies": (
                                    list(points.keys())
                                    if isinstance(points, dict)
                                    else []
                                ),
                            }
                        )

            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)

        # Sort by points
        highlights.sort(key=lambda x: x["points"], reverse=True)

        if not highlights:
            lines.append("No significant highlights found for this period.")
            return [TextContent(type="text", text="\n".join(lines))]

        for h in highlights[:15]:
            comps = ", ".join(h["competencies"][:2])
            lines.append(f"- **{h['title']}** ({h['source']}, {h['points']} pts)")
            lines.append(f"  _{h['date']} - {comps}_")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_questions() -> list[TextContent]:
        """
        List quarterly questions with evidence counts.

        Returns:
            List of questions with status.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        lines = [f"## 📋 Quarterly Questions - Q{quarter} {year}\n"]

        for q in question_mgr.get_questions():
            q_id = q.get("id", "")
            text = q.get("text", "")
            evidence_count = len(q.get("auto_evidence", []))
            notes_count = len(q.get("manual_notes", []))
            has_summary = q.get("llm_summary") is not None
            last_eval = q.get("last_evaluated", "")

            status = "🤖 Evaluated" if has_summary else "⏳ Not evaluated"
            if last_eval:
                status += f" ({last_eval[:10]})"

            lines.append(f"### {q_id}")
            lines.append(f"**{text}**")
            if q.get("subtext"):
                lines.append(f"_{q.get('subtext')}_")
            lines.append(
                f"📊 {evidence_count} evidence | 📝 {notes_count} notes | {status}"
            )
            lines.append("")

        lines.append("**Actions:**")
        lines.append("- `performance_question_note(id, note)` - Add a manual note")
        lines.append("- `performance_evaluate(id)` - Run AI evaluation")
        lines.append(
            "- `performance_question_add(text, categories)` - Add custom question"
        )

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_question_note(
        question_id: str, note: str
    ) -> list[TextContent]:
        """
        Add a manual note to a quarterly question.

        Args:
            question_id: Question ID (e.g., "accomplishments", "priorities")
            note: Note text to add

        Returns:
            Confirmation.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        if question_mgr.add_note(question_id, note):
            return [
                TextContent(
                    type="text", text=f"✅ Added note to question '{question_id}'"
                )
            ]
        else:
            return [
                TextContent(type="text", text=f"❌ Question not found: {question_id}")
            ]

    @registry.tool()
    async def performance_question_add(
        text: str,
        question_id: str = "",
        subtext: str = "",
        categories: str = "all",
    ) -> list[TextContent]:
        """
        Add a custom quarterly question.

        Args:
            text: Question text
            question_id: Optional ID (auto-generated if empty)
            subtext: Optional subtext/hint
            categories: Comma-separated evidence categories

        Returns:
            Confirmation with question details.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        if not question_id:
            question_id = f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        cat_list = [c.strip() for c in categories.split(",")]

        question_mgr.add_question(
            question_id=question_id,
            text=text,
            subtext=subtext if subtext else None,
            evidence_categories=cat_list,
        )

        return [
            TextContent(
                type="text",
                text=(
                    f"✅ Added custom question\n\n**ID:** {question_id}\n"
                    f"**Text:** {text}\n**Categories:** {categories}"
                ),
            )
        ]

    @registry.tool()
    async def performance_question_edit(
        question_id: str,
        text: str = "",
        subtext: str = "",
    ) -> list[TextContent]:
        """
        Edit an existing quarterly question.

        Args:
            question_id: Question ID to edit
            text: New question text (empty to keep current)
            subtext: New subtext (empty to keep current)

        Returns:
            Confirmation.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        result = question_mgr.edit_question(
            question_id=question_id,
            text=text if text else None,
            subtext=subtext if subtext else None,
        )

        if result:
            return [
                TextContent(type="text", text=f"✅ Updated question '{question_id}'")
            ]
        else:
            return [
                TextContent(type="text", text=f"❌ Question not found: {question_id}")
            ]

    @registry.tool()
    async def performance_evaluate(question_id: str = "") -> list[TextContent]:
        """
        Gather evidence and build evaluation prompts for quarterly questions.

        Initializes questions if needed, tags evidence, and returns prompts
        for the LLM to evaluate. After generating a response, save it with
        performance_save_evaluation(question_id, summary).

        Args:
            question_id: Specific question to evaluate (empty for all)

        Returns:
            Evidence and prompts for each question.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        daily_dir = perf_dir / "daily"
        question_mgr = QuestionManager(perf_dir)

        # Ensure evidence is tagged
        questions = question_mgr.get_questions()
        total_evidence = sum(len(q.get("auto_evidence", [])) for q in questions)
        if total_evidence == 0 and daily_dir.exists():
            for daily_file in sorted(daily_dir.glob("*.json")):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                    for event in data.get("events", []):
                        question_mgr.tag_event_to_questions(event)
                except Exception as e:
                    logger.debug("Could not tag events from %s: %s", daily_file, e)
            questions = question_mgr.get_questions()

        if question_id:
            questions = [q for q in questions if q.get("id") == question_id]

        if not questions:
            return [TextContent(type="text", text="No matching questions found.")]

        # Load all events for evidence lookup
        all_events: dict[str, dict] = {}
        if daily_dir.exists():
            for daily_file in daily_dir.glob("*.json"):
                try:
                    with open(daily_file, encoding="utf-8") as f:
                        data = json.load(f)
                    for event in data.get("events", []):
                        all_events[event.get("id", "")] = event
                except Exception as e:
                    logger.debug("Could not load events from %s: %s", daily_file, e)

        # Load competency summary
        summary_file = perf_dir / "summary.json"
        comp_summary: dict[str, int] = {}
        if summary_file.exists():
            try:
                with open(summary_file, encoding="utf-8") as f:
                    summary = json.load(f)
                comp_summary = summary.get("cumulative_percentage", {})
            except Exception as e:
                logger.debug("Could not load competency summary: %s", e)

        comp_text = "\n".join(f"- {k}: {v}%" for k, v in comp_summary.items())

        lines = [f"## Quarterly Question Evaluation - Q{quarter} {year}\n"]

        for q in questions:
            evidence_ids = q.get("auto_evidence", [])
            evidence_events = [
                all_events[eid] for eid in evidence_ids if eid in all_events
            ]
            evidence_events.sort(
                key=lambda e: sum(e.get("points", {}).values()), reverse=True
            )
            top = evidence_events[:20]

            ev_lines = []
            for e in top:
                pts = sum(e.get("points", {}).values())
                comps = ", ".join(f"{k}:{v}" for k, v in e.get("points", {}).items())
                ev_lines.append(
                    f"- [{e.get('source', '')}] {e.get('title', '')} ({pts} pts: {comps})"
                )
            ev_text = "\n".join(ev_lines) if ev_lines else "No evidence"

            notes = q.get("manual_notes", [])
            notes_text = (
                "\n".join(f"- {n.get('text', '')}" for n in notes) if notes else "None"
            )

            lines.append(f"### {q.get('text', '')}")
            if q.get("subtext"):
                lines.append(f"*{q['subtext']}*")
            lines.append(f"\n**Evidence** (top {len(top)} of {len(evidence_events)}):")
            lines.append(ev_text)
            lines.append(f"\n**Manual Notes:** {notes_text}")
            lines.append(f"\n**Competency Scores:**\n{comp_text}")
            lines.append(
                "\nWrite a 2-3 paragraph first-person response highlighting "
                "significant accomplishments with specific examples and metrics."
            )
            lines.append(
                f'\nSave with: `performance_save_evaluation("{q.get("id")}", "<response>")`'
            )
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_save_evaluation(
        question_id: str, summary: str
    ) -> list[TextContent]:
        """
        Save an LLM-generated evaluation for a quarterly question.

        Args:
            question_id: The question ID (e.g. "accomplishments")
            summary: The evaluation text to save

        Returns:
            Confirmation of saved evaluation.
        """
        if not question_id or not summary:
            return [
                TextContent(
                    type="text",
                    text="Both question_id and summary are required.",
                )
            ]

        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        if question_mgr.set_evaluation(question_id, summary):
            return [
                TextContent(
                    type="text",
                    text=f"Saved evaluation for '{question_id}' ({len(summary)} chars). "
                    f"Refresh the QC tab to see the result.",
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"Question '{question_id}' not found.",
                )
            ]

    @registry.tool()
    async def performance_export(format: str = "markdown") -> list[TextContent]:
        """
        Export quarterly performance report.

        Args:
            format: Export format - "markdown", "json", or "html"

        Returns:
            Report content or file path.
        """
        year, quarter, _, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)
        perf_dir = get_performance_dir(year, quarter)
        question_mgr = QuestionManager(perf_dir)

        summary = engine.calculate_summary()

        if format == "json":
            # Return JSON summary
            export_data = {
                **summary,
                "questions": question_mgr.get_questions_summary(),
            }
            return [TextContent(type="text", text=json.dumps(export_data, indent=2))]

        # Generate markdown report
        lines = [
            f"# Quarterly Performance Report - Q{quarter} {year}",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Period:** {summary.get('quarter_start')} to {summary.get('quarter_end')}",
            f"**Day of Quarter:** {summary.get('day_of_quarter')} of 90",
            "",
            "## Summary",
            "",
            f"**Overall Progress:** {summary.get('overall_percentage', 0)}%",
            f"**Total Events:** {summary.get('total_events', 0)}",
            "",
            "## Competency Scores",
            "",
        ]

        comp_pcts = summary.get("cumulative_percentage", {})
        for comp_id, pct in sorted(comp_pcts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- **{comp_id}:** {pct}%")

        lines.append("")
        lines.append("## Quarterly Questions")
        lines.append("")

        for q in question_mgr.get_questions():
            lines.append(f"### {q.get('text', '')}")
            if q.get("subtext"):
                lines.append(f"_{q.get('subtext')}_")
            lines.append("")

            if q.get("llm_summary"):
                lines.append(q.get("llm_summary"))
            else:
                lines.append("_Not yet evaluated_")

            notes = q.get("manual_notes", [])
            if notes:
                lines.append("")
                lines.append("**Manual Notes:**")
                for n in notes:
                    lines.append(f"- {n.get('text', '')}")

            lines.append("")

        # Highlights
        highlights = summary.get("highlights", [])
        if highlights:
            lines.append("## Highlights")
            lines.append("")
            for h in highlights:
                lines.append(f"- {h}")
            lines.append("")

        # Gaps
        gaps = summary.get("gaps", [])
        if gaps:
            lines.append("## Areas for Improvement")
            lines.append("")
            for g in gaps:
                pct = comp_pcts.get(g, 0)
                lines.append(f"- **{g}:** {pct}%")

        report_text = "\n".join(lines)

        # Save to file
        report_file = perf_dir / f"report_q{quarter}_{year}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_text)

        return [
            TextContent(
                type="text",
                text=f"📄 Report exported to: {report_file}\n\n---\n\n{report_text}",
            )
        ]

    @registry.tool()
    async def performance_peer_status() -> list[TextContent]:
        """
        Show peer benchmark data across engineering levels.

        Displays aggregated peer comparison data: overall scores, competency
        averages, and event volumes grouped by Senior, Principal, Sr Principal,
        and Distinguished levels.

        Returns:
            Formatted peer benchmarks summary.
        """
        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"

        if not benchmarks_file.exists():
            return [
                TextContent(
                    type="text",
                    text=(
                        "No peer benchmarks found. Run peer collection first:\n"
                        "- From VSCode: QC tab > Peers > Collect Peers\n"
                        "- Via D-Bus: stats_collectPeers()"
                    ),
                )
            ]

        with open(benchmarks_file, encoding="utf-8") as f:
            benchmarks = json.load(f)

        level_labels = {
            "se": "Senior Engineer",
            "pse": "Principal Engineer",
            "spse": "Sr Principal Engineer",
            "de": "Distinguished Engineer",
        }

        lines = [
            f"# Peer Benchmarks - Q{quarter} {year}",
            f"_Last updated: {benchmarks.get('last_updated', 'unknown')}_",
            "",
        ]

        for level_key in ["se", "pse", "spse", "de"]:
            level_data = benchmarks.get("levels", {}).get(level_key)
            if not level_data:
                continue

            label = level_labels.get(level_key, level_key)
            engineers = ", ".join(level_data.get("engineers", []))
            overall = level_data.get("avg_overall_pct", 0)

            lines.append(f"## {label} ({overall}% overall)")
            lines.append(f"_Engineers: {engineers}_")
            lines.append(f"_Avg daily events: {level_data.get('avg_daily_events', 0)}_")
            lines.append("")

            comp_pcts = level_data.get("avg_competency_pct", {})
            for comp_id, pct in sorted(
                comp_pcts.items(), key=lambda x: x[1], reverse=True
            ):
                name = comp_id.replace("_", " ").title()
                lines.append(f"- {name}: {pct}%")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_peer_compare(level: str = "") -> list[TextContent]:
        """
        Compare your competency scores against a specific peer level or all levels.

        Args:
            level: Engineering level to compare against (se, pse, spse, de).
                   Leave empty to compare against all levels.

        Returns:
            Side-by-side comparison of your scores vs peer averages.
        """
        year, quarter, _, _, _ = get_quarter_info()
        engine = ScoringEngine(year=year, quarter=quarter)
        user_summary = engine.calculate_summary()

        perf_dir = get_performance_dir(year, quarter)
        benchmarks_file = perf_dir / "peers" / "benchmarks.json"

        if not benchmarks_file.exists():
            return [
                TextContent(
                    type="text",
                    text="No peer benchmarks found. Run peer collection first.",
                )
            ]

        with open(benchmarks_file, encoding="utf-8") as f:
            benchmarks = json.load(f)

        level_labels = {
            "se": "Senior",
            "pse": "Principal",
            "spse": "Sr Principal",
            "de": "Distinguished",
        }

        levels_to_compare = (
            [level]
            if level and level in benchmarks.get("levels", {})
            else [
                lk
                for lk in ["se", "pse", "spse", "de"]
                if lk in benchmarks.get("levels", {})
            ]
        )

        user_pcts = user_summary.get("cumulative_percentage", {})
        all_comp_ids = sorted(
            set(user_pcts.keys())
            | {
                c
                for lk in levels_to_compare
                for c in benchmarks.get("levels", {})
                .get(lk, {})
                .get("avg_competency_pct", {})
                .keys()
            }
        )

        lines = [
            f"# Peer Comparison - Q{quarter} {year}",
            f"**Your Overall:** {user_summary.get('overall_percentage', 0)}%",
            "",
        ]

        header = f"| {'Competency':<30} | {'You':>5} |"
        sep = f"| {'-'*30} | {'---':>5} |"
        for lk in levels_to_compare:
            label = level_labels.get(lk, lk)
            header += f" {label:>12} |"
            sep += f" {'---':>12} |"

        lines.append(header)
        lines.append(sep)

        for comp_id in all_comp_ids:
            name = comp_id.replace("_", " ").title()
            if len(name) > 30:
                name = name[:28] + ".."
            user_pct = user_pcts.get(comp_id, 0)
            row = f"| {name:<30} | {user_pct:>4}% |"
            for lk in levels_to_compare:
                peer_pct = (
                    benchmarks["levels"][lk]
                    .get("avg_competency_pct", {})
                    .get(comp_id, 0)
                )
                diff = user_pct - peer_pct
                indicator = "  " if abs(diff) < 5 else (" +" if diff > 0 else " -")
                row += f" {peer_pct:>4}%{indicator:>6} |"
            lines.append(row)

        lines.append("")
        lines.append("_Legend: + = you're above peer avg, - = you're below_")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def performance_peer_narrative() -> list[TextContent]:
        """
        Generate an AI narrative comparing your performance to peer benchmarks.

        Uses local LLM to produce a 3-5 sentence summary highlighting strengths,
        gaps, and which engineering level your profile most closely matches.
        """
        from services.stats.ai_handlers import generate_peer_narrative

        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        summary_file = perf_dir / "performance" / "summary.json"
        if not summary_file.exists():
            return [TextContent(type="text", text="No performance summary found.")]
        with open(summary_file, encoding="utf-8") as f:
            summary = json.load(f)
        user_pct = summary.get("cumulative_percentage", {})
        user_overall = summary.get("overall_percentage", 0)

        benchmarks_file = perf_dir / "peers" / "benchmarks.json"
        if not benchmarks_file.exists():
            return [
                TextContent(
                    type="text",
                    text="No peer benchmarks available. Run `collect_peers` first.",
                )
            ]
        with open(benchmarks_file, encoding="utf-8") as f:
            benchmarks = json.load(f)

        peer_levels = benchmarks.get("levels", {})
        result = generate_peer_narrative(user_pct, user_overall, peer_levels)

        if result.get("success"):
            source = result.get("source", "unknown")
            return [
                TextContent(
                    type="text",
                    text=f"**Peer Narrative** ({source}):\n\n{result['narrative']}",
                )
            ]
        return [TextContent(type="text", text="Failed to generate narrative.")]

    @registry.tool()
    async def performance_promotion_readiness(
        current_level: str = "",
    ) -> list[TextContent]:
        """
        Assess your readiness for promotion to the next engineering level.

        Compares your competency profile against the next level's peer averages
        and generates a structured assessment.

        Args:
            current_level: Your current level (se, pse, spse). Auto-detected if empty.
        """
        from services.stats.ai_handlers import generate_promotion_readiness

        year, quarter, _, _, _ = get_quarter_info()
        perf_dir = get_performance_dir(year, quarter)
        summary_file = perf_dir / "performance" / "summary.json"
        if not summary_file.exists():
            return [TextContent(type="text", text="No performance summary found.")]
        with open(summary_file, encoding="utf-8") as f:
            summary = json.load(f)
        user_pct = summary.get("cumulative_percentage", {})
        user_overall = summary.get("overall_percentage", 0)

        benchmarks_file = perf_dir / "peers" / "benchmarks.json"
        if not benchmarks_file.exists():
            return [TextContent(type="text", text="No peer benchmarks available.")]
        with open(benchmarks_file, encoding="utf-8") as f:
            benchmarks = json.load(f)

        peer_levels = benchmarks.get("levels", {})
        result = generate_promotion_readiness(
            user_pct, user_overall, peer_levels, current_level
        )

        if not result.get("success"):
            return [
                TextContent(
                    type="text",
                    text=result.get("error", "Cannot assess promotion readiness."),
                )
            ]

        lines = [
            f"## Promotion Readiness: {result['next_level_label']}",
            "",
            result.get("summary", ""),
            "",
            f"Meeting **{result['ready_count']}/{result['total_competencies']}** competency benchmarks.",
            "",
            "| Competency | You | Target | Delta | Status |",
            "|------------|-----|--------|-------|--------|",
        ]
        for a in result.get("assessments", []):
            icon = {"ready": "OK", "almost": "~", "gap": "GAP"}.get(a["status"], "?")
            lines.append(
                f"| {a['name']} | {a['user_pct']}% | {a['target_pct']}% | "
                f"{a['delta']:+d}% | {icon} |"
            )
        return [TextContent(type="text", text="\n".join(lines))]

    return registry.count


def _get_gap_suggestions(comp_id: str) -> list[str]:
    """Get suggestions for improving a competency gap."""
    suggestions = {
        "speaking_publicity": [
            "Schedule a demo for your team",
            "Write a blog post about recent work",
            "Present at a team meeting",
            "Log presentations with performance_log_activity",
        ],
        "mentorship": [
            "Offer to help onboard new team members",
            "Write detailed code review comments",
            "Create documentation for newcomers",
            "Log mentoring sessions with performance_log_activity",
        ],
        "collaboration": [
            "Review more MRs from teammates",
            "Comment on Jira issues you're not assigned to",
            "Pair program on complex tasks",
        ],
        "leadership": [
            "Take on cross-team initiatives",
            "Offer to lead technical discussions",
            "Watch and advise on others' issues",
        ],
        "creativity_innovation": [
            "Create a POC for a new idea",
            "Propose process improvements",
            "Work on automation/tooling",
        ],
        "planning_execution": [
            "Create proactive tech-debt issues",
            "Participate in sprint planning",
            "Document future improvements",
        ],
        "opportunity_recognition": [
            "Identify and propose new features",
            "Contribute to upstream projects",
            "Look for optimization opportunities",
        ],
        "portfolio_impact": [
            "Work on API/interface changes",
            "Contribute to app-interface",
            "Document architecture decisions",
        ],
        "continuous_improvement": [
            "Improve CI/CD pipelines",
            "Create automation tools",
            "Resolve tech-debt issues",
        ],
        "end_to_end_delivery": [
            "Own issues from start to finish",
            "Help with customer-reported issues",
            "Participate in releases",
        ],
        "technical_contribution": [
            "Take on larger/more complex tasks",
            "Work on Epic-level items",
            "Contribute to cross-team projects",
        ],
        "technical_knowledge": [
            "Contribute to multiple repos",
            "Write documentation",
            "Give thorough code reviews",
        ],
    }
    return suggestions.get(comp_id, ["Focus on activities related to this competency"])
