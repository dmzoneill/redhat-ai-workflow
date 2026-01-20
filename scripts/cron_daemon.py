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
    systemctl --user start cron-scheduler
    systemctl --user status cron-scheduler
    systemctl --user stop cron-scheduler

D-Bus:
    Service: com.aiworkflow.CronScheduler
    Path: /com/aiworkflow/CronScheduler
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

LOCK_FILE = Path("/tmp/cron-daemon.lock")
PID_FILE = Path("/tmp/cron-daemon.pid")
LOG_FILE = Path.home() / ".config" / "aa-workflow" / "cron_daemon.log"

# Configure logging
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
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


class CronDaemon(DaemonDBusBase):
    """Main cron scheduler daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.CronScheduler"
    object_path = "/com/aiworkflow/CronScheduler"
    interface_name = "com.aiworkflow.CronScheduler"

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
                    await self._scheduler._execute_job(job_name, skill, inputs)
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

        print()
        print("-" * 60)
        print("Daemon running. Press Ctrl+C to stop.")
        print(f"Log file: {LOG_FILE}")
        if self.enable_dbus:
            print(f"D-Bus: {self.service_name}")
        print("-" * 60)

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self):
        """Stop the daemon gracefully."""
        if not self.is_running:
            return

        print()
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
    systemctl --user start cron-scheduler
    systemctl --user status cron-scheduler

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
            print(f"   Log file: {LOG_FILE}")
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
