"""
Helper functions for generating the QC PDF report.

Provides Python-side SVG generators (mindmap, sunburst), calendar HTML,
competency bars, and the full PDF rendering pipeline.
"""

from __future__ import annotations

import calendar
import math
from datetime import datetime
from html import escape
from pathlib import Path

# ============================================================
# Color helpers
# ============================================================


def color_for_pct(pct: float) -> str:
    if pct >= 80:
        return "#10b981"
    if pct >= 50:
        return "#f59e0b"
    if pct >= 25:
        return "#f97316"
    return "#ef4444"


def score_color(pct: float) -> str:
    if pct >= 70:
        return "#4caf50"
    if pct >= 40:
        return "#ff9800"
    return "#ef5350"


# ============================================================
# Sunburst SVG (Python port of TS generateSunburstSVG)
# ============================================================

META_CATEGORIES = [
    {
        "id": "technical_excellence",
        "name": "Technical Excellence",
        "competencies": [
            "technical_contribution",
            "technical_knowledge",
            "creativity_innovation",
            "continuous_improvement",
        ],
    },
    {
        "id": "leadership_influence",
        "name": "Leadership & Influence",
        "competencies": [
            "leadership",
            "collaboration",
            "mentorship",
            "speaking_publicity",
        ],
    },
    {
        "id": "delivery_impact",
        "name": "Delivery & Impact",
        "competencies": [
            "portfolio_impact",
            "planning_execution",
            "end_to_end_delivery",
            "opportunity_recognition",
        ],
    },
]


def _arc_path(
    cx: float,
    cy: float,
    inner_r: float,
    outer_r: float,
    start_angle: float,
    sweep_angle: float,
) -> str:
    start_rad = math.radians(start_angle)
    end_rad = math.radians(start_angle + sweep_angle)

    x1o = cx + outer_r * math.cos(start_rad)
    y1o = cy + outer_r * math.sin(start_rad)
    x2o = cx + outer_r * math.cos(end_rad)
    y2o = cy + outer_r * math.sin(end_rad)

    x1i = cx + inner_r * math.cos(start_rad)
    y1i = cy + inner_r * math.sin(start_rad)
    x2i = cx + inner_r * math.cos(end_rad)
    y2i = cy + inner_r * math.sin(end_rad)

    large = 1 if sweep_angle > 180 else 0

    return (
        f"M {x1o:.1f} {y1o:.1f} "
        f"A {outer_r} {outer_r} 0 {large} 1 {x2o:.1f} {y2o:.1f} "
        f"L {x2i:.1f} {y2i:.1f} "
        f"A {inner_r} {inner_r} 0 {large} 0 {x1i:.1f} {y1i:.1f} Z"
    )


def generate_sunburst_svg(competencies: dict, overall: float) -> str:
    """Generate a sunburst SVG for competency scores."""
    width, height = 350, 350
    cx, cy = width / 2, height / 2
    inner_r, mid_r, outer_r = 55, 100, 145

    center_color = color_for_pct(overall)
    paths = (
        f'<circle cx="{cx}" cy="{cy}" r="{inner_r - 5}" fill="{center_color}" opacity="0.2"/>'
        f'<text x="{cx}" y="{cy - 8}" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="28" font-weight="bold" fill="{center_color}">{overall:.0f}%</text>'
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="10" fill="#888">Overall</text>'
    )

    cat_angle = 360 / len(META_CATEGORIES)
    start = -90.0

    for cat in META_CATEGORIES:
        vals = [
            competencies.get(c, {}).get("percentage", 0) for c in cat["competencies"]
        ]
        cat_avg = round(sum(vals) / max(len(vals), 1))
        cat_color = color_for_pct(cat_avg)

        cat_path = _arc_path(cx, cy, inner_r, mid_r, start, cat_angle - 2)
        paths += (
            f'<path d="{cat_path}" fill="{cat_color}" opacity="0.5" '
            f'stroke="#fff" stroke-width="2"/>'
        )

        comp_angle = cat_angle / max(len(cat["competencies"]), 1)
        comp_start = start
        for comp_id in cat["competencies"]:
            pct = competencies.get(comp_id, {}).get("percentage", 0)
            c = color_for_pct(pct)
            p = _arc_path(cx, cy, mid_r, outer_r, comp_start, comp_angle - 1)
            name = comp_id.replace("_", " ").title()
            paths += (
                f'<path d="{p}" fill="{c}" opacity="0.8" stroke="#fff" stroke-width="1">'
                f"<title>{escape(name)}: {pct}%</title></path>"
            )
            comp_start += comp_angle
        start += cat_angle

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f"<style>text {{ font-family: system-ui, -apple-system, sans-serif; }}</style>"
        f"{paths}</svg>"
    )


# ============================================================
# Mindmap SVG (Python port of TS renderMindmap)
# ============================================================


def generate_mindmap_svg(hierarchy: dict, quarter_label: str) -> str:
    """Generate a dense radial mindmap SVG for the issue hierarchy.

    Levels:
        Center  -- quarter label
        Ring 1  -- ANSTRAT strategies (or unattached epics)
        Ring 2  -- Epics (children of strategies)
        Ring 3  -- Individual issues (children of epics)
    """
    strategies = hierarchy.get("strategies") or []
    unattached = hierarchy.get("unattached_epics") or []
    uncategorized = hierarchy.get("uncategorized") or []
    total = hierarchy.get("total_issues", 0)

    groups: list[dict] = list(strategies) + list(unattached)
    if not groups and uncategorized:
        groups = [
            {
                "key": "Other",
                "summary": "Uncategorized",
                "points": sum(i.get("points", 0) for i in uncategorized),
                "children": uncategorized,
            }
        ]

    if not groups:
        return ""

    # Count total leaf nodes to estimate required canvas size
    total_epics = sum(len(g.get("children") or []) for g in groups)
    total_leaf = sum(
        len(c.get("children") or []) for g in groups for c in (g.get("children") or [])
    )
    canvas = max(700, min(1100, 500 + total_epics * 50 + total_leaf * 20))
    width, height = canvas, canvas
    cx, cy = width / 2, height / 2

    colors = [
        "#3b82f6",
        "#8b5cf6",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#ec4899",
        "#06b6d4",
        "#f97316",
    ]

    # Center node -- prominent
    center_r = 48
    paths = (
        f'<circle cx="{cx}" cy="{cy}" r="{center_r}" fill="#334155" opacity="0.12"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{center_r}" fill="none" stroke="#334155" '
        f'stroke-width="2.5" opacity="0.25"/>'
        f'<text x="{cx}" y="{cy - 10}" text-anchor="middle" dominant-baseline="middle" '
        f'font-size="24" font-weight="800" fill="#1a1a1a">{escape(quarter_label)}</text>'
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" font-size="15" fill="#555">'
        f"{total} issues</text>"
    )

    n_groups = max(len(groups), 1)
    angle_step = 2 * math.pi / n_groups
    strat_r = int(canvas * 0.22)
    epic_r = int(canvas * 0.14)
    issue_r = int(canvas * 0.10)
    max_epics = 8
    max_issues = 6

    for gi, group in enumerate(groups):
        angle = gi * angle_step - math.pi / 2
        gx = cx + strat_r * math.cos(angle)
        gy = cy + strat_r * math.sin(angle)
        color = colors[gi % len(colors)]

        # Line: center -> strategy
        paths += (
            f'<line x1="{cx}" y1="{cy}" x2="{gx:.1f}" y2="{gy:.1f}" '
            f'stroke="{color}" stroke-width="5" opacity="0.45"/>'
        )

        pts = group.get("points", 0)
        sz = min(max(pts / 5, 38), 60)
        key = group.get("key", "")
        short_key = key.replace("ANSTRAT-", "AN-")

        # Strategy node
        paths += (
            f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="{sz:.0f}" fill="{color}" opacity="0.2" '
            f'stroke="{color}" stroke-width="3"/>'
            f'<text x="{gx:.1f}" y="{gy - 7:.1f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-size="16" fill="#1a1a1a" font-weight="800">{escape(short_key)}</text>'
            f'<text x="{gx:.1f}" y="{gy + 13:.1f}" text-anchor="middle" font-size="13" '
            f'fill="#444" font-weight="600">{pts}pts</text>'
        )

        # Ring 2: Epics
        children = (group.get("children") or [])[:max_epics]
        if children:
            n_ch = len(children)
            child_span = min(math.pi * 1.1, max(n_ch * 0.65, 0.8))
            child_step = child_span / max(n_ch - 1, 1)
            child_start = angle - child_span / 2

            for ci, child in enumerate(children):
                ca = angle if n_ch == 1 else child_start + ci * child_step
                ex = gx + epic_r * math.cos(ca)
                ey = gy + epic_r * math.sin(ca)
                epts = child.get("points", 0)
                esz = min(max(epts / 5, 24), 36)
                ckey = child.get("key", "")
                short_ckey = ckey.replace("AAP-", "")

                # Line: strategy -> epic
                paths += (
                    f'<line x1="{gx:.1f}" y1="{gy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                    f'stroke="{color}" stroke-width="3" opacity="0.4"/>'
                    f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{esz:.0f}" fill="{color}" '
                    f'opacity="0.5" stroke="{color}" stroke-width="2"/>'
                    f'<text x="{ex:.1f}" y="{ey:.1f}" text-anchor="middle" dominant-baseline="middle" '
                    f'font-size="14" font-weight="700" fill="#1a1a1a">{escape(short_ckey)}</text>'
                )

                # Ring 3: Issues (children of epics)
                issues = (child.get("children") or [])[:max_issues]
                if issues:
                    n_iss = len(issues)
                    issue_span = min(math.pi * 0.9, max(n_iss * 0.45, 0.6))
                    issue_step = issue_span / max(n_iss - 1, 1)
                    issue_start = ca - issue_span / 2

                    for ii, issue in enumerate(issues):
                        ia = ca if n_iss == 1 else issue_start + ii * issue_step
                        ix = ex + issue_r * math.cos(ia)
                        iy = ey + issue_r * math.sin(ia)
                        ipts = issue.get("points", 0)
                        isz = min(max(ipts / 6, 20), 28)
                        ikey = issue.get("key", "")
                        short_ikey = ikey.replace("AAP-", "")

                        # Line: epic -> issue
                        paths += (
                            f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{ix:.1f}" y2="{iy:.1f}" '
                            f'stroke="{color}" stroke-width="2" opacity="0.35"/>'
                            f'<circle cx="{ix:.1f}" cy="{iy:.1f}" r="{isz:.0f}" '
                            f'fill="{color}" opacity="0.75" stroke="{color}" stroke-width="1.5"/>'
                            f'<text x="{ix:.1f}" y="{iy:.1f}" text-anchor="middle" '
                            f'dominant-baseline="middle" font-size="12" font-weight="700" fill="#fff">'
                            f"{escape(short_ikey)}</text>"
                        )

                    leftover = len(child.get("children") or []) - max_issues
                    if leftover > 0:
                        lx = ex + (issue_r + 18) * math.cos(ca)
                        ly = ey + (issue_r + 18) * math.sin(ca)
                        paths += (
                            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                            f'font-size="12" font-weight="bold" fill="#999">+{leftover}</text>'
                        )

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;">'
        f"<style>text {{ font-family: system-ui, -apple-system, sans-serif; }}</style>"
        f"{paths}</svg>"
    )


# ============================================================
# Calendar HTML
# ============================================================


def generate_calendar_html(
    captured_days: list[dict],
    year: int,
    quarter: int,
) -> str:
    """Generate month-grid HTML tables for the quarter."""
    captured_set = {d.get("date", "") for d in captured_days}
    start_month = (quarter - 1) * 3 + 1
    months = [start_month, start_month + 1, start_month + 2]
    month_names = [
        "",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    html = '<div class="calendar-grid">'
    for m in months:
        html += f'<div class="calendar-month"><div class="calendar-month-title">{month_names[m]} {year}</div>'
        html += "<table><thead><tr>"
        for day_name in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
            html += f"<th>{day_name}</th>"
        html += "</tr></thead><tbody>"

        cal = calendar.monthcalendar(year, m)
        for week in cal:
            html += "<tr>"
            for day in week:
                if day == 0:
                    html += '<td class="cal-empty"></td>'
                else:
                    date_str = f"{year}-{m:02d}-{day:02d}"
                    if date_str in captured_set:
                        html += f'<td class="cal-has-data">{day}</td>'
                    else:
                        html += f'<td class="cal-no-data">{day}</td>'
            html += "</tr>"
        html += "</tbody></table></div>"
    html += "</div>"
    return html


# ============================================================
# Competency bars HTML
# ============================================================


def generate_competency_bars_html(competencies: dict) -> str:
    """Generate horizontal progress bars for each competency."""
    if not competencies:
        return '<p class="empty-note">No competency data available.</p>'

    sorted_comps = sorted(
        competencies.items(),
        key=lambda x: -(x[1].get("percentage", 0) if isinstance(x[1], dict) else 0),
    )

    html = ""
    for comp_id, data in sorted_comps:
        if not isinstance(data, dict):
            continue
        pct = data.get("percentage", 0)
        color = color_for_pct(pct)
        name = comp_id.replace("_", " ").title()
        html += (
            f'<div class="comp-bar-row">'
            f'<div class="comp-bar-name">{escape(name)}</div>'
            f'<div class="comp-bar-track">'
            f'<div class="comp-bar-fill" style="width:{pct}%;background:{color};"></div>'
            f"</div>"
            f'<div class="comp-bar-pct">{pct}%</div>'
            f"</div>"
        )
    return html


# ============================================================
# PDF render pipeline
# ============================================================


def render_pdf(template_data: dict, template_path: Path, output_path: Path) -> str:
    """Render HTML template to PDF via WeasyPrint.

    Args:
        template_data: Dict of all template variables.
        template_path: Path to the Jinja2 HTML template.
        output_path: Where to write the PDF file.

    Returns:
        Path to the generated PDF as a string.
    """
    import jinja2

    try:
        from weasyprint import HTML
    except ImportError:
        raise RuntimeError(
            "weasyprint is not installed. Install it with: "
            "pip install weasyprint  (or:  pip install -e '.[report]')"
        )

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
        autoescape=True,
    )
    template = env.get_template(template_path.name)

    html_str = template.render(**template_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(output_path))

    return str(output_path)
