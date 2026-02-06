#!/usr/bin/env python3
"""
Cron Scheduler Daemon

A standalone service that runs scheduled jobs using Claude CLI.
Designed to run as a systemd user service.

Features:
- APScheduler-based cron scheduling
- Claude CLI execution for AI-powered job runs
- Single instance enforcement (lock file)
- D-Bus IPC for external control
- Graceful shutdown handling
- Config file watching for dynamic updates

Usage:
    python -m services.cron                # Run daemon
    python -m services.cron --status       # Check if running
    python -m services.cron --stop         # Stop running daemon
    python -m services.cron --list-jobs    # List scheduled jobs
    python -m services.cron --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-cron
    systemctl --user status bot-cron
    systemctl --user stop bot-cron

D-Bus:
    Service: com.aiworkflow.BotCron
    Path: /com/aiworkflow/BotCron
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from server.paths import CRON_STATE_FILE  # noqa: E402
from services.base.daemon import BaseDaemon, SingleInstance  # noqa: E402
from services.base.dbus import DaemonDBusBase, get_client  # noqa: E402
from services.base.sleep_wake import SleepWakeAwareDaemon  # noqa: E402

logger = logging.getLogger(__name__)


class CronDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main cron scheduler daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "cron"
    description = "Cron Scheduler Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotCron"
    object_path = "/com/aiworkflow/BotCron"
    interface_name = "com.aiworkflow.BotCron"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        # Initialize all parent classes
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        # SleepWakeAwareDaemon doesn't need explicit init

        self._scheduler = None
        self._jobs_executed = 0
        self._jobs_failed = 0
        self._state_writer_task = None

        # Register custom D-Bus method handlers
        self.register_handler("run_job", self._handle_run_job)
        self.register_handler("list_jobs", self._handle_list_jobs)
        self.register_handler("get_history", self._handle_get_history)
        self.register_handler("toggle_scheduler", self._handle_toggle_scheduler)
        self.register_handler("toggle_job", self._handle_toggle_job)
        self.register_handler("update_config", self._handle_update_config)
        self.register_handler("get_config", self._handle_get_config)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("get_state", self._handle_get_state)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return cron-specific statistics."""
        stats = {
            "jobs_executed": self._jobs_executed,
            "jobs_failed": self._jobs_failed,
            "enabled": self._scheduler.config.enabled if self._scheduler else False,
            "execution_mode": self._scheduler.config.execution_mode if self._scheduler else "unknown",
            "timezone": self._scheduler.config.timezone if self._scheduler else "unknown",
        }

        if self._scheduler:
            jobs = []
            for job in self._scheduler.scheduler.get_jobs():
                if job.id != "_config_watcher":
                    jobs.append(
                        {
                            "name": job.id,
                            "next_run": str(job.next_run_time) if job.next_run_time else None,
                        }
                    )
            stats["jobs"] = jobs
            stats["job_count"] = len(jobs)

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()

        # Add execution history
        if self._scheduler:
            history = self._scheduler.execution_log.get_recent(limit=10)
            service["recent_executions"] = history

        return {**base, **service}

    async def health_check(self) -> dict:
        """
        Perform a comprehensive health check on the cron daemon.

        Checks:
        - Service is running
        - Scheduler is initialized and running
        - Jobs are scheduled
        - No excessive job failures
        """
        self._last_health_check = time.time()
        now = time.time()

        checks = {
            "running": self.is_running,
            "scheduler_initialized": self._scheduler is not None,
        }

        # Check if scheduler is actually running
        if self._scheduler:
            checks["scheduler_running"] = self._scheduler.scheduler.running

            # Check if jobs are scheduled
            jobs = self._scheduler.scheduler.get_jobs()
            active_jobs = [j for j in jobs if j.id != "_config_watcher"]
            checks["jobs_scheduled"] = len(active_jobs) > 0

            # Check job failure rate (if we've executed jobs)
            total_executed = self._jobs_executed + self._jobs_failed
            if total_executed > 0:
                failure_rate = self._jobs_failed / total_executed
                checks["acceptable_failure_rate"] = failure_rate < 0.5
            else:
                checks["acceptable_failure_rate"] = True
        else:
            checks["scheduler_running"] = False
            checks["jobs_scheduled"] = False
            checks["acceptable_failure_rate"] = True

        # Check uptime (informational, not required for health)
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 10
        else:
            checks["uptime_ok"] = False

        # Overall health - only core checks required
        # uptime_ok is informational, not required for watchdog
        core_checks = ["running", "scheduler_initialized", "scheduler_running"]
        healthy = all(checks.get(k, False) for k in core_checks)

        # Build message
        if healthy:
            message = "Cron daemon is healthy"
        else:
            failed = [k for k, v in checks.items() if not v]
            message = f"Unhealthy: {', '.join(failed)}"

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": self._last_health_check,
            "jobs_executed": self._jobs_executed,
            "jobs_failed": self._jobs_failed,
        }

    async def _handle_run_job(self, job_name: str) -> dict:
        """Handle D-Bus request to run a job immediately."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        try:
            for job_config in self._scheduler.config.get_cron_jobs():
                if job_config.get("name") == job_name:
                    skill = job_config.get("skill")
                    inputs = job_config.get("inputs", {})
                    notify = job_config.get("notify", ["memory"])
                    await self._scheduler._execute_job(job_name, skill, inputs, notify)
                    return {"success": True, "job": job_name}

            return {"success": False, "error": f"Job not found: {job_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_list_jobs(self) -> dict:
        """Handle D-Bus request to list jobs."""
        if not self._scheduler:
            return {"jobs": []}

        jobs = []
        for job in self._scheduler.scheduler.get_jobs():
            if job.id != "_config_watcher":
                jobs.append(
                    {
                        "name": job.id,
                        "next_run": str(job.next_run_time) if job.next_run_time else None,
                    }
                )
        return {"jobs": jobs}

    async def _handle_get_history(self, limit: int = 20, **kwargs) -> dict:
        """Handle D-Bus request to get execution history."""
        if not self._scheduler:
            return {"success": False, "history": [], "error": "Scheduler not initialized"}

        history = self._scheduler.execution_log.get_recent(limit=limit)
        return {"success": True, "history": history}

    async def _handle_toggle_scheduler(self, enabled: bool) -> dict:
        """Handle D-Bus request to toggle scheduler enabled state."""
        try:
            from server.state_manager import state as state_manager

            state_manager.set_service_enabled("scheduler", enabled, flush=True)

            if self._scheduler:
                self._scheduler.config.reload()

            return {"success": True, "enabled": enabled, "message": f"Scheduler {'enabled' if enabled else 'disabled'}"}
        except Exception as e:
            logger.error(f"Failed to toggle scheduler: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_toggle_job(self, job_name: str, enabled: bool) -> dict:
        """Handle D-Bus request to toggle a specific job's enabled state."""
        try:
            from server.state_manager import state as state_manager

            state_manager.set_job_enabled(job_name, enabled, flush=True)

            if self._scheduler:
                self._scheduler.config.reload()

            return {
                "success": True,
                "job": job_name,
                "enabled": enabled,
                "message": f"Job '{job_name}' {'enabled' if enabled else 'disabled'}",
            }
        except Exception as e:
            logger.error(f"Failed to toggle job {job_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_update_config(self, section: str, key: str, value) -> dict:
        """Handle D-Bus request to update a config value."""
        try:
            from server.config_manager import config as config_manager

            section_data = config_manager.get(section, default={})
            if not isinstance(section_data, dict):
                section_data = {}

            if key:
                keys = key.split(".")
                obj = section_data
                for k in keys[:-1]:
                    if k not in obj or not isinstance(obj[k], dict):
                        obj[k] = {}
                    obj = obj[k]
                obj[keys[-1]] = value
            else:
                section_data = value

            config_manager.update_section(section, section_data, merge=True, flush=True)

            return {
                "success": True,
                "section": section,
                "key": key,
                "value": value,
                "message": f"Updated config: {section}.{key}" if key else f"Updated config: {section}",
            }
        except Exception as e:
            logger.error(f"Failed to update config {section}.{key}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_config(self, section: str, key: str = None) -> dict:
        """Handle D-Bus request to get a config value."""
        try:
            from server.config_manager import config as config_manager

            section_data = config_manager.get(section, default={})

            if key:
                keys = key.split(".")
                value = section_data
                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return {"success": True, "value": None}
                return {"success": True, "value": value}
            else:
                return {"success": True, "value": section_data}
        except Exception as e:
            logger.error(f"Failed to get config {section}.{key}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_write_state(self) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            await self._write_state()
            return {"success": True, "file": str(CRON_STATE_FILE)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full cron state for UI."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not initialized"}

        try:
            from server.state_manager import state as state_manager

            scheduled_jobs = {}
            for job in self._scheduler.scheduler.get_jobs():
                if job.id != "_config_watcher":
                    scheduled_jobs[job.id] = {
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    }

            jobs = []
            for job_config in self._scheduler.config.jobs:
                job_name = job_config.get("name", "")
                scheduled = scheduled_jobs.get(job_name, {})

                config_enabled = job_config.get("enabled", True)
                runtime_state = state_manager.get("jobs", job_name, {})
                if isinstance(runtime_state, dict) and "enabled" in runtime_state:
                    is_enabled = runtime_state["enabled"]
                else:
                    is_enabled = config_enabled

                jobs.append(
                    {
                        "name": job_name,
                        "description": job_config.get("description", ""),
                        "skill": job_config.get("skill", ""),
                        "cron": job_config.get("cron", ""),
                        "trigger": job_config.get("trigger", "cron"),
                        "persona": job_config.get("persona", ""),
                        "enabled": is_enabled,
                        "notify": job_config.get("notify", []),
                        "next_run": scheduled.get("next_run"),
                    }
                )

            history = self._scheduler.execution_log.get_recent(20)

            cron_state = {
                "enabled": self._scheduler.config.enabled if self._scheduler.config else True,
                "timezone": str(self._scheduler.config.timezone) if self._scheduler.config else "UTC",
                "execution_mode": self._scheduler.config.execution_mode if self._scheduler.config else "claude_cli",
                "jobs": jobs,
                "history": history,
                "total_history": len(history),
                "updated_at": datetime.now().isoformat(),
            }

            return {"success": True, "state": cron_state}

        except Exception as e:
            logger.error(f"Failed to get cron state: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Sleep/Wake Handling ====================

    async def on_system_wake(self):
        """Handle system wake from sleep (SleepWakeAwareDaemon interface)."""
        print("\n[Wake] System wake detected - checking scheduled jobs...")

        try:
            if self._scheduler:
                jobs = self._scheduler.scheduler.get_jobs()
                active_jobs = [j for j in jobs if j.id != "_config_watcher"]

                logger.info(f"After wake: {len(active_jobs)} scheduled jobs")
                print(f"   Active jobs: {len(active_jobs)}")

                for job in active_jobs[:5]:
                    print(f"      - {job.id}: next at {job.next_run_time}")

            print("   Wake handling complete\n")

        except Exception as e:
            logger.error(f"Error handling system wake: {e}")
            print(f"   Wake handling error: {e}\n")

    # ==================== Daemon Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()
        from tool_modules.aa_workflow.src.scheduler import get_scheduler, init_scheduler, start_scheduler

        print("=" * 60)
        print("Cron Scheduler Daemon")
        print("=" * 60)

        # Start D-Bus if enabled
        if self.enable_dbus:
            if await self.start_dbus():
                print(f"D-Bus IPC enabled ({self.service_name})")
            else:
                print("D-Bus not available")

        # Initialize scheduler
        scheduler = init_scheduler(server=None, notification_callback=None)

        print("Config loaded")
        print(f"   Enabled: {scheduler.config.enabled}")
        print(f"   Execution mode: {scheduler.config.execution_mode}")
        print(f"   Timezone: {scheduler.config.timezone}")

        if not scheduler.config.enabled:
            print()
            print("Scheduler is DISABLED in config.json")
            print("   Set schedules.enabled=true to enable")
            print()
            raise RuntimeError("Scheduler is disabled in config.json")

        # List jobs
        cron_jobs = scheduler.config.get_cron_jobs()
        print(f"   Cron jobs: {len(cron_jobs)}")
        for job in cron_jobs:
            print(f"      - {job.get('name')}: {job.get('cron')} -> {job.get('skill')}")

        print()
        print("Starting scheduler...")

        await start_scheduler()

        self._scheduler = get_scheduler()
        self.is_running = True

        print("Scheduler started")
        print()

        # Print next run times
        print("Next scheduled runs:")
        for job in self._scheduler.scheduler.get_jobs():
            if job.id != "_config_watcher":
                print(f"   {job.id}: {job.next_run_time}")

        # Start sleep/wake monitor
        await self.start_sleep_monitor()
        print("Sleep/wake monitor started")

        # Start state writer task
        self._state_writer_task = asyncio.create_task(self._state_writer_loop())
        print("State writer started")

        print()
        print("-" * 60)
        print("Daemon ready.")
        print("Logs: journalctl --user -u bot-cron -f")
        if self.enable_dbus:
            print(f"D-Bus: {self.service_name}")
        print("-" * 60)

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def _state_writer_loop(self):
        """Periodically write cron state to cron_state.json."""
        while not self._shutdown_event.is_set():
            try:
                await self._write_state()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"State writer error: {e}")
                await asyncio.sleep(30)

    async def _write_state(self):
        """Write current cron state to cron_state.json."""
        import json
        import tempfile

        if not self._scheduler:
            return

        try:
            from server.state_manager import state as state_manager

            scheduled_jobs = {}
            for job in self._scheduler.scheduler.get_jobs():
                if job.id != "_config_watcher":
                    scheduled_jobs[job.id] = {
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    }

            jobs = []
            for job_config in self._scheduler.config.jobs:
                job_name = job_config.get("name", "")
                scheduled = scheduled_jobs.get(job_name, {})

                config_enabled = job_config.get("enabled", True)
                runtime_state = state_manager.get("jobs", job_name, {})
                if isinstance(runtime_state, dict) and "enabled" in runtime_state:
                    is_enabled = runtime_state["enabled"]
                else:
                    is_enabled = config_enabled

                jobs.append(
                    {
                        "name": job_name,
                        "description": job_config.get("description", ""),
                        "skill": job_config.get("skill", ""),
                        "cron": job_config.get("cron", ""),
                        "trigger": job_config.get("trigger", "cron"),
                        "persona": job_config.get("persona", ""),
                        "enabled": is_enabled,
                        "notify": job_config.get("notify", []),
                        "next_run": scheduled.get("next_run"),
                    }
                )

            history = self._scheduler.execution_log.get_recent(20)

            cron_state = {
                "enabled": self._scheduler.config.enabled if self._scheduler.config else True,
                "timezone": str(self._scheduler.config.timezone) if self._scheduler.config else "UTC",
                "execution_mode": self._scheduler.config.execution_mode if self._scheduler.config else "claude_cli",
                "jobs": jobs,
                "history": history,
                "total_history": len(history),
                "updated_at": datetime.now().isoformat(),
            }

            CRON_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="cron_state_", dir=CRON_STATE_FILE.parent)
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(cron_state, f, indent=2, default=str)
                Path(temp_path).replace(CRON_STATE_FILE)
            except Exception:
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass
                raise

        except Exception as e:
            logger.debug(f"Failed to write cron state: {e}")

    async def shutdown(self):
        """Stop the daemon gracefully (BaseDaemon interface)."""
        if not self.is_running:
            return

        print()
        print("Stopping daemon...")

        # Stop state writer task
        if self._state_writer_task:
            self._state_writer_task.cancel()
            try:
                await self._state_writer_task
            except asyncio.CancelledError:
                pass

        # Stop sleep monitor
        try:
            await asyncio.wait_for(self.stop_sleep_monitor(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Sleep monitor stop timed out")

        print("Stopping scheduler...")

        from tool_modules.aa_workflow.src.scheduler import stop_scheduler

        await stop_scheduler()

        # Stop D-Bus
        await self.stop_dbus()

        self.is_running = False
        print("Cron Scheduler Daemon stopped")

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """Create argument parser with cron-specific arguments."""
        parser = BaseDaemon.create_argument_parser.__func__(cls)
        parser.add_argument(
            "--list-jobs",
            action="store_true",
            help="List configured cron jobs and exit",
        )
        return parser


def list_jobs():
    """List configured cron jobs without starting the daemon."""
    from tool_modules.aa_workflow.src.scheduler import SchedulerConfig

    config = SchedulerConfig()

    print("Configured Cron Jobs")
    print("=" * 60)
    print(f"Enabled: {config.enabled}")
    print(f"Timezone: {config.timezone}")
    print(f"Execution mode: {config.execution_mode}")
    print()

    cron_jobs = config.get_cron_jobs()
    if not cron_jobs:
        print("No enabled cron jobs configured.")
        return

    for job in cron_jobs:
        enabled = "[enabled]" if job.get("enabled", True) else "[disabled]"
        print(f"{enabled} {job.get('name')}")
        print(f"   Schedule: {job.get('cron')}")
        print(f"   Skill: {job.get('skill')}")
        persona = job.get("persona", "")
        if persona:
            print(f"   Persona: {persona}")
        print(f"   Notify: {', '.join(job.get('notify', []))}")
        print()


def main():
    """Main entry point."""
    import sys

    # Handle --list-jobs before BaseDaemon.main() takes over
    if "--list-jobs" in sys.argv:
        list_jobs()
        return

    # Use BaseDaemon.main() for standard daemon lifecycle
    CronDaemon.main()


if __name__ == "__main__":
    main()
