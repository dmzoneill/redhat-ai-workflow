"""Work log management for Sprint Daemon."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
SPRINT_WORK_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_work"


class SprintWorkLogMixin:
    """Mixin providing work log CRUD and action logging."""

    def _get_work_log_path(self, issue_key: str) -> Path:
        """Get the path to the work log file for an issue."""
        return SPRINT_WORK_DIR / f"{issue_key}.yaml"

    def _load_work_log(self, issue_key: str) -> dict:
        """Load the work log for an issue."""
        path = self._get_work_log_path(issue_key)
        if path.exists():
            import yaml

            return yaml.safe_load(path.read_text()) or {}
        return {}

    def _save_work_log(self, issue_key: str, work_log: dict) -> None:
        """Save the work log for an issue."""
        import yaml

        SPRINT_WORK_DIR.mkdir(parents=True, exist_ok=True)
        path = self._get_work_log_path(issue_key)
        path.write_text(yaml.dump(work_log, default_flow_style=False, sort_keys=False))

    def _init_work_log(self, issue: dict) -> dict:
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

    def _log_action(
        self, issue_key: str, action_type: str, details: str, data: dict = None
    ) -> None:
        """Log an action to the work log."""
        work_log = self._load_work_log(issue_key)
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
        self._save_work_log(issue_key, work_log)
