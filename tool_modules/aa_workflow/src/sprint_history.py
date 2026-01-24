"""Sprint History Storage - Manages completed sprints and timeline events.

Stores sprint history in ~/.config/aa-workflow/sprint_history.json
with support for:
- Saving completed sprints
- Loading history with pagination
- Adding timeline events to issues
- Archiving old sprints
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Storage paths
SPRINT_STATE_FILE = Path.home() / ".config" / "aa-workflow" / "sprint_state.json"
SPRINT_HISTORY_FILE = Path.home() / ".config" / "aa-workflow" / "sprint_history.json"


@dataclass
class TimelineEvent:
    """An event in an issue's timeline."""

    timestamp: str
    action: str
    description: str
    chat_link: str | None = None
    jira_link: str | None = None


@dataclass
class SprintIssue:
    """An issue in a sprint with its state and timeline."""

    key: str
    summary: str
    story_points: int = 0
    priority: str = "Major"
    jira_status: str = "New"
    assignee: str = ""
    approval_status: str = "pending"
    waiting_reason: str | None = None
    priority_reasoning: list[str] = field(default_factory=list)
    estimated_actions: list[str] = field(default_factory=list)
    chat_id: str | None = None
    timeline: list[TimelineEvent] = field(default_factory=list)
    issue_type: str = "Story"
    created: str = ""


@dataclass
class CompletedSprint:
    """A completed sprint with its issues and metadata."""

    id: str
    name: str
    start_date: str
    end_date: str
    total_points: int
    completed_points: int
    issues: list[SprintIssue] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    collapsed: bool = True  # Default collapsed in UI


@dataclass
class SprintState:
    """Current sprint state."""

    current_sprint: dict[str, Any] | None = None
    issues: list[SprintIssue] = field(default_factory=list)
    bot_enabled: bool = False
    last_updated: str = ""
    processing_issue: str | None = None


def ensure_storage_dir() -> None:
    """Ensure the storage directory exists."""
    SPRINT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_sprint_state() -> SprintState:
    """Load current sprint state from file.

    Returns:
        SprintState with current sprint data
    """
    if not SPRINT_STATE_FILE.exists():
        return SprintState(last_updated=datetime.now().isoformat())

    try:
        with open(SPRINT_STATE_FILE) as f:
            data = json.load(f)

        issues = []
        for issue_data in data.get("issues", []):
            timeline = [TimelineEvent(**e) if isinstance(e, dict) else e for e in issue_data.get("timeline", [])]
            issue = SprintIssue(
                key=issue_data.get("key", ""),
                summary=issue_data.get("summary", ""),
                story_points=issue_data.get("storyPoints", issue_data.get("story_points", 0)),
                priority=issue_data.get("priority", "Major"),
                jira_status=issue_data.get("jiraStatus", issue_data.get("jira_status", "New")),
                assignee=issue_data.get("assignee", ""),
                approval_status=issue_data.get("approvalStatus", issue_data.get("approval_status", "pending")),
                waiting_reason=issue_data.get("waitingReason", issue_data.get("waiting_reason")),
                priority_reasoning=issue_data.get("priorityReasoning", issue_data.get("priority_reasoning", [])),
                estimated_actions=issue_data.get("estimatedActions", issue_data.get("estimated_actions", [])),
                chat_id=issue_data.get("chatId", issue_data.get("chat_id")),
                timeline=timeline,
                issue_type=issue_data.get("issueType", issue_data.get("issue_type", "Story")),
                created=issue_data.get("created", ""),
            )
            issues.append(issue)

        return SprintState(
            current_sprint=data.get("currentSprint", data.get("current_sprint")),
            issues=issues,
            bot_enabled=data.get("botEnabled", data.get("bot_enabled", False)),
            last_updated=data.get("lastUpdated", data.get("last_updated", "")),
            processing_issue=data.get("processingIssue", data.get("processing_issue")),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to load sprint state: {e}")
        return SprintState(last_updated=datetime.now().isoformat())


def save_sprint_state(state: SprintState) -> None:
    """Save current sprint state to file.

    Args:
        state: SprintState to save
    """
    ensure_storage_dir()

    # Convert to JSON-serializable format (camelCase for JS compatibility)
    data = {
        "currentSprint": state.current_sprint,
        "issues": [
            {
                "key": issue.key,
                "summary": issue.summary,
                "storyPoints": issue.story_points,
                "priority": issue.priority,
                "jiraStatus": issue.jira_status,
                "assignee": issue.assignee,
                "approvalStatus": issue.approval_status,
                "waitingReason": issue.waiting_reason,
                "priorityReasoning": issue.priority_reasoning,
                "estimatedActions": issue.estimated_actions,
                "chatId": issue.chat_id,
                "timeline": [
                    {
                        "timestamp": e.timestamp,
                        "action": e.action,
                        "description": e.description,
                        "chatLink": e.chat_link,
                        "jiraLink": e.jira_link,
                    }
                    for e in issue.timeline
                ],
                "issueType": issue.issue_type,
                "created": issue.created,
            }
            for issue in state.issues
        ],
        "botEnabled": state.bot_enabled,
        "lastUpdated": state.last_updated or datetime.now().isoformat(),
        "processingIssue": state.processing_issue,
    }

    with open(SPRINT_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_sprint_history(limit: int = 10) -> list[CompletedSprint]:
    """Load previous sprints from history file.

    Args:
        limit: Maximum number of sprints to return

    Returns:
        List of CompletedSprint, most recent first
    """
    if not SPRINT_HISTORY_FILE.exists():
        return []

    try:
        with open(SPRINT_HISTORY_FILE) as f:
            data = json.load(f)

        sprints = []
        for sprint_data in data.get("sprints", [])[:limit]:
            issues = []
            for issue_data in sprint_data.get("issues", []):
                timeline = [
                    TimelineEvent(
                        timestamp=e.get("timestamp", ""),
                        action=e.get("action", ""),
                        description=e.get("description", ""),
                        chat_link=e.get("chatLink", e.get("chat_link")),
                        jira_link=e.get("jiraLink", e.get("jira_link")),
                    )
                    for e in issue_data.get("timeline", [])
                ]
                issue = SprintIssue(
                    key=issue_data.get("key", ""),
                    summary=issue_data.get("summary", ""),
                    story_points=issue_data.get("storyPoints", issue_data.get("story_points", 0)),
                    priority=issue_data.get("priority", "Major"),
                    jira_status=issue_data.get("jiraStatus", issue_data.get("jira_status", "Done")),
                    assignee=issue_data.get("assignee", ""),
                    approval_status=issue_data.get("approvalStatus", issue_data.get("approval_status", "completed")),
                    timeline=timeline,
                )
                issues.append(issue)

            sprint_timeline = [
                TimelineEvent(
                    timestamp=e.get("timestamp", ""),
                    action=e.get("action", ""),
                    description=e.get("description", ""),
                    chat_link=e.get("chatLink", e.get("chat_link")),
                    jira_link=e.get("jiraLink", e.get("jira_link")),
                )
                for e in sprint_data.get("timeline", [])
            ]

            sprint = CompletedSprint(
                id=sprint_data.get("id", ""),
                name=sprint_data.get("name", ""),
                start_date=sprint_data.get("startDate", sprint_data.get("start_date", "")),
                end_date=sprint_data.get("endDate", sprint_data.get("end_date", "")),
                total_points=sprint_data.get("totalPoints", sprint_data.get("total_points", 0)),
                completed_points=sprint_data.get("completedPoints", sprint_data.get("completed_points", 0)),
                issues=issues,
                timeline=sprint_timeline,
                collapsed=sprint_data.get("collapsed", True),
            )
            sprints.append(sprint)

        return sprints
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to load sprint history: {e}")
        return []


def save_sprint_to_history(sprint: CompletedSprint) -> None:
    """Save a completed sprint to history.

    Args:
        sprint: CompletedSprint to archive
    """
    ensure_storage_dir()

    # Load existing history
    history = load_sprint_history(limit=100)  # Load more for archiving

    # Add new sprint at the beginning
    history.insert(0, sprint)

    # Convert to JSON-serializable format
    data = {
        "sprints": [
            {
                "id": s.id,
                "name": s.name,
                "startDate": s.start_date,
                "endDate": s.end_date,
                "totalPoints": s.total_points,
                "completedPoints": s.completed_points,
                "issues": [
                    {
                        "key": issue.key,
                        "summary": issue.summary,
                        "storyPoints": issue.story_points,
                        "priority": issue.priority,
                        "jiraStatus": issue.jira_status,
                        "approvalStatus": issue.approval_status,
                        "timeline": [
                            {
                                "timestamp": e.timestamp,
                                "action": e.action,
                                "description": e.description,
                                "chatLink": e.chat_link,
                                "jiraLink": e.jira_link,
                            }
                            for e in issue.timeline
                        ],
                    }
                    for issue in s.issues
                ],
                "timeline": [
                    {
                        "timestamp": e.timestamp,
                        "action": e.action,
                        "description": e.description,
                        "chatLink": e.chat_link,
                        "jiraLink": e.jira_link,
                    }
                    for e in s.timeline
                ],
                "collapsed": s.collapsed,
            }
            for s in history
        ],
        "lastUpdated": datetime.now().isoformat(),
    }

    with open(SPRINT_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def add_timeline_event(issue_key: str, event: TimelineEvent) -> bool:
    """Add a timeline event to an issue in the current sprint.

    Args:
        issue_key: Jira issue key (e.g., "AAP-12345")
        event: TimelineEvent to add

    Returns:
        True if event was added, False if issue not found
    """
    state = load_sprint_state()

    for issue in state.issues:
        if issue.key == issue_key:
            issue.timeline.append(event)
            state.last_updated = datetime.now().isoformat()
            save_sprint_state(state)
            return True

    logger.warning(f"Issue {issue_key} not found in current sprint")
    return False


def update_issue_status(
    issue_key: str,
    approval_status: str,
    waiting_reason: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Update an issue's status in the current sprint.

    Args:
        issue_key: Jira issue key
        approval_status: New approval status
        waiting_reason: Optional reason if status is "waiting"
        chat_id: Optional chat ID to associate

    Returns:
        True if updated, False if issue not found
    """
    state = load_sprint_state()

    for issue in state.issues:
        if issue.key == issue_key:
            issue.approval_status = approval_status
            if waiting_reason is not None:
                issue.waiting_reason = waiting_reason
            if chat_id is not None:
                issue.chat_id = chat_id

            # Add timeline event
            issue.timeline.append(
                TimelineEvent(
                    timestamp=datetime.now().isoformat(),
                    action="status_changed",
                    description=f"Status changed to {approval_status}"
                    + (f" ({waiting_reason})" if waiting_reason else ""),
                )
            )

            state.last_updated = datetime.now().isoformat()
            save_sprint_state(state)
            return True

    return False


# Statuses that are actionable (bot can work on these)
ACTIONABLE_STATUSES = ["new", "refinement", "to do", "open", "backlog"]


def is_actionable(issue: SprintIssue) -> bool:
    """Check if an issue is actionable based on its Jira status.

    Bot should only work on issues in New/Refinement/Backlog.
    Issues in Review/Done/Release Pending should be ignored.
    """
    jira_status = (issue.jira_status or "").lower()
    return any(s in jira_status for s in ACTIONABLE_STATUSES)


def get_next_issue_to_process(state: SprintState | None = None) -> SprintIssue | None:
    """Get the next issue that should be processed by the bot.

    Skips blocked, waiting, and non-actionable issues.
    Only returns issues in actionable Jira statuses (New/Refinement/Backlog).

    Args:
        state: Optional pre-loaded state

    Returns:
        Next SprintIssue to process, or None if none available
    """
    if state is None:
        state = load_sprint_state()

    # Find approved issues that are actionable
    for issue in state.issues:
        if issue.approval_status == "approved" and is_actionable(issue):
            return issue
        if issue.approval_status == "in_progress" and state.processing_issue == issue.key and is_actionable(issue):
            return issue

    return None


def complete_current_sprint() -> CompletedSprint | None:
    """Complete the current sprint and archive it.

    Returns:
        The archived CompletedSprint, or None if no current sprint
    """
    state = load_sprint_state()

    if not state.current_sprint:
        return None

    # Calculate completion stats
    total_points = sum(i.story_points for i in state.issues)
    completed_points = sum(i.story_points for i in state.issues if i.approval_status == "completed")

    # Create completed sprint
    completed = CompletedSprint(
        id=state.current_sprint.get("id", ""),
        name=state.current_sprint.get("name", ""),
        start_date=state.current_sprint.get("startDate", state.current_sprint.get("start_date", "")),
        end_date=datetime.now().isoformat(),
        total_points=total_points,
        completed_points=completed_points,
        issues=state.issues,
        timeline=[
            TimelineEvent(
                timestamp=datetime.now().isoformat(),
                action="sprint_completed",
                description=f"Sprint completed: {completed_points}/{total_points} points",
            )
        ],
        collapsed=True,
    )

    # Save to history
    save_sprint_to_history(completed)

    # Clear current state
    new_state = SprintState(
        current_sprint=None,
        issues=[],
        bot_enabled=False,
        last_updated=datetime.now().isoformat(),
        processing_issue=None,
    )
    save_sprint_state(new_state)

    return completed
