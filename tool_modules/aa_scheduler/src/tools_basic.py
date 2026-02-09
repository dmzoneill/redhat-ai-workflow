"""Scheduler MCP Tools - Tools for managing scheduled jobs.

This module delegates to the canonical implementations in
tool_modules.aa_workflow.src.scheduler_tools to avoid code duplication.

Provides:
- cron_list: List all scheduled jobs with next run time
- cron_add: Add a new scheduled job
- cron_remove: Remove a scheduled job
- cron_enable: Enable/disable a job
- cron_run_now: Manually trigger a scheduled job
- cron_status: Show scheduler status and recent executions
- cron_notifications: Show recent notifications from scheduled jobs
- cron_scheduler_toggle: Enable/disable the entire scheduler at runtime

Note: Job definitions (cron, skill, inputs) are in config.json.
      Job enabled state is in state.json (managed by StateManager).
"""

from typing import TYPE_CHECKING

# Import shared helpers from the canonical module for backwards compatibility.
from tool_modules.aa_workflow.src.scheduler_tools import (
    _get_schedules_config,
    _update_schedules_config,
    register_scheduler_tools,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Re-export for backwards compatibility
__all__ = [
    "_get_schedules_config",
    "_update_schedules_config",
    "register_tools",
]


def register_tools(server: "FastMCP") -> int:
    """Register scheduler management tools with the MCP server.

    Delegates to the canonical register_scheduler_tools() in
    tool_modules.aa_workflow.src.scheduler_tools.
    """
    return register_scheduler_tools(server)
