#!/usr/bin/env python3
"""
Cron Scheduler Daemon

A standalone service that runs scheduled jobs using Claude CLI.
Designed to run as a systemd user service, similar to slack_daemon.py.

Features:
- APScheduler-based cron scheduling
- Claude CLI execution for AI-powered job runs
- Single instance enforcement (lock file)
- D-Bus IPC for external control
- Graceful shutdown handling
- Config file watching for dynamic updates

Usage:
    python scripts/cron_daemon.py                # Run daemon
    python scripts/cron_daemon.py --status       # Check if running
    python scripts/cron_daemon.py --stop         # Stop running daemon
    python scripts/cron_daemon.py --list-jobs    # List scheduled jobs
    python scripts/cron_daemon.py --dbus         # Enable D-Bus IPC

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
import fcntl
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dbus_base import DaemonDBusBase, get_client  # noqa: E402
from scripts.common.sleep_wake import SleepWakeAwareDaemon  # noqa: E402

LOCK_FILE = Path("/tmp/cron-daemon.lock")
PID_FILE = Path("/tmp/cron-daemon.pid")

# Import centralized paths - cron daemon owns its own state file
from server.paths import CRON_STATE_FILE

# Configure logging for journalctl
# When running under systemd, stdout/stderr automatically go to journald
# Use stderr for logs (stdout may be used for structured output)
# Format without timestamp - journald adds its own timestamps
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


class CronDaemon(SleepWakeAwareDaemon, DaemonDBusBase):
    """Main cron scheduler daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.BotCron"
    object_path = "/com/aiworkflow/BotCron"
    interface_name = "com.aiworkflow.BotCron"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._jobs_executed = 0
        self._jobs_failed = 0

        # Register custom D-Bus method handlers
        self.register_handler("run_job", self._handle_run_job)
        self.register_handler("list_jobs", self._handle_list_jobs)
        self.register_handler("get_history", self._handle_get_history)
        self.register_handler("toggle_scheduler", self._handle_toggle_scheduler)
        self.register_handler("toggle_job", self._handle_toggle_job)
        self.register_handler("update_config", self._handle_update_config)
        self.register_handler("get_config", self._handle_get_config)
        self.register_handler("write_state", self._handle_write_state)

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
        import time

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
                checks["acceptable_failure_rate"] = failure_rate < 0.5  # Less than 50% failures
            else:
                checks["acceptable_failure_rate"] = True  # No jobs run yet is OK
        else:
            checks["scheduler_running"] = False
            checks["jobs_scheduled"] = False
            checks["acceptable_failure_rate"] = True

        # Check uptime (at least 10 seconds)
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 10
        else:
            checks["uptime_ok"] = False

        # Overall health
        healthy = all(checks.values())

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
            # Find the job config
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

    async def _handle_get_history(self, limit: int = 20) -> dict:
        """Handle D-Bus request to get execution history."""
        if not self._scheduler:
            return {"history": []}

        history = self._scheduler.execution_log.get_recent(limit=limit)
        return {"history": history}

    async def _handle_toggle_scheduler(self, enabled: bool) -> dict:
        """Handle D-Bus request to toggle scheduler enabled state.

        Uses StateManager for thread-safe state persistence.
        """
        try:
            from server.state_manager import state as state_manager

            state_manager.set_service_enabled("scheduler", enabled, flush=True)

            # Reload config to pick up the change
            if self._scheduler:
                self._scheduler.config.reload()

            return {"success": True, "enabled": enabled, "message": f"Scheduler {'enabled' if enabled else 'disabled'}"}
        except Exception as e:
            logger.error(f"Failed to toggle scheduler: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_toggle_job(self, job_name: str, enabled: bool) -> dict:
        """Handle D-Bus request to toggle a specific job's enabled state.

        Uses StateManager for thread-safe state persistence.
        """
        try:
            from server.state_manager import state as state_manager

            state_manager.set_job_enabled(job_name, enabled, flush=True)

            # Reload config to pick up the change
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

    async def _handle_update_config(self, section: str, key: str, value: any) -> dict:
        """Handle D-Bus request to update a config value.

        Uses ConfigManager for thread-safe config persistence.

        Args:
            section: Top-level config section (e.g., "inference", "slack")
            key: Dot-separated key path within section (e.g., "default_model")
            value: Value to set
        """
        try:
            from server.config_manager import config as config_manager

            # Get current section
            section_data = config_manager.get(section, default={})
            if not isinstance(section_data, dict):
                section_data = {}

            # Navigate to nested key and set value
            if key:
                keys = key.split(".")
                obj = section_data
                for k in keys[:-1]:
                    if k not in obj or not isinstance(obj[k], dict):
                        obj[k] = {}
                    obj = obj[k]
                obj[keys[-1]] = value
            else:
                # No key means replace entire section
                section_data = value

            # Update section with merge
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
        """Handle D-Bus request to get a config value.

        Uses ConfigManager for thread-safe config access.

        Args:
            section: Top-level config section (e.g., "inference", "slack")
            key: Optional dot-separated key path within section
        """
        try:
            from server.config_manager import config as config_manager

            section_data = config_manager.get(section, default={})

            if key:
                # Navigate to nested key
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

    # ==================== Sleep/Wake Handling ====================

    async def on_system_wake(self):
        """Handle system wake from sleep (SleepWakeAwareDaemon interface).

        After wake, we need to check if any jobs were missed and potentially
        run them. APScheduler handles missed jobs based on misfire_grace_time,
        but we log the wake event for visibility.
        """
        print("\n🌅 System wake detected - checking scheduled jobs...")

        try:
            if self._scheduler:
                # Get current jobs and their next run times
                jobs = self._scheduler.scheduler.get_jobs()
                active_jobs = [j for j in jobs if j.id != "_config_watcher"]

                logger.info(f"After wake: {len(active_jobs)} scheduled jobs")
                print(f"   📅 Active jobs: {len(active_jobs)}")

                # Log next run times
                for job in active_jobs[:5]:  # Show first 5
                    print(f"      - {job.id}: next at {job.next_run_time}")

            print("   ✅ Wake handling complete\n")

        except Exception as e:
            logger.error(f"Error handling system wake: {e}")
            print(f"   ⚠️  Wake handling error: {e}\n")

    # ==================== Daemon Lifecycle ====================

    async def start(self):
        """Initialize and start the daemon."""
        from tool_modules.aa_workflow.src.scheduler import get_scheduler, init_scheduler, start_scheduler

        self.start_time = datetime.now().timestamp()

        print("=" * 60)
        print("🕐 Cron Scheduler Daemon")
        print("=" * 60)

        # Start D-Bus if enabled
        if self.enable_dbus:
            if await self.start_dbus():
                print(f"✅ D-Bus IPC enabled ({self.service_name})")
            else:
                print("⚠️  D-Bus not available")

        # Initialize scheduler (without MCP server - we use Claude CLI)
        scheduler = init_scheduler(server=None, notification_callback=None)

        print("✅ Config loaded")
        print(f"   Enabled: {scheduler.config.enabled}")
        print(f"   Execution mode: {scheduler.config.execution_mode}")
        print(f"   Timezone: {scheduler.config.timezone}")

        if not scheduler.config.enabled:
            print()
            print("⚠️  Scheduler is DISABLED in config.json")
            print("   Set schedules.enabled=true to enable")
            print()
            print("Exiting...")
            return

        # List jobs
        cron_jobs = scheduler.config.get_cron_jobs()
        print(f"   Cron jobs: {len(cron_jobs)}")
        for job in cron_jobs:
            print(f"      - {job.get('name')}: {job.get('cron')} -> {job.get('skill')}")

        print()
        print("Starting scheduler...")

        # Start the scheduler
        await start_scheduler()

        self._scheduler = get_scheduler()
        self.is_running = True

        print("✅ Scheduler started")
        print()

        # Print next run times
        print("📅 Next scheduled runs:")
        for job in self._scheduler.scheduler.get_jobs():
            if job.id != "_config_watcher":
                print(f"   {job.id}: {job.next_run_time}")

        # Start sleep/wake monitor (from SleepWakeAwareDaemon mixin)
        await self.start_sleep_monitor()
        print("✅ Sleep/wake monitor started")

        # Start state writer task (writes cron_state.json periodically)
        self._state_writer_task = asyncio.create_task(self._state_writer_loop())
        print("✅ State writer started")

        print()
        print("-" * 60)
        print("Daemon running. Press Ctrl+C to stop.")
        print("Logs: journalctl --user -u bot-cron -f")
        if self.enable_dbus:
            print(f"D-Bus: {self.service_name}")
        print("-" * 60)

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def _state_writer_loop(self):
        """Periodically write cron state to cron_state.json.

        Each service owns its own state file. The VS Code extension reads
        all state files on refresh. No shared file = no race conditions.
        """
        while not self._shutdown_event.is_set():
            try:
                await self._write_state()
                await asyncio.sleep(30)  # Write every 30 seconds (cron changes less frequently)
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
            # Get scheduled jobs from APScheduler (for next_run times)
            scheduled_jobs = {}
            for job in self._scheduler.scheduler.get_jobs():
                if job.id != "_config_watcher":
                    scheduled_jobs[job.id] = {
                        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    }

            # Get ALL jobs from config (including disabled ones and poll jobs)
            # This is what the UI needs to display
            jobs = []
            for job_config in self._scheduler.config.jobs:
                job_name = job_config.get("name", "")
                scheduled = scheduled_jobs.get(job_name, {})

                # Check if job is enabled:
                # 1. Config default (from config.json)
                # 2. Runtime override (from state.json via state_manager)
                from server.state_manager import state as state_manager

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

            # Get execution history
            history = self._scheduler.execution_log.get_recent(20)

            # Build cron state
            cron_state = {
                "enabled": self._scheduler.config.enabled if self._scheduler.config else True,
                "timezone": str(self._scheduler.config.timezone) if self._scheduler.config else "UTC",
                "execution_mode": self._scheduler.config.execution_mode if self._scheduler.config else "claude_cli",
                "jobs": jobs,
                "history": history,
                "total_history": len(history),
                "updated_at": datetime.now().isoformat(),
            }

            # Write atomically
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

    async def stop(self):
        """Stop the daemon gracefully."""
        if not self.is_running:
            return

        print()
        print("Stopping daemon...")

        # Stop state writer task
        if hasattr(self, "_state_writer_task") and self._state_writer_task:
            self._state_writer_task.cancel()
            try:
                await self._state_writer_task
            except asyncio.CancelledError:
                pass

        # Stop sleep monitor first (from SleepWakeAwareDaemon mixin)
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
        print("✅ Cron Scheduler Daemon stopped")

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            self._shutdown_event.set()
            self.request_shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


def list_jobs():
    """List configured cron jobs without starting the daemon."""
    from tool_modules.aa_workflow.src.scheduler import SchedulerConfig

    config = SchedulerConfig()

    print("📋 Configured Cron Jobs")
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
        enabled = "✅" if job.get("enabled", True) else "❌"
        print(f"{enabled} {job.get('name')}")
        print(f"   Schedule: {job.get('cron')}")
        print(f"   Skill: {job.get('skill')}")
        persona = job.get("persona", "")
        if persona:
            print(f"   Persona: {persona}")
        print(f"   Notify: {', '.join(job.get('notify', []))}")
        print()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Cron Scheduler Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/cron_daemon.py              # Start daemon
    python scripts/cron_daemon.py --dbus       # Start with D-Bus IPC
    python scripts/cron_daemon.py --status     # Check status
    python scripts/cron_daemon.py --stop       # Stop daemon
    python scripts/cron_daemon.py --list-jobs  # List jobs

Systemd:
    systemctl --user start bot-cron
    systemctl --user status bot-cron

D-Bus Control:
    python -c "import asyncio; from scripts.common.dbus_base import get_client; \\
        c = get_client('cron'); asyncio.run(c.connect()); print(asyncio.run(c.get_status()))"
""",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--dbus",
        action="store_true",
        help="Enable D-Bus IPC interface",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status of running daemon and exit",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop running daemon and exit",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="List configured cron jobs and exit",
    )

    args = parser.parse_args()

    # Handle --list-jobs
    if args.list_jobs:
        list_jobs()
        return

    # Check for single-instance commands
    instance = SingleInstance()

    # Handle --status: Try D-Bus first, fall back to PID check
    if args.status:
        # Try D-Bus status first
        try:
            client = get_client("cron")
            if await client.connect():
                status = await client.get_status()
                await client.disconnect()
                print("✅ Cron daemon is running (via D-Bus)")
                print(f"   Uptime: {status.get('uptime', 0):.0f}s")
                print(f"   Jobs: {status.get('job_count', 0)}")
                print(f"   Executed: {status.get('jobs_executed', 0)}")
                print(f"   Failed: {status.get('jobs_failed', 0)}")
                print(f"   Mode: {status.get('execution_mode', 'unknown')}")
                return
        except Exception:
            pass

        # Fall back to PID check
        pid = instance.get_running_pid()
        if pid:
            print(f"✅ Cron daemon is running (PID: {pid})")
            print(f"   Lock file: {LOCK_FILE}")
            print(f"   PID file: {PID_FILE}")
            print("   Logs: journalctl --user -u bot-cron -f")
            print("   (D-Bus not available - run with --dbus for IPC)")
        else:
            print("❌ Cron daemon is not running")
        return

    # Handle --stop: Try D-Bus first, fall back to SIGTERM
    if args.stop:
        # Try D-Bus shutdown first
        try:
            client = get_client("cron")
            if await client.connect():
                result = await client.shutdown()
                await client.disconnect()
                if result.get("success"):
                    print("✅ Shutdown signal sent via D-Bus")
                    return
        except Exception:
            pass

        # Fall back to SIGTERM
        pid = instance.get_running_pid()
        if pid:
            print(f"Stopping daemon (PID: {pid})...")
            try:
                os.kill(pid, signal.SIGTERM)
                print("✅ Stop signal sent")
            except OSError as e:
                print(f"❌ Failed to stop: {e}")
        else:
            print("❌ Cron daemon is not running")
        return

    # Try to acquire the lock
    if not instance.acquire():
        existing_pid = instance.get_running_pid()
        print(f"⚠️  Another instance is already running (PID: {existing_pid})")
        print()
        print("Use --status to check status or --stop to stop it.")
        return

    daemon = CronDaemon(verbose=args.verbose, enable_dbus=args.dbus)
    daemon.setup_signal_handlers()

    try:
        await daemon.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Daemon error: {e}")
        import traceback

        logger.error(traceback.format_exc())
    finally:
        await daemon.stop()
        instance.release()
        print("🔓 Lock released")


if __name__ == "__main__":
    asyncio.run(main())
