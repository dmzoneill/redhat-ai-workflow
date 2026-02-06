"""Chart Generator - Generate SVG charts for performance visualization.

Generates:
- Sunburst chart for competency overview
- Progress bars for individual competencies
- Trend line charts for daily activity
"""

import math


def get_color_for_percentage(pct: int) -> str:
    """Get color based on percentage of target achieved."""
    if pct >= 80:
        return "#10b981"  # Green
    elif pct >= 50:
        return "#f59e0b"  # Yellow/Amber
    elif pct >= 25:
        return "#f97316"  # Orange
    else:
        return "#ef4444"  # Red


def get_status_icon(pct: int) -> str:
    """Get status icon based on percentage."""
    if pct >= 80:
        return "✓"
    elif pct >= 50:
        return ""
    else:
        return "⚠"


def generate_sunburst_svg(
    data: dict,
    width: int = 400,
    height: int = 400,
) -> str:
    """Generate a sunburst chart SVG.

    Args:
        data: Dict with structure:
            {
                "center": {"label": "72%", "value": 72},
                "inner": [
                    {"id": "cat1", "name": "Technical", "value": 75, "children": [
                        {"id": "comp1", "name": "Tech Contrib", "value": 89},
                        ...
                    ]},
                    ...
                ]
            }
        width: SVG width
        height: SVG height

    Returns:
        SVG string
    """
    cx, cy = width // 2, height // 2
    inner_radius = 60
    middle_radius = 110
    outer_radius = 160

    paths = []

    # Center circle with overall percentage
    center = data.get("center", {})
    center_value = center.get("value", 0)
    center_color = get_color_for_percentage(center_value)

    paths.append(
        f"""
        <circle cx="{cx}" cy="{cy}" r="{inner_radius - 5}" fill="{center_color}" opacity="0.2"/>
        <text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="middle"
              font-size="24" font-weight="bold" fill="{center_color}">{center.get("label", "")}</text>
    """
    )

    # Inner ring - meta categories
    inner_categories = data.get("inner", [])
    if inner_categories:
        total_inner = sum(cat.get("value", 0) for cat in inner_categories)
        if total_inner == 0:
            total_inner = len(inner_categories) * 100  # Assume equal distribution

        start_angle = -90  # Start at top
        for cat in inner_categories:
            cat_value = cat.get("value", 0)
            # Use equal slices for categories, color by value
            sweep_angle = 360 / len(inner_categories)
            color = get_color_for_percentage(cat_value)

            path = _arc_path(cx, cy, inner_radius, middle_radius, start_angle, sweep_angle)
            paths.append(
                f"""
                <path d="{path}" fill="{color}" opacity="0.6" stroke="var(--bg-primary, #1a1a2e)" stroke-width="2">
                    <title>{cat.get("name", "")}: {cat_value}%</title>
                </path>
            """
            )

            # Outer ring - individual competencies
            children = cat.get("children", [])
            if children:
                child_start = start_angle
                child_sweep = sweep_angle / len(children)

                for child in children:
                    child_value = child.get("value", 0)
                    child_color = get_color_for_percentage(child_value)

                    child_path = _arc_path(cx, cy, middle_radius, outer_radius, child_start, child_sweep - 1)
                    paths.append(
                        f"""
                        <path d="{child_path}" fill="{child_color}" opacity="0.8"
                              stroke="var(--bg-primary, #1a1a2e)" stroke-width="1">
                            <title>{child.get("name", "")}: {child_value}%</title>
                        </path>
                    """
                    )
                    child_start += child_sweep

            start_angle += sweep_angle

    svg = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
                  xmlns="http://www.w3.org/2000/svg">
        <style>
            text {{ font-family: system-ui, -apple-system, sans-serif; }}
        </style>
        {"".join(paths)}
    </svg>"""

    return svg


def _arc_path(
    cx: float,
    cy: float,
    inner_r: float,
    outer_r: float,
    start_angle: float,
    sweep_angle: float,
) -> str:
    """Generate SVG path for an arc segment."""
    # Convert to radians
    start_rad = math.radians(start_angle)
    end_rad = math.radians(start_angle + sweep_angle)

    # Calculate points
    x1_outer = cx + outer_r * math.cos(start_rad)
    y1_outer = cy + outer_r * math.sin(start_rad)
    x2_outer = cx + outer_r * math.cos(end_rad)
    y2_outer = cy + outer_r * math.sin(end_rad)

    x1_inner = cx + inner_r * math.cos(start_rad)
    y1_inner = cy + inner_r * math.sin(start_rad)
    x2_inner = cx + inner_r * math.cos(end_rad)
    y2_inner = cy + inner_r * math.sin(end_rad)

    large_arc = 1 if sweep_angle > 180 else 0

    return (
        f"M {x1_outer} {y1_outer} "
        f"A {outer_r} {outer_r} 0 {large_arc} 1 {x2_outer} {y2_outer} "
        f"L {x2_inner} {y2_inner} "
        f"A {inner_r} {inner_r} 0 {large_arc} 0 {x1_inner} {y1_inner} Z"
    )


def generate_progress_bars_html(
    competencies: dict[str, dict],
    show_icons: bool = True,
) -> str:
    """Generate HTML for competency progress bars.

    Args:
        competencies: Dict of competency_id -> {"name": str, "percentage": int, "points": int}
        show_icons: Whether to show status icons

    Returns:
        HTML string
    """
    html_parts = ['<div class="competency-progress">']

    # Sort by percentage descending
    sorted_comps = sorted(
        competencies.items(),
        key=lambda x: x[1].get("percentage", 0),
        reverse=True,
    )

    for comp_id, comp_data in sorted_comps:
        name = comp_data.get("name", comp_id)
        pct = comp_data.get("percentage", 0)
        color = get_color_for_percentage(pct)
        icon = get_status_icon(pct) if show_icons else ""

        html_parts.append(
            f"""
            <div class="progress-row" data-competency="{comp_id}">
                <div class="progress-label">
                    <span class="progress-name">{name}</span>
                    <span class="progress-value">{pct}% {icon}</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" style="width: {min(pct, 100)}%; background: {color};"></div>
                </div>
            </div>
        """
        )

    html_parts.append("</div>")
    return "\n".join(html_parts)


def generate_trend_chart_svg(
    daily_trend: list[dict],
    width: int = 600,
    height: int = 200,
) -> str:
    """Generate a trend line chart SVG.

    Args:
        daily_trend: List of {"date": str, "total": int}
        width: SVG width
        height: SVG height

    Returns:
        SVG string
    """
    if not daily_trend:
        return f'<svg width="{width}" height="{height}"><text x="50%" y="50%" text-anchor="middle">No data</text></svg>'

    padding = 40
    chart_width = width - 2 * padding
    chart_height = height - 2 * padding

    max_value = max(d.get("total", 0) for d in daily_trend) or 1
    num_points = len(daily_trend)

    # Generate path points
    points = []
    for i, day in enumerate(daily_trend):
        x = padding + (i / max(num_points - 1, 1)) * chart_width
        y = height - padding - (day.get("total", 0) / max_value) * chart_height
        points.append(f"{x},{y}")

    path_d = "M " + " L ".join(points)

    # Area fill
    area_points = points + [f"{padding + chart_width},{height - padding}", f"{padding},{height - padding}"]
    area_d = "M " + " L ".join(area_points) + " Z"

    svg = f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
                  xmlns="http://www.w3.org/2000/svg">
        <style>
            text {{ font-family: system-ui, -apple-system, sans-serif; font-size: 10px; fill: var(--text-muted, #888); }}
        </style>

        <!-- Grid lines -->
        <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"
              stroke="var(--border-color, #333)" stroke-width="1"/>
        <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"
              stroke="var(--border-color, #333)" stroke-width="1"/>

        <!-- Area fill -->
        <path d="{area_d}" fill="url(#gradient)" opacity="0.3"/>

        <!-- Line -->
        <path d="{path_d}" fill="none" stroke="#3b82f6" stroke-width="2"/>

        <!-- Points -->
        {"".join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="3" fill="#3b82f6"/>' for p in points[-10:])}

        <!-- Gradient definition -->
        <defs>
            <linearGradient id="gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" style="stop-color:#3b82f6;stop-opacity:0.8"/>
                <stop offset="100%" style="stop-color:#3b82f6;stop-opacity:0"/>
            </linearGradient>
        </defs>

        <!-- Labels -->
        <text x="{padding}" y="{height - 10}">{daily_trend[0].get("date", "")[-5:]}</text>
        <text x="{width - padding}" y="{height - 10}" text-anchor="end">{daily_trend[-1].get("date", "")[-5:]}</text>
        <text x="{padding - 5}" y="{padding + 5}" text-anchor="end">{max_value}</text>
        <text x="{padding - 5}" y="{height - padding}" text-anchor="end">0</text>
    </svg>"""

    return svg


def build_sunburst_data(
    competency_percentages: dict[str, int],
    meta_categories: dict[str, dict],
    competency_names: dict[str, str],
) -> dict:
    """Build sunburst chart data structure.

    Args:
        competency_percentages: Dict of competency_id -> percentage
        meta_categories: Dict of category_id -> {"name": str, "competencies": list}
        competency_names: Dict of competency_id -> display name

    Returns:
        Sunburst data structure for generate_sunburst_svg
    """
    # Calculate overall percentage
    if competency_percentages:
        overall = sum(competency_percentages.values()) // len(competency_percentages)
    else:
        overall = 0

    inner = []
    for cat_id, cat_config in meta_categories.items():
        cat_competencies = cat_config.get("competencies", [])

        # Calculate category average
        cat_values = [competency_percentages.get(c, 0) for c in cat_competencies]
        cat_avg = sum(cat_values) // len(cat_values) if cat_values else 0

        children = [
            {
                "id": comp_id,
                "name": competency_names.get(comp_id, comp_id),
                "value": competency_percentages.get(comp_id, 0),
            }
            for comp_id in cat_competencies
        ]

        inner.append(
            {
                "id": cat_id,
                "name": cat_config.get("name", cat_id),
                "value": cat_avg,
                "children": children,
            }
        )

    return {
        "center": {"label": f"{overall}%", "value": overall},
        "inner": inner,
    }
