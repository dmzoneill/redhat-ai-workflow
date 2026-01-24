"""Sprint Issue Prioritizer - Orders issues with reasoning capture.

Determines work order based on:
- Story points (lower points first for quick wins)
- Priority (Blocker > Critical > Major > Minor)
- Dependencies (blocked issues last)
- Type (bugs before features)
- Age (older issues first)
- Waiting status (issues awaiting clarification deprioritized)

The reasoning is captured for each decision and displayed in the Sprint Board UI.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PrioritizedIssue:
    """An issue with its priority score and reasoning."""

    key: str
    summary: str
    rank: int
    score: float
    reasoning: list[str] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)

    # Original issue data
    story_points: int = 0
    priority: str = "Major"
    issue_type: str = "Story"
    status: str = "New"
    created: str = ""
    assignee: str = ""
    is_blocked: bool = False
    waiting_reason: str | None = None


# Priority weights (higher = more important)
PRIORITY_SCORES = {
    "blocker": 100,
    "critical": 80,
    "major": 50,
    "minor": 20,
    "trivial": 10,
}

# Issue type weights (higher = prioritized)
TYPE_SCORES = {
    "bug": 30,
    "defect": 30,
    "incident": 25,
    "task": 20,
    "story": 15,
    "feature": 10,
    "epic": 5,
    "improvement": 10,
}


def calculate_age_score(created_date: str) -> tuple[float, str]:
    """Calculate age score - older issues get higher scores.

    Returns (score, reasoning_text)
    """
    if not created_date:
        return 0, ""

    try:
        # Parse ISO date
        if "T" in created_date:
            created = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
        else:
            created = datetime.strptime(created_date[:10], "%Y-%m-%d")

        age_days = (datetime.now(created.tzinfo) - created).days

        if age_days > 30:
            return 30, f"Aging issue ({age_days} days old)"
        elif age_days > 14:
            return 20, f"Getting stale ({age_days} days)"
        elif age_days > 7:
            return 10, f"Week old ({age_days} days)"
        else:
            return 5, f"Recent ({age_days} days)"
    except (ValueError, TypeError):
        return 0, ""


def calculate_points_score(story_points: int | None) -> tuple[float, str]:
    """Calculate points score - lower points get higher scores (quick wins).

    Returns (score, reasoning_text)
    """
    if story_points is None or story_points == 0:
        return 10, "Unestimated (medium priority)"

    if story_points <= 2:
        return 40, f"Quick win ({story_points} pts)"
    elif story_points <= 5:
        return 30, f"Medium effort ({story_points} pts)"
    elif story_points <= 8:
        return 20, f"Larger effort ({story_points} pts)"
    else:
        return 10, f"Large item ({story_points} pts)"


def prioritize_issues(issues: list[dict[str, Any]], config: dict[str, Any] | None = None) -> list[PrioritizedIssue]:
    """Order issues by weighted score, capturing reasoning for UI display.

    Args:
        issues: List of issue dicts with keys like 'key', 'summary', 'priority', etc.
        config: Optional config with prioritization weights

    Returns:
        List of PrioritizedIssue sorted by score (highest first)
    """
    config = config or {}
    weights = config.get(
        "prioritization",
        {
            "points_weight": 0.3,
            "priority_weight": 0.4,
            "age_weight": 0.2,
            "type_weight": 0.1,
        },
    )

    prioritized: list[PrioritizedIssue] = []

    for issue in issues:
        key = issue.get("key", "")
        summary = issue.get("summary", "")
        priority = issue.get("priority", "Major").lower()
        issue_type = issue.get("issuetype", issue.get("type", "Story")).lower()
        story_points = issue.get("storyPoints", issue.get("story_points", 0))
        created = issue.get("created", "")
        status = issue.get("status", "New")
        assignee = issue.get("assignee", "")

        # Check for blocked/waiting status
        is_blocked = issue.get("blocked", False) or "blocked" in status.lower()
        waiting_reason = issue.get("waitingReason", issue.get("waiting_reason"))

        reasoning: list[str] = []
        factors: dict[str, float] = {}

        # Calculate component scores
        priority_score = PRIORITY_SCORES.get(priority, 30)
        factors["priority"] = priority_score
        if priority in ["blocker", "critical"]:
            reasoning.append(f"High priority ({priority.title()})")

        type_score = TYPE_SCORES.get(issue_type, 15)
        factors["type"] = type_score
        if issue_type in ["bug", "defect", "incident"]:
            reasoning.append(f"{issue_type.title()} type (fix first)")

        points_score, points_reason = calculate_points_score(story_points)
        factors["points"] = points_score
        if points_reason:
            reasoning.append(points_reason)

        age_score, age_reason = calculate_age_score(created)
        factors["age"] = age_score
        if age_reason:
            reasoning.append(age_reason)

        # Apply weights
        weighted_score = (
            priority_score * weights.get("priority_weight", 0.4)
            + type_score * weights.get("type_weight", 0.1)
            + points_score * weights.get("points_weight", 0.3)
            + age_score * weights.get("age_weight", 0.2)
        )

        # Penalties
        if is_blocked:
            weighted_score *= 0.3  # Heavy penalty for blocked
            reasoning.append("Blocked (deprioritized)")
            factors["blocked_penalty"] = -weighted_score * 0.7

        if waiting_reason:
            weighted_score *= 0.5  # Penalty for waiting
            reasoning.append(f"Waiting: {waiting_reason[:50]}")
            factors["waiting_penalty"] = -weighted_score * 0.5

        prioritized.append(
            PrioritizedIssue(
                key=key,
                summary=summary,
                rank=0,  # Will be set after sorting
                score=weighted_score,
                reasoning=reasoning,
                factors=factors,
                story_points=story_points or 0,
                priority=priority.title(),
                issue_type=issue_type.title(),
                status=status,
                created=created,
                assignee=assignee,
                is_blocked=is_blocked,
                waiting_reason=waiting_reason,
            )
        )

    # Sort by score (highest first)
    prioritized.sort(key=lambda x: x.score, reverse=True)

    # Assign ranks
    for i, issue in enumerate(prioritized):
        issue.rank = i + 1

    return prioritized


def get_priority_summary(prioritized: list[PrioritizedIssue]) -> str:
    """Generate a summary of the prioritization for display.

    Args:
        prioritized: List of prioritized issues

    Returns:
        Markdown-formatted summary
    """
    if not prioritized:
        return "No issues to prioritize."

    lines = ["## Sprint Priority Order\n"]

    for issue in prioritized[:10]:  # Top 10
        status_icon = "🔴" if issue.is_blocked else ("⏳" if issue.waiting_reason else "🟢")
        lines.append(f"### {issue.rank}. {status_icon} {issue.key}")
        lines.append(f"**{issue.summary}**")
        lines.append(f"- Score: {issue.score:.1f}")
        lines.append(f"- Points: {issue.story_points or '?'} | Priority: {issue.priority}")
        if issue.reasoning:
            lines.append(f"- Reasoning: {', '.join(issue.reasoning)}")
        lines.append("")

    return "\n".join(lines)


def to_sprint_issue_format(prioritized: list[PrioritizedIssue]) -> list[dict[str, Any]]:
    """Convert prioritized issues to the format expected by the Sprint Tab UI.

    Args:
        prioritized: List of prioritized issues

    Returns:
        List of dicts matching SprintIssue interface
    """
    return [
        {
            "key": issue.key,
            "summary": issue.summary,
            "storyPoints": issue.story_points,
            "priority": issue.priority,
            "jiraStatus": issue.status,
            "assignee": issue.assignee,
            "approvalStatus": "blocked" if issue.is_blocked else ("waiting" if issue.waiting_reason else "pending"),
            "waitingReason": issue.waiting_reason,
            "priorityReasoning": issue.reasoning,
            "estimatedActions": ["start_work", "implement", "create_mr"],
            "chatId": None,
            "timeline": [],
            "issueType": issue.issue_type,
            "created": issue.created,
        }
        for issue in prioritized
    ]
