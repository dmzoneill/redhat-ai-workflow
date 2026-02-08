"""
Sprint History Tracker — Work log management, context prompts, and history recording.

Extracted from SprintDaemon to keep history/logging logic separate from
daemon lifecycle and D-Bus orchestration.
"""

import logging
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Directory for background work logs
SPRINT_WORK_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_work"

logger = logging.getLogger(__name__)


class SprintHistoryTracker:
    """Manages work logs, continuation prompts, and Cursor context for sprint issues."""

    # ==================== Work Log Management ====================

    def get_work_log_path(self, issue_key: str) -> Path:
        """Get the path to the work log file for an issue."""
        return SPRINT_WORK_DIR / f"{issue_key}.yaml"

    def load_work_log(self, issue_key: str) -> dict:
        """Load the work log for an issue."""
        path = self.get_work_log_path(issue_key)
        if path.exists():
            import yaml

            return yaml.safe_load(path.read_text()) or {}
        return {}

    def save_work_log(self, issue_key: str, work_log: dict) -> None:
        """Save the work log for an issue."""
        import yaml

        SPRINT_WORK_DIR.mkdir(parents=True, exist_ok=True)
        path = self.get_work_log_path(issue_key)
        path.write_text(yaml.dump(work_log, default_flow_style=False, sort_keys=False))

    def init_work_log(self, issue: dict) -> dict:
        """Initialize a new work log for an issue."""
        return {
            "issue_key": issue["key"],
            "summary": issue.get("summary", ""),
            "description": issue.get("description", ""),
            "issue_type": issue.get("issueType", "Story"),
            "story_points": issue.get("storyPoints"),
            "jira_status": issue.get("jiraStatus", ""),
            "started": datetime.now().isoformat(),
            "status": "in_progress",
            "execution_mode": "background",
            "persona_used": "developer",
            "actions": [],
            "outcome": {
                "commits": [],
                "merge_requests": [],
                "files_changed": [],
                "branches_created": [],
            },
            # Context for loading into Cursor later
            "cursor_context": {
                "can_continue": True,
                "suggested_prompt": "",
                "files_to_review": [],
                "next_steps": [],
            },
        }

    def log_action(
        self, issue_key: str, action_type: str, details: str, data: dict = None
    ) -> None:
        """Log an action to the work log."""
        work_log = self.load_work_log(issue_key)
        if not work_log:
            return

        action = {
            "timestamp": datetime.now().isoformat(),
            "type": action_type,
            "details": details,
        }
        if data:
            action["data"] = data

        work_log.setdefault("actions", []).append(action)
        self.save_work_log(issue_key, work_log)

    # ==================== Context Prompts ====================

    def generate_continuation_prompt(self, issue_key: str, work_log: dict) -> str:
        """Generate a prompt for continuing work in Cursor."""
        status = work_log.get("status", "unknown")
        summary = work_log.get("summary", "")
        commits = work_log.get("outcome", {}).get("commits", [])
        mrs = work_log.get("outcome", {}).get("merge_requests", [])
        files = work_log.get("outcome", {}).get("files_changed", [])

        prompt_parts = [f"Continue working on {issue_key}: {summary}"]
        prompt_parts.append("")
        prompt_parts.append("## Background Work Summary")
        prompt_parts.append(f"- Status: {status}")

        if commits:
            prompt_parts.append(f"- Commits created: {', '.join(commits[:5])}")
        if mrs:
            prompt_parts.append(f"- Merge requests: {', '.join(mrs)}")
        if files:
            prompt_parts.append(f"- Files modified: {', '.join(files[:5])}")

        prompt_parts.append("")
        prompt_parts.append("## Next Steps")

        if status == "completed":
            prompt_parts.append("The background work completed successfully. Please:")
            prompt_parts.append("1. Review the changes made")
            prompt_parts.append("2. Run tests to verify the implementation")
            prompt_parts.append("3. Check if the MR needs any updates")
        elif status == "failed":
            prompt_parts.append("The background work failed. Please:")
            prompt_parts.append("1. Review the error in the work log")
            prompt_parts.append("2. Investigate the issue")
            prompt_parts.append("3. Complete the implementation")
        else:
            prompt_parts.append("Please review the work done and continue as needed.")

        return "\n".join(prompt_parts)

    def build_cursor_context_prompt(self, issue_key: str, work_log: dict) -> str:
        """Build a comprehensive context prompt for continuing work in Cursor."""
        parts = []

        # Header
        parts.append(f"# Continuing Work on {issue_key}")
        parts.append("")

        # Issue details
        parts.append("## Issue Details")
        parts.append(f"- **Summary**: {work_log.get('summary', 'N/A')}")
        parts.append(f"- **Type**: {work_log.get('issue_type', 'N/A')}")
        if work_log.get("story_points"):
            parts.append(f"- **Story Points**: {work_log.get('story_points')}")
        parts.append("")

        # Background work summary
        parts.append("## Background Work Summary")
        parts.append(f"- **Status**: {work_log.get('status', 'unknown')}")
        parts.append(f"- **Started**: {work_log.get('started', 'N/A')}")
        parts.append(f"- **Completed**: {work_log.get('completed', 'N/A')}")
        parts.append("")

        # Outcome
        outcome = work_log.get("outcome", {})
        if any(outcome.values()):
            parts.append("## Work Completed")
            if outcome.get("commits"):
                parts.append(f"- **Commits**: {', '.join(outcome['commits'][:5])}")
            if outcome.get("merge_requests"):
                parts.append(
                    f"- **Merge Requests**: {', '.join(outcome['merge_requests'])}"
                )
            if outcome.get("files_changed"):
                parts.append(
                    f"- **Files Changed**: {', '.join(outcome['files_changed'][:10])}"
                )
            if outcome.get("branches_created"):
                parts.append(
                    f"- **Branches**: {', '.join(outcome['branches_created'])}"
                )
            parts.append("")

        # Actions log (last 10)
        actions = work_log.get("actions", [])
        if actions:
            parts.append("## Recent Actions")
            for action in actions[-10:]:
                timestamp = action.get("timestamp", "")[:19]  # Trim to datetime
                action_type = action.get("type", "")
                details = action.get("details", "")
                parts.append(f"- [{timestamp}] **{action_type}**: {details}")
            parts.append("")

        # Suggested next steps
        cursor_context = work_log.get("cursor_context", {})
        if cursor_context.get("suggested_prompt"):
            parts.append("## Suggested Next Steps")
            parts.append(cursor_context["suggested_prompt"])
            parts.append("")

        # Files to review
        if cursor_context.get("files_to_review"):
            parts.append("## Files to Review")
            for f in cursor_context["files_to_review"]:
                parts.append(f"- `{f}`")
            parts.append("")

        # Error info if failed
        if work_log.get("error"):
            parts.append("## Error Information")
            parts.append(f"```\n{work_log['error']}\n```")
            parts.append("")

        # Instructions
        parts.append("---")
        parts.append(
            "Please review the above context and continue working on this issue."
        )
        parts.append(
            'Load the developer persona if needed: `persona_load("developer")`'
        )

        return "\n".join(parts)
