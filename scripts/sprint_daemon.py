#!/usr/bin/env python3
"""
Sprint Bot Daemon

A standalone service that automates sprint work by orchestrating Cursor chats.
Designed to run as a systemd user service, similar to meet_daemon.py.

Features:
- Working hours enforcement (Mon-Fri, 9am-5pm configurable)
- Jira sprint issue fetching and prioritization
- Cursor chat launching via D-Bus to VS Code extension
- Sequential issue processing with skip-on-block
- Real-time UI updates via workspace state file
- Single instance enforcement (lock file)
- D-Bus IPC for external control
- Graceful shutdown handling

Usage:
    python scripts/sprint_daemon.py                # Run daemon
    python scripts/sprint_daemon.py --status       # Check if running
    python scripts/sprint_daemon.py --stop         # Stop running daemon
    python scripts/sprint_daemon.py --list         # List sprint issues
    python scripts/sprint_daemon.py --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-sprint
    systemctl --user status bot-sprint
    systemctl --user stop bot-sprint

D-Bus:
    Service: com.aiworkflow.BotSprint
    Path: /com/aiworkflow/BotSprint
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
import time as time_module
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dbus_base import DaemonDBusBase, get_client  # noqa: E402
from scripts.common.sleep_wake import SleepWakeAwareDaemon  # noqa: E402
from scripts.sprint_bot.execution_tracer import ExecutionTracer, StepStatus, WorkflowState, get_trace, list_traces

# Import workflow configuration and execution tracer
from scripts.sprint_bot.workflow_config import WorkflowConfig, get_workflow_config

LOCK_FILE = Path("/tmp/sprint-daemon.lock")
PID_FILE = Path("/tmp/sprint-daemon.pid")

# Sprint daemon owns its own state file - no shared file with other services
from server.paths import SPRINT_STATE_FILE_V2

SPRINT_STATE_FILE = SPRINT_STATE_FILE_V2

# Directory for background work logs
SPRINT_WORK_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_work"

# Configure logging for journalctl
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger(__name__)


class SingleInstance:
    """Ensures only one instance of the daemon runs at a time."""

    def __init__(self):
        self._lock_file = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock_file = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID
            PID_FILE.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass
        self._acquired = False

    def get_running_pid(self) -> int | None:
        """Get PID of running instance, or None if not running."""
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError):
                pass
        return None


class SprintDaemon(SleepWakeAwareDaemon, DaemonDBusBase):
    """Main Sprint Bot daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSprint"
    object_path = "/com/aiworkflow/BotSprint"
    interface_name = "com.aiworkflow.BotSprint"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._issues_processed = 0
        self._issues_completed = 0
        self._last_jira_refresh = datetime.min
        self._last_review_check = datetime.min

        # Configuration
        self._config = {
            "jira_project": "AAP",
            "jira_component": None,
            "working_hours": {
                "start_hour": 9,
                "start_minute": 0,
                "end_hour": 17,
                "end_minute": 0,
                "weekdays_only": True,
                "timezone": "Europe/Dublin",
            },
            "check_interval_seconds": 300,  # Check every 5 minutes
            "jira_refresh_interval_seconds": 1800,  # Refresh from Jira every 30 minutes
            "skip_blocked_after_minutes": 30,
        }

        # Register custom D-Bus method handlers
        self.register_handler("list_issues", self._handle_list_issues)
        self.register_handler("approve_issue", self._handle_approve_issue)
        self.register_handler("skip_issue", self._handle_skip_issue)
        self.register_handler("refresh", self._handle_refresh)
        self.register_handler("enable", self._handle_enable)  # Enable automatic mode
        self.register_handler("disable", self._handle_disable)  # Disable automatic mode
        self.register_handler("start", self._handle_start)  # Manual start (ignores schedule)
        self.register_handler("stop", self._handle_stop)  # Manual stop
        self.register_handler("get_config", self._handle_get_config)
        self.register_handler("set_config", self._handle_set_config)
        self.register_handler("approve_all", self._handle_approve_all)
        self.register_handler("process_next", self._handle_process_next)
        self.register_handler("open_in_cursor", self._handle_open_in_cursor)
        self.register_handler("get_work_log", self._handle_get_work_log)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("start_issue", self._handle_start_issue)

    # ==================== Abstract Method Implementations ====================

    async def on_system_wake(self):
        """Called when system wakes from sleep - refresh Jira data."""
        logger.info("System wake detected, refreshing sprint data...")
        await self._refresh_from_jira()

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        state = self._load_state()
        automatic_mode = state.get("automaticMode", False)
        manually_started = state.get("manuallyStarted", False)
        within_hours = self._is_within_working_hours()

        # Determine if bot is actively working
        is_active = manually_started or (automatic_mode and within_hours)

        return {
            "running": True,
            "automatic_mode": automatic_mode,
            "manually_started": manually_started,
            "is_active": is_active,
            "within_working_hours": within_hours,
            "total_issues": len(state.get("issues", [])),
            "processing_issue": state.get("processingIssue"),
            "last_updated": state.get("lastUpdated", ""),
            "issues_processed": self._issues_processed,
            "issues_completed": self._issues_completed,
        }

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return sprint-specific statistics."""
        state = self._load_state()

        # Count issues by status
        status_counts = {}
        for issue in state.get("issues", []):
            status = issue.get("approvalStatus", "pending")
            status_counts[status] = status_counts.get(status, 0) + 1

        automatic_mode = state.get("automaticMode", False)
        manually_started = state.get("manuallyStarted", False)
        within_hours = self._is_within_working_hours()

        return {
            "issues_processed": self._issues_processed,
            "issues_completed": self._issues_completed,
            "automatic_mode": automatic_mode,
            "manually_started": manually_started,
            "is_active": manually_started or (automatic_mode and within_hours),
            "total_issues": len(state.get("issues", [])),
            "status_counts": status_counts,
            "processing_issue": state.get("processingIssue"),
            "last_updated": state.get("lastUpdated", ""),
            "within_working_hours": within_hours,
        }

    async def _handle_list_issues(self, params: dict) -> dict:
        """List all sprint issues."""
        state = self._load_state()
        issues = state.get("issues", [])

        # Add actionable flag to each issue
        for issue in issues:
            issue["isActionable"] = self._is_actionable(issue)

        # Filter by status if requested
        status_filter = params.get("status")
        if status_filter:
            issues = [i for i in issues if i.get("approvalStatus") == status_filter]

        # Filter by actionable if requested
        actionable_filter = params.get("actionable")
        if actionable_filter is not None:
            issues = [i for i in issues if i.get("isActionable") == actionable_filter]

        actionable_count = sum(1 for i in issues if i.get("isActionable"))

        return {
            "success": True,
            "issues": issues,
            "total": len(issues),
            "actionable_count": actionable_count,
            "not_actionable_count": len(issues) - actionable_count,
        }

    async def _handle_approve_issue(self, params: dict) -> dict:
        """Approve an issue for processing.

        Only allows approval of actionable issues (New/Refinement/Backlog).
        Issues in Review/Done cannot be approved.
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                # Check if issue is actionable
                if not self._is_actionable(issue):
                    jira_status = issue.get("jiraStatus", "unknown")
                    return {
                        "success": False,
                        "error": f"Issue {issue_key} is not actionable (status: {jira_status}). "
                        f"Bot only works on issues in New/Refinement/Backlog.",
                    }

                issue["approvalStatus"] = "approved"
                issue["timeline"] = issue.get("timeline", [])
                issue["timeline"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "approved",
                        "description": "Issue approved for sprint bot",
                    }
                )
                self._save_state(state)
                logger.info(f"Approved issue: {issue_key}")
                return {"success": True, "message": f"Issue {issue_key} approved"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_skip_issue(self, params: dict) -> dict:
        """Skip/block an issue."""
        issue_key = params.get("issue_key")
        reason = params.get("reason", "Manually skipped")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "blocked"
                issue["waitingReason"] = reason
                issue["timeline"] = issue.get("timeline", [])
                issue["timeline"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "skipped",
                        "description": f"Issue skipped: {reason}",
                    }
                )
                self._save_state(state)
                logger.info(f"Skipped issue: {issue_key} - {reason}")
                return {"success": True, "message": f"Issue {issue_key} skipped"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_refresh(self, params: dict) -> dict:
        """Force refresh from Jira."""
        try:
            await self._refresh_from_jira()
            return {"success": True, "message": "Refreshed from Jira"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_enable(self, params: dict) -> dict:
        """Enable automatic mode (scheduled Mon-Fri 9-5)."""
        state = self._load_state()
        state["automaticMode"] = True
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode enabled")
        return {"success": True, "message": "Sprint bot automatic mode enabled"}

    async def _handle_disable(self, params: dict) -> dict:
        """Disable automatic mode."""
        state = self._load_state()
        state["automaticMode"] = False
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode disabled")
        return {"success": True, "message": "Sprint bot automatic mode disabled"}

    async def _handle_start(self, params: dict) -> dict:
        """Manually start the bot (ignores schedule)."""
        state = self._load_state()
        state["manuallyStarted"] = True
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot manually started")
        return {"success": True, "message": "Sprint bot started manually"}

    async def _handle_stop(self, params: dict) -> dict:
        """Stop the bot (if manually started)."""
        state = self._load_state()
        state["manuallyStarted"] = False
        state["processingIssue"] = None
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot stopped")
        return {"success": True, "message": "Sprint bot stopped"}

    async def _handle_get_config(self, params: dict) -> dict:
        """Get current configuration."""
        return {"success": True, "config": self._config}

    async def _handle_set_config(self, params: dict) -> dict:
        """Update configuration."""
        for key, value in params.items():
            if key in self._config:
                self._config[key] = value
        return {"success": True, "config": self._config}

    async def _handle_approve_all(self, params: dict) -> dict:
        """Approve all pending actionable issues.

        Only approves issues that are in actionable Jira statuses
        (New, Refinement, Backlog, etc.). Issues in Review/Done are skipped.
        """
        state = self._load_state()
        approved_count = 0
        skipped_count = 0

        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "pending":
                if self._is_actionable(issue):
                    issue["approvalStatus"] = "approved"
                    issue["timeline"] = issue.get("timeline", [])
                    issue["timeline"].append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "approved",
                            "description": "Bulk approved by sprint bot",
                        }
                    )
                    approved_count += 1
                else:
                    # Mark as completed/ignored since it's not actionable
                    issue["approvalStatus"] = "completed"
                    skipped_count += 1
                    logger.debug(
                        f"Skipped non-actionable issue: {issue.get('key')} (status: {issue.get('jiraStatus')})"
                    )

        self._save_state(state)
        logger.info(f"Approved {approved_count} actionable issues, skipped {skipped_count} non-actionable")
        return {"success": True, "approved_count": approved_count, "skipped_count": skipped_count}

    async def _handle_process_next(self, params: dict) -> dict:
        """Manually trigger processing of next issue."""
        result = await self._process_next_issue()
        return result

    async def _handle_get_work_log(self, params: dict) -> dict:
        """Get the work log for an issue."""
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        work_log = self._load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        return {"success": True, "work_log": work_log}

    async def _handle_write_state(self, params: dict) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            state = self._load_state()
            self._save_state(state)
            return {"success": True, "file": str(SPRINT_STATE_FILE)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_start_issue(self, params: dict) -> dict:
        """Start processing an issue immediately, bypassing all checks.

        This is triggered from the UI "Start Issue" button and:
        - Skips sprint started/automatic mode checks
        - Skips Jira hygiene checks (missing story points, etc.)
        - Skips actionable status checks
        - Immediately starts processing the issue

        Parameters:
            issue_key: The Jira issue key to start
            background: If False, opens chat in foreground (default: use state.backgroundTasks)
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        # Get background preference from params, falling back to state setting
        state = self._load_state()
        background_mode = params.get("background")
        if background_mode is None:
            background_mode = state.get("backgroundTasks", True)

        # Find the issue
        target_issue = None
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                target_issue = issue
                break

        if not target_issue:
            return {"success": False, "error": f"Issue {issue_key} not found in sprint"}

        logger.info(f"Starting issue immediately: {issue_key} (background={background_mode})")

        # Mark as in_progress and set as processing
        target_issue["approvalStatus"] = "in_progress"
        state["processingIssue"] = issue_key
        target_issue["timeline"] = target_issue.get("timeline", [])
        target_issue["timeline"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "force_started",
                "description": "Issue started immediately via UI (bypassing checks)",
            }
        )
        self._save_state(state)

        # Initialize execution tracer
        tracer = self._get_tracer(issue_key, target_issue)
        self._trace_transition(tracer, WorkflowState.LOADING, trigger="force_start")
        self._trace_step(
            tracer,
            "force_start_issue",
            inputs={"issue_key": issue_key, "background_mode": background_mode},
            decision="force_start",
            reason="User requested immediate start via UI, bypassing all checks",
        )

        # FOREGROUND MODE: Open Cursor chat
        if not background_mode:
            cursor_available = await self._is_cursor_available()
            if not cursor_available:
                # Can't do foreground without Cursor - inform user
                target_issue["approvalStatus"] = "blocked"
                target_issue["waitingReason"] = "Cursor not available for foreground mode"
                state["processingIssue"] = None
                self._save_state(state)
                return {
                    "success": False,
                    "error": "Cursor is not available. Please open VS Code/Cursor first, or use background mode.",
                }

            # Process in Cursor (foreground)
            result = await self._process_in_cursor_traced(target_issue, state, tracer)
            return result

        # BACKGROUND MODE: Run via Claude CLI
        # Transition Jira to In Progress
        self._trace_transition(tracer, WorkflowState.TRANSITIONING_JIRA, trigger="force_start_background")
        jira_success = await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_PROGRESS)
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={"issue_key": issue_key, "target_status": self.JIRA_STATUS_IN_PROGRESS},
            outputs={"success": jira_success},
            tool_name="jira_transition",
        )

        target_issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        target_issue["timeline"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            }
        )
        target_issue["hasTrace"] = True
        target_issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt and run
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="jira_transitioned")
        self._trace_transition(tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background")

        result = await self._run_issue_in_background_traced(target_issue, tracer)

        # Reload state and update
        state = self._load_state()
        target_issue = next((i for i in state.get("issues", []) if i["key"] == issue_key), target_issue)

        if result.get("success"):
            self._trace_transition(tracer, WorkflowState.CREATING_MR, trigger="implementation_complete")
            await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_REVIEW)
            self._trace_transition(tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created")
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            target_issue["timeline"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self._get_work_log_path(issue_key)),
                    "jiraTransition": self.JIRA_STATUS_IN_REVIEW,
                }
            )
            target_issue["approvalStatus"] = "completed"
            target_issue["jiraStatus"] = self.JIRA_STATUS_IN_REVIEW
            target_issue["hasWorkLog"] = True
            target_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            state["processingIssue"] = None
            self._save_state(state)
            self._issues_processed += 1

            return {"success": True, "message": f"Completed {issue_key}", "mode": "background"}
        else:
            error_reason = result.get("error", "Background processing failed")
            tracer.mark_blocked(error_reason)

            target_issue["timeline"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                }
            )
            target_issue["approvalStatus"] = "blocked"
            target_issue["waitingReason"] = error_reason
            target_issue["hasWorkLog"] = True
            target_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            state["processingIssue"] = None
            self._save_state(state)

            return {"success": False, "error": error_reason, "mode": "background"}

    async def _handle_open_in_cursor(self, params: dict) -> dict:
        """Open an issue's work log in Cursor for interactive continuation.

        This creates a new Cursor chat with the context from the background work,
        allowing the user to continue working on the issue interactively.
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        # Load work log
        work_log = self._load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        # Check if Cursor is available
        cursor_available = await self._is_cursor_available()
        if not cursor_available:
            return {"success": False, "error": "Cursor is not available. Please open VS Code/Cursor first."}

        # Build the context prompt from the work log
        prompt = self._build_cursor_context_prompt(issue_key, work_log)

        # Create a Cursor chat with this context
        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            introspection = await bus.introspect("com.aiworkflow.Chat", "/com/aiworkflow/Chat")
            proxy = bus.get_proxy_object("com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection)
            chat_interface = proxy.get_interface("com.aiworkflow.Chat")

            # Launch the chat with context
            result = await chat_interface.call_launch_issue_chat(
                issue_key,
                f"Continue: {work_log.get('summary', '')}",
                False,  # Don't return to previous - user wants to work on this
            )

            bus.disconnect()

            if result:
                result_dict = json.loads(str(result))
                if result_dict.get("success"):
                    chat_id = result_dict.get("chatId")

                    # Update the issue with the new chat ID
                    state = self._load_state()
                    for issue in state.get("issues", []):
                        if issue.get("key") == issue_key:
                            issue["chatId"] = chat_id
                            issue["timeline"] = issue.get("timeline", [])
                            issue["timeline"].append(
                                {
                                    "timestamp": datetime.now().isoformat(),
                                    "action": "opened_in_cursor",
                                    "description": "Opened background work in Cursor for interactive continuation",
                                    "chatLink": chat_id,
                                }
                            )
                            break
                    self._save_state(state)

                    logger.info(f"Opened {issue_key} in Cursor: {chat_id}")
                    return {
                        "success": True,
                        "message": f"Opened {issue_key} in Cursor",
                        "chat_id": chat_id,
                        "context_prompt": prompt,
                    }

            return {"success": False, "error": "Failed to create Cursor chat"}

        except Exception as e:
            logger.error(f"Failed to open {issue_key} in Cursor: {e}")
            return {"success": False, "error": str(e)}

    def _build_cursor_context_prompt(self, issue_key: str, work_log: dict) -> str:
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
                parts.append(f"- **Merge Requests**: {', '.join(outcome['merge_requests'])}")
            if outcome.get("files_changed"):
                parts.append(f"- **Files Changed**: {', '.join(outcome['files_changed'][:10])}")
            if outcome.get("branches_created"):
                parts.append(f"- **Branches**: {', '.join(outcome['branches_created'])}")
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
        parts.append("Please review the above context and continue working on this issue.")
        parts.append('Load the developer persona if needed: `persona_load("developer")`')

        return "\n".join(parts)

    # ==================== State Management ====================

    def _load_state(self) -> dict:
        """Load sprint state from sprint_state.json.

        Handles backward compatibility with old 'botEnabled' field.
        """
        try:
            if SPRINT_STATE_FILE.exists():
                state = json.loads(SPRINT_STATE_FILE.read_text())

                # Migrate old 'botEnabled' field to new fields
                if "botEnabled" in state and "automaticMode" not in state:
                    state["automaticMode"] = state.pop("botEnabled", False)
                    state["manuallyStarted"] = False

                # Ensure new fields exist
                if "automaticMode" not in state:
                    state["automaticMode"] = False
                if "manuallyStarted" not in state:
                    state["manuallyStarted"] = False
                if "nextSprint" not in state:
                    state["nextSprint"] = None

                return state
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
        return self._default_state()

    def _save_state(self, sprint_state: dict) -> None:
        """Save sprint state to sprint_state.json.

        Each service owns its own state file. The VS Code extension reads
        all state files on refresh. No shared file = no race conditions.
        """
        try:
            import tempfile

            SPRINT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Add workflow config to state for UI consumption
            sprint_state["workflowConfig"] = self._export_workflow_config()

            # Write atomically (temp file + rename)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="sprint_state_", dir=SPRINT_STATE_FILE.parent)
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(sprint_state, f, indent=2, default=str)
                Path(temp_path).replace(SPRINT_STATE_FILE)
            except Exception:
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass
                raise

        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _export_workflow_config(self) -> dict:
        """Export workflow configuration for UI consumption.

        Returns a simplified version of the workflow config that the UI needs
        for rendering status sections and colors.
        """
        config = self.workflow_config

        # Export status mappings
        status_mappings = {}
        for stage, stage_config in config.get_all_status_mappings().items():
            status_mappings[stage] = {
                "displayName": stage_config.get("display_name", stage.title()),
                "icon": stage_config.get("icon", "📋"),
                "color": stage_config.get("color", "gray"),
                "description": stage_config.get("description", ""),
                "jiraStatuses": stage_config.get("jira_statuses", []),
                "botCanWork": stage_config.get("bot_can_work", False),
                "uiOrder": stage_config.get("ui_order", 99),
                "showApproveButtons": stage_config.get("show_approve_buttons", False),
                "botMonitors": stage_config.get("bot_monitors", False),
            }

        # Export merge hold patterns
        merge_hold_patterns = config.get_merge_hold_patterns()

        # Export issue classification keywords
        issue_classification = config.get("issue_classification", {})
        spike_keywords = issue_classification.get("spike", {}).get("keywords", [])

        return {
            "statusMappings": status_mappings,
            "mergeHoldPatterns": merge_hold_patterns,
            "spikeKeywords": spike_keywords,
            "version": config.get("version", "1.0"),
        }

    def _default_state(self) -> dict:
        """Return default sprint state."""
        return {
            "currentSprint": None,
            "nextSprint": None,
            "issues": [],
            "automaticMode": False,  # Bot runs on schedule (Mon-Fri 9-5)
            "manuallyStarted": False,  # Bot is running now (ignores schedule)
            "backgroundTasks": False,
            "lastUpdated": datetime.now().isoformat(),
            "processingIssue": None,
        }

    # ==================== Working Hours ====================

    def _is_within_working_hours(self) -> bool:
        """Check if current time is within working hours."""
        wh = self._config["working_hours"]

        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(wh["timezone"])
            now = datetime.now(tz)
        except ImportError:
            now = datetime.now()

        # Check weekday (0=Monday, 6=Sunday)
        if wh["weekdays_only"] and now.weekday() >= 5:
            return False

        # Check time
        start = time(wh["start_hour"], wh["start_minute"])
        end = time(wh["end_hour"], wh["end_minute"])
        current_time = now.time()

        return start <= current_time <= end

    # ==================== Jira Integration ====================

    async def _refresh_from_jira(self) -> None:
        """Refresh sprint issues from Jira by calling the Jira API directly.

        Fetches sprint issues and saves to state file.
        """
        logger.info("Refreshing sprint issues from Jira...")

        try:
            from tool_modules.aa_workflow.src.sprint_bot import (
                SprintBotConfig,
                WorkingHours,
                fetch_sprint_issues,
                to_sprint_issue_format,
            )
            from tool_modules.aa_workflow.src.sprint_history import (
                SprintIssue,
                SprintState,
                load_sprint_state,
                save_sprint_state,
            )
            from tool_modules.aa_workflow.src.sprint_prioritizer import prioritize_issues

            config = SprintBotConfig(
                working_hours=WorkingHours(),
                jira_project="AAP",
            )

            # Fetch issues from Jira (async)
            jira_issues = await fetch_sprint_issues(config)

            if not jira_issues:
                logger.warning("No issues fetched from Jira, keeping existing state")
                self._last_jira_refresh = datetime.now()
                return

            # Filter to only show issues assigned to current user
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

            if not jira_issues:
                logger.info("No issues assigned to current user, clearing sprint list")
                state = load_sprint_state()
                state.issues = []
                state.last_updated = datetime.now().isoformat()
                save_sprint_state(state)
                self._last_jira_refresh = datetime.now()
                return

            # Prioritize issues
            prioritized = prioritize_issues(jira_issues)
            sprint_issues = to_sprint_issue_format(prioritized)

            # Load existing state to preserve approval status, chat IDs, etc.
            state = load_sprint_state()
            existing_by_key = {issue.key: issue for issue in state.issues}

            # Merge with existing state
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

            logger.info(f"Sprint refresh completed: {len(new_issues)} issues")
            self._last_jira_refresh = datetime.now()

        except Exception as e:
            logger.error(f"Failed to refresh sprint: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            # Don't block - use existing state
            self._last_jira_refresh = datetime.now()

    async def _check_review_issues(self) -> None:
        """Check issues in Review status and try to move them to Done.

        This runs periodically (3x daily) to:
        1. Find issues in "In Review" status
        2. Check if their MR is approved and CI passed
        3. Check for "don't merge" comments
        4. Merge the MR and transition to Done if ready

        This automates the final step of the workflow.
        """
        logger.info("Checking issues in Review for merge readiness...")
        self._last_review_check = datetime.now()

        state = self._load_state()
        issues = state.get("issues", [])

        # Find issues in Review status
        review_statuses = ["in review", "review", "code review", "peer review"]
        review_issues = [i for i in issues if i.get("jiraStatus", "").lower() in review_statuses]

        if not review_issues:
            logger.info("No issues in Review status")
            return

        logger.info(f"Found {len(review_issues)} issues in Review")

        # Patterns that indicate "don't merge yet"
        dont_merge_patterns = [
            "don't merge",
            "do not merge",
            "dont merge",
            "hold off",
            "hold merge",
            "wait until",
            "don't merge until",
            "do not merge until",
            "needs more work",
            "wip",
            "work in progress",
        ]

        for issue in review_issues:
            issue_key = issue.get("key")
            if not issue_key:
                continue

            try:
                await self._check_single_review_issue(issue, dont_merge_patterns, state)
            except Exception as e:
                logger.error(f"Error checking review issue {issue_key}: {e}")
                continue

        # Save any state changes
        self._save_state(state)

    async def _check_single_review_issue(self, issue: dict, dont_merge_patterns: list, state: dict) -> None:
        """Check a single issue in Review and try to merge/close if ready."""
        issue_key = issue.get("key")
        logger.info(f"Checking review status for {issue_key}")

        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning("Claude CLI not found, skipping review check")
                return

            # Build prompt to check MR status
            prompt = f"""Check the merge request status for Jira issue {issue_key}.

1. First, find the MR for this issue:
   ```
   gitlab_mr_list(project="automation-analytics/automation-analytics-backend", search="{issue_key}")
   ```

2. If an MR exists, check its status:
   - Is it approved?
   - Has the pipeline passed?
   - Are there any comments containing: {', '.join(dont_merge_patterns[:5])}

3. Report the status in this exact format:
   [MR_STATUS: READY_TO_MERGE] - MR is approved, CI passed, no hold comments
   [MR_STATUS: APPROVED_WITH_HOLD] reason: <the hold comment>
   [MR_STATUS: NEEDS_APPROVAL] - MR not yet approved
   [MR_STATUS: CI_FAILING] - Pipeline failed
   [MR_STATUS: NO_MR] - No MR found for this issue
   [MR_STATUS: CHANGES_REQUESTED] - Reviewer requested changes

Also output the MR ID if found: [MR_ID: <number>]
"""

            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=120,  # 2 minute timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Review check timed out for {issue_key}")
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the status
            import re

            status_match = re.search(r"\[MR_STATUS:\s*(\w+(?:_\w+)*)\](?:\s*reason:\s*(.+))?", output, re.IGNORECASE)
            mr_id_match = re.search(r"\[MR_ID:\s*(\d+)\]", output)

            if not status_match:
                logger.warning(f"Could not parse MR status for {issue_key}")
                return

            mr_status = status_match.group(1).upper()
            hold_reason = status_match.group(2).strip() if status_match.group(2) else None
            mr_id = int(mr_id_match.group(1)) if mr_id_match else None

            logger.info(f"{issue_key}: MR status = {mr_status}, MR ID = {mr_id}")

            if mr_status == "READY_TO_MERGE" and mr_id:
                # Merge the MR and transition to Done
                await self._merge_and_close(issue_key, mr_id, issue, state)

            elif mr_status == "APPROVED_WITH_HOLD":
                # Log but don't merge
                logger.info(f"{issue_key}: MR approved but on hold: {hold_reason}")
                issue["timeline"] = issue.get("timeline", [])
                issue["timeline"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "review_hold",
                        "description": f"MR approved but merge on hold: {hold_reason}",
                    }
                )

            elif mr_status == "CHANGES_REQUESTED":
                logger.info(f"{issue_key}: Changes requested on MR")
                # Could notify or take action here

            elif mr_status == "CI_FAILING":
                logger.info(f"{issue_key}: CI is failing")
                # Could notify or take action here

            elif mr_status == "NO_MR":
                logger.warning(f"{issue_key}: No MR found but issue is in Review")

        except Exception as e:
            logger.error(f"Error checking MR status for {issue_key}: {e}")

    async def _merge_and_close(self, issue_key: str, mr_id: int, issue: dict, state: dict) -> None:
        """Merge an MR and transition the Jira issue to Done."""
        logger.info(f"Merging MR !{mr_id} and closing {issue_key}")

        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning("Claude CLI not found, cannot merge")
                return

            # Build prompt to merge and close
            prompt = f"""Merge the MR and close the Jira issue:

1. Merge the MR:
   ```
   gitlab_mr_merge(project="automation-analytics/automation-analytics-backend", mr_id={mr_id}, when_pipeline_succeeds=true)
   ```

2. Close the Jira issue:
   ```
   skill_run("close_issue", '{{"issue_key": "{issue_key}"}}')
   ```

3. Report the result:
   [MERGE_RESULT: SUCCESS] - MR merged and issue closed
   [MERGE_RESULT: MERGE_FAILED] error: <reason>
   [MERGE_RESULT: CLOSE_FAILED] error: <reason>
"""

            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=180,  # 3 minute timeout for merge
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Merge/close timed out for {issue_key}")
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the result
            import re

            result_match = re.search(r"\[MERGE_RESULT:\s*(\w+)\](?:\s*error:\s*(.+))?", output, re.IGNORECASE)

            if result_match:
                result = result_match.group(1).upper()
                error = result_match.group(2).strip() if result_match.group(2) else None

                if result == "SUCCESS":
                    logger.info(f"Successfully merged MR !{mr_id} and closed {issue_key}")

                    # Update local state
                    issue["jiraStatus"] = self.JIRA_STATUS_DONE
                    issue["approvalStatus"] = "completed"
                    issue["timeline"] = issue.get("timeline", [])
                    issue["timeline"].append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "merged_and_closed",
                            "description": f"MR !{mr_id} merged, issue closed",
                            "jiraTransition": self.JIRA_STATUS_DONE,
                        }
                    )
                    self._issues_completed += 1
                else:
                    logger.warning(f"Merge/close failed for {issue_key}: {error}")
                    issue["timeline"] = issue.get("timeline", [])
                    issue["timeline"].append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "merge_failed",
                            "description": f"Failed to merge/close: {error}",
                        }
                    )
            else:
                logger.warning(f"Could not parse merge result for {issue_key}")

        except Exception as e:
            logger.error(f"Error merging/closing {issue_key}: {e}")

    # ==================== Issue Processing ====================

    # ==================== WORKFLOW CONFIG ====================
    # Status mappings and workflow logic are loaded from config.json -> sprint section
    # See: server/config_manager.py and scripts/sprint_bot/workflow_config.py

    @property
    def workflow_config(self) -> WorkflowConfig:
        """Get the workflow configuration (lazy loaded)."""
        if not hasattr(self, "_workflow_config") or self._workflow_config is None:
            self._workflow_config = get_workflow_config()
        return self._workflow_config

    # Legacy properties for backward compatibility - delegate to config
    @property
    def ACTIONABLE_STATUSES(self) -> list[str]:
        """Get actionable statuses from config."""
        return self.workflow_config.get_actionable_statuses()

    @property
    def JIRA_STATUS_IN_PROGRESS(self) -> str:
        """Get In Progress status name from config."""
        return self.workflow_config.get_jira_transition("in_progress")

    @property
    def JIRA_STATUS_IN_REVIEW(self) -> str:
        """Get In Review status name from config."""
        return self.workflow_config.get_jira_transition("in_review")

    @property
    def JIRA_STATUS_DONE(self) -> str:
        """Get Done status name from config."""
        return self.workflow_config.get_jira_transition("done")

    def _build_work_prompt(self, issue: dict) -> str:
        """Build the unified work prompt for both foreground and background modes.

        This prompt guides the bot through the complete workflow from understanding
        the issue to completing the work and transitioning Jira status.

        Now delegates to WorkflowConfig for the actual prompt building.
        """
        return self.workflow_config.build_work_prompt(issue)

    # ==================== EXECUTION TRACING ====================
    # Tracks state machine transitions and step execution for observability

    def _get_tracer(self, issue_key: str, issue: dict = None) -> ExecutionTracer:
        """Get or create an execution tracer for an issue.

        Loads existing trace if available, otherwise creates a new one.
        """
        # Try to load existing trace
        tracer = ExecutionTracer.load(issue_key)

        if tracer is None:
            # Create new tracer
            workflow_type = None
            execution_mode = "foreground"

            if issue:
                workflow_type = self.workflow_config.classify_issue(issue)
                state = self._load_state()
                execution_mode = "background" if state.get("backgroundTasks", True) else "foreground"

            tracer = ExecutionTracer(
                issue_key=issue_key,
                workflow_type=workflow_type,
                execution_mode=execution_mode,
            )

        return tracer

    def _trace_step(
        self,
        tracer: ExecutionTracer,
        name: str,
        inputs: dict = None,
        outputs: dict = None,
        decision: str = None,
        reason: str = None,
        skill_name: str = None,
        tool_name: str = None,
        status: StepStatus = StepStatus.SUCCESS,
        error: str = None,
        chat_id: str = None,
    ) -> None:
        """Log a step to the tracer and save."""
        tracer.log_step(
            name=name,
            inputs=inputs,
            outputs=outputs,
            decision=decision,
            reason=reason,
            skill_name=skill_name,
            tool_name=tool_name,
            status=status,
            error=error,
            chat_id=chat_id,
        )
        tracer.save()

    def _trace_transition(
        self,
        tracer: ExecutionTracer,
        to_state: WorkflowState,
        trigger: str = None,
        data: dict = None,
    ) -> None:
        """Log a state transition and save."""
        tracer.transition(to_state, trigger, data)
        tracer.save()

    async def _transition_jira_issue(self, issue_key: str, target_status: str) -> bool:
        """Transition a Jira issue to a new status using Claude CLI.

        Returns True if successful, False otherwise.
        """
        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning(f"Claude CLI not found, cannot transition {issue_key}")
                return False

            prompt = f'Call jira_transition("{issue_key}", "{target_status}") to move the issue to {target_status}.'

            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60,  # 1 minute timeout for transition
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Jira transition timed out for {issue_key}")
                return False

            if process.returncode == 0:
                logger.info(f"Transitioned {issue_key} to {target_status}")
                return True
            else:
                error = stderr.decode("utf-8", errors="replace") if stderr else ""
                logger.warning(f"Failed to transition {issue_key}: {error[:200]}")
                return False

        except Exception as e:
            logger.error(f"Error transitioning {issue_key}: {e}")
            return False

    def _is_actionable(self, issue: dict) -> bool:
        """Check if an issue is actionable based on its Jira status.

        Uses WorkflowConfig to determine actionability based on status mappings.
        Bot should only work on issues in statuses marked with bot_can_work=true.
        """
        return self.workflow_config.is_actionable(issue)

    async def _process_next_issue(self) -> dict:
        """Process the next approved issue that is actionable.

        Execution mode depends on backgroundTasks setting:
        - backgroundTasks=false (Foreground): Opens Cursor chat, WAITS if Cursor not available
        - backgroundTasks=true (Background): Runs via Claude CLI, no Cursor dependency

        Now includes execution tracing for full observability.
        """
        state = self._load_state()

        # Find next approved issue that is also actionable
        next_issue = None
        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "approved" and self._is_actionable(issue):
                next_issue = issue
                break

        if not next_issue:
            return {"success": True, "message": "No approved actionable issues to process"}

        issue_key = next_issue["key"]
        background_mode = state.get("backgroundTasks", True)

        logger.info(f"Processing issue: {issue_key} (background={background_mode})")

        # Initialize execution tracer
        tracer = self._get_tracer(issue_key, next_issue)
        self._trace_transition(tracer, WorkflowState.LOADING, trigger="start_processing")

        # Log issue loading step
        self._trace_step(
            tracer,
            "load_issue",
            inputs={"issue_key": issue_key, "approval_status": next_issue.get("approvalStatus")},
            outputs={"summary": next_issue.get("summary", "")[:100], "jira_status": next_issue.get("jiraStatus")},
        )
        self._trace_transition(tracer, WorkflowState.ANALYZING, trigger="issue_loaded")

        # Classify the issue
        workflow_type = self.workflow_config.classify_issue(next_issue)
        tracer.set_workflow_type(
            workflow_type,
            reason=f"Issue type: {next_issue.get('issueType', 'Story')}, keywords matched: {workflow_type}",
        )
        self._trace_transition(tracer, WorkflowState.CLASSIFYING, trigger="analysis_complete")

        # Check actionability
        is_actionable = self._is_actionable(next_issue)
        self._trace_step(
            tracer,
            "check_actionable",
            inputs={"jira_status": next_issue.get("jiraStatus")},
            outputs={"is_actionable": is_actionable},
            decision="actionable" if is_actionable else "not_actionable",
            reason=f"Status '{next_issue.get('jiraStatus')}' is {'actionable' if is_actionable else 'not actionable'} per workflow config",
        )
        self._trace_transition(tracer, WorkflowState.CHECKING_ACTIONABLE, trigger="classified")

        # Check Cursor availability
        cursor_available = await self._is_cursor_available()

        # FOREGROUND MODE: Requires Cursor - wait if not available
        if not background_mode:
            if not cursor_available:
                logger.info(f"Foreground mode: Cursor not available, waiting...")
                self._trace_step(
                    tracer,
                    "check_cursor",
                    inputs={"mode": "foreground"},
                    outputs={"cursor_available": False},
                    status=StepStatus.SKIPPED,
                    reason="Cursor not available, waiting...",
                )
                return {"success": False, "waiting": True, "message": "Waiting for Cursor to be available"}

            # Cursor is available - launch chat
            self._trace_step(
                tracer,
                "check_cursor",
                inputs={"mode": "foreground"},
                outputs={"cursor_available": True},
            )
            return await self._process_in_cursor_traced(next_issue, state, tracer)

        # BACKGROUND MODE: Run via Claude CLI (no Cursor dependency)
        logger.info(f"Background mode: Running {issue_key} via Claude CLI")
        self._trace_step(
            tracer,
            "select_execution_mode",
            inputs={"background_tasks": True, "cursor_available": cursor_available},
            decision="background",
            reason="Background mode enabled, running via Claude CLI",
        )

        # Transition to starting work
        self._trace_transition(tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable")

        # Transition Jira issue to "In Progress"
        jira_success = await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_PROGRESS)
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={"issue_key": issue_key, "target_status": self.JIRA_STATUS_IN_PROGRESS},
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )

        if workflow_type == "spike":
            self._trace_transition(tracer, WorkflowState.RESEARCHING, trigger="transitioned_spike")
        else:
            self._trace_transition(tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change")

        # Update local status
        next_issue["approvalStatus"] = "in_progress"
        next_issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        next_issue["timeline"] = next_issue.get("timeline", [])
        next_issue["timeline"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            }
        )
        # Add trace reference to issue
        next_issue["hasTrace"] = True
        next_issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created")
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": workflow_type},
            outputs={"prompt_length": len(self._build_work_prompt(next_issue))},
        )

        # Run in background
        self._trace_transition(tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background")
        result = await self._run_issue_in_background_traced(next_issue, tracer)

        # Reload state in case it changed
        state = self._load_state()
        next_issue = next((i for i in state.get("issues", []) if i["key"] == issue_key), next_issue)

        if result.get("success"):
            # Transition Jira issue to "In Review" (work completed, MR created)
            self._trace_transition(tracer, WorkflowState.CREATING_MR, trigger="implementation_complete")

            await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_REVIEW)
            self._trace_step(
                tracer,
                "transition_jira_review",
                inputs={"issue_key": issue_key, "target_status": self.JIRA_STATUS_IN_REVIEW},
                outputs={"success": True},
                tool_name="jira_transition",
            )

            self._trace_transition(tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created")
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            next_issue["timeline"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self._get_work_log_path(issue_key)),
                    "jiraTransition": self.JIRA_STATUS_IN_REVIEW,
                }
            )
            next_issue["approvalStatus"] = "completed"
            next_issue["jiraStatus"] = self.JIRA_STATUS_IN_REVIEW
            next_issue["hasWorkLog"] = True
            next_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            next_issue["hasTrace"] = True
            next_issue["tracePath"] = str(tracer.trace_path)
            state["processingIssue"] = None
            self._save_state(state)
            self._issues_processed += 1
            return result
        else:
            # Bot is blocked - keep in "In Progress" but mark as blocked with reason
            # Do NOT transition Jira status - it stays "In Progress"
            error_reason = result.get("error", "Background processing failed")

            tracer.mark_blocked(error_reason)

            next_issue["timeline"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                }
            )
            next_issue["approvalStatus"] = "blocked"
            next_issue["waitingReason"] = error_reason
            # jiraStatus stays as "In Progress" - issue is not done, just blocked
            next_issue["hasWorkLog"] = True
            next_issue["hasTrace"] = True
            next_issue["tracePath"] = str(tracer.trace_path)
            next_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            state["processingIssue"] = None
            self._save_state(state)
            return result

    async def _process_in_cursor(self, issue: dict, state: dict) -> dict:
        """Process an issue by opening a Cursor chat (foreground mode).

        In foreground mode, the bot creates a Cursor chat and the user/bot
        works interactively. The Jira transitions happen:
        - Start: Transition to "In Progress"
        - The chat itself handles completion/review transitions via skills
        """
        # Create tracer and delegate to traced version
        tracer = self._get_tracer(issue["key"], issue)
        return await self._process_in_cursor_traced(issue, state, tracer)

    async def _process_in_cursor_traced(self, issue: dict, state: dict, tracer: ExecutionTracer) -> dict:
        """Process an issue in Cursor with full execution tracing."""
        issue_key = issue["key"]

        # Transition to starting work
        self._trace_transition(tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable")

        # Transition Jira issue to "In Progress"
        jira_success = await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_PROGRESS)
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={"issue_key": issue_key, "target_status": self.JIRA_STATUS_IN_PROGRESS},
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )

        self._trace_transition(tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change")

        # Update local status
        issue["approvalStatus"] = "in_progress"
        issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        issue["timeline"] = issue.get("timeline", [])
        issue["timeline"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started processing in Cursor",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            }
        )
        issue["hasTrace"] = True
        issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created")
        prompt = self._build_work_prompt(issue)
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": tracer.workflow_type},
            outputs={"prompt_length": len(prompt)},
        )

        # Launch Cursor chat
        self._trace_transition(tracer, WorkflowState.LAUNCHING_CHAT, trigger="prompt_ready_foreground")
        self._trace_step(tracer, "launch_cursor_chat", inputs={"issue_key": issue_key})

        chat_id = await self._launch_cursor_chat(issue)

        if chat_id:
            self._trace_step(
                tracer,
                "chat_created",
                outputs={"chat_id": chat_id},
                chat_id=chat_id,
            )
            self._trace_transition(tracer, WorkflowState.IMPLEMENTING, trigger="chat_launched")

            issue["chatId"] = chat_id
            issue["timeline"].append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "chat_created",
                    "description": "Cursor chat created - work in progress",
                    "chatLink": chat_id,
                }
            )
            self._save_state(state)
            self._issues_processed += 1
            logger.info(f"Chat created for {issue_key}: {chat_id}")

            # Note: In foreground mode, the tracer stays in IMPLEMENTING state
            # The chat itself will complete the work and transition Jira
            tracer.save()

            return {"success": True, "message": f"Processing {issue_key}", "chat_id": chat_id}
        else:
            # Chat creation failed - mark as blocked but keep In Progress in Jira
            self._trace_step(
                tracer,
                "chat_creation_failed",
                error="Failed to create Cursor chat",
                status=StepStatus.FAILED,
            )
            tracer.mark_blocked("Failed to create Cursor chat")

            issue["approvalStatus"] = "blocked"
            issue["waitingReason"] = "Failed to create Cursor chat"
            state["processingIssue"] = None
            self._save_state(state)
            logger.warning(f"Could not create chat for {issue_key}")
            return {"success": False, "error": f"Failed to create chat for {issue_key}"}

    async def _launch_cursor_chat(self, issue: dict) -> str | None:
        """Launch a Cursor chat for an issue via D-Bus.

        Calls the VS Code extension's D-Bus service to create a new chat
        for the given issue with the unified work prompt. The extension will:
        1. Create a new Cursor chat
        2. Name it with the issue key (using Cursor's auto-naming)
        3. Paste the unified work prompt
        4. Optionally return to the previous chat (background mode)

        Returns the chat ID if successful, None otherwise.
        """
        state = self._load_state()
        return_to_previous = state.get("backgroundTasks", True)

        # Build the unified work prompt
        prompt = self._build_work_prompt(issue)

        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()

            # Get the VS Code extension's chat service
            introspection = await bus.introspect("com.aiworkflow.Chat", "/com/aiworkflow/Chat")

            proxy = bus.get_proxy_object("com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection)

            chat_interface = proxy.get_interface("com.aiworkflow.Chat")

            # Launch the chat with the unified prompt
            # Method signature: LaunchIssueChatWithPrompt(issueKey, summary, prompt, returnToPrevious) -> string
            result = await chat_interface.call_launch_issue_chat_with_prompt(
                issue["key"],
                issue.get("summary", "sprint work"),
                prompt,
                return_to_previous,
            )

            bus.disconnect()

            if result:
                result_dict = json.loads(str(result))
                if result_dict.get("success"):
                    return result_dict.get("chatId")
                else:
                    logger.warning(f"LaunchIssueChatWithPrompt returned error: {result_dict.get('error')}")

            return None

        except Exception as e:
            logger.error(f"Failed to launch chat via D-Bus: {e}")
            logger.debug(f"Is VS Code running with the AA Workflow extension active?")
            return None

    # ==================== Background Execution ====================

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

    def _log_action(self, issue_key: str, action_type: str, details: str, data: dict = None) -> None:
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

    async def _run_issue_in_background(self, issue: dict) -> dict:
        """Run issue processing via Claude CLI (no Cursor chat).

        This is used when backgroundTasks=true and allows the bot to work
        without requiring Cursor to be open.

        The work log captures all actions so the issue can be continued
        interactively in Cursor later if needed.

        Returns dict with success status and details.
        """
        # Create tracer and delegate to traced version
        tracer = self._get_tracer(issue["key"], issue)
        return await self._run_issue_in_background_traced(issue, tracer)

    async def _run_issue_in_background_traced(self, issue: dict, tracer: ExecutionTracer) -> dict:
        """Run issue processing via Claude CLI with full execution tracing.

        Returns dict with success status and details.
        """
        issue_key = issue["key"]
        summary = issue.get("summary", "")
        description = issue.get("description", "")

        logger.info(f"Running {issue_key} in background mode (Claude CLI)")

        # Initialize work log
        work_log = self._init_work_log(issue)
        self._save_work_log(issue_key, work_log)

        self._log_action(issue_key, "started", "Background processing started")
        self._trace_step(tracer, "init_work_log", outputs={"work_log_path": str(self._get_work_log_path(issue_key))})

        # Emit toast notification for issue started
        try:
            from tool_modules.aa_workflow.src.notification_emitter import notify_sprint_issue_started

            notify_sprint_issue_started(issue_key, issue.get("summary", "")[:50])
        except Exception:
            pass

        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                self._log_action(issue_key, "error", "Claude CLI not found")
                self._trace_step(tracer, "check_claude_cli", error="Claude CLI not found", status=StepStatus.FAILED)
                tracer.mark_failed("Claude CLI not found")
                work_log["status"] = "failed"
                work_log["error"] = "Claude CLI not found"
                self._save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI not found"}

            self._trace_step(tracer, "check_claude_cli", outputs={"claude_path": claude_path})

            # Build the unified work prompt
            prompt = self._build_work_prompt(issue)

            self._log_action(
                issue_key,
                "claude_started",
                "Started Claude CLI execution",
                {
                    "prompt_length": len(prompt),
                },
            )

            # Start step for Claude execution
            step_id = tracer.start_step("execute_claude_cli", inputs={"prompt_length": len(prompt)})

            # Run Claude CLI with extended timeout for actual work
            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=1800,  # 30 minute timeout for actual work
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                self._log_action(issue_key, "timeout", "Claude CLI timed out after 30 minutes")
                tracer.end_step(step_id, status=StepStatus.FAILED, error="Timeout after 30 minutes")
                tracer.mark_failed("Claude CLI timed out after 30 minutes")
                work_log = self._load_work_log(issue_key)
                work_log["status"] = "timeout"
                work_log["completed"] = datetime.now().isoformat()
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"][
                    "suggested_prompt"
                ] = f"Continue working on {issue_key}. The background process timed out. Review the work log and continue from where it left off."
                self._save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI timed out"}

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Update work log with results
            work_log = self._load_work_log(issue_key)
            work_log["completed"] = datetime.now().isoformat()

            # Parse output to extract useful information
            self._parse_background_output(issue_key, output, work_log)

            # Check for explicit status markers in output
            bot_status = self._parse_bot_status(output)

            # End the Claude execution step
            tracer.end_step(
                step_id,
                status=(
                    StepStatus.SUCCESS
                    if bot_status["status"] in ("COMPLETED", "UNKNOWN") and process.returncode == 0
                    else StepStatus.FAILED
                ),
                outputs={
                    "return_code": process.returncode,
                    "bot_status": bot_status["status"],
                    "output_length": len(output),
                    "commits_found": len(work_log.get("outcome", {}).get("commits", [])),
                    "mrs_found": len(work_log.get("outcome", {}).get("merge_requests", [])),
                },
            )

            if bot_status["status"] == "COMPLETED":
                work_log["status"] = "completed"
                self._log_action(issue_key, "completed", "Background processing completed successfully")

                # Emit toast notification for issue completed
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import notify_sprint_issue_completed

                    notify_sprint_issue_completed(issue_key)
                except Exception:
                    pass
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="completed",
                    reason="Bot reported COMPLETED status",
                    outputs={"commits": work_log.get("outcome", {}).get("commits", [])},
                )

                # Create context for continuing in Cursor
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = self._generate_continuation_prompt(issue_key, work_log)

                self._save_work_log(issue_key, work_log)
                logger.info(f"Background processing completed for {issue_key}")
                return {"success": True, "message": f"Completed {issue_key} in background"}

            elif bot_status["status"] == "BLOCKED":
                # Bot is blocked - needs human intervention
                blocked_reason = bot_status.get("reason", "Unknown reason")
                work_log["status"] = "blocked"
                work_log["blocked_reason"] = blocked_reason
                self._log_action(issue_key, "blocked", f"Bot blocked: {blocked_reason}")

                # Emit toast notification for issue blocked
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import notify_sprint_issue_blocked

                    notify_sprint_issue_blocked(issue_key, blocked_reason)
                except Exception:
                    pass
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="blocked",
                    reason=blocked_reason,
                    status=StepStatus.FAILED,
                )

                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"][
                    "suggested_prompt"
                ] = f"The bot was blocked on {issue_key}: {blocked_reason}. Please provide the needed information or continue the work."

                self._save_work_log(issue_key, work_log)
                logger.warning(f"Background processing blocked for {issue_key}: {blocked_reason}")
                return {"success": False, "error": f"Blocked: {blocked_reason}", "blocked": True}

            elif bot_status["status"] == "FAILED" or process.returncode != 0:
                # Bot failed
                error_reason = bot_status.get("error") or error_output[:500]
                work_log["status"] = "failed"
                work_log["error"] = error_reason
                self._log_action(issue_key, "failed", f"Background processing failed: {error_reason[:200]}")
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="failed",
                    error=error_reason[:200],
                    status=StepStatus.FAILED,
                )

                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"][
                    "suggested_prompt"
                ] = f"The background process for {issue_key} failed: {error_reason[:200]}. Please investigate and continue the work."

                self._save_work_log(issue_key, work_log)
                logger.warning(f"Background processing failed for {issue_key}: {error_reason[:200]}")
                return {"success": False, "error": f"Failed: {error_reason[:200]}"}

            else:
                # No explicit status - assume completed if return code is 0
                if process.returncode == 0:
                    work_log["status"] = "completed"
                    self._log_action(issue_key, "completed", "Background processing completed (no explicit status)")
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"]["suggested_prompt"] = self._generate_continuation_prompt(
                        issue_key, work_log
                    )
                    self._save_work_log(issue_key, work_log)
                    logger.info(f"Background processing completed for {issue_key}")
                    return {"success": True, "message": f"Completed {issue_key} in background"}
                else:
                    work_log["status"] = "failed"
                    work_log["error"] = error_output[:500]
                    self._log_action(issue_key, "failed", f"Claude CLI failed: {error_output[:200]}")
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"][
                        "suggested_prompt"
                    ] = f"The background process for {issue_key} failed. Please investigate and continue the work."
                    self._save_work_log(issue_key, work_log)
                    logger.warning(f"Background processing failed for {issue_key}: {error_output[:200]}")
                    return {"success": False, "error": f"Claude CLI failed: {error_output[:200]}"}

        except Exception as e:
            self._log_action(issue_key, "error", f"Exception: {str(e)}")
            work_log = self._load_work_log(issue_key)
            work_log["status"] = "failed"
            work_log["error"] = str(e)
            work_log["completed"] = datetime.now().isoformat()
            work_log["cursor_context"]["can_continue"] = True
            work_log["cursor_context"][
                "suggested_prompt"
            ] = f"The background process for {issue_key} encountered an error: {str(e)}. Please investigate and continue the work."
            self._save_work_log(issue_key, work_log)
            logger.error(f"Background processing error for {issue_key}: {e}")
            return {"success": False, "error": str(e)}

    def _parse_bot_status(self, output: str) -> dict:
        """Parse the bot status marker from Claude CLI output.

        Looks for lines like:
        - [SPRINT_BOT_STATUS: COMPLETED]
        - [SPRINT_BOT_STATUS: BLOCKED] reason: Need clarification
        - [SPRINT_BOT_STATUS: FAILED] error: Could not find file

        Returns dict with 'status' and optional 'reason' or 'error'.
        """
        import re

        # Look for status marker
        status_pattern = r"\[SPRINT_BOT_STATUS:\s*(COMPLETED|BLOCKED|FAILED)\](?:\s*(?:reason|error):\s*(.+))?"
        match = re.search(status_pattern, output, re.IGNORECASE)

        if match:
            status = match.group(1).upper()
            detail = match.group(2).strip() if match.group(2) else None

            result = {"status": status}
            if status == "BLOCKED" and detail:
                result["reason"] = detail
            elif status == "FAILED" and detail:
                result["error"] = detail

            return result

        return {"status": "UNKNOWN"}

    def _parse_background_output(self, issue_key: str, output: str, work_log: dict) -> None:
        """Parse Claude CLI output to extract commits, MRs, files changed, etc."""
        import re

        # Store full output (truncated for large outputs)
        work_log["output_summary"] = output[:5000] if len(output) > 5000 else output

        # Extract commit hashes (git commit output patterns)
        commit_pattern = r"\[[\w-]+\s+([a-f0-9]{7,40})\]"
        commits = re.findall(commit_pattern, output)
        if commits:
            work_log["outcome"]["commits"].extend(commits)
            self._log_action(issue_key, "commits_created", f"Created {len(commits)} commit(s)", {"commits": commits})

        # Extract MR/PR URLs or IDs
        mr_pattern = r"[Mm]erge [Rr]equest[:\s]+[#!]?(\d+)|MR[:\s]+[#!]?(\d+)|!(\d+)"
        mr_matches = re.findall(mr_pattern, output)
        mrs = [m for match in mr_matches for m in match if m]
        if mrs:
            work_log["outcome"]["merge_requests"].extend(mrs)
            self._log_action(issue_key, "mr_created", f"Created/referenced MR(s)", {"merge_requests": mrs})

        # Extract file paths that were modified
        file_pattern = r"(?:modified|created|edited|changed):\s*([^\s\n]+\.[a-zA-Z]+)"
        files = re.findall(file_pattern, output, re.IGNORECASE)
        if files:
            work_log["outcome"]["files_changed"].extend(list(set(files)))
            work_log["cursor_context"]["files_to_review"] = list(set(files))[:10]  # Top 10 files

        # Extract branch names
        branch_pattern = r"(?:branch|checkout -b|created branch)[\s:]+([a-zA-Z0-9_/-]+)"
        branches = re.findall(branch_pattern, output, re.IGNORECASE)
        if branches:
            work_log["outcome"]["branches_created"].extend(list(set(branches)))

    def _generate_continuation_prompt(self, issue_key: str, work_log: dict) -> str:
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

    async def _is_cursor_available(self) -> bool:
        """Check if Cursor/VS Code is available via D-Bus."""
        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            introspection = await bus.introspect("com.aiworkflow.Chat", "/com/aiworkflow/Chat")

            proxy = bus.get_proxy_object("com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection)

            chat_interface = proxy.get_interface("com.aiworkflow.Chat")
            result = await chat_interface.call_ping()
            bus.disconnect()

            return result and "pong" in result

        except Exception:
            return False

    # ==================== Main Loop ====================

    async def _wait_with_shutdown(self, seconds: float) -> bool:
        """Wait for specified seconds, but return early if shutdown requested.

        Returns True if shutdown was requested, False if wait completed normally.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=seconds)
            return True  # Shutdown requested
        except asyncio.TimeoutError:
            return False  # Normal timeout

    async def run(self):
        """Main daemon loop."""
        logger.info("Sprint bot daemon starting...")
        self.is_running = True
        self.start_time = time_module.time()

        # Start sleep/wake monitor
        await self.start_sleep_monitor()

        # Initial Jira refresh
        await self._refresh_from_jira()

        # Save initial state for UI
        state = self._load_state()
        self._save_state(state)
        logger.info(f"Initial state saved: {len(state.get('issues', []))} issues")

        while not self._shutdown_event.is_set():
            try:
                state = self._load_state()

                # Check if bot should run:
                # - manuallyStarted: run immediately (ignores schedule)
                # - automaticMode + within working hours: run on schedule
                manually_started = state.get("manuallyStarted", False)
                automatic_mode = state.get("automaticMode", False)
                within_hours = self._is_within_working_hours()

                should_run = manually_started or (automatic_mode and within_hours)

                if not should_run:
                    if automatic_mode and not within_hours:
                        logger.debug("Automatic mode enabled but outside working hours, waiting...")
                    elif not automatic_mode and not manually_started:
                        logger.debug("Bot not active (automatic mode off, not manually started), waiting...")
                    if await self._wait_with_shutdown(60):
                        break
                    continue

                # Refresh from Jira periodically
                refresh_interval = self._config["jira_refresh_interval_seconds"]
                if (datetime.now() - self._last_jira_refresh).total_seconds() > refresh_interval:
                    await self._refresh_from_jira()

                # Check issues in Review for merge readiness (3x daily = every 8 hours)
                review_check_interval = 8 * 60 * 60  # 8 hours
                if (datetime.now() - self._last_review_check).total_seconds() > review_check_interval:
                    await self._check_review_issues()

                # Check if we should process next issue
                # Only process if no issue is currently in progress
                if not state.get("processingIssue"):
                    # Check for approved AND actionable issues
                    approved_actionable = [
                        i
                        for i in state.get("issues", [])
                        if i.get("approvalStatus") == "approved" and self._is_actionable(i)
                    ]
                    if approved_actionable:
                        logger.info(f"Found {len(approved_actionable)} approved actionable issues")
                        await self._process_next_issue()
                    else:
                        # Log status periodically
                        issues = state.get("issues", [])
                        actionable = [i for i in issues if self._is_actionable(i)]
                        logger.debug(
                            f"Issues: {len(issues)} total, {len(actionable)} actionable, 0 approved+actionable"
                        )

                # Save state periodically (for UI to read)
                self._save_state(state)

                # Wait before next check (with shutdown awareness)
                check_interval = self._config["check_interval_seconds"]
                if await self._wait_with_shutdown(check_interval):
                    break

            except asyncio.CancelledError:
                logger.info("Main loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
                if await self._wait_with_shutdown(60):
                    break

        # Cleanup
        await self.stop_sleep_monitor()
        self.is_running = False
        logger.info("Sprint bot daemon stopped")

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down sprint bot daemon...")
        self._shutdown_event.set()
        # Give the main loop a moment to exit cleanly
        await asyncio.sleep(0.5)


async def main_async(args):
    """Async main entry point."""
    instance = SingleInstance()

    # Handle --status
    if args.status:
        pid = instance.get_running_pid()
        if pid:
            print(f"Sprint bot daemon is running (PID: {pid})")
            return 0
        else:
            print("Sprint bot daemon is not running")
            return 1

    # Handle --stop
    if args.stop:
        pid = instance.get_running_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to sprint bot daemon (PID: {pid})")
                return 0
            except OSError as e:
                print(f"Failed to stop daemon: {e}")
                return 1
        else:
            print("Sprint bot daemon is not running")
            return 1

    # Handle --list
    if args.list:
        try:
            client = get_client("com.aiworkflow.BotSprint", "/com/aiworkflow/BotSprint", "com.aiworkflow.BotSprint")
            result = client.call_method("list_issues", {})
            issues = json.loads(result).get("issues", [])

            if not issues:
                print("No sprint issues found")
                return 0

            print(f"\n{'Key':<12} {'Status':<12} {'Priority':<10} {'Summary'}")
            print("-" * 80)
            for issue in issues:
                print(
                    f"{issue.get('key', ''):<12} {issue.get('approvalStatus', ''):<12} "
                    f"{issue.get('priority', ''):<10} {issue.get('summary', '')[:40]}"
                )
            return 0
        except Exception as e:
            print(f"Failed to list issues: {e}")
            print("Is the sprint bot daemon running?")
            return 1

    # Try to acquire lock
    if not instance.acquire():
        pid = instance.get_running_pid()
        print(f"Sprint bot daemon is already running (PID: {pid})")
        return 1

    daemon = SprintDaemon(verbose=args.verbose, enable_dbus=args.dbus)

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler():
        asyncio.create_task(daemon.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # Start D-Bus if enabled
        if args.dbus:
            await daemon.start_dbus()

        # Run main loop
        await daemon.run()

    finally:
        if args.dbus:
            await daemon.stop_dbus()
        instance.release()

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sprint Bot Daemon")
    parser.add_argument("--status", action="store_true", help="Check if daemon is running")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--list", action="store_true", help="List sprint issues")
    parser.add_argument("--dbus", action="store_true", help="Enable D-Bus IPC")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    try:
        exit_code = asyncio.run(main_async(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
