"""Shared Slack utilities.

Provides consistent Slack message formatting across skills.
"""

from typing import Optional

from scripts.common.config_loader import get_jira_url, get_team_group_handle, get_team_group_id


def build_team_mention(group_id: Optional[str] = None, group_handle: Optional[str] = None) -> str:
    """
    Build a Slack team mention string.

    Args:
        group_id: Slack user group ID (e.g., "S1234ABCD") - defaults to config
        group_handle: Fallback handle if no group_id - defaults to config

    Returns:
        Formatted mention string: <!subteam^ID|@handle> or @handle
    """
    if group_id is None:
        group_id = get_team_group_id()
    if group_handle is None:
        group_handle = get_team_group_handle()

    if group_id:
        return f"<!subteam^{group_id}|@{group_handle}>"
    return f"@{group_handle}"


def build_mr_notification(
    mr_url: str,
    mr_id: str | int,
    mr_title: str,
    issue_key: Optional[str] = None,
    jira_url: Optional[str] = None,
    team_group_id: Optional[str] = None,
    team_group_handle: Optional[str] = None,
    header: str = "🔀 *MR Ready for Review*",
) -> str:
    """
    Build a standardized MR notification message for Slack.

    Args:
        mr_url: GitLab MR URL
        mr_id: MR IID
        mr_title: MR title (truncated if needed)
        issue_key: Optional Jira issue key
        jira_url: Jira base URL (defaults to config)
        team_group_id: Slack group ID for mention (defaults to config)
        team_group_handle: Slack group handle (defaults to config)
        header: Message header

    Returns:
        Formatted Slack message.
    """
    # Get defaults from config
    if jira_url is None:
        jira_url = get_jira_url()

    team_mention = build_team_mention(team_group_id, team_group_handle)

    lines = [team_mention, header, ""]

    if issue_key:
        lines.append(f"• <{jira_url}/browse/{issue_key}|{issue_key}>")

    # Truncate title if needed
    title = mr_title[:60] if len(mr_title) > 60 else mr_title
    lines.append(f"• <{mr_url}|!{mr_id}: {title}>")

    return "\n".join(lines)


def build_alert_notification(
    alert_name: str,
    environment: str,
    severity: str = "warning",
    description: str = "",
    team_group_id: str = "",
    team_group_handle: str = "aa-api-team",
) -> str:
    """
    Build an alert notification message for Slack.

    Args:
        alert_name: Name of the alert
        environment: Environment (stage, prod)
        severity: Alert severity
        description: Alert description
        team_group_id: Slack group ID
        team_group_handle: Slack group handle

    Returns:
        Formatted Slack alert message.
    """
    team_mention = build_team_mention(team_group_id, team_group_handle)

    emoji = "🔴" if severity == "critical" else "🟡" if severity == "warning" else "ℹ️"

    lines = [
        team_mention,
        f"{emoji} *Alert: {alert_name}*",
        "",
        f"• Environment: `{environment}`",
        f"• Severity: `{severity}`",
    ]

    if description:
        lines.append(f"• {description[:100]}")

    return "\n".join(lines)
