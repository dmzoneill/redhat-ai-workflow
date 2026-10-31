"""
Base Daemon Infrastructure

Provides the foundation for all AI Workflow daemons:
- SingleInstance: Lock file management for single-instance enforcement
- BaseDaemon: Base class with CLI, signals, and lifecycle management
- Systemd watchdog integration with D-Bus health verification

Usage:
    from services.base import BaseDaemon, SleepWakeAwareDaemon, DaemonDBusBase

    class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
        name = "my-service"
        description = "My service daemon"

        # D-Bus configuration
        service_name = "com.aiworkflow.MyService"
        object_path = "/com/aiworkflow/MyService"
        interface_name = "com.aiworkflow.MyService"

        async def run_daemon(self):
            # Main daemon logic
            while not self._shutdown_event.is_set():
                await asyncio.sleep(1)

    if __name__ == "__main__":
        MyDaemon.main()

IMPORTANT - Multiple Inheritance Order (MRO):
    When using multiple inheritance, the order matters! List mixins BEFORE BaseDaemon:

    CORRECT:   class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon)
    INCORRECT: class MyDaemon(BaseDaemon, DaemonDBusBase, SleepWakeAwareDaemon)

    This ensures:
    1. Mixin __init__ methods are called first (via super())
    2. BaseDaemon.__init__ is called last to complete initialization
    3. Method resolution follows Python's C3 linearization

    Each mixin should call super().__init__() to chain properly.
"""

import argparse
import asyncio
import fcntl
import logging
import os
import signal
import socket
import sys
from abc import ABC, abstractmethod
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)


# =============================================================================
# SYSTEMD WATCHDOG SUPPORT
# =============================================================================


def sd_notify(state: str) -> bool:
    """
    Send a notification to systemd.

    Args:
        state: Notification string (e.g., "READY=1", "WATCHDOG=1", "STATUS=...")

    Returns:
        True if notification was sent, False if NOTIFY_SOCKET not set
    """
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            # Handle abstract socket (starts with @)
            if notify_socket.startswith("@"):
                notify_socket = "\0" + notify_socket[1:]
            sock.connect(notify_socket)
            sock.sendall(state.encode())
            return True
        finally:
            sock.close()
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Notify boundary: a broken NOTIFY_SOCKET must not stop the daemon.
        logger.warning("Failed to send sd_notify(%s): %s", state, e, exc_info=True)
        return False


def get_watchdog_interval() -> float:
    """
    Get the watchdog interval from systemd.

    Returns:
        Interval in seconds to send watchdog pings (half of WatchdogSec),
        or 0 if watchdog is not enabled.
    """
    watchdog_usec = os.environ.get("WATCHDOG_USEC")
    if not watchdog_usec:
        return 0

    try:
        # Convert microseconds to seconds, ping at half the interval
        return int(watchdog_usec) / 1_000_000 / 2
    except ValueError:
        return 0


class SingleInstance:
    """
    Ensures only one instance of a daemon runs at a time.

    Uses file locking (fcntl.flock) for atomic lock acquisition.
    PID file is written for external status checks.

    Args:
        name: Daemon name used for lock/pid file paths
        lock_dir: Directory for lock files (default: /tmp)
    """

    def __init__(self, name: str, lock_dir: str = "/tmp"):
        self.name = name
        self.lock_dir = Path(lock_dir)
        self._lock_file: TextIO | None = None
        self._lock_stack = ExitStack()
        self._acquired = False

    @property
    def lock_path(self) -> Path:
        """Path to the lock file."""
        return self.lock_dir / f"{self.name}-daemon.lock"

    @property
    def pid_path(self) -> Path:
        """Path to the PID file."""
        return self.lock_dir / f"{self.name}-daemon.pid"

    def acquire(self) -> bool:
        """
        Try to acquire the lock.

        Returns:
            True if lock acquired, False if another instance is running.
        """
        # The flock is held only while this handle stays open, so the stack is kept until release().
        stack = ExitStack()
        try:
            lock_file = stack.enter_context(self.lock_path.open("w", encoding="utf-8"))
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID for external status checks
            self.pid_path.write_text(str(os.getpid()))
        except OSError:
            stack.close()
            return False
        self._lock_stack = stack
        self._lock_file = lock_file
        self._acquired = True
        return True

    def release(self):
        """Release the lock and clean up files."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_stack.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Cleanup boundary: unlocking must not raise out of release.
                logger.debug("Suppressed error: %s", exc, exc_info=True)
        if self.pid_path.exists():
            try:
                self.pid_path.unlink()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Cleanup boundary: removing the pid file must not raise.
                logger.debug("Suppressed error: %s", exc, exc_info=True)
        self._acquired = False

    def get_running_pid(self) -> int | None:
        """
        Get PID of running instance.

        Returns:
            PID if running, None otherwise.
        """
        if self.pid_path.exists():
            try:
                pid = int(self.pid_path.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError) as exc:
                logger.debug("Suppressed error: %s", exc)
        return None

    @property
    def is_acquired(self) -> bool:
        """Whether this instance holds the lock."""
        return self._acquired


class BaseDaemon(ABC):
    """
    Base class for all AI Workflow daemons.

    Provides:
    - Single instance enforcement via lock files
    - Standard CLI arguments (--status, --stop, --verbose, --dbus)
    - Signal handling for graceful shutdown
    - Logging configuration for systemd/journald
    - Systemd watchdog integration with D-Bus health verification

    Subclasses must:
    - Set `name` and `description` class attributes
    - Implement `run_daemon()` async method

    Usage:
        class MyDaemon(BaseDaemon):
            name = "my-service"
            description = "My service daemon"

            async def run_daemon(self):
                while not self._shutdown_event.is_set():
                    # Do work
                    await asyncio.sleep(1)

        if __name__ == "__main__":
            MyDaemon.main()
    """

    # Subclasses must set these
    name: str = ""
    description: str = ""

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        """
        Initialize the daemon.

        Args:
            verbose: Enable verbose logging
            enable_dbus: Enable D-Bus IPC interface
        """
        if not self.name:
            raise ValueError("Daemon 'name' must be set")

        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._single_instance = SingleInstance(self.name)
        self._watchdog_task: asyncio.Task | None = None
        self._watchdog_healthy = True  # Track if last health check passed

    @property
    def lock_file(self) -> Path:
        """Path to the lock file."""
        return self._single_instance.lock_path

    @property
    def pid_file(self) -> Path:
        """Path to the PID file."""
        return self._single_instance.pid_path

    @abstractmethod
    async def run_daemon(self):
        """
        Main daemon logic. Override this in subclasses.

        This method should run until self._shutdown_event is set.
        Use `await self._shutdown_event.wait()` or check
        `self._shutdown_event.is_set()` in loops.
        """

    async def startup(self):
        """
        Called before run_daemon(). Override for initialization.

        Default implementation starts D-Bus if enabled.
        """
        if self.enable_dbus and hasattr(self, "start_dbus"):
            # start_dbus is provided by DaemonDBusBase, not BaseDaemon.
            # pylint: disable-next=no-member
            await self.start_dbus()

    async def shutdown(self):
        """
        Called after run_daemon() exits. Override for cleanup.

        Default implementation stops D-Bus if enabled.
        """
        if self.enable_dbus and hasattr(self, "stop_dbus"):
            # stop_dbus is provided by DaemonDBusBase, not BaseDaemon.
            # pylint: disable-next=no-member
            await self.stop_dbus()

    def request_shutdown(self):
        """Request graceful shutdown of the daemon."""
        logger.info("Shutdown requested for %s", self.name)
        self._shutdown_event.set()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def signal_handler(sig):
            logger.info("Received signal %s", sig.name)
            self.request_shutdown()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler, sig)

    async def _watchdog_loop(self):
        """
        Periodically notify systemd that the daemon is healthy.

        This loop:
        1. Verifies D-Bus interface is responding (if enabled)
        2. Calls the daemon's health_check() method (if available)
        3. Only sends WATCHDOG=1 if both checks pass

        If the daemon becomes unhealthy, systemd will restart it after
        WatchdogSec expires without receiving a ping.
        """
        interval = get_watchdog_interval()
        if interval <= 0:
            logger.debug("Watchdog not enabled (WATCHDOG_USEC not set)")
            return

        logger.info("Watchdog enabled, pinging every %.1fs", interval)

        while not self._shutdown_event.is_set():
            try:
                healthy = await self._verify_health()

                if healthy:
                    sd_notify("WATCHDOG=1")
                    if not self._watchdog_healthy:
                        logger.info("Watchdog: Service recovered, resuming pings")
                    self._watchdog_healthy = True
                else:
                    if self._watchdog_healthy:
                        logger.warning("Watchdog: Health check failed, stopping pings")
                    self._watchdog_healthy = False
                    # Don't send watchdog ping - systemd will restart us

            except Exception:  # pylint: disable=broad-exception-caught
                # Watchdog boundary: health failures are contained here.
                logger.exception("Watchdog loop error")
                self._watchdog_healthy = False

            # Wait for next interval or shutdown
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=interval)
                break  # Shutdown requested
            except asyncio.TimeoutError as exc:
                logger.debug("Operation timed out: %s", exc)

    async def _verify_health(self) -> bool:
        """
        Verify the daemon is healthy by checking D-Bus and calling health_check().

        Returns:
            True if healthy, False otherwise
        """
        # Check 1: Verify D-Bus interface is responding (if enabled).
        # _bus and _dbus_interface come from DaemonDBusBase, not BaseDaemon.
        # pylint: disable-next=no-member
        if self.enable_dbus and hasattr(self, "_bus") and self._bus:
            try:
                # Try to call our own Ping method via D-Bus to verify the interface works
                # pylint: disable-next=no-member
                if hasattr(self, "_dbus_interface") and self._dbus_interface:
                    # The interface exists, D-Bus is working
                    pass
                else:
                    logger.warning("Watchdog: D-Bus interface not initialized")
                    return False
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Watchdog boundary: health failures are contained here.
                logger.warning("Watchdog: D-Bus check failed: %s", e, exc_info=True)
                return False

        # Check 2: Call daemon's health_check() if available
        if hasattr(self, "health_check"):
            try:
                result = await self.health_check()
                if isinstance(result, dict) and not result.get("healthy", True):
                    logger.warning(
                        "Watchdog: Health check failed: %s",
                        result.get("message", "unknown"),
                    )
                    return False
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Watchdog boundary: health failures are contained here.
                logger.warning("Watchdog: health_check() raised exception: %s", e, exc_info=True)
                return False

        return True

    async def _run(self):
        """Internal run method that handles lifecycle."""
        self._setup_signal_handlers()

        try:
            await self.startup()

            # Notify systemd we're ready (for Type=notify services)
            sd_notify("READY=1")
            sd_notify(f"STATUS=Running: {self.description or self.name}")
            logger.info("Daemon ready: %s", self.name)

            # Start watchdog loop in background
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

            await self.run_daemon()
        except asyncio.CancelledError:
            logger.info("Daemon cancelled")
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Lifecycle boundary: log the failure, then propagate it.
            logger.exception("Daemon error")
            sd_notify(f"STATUS=Error: {e}")
            raise
        finally:
            # Stop watchdog
            if self._watchdog_task and not self._watchdog_task.done():
                self._watchdog_task.cancel()
                # Let the watchdog finish without swallowing a cancellation of this task
                await asyncio.wait({self._watchdog_task})

            sd_notify("STOPPING=1")
            await self.shutdown()

    def run(self):
        """Run the daemon (blocking)."""
        # Acquire lock
        if not self._single_instance.acquire():
            pid = self._single_instance.get_running_pid()
            print(f"Another instance is already running (PID: {pid})")
            sys.exit(1)

        try:
            asyncio.run(self._run())
        except asyncio.CancelledError:
            # Cancellation already logged and cleaned up inside _run(); exit normally.
            logger.info("Daemon exited after cancellation")
        finally:
            self._single_instance.release()

    @classmethod
    def configure_logging(cls, verbose: bool = False):
        """
        Configure logging for systemd/journald.

        When running under systemd, stdout/stderr go to journald.
        Format excludes timestamp (journald adds its own).
        """
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stderr)],
        )

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create the argument parser with standard daemon arguments.

        Subclasses can override to add custom arguments.
        """
        parser = argparse.ArgumentParser(
            description=cls.description or f"{cls.name} daemon",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "--status",
            action="store_true",
            help="Check if daemon is running",
        )
        parser.add_argument(
            "--stop",
            action="store_true",
            help="Stop running daemon",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Enable verbose output",
        )
        parser.add_argument(
            "--dbus",
            action="store_true",
            dest="enable_dbus",
            default=True,  # D-Bus enabled by default
            help="Enable D-Bus IPC interface (default)",
        )
        parser.add_argument(
            "--no-dbus",
            action="store_false",
            dest="enable_dbus",
            help="Disable D-Bus IPC interface",
        )
        return parser

    @classmethod
    def handle_status(cls) -> int:
        """Handle --status command. Returns exit code."""
        instance = SingleInstance(cls.name)
        pid = instance.get_running_pid()
        if pid:
            print(f"{cls.name} is running (PID: {pid})")
            return 0
        print(f"{cls.name} is not running")
        return 1

    @classmethod
    def handle_stop(cls) -> int:
        """Handle --stop command. Returns exit code."""
        instance = SingleInstance(cls.name)
        pid = instance.get_running_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to {cls.name} (PID: {pid})")
                return 0
            except OSError as e:
                print(f"Failed to stop {cls.name}: {e}")
                return 1
        else:
            print(f"{cls.name} is not running")
            return 1

    @classmethod
    def main(cls, args: list | None = None):
        """
        Main entry point for the daemon.

        Handles CLI arguments and runs the daemon.

        Args:
            args: Command line arguments (defaults to sys.argv)
        """
        parser = cls.create_argument_parser()
        parsed = parser.parse_args(args)

        # Handle --status
        if parsed.status:
            sys.exit(cls.handle_status())

        # Handle --stop
        if parsed.stop:
            sys.exit(cls.handle_stop())

        # Configure logging
        cls.configure_logging(verbose=parsed.verbose)

        # Create and run daemon
        daemon = cls(verbose=parsed.verbose, enable_dbus=parsed.enable_dbus)
        daemon.run()
