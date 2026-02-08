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

# Sprint daemon owns its own state file - no shared file with other services
from server.paths import SPRINT_STATE_FILE_V2
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon
from services.sprint.issue_executor import IssueExecutor
from services.sprint.sprint_history_tracker import SprintHistoryTracker
from services.sprint.sprint_planner import SprintPlanner

PROJECT_ROOT = Path(__file__).parent.parent.parent
SPRINT_STATE_FILE = SPRINT_STATE_FILE_V2

logger = logging.getLogger(__name__)


# Maximum timeline entries per issue to prevent unbounded memory growth
MAX_TIMELINE_ENTRIES = 50


def _add_timeline_event(issue: dict, event: dict) -> None:
    """Add a timeline event to an issue, trimming old entries if needed."""
    if "timeline" not in issue:
        issue["timeline"] = []
    issue["timeline"].append(event)
    if len(issue["timeline"]) > MAX_TIMELINE_ENTRIES:
        issue["timeline"] = issue["timeline"][-MAX_TIMELINE_ENTRIES:]


class SprintDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main Sprint Bot daemon with D-Bus support.

    Orchestrates sprint work using extracted components:
    - SprintPlanner: Jira refresh, issue prioritization, workflow config
    - IssueExecutor: Claude CLI invocation, Cursor chat, Jira transitions
    - SprintHistoryTracker: Work logs, context prompts, history recording
    """

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

        # Initialize extracted components
        self._planner = SprintPlanner()
        self._history = SprintHistoryTracker()
        self._executor = IssueExecutor(self._planner, self._history)

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

    # ==================== Delegated Properties ====================
    # These delegate to SprintPlanner for backward compatibility with any code
    # that accesses them on SprintDaemon.

    @property
    def workflow_config(self):
        return self._planner.workflow_config

    @property
    def ACTIONABLE_STATUSES(self):
        return self._planner.ACTIONABLE_STATUSES

    @property
    def JIRA_STATUS_IN_PROGRESS(self):
        return self._planner.JIRA_STATUS_IN_PROGRESS

    @property
    def JIRA_STATUS_IN_REVIEW(self):
        return self._planner.JIRA_STATUS_IN_REVIEW

    @property
    def JIRA_STATUS_DONE(self):
        return self._planner.JIRA_STATUS_DONE

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
            issue["isActionable"] = self._planner.is_actionable(issue)

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
                if not self._planner.is_actionable(issue):
                    jira_status = issue.get("jiraStatus", "unknown")
                    return {
                        "success": False,
                        "error": f"Issue {issue_key} is not actionable (status: {jira_status}). "
                        f"Bot only works on issues in New/Refinement/Backlog.",
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
        except Exception as e:
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
                if self._planner.is_actionable(issue):
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
        except Exception as e:
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
            traces_dir = (
                Path.home()
                / "src"
                / "redhat-ai-workflow"
                / "memory"
                / "state"
                / "sprint_traces"
            )
            trace_file = traces_dir / f"{issue_key}.yaml"

            if not trace_file.exists():
                return {"success": False, "error": f"No trace found for {issue_key}"}

            import yaml

            with open(trace_file) as f:
                trace = yaml.safe_load(f)

            return {"success": True, "trace": trace}
        except Exception as e:
            logger.error(f"Failed to get trace for {issue_key}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_list_traces(self, **kwargs) -> dict:
        """List all available execution traces.

        Returns a list of trace summaries (issue key, state, started_at).
        """
        try:
            traces_dir = (
                Path.home()
                / "src"
                / "redhat-ai-workflow"
                / "memory"
                / "state"
                / "sprint_traces"
            )
            traces = []

            if traces_dir.exists():
                import yaml

                for trace_file in traces_dir.glob("*.yaml"):
                    try:
                        with open(trace_file) as f:
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
                    except Exception as e:
                        logger.warning(f"Failed to parse trace {trace_file}: {e}")

            # Sort by started_at descending
            traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)
            return {"success": True, "traces": traces}
        except Exception as e:
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

        work_log = self._history.load_work_log(issue_key)
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
        from services.sprint.bot.execution_tracer import WorkflowState

        tracer = self._executor._get_tracer(issue_key, target_issue, self._load_state)
        self._executor._trace_transition(
            tracer, WorkflowState.LOADING, trigger="force_start"
        )
        self._executor._trace_step(
            tracer,
            "force_start_issue",
            inputs={"issue_key": issue_key, "background_mode": background_mode},
            decision="force_start",
            reason="User requested immediate start via UI, bypassing all checks",
        )

        # FOREGROUND MODE: Open Cursor chat
        if not background_mode:
            cursor_available = await self._executor.is_cursor_available()
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
            result = await self._executor._process_in_cursor_traced(
                target_issue,
                state,
                tracer,
                self._load_state,
                self._save_state,
                self._on_issue_processed,
            )
            return result

        # BACKGROUND MODE: Run via Claude CLI
        # Transition Jira to In Progress
        self._executor._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="force_start_background"
        )
        jira_success = await self._executor.transition_jira_issue(
            issue_key, self._planner.JIRA_STATUS_IN_PROGRESS
        )
        self._executor._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self._planner.JIRA_STATUS_IN_PROGRESS,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
        )

        target_issue["jiraStatus"] = self._planner.JIRA_STATUS_IN_PROGRESS
        _add_timeline_event(
            target_issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self._planner.JIRA_STATUS_IN_PROGRESS,
            },
        )
        target_issue["hasTrace"] = True
        target_issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt and run
        self._executor._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="jira_transitioned"
        )
        self._executor._trace_transition(
            tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background"
        )

        result = await self._executor._run_issue_in_background_traced(
            target_issue, tracer
        )

        # Reload state and update
        state = self._load_state()
        target_issue = next(
            (i for i in state.get("issues", []) if i["key"] == issue_key), target_issue
        )

        if result.get("success"):
            self._executor._trace_transition(
                tracer, WorkflowState.CREATING_MR, trigger="implementation_complete"
            )
            await self._executor.transition_jira_issue(
                issue_key, self._planner.JIRA_STATUS_IN_REVIEW
            )
            self._executor._trace_transition(
                tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created"
            )
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            _add_timeline_event(
                target_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self._history.get_work_log_path(issue_key)),
                    "jiraTransition": self._planner.JIRA_STATUS_IN_REVIEW,
                },
            )
            target_issue["approvalStatus"] = "completed"
            target_issue["jiraStatus"] = self._planner.JIRA_STATUS_IN_REVIEW
            target_issue["hasWorkLog"] = True
            target_issue["workLogPath"] = str(
                self._history.get_work_log_path(issue_key)
            )
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
            target_issue["workLogPath"] = str(
                self._history.get_work_log_path(issue_key)
            )
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
        work_log = self._history.load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        # Check if Cursor is available
        cursor_available = await self._executor.is_cursor_available()
        if not cursor_available:
            return {
                "success": False,
                "error": "Cursor is not available. Please open VS Code/Cursor first.",
            }

        # Build the context prompt from the work log
        prompt = self._history.build_cursor_context_prompt(issue_key, work_log)

        # Create a Cursor chat with this context
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
                            _add_timeline_event(
                                issue,
                                {
                                    "timestamp": datetime.now().isoformat(),
                                    "action": "opened_in_cursor",
                                    "description": "Opened background work in Cursor for interactive continuation",
                                    "chatLink": chat_id,
                                },
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
            sprint_state["workflowConfig"] = self._planner.export_workflow_config()

            # Write atomically (temp file + rename)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="sprint_state_", dir=SPRINT_STATE_FILE.parent
            )
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

    # ==================== Delegating Methods ====================

    async def _refresh_from_jira(self) -> None:
        """Refresh sprint issues from Jira. Delegates to SprintPlanner."""
        await self._planner.refresh_from_jira()
        self._last_jira_refresh = datetime.now()

    async def _check_review_issues(self) -> None:
        """Check issues in Review for merge readiness. Delegates to SprintPlanner."""
        self._last_review_check = datetime.now()
        await self._planner.check_review_issues(self._load_state, self._save_state)

    async def _process_next_issue(self) -> dict:
        """Process the next approved issue. Delegates to IssueExecutor."""
        return await self._executor.process_next_issue(
            self._load_state, self._save_state, self._on_issue_processed
        )

    def _on_issue_processed(self):
        """Callback to increment the processed issues counter."""
        self._issues_processed += 1

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

                # Check issues in Review for merge readiness (3x daily = every 8 hours)
                review_check_interval = 8 * 60 * 60  # 8 hours
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
                        and self._planner.is_actionable(i)
                    ]
                    if approved_actionable:
                        logger.info(
                            f"Found {len(approved_actionable)} approved actionable issues"
                        )
                        await self._process_next_issue()
                    else:
                        # Log status periodically
                        issues = state.get("issues", [])
                        actionable = [
                            i for i in issues if self._planner.is_actionable(i)
                        ]
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
