# pylint: disable=duplicate-code,cyclic-import
"""Scheduler Engine - Cron-based task scheduling for MCP server.

Provides:
- CronScheduler: APScheduler-based scheduler for running skills on schedule
- Hot-reload support for config changes
- Integration with SkillExecutor for task execution
- Auto-retry with exponential backoff and remediation for failed jobs

RetryConfig, SchedulerConfig, and JobExecutionLog live in scheduler_config.
Job execution lives on JobRunner, which CronScheduler inherits.
"""

import logging
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

from server.config_manager import CONFIG_FILE
from server.config_manager import config as config_manager
from server.state_manager import state as state_manager

from .scheduler_config import (
    DEFAULT_RETRY_CONFIG,
    JobExecutionLog,
    RetryConfig,
    SchedulerConfig,
)
from .scheduler_job_runner import JobRunner

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _manager_bindings():
    """Expose config and state managers that tests patch on this module."""
    return config_manager, state_manager


# Re-export config types that callers import from this module.
__all__ = [
    "DEFAULT_RETRY_CONFIG",
    "CronScheduler",
    "JobExecutionLog",
    "RetryConfig",
    "SchedulerConfig",
    "get_scheduler",
    "init_scheduler",
    "start_scheduler",
    "stop_scheduler",
]


class CronScheduler(JobRunner):
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
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )

    async def start(self, add_cron_jobs: bool = True):
        """Start the scheduler.

        The scheduler always starts to enable config watching.
        Jobs are only added if the scheduler is enabled in config AND add_cron_jobs=True.

        Args:
            add_cron_jobs: If False, skip adding cron jobs (useful when cron daemon handles them).
                          Default True for backward compatibility with cron_daemon.py.
        """
        self._log_to_file(
            f"start() called, _running={self._running}, add_cron_jobs={add_cron_jobs}"
        )
        if self._running:
            logger.warning("Scheduler already running")
            self._log_to_file("Scheduler already running, returning")
            return

        self.scheduler = self._create_scheduler()
        self._log_to_file(f"Created scheduler, config.enabled={self.config.enabled}")
        self.scheduler.add_job(
            self._check_config_and_reload,
            "interval",
            seconds=30,
            id="_config_watcher",
            name="Config Watcher",
            replace_existing=True,
        )
        self._log_to_file("Added config watcher job")
        self._register_cron_jobs(add_cron_jobs)
        self.scheduler.start()
        self._running = True
        self._config_mtime = (
            CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
        )
        self._log_to_file(f"Scheduler started, _running={self._running}")

    def _register_cron_jobs(self, add_cron_jobs: bool):
        if self.config.enabled and add_cron_jobs:
            cron_jobs = self.config.get_cron_jobs()
            self._log_to_file(
                f"Adding {len(cron_jobs)} cron jobs: {[j.get('name') for j in cron_jobs]}"
            )
            for job in cron_jobs:
                self._add_cron_job(job)
            logger.info("Scheduler started with %s cron jobs", len(cron_jobs))
            return
        if self.config.enabled and not add_cron_jobs:
            logger.info("Scheduler started (cron jobs handled by cron_daemon)")
            self._log_to_file(
                "Scheduler started, cron jobs skipped (handled by cron_daemon)"
            )
            return
        logger.info("Scheduler started (disabled in config, watching for changes)")
        self._log_to_file("Scheduler disabled in config")

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
        if not skill or not cron_expr:
            logger.warning("Job %s missing skill or cron expression", job_name)
            return
        try:
            self._schedule_cron_job(job_config, job_name, skill, cron_expr)
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.error("Failed to add job %s: %s", job_name, exc)

    def _schedule_cron_job(self, job_config, job_name, skill, cron_expr):
        retry_config = self.config.get_retry_config(job_config)
        timeout_seconds = job_config.get("timeout_seconds", 600)
        trigger = self._parse_cron_to_trigger(cron_expr)
        self.scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_name,
            name=job_name,
            kwargs={
                "job_name": job_name,
                "skill": skill,
                "inputs": job_config.get("inputs", {}),
                "notify": job_config.get("notify", []),
                "persona": job_config.get("persona", ""),
                "retry_config": retry_config,
                "timeout_seconds": timeout_seconds,
            },
            replace_existing=True,
        )
        self._log_added_job(job_name, job_config, retry_config, timeout_seconds)

    def _log_added_job(self, job_name, job_config, retry_config, timeout_seconds):
        persona = job_config.get("persona", "")
        cron_expr = job_config.get("cron", "")
        skill = job_config.get("skill", "")
        persona_info = f" (persona: {persona})" if persona else ""
        retry_info = (
            f", retry: {retry_config.max_attempts}"
            if retry_config.enabled
            else ", retry: disabled"
        )
        timeout_info = (
            f", timeout: {timeout_seconds}s" if timeout_seconds != 600 else ""
        )
        logger.info(
            "Added cron job: %s (%s) -> skill:%s%s%s%s",
            job_name,
            cron_expr,
            skill,
            persona_info,
            retry_info,
            timeout_info,
        )

    def _parse_cron_to_trigger(self, cron_expr: str) -> CronTrigger:
        """Parse a cron expression into an APScheduler CronTrigger.

        Supports standard 5-field cron: minute hour day month day_of_week
        """
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression: {cron_expr} (expected 5 fields)"
            )
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=self.config.timezone,
        )

    def reload_config(self):
        """Reload configuration and update jobs."""
        if not self.scheduler:
            return
        self.config = SchedulerConfig()
        current_job_ids = {job.id for job in self.scheduler.get_jobs()}
        new_job_names = {job.get("name") for job in self.config.get_cron_jobs()}
        for job_id in current_job_ids:
            if job_id.startswith("_"):
                continue
            if job_id not in new_job_names:
                self.scheduler.remove_job(job_id)
                logger.info("Removed job: %s", job_id)
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

    async def _check_config_and_reload(self):
        """Periodically check for config changes and reload if needed.

        This method is called by the config watcher job every 30 seconds.
        It handles reloading job configurations and pausing jobs when disabled.
        """
        if not self.check_config_changed():
            return
        logger.info("Config file changed, checking for updates...")
        self._config_mtime = (
            CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
        )
        old_enabled = self.config.enabled
        self.config = SchedulerConfig()
        if old_enabled and not self.config.enabled:
            logger.info("Scheduler disabled in config, stopping...")
            self._drop_user_jobs()
            logger.info("Scheduler jobs paused (config watcher still running)")
            return
        if not old_enabled and self.config.enabled:
            logger.info("Scheduler enabled in config, starting jobs...")
        self.reload_config()

    def _drop_user_jobs(self):
        if not self.scheduler:
            return
        for job in self.scheduler.get_jobs():
            if job.id != "_config_watcher":
                self.scheduler.remove_job(job.id)

    async def run_job_now(self, job_name: str) -> dict:
        """Manually trigger a job to run immediately.

        Args:
            job_name: Name of the job to run

        Returns:
            Dict with success status and result/error
        """
        job_config = _find_job(self.config.jobs, job_name)
        if not job_config:
            return {"success": False, "error": f"Job not found: {job_name}"}
        try:
            await self._execute_job(
                job_name=job_name,
                skill=job_config.get("skill", ""),
                inputs=job_config.get("inputs", {}),
                notify=job_config.get("notify", []),
                persona=job_config.get("persona", ""),
                retry_config=self.config.get_retry_config(job_config),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # A manual run must return an error dict instead of escaping the scheduler.
            return {"success": False, "error": str(exc)}
        return {"success": True, "message": f"Job {job_name} executed"}

    def get_job_info(self, job_name: str) -> dict | None:
        """Get information about a specific job."""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(job_name)
        if not job:
            return None
        job_config = _find_job(self.config.jobs, job_name)
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        return {
            "name": job_name,
            "skill": job_config.get("skill") if job_config else "unknown",
            "cron": job_config.get("cron") if job_config else "unknown",
            "next_run": next_run,
            "enabled": self.config.job_is_enabled(job_config) if job_config else False,
            "notify": job_config.get("notify", []) if job_config else [],
            "retry": _retry_summary(self.config, job_config),
            "recent_executions": self.execution_log.get_for_job(job_name),
        }

    def get_all_jobs(self) -> list[dict]:
        """Get information about all configured jobs."""
        jobs = []
        for job_config in self.config.jobs:
            jobs.append(self._describe_job(job_config))
        return jobs

    def _describe_job(self, job_config: dict) -> dict:
        job_name = job_config.get("name", "unnamed")
        job_info = {
            "name": job_name,
            "skill": job_config.get("skill", ""),
            "enabled": self.config.job_is_enabled(job_config),
            "notify": job_config.get("notify", []),
        }
        if job_config.get("cron"):
            job_info["type"] = "cron"
            job_info["cron"] = job_config.get("cron")
            job_info["next_run"] = _next_cron_run(job_config["cron"])
        elif job_config.get("trigger") == "poll":
            job_info["type"] = "poll"
            job_info["poll_interval"] = job_config.get("poll_interval", "1h")
            job_info["condition"] = job_config.get("condition", "")
        return job_info

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


def _find_job(jobs: list, job_name: str) -> dict | None:
    for job in jobs:
        if job.get("name") == job_name:
            return job
    return None


def _retry_summary(config: SchedulerConfig, job_config: dict | None) -> dict | None:
    if not job_config:
        return None
    retry_config = config.get_retry_config(job_config)
    return {
        "enabled": retry_config.enabled,
        "max_attempts": retry_config.max_attempts,
        "backoff": retry_config.backoff,
        "retry_on": retry_config.retry_on,
    }


def _next_cron_run(expression: str):
    try:
        cron = croniter(expression, datetime.now())
        return cron.get_next(datetime).isoformat()
    except ValueError:
        return None


# Singleton. Tests patch this module attribute by name.
_scheduler: CronScheduler | None = None  # pylint: disable=invalid-name


def get_scheduler() -> CronScheduler | None:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(
    server: "FastMCP | None" = None,
    notification_callback: Callable | None = None,
) -> CronScheduler:
    """Initialize the global scheduler instance.

    This is a singleton - if a scheduler already exists, it returns the existing
    instance instead of creating a new one. This prevents duplicate job execution
    when multiple MCP server instances start (e.g., multiple Cursor windows).
    """
    module = sys.modules[__name__]
    current = getattr(module, "_scheduler")
    if current is not None:
        logger.warning(
            "Scheduler already initialized, returning existing instance. "
            "This prevents duplicate job execution from multiple MCP connections."
        )
        return current
    created = CronScheduler(server=server, notification_callback=notification_callback)
    setattr(module, "_scheduler", created)
    return created


async def start_scheduler(add_cron_jobs: bool = True):
    """Start the global scheduler.

    Args:
        add_cron_jobs: If False, skip adding cron jobs (cron_daemon handles them).
    """
    if _scheduler:
        await _scheduler.start(add_cron_jobs=add_cron_jobs)


async def stop_scheduler():
    """Stop the global scheduler."""
    if _scheduler:
        await _scheduler.stop()
