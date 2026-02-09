"""
Usage Context Injector - Layer 5 Phase 4.

Injects high-confidence prevention patterns into Claude's context at session start.
"""

import logging
from typing import Optional

from server.usage_pattern_storage import UsagePatternStorage

logger = logging.getLogger(__name__)


class UsageContextInjector:
    """Generate prevention guidelines for Claude's context."""

    def __init__(self, storage: Optional[UsagePatternStorage] = None):
        """Initialize context injector.

        Args:
            storage: UsagePatternStorage instance. If None, creates default.
        """
        self.storage = storage or UsagePatternStorage()

    def generate_prevention_context(
        self,
        top_n: int = 15,
        min_confidence: float = 0.80,
        format_type: str = "markdown",
    ) -> str:
        """Generate prevention guidelines for Claude's context.

        Args:
            top_n: Number of top patterns to include
            min_confidence: Minimum confidence threshold (default: 80%)
            format_type: Output format ('markdown' or 'text')

        Returns:
            Formatted prevention guidelines
        """
        # Load all patterns
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        # Filter by confidence
        high_conf_patterns = [
            p for p in patterns if p.get("confidence", 0) >= min_confidence
        ]

        # Sort by confidence (descending), then observations (descending)
        high_conf_patterns.sort(
            key=lambda p: (p.get("confidence", 0), p.get("observations", 0)),
            reverse=True,
        )

        # Take top N
        top_patterns = high_conf_patterns[:top_n]

        if not top_patterns:
            return ""

        if format_type == "markdown":
            return self._format_markdown(top_patterns)
        else:
            return self._format_text(top_patterns)

    def _format_markdown(self, patterns: list[dict]) -> str:
        """Format patterns as markdown for Claude's context.

        Args:
            patterns: List of pattern dicts

        Returns:
            Markdown formatted string
        """
        lines = []
        lines.append("## 🧠 Layer 5: Learned Usage Patterns")
        lines.append("")
        lines.append(
            f"The system has learned {len(patterns)} high-confidence patterns "
            "from past mistakes. Follow these guidelines to avoid common errors:"
        )
        lines.append("")

        # Group by tool
        by_tool = {}
        for pattern in patterns:
            tool = pattern["tool"]
            if tool not in by_tool:
                by_tool[tool] = []
            by_tool[tool].append(pattern)

        # Format each tool's patterns
        for tool_name, tool_patterns in sorted(by_tool.items()):
            lines.append(f"### Tool: `{tool_name}`")
            lines.append("")

            for _i, pattern in enumerate(tool_patterns, 1):
                conf = pattern.get("confidence", 0)
                obs = pattern.get("observations", 0)
                root_cause = pattern.get("root_cause", "Unknown issue")
                prevention = pattern.get("prevention_steps", [])

                # Confidence emoji
                if conf >= 0.95:
                    emoji = "🔴"
                    level = "CRITICAL"
                elif conf >= 0.85:
                    emoji = "🟠"
                    level = "HIGH"
                else:
                    emoji = "🟡"
                    level = "MEDIUM"

                lines.append(f"{emoji} **{level}** ({conf:.0%}, {obs} observations)")
                lines.append(f"   - **Issue**: {root_cause}")

                if prevention:
                    lines.append("   - **Prevention**:")
                    for step in prevention:
                        reason = step.get("reason", step.get("action", "Unknown"))
                        lines.append(f"     - {reason}")

                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("💡 **When you see warnings during tool execution:**")
        lines.append("1. Read the prevention steps carefully")
        lines.append("2. Fix the parameter(s) or call prerequisite tool(s)")
        lines.append("3. Retry with corrected parameters")
        lines.append("")
        lines.append("⛔ **If execution is blocked (>= 95% confidence):**")
        lines.append("- The pattern has been confirmed by 100+ observations")
        lines.append("- Following prevention steps is strongly recommended")
        lines.append("- Ignoring the block will likely result in failure")
        lines.append("")

        return "\n".join(lines)

    def _format_text(self, patterns: list[dict]) -> str:
        """Format patterns as plain text.

        Args:
            patterns: List of pattern dicts

        Returns:
            Plain text formatted string
        """
        lines = []
        lines.append("=== LAYER 5: LEARNED USAGE PATTERNS ===")
        lines.append("")
        lines.append(
            f"The system has learned {len(patterns)} high-confidence patterns "
            "from past mistakes."
        )
        lines.append("")

        for i, pattern in enumerate(patterns, 1):
            tool = pattern["tool"]
            conf = pattern.get("confidence", 0)
            obs = pattern.get("observations", 0)
            root_cause = pattern.get("root_cause", "Unknown")
            prevention = pattern.get("prevention_steps", [])

            lines.append(f"{i}. {tool} ({conf:.0%} confidence, {obs} observations)")
            lines.append(f"   Issue: {root_cause}")

            if prevention:
                lines.append("   Prevention:")
                for step in prevention:
                    reason = step.get("reason", step.get("action", "Unknown"))
                    lines.append(f"   - {reason}")

            lines.append("")

        return "\n".join(lines)

    def get_pattern_count_by_confidence(self) -> dict:
        """Get count of patterns by confidence level.

        Returns:
            {
                "critical": int,  # >= 95%
                "high": int,      # >= 85%
                "medium": int,    # >= 75%
                "low": int,       # < 75%
            }
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }

        for pattern in patterns:
            conf = pattern.get("confidence", 0)
            if conf >= 0.95:
                counts["critical"] += 1
            elif conf >= 0.85:
                counts["high"] += 1
            elif conf >= 0.75:
                counts["medium"] += 1
            else:
                counts["low"] += 1

        return counts

    def get_prevention_summary(self, tool_name: Optional[str] = None) -> str:
        """Get a quick summary of prevention patterns.

        Args:
            tool_name: Optional tool name to filter by

        Returns:
            Summary string
        """
        data = self.storage.load()
        patterns = data.get("usage_patterns", [])

        if tool_name:
            patterns = [p for p in patterns if p.get("tool") == tool_name]

        total = len(patterns)
        counts = {
            "critical": sum(1 for p in patterns if p.get("confidence", 0) >= 0.95),
            "high": sum(1 for p in patterns if 0.85 <= p.get("confidence", 0) < 0.95),
            "medium": sum(1 for p in patterns if 0.75 <= p.get("confidence", 0) < 0.85),
        }

        if total == 0:
            return "No prevention patterns found."

        summary_lines = []

        if tool_name:
            summary_lines.append(
                f"Prevention patterns for `{tool_name}`: {total} total"
            )
        else:
            summary_lines.append(f"Prevention patterns: {total} total")

        if counts["critical"] > 0:
            summary_lines.append(f"  🔴 Critical (>= 95%): {counts['critical']}")
        if counts["high"] > 0:
            summary_lines.append(f"  🟠 High (>= 85%): {counts['high']}")
        if counts["medium"] > 0:
            summary_lines.append(f"  🟡 Medium (>= 75%): {counts['medium']}")

        return "\n".join(summary_lines)
