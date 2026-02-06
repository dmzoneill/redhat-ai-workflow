"""Scheduler MCP Tools - Tools for managing scheduled jobs.

NOTE: This module is largely duplicated by tool_modules/aa_scheduler/src/tools_basic.py.
Consider using aa_scheduler module instead for new code.

Provides:
- cron_list: List all scheduled jobs with next run time
- cron_add: Add a new scheduled job
- cron_remove: Remove a scheduled job
- cron_enable: Enable/disable a job
- cron_run_now: Manually trigger a scheduled job
- cron_status: Show scheduler status and recent executions
- cron_scheduler_toggle: Enable/disable the entire scheduler at runtime

Note: Job definitions (cron, skill, inputs) are in config.json.
      Job/service enabled state is in state.json (managed by StateManager).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from croniter import croniter
from mcp.types import TextContent

from server.config_manager import config as config_manager
from server.state_manager import state as state_manager
from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent


def _get_schedules_config() -> dict:
    """Get the schedules section from config (job definitions only)."""
    return config_manager.get("schedules", default={})


def _update_schedules_config(schedules: dict):
    """Update the schedules section in config (job definitions only)."""
    config_manager.update_section("schedules", schedules, merge=False, flush=True)


def register_scheduler_tools(server: "FastMCP") -> int:
    """Register scheduler management tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def cron_list() -> list[TextContent]:
        """
        List all scheduled jobs with their next run time.

        Shows both cron-based and poll-based scheduled jobs,
        including their status, schedule, and next execution time.

        Returns:
            List of scheduled jobs with details.
        """
        schedules = _get_schedules_config()

        if not state_manager.is_service_enabled("scheduler"):
            return [
                TextContent(
                    type="text",
                    text="⚠️ Scheduler is disabled.\n\nEnable it with `cron_scheduler_toggle(enabled=True)`",
                )
            ]

        jobs = schedules.get("jobs", [])
        if not jobs:
            return [
                TextContent(
                    type="text",
                    text="No scheduled jobs configured.\n\nUse `cron_add` to create a new scheduled job.",
                )
            ]

        lines = ["## 📅 Scheduled Jobs\n"]
        lines.append(f"**Timezone:** {schedules.get('timezone', 'UTC')}")

        # Show default retry config
        default_retry = schedules.get("default_retry", {})
        if default_retry:
            lines.append(
                f"**Default Retry:** {default_retry.get('max_attempts', 2)} attempts, {default_retry.get('backoff', 'exponential')} backoff"
            )
        lines.append("")

        now = datetime.now()

        for job in jobs:
            name = job.get("name", "unnamed")
            skill = job.get("skill", "")
            # Get enabled state from state.json
            enabled = state_manager.is_job_enabled(name)
            notify = job.get("notify", [])
            persona = job.get("persona", "")
            retry = job.get("retry")

            status_emoji = "✅" if enabled else "⏸️"
            lines.append(f"### {status_emoji} {name}")
            lines.append(f"**Skill:** `{skill}`")

            if persona:
                lines.append(f"**Persona:** `{persona}`")

            if job.get("cron"):
                cron_expr = job["cron"]
                lines.append(f"**Schedule:** `{cron_expr}` (cron)")

                # Calculate next run
                try:
                    cron = croniter(cron_expr, now)
                    next_run = cron.get_next(datetime)
                    lines.append(f"**Next run:** {next_run.strftime('%Y-%m-%d %H:%M')}")
                except Exception:
                    lines.append("**Next run:** (invalid cron expression)")

            elif job.get("trigger") == "poll":
                interval = job.get("poll_interval", "1h")
                condition = job.get("condition", "")
                lines.append(f"**Type:** Poll (every {interval})")
                lines.append(f"**Condition:** `{condition}`")

            if notify:
                lines.append(f"**Notify:** {', '.join(notify)}")

            # Show retry configuration
            if retry is False:
                lines.append("**Retry:** disabled")
            elif isinstance(retry, dict):
                retry_info = f"{retry.get('max_attempts', 2)} attempts"
                if retry.get("retry_on"):
                    retry_info += f" on {', '.join(retry['retry_on'])}"
                lines.append(f"**Retry:** {retry_info}")
            else:
                lines.append("**Retry:** default")

            if job.get("inputs"):
                lines.append(f"**Inputs:** `{json.dumps(job['inputs'])}`")

            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def cron_add(
        name: str,
        skill: str,
        cron: str = "",
        poll_interval: str = "",
        poll_condition: str = "",
        inputs: str = "{}",
        notify: str = "memory",
        enabled: bool = True,
        retry_max_attempts: int = -1,
        retry_on: str = "",
    ) -> list[TextContent]:
        """
        Add a new scheduled job with optional retry configuration.

        Creates either a cron-based job (runs at specific times) or a
        poll-based job (checks conditions periodically).

        Args:
            name: Unique name for the job
            skill: Name of the skill to run (e.g., "coffee", "beer")
            cron: Cron expression for time-based scheduling (e.g., "30 8 * * 1-5")
            poll_interval: Interval for poll-based jobs (e.g., "1h", "30m")
            poll_condition: Condition name for poll-based jobs
            inputs: JSON string of inputs to pass to the skill
            notify: Comma-separated notification channels (slack,desktop,memory)
            enabled: Whether the job is enabled
            retry_max_attempts: Max retry attempts (-1 for default, 0 to disable)
            retry_on: Comma-separated failure types to retry on (auth,network,timeout)

        Returns:
            Confirmation of job creation.

        Examples:
            # Morning coffee at 8:30 AM on weekdays
            cron_add("morning_coffee", "coffee", cron="30 8 * * 1-5", notify="slack,desktop")

            # Evening beer at 5:30 PM on weekdays
            cron_add("evening_beer", "beer", cron="30 17 * * 1-5", notify="slack")

            # Check for stale PRs every hour with custom retry
            cron_add("stale_prs", "pr_reminder", poll_interval="1h", poll_condition="gitlab_stale_prs", retry_max_attempts=3, retry_on="auth,network")
        """
        # Validate inputs
        if not name:
            return [TextContent(type="text", text="❌ Job name is required")]

        if not skill:
            return [TextContent(type="text", text="❌ Skill name is required")]

        if not cron and not poll_interval:
            return [
                TextContent(
                    type="text",
                    text="❌ Either `cron` or `poll_interval` is required",
                )
            ]

        # Validate cron expression
        if cron:
            try:
                croniter(cron)
            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Invalid cron expression: {e}\n\n"
                        "Format: `minute hour day month day_of_week`\n"
                        "Example: `30 8 * * 1-5` (8:30 AM on weekdays)",
                    )
                ]

        # Parse inputs JSON
        try:
            job_inputs = json.loads(inputs) if inputs else {}
        except json.JSONDecodeError as e:
            return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {e}")]

        # Parse notify channels
        notify_channels = [c.strip() for c in notify.split(",") if c.strip()]

        # Load current config
        schedules = _get_schedules_config()

        # Ensure schedules section exists
        if not schedules:
            schedules = {
                "timezone": "UTC",
                "jobs": [],
                "poll_sources": {},
            }

        # Check for duplicate name
        existing_names = {j.get("name") for j in schedules.get("jobs", [])}
        if name in existing_names:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Job with name `{name}` already exists.\n\n"
                    "Use `cron_remove` to delete it first, or choose a different name.",
                )
            ]

        # Build job config (no enabled flag - that goes in state.json)
        job: dict = {
            "name": name,
            "skill": skill,
            "notify": notify_channels,
        }

        # Set job enabled state in state.json
        state_manager.set_job_enabled(name, enabled)

        if job_inputs:
            job["inputs"] = job_inputs

        if cron:
            job["cron"] = cron
        else:
            job["trigger"] = "poll"
            job["poll_interval"] = poll_interval
            if poll_condition:
                job["condition"] = poll_condition

        # Add retry configuration if specified
        if retry_max_attempts == 0:
            # Explicitly disable retry
            job["retry"] = False
        elif retry_max_attempts > 0 or retry_on:
            # Custom retry config
            retry_config = {}
            if retry_max_attempts > 0:
                retry_config["max_attempts"] = retry_max_attempts
            if retry_on:
                retry_config["retry_on"] = [t.strip() for t in retry_on.split(",") if t.strip()]
            if retry_config:
                job["retry"] = retry_config

        # Add to jobs list
        if "jobs" not in schedules:
            schedules["jobs"] = []
        schedules["jobs"].append(job)

        # Save config
        _update_schedules_config(schedules)

        # Format response
        lines = [f"✅ Created scheduled job: **{name}**\n"]
        lines.append(f"**Skill:** `{skill}`")

        if cron:
            lines.append(f"**Schedule:** `{cron}`")
            try:
                cron_iter = croniter(cron, datetime.now())
                next_run = cron_iter.get_next(datetime)
                lines.append(f"**Next run:** {next_run.strftime('%Y-%m-%d %H:%M')}")
            except Exception:
                pass
        else:
            lines.append(f"**Poll interval:** {poll_interval}")
            if poll_condition:
                lines.append(f"**Condition:** `{poll_condition}`")

        lines.append(f"**Notify:** {', '.join(notify_channels)}")

        # Show retry configuration
        if job.get("retry") is False:
            lines.append("**Retry:** disabled")
        elif isinstance(job.get("retry"), dict):
            retry_info = job["retry"]
            lines.append(
                f"**Retry:** {retry_info.get('max_attempts', 'default')} attempts on {', '.join(retry_info.get('retry_on', ['default']))}"
            )
        else:
            lines.append("**Retry:** default (2 attempts on auth, network)")

        lines.append("\n💡 The scheduler will pick up this job on next restart.")
        lines.append("Use `cron_run_now` to test it immediately.")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def cron_remove(name: str) -> list[TextContent]:
        """
        Remove a scheduled job.

        Args:
            name: Name of the job to remove

        Returns:
            Confirmation of job removal.
        """
        schedules = _get_schedules_config()
        jobs = schedules.get("jobs", [])

        # Find and remove the job
        original_count = len(jobs)
        jobs = [j for j in jobs if j.get("name") != name]

        if len(jobs) == original_count:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Job not found: `{name}`\n\nUse `cron_list` to see available jobs.",
                )
            ]

        schedules["jobs"] = jobs
        _update_schedules_config(schedules)

        return [
            TextContent(
                type="text",
                text=f"✅ Removed scheduled job: **{name}**\n\n"
                "The scheduler will stop running this job on next restart.",
            )
        ]

    @registry.tool()
    async def cron_enable(name: str, enabled: bool = True) -> list[TextContent]:
        """
        Enable or disable a scheduled job.

        Args:
            name: Name of the job to enable/disable
            enabled: True to enable, False to disable

        Returns:
            Confirmation of status change.
        """
        schedules = _get_schedules_config()
        jobs = schedules.get("jobs", [])

        # Check if job exists in config
        job_names = {j.get("name") for j in jobs}
        if name not in job_names:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Job not found: `{name}`\n\nUse `cron_list` to see available jobs.",
                )
            ]

        # Update enabled state in state.json
        state_manager.set_job_enabled(name, enabled, flush=True)

        status = "enabled" if enabled else "disabled"
        emoji = "✅" if enabled else "⏸️"

        return [
            TextContent(
                type="text",
                text=f"{emoji} Job **{name}** is now **{status}**\n\n" "The change takes effect immediately.",
            )
        ]

    @registry.tool()
    async def cron_run_now(name: str) -> list[TextContent]:
        """
        Manually trigger a scheduled job to run immediately.

        This runs the job's skill with its configured inputs,
        regardless of the schedule.

        Args:
            name: Name of the job to run

        Returns:
            Job execution result.
        """
        try:
            from tool_modules.aa_workflow.src.scheduler import get_scheduler
        except ImportError:
            from .scheduler import get_scheduler

        scheduler = get_scheduler()

        if not scheduler:
            # Scheduler not running - execute directly
            schedules = _get_schedules_config()
            jobs = schedules.get("jobs", [])

            job_config = None
            for job in jobs:
                if job.get("name") == name:
                    job_config = job
                    break

            if not job_config:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Job not found: `{name}`\n\nUse `cron_list` to see available jobs.",
                    )
                ]

            # Execute the skill directly via the MCP server
            skill = job_config.get("skill", "")
            inputs = job_config.get("inputs", {})

            try:
                # Use the server's call_tool to invoke skill_run
                result = await server.call_tool(
                    "skill_run",
                    {
                        "skill_name": skill,
                        "inputs": json.dumps(inputs),
                        "execute": True,
                        "debug": False,
                    },
                )
                # Extract text from result
                if hasattr(result, "content") and result.content:
                    return result.content
                return [TextContent(type="text", text=f"✅ Job `{name}` executed")]
            except Exception as e:
                return [TextContent(type="text", text=f"❌ Failed to run job: {e}")]

        # Use scheduler's run_job_now
        result = await scheduler.run_job_now(name)

        if result.get("success"):
            return [
                TextContent(
                    type="text",
                    text=f"✅ Job **{name}** executed successfully.\n\n" "Check `cron_status` for execution details.",
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Job **{name}** failed: {result.get('error', 'Unknown error')}",
                )
            ]

    @registry.tool()
    async def cron_status() -> list[TextContent]:
        """
        Show scheduler status and recent job executions.

        Returns:
            Scheduler status including running state, job counts,
            and recent execution history.
        """
        try:
            from tool_modules.aa_workflow.src.scheduler import get_scheduler
        except ImportError:
            from .scheduler import get_scheduler

        scheduler = get_scheduler()
        schedules = _get_schedules_config()

        lines = ["## 🕐 Scheduler Status\n"]

        # Basic config status
        enabled = state_manager.is_service_enabled("scheduler")
        timezone = schedules.get("timezone", "UTC")
        total_jobs = len(schedules.get("jobs", []))

        lines.append(f"**Scheduler enabled:** {'✅ Yes' if enabled else '❌ No'}")
        lines.append(f"**Timezone:** {timezone}")
        lines.append(f"**Total jobs configured:** {total_jobs}")

        # Show default retry config
        default_retry = schedules.get("default_retry", {})
        if default_retry:
            lines.append(
                f"**Default Retry:** {default_retry.get('max_attempts', 2)} attempts, {default_retry.get('backoff', 'exponential')} backoff"
            )

        if scheduler:
            status = scheduler.get_status()
            lines.append(f"**Scheduler running:** {'✅ Yes' if status['running'] else '❌ No'}")
            lines.append(f"**Cron jobs active:** {status['cron_jobs']}")
            lines.append(f"**Poll jobs active:** {status['poll_jobs']}")

            # Recent executions with retry info
            recent = status.get("recent_executions", [])
            if recent:
                lines.append("\n### 📜 Recent Executions\n")

                # Count retry stats
                total_with_retry = 0
                successful_after_retry = 0

                for entry in recent[-10:]:
                    timestamp = entry.get("timestamp", "")[:16]
                    job_name = entry.get("job_name", "")
                    success = entry.get("success", False)
                    duration = entry.get("duration_ms", 0)
                    retry_info = entry.get("retry", {})

                    emoji = "✅" if success else "❌"
                    retry_badge = ""

                    if retry_info and retry_info.get("retried"):
                        total_with_retry += 1
                        attempts = retry_info.get("attempts", 1)
                        remediation = retry_info.get("remediation_applied", "")
                        if success:
                            successful_after_retry += 1
                            retry_badge = (
                                f" 🔄 (retry #{attempts}, fixed with {remediation})"
                                if remediation
                                else f" 🔄 (retry #{attempts})"
                            )
                        else:
                            retry_badge = f" 🔄 (failed after {attempts} attempts)"

                    lines.append(f"- {emoji} `{timestamp}` **{job_name}** ({duration}ms){retry_badge}")

                    if not success and entry.get("error"):
                        lines.append(f"  Error: {entry['error'][:100]}")

                # Show retry summary if any retries occurred
                if total_with_retry > 0:
                    lines.append(
                        f"\n**Retry Summary:** {successful_after_retry}/{total_with_retry} jobs recovered via auto-retry"
                    )
        else:
            lines.append("**Scheduler running:** ❌ No (not started)")
            lines.append("\n💡 The scheduler starts automatically with the MCP server.")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def cron_notifications(limit: int = 20) -> list[TextContent]:
        """
        Show recent notifications from scheduled jobs.

        Args:
            limit: Maximum number of notifications to show

        Returns:
            List of recent notifications.
        """
        from .notification_engine import get_notification_engine

        engine = get_notification_engine()

        if not engine:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Notification engine not initialized.\n\n"
                    "Notifications are logged to `memory/state/notifications.yaml`",
                )
            ]

        notifications = engine.get_recent_notifications(limit)

        if not notifications:
            return [
                TextContent(
                    type="text",
                    text="No recent notifications.\n\n" "Notifications will appear here after scheduled jobs run.",
                )
            ]

        lines = ["## 🔔 Recent Notifications\n"]

        for notif in reversed(notifications):
            timestamp = notif.get("timestamp", "")[:16]
            title = notif.get("title", "")
            success = notif.get("success", True)
            job_name = notif.get("job_name", "")

            emoji = "✅" if success else "❌"
            lines.append(f"### {emoji} {title}")
            lines.append(f"**Time:** {timestamp}")
            if job_name:
                lines.append(f"**Job:** {job_name}")

            message = notif.get("message", "")
            if message:
                # Truncate long messages
                if len(message) > 200:
                    message = message[:200] + "..."
                lines.append(f"```\n{message}\n```")

            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def cron_scheduler_toggle(enabled: bool = True) -> list[TextContent]:
        """
        Enable or disable the entire scheduler at runtime.

        This updates state.json and starts/stops the scheduler immediately,
        without requiring a server restart.

        Args:
            enabled: True to enable and start the scheduler, False to disable and stop it

        Returns:
            Confirmation of scheduler state change.
        """
        try:
            from tool_modules.aa_workflow.src.scheduler import (
                get_scheduler,
            )
        except ImportError:
            from .scheduler import get_scheduler

        # Update state file
        state_manager.set_service_enabled("scheduler", enabled, flush=True)

        scheduler = get_scheduler()

        if enabled:
            # Start the scheduler if not already running
            if scheduler and not scheduler.is_running:
                # Reload config to pick up any job changes
                scheduler.config = scheduler.config.__class__()
                await scheduler.start()
                return [
                    TextContent(
                        type="text",
                        text="✅ Scheduler **enabled** and started.\n\n"
                        f"**Active cron jobs:** {len(scheduler.config.get_cron_jobs())}\n"
                        f"**Active poll jobs:** {len(scheduler.config.get_poll_jobs())}\n\n"
                        "Jobs will now run on their configured schedules.",
                    )
                ]
            elif scheduler and scheduler.is_running:
                # Already running, just reload config
                scheduler.reload_config()
                return [
                    TextContent(
                        type="text",
                        text="✅ Scheduler already running. Config reloaded.\n\n"
                        f"**Active cron jobs:** {len(scheduler.config.get_cron_jobs())}\n"
                        f"**Active poll jobs:** {len(scheduler.config.get_poll_jobs())}",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text="✅ Scheduler **enabled** in config.\n\n"
                        "⚠️ Scheduler instance not found. It will start on next server restart.",
                    )
                ]
        else:
            # Stop the scheduler
            if scheduler and scheduler.is_running:
                await scheduler.stop()
                return [
                    TextContent(
                        type="text",
                        text="⏸️ Scheduler **disabled** and stopped.\n\n"
                        "All scheduled jobs are paused. Enable again to resume.",
                    )
                ]
            else:
                return [
                    TextContent(
                        type="text",
                        text="⏸️ Scheduler **disabled** in config.\n\n" "Scheduler was not running.",
                    )
                ]

    return registry.count
