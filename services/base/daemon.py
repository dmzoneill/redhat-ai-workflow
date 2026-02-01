#!/usr/bin/env python3
"""
Base Daemon Infrastructure

Provides the foundation for all AI Workflow daemons:
- SingleInstance: Lock file management for single-instance enforcement
- BaseDaemon: Base class with CLI, signals, and lifecycle management

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
"""

import argparse
import asyncio
import fcntl
import logging
import os
import signal
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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
        self._lock_file = None
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
        try:
            self._lock_file = open(self.lock_path, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID for external status checks
            self.pid_path.write_text(str(os.getpid()))
            self._acquired = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the lock and clean up files."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
        if self.pid_path.exists():
            try:
                self.pid_path.unlink()
            except Exception:
                pass
        self._acquired = False

    def get_running_pid(self) -> Optional[int]:
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
            except (ValueError, OSError):
                pass
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
        pass

    async def startup(self):
        """
        Called before run_daemon(). Override for initialization.

        Default implementation starts D-Bus if enabled.
        """
        if self.enable_dbus and hasattr(self, "start_dbus"):
            await self.start_dbus()

    async def shutdown(self):
        """
        Called after run_daemon() exits. Override for cleanup.

        Default implementation stops D-Bus if enabled.
        """
        if self.enable_dbus and hasattr(self, "stop_dbus"):
            await self.stop_dbus()

    def request_shutdown(self):
        """Request graceful shutdown of the daemon."""
        logger.info(f"Shutdown requested for {self.name}")
        self._shutdown_event.set()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        def signal_handler(sig):
            logger.info(f"Received signal {sig.name}")
            self.request_shutdown()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler, sig)

    async def _run(self):
        """Internal run method that handles lifecycle."""
        self._setup_signal_handlers()

        try:
            await self.startup()
            await self.run_daemon()
        except asyncio.CancelledError:
            logger.info("Daemon cancelled")
        except Exception as e:
            logger.exception(f"Daemon error: {e}")
            raise
        finally:
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
            help="Enable D-Bus IPC interface",
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
        else:
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
    def main(cls, args: Optional[list] = None):
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
