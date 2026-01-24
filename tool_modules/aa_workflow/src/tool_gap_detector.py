"""Tool Gap Detector - Logs desired actions when no MCP tool exists.

This is a REUSABLE component used by ALL skills, not just Sprint Bot.
When any skill wants to perform an action but no MCP tool exists, it should:

1. Log the desired action to memory/learned/tool_requests.yaml
2. Continue with available alternatives or mark as blocked
3. Surface in UI for human review and potential tool development
4. Aggregate across skills to identify most-requested tools

Usage in any skill's compute block:
    from tool_modules.aa_workflow.src.tool_gap_detector import tool_gap

    # Log a gap
    tool_gap.log("quay_image_tag_exists",
                 action="Check if specific tag exists",
                 skill="sprint_autopilot")

    # Or try with fallback
    exists, result = tool_gap.try_or_log(
        tool_name="quay_image_tag_exists",
        action="Check tag existence",
        skill="my_skill",
        fallback=lambda: manual_check()
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Storage path - use project memory/ directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TOOL_GAP_FILE = PROJECT_ROOT / "memory" / "learned" / "tool_requests.yaml"


@dataclass
class ToolGapRequest:
    """A request for a tool that doesn't exist yet."""

    id: str
    timestamp: str
    suggested_tool_name: str
    desired_action: str
    context: str = ""
    suggested_args: dict[str, Any] = field(default_factory=dict)
    workaround_used: str | None = None
    requesting_skills: list[str] = field(default_factory=list)
    issue_key: str | None = None
    vote_count: int = 1
    status: str = "open"  # open, in_progress, implemented, rejected
    last_requested: str = ""


class ToolGapDetector:
    """
    Reusable detector for logging tool gaps across ALL skills.

    This is a singleton class that maintains a list of tool gaps
    and persists them to disk for review.

    Usage:
        from tool_modules.aa_workflow.src.tool_gap_detector import tool_gap

        # Log a gap
        tool_gap.log("quay_image_tag_exists",
                     action="Check if specific tag exists",
                     skill="sprint_autopilot")

        # Or try with fallback
        result = tool_gap.try_or_log(
            tool_name="quay_image_tag_exists",
            action="Check tag existence",
            skill="my_skill",
            fallback=lambda: manual_check()
        )
    """

    _instance: "ToolGapDetector | None" = None
    _gaps: list[dict[str, Any]]

    def __new__(cls) -> "ToolGapDetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._gaps = []
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        """Load existing gaps from file."""
        if TOOL_GAP_FILE.exists():
            try:
                with open(TOOL_GAP_FILE) as f:
                    data = yaml.safe_load(f) or {}
                    self._gaps = data.get("tool_requests", [])
                    logger.debug(f"Loaded {len(self._gaps)} tool gap requests")
            except Exception as e:
                logger.error(f"Failed to load tool gaps: {e}")
                self._gaps = []
        else:
            self._gaps = []

    def _save(self) -> None:
        """Save gaps to file."""
        try:
            TOOL_GAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TOOL_GAP_FILE, "w") as f:
                yaml.dump(
                    {
                        "tool_requests": self._gaps,
                        "last_updated": datetime.now().isoformat(),
                    },
                    f,
                    default_flow_style=False,
                    sort_keys=False,
                )
            logger.debug(f"Saved {len(self._gaps)} tool gap requests")
        except Exception as e:
            logger.error(f"Failed to save tool gaps: {e}")

    def log(
        self,
        suggested_tool_name: str,
        action: str,
        skill: str,
        context: str = "",
        args: dict[str, Any] | None = None,
        workaround: str | None = None,
        issue_key: str | None = None,
    ) -> str:
        """
        Log a tool gap. Returns gap ID.

        If the same tool was requested before, increments vote_count instead.

        Args:
            suggested_tool_name: Name of the tool that would be useful
            action: What the tool should do
            skill: Name of the skill requesting this
            context: Additional context about when this is needed
            args: Suggested arguments for the tool
            workaround: Description of workaround used (if any)
            issue_key: Related Jira issue (if applicable)

        Returns:
            Gap ID (existing or new)
        """
        # Check if this tool was already requested
        for gap in self._gaps:
            if gap.get("suggested_tool_name") == suggested_tool_name:
                # Update existing request
                gap["vote_count"] = gap.get("vote_count", 1) + 1
                gap["last_requested"] = datetime.now().isoformat()
                gap["requesting_skills"] = list(set(gap.get("requesting_skills", []) + [skill]))
                if workaround and not gap.get("workaround_used"):
                    gap["workaround_used"] = workaround
                if context and not gap.get("context"):
                    gap["context"] = context
                self._save()
                logger.info(
                    f"Tool gap '{suggested_tool_name}' requested again " f"(vote #{gap['vote_count']}) by {skill}"
                )
                return gap.get("id", suggested_tool_name)

        # New request
        gap_id = f"{suggested_tool_name}_{len(self._gaps)}"
        new_gap = {
            "id": gap_id,
            "timestamp": datetime.now().isoformat(),
            "suggested_tool_name": suggested_tool_name,
            "desired_action": action,
            "context": context,
            "suggested_args": args or {},
            "workaround_used": workaround,
            "requesting_skills": [skill],
            "issue_key": issue_key,
            "vote_count": 1,
            "status": "open",
            "last_requested": datetime.now().isoformat(),
        }
        self._gaps.append(new_gap)
        self._save()
        logger.info(f"New tool gap logged: '{suggested_tool_name}' by {skill}")
        return gap_id

    def try_or_log(
        self,
        tool_name: str,
        action: str,
        skill: str,
        fallback: Callable[[], Any] | None = None,
        context: str = "",
        args: dict[str, Any] | None = None,
        issue_key: str | None = None,
    ) -> tuple[bool, Any]:
        """
        Try to use a tool, or log gap if it doesn't exist.

        This method checks if a tool exists in the registry. If not,
        it logs the gap and optionally executes a fallback.

        Args:
            tool_name: Name of the tool to try
            action: What the tool should do
            skill: Name of the skill calling this
            fallback: Optional fallback function to call if tool doesn't exist
            context: Additional context
            args: Suggested tool arguments
            issue_key: Related Jira issue

        Returns:
            (tool_existed, result_or_gap_id)
            - If tool exists: (True, None) - caller should use tool normally
            - If tool doesn't exist and fallback provided: (False, fallback_result)
            - If tool doesn't exist and no fallback: (False, gap_id)
        """
        # Check if tool exists
        # We try to import the tool registry, but if it fails, assume tool doesn't exist
        tool_exists = False
        try:
            # Try to check tool existence via the loaded tools
            # This is a simplified check - in practice you'd check the MCP tool registry
            from server.main import get_tool_registry

            registry = get_tool_registry()
            if registry and hasattr(registry, "tool_exists"):
                tool_exists = registry.tool_exists(tool_name)
            elif registry and hasattr(registry, "get_tool"):
                tool_exists = registry.get_tool(tool_name) is not None
        except ImportError:
            # If we can't import the registry, check a simpler way
            # Just assume the tool doesn't exist and log the gap
            pass
        except Exception as e:
            logger.debug(f"Error checking tool existence: {e}")

        if tool_exists:
            logger.debug(f"Tool '{tool_name}' exists, caller should use it")
            return True, None

        # Tool doesn't exist, log the gap
        workaround = "fallback provided" if fallback else None
        gap_id = self.log(
            suggested_tool_name=tool_name,
            action=action,
            skill=skill,
            context=context,
            args=args,
            workaround=workaround,
            issue_key=issue_key,
        )

        if fallback:
            try:
                result = fallback()
                logger.debug(f"Fallback for '{tool_name}' executed successfully")
                return False, result
            except Exception as e:
                logger.error(f"Fallback for '{tool_name}' failed: {e}")
                return False, gap_id

        return False, gap_id

    def get_gaps(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Get tool gaps, optionally filtered by status.

        Args:
            status: Filter by status (open, in_progress, implemented, rejected)
            limit: Maximum number of results

        Returns:
            List of gap dicts sorted by vote_count (most requested first)
        """
        gaps = self._gaps
        if status:
            gaps = [g for g in gaps if g.get("status") == status]

        # Sort by vote_count descending (most requested first)
        gaps = sorted(gaps, key=lambda g: g.get("vote_count", 1), reverse=True)
        return gaps[:limit]

    def get_most_requested(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most-requested tools for prioritization.

        Args:
            limit: Maximum number of results

        Returns:
            List of open gaps sorted by vote_count
        """
        return self.get_gaps(status="open", limit=limit)

    def update_status(self, gap_id: str, status: str) -> bool:
        """Update the status of a tool gap.

        Args:
            gap_id: Gap ID to update
            status: New status (open, in_progress, implemented, rejected)

        Returns:
            True if updated, False if not found
        """
        for gap in self._gaps:
            if gap.get("id") == gap_id:
                gap["status"] = status
                self._save()
                return True
        return False

    def get_by_skill(self, skill: str) -> list[dict[str, Any]]:
        """Get all gaps requested by a specific skill.

        Args:
            skill: Skill name

        Returns:
            List of gaps requested by this skill
        """
        return [g for g in self._gaps if skill in g.get("requesting_skills", [])]

    def format_summary(self, limit: int = 10) -> str:
        """Format a summary of most-requested tools.

        Args:
            limit: Maximum number to include

        Returns:
            Markdown-formatted summary
        """
        gaps = self.get_most_requested(limit=limit)

        if not gaps:
            return "No tool gaps recorded."

        lines = ["## Most Requested Tools\n"]
        for g in gaps:
            lines.append(f"### {g['suggested_tool_name']} ({g['vote_count']} requests)")
            lines.append(f"- **Action:** {g['desired_action']}")
            skills = g.get("requesting_skills", [])
            if skills:
                lines.append(f"- **Skills:** {', '.join(skills)}")
            if g.get("workaround_used"):
                lines.append(f"- **Workaround:** {g['workaround_used']}")
            if g.get("context"):
                lines.append(f"- **Context:** {g['context']}")
            lines.append("")

        return "\n".join(lines)

    def reload(self) -> None:
        """Reload gaps from disk (useful after external edits)."""
        self._load()


# Singleton instance for easy import
tool_gap = ToolGapDetector()
