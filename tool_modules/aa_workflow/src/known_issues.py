"""Shared known-issues checking for skill_engine and meta_tools."""

import logging

import yaml

from tool_modules.common import PROJECT_ROOT

logger = logging.getLogger(__name__)


def check_known_issues_sync(tool_name: str = "", error_text: str = "") -> list:
    """Check memory for known issues matching this tool/error."""
    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        memory_dir = PROJECT_ROOT / "memory" / "learned"

        patterns_file = memory_dir / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file, encoding="utf-8") as f:
                patterns = yaml.safe_load(f) or {}

            for category in [
                "error_patterns",
                "auth_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns.get(category, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (
                        pattern_text in error_lower or pattern_text in tool_lower
                    ):
                        matches.append(
                            {
                                "source": category,
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

        fixes_file = memory_dir / "tool_fixes.yaml"
        if fixes_file.exists():
            with open(fixes_file, encoding="utf-8") as f:
                fixes = yaml.safe_load(f) or {}

            for fix in fixes.get("tool_fixes", []):
                if tool_name and fix.get("tool_name", "").lower() == tool_lower:
                    matches.append(
                        {
                            "source": "tool_fixes",
                            "tool_name": fix.get("tool_name"),
                            "pattern": fix.get("error_pattern", ""),
                            "fix": fix.get("fix_applied", ""),
                        }
                    )
                elif error_text:
                    fix_pattern = fix.get("error_pattern", "").lower()
                    if fix_pattern and fix_pattern in error_lower:
                        matches.append(
                            {
                                "source": "tool_fixes",
                                "tool_name": fix.get("tool_name"),
                                "pattern": fix.get("error_pattern", ""),
                                "fix": fix.get("fix_applied", ""),
                            }
                        )

    except (yaml.YAMLError, OSError) as exc:
        logger.debug("Suppressed error: %s", exc)

    return matches


def format_known_issues(matches: list) -> str:
    """Format known issues for display."""
    if not matches:
        return ""

    lines = ["\n## 💡 Known Issues Found!\n"]
    for match in matches[:3]:
        lines.append(f"**Pattern:** `{match.get('pattern', '?')}`")
        if match.get("meaning"):
            lines.append(f"*{match.get('meaning')}*")
        if match.get("fix"):
            lines.append(f"**Fix:** {match.get('fix')}")
        if match.get("commands"):
            lines.append("**Try:**")
            for cmd in match.get("commands", [])[:2]:
                lines.append(f"- `{cmd}`")
        lines.append("")

    return "\n".join(lines)
