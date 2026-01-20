#!/usr/bin/env python3
"""
Google Meet Bot Daemon

A standalone service that monitors calendars and auto-joins meetings.
Designed to run as a systemd user service, similar to slack_daemon.py.

Features:
- Calendar polling for upcoming meetings
- Automatic meeting join with configurable buffer
- Note-taking during meetings
- Single instance enforcement (lock file)
- D-Bus IPC for external control
- Graceful shutdown handling

Usage:
    python scripts/meet_daemon.py                # Run daemon
    python scripts/meet_daemon.py --status       # Check if running
    python scripts/meet_daemon.py --stop         # Stop running daemon
    python scripts/meet_daemon.py --list         # List upcoming meetings
    python scripts/meet_daemon.py --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start meet-bot
    systemctl --user status meet-bot
    systemctl --user stop meet-bot

D-Bus:
    Service: com.aiworkflow.MeetBot
    Path: /com/aiworkflow/MeetBot
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

LOCK_FILE = Path("/tmp/meet-daemon.lock")
PID_FILE = Path("/tmp/meet-daemon.pid")
LOG_FILE = Path.home() / ".config" / "aa-workflow" / "meet_daemon.log"

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


class MeetDaemon(DaemonDBusBase):
    """Main Google Meet bot daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.MeetBot"
    object_path = "/com/aiworkflow/MeetBot"
    interface_name = "com.aiworkflow.MeetBot"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._scheduler = None
        self._meetings_joined = 0
        self._meetings_completed = 0

        # Register custom D-Bus method handlers
        self.register_handler("list_meetings", self._handle_list_meetings)
        self.register_handler("skip_meeting", self._handle_skip_meeting)
        self.register_handler("force_join", self._handle_force_join)
        self.register_handler("list_calendars", self._handle_list_calendars)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return meet-specific statistics."""
        stats = {
            "meetings_joined": self._meetings_joined,
            "meetings_completed": self._meetings_completed,
        }

        if self._scheduler:
            scheduler_status = await self._scheduler.get_status()
            stats["current_meeting"] = scheduler_status.get("current_meeting")
            stats["upcoming_count"] = scheduler_status.get("upcoming_count", 0)
            stats["completed_today"] = scheduler_status.get("completed_today", 0)
            stats["last_poll"] = scheduler_status.get("last_poll")

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()

        # Add upcoming meetings
        if self._scheduler:
            scheduler_status = await self._scheduler.get_status()
            service["upcoming_meetings"] = scheduler_status.get("upcoming_meetings", [])
            service["errors"] = scheduler_status.get("errors", [])

        return {**base, **service}

    async def _handle_list_meetings(self) -> dict:
        """Handle D-Bus request to list upcoming meetings."""
        if not self._scheduler:
            return {"meetings": []}

        status = await self._scheduler.get_status()
        return {"meetings": status.get("upcoming_meetings", [])}

    async def _handle_skip_meeting(self, event_id: str) -> dict:
        """Handle D-Bus request to skip a meeting."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.skip_meeting(event_id)
        return {"success": success, "event_id": event_id}

    async def _handle_force_join(self, event_id: str) -> dict:
        """Handle D-Bus request to force join a meeting."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.force_join(event_id)
        return {"success": success, "event_id": event_id}

    async def _handle_list_calendars(self) -> dict:
        """Handle D-Bus request to list monitored calendars."""
        if not self._scheduler:
            return {"calendars": []}

        calendars = await self._scheduler.list_calendars()
        return {
            "calendars": [
                {
                    "calendar_id": c.calendar_id,
                    "name": c.name,
                    "enabled": c.enabled,
                    "auto_join": c.auto_join,
                    "bot_mode": c.bot_mode,
                }
                for c in calendars
            ]
        }

    # ==================== Daemon Lifecycle ====================

    async def start(self):
        """Initialize and start the daemon."""
        from tool_modules.aa_meet_bot.src.meeting_scheduler import init_scheduler

        self.start_time = datetime.now().timestamp()

        print("=" * 60)
        print("🎥 Google Meet Bot Daemon")
        print("=" * 60)

        # Start D-Bus if enabled
        if self.enable_dbus:
            if await self.start_dbus():
                print(f"✅ D-Bus IPC enabled ({self.service_name})")
            else:
                print("⚠️  D-Bus not available")

        # Initialize scheduler
        try:
            self._scheduler = await init_scheduler()
            print("✅ Meeting scheduler initialized")
        except Exception as e:
            print(f"❌ Failed to initialize scheduler: {e}")
            logger.error(f"Initialization error: {e}")
            return

        # List monitored calendars
        calendars = await self._scheduler.list_calendars()
        print(f"   Monitored calendars: {len(calendars)}")
        for cal in calendars:
            status = "✅" if cal.enabled else "❌"
            print(f"      {status} {cal.name} ({cal.calendar_id})")

        if not calendars:
            print()
            print("⚠️  No calendars configured!")
            print("   Add calendars using the meet_bot tools:")
            print("   meet_add_calendar(calendar_id='your@email.com')")
            print()

        print()
        print("Starting scheduler...")

        # Start the scheduler
        await self._scheduler.start()
        self.is_running = True

        print("✅ Scheduler started")
        print()

        # Show status
        status = await self._scheduler.get_status()
        print(f"📅 Upcoming meetings: {status['upcoming_count']}")
        for meeting in status.get("upcoming_meetings", [])[:5]:
            print(f"   - {meeting['title']} at {meeting['start']}")

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

        if self._scheduler:
            await self._scheduler.stop()

        # Stop D-Bus
        await self.stop_dbus()

        self.is_running = False
        print("✅ Meet Bot Daemon stopped")

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, shutting down...")
            self._shutdown_event.set()
            self.request_shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def list_meetings():
    """List upcoming meetings without starting the daemon."""
    from tool_modules.aa_meet_bot.src.meeting_scheduler import init_scheduler

    print("📅 Upcoming Meetings")
    print("=" * 60)

    try:
        scheduler = await init_scheduler()

        # Trigger a poll
        await scheduler._poll_calendars()

        status = await scheduler.get_status()

        if not status.get("upcoming_meetings"):
            print("No upcoming meetings with Google Meet links found.")
            return

        for meeting in status["upcoming_meetings"]:
            status_icon = {
                "scheduled": "📅",
                "joining": "🔄",
                "active": "🎥",
                "completed": "✅",
                "skipped": "⏭️",
            }.get(meeting["status"], "❓")

            print(f"{status_icon} {meeting['title']}")
            print(f"   Start: {meeting['start']}")
            print(f"   End: {meeting['end']}")
            print(f"   Status: {meeting['status']}")
            print(f"   Mode: {meeting['bot_mode']}")
            print()

    except Exception as e:
        print(f"❌ Error: {e}")
        logger.error(f"Failed to list meetings: {e}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Google Meet Bot Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/meet_daemon.py              # Start daemon
    python scripts/meet_daemon.py --dbus       # Start with D-Bus IPC
    python scripts/meet_daemon.py --status     # Check status
    python scripts/meet_daemon.py --stop       # Stop daemon
    python scripts/meet_daemon.py --list       # List upcoming meetings

Systemd:
    systemctl --user start meet-bot
    systemctl --user status meet-bot

D-Bus Control:
    python -c "import asyncio; from scripts.common.dbus_base import get_client; \\
        c = get_client('meet'); asyncio.run(c.connect()); print(asyncio.run(c.get_status()))"
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
        "--list",
        action="store_true",
        help="List upcoming meetings and exit",
    )

    args = parser.parse_args()

    # Handle --list
    if args.list:
        await list_meetings()
        return

    # Check for single-instance commands
    instance = SingleInstance()

    # Handle --status: Try D-Bus first, fall back to PID check
    if args.status:
        # Try D-Bus status first
        try:
            client = get_client("meet")
            if await client.connect():
                status = await client.get_status()
                await client.disconnect()
                print("✅ Meet bot daemon is running (via D-Bus)")
                print(f"   Uptime: {status.get('uptime', 0):.0f}s")
                print(f"   Current meeting: {status.get('current_meeting', 'None')}")
                print(f"   Upcoming: {status.get('upcoming_count', 0)}")
                print(f"   Completed today: {status.get('completed_today', 0)}")
                return
        except Exception:
            pass

        # Fall back to PID check
        pid = instance.get_running_pid()
        if pid:
            print(f"✅ Meet bot daemon is running (PID: {pid})")
            print(f"   Lock file: {LOCK_FILE}")
            print(f"   PID file: {PID_FILE}")
            print(f"   Log file: {LOG_FILE}")
            print("   (D-Bus not available - run with --dbus for IPC)")
        else:
            print("❌ Meet bot daemon is not running")
        return

    # Handle --stop: Try D-Bus first, fall back to SIGTERM
    if args.stop:
        # Try D-Bus shutdown first
        try:
            client = get_client("meet")
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
            print("❌ Meet bot daemon is not running")
        return

    # Try to acquire the lock
    if not instance.acquire():
        existing_pid = instance.get_running_pid()
        print(f"⚠️  Another instance is already running (PID: {existing_pid})")
        print()
        print("Use --status to check status or --stop to stop it.")
        return

    daemon = MeetDaemon(verbose=args.verbose, enable_dbus=args.dbus)
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
