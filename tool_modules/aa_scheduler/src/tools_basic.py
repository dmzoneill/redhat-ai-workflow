"""Scheduler MCP Tools - Tools for managing scheduled jobs.

Provides:
- cron_list: List all scheduled jobs with next run time
- cron_add: Add a new scheduled job
- cron_remove: Remove a scheduled job
- cron_enable: Enable/disable a job
- cron_run_now: Manually trigger a scheduled job
- cron_status: Show scheduler status and recent executions
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from croniter import croniter
from mcp.types import TextContent

from server.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
CONFIG_FILE = PROJECT_DIR / "config.json"


def _load_config() -> dict:
    """Load config from config.json."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _save_config(config: dict):
    """Save config to config.json."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def _get_schedules_config() -> dict:
    """Get the schedules section from config."""
    config = _load_config()
    return config.get("schedules", {})


def _update_schedules_config(schedules: dict):
    """Update the schedules section in config."""
    config = _load_config()
    config["schedules"] = schedules
    _save_config(config)


def register_tools(server: "FastMCP") -> int:
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

        if not schedules.get("enabled", False):
            return [
                TextContent(
                    type="text",
                    text="⚠️ Scheduler is disabled.\n\nEnable it by setting `schedules.enabled: true` in config.json",
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
        lines.append(f"**Timezone:** {schedules.get('timezone', 'UTC')}\n")

        now = datetime.now()

        for job in jobs:
            name = job.get("name", "unnamed")
            skill = job.get("skill", "")
            enabled = job.get("enabled", True)
            notify = job.get("notify", [])

            status_emoji = "✅" if enabled else "⏸️"
            lines.append(f"### {status_emoji} {name}")
            lines.append(f"**Skill:** `{skill}`")

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
    ) -> list[TextContent]:
        """
        Add a new scheduled job.

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

        Returns:
            Confirmation of job creation.

        Examples:
            # Morning coffee at 8:30 AM on weekdays
            cron_add("morning_coffee", "coffee", cron="30 8 * * 1-5", notify="slack,desktop")

            # Evening beer at 5:30 PM on weekdays
            cron_add("evening_beer", "beer", cron="30 17 * * 1-5", notify="slack")

            # Check for stale PRs every hour
            cron_add("stale_prs", "pr_reminder", poll_interval="1h", poll_condition="gitlab_stale_prs")
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
                "enabled": True,
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

        # Build job config
        job: dict = {
            "name": name,
            "skill": skill,
            "enabled": enabled,
            "notify": notify_channels,
        }

        if job_inputs:
            job["inputs"] = job_inputs

        if cron:
            job["cron"] = cron
        else:
            job["trigger"] = "poll"
            job["poll_interval"] = poll_interval
            if poll_condition:
                job["condition"] = poll_condition

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

        # Find and update the job
        found = False
        for job in jobs:
            if job.get("name") == name:
                job["enabled"] = enabled
                found = True
                break

        if not found:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Job not found: `{name}`\n\nUse `cron_list` to see available jobs.",
                )
            ]

        schedules["jobs"] = jobs
        _update_schedules_config(schedules)

        status = "enabled" if enabled else "disabled"
        emoji = "✅" if enabled else "⏸️"

        return [
            TextContent(
                type="text",
                text=f"{emoji} Job **{name}** is now **{status}**\n\n"
                "The change will take effect on next scheduler restart.",
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

            # Execute the skill directly
            skill = job_config.get("skill", "")
            inputs = job_config.get("inputs", {})

            try:
                from .skill_engine import _skill_run_impl

                result = await _skill_run_impl(
                    skill_name=skill,
                    inputs=json.dumps(inputs),
                    execute=True,
                    debug=False,
                    server=server,
                )
                return result
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
        from .scheduler import get_scheduler

        scheduler = get_scheduler()
        schedules = _get_schedules_config()

        lines = ["## 🕐 Scheduler Status\n"]

        # Basic config status
        enabled = schedules.get("enabled", False)
        timezone = schedules.get("timezone", "UTC")
        total_jobs = len(schedules.get("jobs", []))

        lines.append(f"**Enabled in config:** {'✅ Yes' if enabled else '❌ No'}")
        lines.append(f"**Timezone:** {timezone}")
        lines.append(f"**Total jobs configured:** {total_jobs}")

        if scheduler:
            status = scheduler.get_status()
            lines.append(f"**Scheduler running:** {'✅ Yes' if status['running'] else '❌ No'}")
            lines.append(f"**Cron jobs active:** {status['cron_jobs']}")
            lines.append(f"**Poll jobs active:** {status['poll_jobs']}")

            # Recent executions
            recent = status.get("recent_executions", [])
            if recent:
                lines.append("\n### 📜 Recent Executions\n")
                for entry in recent[-10:]:
                    timestamp = entry.get("timestamp", "")[:16]
                    job_name = entry.get("job_name", "")
                    success = entry.get("success", False)
                    duration = entry.get("duration_ms", 0)

                    emoji = "✅" if success else "❌"
                    lines.append(f"- {emoji} `{timestamp}` **{job_name}** ({duration}ms)")

                    if not success and entry.get("error"):
                        lines.append(f"  Error: {entry['error'][:100]}")
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

    return registry.count
