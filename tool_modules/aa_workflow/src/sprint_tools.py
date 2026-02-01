"""Sprint Bot MCP Tools - Expose sprint functionality to Claude.

These tools allow Claude to:
- Load and refresh sprint issues
- Enable/disable the sprint bot
- Approve/skip individual issues
- Check sprint status
- View sprint history
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastmcp import Context

# Support both package import and direct loading
try:
    from .sprint_bot import (
        SprintBotConfig,
        WorkingHours,
        approve_issue,
        disable_sprint_bot,
        enable_sprint_bot,
        get_sprint_status,
        is_within_working_hours,
        refresh_sprint_state,
        skip_issue,
    )
    from .sprint_history import (
        SprintIssue,
        TimelineEvent,
        add_timeline_event,
        load_sprint_history,
        load_sprint_state,
        save_sprint_state,
    )
    from .sprint_prioritizer import get_priority_summary, prioritize_issues
except ImportError:
    from sprint_bot import (
        SprintBotConfig,
        WorkingHours,
        approve_issue,
        disable_sprint_bot,
        enable_sprint_bot,
        get_sprint_status,
        is_within_working_hours,
        refresh_sprint_state,
        skip_issue,
    )
    from sprint_history import (
        SprintIssue,
        TimelineEvent,
        add_timeline_event,
        load_sprint_history,
        load_sprint_state,
        save_sprint_state,
    )
    from sprint_prioritizer import get_priority_summary, prioritize_issues

logger = logging.getLogger(__name__)

# Statuses that are actionable (bot can work on these)
ACTIONABLE_STATUSES = ["new", "refinement", "to do", "open", "backlog"]


def is_actionable(issue: SprintIssue) -> bool:
    """Check if an issue is actionable based on its Jira status.

    Bot should only work on issues in New/Refinement/Backlog.
    Issues in Review/Done/Release Pending should be ignored.
    """
    jira_status = (issue.jira_status or "").lower()
    return any(s in jira_status for s in ACTIONABLE_STATUSES)


def sprint_load(
    project: str = "AAP",
    refresh: bool = True,
) -> str:
    """
    Load sprint issues from Jira and prioritize them.

    Fetches issues from the active sprint, prioritizes them based on
    story points, priority, age, and type, then returns the ordered list
    with reasoning for each prioritization decision.

    Args:
        project: Jira project key (default: AAP)
        refresh: If True, fetch fresh data from Jira. If False, use cached state.

    Returns:
        Formatted sprint summary with prioritized issues.
    """
    try:
        if refresh:
            config = SprintBotConfig(
                working_hours=WorkingHours(),
                jira_project=project,
            )
            state = refresh_sprint_state(config)
        else:
            state = load_sprint_state()

        if not state.issues:
            return "No sprint issues found. Make sure there's an active sprint in Jira."

        # Split into actionable and not actionable
        actionable_issues = [i for i in state.issues if is_actionable(i)]
        not_actionable_issues = [i for i in state.issues if not is_actionable(i)]

        # Build summary
        lines = [
            "## Current Sprint",
            f"**Last Updated:** {state.last_updated}",
            f"**Bot Enabled:** {'Yes' if state.bot_enabled else 'No'}",
            f"**Total Issues:** {len(state.issues)} ({len(actionable_issues)} actionable, {len(not_actionable_issues)} not actionable)",
            "",
        ]

        if state.processing_issue:
            lines.append(f"**Currently Processing:** {state.processing_issue}")
            lines.append("")

        # Show actionable issues first
        if actionable_issues:
            lines.append(f"### ✅ Actionable Issues ({len(actionable_issues)})")
            lines.append("*Issues in New/Refinement - bot can work on these*")
            lines.append("")

            for issue in actionable_issues:
                pts = f"[{issue.story_points}pts]" if issue.story_points else "[?pts]"
                status_icon = {"pending": "⏳", "approved": "✅", "in_progress": "🔄", "blocked": "🔴"}.get(
                    issue.approval_status, "•"
                )
                lines.append(f"- {status_icon} **{issue.key}** {pts} ({issue.jira_status}) {issue.summary[:50]}...")
                if issue.priority_reasoning:
                    lines.append(f"  - Reasoning: {', '.join(issue.priority_reasoning[:2])}")

            lines.append("")

        # Show not actionable issues
        if not_actionable_issues:
            lines.append(f"### 🚫 Not Actionable ({len(not_actionable_issues)})")
            lines.append("*Issues in Review/Done/etc - bot will not touch these*")
            lines.append("")

            for issue in not_actionable_issues:
                pts = f"[{issue.story_points}pts]" if issue.story_points else "[?pts]"
                lines.append(f"- ~~**{issue.key}**~~ {pts} ({issue.jira_status}) {issue.summary[:50]}...")

            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.exception(f"sprint_load error: {e}")
        return f"Error loading sprint: {str(e)}"


def sprint_enable() -> str:
    """
    Enable the sprint bot to automatically work on approved issues.

    When enabled, the bot will:
    - Run during working hours (Mon-Fri, 9am-5pm)
    - Process approved issues sequentially
    - Create Cursor chats for each issue
    - Skip blocked/waiting issues

    Returns:
        Confirmation message.
    """
    result = enable_sprint_bot()

    if result["success"]:
        return "✅ Sprint bot enabled! It will process approved issues during working hours."
    else:
        return f"❌ Failed to enable sprint bot: {result.get('message', 'Unknown error')}"


def sprint_disable() -> str:
    """
    Disable the sprint bot.

    Stops the bot from automatically processing issues.
    Any issue currently being processed will be left in its current state.

    Returns:
        Confirmation message.
    """
    result = disable_sprint_bot()

    if result["success"]:
        return "🛑 Sprint bot disabled. No more issues will be automatically processed."
    else:
        return f"❌ Failed to disable sprint bot: {result.get('message', 'Unknown error')}"


def sprint_approve(issue_key: str) -> str:
    """
    Approve an issue for the sprint bot to work on.

    The bot will pick up approved issues in priority order.
    Only issues in actionable statuses (New/Refinement/Backlog) can be approved.

    Args:
        issue_key: Jira issue key (e.g., "AAP-12345")

    Returns:
        Confirmation message.
    """
    if not issue_key:
        return "❌ Please provide an issue key (e.g., AAP-12345)"

    # Check if issue is actionable first
    state = load_sprint_state()
    issue = None
    for i in state.issues:
        if i.key == issue_key:
            issue = i
            break

    if not issue:
        return f"❌ Issue {issue_key} not found in current sprint."

    if not is_actionable(issue):
        return (
            f"❌ Issue {issue_key} is not actionable (status: {issue.jira_status}).\n"
            f"Bot only works on issues in New/Refinement/Backlog.\n"
            f"Issues in Review/Done are managed by the user."
        )

    result = approve_issue(issue_key)

    if result["success"]:
        return f"✅ Issue {issue_key} approved for sprint bot processing."
    else:
        return f"❌ {result.get('message', 'Failed to approve issue')}"


def sprint_skip(issue_key: str, reason: str = "") -> str:
    """
    Skip/block an issue from sprint bot processing.

    Use this when an issue is blocked, needs clarification, or you want
    to handle it manually.

    Args:
        issue_key: Jira issue key (e.g., "AAP-12345")
        reason: Reason for skipping (optional)

    Returns:
        Confirmation message.
    """
    if not issue_key:
        return "❌ Please provide an issue key (e.g., AAP-12345)"

    skip_reason = reason or "Manually skipped"
    result = skip_issue(issue_key, skip_reason)

    if result["success"]:
        return f"⏭️ Issue {issue_key} skipped: {skip_reason}"
    else:
        return f"❌ {result.get('message', 'Failed to skip issue')}"


def sprint_status() -> str:
    """
    Get current sprint bot status and statistics.

    Shows:
    - Bot enabled/disabled state
    - Currently processing issue (if any)
    - Issue counts by status
    - Actionable vs not actionable breakdown
    - Working hours status

    Returns:
        Formatted status summary.
    """
    status = get_sprint_status()
    state = load_sprint_state()

    # Count actionable issues
    actionable_count = sum(1 for i in state.issues if is_actionable(i))
    not_actionable_count = len(state.issues) - actionable_count

    # Check working hours
    config = WorkingHours()
    in_hours = is_within_working_hours(config)

    lines = [
        "## Sprint Bot Status",
        "",
        f"**Bot Enabled:** {'✅ Yes' if status['bot_enabled'] else '❌ No'}",
        f"**Working Hours:** {'✅ Active' if in_hours else '💤 Outside hours'}",
        f"**Last Updated:** {status['last_updated']}",
        "",
    ]

    if status["processing_issue"]:
        lines.append(f"**Currently Processing:** {status['processing_issue']}")
        lines.append("")

    lines.append(f"### Issues ({status['total_issues']} total)")
    lines.append(f"- ✅ Actionable (New/Refinement): {actionable_count}")
    lines.append(f"- 🚫 Not Actionable (Review/Done): {not_actionable_count}")
    lines.append("")

    lines.append("### By Approval Status")

    status_icons = {
        "in_progress": "🔄",
        "approved": "✅",
        "pending": "⏳",
        "waiting": "❓",
        "blocked": "🔴",
        "completed": "✔️",
    }

    for status_name, count in status["status_counts"].items():
        icon = status_icons.get(status_name, "•")
        lines.append(f"- {icon} {status_name.replace('_', ' ').title()}: {count}")

    return "\n".join(lines)


def sprint_history(limit: int = 5) -> str:
    """
    View completed sprint history.

    Shows previous sprints with completion statistics.

    Args:
        limit: Maximum number of sprints to show (default: 5)

    Returns:
        Formatted sprint history.
    """
    history = load_sprint_history(limit=limit)

    if not history:
        return "No sprint history found."

    lines = ["## Sprint History", ""]

    for sprint in history:
        completion_pct = (sprint.completed_points / sprint.total_points * 100) if sprint.total_points > 0 else 0

        lines.append(f"### {sprint.name}")
        lines.append(f"- **Period:** {sprint.start_date[:10]} to {sprint.end_date[:10]}")
        lines.append(f"- **Points:** {sprint.completed_points}/{sprint.total_points} ({completion_pct:.0f}%)")
        lines.append(f"- **Issues:** {len(sprint.issues)}")
        lines.append("")

    return "\n".join(lines)


def sprint_timeline(issue_key: str) -> str:
    """
    View timeline events for a specific issue.

    Shows all actions taken on the issue by the sprint bot.

    Args:
        issue_key: Jira issue key (e.g., "AAP-12345")

    Returns:
        Formatted timeline.
    """
    state = load_sprint_state()

    issue = None
    for i in state.issues:
        if i.key == issue_key:
            issue = i
            break

    if not issue:
        return f"Issue {issue_key} not found in current sprint."

    lines = [
        f"## Timeline: {issue_key}",
        f"**{issue.summary}**",
        f"**Status:** {issue.approval_status}",
        "",
    ]

    if not issue.timeline:
        lines.append("No timeline events yet.")
    else:
        for event in issue.timeline:
            timestamp = event.timestamp[:16].replace("T", " ")
            lines.append(f"- **{timestamp}** [{event.action}] {event.description}")
            if event.chat_link:
                lines.append(f"  - Chat: {event.chat_link}")
            if event.jira_link:
                lines.append(f"  - Jira: {event.jira_link}")

    return "\n".join(lines)


def sprint_approve_all() -> str:
    """
    Approve all pending actionable issues in the sprint.

    Only approves issues in actionable statuses (New/Refinement/Backlog).
    Issues in Review/Done are skipped automatically.

    Returns:
        Confirmation message with count.
    """
    state = load_sprint_state()

    approved_count = 0
    skipped_count = 0

    for issue in state.issues:
        if issue.approval_status == "pending":
            if is_actionable(issue):
                issue.approval_status = "approved"
                issue.timeline.append(
                    TimelineEvent(
                        timestamp=datetime.now().isoformat(),
                        action="approved",
                        description="Bulk approved for sprint bot",
                    )
                )
                approved_count += 1
            else:
                # Mark as completed since it's not actionable
                issue.approval_status = "completed"
                skipped_count += 1

    if approved_count > 0 or skipped_count > 0:
        state.last_updated = datetime.now().isoformat()
        save_sprint_state(state)

        msg = f"✅ Approved {approved_count} actionable issues for sprint bot processing."
        if skipped_count > 0:
            msg += f"\n🚫 Skipped {skipped_count} non-actionable issues (in Review/Done)."
        return msg
    else:
        return "No pending issues to approve."


# Register tools with MCP server
def register_sprint_tools(mcp) -> int:
    """Register sprint tools with the MCP server.

    Args:
        mcp: FastMCP server instance

    Returns:
        Number of tools registered
    """
    mcp.tool()(sprint_load)
    mcp.tool()(sprint_enable)
    mcp.tool()(sprint_disable)
    mcp.tool()(sprint_approve)
    mcp.tool()(sprint_skip)
    mcp.tool()(sprint_status)
    mcp.tool()(sprint_history)
    mcp.tool()(sprint_timeline)
    mcp.tool()(sprint_approve_all)

    logger.info("Sprint tools registered (9 tools)")
    return 9
