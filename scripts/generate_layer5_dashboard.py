#!/usr/bin/env python3
"""
Generate Layer 5 Dashboard.

Creates a markdown dashboard showing usage pattern statistics and effectiveness.

Usage:
    python scripts/generate_layer5_dashboard.py [--output FILE]
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _get_confidence_emoji(conf: float) -> str:
    """Get emoji based on confidence level."""
    if conf >= 0.95:
        return "🔴"
    elif conf >= 0.85:
        return "🟠"
    elif conf >= 0.75:
        return "🟡"
    else:
        return "⚪"


def _build_header(lines: list[str]) -> None:
    """Build dashboard header."""
    lines.append("# 🧠 Layer 5: Usage Pattern Learning Dashboard")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")


def _build_overview(
    lines: list[str], patterns: list, conf_counts: dict, stats: dict
) -> None:
    """Build overview section."""
    lines.append("## 📊 Overview")
    lines.append("")
    lines.append(f"- **Total Patterns**: {len(patterns)}")
    high_conf_count = (
        conf_counts["critical"] + conf_counts["high"] + conf_counts["medium"]
    )
    lines.append(f"- **High Confidence (>= 80%)**: {high_conf_count}")
    lines.append(f"- **Last Updated**: {stats.get('last_updated', 'Never')}")
    lines.append("")


def _build_confidence_levels(lines: list[str], conf_counts: dict) -> None:
    """Build confidence levels table."""
    lines.append("## 🎯 Confidence Levels")
    lines.append("")
    lines.append("| Level | Confidence | Count | Behavior |")
    lines.append("|-------|-----------|-------|----------|")
    lines.append(
        f"| 🔴 Critical | >= 95% | {conf_counts['critical']} | **Blocks execution** |"
    )
    lines.append(f"| 🟠 High | 85-94% | {conf_counts['high']} | Strong warning |")
    lines.append(f"| 🟡 Medium | 75-84% | {conf_counts['medium']} | Warning |")
    lines.append(f"| ⚪ Low | < 75% | {conf_counts['low']} | No warning (filtered) |")
    lines.append("")


def _build_top_patterns(lines: list[str], patterns: list) -> None:
    """Build top patterns section."""
    lines.append("## 🔝 Top Patterns by Confidence")
    lines.append("")

    sorted_patterns = sorted(
        patterns, key=lambda p: p.get("confidence", 0), reverse=True
    )
    top_patterns = sorted_patterns[:10]

    if top_patterns:
        lines.append("| Tool | Issue | Confidence | Observations |")
        lines.append("|------|-------|-----------|--------------|")

        for pattern in top_patterns:
            tool = pattern["tool"]
            root_cause = pattern.get("root_cause", "Unknown")[:50]
            conf = pattern.get("confidence", 0)
            obs = pattern.get("observations", 0)
            emoji = _get_confidence_emoji(conf)
            lines.append(f"| {emoji} `{tool}` | {root_cause} | {conf:.0%} | {obs} |")

        lines.append("")
    else:
        lines.append("*No patterns learned yet.*")
        lines.append("")


def _build_category_breakdown(lines: list[str], stats: dict) -> None:
    """Build category breakdown section."""
    lines.append("## 📂 Patterns by Category")
    lines.append("")

    category_stats = stats.get("by_category", {})
    if category_stats:
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")

        for category, count in sorted(
            category_stats.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"| {category.replace('_', ' ').title()} | {count} |")

        lines.append("")
    else:
        lines.append("*No category statistics available.*")
        lines.append("")


def _build_prevention_effectiveness(lines: list[str], patterns: list) -> None:
    """Build prevention effectiveness section."""
    lines.append("## ✅ Prevention Effectiveness")
    lines.append("")

    total_obs = sum(p.get("observations", 0) for p in patterns)
    total_success = sum(p.get("success_after_prevention", 0) for p in patterns)
    success_rate = (total_success / total_obs * 100) if total_obs > 0 else 0

    lines.append(f"- **Total Observations**: {total_obs}")
    lines.append(f"- **Successful Prevention**: {total_success}")
    lines.append(f"- **Success Rate**: {success_rate:.1f}%")
    lines.append("")

    if success_rate >= 90:
        lines.append("🎉 **Excellent!** Prevention is highly effective.")
    elif success_rate >= 75:
        lines.append("👍 **Good!** Prevention is working well.")
    elif success_rate >= 50:
        lines.append("⚠️  **Fair.** Some patterns may need refinement.")
    else:
        lines.append("⚠️  **Needs attention.** Review pattern quality.")

    lines.append("")


def _build_optimization_opportunities(lines: list[str], opt_stats: dict) -> None:
    """Build optimization opportunities section."""
    lines.append("## 🔧 Optimization Opportunities")
    lines.append("")

    lines.append(f"- **Old Patterns** (>90 days): {opt_stats['old_patterns']}")
    lines.append(f"- **Low Confidence** (<70%): {opt_stats['low_confidence']}")
    lines.append(f"- **Inactive** (>30 days): {opt_stats['inactive_patterns']}")
    lines.append("")
    lines.append(f"- **Candidates for Pruning**: {opt_stats['candidates_for_pruning']}")
    lines.append(f"- **Candidates for Decay**: {opt_stats['candidates_for_decay']}")
    lines.append("")

    if opt_stats["candidates_for_pruning"] > 0:
        lines.append(
            "💡 **Recommendation**: Run pattern pruning to remove stale patterns."
        )
        lines.append("")
        lines.append("```bash")
        lines.append("python scripts/optimize_patterns.py --prune")
        lines.append("```")
        lines.append("")


def _build_tools_with_patterns(lines: list[str], patterns: list) -> None:
    """Build tools with most patterns section."""
    lines.append("## 🛠️  Tools with Most Patterns")
    lines.append("")

    tool_counts = {}
    for pattern in patterns:
        tool = pattern["tool"]
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    if tool_counts:
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[
            :10
        ]

        lines.append("| Tool | Patterns |")
        lines.append("|------|----------|")

        for tool, count in sorted_tools:
            lines.append(f"| `{tool}` | {count} |")

        lines.append("")
    else:
        lines.append("*No patterns learned yet.*")
        lines.append("")


def _build_recent_activity(lines: list[str], patterns: list) -> None:
    """Build recent activity section."""
    lines.append("## 📅 Recent Activity")
    lines.append("")

    recent_patterns = sorted(
        patterns, key=lambda p: p.get("last_seen", ""), reverse=True
    )[:5]

    if recent_patterns:
        lines.append("| Tool | Last Seen | Confidence | Observations |")
        lines.append("|------|-----------|-----------|--------------|")

        for pattern in recent_patterns:
            tool = pattern["tool"]
            last_seen = pattern.get("last_seen", "Unknown")[:10]
            conf = pattern.get("confidence", 0)
            obs = pattern.get("observations", 0)

            lines.append(f"| `{tool}` | {last_seen} | {conf:.0%} | {obs} |")

        lines.append("")
    else:
        lines.append("*No recent activity.*")
        lines.append("")


def generate_dashboard(output_file: Path = None) -> str:
    # Import after path setup
    from server.usage_context_injector import UsageContextInjector
    from server.usage_pattern_optimizer import UsagePatternOptimizer
    from server.usage_pattern_storage import UsagePatternStorage

    """Generate Layer 5 dashboard.

    Args:
        output_file: Optional path to write dashboard to

    Returns:
        Dashboard content as markdown string
    """
    storage = UsagePatternStorage()
    injector = UsageContextInjector(storage=storage)
    optimizer = UsagePatternOptimizer(storage=storage)

    # Load data
    data = storage.load()
    patterns = data.get("usage_patterns", [])
    stats = data.get("stats", {})

    # Get optimization stats
    opt_stats = optimizer.get_optimization_stats()

    # Get pattern counts by confidence
    conf_counts = injector.get_pattern_count_by_confidence()

    # Build dashboard
    lines = []

    _build_header(lines)
    _build_overview(lines, patterns, conf_counts, stats)
    _build_confidence_levels(lines, conf_counts)
    _build_top_patterns(lines, patterns)
    _build_category_breakdown(lines, stats)
    _build_prevention_effectiveness(lines, patterns)
    _build_optimization_opportunities(lines, opt_stats)
    _build_tools_with_patterns(lines, patterns)
    _build_recent_activity(lines, patterns)

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        "*This dashboard is generated automatically from learned usage patterns.*"
    )
    lines.append("")

    # Join all lines
    content = "\n".join(lines)

    # Write to file if specified
    if output_file:
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ Dashboard written to: {output_file}")
        except OSError as e:
            print(f"❌ Failed to write dashboard: {e}")

    return content


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate Layer 5 Dashboard")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file path (default: print to stdout)",
    )

    args = parser.parse_args()

    try:
        content = generate_dashboard(output_file=args.output)

        if not args.output:
            # Print to stdout
            print(content)

    except Exception as e:
        print(f"❌ Error generating dashboard: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
