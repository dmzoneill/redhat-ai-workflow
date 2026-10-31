"""Quarterly report export (JSON, Markdown, PDF) for the stats daemon.

Split out of ``services/stats/daemon.py``; ``StatsDaemon`` mixes
``ReportExportMixin`` in, so the ``export_report`` D-Bus method and its
``format`` argument are unchanged.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.stats.executive_emails import ExecutiveEmailMixin
from services.stats.handler_utils import (
    DATA_ERRORS,
    load_daily_files,
    now_local,
    quarter_of,
    read_json,
    write_json,
    write_text,
)
from services.stats.report_helpers import (
    generate_calendar_html,
    generate_competency_bars_html,
    generate_mindmap_svg,
    generate_sunburst_svg,
    render_pdf,
    score_color,
)

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "report_template.html"


@dataclass
class ReportContext:
    """Everything a report needs about the quarter being exported."""

    year: int
    quarter: int
    now: datetime
    perf_dir: Path
    summary: dict
    all_events: list[dict]

    @property
    def label(self) -> str:
        """``Q<n> <year>`` label."""
        return f"Q{self.quarter} {self.year}"

    def report_file(self, suffix: str) -> Path:
        """Path of the report file with the given extension."""
        return self.perf_dir / f"report_q{self.quarter}_{self.year}.{suffix}"


def load_all_events(daily_dir: Path) -> list[dict]:
    """Concatenate the events of every readable daily file."""
    events: list[dict] = []
    for _, data in load_daily_files(daily_dir):
        if data is not None:
            events.extend(data.get("events", []))
    return events


def build_markdown(ctx: ReportContext) -> str:
    """Render the Markdown quarterly report."""
    summary = ctx.summary
    lines = [
        f"# {ctx.label} Quarterly Connection Report",
        "",
        f"**Generated:** {ctx.now.strftime('%Y-%m-%d %H:%M')}",
        f"**Overall Score:** {summary.get('overall_percentage', 0)}%",
        f"**Total Events:** {len(ctx.all_events)}",
        "",
        "## Competency Progress",
        "",
    ]
    for comp, pct in sorted(summary.get("cumulative_percentage", {}).items(), key=lambda x: -x[1]):
        name = comp.replace("_", " ").title()
        pts = summary.get("cumulative_points", {}).get(comp, 0)
        lines.append(f"- **{name}**: {pct}% ({pts} pts)")

    if summary.get("gaps"):
        lines.append("\n## Areas Needing Attention\n")
        lines.extend(f"- {gap.replace('_', ' ').title()}" for gap in summary["gaps"])

    if summary.get("highlights"):
        lines.append("\n## Highlights\n")
        lines.extend(f"- {h}" for h in summary["highlights"])

    lines.append("")
    return "\n".join(lines)


def competency_dict(summary: dict) -> dict[str, dict]:
    """Percentage and points per competency from the quarter summary."""
    points = summary.get("cumulative_points", {})
    return {
        comp_id: {"percentage": pct, "points": points.get(comp_id, 0)}
        for comp_id, pct in summary.get("cumulative_percentage", {}).items()
    }


class ReportExporter:
    """Write the quarterly report for a stats daemon in JSON, Markdown or PDF."""

    def __init__(self, source: ExecutiveEmailMixin):
        self.source = source

    async def export(self, fmt: str = "markdown") -> dict:
        """Generate and export the current quarter's report in *fmt*."""
        now = now_local()
        year, quarter = now.year, quarter_of(now)

        perf_dir = self.source.perf_dir(year, quarter)
        ctx = ReportContext(
            year=year,
            quarter=quarter,
            now=now,
            perf_dir=perf_dir,
            summary=self.source.load_file(perf_dir / "summary.json") or {},
            all_events=await asyncio.to_thread(load_all_events, self.source.daily_dir(year, quarter)),
        )

        if fmt == "pdf":
            return await self.export_pdf(ctx)

        if fmt == "json":
            report_file = ctx.report_file("json")
            report = {
                "quarter": ctx.label,
                "summary": ctx.summary,
                "total_events": len(ctx.all_events),
                "events": ctx.all_events,
            }
            await asyncio.to_thread(write_json, report_file, report)
        else:
            report_file = ctx.report_file("md")
            await asyncio.to_thread(write_text, report_file, build_markdown(ctx))

        return {
            "success": True,
            "path": str(report_file),
            "format": fmt,
            "event_count": len(ctx.all_events),
        }

    async def _hierarchy(self) -> dict | None:
        try:
            result = await self.source.issue_hierarchy(refresh=False)
        except DATA_ERRORS as e:
            logger.warning("Failed to load hierarchy for PDF: %s", e)
            return None
        if result.get("strategies") or result.get("unattached_epics"):
            return result
        return None

    async def _evidence(self) -> tuple[dict, dict]:
        try:
            result = await self.source.competency_evidence()
        except DATA_ERRORS as e:
            logger.warning("Failed to load competency evidence for PDF: %s", e)
            return {}, {}
        return result.get("competency_evidence", {}), result.get("gap_suggestions", {})

    async def _captured_days(self) -> list[dict]:
        try:
            result = await self.source.captured_days()
        except DATA_ERRORS as e:
            logger.warning("Failed to load captured days for PDF: %s", e)
            return []
        days: list[dict] = result.get("days", [])
        return days

    async def _strategy(self) -> dict | None:
        try:
            emails = await self.source.list_executive_emails()
            if not emails:
                return None
            email_id = emails[0].get("email_id", "")
            cache_file = self.source.executive_emails_dir() / f"{email_id}.json"
            parsed_email = await asyncio.to_thread(read_json, cache_file) if cache_file.exists() else None
            map_result = await self.source.map_deliverables(email_id)
        except DATA_ERRORS as e:
            logger.warning("Failed to load strategy data for PDF: %s", e)
            return None
        return {
            "parsed_email": parsed_email,
            "mappings": map_result.get("mappings", []),
            "priority_coverage": map_result.get("priority_coverage", []),
            "coverage_summary": map_result.get("coverage_summary"),
        }

    async def export_pdf(self, ctx: ReportContext) -> dict:
        """Gather all data and render the PDF report."""
        summary = ctx.summary
        overall_pct = summary.get("overall_percentage", 0)
        comp_dict = competency_dict(summary)

        hierarchy = await self._hierarchy()
        comp_evidence, gap_suggestions_data = await self._evidence()
        captured_days = await self._captured_days()
        strategy_data = await self._strategy()

        template_data = {
            "quarter": ctx.label,
            "generated_at": ctx.now.strftime("%Y-%m-%d %H:%M"),
            "overall_pct": overall_pct,
            "score_color": score_color(overall_pct),
            "day_of_quarter": summary.get("day_of_quarter", 0),
            "total_events": len(ctx.all_events),
            "days_captured": len(captured_days),
            "total_issues": hierarchy.get("total_issues", 0) if hierarchy else 0,
            "num_competencies": len(comp_dict),
            "sunburst_svg": generate_sunburst_svg(comp_dict, overall_pct) if comp_dict else "",
            "mindmap_svg": generate_mindmap_svg(hierarchy, ctx.label) if hierarchy else "",
            "calendar_html": generate_calendar_html(captured_days, ctx.year, ctx.quarter),
            "competency_bars_html": generate_competency_bars_html(comp_dict),
            "competencies": comp_dict,
            "highlights": summary.get("highlights", []),
            "gaps_list": [g.replace("_", " ").title() for g in summary.get("gaps", [])],
            "hierarchy": hierarchy,
            "competency_evidence": comp_evidence,
            "gap_suggestions": gap_suggestions_data,
            "questions_summary": summary.get("questions_summary") or [],
            "strategy_data": strategy_data,
            "all_events": ctx.all_events,
        }

        pdf_path = await asyncio.to_thread(render_pdf, template_data, TEMPLATE_PATH, ctx.report_file("pdf"))
        return {
            "success": True,
            "path": pdf_path,
            "format": "pdf",
            "event_count": len(ctx.all_events),
        }
