"""Sprint Bot Orchestrator - Automates sprint work with Cursor chat integration.

The Sprint Bot:
1. Fetches sprint issues from Jira
2. Prioritizes them using sprint_prioritizer
3. Creates Cursor chats for each issue (via VS Code extension D-Bus)
4. Tracks progress and updates UI
5. Respects working hours (configurable)
6. Handles blocked/waiting issues by skipping to next

The bot runs as a cron job during working hours and creates one chat per issue.
Each chat is named with the issue key for easy identification.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

# Support both package import and direct loading
try:
    from .sprint_history import (
        SprintIssue,
        SprintState,
        TimelineEvent,
        add_timeline_event,
        get_next_issue_to_process,
        load_sprint_state,
        save_sprint_state,
        update_issue_status,
    )
    from .sprint_prioritizer import prioritize_issues, to_sprint_issue_format
except ImportError:
    from sprint_history import (
        SprintIssue,
        SprintState,
        TimelineEvent,
        add_timeline_event,
        get_next_issue_to_process,
        load_sprint_state,
        save_sprint_state,
        update_issue_status,
    )
    from sprint_prioritizer import prioritize_issues, to_sprint_issue_format

logger = logging.getLogger(__name__)

# Lock file to prevent concurrent bot runs
LOCK_FILE = Path.home() / ".config" / "aa-workflow" / "sprint_bot.lock"


@dataclass
class WorkingHours:
    """Working hours configuration."""

    start_hour: int = 9
    start_minute: int = 0
    end_hour: int = 17
    end_minute: int = 0
    weekdays_only: bool = True
    timezone: str = "Europe/Dublin"


@dataclass
class SprintBotConfig:
    """Sprint bot configuration."""

    working_hours: WorkingHours
    jira_project: str = "AAP"
    jira_component: str | None = None
    auto_approve: bool = False  # If True, auto-approve all issues
    max_concurrent_chats: int = 1  # For now, always 1 (sequential)
    skip_blocked_after_minutes: int = 30  # Skip blocked issues after this time


def is_within_working_hours(config: WorkingHours) -> bool:
    """Check if current time is within working hours.

    Args:
        config: WorkingHours configuration

    Returns:
        True if within working hours
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(config.timezone)
        now = datetime.now(tz)
    except ImportError:
        # Fallback for older Python
        now = datetime.now()

    # Check weekday (0=Monday, 6=Sunday)
    if config.weekdays_only and now.weekday() >= 5:
        return False

    # Check time
    start = time(config.start_hour, config.start_minute)
    end = time(config.end_hour, config.end_minute)
    current_time = now.time()

    return start <= current_time <= end


def acquire_lock() -> bool:
    """Try to acquire the bot lock.

    Returns:
        True if lock acquired, False if another instance is running
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    if LOCK_FILE.exists():
        # Check if lock is stale (older than 1 hour)
        lock_age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
        if lock_age < 3600:  # 1 hour
            logger.info("Sprint bot lock exists and is recent - another instance may be running")
            return False
        logger.warning("Removing stale sprint bot lock")

    # Create lock
    LOCK_FILE.write_text(
        json.dumps(
            {
                "pid": __import__("os").getpid(),
                "started": datetime.now().isoformat(),
            }
        )
    )
    return True


def release_lock() -> None:
    """Release the bot lock."""
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


async def fetch_sprint_issues(config: SprintBotConfig) -> list[dict[str, Any]]:
    """Fetch issues from the active sprint in Jira.

    Args:
        config: Bot configuration

    Returns:
        List of issue dicts from Jira
    """
    # Import Jira tools - these are MCP tools so we call them via tool_exec
    # For now, we'll use a direct import approach
    try:
        from tool_modules.aa_jira.src.tools_basic import jira_get_active_sprint, jira_get_sprint_issues

        # Get active sprint
        sprint_result = await jira_get_active_sprint(project=config.jira_project)
        if not sprint_result or "error" in str(sprint_result).lower():
            logger.error(f"Failed to get active sprint: {sprint_result}")
            return []

        # Extract sprint ID
        sprint_id = None
        if isinstance(sprint_result, dict):
            sprint_id = sprint_result.get("id")

        if not sprint_id:
            logger.error("No active sprint found")
            return []

        # Get sprint issues
        issues_result = await jira_get_sprint_issues(sprint_id=sprint_id)
        if isinstance(issues_result, list):
            return issues_result
        elif isinstance(issues_result, dict) and "issues" in issues_result:
            return issues_result["issues"]

        return []

    except ImportError:
        logger.warning("Jira tools not available, using mock data")
        return []
    except Exception as e:
        logger.error(f"Error fetching sprint issues: {e}")
        return []


def load_sprint_issues_from_jira_sync(config: SprintBotConfig) -> list[dict[str, Any]]:
    """Synchronous wrapper for fetching sprint issues.

    Uses existing MCP tool infrastructure.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(fetch_sprint_issues(config))


def refresh_sprint_state(config: SprintBotConfig) -> SprintState:
    """Refresh sprint state from Jira and prioritize issues.

    Args:
        config: Bot configuration

    Returns:
        Updated SprintState
    """
    # Load current state
    state = load_sprint_state()

    # Fetch fresh issues from Jira
    jira_issues = load_sprint_issues_from_jira_sync(config)

    if not jira_issues:
        logger.warning("No issues fetched from Jira, keeping existing state")
        return state

    # Filter to only show issues assigned to current user
    try:
        from server.config import load_config

        user_config = load_config()
        user_info = user_config.get("user", {})
        jira_username = user_info.get("jira_username", "")
        full_name = user_info.get("full_name", "")
        if jira_username or full_name:
            original_count = len(jira_issues)
            # Match against username OR full name (Jira may use either)
            match_values = [v.lower() for v in [jira_username, full_name] if v]
            jira_issues = [issue for issue in jira_issues if issue.get("assignee", "").lower() in match_values]
            logger.info(
                f"Filtered to {len(jira_issues)}/{original_count} issues assigned to {jira_username or full_name}"
            )
    except Exception as e:
        logger.warning(f"Could not filter by assignee: {e}")

    if not jira_issues:
        logger.info("No issues assigned to current user")
        state.issues = []
        state.last_updated = datetime.now().isoformat()
        save_sprint_state(state)
        return state

    # Prioritize issues
    prioritized = prioritize_issues(jira_issues)
    sprint_issues = to_sprint_issue_format(prioritized)

    # Merge with existing state (preserve approval status, chat IDs, timelines)
    existing_by_key = {issue.key: issue for issue in state.issues}

    new_issues = []
    for issue_data in sprint_issues:
        key = issue_data["key"]

        if key in existing_by_key:
            # Preserve existing state
            existing = existing_by_key[key]
            new_issues.append(
                SprintIssue(
                    key=key,
                    summary=issue_data["summary"],
                    story_points=issue_data.get("storyPoints", 0),
                    priority=issue_data.get("priority", "Major"),
                    jira_status=issue_data.get("jiraStatus", "New"),
                    assignee=issue_data.get("assignee", ""),
                    approval_status=existing.approval_status,  # Preserve
                    waiting_reason=existing.waiting_reason,  # Preserve
                    priority_reasoning=issue_data.get("priorityReasoning", []),
                    estimated_actions=issue_data.get("estimatedActions", []),
                    chat_id=existing.chat_id,  # Preserve
                    timeline=existing.timeline,  # Preserve
                    issue_type=issue_data.get("issueType", "Story"),
                    created=issue_data.get("created", ""),
                )
            )
        else:
            # New issue
            new_issues.append(
                SprintIssue(
                    key=key,
                    summary=issue_data["summary"],
                    story_points=issue_data.get("storyPoints", 0),
                    priority=issue_data.get("priority", "Major"),
                    jira_status=issue_data.get("jiraStatus", "New"),
                    assignee=issue_data.get("assignee", ""),
                    approval_status="pending",
                    waiting_reason=None,
                    priority_reasoning=issue_data.get("priorityReasoning", []),
                    estimated_actions=issue_data.get("estimatedActions", []),
                    chat_id=None,
                    timeline=[],
                    issue_type=issue_data.get("issueType", "Story"),
                    created=issue_data.get("created", ""),
                )
            )

    # Update state
    state.issues = new_issues
    state.last_updated = datetime.now().isoformat()
    save_sprint_state(state)

    return state


async def launch_issue_chat(issue: SprintIssue) -> str | None:
    """Launch a Cursor chat for an issue via D-Bus.

    Args:
        issue: SprintIssue to work on

    Returns:
        Chat ID if successful, None otherwise
    """
    try:
        # Try D-Bus first (preferred method)
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        # Get the chat service
        chat_service = bus.get_object("com.redhat.AAWorkflow.Chat", "/com/redhat/AAWorkflow/Chat")
        chat_interface = dbus.Interface(chat_service, "com.redhat.AAWorkflow.Chat")

        # Launch the chat
        result = chat_interface.LaunchIssueChat(
            issue.key,
            issue.summary,  # Use summary as the description
            True,  # Return to previous chat
            False,  # Don't auto-approve
        )

        if result:
            result_dict = json.loads(str(result))
            return result_dict.get("chatId")

        return None

    except Exception as e:
        logger.error(f"Failed to launch chat via D-Bus: {e}")

        # Fallback: Log the action for manual execution
        logger.info(f"Manual action required: Create chat for {issue.key}")
        logger.info(f"  Summary: {issue.summary}")
        logger.info(f"  Command: skill_run('sprint_autopilot', '{{\"issue_key\": \"{issue.key}\"}}')")

        return None


def process_next_issue(state: SprintState, config: SprintBotConfig) -> bool:
    """Process the next available issue.

    Args:
        state: Current sprint state
        config: Bot configuration

    Returns:
        True if an issue was processed, False if none available
    """
    import asyncio

    # Get next issue to process
    issue = get_next_issue_to_process(state)

    if not issue:
        logger.info("No issues available to process")
        return False

    logger.info(f"Processing issue: {issue.key} - {issue.summary}")

    # Update status to in_progress
    update_issue_status(issue.key, "in_progress")
    state.processing_issue = issue.key
    save_sprint_state(state)

    # Add timeline event
    add_timeline_event(
        issue.key,
        TimelineEvent(
            timestamp=datetime.now().isoformat(),
            action="started",
            description="Sprint bot started working on this issue",
        ),
    )

    # Launch chat
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    chat_id = loop.run_until_complete(launch_issue_chat(issue))

    if chat_id:
        # Update with chat ID
        update_issue_status(issue.key, "in_progress", chat_id=chat_id)
        add_timeline_event(
            issue.key,
            TimelineEvent(
                timestamp=datetime.now().isoformat(),
                action="chat_created",
                description="Cursor chat created",
                chat_link=chat_id,
            ),
        )
        logger.info(f"Chat created for {issue.key}: {chat_id}")
    else:
        logger.warning(f"Could not create chat for {issue.key}")

    return True


def run_sprint_bot(config: SprintBotConfig | None = None) -> dict[str, Any]:
    """Main entry point for the sprint bot.

    Called by cron job during working hours.

    Args:
        config: Optional bot configuration

    Returns:
        Status dict with results
    """
    if config is None:
        config = SprintBotConfig(
            working_hours=WorkingHours(),
            jira_project="AAP",
        )

    result = {
        "success": False,
        "message": "",
        "issues_processed": 0,
        "timestamp": datetime.now().isoformat(),
    }

    # Check working hours
    if not is_within_working_hours(config.working_hours):
        result["message"] = "Outside working hours"
        logger.info("Sprint bot: Outside working hours, skipping")
        return result

    # Try to acquire lock
    if not acquire_lock():
        result["message"] = "Another instance is running"
        logger.info("Sprint bot: Another instance is running, skipping")
        return result

    try:
        # Load/refresh sprint state
        state = load_sprint_state()

        if not state.bot_enabled:
            result["message"] = "Bot is disabled"
            logger.info("Sprint bot: Bot is disabled")
            return result

        # Refresh from Jira periodically (every 30 minutes)
        last_updated = datetime.fromisoformat(state.last_updated) if state.last_updated else datetime.min
        if (datetime.now() - last_updated).total_seconds() > 1800:
            logger.info("Refreshing sprint state from Jira")
            state = refresh_sprint_state(config)

        # Process next issue
        processed = process_next_issue(state, config)

        if processed:
            result["success"] = True
            result["issues_processed"] = 1
            result["message"] = f"Processed issue: {state.processing_issue}"
        else:
            result["success"] = True
            result["message"] = "No issues to process"

        return result

    except Exception as e:
        logger.exception(f"Sprint bot error: {e}")
        result["message"] = f"Error: {str(e)}"
        return result

    finally:
        release_lock()


def enable_sprint_bot() -> dict[str, Any]:
    """Enable the sprint bot."""
    state = load_sprint_state()
    state.bot_enabled = True
    state.last_updated = datetime.now().isoformat()
    save_sprint_state(state)

    return {
        "success": True,
        "message": "Sprint bot enabled",
        "bot_enabled": True,
    }


def disable_sprint_bot() -> dict[str, Any]:
    """Disable the sprint bot."""
    state = load_sprint_state()
    state.bot_enabled = False
    state.processing_issue = None
    state.last_updated = datetime.now().isoformat()
    save_sprint_state(state)

    # Release any lock
    release_lock()

    return {
        "success": True,
        "message": "Sprint bot disabled",
        "bot_enabled": False,
    }


# Statuses that are actionable (bot can work on these)
ACTIONABLE_STATUSES = ["new", "refinement", "to do", "open", "backlog"]


def is_actionable(issue: SprintIssue) -> bool:
    """Check if an issue is actionable based on its Jira status.

    Bot should only work on issues in New/Refinement/Backlog.
    Issues in Review/Done/Release Pending should be ignored.
    """
    jira_status = (issue.jira_status or "").lower()
    return any(s in jira_status for s in ACTIONABLE_STATUSES)


def approve_issue(issue_key: str) -> dict[str, Any]:
    """Approve an issue for the bot to work on.

    Only approves issues that are in actionable statuses (New/Refinement/Backlog).

    Args:
        issue_key: Jira issue key

    Returns:
        Status dict
    """
    # First check if issue is actionable
    state = load_sprint_state()
    issue = None
    for i in state.issues:
        if i.key == issue_key:
            issue = i
            break

    if not issue:
        return {
            "success": False,
            "message": f"Issue {issue_key} not found",
        }

    if not is_actionable(issue):
        return {
            "success": False,
            "message": f"Issue {issue_key} is not actionable (status: {issue.jira_status}). "
            "Bot only works on issues in New/Refinement/Backlog.",
        }

    success = update_issue_status(issue_key, "approved")

    if success:
        add_timeline_event(
            issue_key,
            TimelineEvent(
                timestamp=datetime.now().isoformat(),
                action="approved",
                description="Issue approved for sprint bot",
            ),
        )

    return {
        "success": success,
        "message": f"Issue {issue_key} approved" if success else f"Issue {issue_key} not found",
    }


def skip_issue(issue_key: str, reason: str = "Manually skipped") -> dict[str, Any]:
    """Skip/block an issue.

    Args:
        issue_key: Jira issue key
        reason: Reason for skipping

    Returns:
        Status dict
    """
    success = update_issue_status(issue_key, "blocked", waiting_reason=reason)

    if success:
        add_timeline_event(
            issue_key,
            TimelineEvent(
                timestamp=datetime.now().isoformat(),
                action="skipped",
                description=f"Issue skipped: {reason}",
            ),
        )

    return {
        "success": success,
        "message": f"Issue {issue_key} skipped" if success else f"Issue {issue_key} not found",
    }


def get_sprint_status() -> dict[str, Any]:
    """Get current sprint bot status.

    Returns:
        Status dict with sprint info
    """
    state = load_sprint_state()

    # Count issues by status
    status_counts = {}
    for issue in state.issues:
        status = issue.approval_status
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "bot_enabled": state.bot_enabled,
        "processing_issue": state.processing_issue,
        "total_issues": len(state.issues),
        "status_counts": status_counts,
        "last_updated": state.last_updated,
        "current_sprint": state.current_sprint,
    }
