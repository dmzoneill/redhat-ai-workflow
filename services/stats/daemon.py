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
    python -m services.stats           # Run daemon
    python -m services.stats --status  # Check if running
    python -m services.stats --dbus    # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-stats
    systemctl --user status bot-stats
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase

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


logger = logging.getLogger(__name__)


class StatsDaemon(DaemonDBusBase, BaseDaemon):
    """Stats daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "stats"
    description = "Stats Daemon - Agent statistics via D-Bus"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotStats"
    object_path = "/com/aiworkflow/BotStats"
    interface_name = "com.aiworkflow.BotStats"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
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

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Stats daemon starting...")

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

        self.is_running = True
        logger.info("Stats daemon ready")

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Stats daemon shutting down...")

        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Stats daemon stopped")

    async def health_check(self) -> dict:
        """Perform a health check on the stats daemon."""
        self._last_health_check = time.time()

        checks = {
            "running": self.is_running,
            "config_dir_exists": AA_CONFIG_DIR.exists(),
            "cache_entries": len(self._stats_cache) > 0,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": "Stats daemon is healthy" if healthy else "Stats daemon has issues",
            "timestamp": self._last_health_check,
        }


if __name__ == "__main__":
    StatsDaemon.main()
