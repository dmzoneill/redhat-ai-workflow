# pylint: disable=duplicate-code,cyclic-import
"""Helpers shared by the skill engine."""

import logging
from pathlib import Path

import yaml

from .skill_paths import skills_dir

logger = logging.getLogger(__name__)


class AttrDict(dict):
    """Dictionary that allows attribute-style access to keys.

    This allows skill YAML compute blocks to use `inputs.repo` instead of `inputs["repo"]`.
    """

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'") from e

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError as e:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'") from e


def _get_agent_stats_module():
    """Get the agent_stats module, handling both package and direct load contexts."""
    try:
        # Try relative import first (works when loaded as package)
        from . import agent_stats  # pylint: disable=import-outside-toplevel

        return agent_stats
    except ImportError:
        # Fall back to direct file loading (works when loaded dynamically)
        # Force fresh load by removing from sys.modules cache
        import importlib.util  # pylint: disable=import-outside-toplevel
        import sys  # pylint: disable=import-outside-toplevel

        agent_stats_path = Path(__file__).parent / "agent_stats.py"

        # Remove cached version to force fresh load
        if "agent_stats" in sys.modules:
            del sys.modules["agent_stats"]

        spec = importlib.util.spec_from_file_location("agent_stats", agent_stats_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["agent_stats"] = (
            module  # Register before exec to handle circular imports
        )
        spec.loader.exec_module(module)
        return module


def _check_known_issues_sync(  # pylint: disable=too-many-locals
    tool_name: str = "", error_text: str = ""
) -> list:  # pylint: disable=too-many-locals
    """Check memory for known issues matching this tool/error."""
    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        patterns_file = skills_dir().parent / "memory" / "learned" / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file, encoding="utf-8") as f:
                patterns = yaml.safe_load(f) or {}

            # Check all pattern categories
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

        # Check tool_fixes.yaml
        fixes_file = skills_dir().parent / "memory" / "learned" / "tool_fixes.yaml"
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


def _format_known_issues(matches: list) -> str:
    """Format known issues for display."""
    if not matches:
        return ""

    lines = ["\n## 💡 Known Issues Found!\n"]
    for match in matches[:3]:  # Limit to 3
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
