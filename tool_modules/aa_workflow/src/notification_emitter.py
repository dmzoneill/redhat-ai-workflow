"""
Notification Emitter

Unified notification system for emitting toast notifications to the VS Code extension.
This module provides a single API for all components (daemons, tools, skills) to emit
notifications that appear as toast messages in the IDE.

Notifications are written to: ~/.config/aa-workflow/notifications.json

The VS Code extension watches this file and displays appropriate toast messages
based on the notification level (info, warning, error).

File Locking:
- Uses the same lockfile mechanism as skill_execution_events.py
- Lock acquisition uses atomic O_CREAT|O_EXCL for cross-process safety
- Compatible with TypeScript implementation in VS Code extension
"""

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Literal

logger = logging.getLogger(__name__)

# Notification file path - centralized in server.paths
try:
    from server.paths import AA_CONFIG_DIR

    NOTIFICATIONS_FILE = AA_CONFIG_DIR / "notifications.json"
except ImportError:
    NOTIFICATIONS_FILE = Path.home() / ".config" / "aa-workflow" / "notifications.json"

# Cleanup old notifications after this many seconds
CLEANUP_TIMEOUT_SECONDS = 60  # 1 minute (notifications are transient)

# Maximum notifications to keep in file
MAX_NOTIFICATIONS = 50

# File locking constants (same as skill_execution_events.py for consistency)
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_RETRY_INTERVAL_SECONDS = 0.05
LOCK_STALE_SECONDS = 10.0

# Type definitions
NotificationLevel = Literal["info", "warning", "error"]
NotificationCategory = Literal[
    "skill",
    "persona",
    "session",
    "cron",
    "meet",
    "sprint",
    "slack",
    "auto_heal",
    "git",
    "jira",
    "gitlab",
    "memory",
    "daemon",
]


@contextmanager
def _file_lock(file_path: Path) -> Generator[bool, None, None]:
    """
    Context manager for file locking using a lockfile.

    Uses atomic O_CREAT|O_EXCL to create lockfile, ensuring only one process
    can hold the lock at a time. Compatible with the TypeScript implementation
    in the VS Code extension.

    Yields True if lock acquired, False if timeout.
    """
    lock_path = Path(str(file_path) + ".lock")
    start_time = time.time()
    acquired = False

    while time.time() - start_time < LOCK_TIMEOUT_SECONDS:
        try:
            # Check if lock exists and is stale
            if lock_path.exists():
                try:
                    lock_age = time.time() - lock_path.stat().st_mtime
                    if lock_age > LOCK_STALE_SECONDS:
                        try:
                            lock_path.unlink()
                            logger.debug(f"Removed stale notification lock (age: {lock_age:.1f}s)")
                        except OSError:
                            pass
                except OSError:
                    pass

            # Try to create lock file exclusively
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}\n{time.time()}".encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
        except OSError as e:
            logger.warning(f"Error acquiring notification lock: {e}")
            break

    if not acquired:
        logger.warning("Timeout waiting for notification file lock")

    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError as e:
                if e.errno != 2:  # ENOENT
                    logger.warning(f"Error releasing notification lock: {e}")


def _load_notifications_unlocked() -> dict:
    """Load notifications from file without lock."""
    try:
        if NOTIFICATIONS_FILE.exists():
            with open(NOTIFICATIONS_FILE) as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"Could not load notifications file: {e}")

    return {
        "notifications": [],
        "lastUpdated": datetime.now().isoformat(),
        "version": 1,
    }


def _save_notifications_unlocked(data: dict) -> None:
    """Save notifications to file atomically without lock."""
    try:
        data["lastUpdated"] = datetime.now().isoformat()
        tmp_file = NOTIFICATIONS_FILE.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2)
        tmp_file.rename(NOTIFICATIONS_FILE)
    except Exception as e:
        logger.warning(f"Failed to save notifications: {e}")


def _cleanup_old_notifications(data: dict) -> dict:
    """Remove old notifications and enforce max count."""
    now = datetime.now()
    notifications = data.get("notifications", [])

    # Filter out old notifications
    filtered = []
    for notif in notifications:
        timestamp_str = notif.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                age_seconds = (now - timestamp).total_seconds()
                if age_seconds <= CLEANUP_TIMEOUT_SECONDS:
                    filtered.append(notif)
            except (ValueError, TypeError):
                pass

    # Keep only the most recent MAX_NOTIFICATIONS
    if len(filtered) > MAX_NOTIFICATIONS:
        filtered = filtered[-MAX_NOTIFICATIONS:]

    data["notifications"] = filtered
    return data


def emit_notification(
    category: NotificationCategory,
    event_type: str,
    title: str,
    message: str,
    level: NotificationLevel = "info",
    actions: list[dict[str, str]] | None = None,
    data: dict[str, Any] | None = None,
    source: str | None = None,
) -> None:
    """
    Emit a notification to the VS Code extension.

    Args:
        category: Notification category (e.g., "persona", "session", "cron")
        event_type: Specific event type (e.g., "loaded", "started", "failed")
        title: Short title for the toast
        message: Detailed message
        level: Notification level - "info", "warning", or "error"
        actions: Optional list of action buttons, e.g., [{"label": "View", "command": "aa-workflow.viewLogs"}]
        data: Optional additional data for the notification
        source: Optional source identifier (e.g., daemon name, skill name)

    Example:
        emit_notification(
            category="persona",
            event_type="loaded",
            title="Persona Loaded",
            message="Loaded developer persona with 45 tools",
            level="info",
            data={"persona": "developer", "tool_count": 45}
        )
    """
    # Ensure directory exists
    NOTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    notification = {
        "id": f"{category}_{event_type}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "category": category,
        "eventType": event_type,
        "title": title,
        "message": message,
        "level": level,
        "timestamp": datetime.now().isoformat(),
        "actions": actions or [],
        "data": data or {},
        "source": source,
        "read": False,
    }

    with _file_lock(NOTIFICATIONS_FILE) as acquired:
        if not acquired:
            logger.warning("Failed to acquire lock for notification, skipping")
            return

        try:
            all_data = _load_notifications_unlocked()
            all_data = _cleanup_old_notifications(all_data)
            all_data["notifications"].append(notification)
            _save_notifications_unlocked(all_data)

            logger.debug(f"Emitted notification: [{level}] {category}/{event_type}: {title}")
        except Exception as e:
            logger.warning(f"Failed to emit notification: {e}")


# Convenience functions for common notification patterns


def notify_info(
    category: NotificationCategory,
    event_type: str,
    title: str,
    message: str,
    **kwargs,
) -> None:
    """Emit an info-level notification."""
    emit_notification(category, event_type, title, message, level="info", **kwargs)


def notify_warning(
    category: NotificationCategory,
    event_type: str,
    title: str,
    message: str,
    **kwargs,
) -> None:
    """Emit a warning-level notification."""
    emit_notification(category, event_type, title, message, level="warning", **kwargs)


def notify_error(
    category: NotificationCategory,
    event_type: str,
    title: str,
    message: str,
    **kwargs,
) -> None:
    """Emit an error-level notification."""
    emit_notification(category, event_type, title, message, level="error", **kwargs)


# Category-specific convenience functions


def notify_persona_loaded(persona: str, tool_count: int) -> None:
    """Notify that a persona was loaded."""
    emit_notification(
        category="persona",
        event_type="loaded",
        title="Persona Loaded",
        message=f"Loaded {persona} persona with {tool_count} tools",
        level="info",
        data={"persona": persona, "tool_count": tool_count},
    )


def notify_persona_failed(persona: str, error: str) -> None:
    """Notify that persona loading failed."""
    emit_notification(
        category="persona",
        event_type="failed",
        title="Persona Load Failed",
        message=f"Failed to load {persona}: {error}",
        level="error",
        data={"persona": persona, "error": error},
        actions=[{"label": "View Logs", "command": "aa-workflow.viewLogs"}],
    )


def notify_session_created(session_id: str, name: str | None = None) -> None:
    """Notify that a new session was created."""
    title = "Session Created"
    message = f"Session {name or session_id[:8]} started"
    emit_notification(
        category="session",
        event_type="created",
        title=title,
        message=message,
        level="info",
        data={"session_id": session_id, "name": name},
    )


def notify_session_resumed(session_id: str, name: str | None = None) -> None:
    """Notify that a session was resumed."""
    emit_notification(
        category="session",
        event_type="resumed",
        title="Session Resumed",
        message=f"Resumed session {name or session_id[:8]}",
        level="info",
        data={"session_id": session_id, "name": name},
    )


def notify_auto_heal_triggered(step_name: str, error_type: str, fix_action: str) -> None:
    """Notify that auto-heal was triggered."""
    emit_notification(
        category="auto_heal",
        event_type="triggered",
        title="Auto-Heal Triggered",
        message=f"Healing {error_type} in {step_name}: {fix_action}",
        level="warning",
        data={"step_name": step_name, "error_type": error_type, "fix_action": fix_action},
    )


def notify_auto_heal_succeeded(step_name: str, fix_action: str) -> None:
    """Notify that auto-heal succeeded."""
    emit_notification(
        category="auto_heal",
        event_type="succeeded",
        title="Auto-Heal Succeeded",
        message=f"Successfully healed {step_name}",
        level="info",
        data={"step_name": step_name, "fix_action": fix_action},
    )


def notify_auto_heal_failed(step_name: str, error: str) -> None:
    """Notify that auto-heal failed."""
    emit_notification(
        category="auto_heal",
        event_type="failed",
        title="Auto-Heal Failed",
        message=f"Failed to heal {step_name}: {error}",
        level="error",
        data={"step_name": step_name, "error": error},
        actions=[{"label": "Debug", "command": "aa-workflow.debugTool"}],
    )


def notify_step_failed(skill_name: str, step_name: str, error: str) -> None:
    """Notify that a skill step failed (with on_error: continue)."""
    emit_notification(
        category="skill",
        event_type="step_failed",
        title=f'Skill failed: {skill_name} at step "{step_name}"',
        message=error[:150],
        level="error",
        data={"skill_name": skill_name, "step_name": step_name, "error": error},
        actions=[{"label": "Show Output", "command": "aa-workflow.showSkillOutput"}],
    )


def notify_cron_job_started(job_name: str, skill: str) -> None:
    """Notify that a cron job started."""
    emit_notification(
        category="cron",
        event_type="job_started",
        title="Cron Job Started",
        message=f"Running {job_name} ({skill})",
        level="info",
        data={"job_name": job_name, "skill": skill},
        source="cron_daemon",
    )


def notify_cron_job_completed(job_name: str, skill: str, duration_seconds: float) -> None:
    """Notify that a cron job completed."""
    emit_notification(
        category="cron",
        event_type="job_completed",
        title="Cron Job Completed",
        message=f"{job_name} completed in {duration_seconds:.1f}s",
        level="info",
        data={"job_name": job_name, "skill": skill, "duration": duration_seconds},
        source="cron_daemon",
    )


def notify_cron_job_failed(job_name: str, skill: str, error: str) -> None:
    """Notify that a cron job failed."""
    emit_notification(
        category="cron",
        event_type="job_failed",
        title="Cron Job Failed",
        message=f"{job_name} failed: {error[:100]}",
        level="error",
        data={"job_name": job_name, "skill": skill, "error": error},
        source="cron_daemon",
        actions=[{"label": "View Logs", "command": "aa-workflow.viewCronLogs"}],
    )


def notify_meeting_soon(title: str, minutes: int, event_id: str) -> None:
    """Notify that a meeting is starting soon."""
    emit_notification(
        category="meet",
        event_type="meeting_soon",
        title="Meeting Starting Soon",
        message=f"{title} starts in {minutes} minutes",
        level="warning",
        data={"meeting_title": title, "minutes": minutes, "event_id": event_id},
        source="meet_daemon",
        actions=[{"label": "Skip", "command": "aa-workflow.skipMeeting"}],
    )


def notify_meeting_joined(title: str, mode: str) -> None:
    """Notify that a meeting was joined."""
    emit_notification(
        category="meet",
        event_type="meeting_joined",
        title="Meeting Joined",
        message=f"Joined: {title} ({mode} mode)",
        level="info",
        data={"meeting_title": title, "mode": mode},
        source="meet_daemon",
    )


def notify_meeting_left(title: str, duration_minutes: float, transcript_count: int) -> None:
    """Notify that a meeting was left."""
    emit_notification(
        category="meet",
        event_type="meeting_left",
        title="Meeting Ended",
        message=f"Left {title} ({duration_minutes:.0f}m, {transcript_count} captions)",
        level="info",
        data={
            "meeting_title": title,
            "duration_minutes": duration_minutes,
            "transcript_count": transcript_count,
        },
        source="meet_daemon",
    )


def notify_sprint_issue_started(issue_key: str, summary: str) -> None:
    """Notify that sprint bot started working on an issue."""
    emit_notification(
        category="sprint",
        event_type="issue_started",
        title="Sprint: Issue Started",
        message=f"Working on {issue_key}: {summary[:50]}",
        level="info",
        data={"issue_key": issue_key, "summary": summary},
        source="sprint_daemon",
    )


def notify_sprint_issue_completed(issue_key: str) -> None:
    """Notify that sprint bot completed an issue."""
    emit_notification(
        category="sprint",
        event_type="issue_completed",
        title="Sprint: Issue Completed",
        message=f"Completed work on {issue_key}",
        level="info",
        data={"issue_key": issue_key},
        source="sprint_daemon",
    )


def notify_sprint_issue_blocked(issue_key: str, reason: str) -> None:
    """Notify that an issue is blocked."""
    emit_notification(
        category="sprint",
        event_type="issue_blocked",
        title="Sprint: Issue Blocked",
        message=f"{issue_key} blocked: {reason[:50]}",
        level="warning",
        data={"issue_key": issue_key, "reason": reason},
        source="sprint_daemon",
    )


def notify_slack_message(channel: str, user: str, preview: str) -> None:
    """Notify of a Slack message."""
    emit_notification(
        category="slack",
        event_type="message_received",
        title=f"Slack: {user}",
        message=f"#{channel}: {preview[:50]}...",
        level="info",
        data={"channel": channel, "user": user, "preview": preview},
        source="slack_daemon",
    )


def notify_slack_pending_approval(channel: str, user: str, preview: str) -> None:
    """Notify of a Slack message pending approval."""
    emit_notification(
        category="slack",
        event_type="pending_approval",
        title="Slack: Approval Needed",
        message=f"{user} in #{channel}: {preview[:30]}...",
        level="warning",
        data={"channel": channel, "user": user, "preview": preview},
        source="slack_daemon",
        actions=[{"label": "View", "command": "aa-workflow.viewSlackMessage"}],
    )
