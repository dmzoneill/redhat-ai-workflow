#!/usr/bin/env python3
"""
Sprint Bot Daemon

A standalone service that automates sprint work by orchestrating Cursor chats.
Designed to run as a systemd user service.

Features:
- Working hours enforcement (Mon-Fri, 9am-5pm configurable)
- Jira sprint issue fetching and prioritization
- Cursor chat launching via D-Bus to VS Code extension
- Sequential issue processing with skip-on-block
- Real-time UI updates via workspace state file
- D-Bus IPC for external control
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.sprint                # Run daemon
    python -m services.sprint --status       # Check if running
    python -m services.sprint --stop         # Stop running daemon
    python -m services.sprint --list         # List sprint issues
    python -m services.sprint --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-sprint
    systemctl --user status bot-sprint
    systemctl --user stop bot-sprint

D-Bus:
    Service: com.aiworkflow.BotSprint
    Path: /com/aiworkflow/BotSprint
"""

import asyncio
import json
import logging
import os
from datetime import datetime, time
from pathlib import Path

import yaml

# Sprint daemon owns its own state file - no shared file with other services
from server.paths import SPRINT_STATE_FILE_V2
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon
from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.bot.workflow_config import WorkflowConfig, get_workflow_config
from services.sprint.sprint_cursor import SprintCursorMixin
from services.sprint.sprint_jira import SprintJiraMixin
from services.sprint.sprint_worklog import SprintWorkLogMixin
from services.sprint.timeline import _add_timeline_event

PROJECT_ROOT = Path(__file__).parent.parent.parent
SPRINT_STATE_FILE = SPRINT_STATE_FILE_V2

# Directory for background work logs
SPRINT_WORK_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_work"

logger = logging.getLogger(__name__)


class SprintDaemon(
    SprintJiraMixin,
    SprintCursorMixin,
    SprintWorkLogMixin,
    SleepWakeAwareDaemon,
    DaemonDBusBase,
    BaseDaemon,
):
    """Main Sprint Bot daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "sprint"
    description = "Sprint Bot Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSprint"
    object_path = "/com/aiworkflow/BotSprint"
    interface_name = "com.aiworkflow.BotSprint"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._issues_processed = 0
        self._issues_completed = 0
        self._last_jira_refresh = datetime.min
        self._last_review_check = datetime.min

        # Configuration - read from config.json sprint section
        from server.utils import load_config

        full_config = load_config()
        sprint_config = full_config.get("sprint", {})
        scheduling = sprint_config.get("scheduling", {})

        self._config = {
            "jira_project": sprint_config.get("jira", {}).get("project", "AAP"),
            "jira_component": sprint_config.get("jira", {}).get("component"),
            "working_hours": sprint_config.get("working_hours", {}),
            "check_interval_seconds": scheduling.get("issue_processing", {}).get(
                "interval_seconds", 300
            ),
            "jira_refresh_interval_seconds": scheduling.get("jira_refresh", {}).get(
                "interval_seconds", 1800
            ),
            "review_check_interval_seconds": scheduling.get("review_check", {}).get(
                "interval_hours", 8
            )
            * 3600,
            "skip_blocked_after_minutes": sprint_config.get(
                "skip_blocked_after_minutes", 30
            ),
            "claude_cli_timeout_seconds": sprint_config.get(
                "claude_cli_timeout_seconds", 1800
            ),
        }

        # Register custom D-Bus method handlers
        self.register_handler("list_issues", self._handle_list_issues)
        self.register_handler("approve_issue", self._handle_approve_issue)
        self.register_handler("reject_issue", self._handle_reject_issue)  # Unapprove
        self.register_handler(
            "abort_issue", self._handle_abort_issue
        )  # Abort in-progress
        self.register_handler("skip_issue", self._handle_skip_issue)
        self.register_handler("refresh", self._handle_refresh)
        self.register_handler("enable", self._handle_enable)  # Enable automatic mode
        self.register_handler("disable", self._handle_disable)  # Disable automatic mode
        self.register_handler(
            "start", self._handle_start
        )  # Manual start (ignores schedule)
        self.register_handler("stop", self._handle_stop)  # Manual stop
        self.register_handler("get_config", self._handle_get_config)
        self.register_handler("set_config", self._handle_set_config)
        self.register_handler("approve_all", self._handle_approve_all)
        self.register_handler("reject_all", self._handle_reject_all)  # Unapprove all
        self.register_handler("process_next", self._handle_process_next)
        self.register_handler("open_in_cursor", self._handle_open_in_cursor)
        self.register_handler("get_work_log", self._handle_get_work_log)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("start_issue", self._handle_start_issue)
        self.register_handler("toggle_background", self._handle_toggle_background)
        self.register_handler("get_state", self._handle_get_state)  # Full state for UI
        self.register_handler("get_history", self._handle_get_history)  # Sprint history
        self.register_handler("get_trace", self._handle_get_trace)  # Execution trace
        self.register_handler(
            "list_traces", self._handle_list_traces
        )  # List all traces

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

    async def _handle_list_issues(
        self, status: str = None, actionable: bool = None, **kwargs
    ) -> dict:
        """List all sprint issues."""
        state = self._load_state()
        issues = state.get("issues", [])

        # Add actionable flag to each issue
        for issue in issues:
            issue["isActionable"] = self._is_actionable(issue)

        # Filter by status if requested
        if status:
            issues = [i for i in issues if i.get("approvalStatus") == status]

        # Filter by actionable if requested
        if actionable is not None:
            issues = [i for i in issues if i.get("isActionable") == actionable]

        actionable_count = sum(1 for i in issues if i.get("isActionable"))

        return {
            "success": True,
            "issues": issues,
            "total": len(issues),
            "actionable_count": actionable_count,
            "not_actionable_count": len(issues) - actionable_count,
        }

    async def _handle_approve_issue(self, issue_key: str = None, **kwargs) -> dict:
        """Approve an issue for processing.

        Only allows approval of actionable issues (New/Refinement/Backlog).
        Issues in Review/Done cannot be approved.
        """
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
                        "Bot only works on issues in New/Refinement/Backlog.",
                    }

                issue["approvalStatus"] = "approved"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "approved",
                        "description": "Issue approved for sprint bot",
                    },
                )
                self._save_state(state)
                logger.info(f"Approved issue: {issue_key}")
                return {"success": True, "message": f"Issue {issue_key} approved"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_reject_issue(self, issue_key: str = None, **kwargs) -> dict:
        """Reject/unapprove an issue - set back to pending.

        This is the opposite of approve - removes the issue from the bot queue.
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "pending"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "unapproved",
                        "description": "Issue unapproved - removed from bot queue",
                    },
                )
                self._save_state(state)
                logger.info(f"Rejected/unapproved issue: {issue_key}")
                return {"success": True, "message": f"Issue {issue_key} unapproved"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_abort_issue(self, issue_key: str = None, **kwargs) -> dict:
        """Abort an in-progress issue - user takes control.

        Sets the issue to blocked and clears processingIssue if it matches.
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "blocked"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "aborted",
                        "description": "User took control - automated work stopped",
                    },
                )
                # Clear processingIssue if this was the active one
                if state.get("processingIssue") == issue_key:
                    state["processingIssue"] = None
                self._save_state(state)
                logger.info(f"Aborted issue: {issue_key}")
                return {
                    "success": True,
                    "message": f"Issue {issue_key} aborted - you can now work on it manually",
                }

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_skip_issue(
        self, issue_key: str = None, reason: str = "Manually skipped", **kwargs
    ) -> dict:
        """Skip/block an issue."""
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "blocked"
                issue["waitingReason"] = reason
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "skipped",
                        "description": f"Issue skipped: {reason}",
                    },
                )
                self._save_state(state)
                logger.info(f"Skipped issue: {issue_key} - {reason}")
                return {"success": True, "message": f"Issue {issue_key} skipped"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_refresh(self, **kwargs) -> dict:
        """Force refresh from Jira."""
        try:
            await self._refresh_from_jira()
            return {"success": True, "message": "Refreshed from Jira"}
        except (
            OSError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as e:
            return {"success": False, "error": str(e)}

    async def _handle_enable(self, **kwargs) -> dict:
        """Enable automatic mode (scheduled Mon-Fri 9-5)."""
        state = self._load_state()
        state["automaticMode"] = True
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode enabled")
        return {"success": True, "message": "Sprint bot automatic mode enabled"}

    async def _handle_disable(self, **kwargs) -> dict:
        """Disable automatic mode."""
        state = self._load_state()
        state["automaticMode"] = False
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode disabled")
        return {"success": True, "message": "Sprint bot automatic mode disabled"}

    async def _handle_start(self, **kwargs) -> dict:
        """Manually start the bot (ignores schedule)."""
        state = self._load_state()
        state["manuallyStarted"] = True
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot manually started")
        return {"success": True, "message": "Sprint bot started manually"}

    async def _handle_stop(self, **kwargs) -> dict:
        """Stop the bot (if manually started)."""
        state = self._load_state()
        state["manuallyStarted"] = False
        state["processingIssue"] = None
        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot stopped")
        return {"success": True, "message": "Sprint bot stopped"}

    async def _handle_get_config(self, **kwargs) -> dict:
        """Get current configuration."""
        return {"success": True, "config": self._config}

    async def _handle_set_config(self, **kwargs) -> dict:
        """Update configuration."""
        for key, value in kwargs.items():
            if key in self._config:
                self._config[key] = value
        return {"success": True, "config": self._config}

    async def _handle_approve_all(self, **kwargs) -> dict:
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
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "approved",
                            "description": "Bulk approved by sprint bot",
                        },
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
        logger.info(
            f"Approved {approved_count} actionable issues, skipped {skipped_count} non-actionable"
        )
        return {
            "success": True,
            "approved_count": approved_count,
            "skipped_count": skipped_count,
        }

    async def _handle_reject_all(self, **kwargs) -> dict:
        """Reject/unapprove all approved issues - set back to pending.

        This is the opposite of approve_all.
        """
        state = self._load_state()
        rejected_count = 0

        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "approved":
                issue["approvalStatus"] = "pending"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "unapproved",
                        "description": "Bulk unapproved",
                    },
                )
                rejected_count += 1

        self._save_state(state)
        logger.info(f"Unapproved {rejected_count} issues")
        return {"success": True, "rejected_count": rejected_count}

    async def _handle_toggle_background(self, enabled: bool = None, **kwargs) -> dict:
        """Toggle background tasks mode.

        When enabled, the bot processes issues in background without opening
        Cursor windows in the foreground.
        """
        state = self._load_state()

        if enabled is not None:
            state["backgroundTasks"] = enabled
        else:
            state["backgroundTasks"] = not state.get("backgroundTasks", False)

        state["lastUpdated"] = datetime.now().isoformat()
        self._save_state(state)

        mode = "enabled" if state["backgroundTasks"] else "disabled"
        logger.info(f"Background tasks {mode}")
        return {
            "success": True,
            "backgroundTasks": state["backgroundTasks"],
            "message": f"Background tasks {mode}",
        }

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full sprint state for UI.

        Returns the complete sprint state including issues, config, and status.
        This is the primary method for UI to read sprint state via D-Bus.
        """
        state = self._load_state()

        # Add runtime status info
        automatic_mode = state.get("automaticMode", False)
        manually_started = state.get("manuallyStarted", False)
        within_hours = self._is_within_working_hours()
        is_active = manually_started or (automatic_mode and within_hours)

        state["runtime"] = {
            "is_active": is_active,
            "within_working_hours": within_hours,
            "issues_processed": self._issues_processed,
            "issues_completed": self._issues_completed,
            "last_jira_refresh": (
                self._last_jira_refresh.isoformat()
                if self._last_jira_refresh != datetime.min
                else None
            ),
        }

        return {"success": True, "state": state}

    async def _handle_get_history(self, **kwargs) -> dict:
        """Get sprint history (completed sprints).

        Returns a list of completed sprints with their issues and stats.
        """
        try:
            state = self._load_state()
            history = state.get("sprint_history", [])
            return {"success": True, "history": history}
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            logger.error(f"Failed to get sprint history: {e}")
            return {"success": False, "error": str(e), "history": []}

    async def _handle_get_trace(self, issue_key: str = None, **kwargs) -> dict:
        """Get execution trace for an issue.

        Parameters:
            issue_key: The Jira issue key to get trace for
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        try:
            traces_dir = PROJECT_ROOT / "memory" / "state" / "sprint_traces"
            trace_file = traces_dir / f"{issue_key}.yaml"

            if not trace_file.exists():
                return {"success": False, "error": f"No trace found for {issue_key}"}

            import yaml

            with open(trace_file, encoding="utf-8") as f:
                trace = yaml.safe_load(f)

            return {"success": True, "trace": trace}
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Failed to get trace for {issue_key}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_list_traces(self, **kwargs) -> dict:
        """List all available execution traces.

        Returns a list of trace summaries (issue key, state, started_at).
        """
        try:
            traces_dir = PROJECT_ROOT / "memory" / "state" / "sprint_traces"
            traces = []

            if traces_dir.exists():
                import yaml

                for trace_file in traces_dir.glob("*.yaml"):
                    try:
                        with open(trace_file, encoding="utf-8") as f:
                            trace = yaml.safe_load(f)
                        if trace:
                            traces.append(
                                {
                                    "issue_key": trace.get(
                                        "issue_key", trace_file.stem
                                    ),
                                    "state": trace.get("current_state", "unknown"),
                                    "started_at": trace.get("started_at", ""),
                                }
                            )
                    except (OSError, yaml.YAMLError) as e:
                        logger.warning(f"Failed to parse trace {trace_file}: {e}")

            # Sort by started_at descending
            traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)
            return {"success": True, "traces": traces}
        except OSError as e:
            logger.error(f"Failed to list traces: {e}")
            return {"success": False, "error": str(e), "traces": []}

    async def _handle_process_next(self, **kwargs) -> dict:
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
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
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

        logger.info(
            f"Starting issue immediately: {issue_key} (background={background_mode})"
        )

        # Mark as in_progress and set as processing
        target_issue["approvalStatus"] = "in_progress"
        state["processingIssue"] = issue_key
        _add_timeline_event(
            target_issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "force_started",
                "description": "Issue started immediately via UI (bypassing checks)",
            },
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
                target_issue["waitingReason"] = (
                    "Cursor not available for foreground mode"
                )
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
        self._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="force_start_background"
        )
        jira_success = await self._transition_jira_issue(
            issue_key, self.JIRA_STATUS_IN_PROGRESS
        )
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.JIRA_STATUS_IN_PROGRESS,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
        )

        target_issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        _add_timeline_event(
            target_issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            },
        )
        target_issue["hasTrace"] = True
        target_issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt and run
        self._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="jira_transitioned"
        )
        self._trace_transition(
            tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background"
        )

        result = await self._run_issue_in_background_traced(target_issue, tracer)

        # Reload state and update
        state = self._load_state()
        target_issue = next(
            (i for i in state.get("issues", []) if i["key"] == issue_key), target_issue
        )

        if result.get("success"):
            self._trace_transition(
                tracer, WorkflowState.CREATING_MR, trigger="implementation_complete"
            )
            await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_REVIEW)
            self._trace_transition(
                tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created"
            )
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            _add_timeline_event(
                target_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self._get_work_log_path(issue_key)),
                    "jiraTransition": self.JIRA_STATUS_IN_REVIEW,
                },
            )
            target_issue["approvalStatus"] = "completed"
            target_issue["jiraStatus"] = self.JIRA_STATUS_IN_REVIEW
            target_issue["hasWorkLog"] = True
            target_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            state["processingIssue"] = None
            self._save_state(state)
            self._issues_processed += 1

            return {
                "success": True,
                "message": f"Completed {issue_key}",
                "mode": "background",
            }
        else:
            error_reason = result.get("error", "Background processing failed")
            tracer.mark_blocked(error_reason)

            _add_timeline_event(
                target_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                },
            )
            target_issue["approvalStatus"] = "blocked"
            target_issue["waitingReason"] = error_reason
            target_issue["hasWorkLog"] = True
            target_issue["workLogPath"] = str(self._get_work_log_path(issue_key))
            state["processingIssue"] = None
            self._save_state(state)

            return {"success": False, "error": error_reason, "mode": "background"}

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
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
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
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="sprint_state_", dir=SPRINT_STATE_FILE.parent
            )
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(sprint_state, f, indent=2, default=str)
                Path(temp_path).replace(SPRINT_STATE_FILE)
            except (OSError, TypeError):
                try:
                    Path(temp_path).unlink()
                except OSError as exc:
                    logger.debug("OS operation failed: %s", exc)
                raise

        except (OSError, TypeError) as e:
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
                execution_mode = (
                    "background" if state.get("backgroundTasks", True) else "foreground"
                )

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
            return {
                "success": True,
                "message": "No approved actionable issues to process",
            }

        issue_key = next_issue["key"]
        background_mode = state.get("backgroundTasks", True)

        logger.info(f"Processing issue: {issue_key} (background={background_mode})")

        # Initialize execution tracer
        tracer = self._get_tracer(issue_key, next_issue)
        self._trace_transition(
            tracer, WorkflowState.LOADING, trigger="start_processing"
        )

        # Log issue loading step
        self._trace_step(
            tracer,
            "load_issue",
            inputs={
                "issue_key": issue_key,
                "approval_status": next_issue.get("approvalStatus"),
            },
            outputs={
                "summary": next_issue.get("summary", "")[:100],
                "jira_status": next_issue.get("jiraStatus"),
            },
        )
        self._trace_transition(tracer, WorkflowState.ANALYZING, trigger="issue_loaded")

        # Classify the issue
        workflow_type = self.workflow_config.classify_issue(next_issue)
        tracer.set_workflow_type(
            workflow_type,
            reason=f"Issue type: {next_issue.get('issueType', 'Story')}, keywords matched: {workflow_type}",
        )
        self._trace_transition(
            tracer, WorkflowState.CLASSIFYING, trigger="analysis_complete"
        )

        # Check actionability
        is_actionable = self._is_actionable(next_issue)
        self._trace_step(
            tracer,
            "check_actionable",
            inputs={"jira_status": next_issue.get("jiraStatus")},
            outputs={"is_actionable": is_actionable},
            decision="actionable" if is_actionable else "not_actionable",
            reason=(
                f"Status '{next_issue.get('jiraStatus')}' is "
                f"{'actionable' if is_actionable else 'not actionable'} per workflow config"
            ),
        )
        self._trace_transition(
            tracer, WorkflowState.CHECKING_ACTIONABLE, trigger="classified"
        )

        # Check Cursor availability
        cursor_available = await self._is_cursor_available()

        # FOREGROUND MODE: Requires Cursor - wait if not available
        if not background_mode:
            if not cursor_available:
                logger.info("Foreground mode: Cursor not available, waiting...")
                self._trace_step(
                    tracer,
                    "check_cursor",
                    inputs={"mode": "foreground"},
                    outputs={"cursor_available": False},
                    status=StepStatus.SKIPPED,
                    reason="Cursor not available, waiting...",
                )
                return {
                    "success": False,
                    "waiting": True,
                    "message": "Waiting for Cursor to be available",
                }

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
        self._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable"
        )

        # Transition Jira issue to "In Progress"
        jira_success = await self._transition_jira_issue(
            issue_key, self.JIRA_STATUS_IN_PROGRESS
        )
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.JIRA_STATUS_IN_PROGRESS,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )

        if workflow_type == "spike":
            self._trace_transition(
                tracer, WorkflowState.RESEARCHING, trigger="transitioned_spike"
            )
        else:
            self._trace_transition(
                tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change"
            )

        # Update local status
        next_issue["approvalStatus"] = "in_progress"
        next_issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        _add_timeline_event(
            next_issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            },
        )
        # Add trace reference to issue
        next_issue["hasTrace"] = True
        next_issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt
        self._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created"
        )
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": workflow_type},
            outputs={"prompt_length": len(self._build_work_prompt(next_issue))},
        )

        # Run in background
        self._trace_transition(
            tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background"
        )
        result = await self._run_issue_in_background_traced(next_issue, tracer)

        # Reload state in case it changed
        state = self._load_state()
        next_issue = next(
            (i for i in state.get("issues", []) if i["key"] == issue_key), next_issue
        )

        if result.get("success"):
            # Transition Jira issue to "In Review" (work completed, MR created)
            self._trace_transition(
                tracer, WorkflowState.CREATING_MR, trigger="implementation_complete"
            )

            await self._transition_jira_issue(issue_key, self.JIRA_STATUS_IN_REVIEW)
            self._trace_step(
                tracer,
                "transition_jira_review",
                inputs={
                    "issue_key": issue_key,
                    "target_status": self.JIRA_STATUS_IN_REVIEW,
                },
                outputs={"success": True},
                tool_name="jira_transition",
            )

            self._trace_transition(
                tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created"
            )
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            _add_timeline_event(
                next_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self._get_work_log_path(issue_key)),
                    "jiraTransition": self.JIRA_STATUS_IN_REVIEW,
                },
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

            _add_timeline_event(
                next_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                },
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

    async def _is_cursor_available(self) -> bool:
        """Check if Cursor/VS Code is available via D-Bus."""
        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            introspection = await bus.introspect(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat"
            )

            proxy = bus.get_proxy_object(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection
            )

            chat_interface = proxy.get_interface("com.aiworkflow.Chat")
            result = await chat_interface.call_ping()
            bus.disconnect()

            return result and "pong" in result

        except OSError:
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

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Sprint bot daemon starting...")

        # Start sleep/wake monitor
        await self.start_sleep_monitor()

        # Start D-Bus if enabled
        if self.enable_dbus:
            await self.start_dbus()

        # Initial Jira refresh
        await self._refresh_from_jira()

        # Save initial state for UI
        state = self._load_state()
        self._save_state(state)
        self.is_running = True
        logger.info(f"Sprint daemon ready: {len(state.get('issues', []))} issues")

    async def run_daemon(self):
        """Main daemon loop."""
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
                        logger.debug(
                            "Automatic mode enabled but outside working hours, waiting..."
                        )
                    elif not automatic_mode and not manually_started:
                        logger.debug(
                            "Bot not active (automatic mode off, not manually started), waiting..."
                        )
                    if await self._wait_with_shutdown(60):
                        break
                    continue

                # Refresh from Jira periodically
                refresh_interval = self._config["jira_refresh_interval_seconds"]
                if (
                    datetime.now() - self._last_jira_refresh
                ).total_seconds() > refresh_interval:
                    await self._refresh_from_jira()

                # Check issues in Review for merge readiness (interval from config)
                review_check_interval = self._config["review_check_interval_seconds"]
                if (
                    datetime.now() - self._last_review_check
                ).total_seconds() > review_check_interval:
                    await self._check_review_issues()

                # Check if we should process next issue
                # Only process if no issue is currently in progress
                if not state.get("processingIssue"):
                    # Check for approved AND actionable issues
                    approved_actionable = [
                        i
                        for i in state.get("issues", [])
                        if i.get("approvalStatus") == "approved"
                        and self._is_actionable(i)
                    ]
                    if approved_actionable:
                        logger.info(
                            f"Found {len(approved_actionable)} approved actionable issues"
                        )
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
            except (
                OSError,
                json.JSONDecodeError,
                yaml.YAMLError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ) as e:
                logger.exception(f"Error in main loop: {e}")
                if await self._wait_with_shutdown(60):
                    break

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Sprint daemon shutting down...")

        # Stop sleep monitor
        await self.stop_sleep_monitor()

        # Stop D-Bus
        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Sprint bot daemon stopped")


if __name__ == "__main__":
    SprintDaemon.main()
