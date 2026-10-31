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
import logging
from datetime import datetime

# Sprint daemon owns its own state file - no shared file with other services
from server.utils import load_config
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon
from services.sprint.bot.workflow_config import (
    WorkflowConfig,
)
from services.sprint.daemon_common import RECOVERABLE_ERRORS, _add_timeline_event
from services.sprint.daemon_handlers import SprintDBusHandlersMixin

__all__ = ["SprintDaemon", "_add_timeline_event"]

logger = logging.getLogger(__name__)


# pylint: disable-next=too-many-instance-attributes
class SprintDaemon(SprintDBusHandlersMixin, SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main Sprint Bot daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "sprint"
    description = "Sprint Bot Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSprint"
    object_path = "/com/aiworkflow/BotSprint"
    interface_name = "com.aiworkflow.BotSprint"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        self._workflow_config: WorkflowConfig | None = None
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._issues_processed = 0
        self._issues_completed = 0
        self._last_jira_refresh: datetime | None = None
        self._last_review_check: datetime | None = None

        # Configuration - read from config.json sprint section
        full_config = load_config()
        sprint_config = full_config.get("sprint", {})
        scheduling = sprint_config.get("scheduling", {})

        self._config = {
            "jira_project": sprint_config.get("jira", {}).get("project", "AAP"),
            "jira_component": sprint_config.get("jira", {}).get("component"),
            "working_hours": sprint_config.get("working_hours", {}),
            "check_interval_seconds": scheduling.get("issue_processing", {}).get("interval_seconds", 300),
            "jira_refresh_interval_seconds": scheduling.get("jira_refresh", {}).get("interval_seconds", 1800),
            "review_check_interval_seconds": scheduling.get("review_check", {}).get("interval_hours", 8) * 3600,
            "skip_blocked_after_minutes": sprint_config.get("skip_blocked_after_minutes", 30),
            "claude_cli_timeout_seconds": sprint_config.get("claude_cli_timeout_seconds", 1800),
        }

        # Register custom D-Bus method handlers
        self.register_handler("list_issues", self._handle_list_issues)
        self.register_handler("approve_issue", self._handle_approve_issue)
        self.register_handler("reject_issue", self._handle_reject_issue)  # Unapprove
        self.register_handler("abort_issue", self._handle_abort_issue)  # Abort in-progress
        self.register_handler("skip_issue", self._handle_skip_issue)
        self.register_handler("refresh", self._handle_refresh)
        self.register_handler("enable", self._handle_enable)  # Enable automatic mode
        self.register_handler("disable", self._handle_disable)  # Disable automatic mode
        self.register_handler("start", self._handle_start)  # Manual start (ignores schedule)
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
        self.register_handler("list_traces", self._handle_list_traces)  # List all traces

    # ==================== Abstract Method Implementations ====================

    async def on_system_wake(self):
        """Called when system wakes from sleep - refresh Jira data."""
        logger.info("System wake detected, refreshing sprint data...")
        await self._refresh_from_jira()

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        state = self._load_state()
        automatic_mode, manually_started, within_hours, is_active = self._runtime_flags(state)

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
        status_counts: dict[str, int] = {}
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
        logger.info("Sprint daemon ready: %s issues", len(state.get("issues", [])))

    # pylint: disable-next=too-many-branches
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
                        logger.debug("Automatic mode enabled but outside working hours, waiting...")
                    elif not automatic_mode and not manually_started:
                        logger.debug("Bot not active (automatic mode off, not manually started), waiting...")
                    if await self._wait_with_shutdown(60):
                        break
                    continue

                # Refresh from Jira periodically
                refresh_interval = self._config["jira_refresh_interval_seconds"]
                if self._elapsed_seconds(self._last_jira_refresh) > refresh_interval:
                    await self._refresh_from_jira()

                # Check issues in Review for merge readiness (interval from config)
                review_check_interval = self._config["review_check_interval_seconds"]
                if self._elapsed_seconds(self._last_review_check) > review_check_interval:
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
                        logger.info("Found %s approved actionable issues", len(approved_actionable))
                        await self._process_next_issue()
                    else:
                        # Log status periodically
                        issues = state.get("issues", [])
                        actionable = [i for i in issues if self._is_actionable(i)]
                        logger.debug(
                            "Issues: %s total, %s actionable, 0 approved+actionable", len(issues), len(actionable)
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
            except RECOVERABLE_ERRORS:
                logger.exception("Error in main loop")
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
