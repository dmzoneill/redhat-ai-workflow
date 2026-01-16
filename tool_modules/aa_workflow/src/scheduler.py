"""Scheduler Engine - Cron-based task scheduling for MCP server.

Provides:
- CronScheduler: APScheduler-based scheduler for running skills on schedule
- Hot-reload support for config changes
- Integration with SkillExecutor for task execution
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
CONFIG_FILE = PROJECT_DIR / "config.json"
SKILLS_DIR = PROJECT_DIR / "skills"


class SchedulerConfig:
    """Configuration for the scheduler loaded from config.json."""

    def __init__(self, config_data: dict | None = None):
        """Initialize scheduler config from config data or load from file."""
        if config_data is None:
            config_data = self._load_config()

        schedules = config_data.get("schedules", {})
        self.enabled = schedules.get("enabled", False)
        self.timezone = schedules.get("timezone", "UTC")
        self.jobs = schedules.get("jobs", [])
        self.poll_sources = schedules.get("poll_sources", {})

    def _load_config(self) -> dict:
        """Load config from config.json."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        return {}

    def get_cron_jobs(self) -> list[dict]:
        """Get jobs that use cron triggers (not poll triggers)."""
        return [j for j in self.jobs if j.get("cron") and j.get("enabled", True)]

    def get_poll_jobs(self) -> list[dict]:
        """Get jobs that use poll triggers."""
        return [j for j in self.jobs if j.get("trigger") == "poll" and j.get("enabled", True)]


class JobExecutionLog:
    """Track job execution history."""

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.entries: list[dict] = []

    def log_execution(
        self,
        job_name: str,
        skill: str,
        success: bool,
        duration_ms: int,
        error: str | None = None,
        output_preview: str | None = None,
    ):
        """Log a job execution."""
        entry = {
            "job_name": job_name,
            "skill": skill,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration_ms": duration_ms,
            "error": error,
            "output_preview": output_preview[:200] if output_preview else None,
        }
        self.entries.append(entry)

        # Trim to max entries
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent execution entries."""
        return self.entries[-limit:]

    def get_for_job(self, job_name: str, limit: int = 5) -> list[dict]:
        """Get recent executions for a specific job."""
        job_entries = [e for e in self.entries if e["job_name"] == job_name]
        return job_entries[-limit:]


class CronScheduler:
    """APScheduler-based cron scheduler for MCP server.

    Runs skills on schedule based on config.json configuration.
    """

    def __init__(
        self,
        server: "FastMCP | None" = None,
        notification_callback: Callable | None = None,
    ):
        """Initialize the scheduler.

        Args:
            server: FastMCP server instance for skill execution
            notification_callback: Async callback for sending notifications
        """
        self.server = server
        self.notification_callback = notification_callback
        self.config = SchedulerConfig()
        self.scheduler: AsyncIOScheduler | None = None
        self.execution_log = JobExecutionLog()
        self._running = False
        self._config_mtime: float | None = None

    def _create_scheduler(self) -> AsyncIOScheduler:
        """Create a new APScheduler instance."""
        return AsyncIOScheduler(
            timezone=self.config.timezone,
            job_defaults={
                "coalesce": True,  # Combine missed runs
                "max_instances": 1,  # Only one instance per job
                "misfire_grace_time": 300,  # 5 min grace for missed jobs
            },
        )

    async def start(self):
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        if not self.config.enabled:
            logger.info("Scheduler disabled in config")
            return

        self.scheduler = self._create_scheduler()

        # Add cron jobs
        for job in self.config.get_cron_jobs():
            self._add_cron_job(job)

        # Start the scheduler
        self.scheduler.start()
        self._running = True
        self._config_mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None

        logger.info(f"Scheduler started with {len(self.config.get_cron_jobs())} cron jobs")

    async def stop(self):
        """Stop the scheduler gracefully."""
        if not self._running or not self.scheduler:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Scheduler stopped")

    def _add_cron_job(self, job_config: dict):
        """Add a cron job to the scheduler."""
        if not self.scheduler:
            return

        job_name = job_config.get("name", "unnamed")
        skill = job_config.get("skill", "")
        cron_expr = job_config.get("cron", "")
        inputs = job_config.get("inputs", {})
        notify = job_config.get("notify", [])

        if not skill or not cron_expr:
            logger.warning(f"Job {job_name} missing skill or cron expression")
            return

        try:
            # Parse cron expression into APScheduler trigger
            trigger = self._parse_cron_to_trigger(cron_expr)

            # Add the job
            self.scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                id=job_name,
                name=job_name,
                kwargs={
                    "job_name": job_name,
                    "skill": skill,
                    "inputs": inputs,
                    "notify": notify,
                },
                replace_existing=True,
            )

            logger.info(f"Added cron job: {job_name} ({cron_expr}) -> skill:{skill}")

        except Exception as e:
            logger.error(f"Failed to add job {job_name}: {e}")

    def _parse_cron_to_trigger(self, cron_expr: str) -> CronTrigger:
        """Parse a cron expression into an APScheduler CronTrigger.

        Supports standard 5-field cron: minute hour day month day_of_week
        """
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr} (expected 5 fields)")

        minute, hour, day, month, day_of_week = parts

        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=self.config.timezone,
        )

    async def _execute_job(
        self,
        job_name: str,
        skill: str,
        inputs: dict,
        notify: list[str],
    ):
        """Execute a scheduled job."""
        import time

        start_time = time.time()
        logger.info(f"Executing scheduled job: {job_name} (skill: {skill})")

        success = False
        error_msg = None
        output = None

        try:
            # Execute the skill
            output = await self._run_skill(skill, inputs)
            success = True
            logger.info(f"Job {job_name} completed successfully")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job {job_name} failed: {e}")

        duration_ms = int((time.time() - start_time) * 1000)

        # Log execution
        self.execution_log.log_execution(
            job_name=job_name,
            skill=skill,
            success=success,
            duration_ms=duration_ms,
            error=error_msg,
            output_preview=output,
        )

        # Send notifications
        if notify and self.notification_callback:
            await self._send_notifications(
                job_name=job_name,
                skill=skill,
                success=success,
                output=output,
                error=error_msg,
                notify_channels=notify,
            )

    async def _run_skill(self, skill_name: str, inputs: dict) -> str:
        """Run a skill and return its output."""
        import yaml

        from .skill_engine import SkillExecutor

        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        with open(skill_file) as f:
            skill = yaml.safe_load(f)

        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            debug=False,
            server=self.server,
            enable_interactive_recovery=False,  # No interactive recovery for scheduled jobs
            emit_events=False,  # No VS Code events for background jobs
        )

        result = await executor.execute()
        return result

    async def _send_notifications(
        self,
        job_name: str,
        skill: str,
        success: bool,
        output: str | None,
        error: str | None,
        notify_channels: list[str],
    ):
        """Send notifications for job completion."""
        if not self.notification_callback:
            return

        try:
            await self.notification_callback(
                job_name=job_name,
                skill=skill,
                success=success,
                output=output,
                error=error,
                channels=notify_channels,
            )
        except Exception as e:
            logger.error(f"Failed to send notifications for {job_name}: {e}")

    def reload_config(self):
        """Reload configuration and update jobs."""
        if not self.scheduler:
            return

        old_config = self.config
        self.config = SchedulerConfig()

        # Remove jobs that no longer exist
        current_job_ids = {j.id for j in self.scheduler.get_jobs()}
        new_job_names = {j.get("name") for j in self.config.get_cron_jobs()}

        for job_id in current_job_ids:
            if job_id not in new_job_names:
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed job: {job_id}")

        # Add/update jobs
        for job in self.config.get_cron_jobs():
            self._add_cron_job(job)

        logger.info("Scheduler config reloaded")

    def check_config_changed(self) -> bool:
        """Check if config file has changed since last load."""
        if not CONFIG_FILE.exists():
            return False

        current_mtime = CONFIG_FILE.stat().st_mtime
        if self._config_mtime is None:
            self._config_mtime = current_mtime
            return False

        return current_mtime > self._config_mtime

    async def run_job_now(self, job_name: str) -> dict:
        """Manually trigger a job to run immediately.

        Args:
            job_name: Name of the job to run

        Returns:
            Dict with success status and result/error
        """
        # Find the job config
        job_config = None
        for job in self.config.jobs:
            if job.get("name") == job_name:
                job_config = job
                break

        if not job_config:
            return {"success": False, "error": f"Job not found: {job_name}"}

        skill = job_config.get("skill", "")
        inputs = job_config.get("inputs", {})
        notify = job_config.get("notify", [])

        try:
            await self._execute_job(
                job_name=job_name,
                skill=skill,
                inputs=inputs,
                notify=notify,
            )
            return {"success": True, "message": f"Job {job_name} executed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_job_info(self, job_name: str) -> dict | None:
        """Get information about a specific job."""
        if not self.scheduler:
            return None

        job = self.scheduler.get_job(job_name)
        if not job:
            return None

        # Find config
        job_config = None
        for j in self.config.jobs:
            if j.get("name") == job_name:
                job_config = j
                break

        next_run = job.next_run_time.isoformat() if job.next_run_time else None

        return {
            "name": job_name,
            "skill": job_config.get("skill") if job_config else "unknown",
            "cron": job_config.get("cron") if job_config else "unknown",
            "next_run": next_run,
            "enabled": job_config.get("enabled", True) if job_config else False,
            "notify": job_config.get("notify", []) if job_config else [],
            "recent_executions": self.execution_log.get_for_job(job_name),
        }

    def get_all_jobs(self) -> list[dict]:
        """Get information about all configured jobs."""
        jobs = []

        for job_config in self.config.jobs:
            job_name = job_config.get("name", "unnamed")
            job_info = {
                "name": job_name,
                "skill": job_config.get("skill", ""),
                "enabled": job_config.get("enabled", True),
                "notify": job_config.get("notify", []),
            }

            # Add cron-specific info
            if job_config.get("cron"):
                job_info["type"] = "cron"
                job_info["cron"] = job_config.get("cron")

                # Calculate next run time
                try:
                    cron = croniter(job_config["cron"], datetime.now())
                    job_info["next_run"] = cron.get_next(datetime).isoformat()
                except Exception:
                    job_info["next_run"] = None

            # Add poll-specific info
            elif job_config.get("trigger") == "poll":
                job_info["type"] = "poll"
                job_info["poll_interval"] = job_config.get("poll_interval", "1h")
                job_info["condition"] = job_config.get("condition", "")

            jobs.append(job_info)

        return jobs

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "timezone": self.config.timezone,
            "total_jobs": len(self.config.jobs),
            "cron_jobs": len(self.config.get_cron_jobs()),
            "poll_jobs": len(self.config.get_poll_jobs()),
            "recent_executions": self.execution_log.get_recent(10),
        }

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running


# Global scheduler instance
_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler | None:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(
    server: "FastMCP | None" = None,
    notification_callback: Callable | None = None,
) -> CronScheduler:
    """Initialize the global scheduler instance."""
    global _scheduler
    _scheduler = CronScheduler(server=server, notification_callback=notification_callback)
    return _scheduler


async def start_scheduler():
    """Start the global scheduler."""
    if _scheduler:
        await _scheduler.start()


async def stop_scheduler():
    """Stop the global scheduler."""
    if _scheduler:
        await _scheduler.stop()
