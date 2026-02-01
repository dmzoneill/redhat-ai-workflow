#!/usr/bin/env python3
"""
Stats Daemon - Serves agent statistics via D-Bus

This daemon provides D-Bus access to agent statistics files:
- agent_stats.json: Tool calls, skill executions, memory ops
- inference_stats.json: LLM inference statistics
- skill_execution.json: Current skill execution state

The daemon watches these files for changes and serves them via D-Bus,
allowing the VS Code extension to read stats without direct file access.

D-Bus Service: com.aiworkflow.BotStats
Object Path: /com/aiworkflow/BotStats

Usage:
    python scripts/stats_daemon.py           # Run daemon
    python scripts/stats_daemon.py --status  # Check if running

Systemd:
    systemctl --user start bot-stats
    systemctl --user status bot-stats
"""

import argparse
import asyncio
import fcntl
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.base.dbus import DaemonDBusBase  # noqa: E402

# Lock and PID files
LOCK_FILE = Path("/tmp/stats-daemon.lock")
PID_FILE = Path("/tmp/stats-daemon.pid")

# Stats files
AA_CONFIG_DIR = Path.home() / ".config" / "aa-workflow"
AGENT_STATS_FILE = AA_CONFIG_DIR / "agent_stats.json"
INFERENCE_STATS_FILE = AA_CONFIG_DIR / "inference_stats.json"
SKILL_EXECUTION_FILE = AA_CONFIG_DIR / "skill_execution.json"


def get_performance_summary_path() -> Path:
    """Get current quarter's performance summary file path."""
    now = datetime.now()
    year = now.year
    quarter = (now.month - 1) // 3 + 1
    return AA_CONFIG_DIR / "performance" / str(year) / f"q{quarter}" / "performance" / "summary.json"


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
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
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError):
                pass
        return None


class StatsDaemon(DaemonDBusBase):
    """Stats daemon with D-Bus support."""

    # D-Bus configuration
    service_name = "com.aiworkflow.BotStats"
    object_path = "/com/aiworkflow/BotStats"
    interface_name = "com.aiworkflow.BotStats"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        super().__init__()
        self.verbose = verbose
        self.enable_dbus = enable_dbus
        self._shutdown_event = asyncio.Event()
        self._stats_cache: dict[str, Any] = {}
        self._last_modified: dict[str, float] = {}

        # Register D-Bus handlers
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("get_agent_stats", self._handle_get_agent_stats)
        self.register_handler("get_inference_stats", self._handle_get_inference_stats)
        self.register_handler("get_skill_execution", self._handle_get_skill_execution)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return stats-specific statistics."""
        return {
            "files_watched": 4,
            "cache_entries": len(self._stats_cache),
            "last_refresh": datetime.now().isoformat(),
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        return {
            "status": "running",
            "files": {
                "agent_stats": str(AGENT_STATS_FILE),
                "inference_stats": str(INFERENCE_STATS_FILE),
                "skill_execution": str(SKILL_EXECUTION_FILE),
                "performance_summary": str(get_performance_summary_path()),
            },
            "cache_age": {k: datetime.now().timestamp() - v for k, v in self._last_modified.items()},
        }

    # ==================== D-Bus Handlers ====================

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full stats state for UI.

        Returns all stats in a single call for efficient UI updates.
        """
        # Load performance summary and transform to expected format
        perf_summary = self._load_file(get_performance_summary_path())
        performance_data = None
        if perf_summary:
            # Transform summary.json format to PerformanceState format expected by UI
            now = datetime.now()
            quarter = (now.month - 1) // 3 + 1
            quarter_start = datetime(now.year, (quarter - 1) * 3 + 1, 1)
            day_of_quarter = (now - quarter_start).days + 1

            performance_data = {
                "last_updated": perf_summary.get("last_updated", now.isoformat()),
                "quarter": f"Q{quarter} {now.year}",
                "day_of_quarter": day_of_quarter,
                "overall_percentage": perf_summary.get("overall_percentage", 0),
                "competencies": {
                    k: {"points": perf_summary.get("cumulative_points", {}).get(k, 0), "percentage": v}
                    for k, v in perf_summary.get("cumulative_percentage", {}).items()
                },
                "highlights": perf_summary.get("highlights", []),
                "gaps": perf_summary.get("gaps", []),
                "questions_summary": perf_summary.get("questions_summary"),
            }

        return {
            "success": True,
            "state": {
                "agent_stats": self._load_file(AGENT_STATS_FILE),
                "inference_stats": self._load_file(INFERENCE_STATS_FILE),
                "skill_execution": self._load_file(SKILL_EXECUTION_FILE),
                "performance": performance_data,
                "updated_at": datetime.now().isoformat(),
            },
        }

    async def _handle_get_agent_stats(self, **kwargs) -> dict:
        """Get agent statistics (tool calls, skill executions, etc.)."""
        stats = self._load_file(AGENT_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Agent stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_inference_stats(self, **kwargs) -> dict:
        """Get inference statistics (LLM usage, tokens, etc.)."""
        stats = self._load_file(INFERENCE_STATS_FILE)
        if stats is None:
            return {"success": False, "error": "Inference stats file not found"}
        return {"success": True, "stats": stats}

    async def _handle_get_skill_execution(self, **kwargs) -> dict:
        """Get current skill execution state."""
        state = self._load_file(SKILL_EXECUTION_FILE)
        if state is None:
            return {"success": False, "error": "Skill execution file not found"}
        return {"success": True, "execution": state}

    # ==================== File Loading ====================

    def _load_file(self, filepath: Path) -> dict | None:
        """Load and cache a JSON file."""
        key = str(filepath)
        try:
            if not filepath.exists():
                return None

            # Check if file has been modified
            mtime = filepath.stat().st_mtime
            if key in self._stats_cache and self._last_modified.get(key, 0) >= mtime:
                return self._stats_cache[key]

            # Load fresh data
            with open(filepath) as f:
                data = json.load(f)
            self._stats_cache[key] = data
            self._last_modified[key] = mtime
            return data

        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
            return self._stats_cache.get(key)

    # ==================== Main Loop ====================

    async def run(self):
        """Main daemon run loop."""
        logger.info("Stats daemon starting...")
        self.is_running = True
        self.start_time = datetime.now().timestamp()

        # Ensure config directory exists
        AA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Initial load
        self._load_file(AGENT_STATS_FILE)
        self._load_file(INFERENCE_STATS_FILE)
        self._load_file(SKILL_EXECUTION_FILE)
        self._load_file(get_performance_summary_path())

        # Start D-Bus
        if self.enable_dbus:
            await self.start_dbus()

        logger.info("Stats daemon running")

        try:
            # Wait for shutdown
            await self._shutdown_event.wait()
        finally:
            if self.enable_dbus:
                await self.stop_dbus()
            self.is_running = False
            logger.info("Stats daemon stopped")

    def shutdown(self):
        """Request graceful shutdown."""
        self._shutdown_event.set()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Stats Daemon")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--status", action="store_true", help="Check daemon status")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--no-dbus", action="store_true", help="Disable D-Bus")
    args = parser.parse_args()

    single = SingleInstance()

    if args.status:
        pid = single.get_running_pid()
        if pid:
            print(f"Stats daemon is running (PID: {pid})")
            sys.exit(0)
        else:
            print("Stats daemon is not running")
            sys.exit(1)

    if args.stop:
        pid = single.get_running_pid()
        if pid:
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to PID {pid}")
        else:
            print("Stats daemon is not running")
        sys.exit(0)

    # Try to acquire lock
    if not single.acquire():
        pid = single.get_running_pid()
        logger.error(f"Another instance is running (PID: {pid})")
        sys.exit(1)

    daemon = StatsDaemon(verbose=args.verbose, enable_dbus=not args.no_dbus)

    # Setup signal handlers using asyncio (properly wakes up event loop)
    loop = asyncio.get_running_loop()

    def signal_handler():
        logger.info("Received shutdown signal, shutting down...")
        daemon.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await daemon.run()
    finally:
        single.release()


if __name__ == "__main__":
    asyncio.run(main())
