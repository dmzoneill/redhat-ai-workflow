"""
Agent Statistics Tracking

Tracks and persists agent activity metrics:
- Tool calls (count, duration, success/failure)
- Skill executions (count, duration, success/failure)
- Memory operations (reads/writes)
- Lines of code written (estimated from file edits)
- Session activity

Stats are persisted to: ~/.config/aa-workflow/agent_stats.json
Daily stats are rolled up and historical data is kept for 30 days.

This module is workspace-aware: stats can be tracked per-workspace in addition
to global stats. Use workspace_uri parameter to track workspace-specific stats.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Stats file path - centralized in server.paths
try:
    from server.paths import AA_CONFIG_DIR, AGENT_STATS_FILE

    STATS_FILE = AGENT_STATS_FILE
    STATS_DIR = AA_CONFIG_DIR
except ImportError:
    STATS_FILE = Path.home() / ".config" / "aa-workflow" / "agent_stats.json"
    STATS_DIR = STATS_FILE.parent

# Current workspace for tracking (set by tools)
_current_workspace_uri: str = "default"


def set_current_workspace(workspace_uri: str) -> None:
    """Set the current workspace for stats tracking."""
    global _current_workspace_uri
    _current_workspace_uri = workspace_uri


def get_current_workspace() -> str:
    """Get the current workspace for stats tracking."""
    return _current_workspace_uri


class AgentStats:
    """Tracks and persists agent activity statistics.

    Workspace-aware: tracks both global and per-workspace stats.
    """

    _instance: "AgentStats | None" = None
    _lock = Lock()

    def __new__(cls) -> "AgentStats":
        """Singleton pattern for global stats tracking."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._stats_lock = Lock()
        self._stats = self._load_stats()
        self._ensure_today()

    def _load_stats(self) -> dict[str, Any]:
        """Load stats from disk or create new."""
        try:
            if STATS_FILE.exists():
                with open(STATS_FILE) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load stats: {e}")

        return self._create_empty_stats()

    def _create_empty_stats(self) -> dict[str, Any]:
        """Create empty stats structure."""
        return {
            "version": 2,  # Bumped for workspace support
            "created": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "lifetime": {
                "tool_calls": 0,
                "tool_successes": 0,
                "tool_failures": 0,
                "tool_duration_ms": 0,
                "skill_executions": 0,
                "skill_successes": 0,
                "skill_failures": 0,
                "skill_duration_ms": 0,
                "memory_reads": 0,
                "memory_writes": 0,
                "lines_written": 0,
                "sessions": 0,
            },
            "daily": {},  # date -> daily stats
            "tools": {},  # tool_name -> {calls, successes, failures, duration_ms}
            "skills": {},  # skill_name -> {executions, successes, failures, duration_ms}
            "workspaces": {},  # workspace_uri -> workspace-specific stats
            "current_session": {
                "started": datetime.now().isoformat(),
                "tool_calls": 0,
                "skill_executions": 0,
                "memory_ops": 0,
                "workspace_uri": "default",
            },
        }

    def _ensure_today(self) -> str:
        """Ensure today's entry exists and return today's date key."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._stats["daily"]:
            self._stats["daily"][today] = {
                "tool_calls": 0,
                "tool_successes": 0,
                "tool_failures": 0,
                "tool_duration_ms": 0,
                "skill_executions": 0,
                "skill_successes": 0,
                "skill_failures": 0,
                "skill_duration_ms": 0,
                "memory_reads": 0,
                "memory_writes": 0,
                "lines_written": 0,
                "sessions": 0,
                "tools_used": {},  # tool_name -> count
                "skills_run": {},  # skill_name -> count
            }
            # Cleanup old daily stats (keep 30 days)
            self._cleanup_old_daily()
        return today

    def _cleanup_old_daily(self) -> None:
        """Remove daily stats older than 30 days."""
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        old_dates = [d for d in self._stats["daily"] if d < cutoff]
        for date in old_dates:
            del self._stats["daily"][date]

    def _save_stats(self) -> None:
        """Save stats to disk."""
        try:
            STATS_DIR.mkdir(parents=True, exist_ok=True)
            self._stats["last_updated"] = datetime.now().isoformat()
            tmp_file = STATS_FILE.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(self._stats, f, indent=2)
            tmp_file.rename(STATS_FILE)
        except Exception as e:
            logger.warning(f"Failed to save stats: {e}")

    # =========================================================================
    # Tool Tracking
    # =========================================================================

    def _ensure_workspace(self, workspace_uri: str) -> dict:
        """Ensure workspace entry exists and return it."""
        if "workspaces" not in self._stats:
            self._stats["workspaces"] = {}

        if workspace_uri not in self._stats["workspaces"]:
            self._stats["workspaces"][workspace_uri] = {
                "tool_calls": 0,
                "tool_successes": 0,
                "tool_failures": 0,
                "skill_executions": 0,
                "skill_successes": 0,
                "skill_failures": 0,
                "memory_reads": 0,
                "memory_writes": 0,
                "lines_written": 0,
                "first_seen": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
            }
        return self._stats["workspaces"][workspace_uri]

    def record_tool_call(
        self,
        tool_name: str,
        success: bool,
        duration_ms: int = 0,
        workspace_uri: str | None = None,
    ) -> None:
        """Record a tool call.

        Args:
            tool_name: Name of the tool called.
            success: Whether the call succeeded.
            duration_ms: Duration in milliseconds.
            workspace_uri: Workspace URI for workspace-specific tracking.
        """
        with self._stats_lock:
            # Reload stats from disk to avoid overwriting changes from other processes
            self._stats = self._load_stats()
            today = self._ensure_today()
            ws_uri = workspace_uri or get_current_workspace()

            # Lifetime stats
            self._stats["lifetime"]["tool_calls"] += 1
            self._stats["lifetime"]["tool_duration_ms"] += duration_ms
            if success:
                self._stats["lifetime"]["tool_successes"] += 1
            else:
                self._stats["lifetime"]["tool_failures"] += 1

            # Daily stats
            self._stats["daily"][today]["tool_calls"] += 1
            self._stats["daily"][today]["tool_duration_ms"] += duration_ms
            if success:
                self._stats["daily"][today]["tool_successes"] += 1
            else:
                self._stats["daily"][today]["tool_failures"] += 1

            # Workspace stats
            ws_stats = self._ensure_workspace(ws_uri)
            ws_stats["tool_calls"] += 1
            ws_stats["last_active"] = datetime.now().isoformat()
            if success:
                ws_stats["tool_successes"] += 1
            else:
                ws_stats["tool_failures"] += 1

            # Per-tool stats
            if tool_name not in self._stats["tools"]:
                self._stats["tools"][tool_name] = {
                    "calls": 0,
                    "successes": 0,
                    "failures": 0,
                    "duration_ms": 0,
                }
            self._stats["tools"][tool_name]["calls"] += 1
            self._stats["tools"][tool_name]["duration_ms"] += duration_ms
            if success:
                self._stats["tools"][tool_name]["successes"] += 1
            else:
                self._stats["tools"][tool_name]["failures"] += 1

            # Daily per-tool
            if tool_name not in self._stats["daily"][today]["tools_used"]:
                self._stats["daily"][today]["tools_used"][tool_name] = 0
            self._stats["daily"][today]["tools_used"][tool_name] += 1

            # Session stats
            self._stats["current_session"]["tool_calls"] += 1

            self._save_stats()

    # =========================================================================
    # Skill Tracking
    # =========================================================================

    def record_skill_execution(
        self,
        skill_name: str,
        success: bool,
        duration_ms: int = 0,
        steps_completed: int = 0,
        total_steps: int = 0,
    ) -> None:
        """Record a skill execution."""
        with self._stats_lock:
            # Reload stats from disk to avoid overwriting changes from other processes
            self._stats = self._load_stats()
            today = self._ensure_today()

            # Lifetime stats
            self._stats["lifetime"]["skill_executions"] += 1
            self._stats["lifetime"]["skill_duration_ms"] += duration_ms
            if success:
                self._stats["lifetime"]["skill_successes"] += 1
            else:
                self._stats["lifetime"]["skill_failures"] += 1

            # Daily stats
            self._stats["daily"][today]["skill_executions"] += 1
            self._stats["daily"][today]["skill_duration_ms"] += duration_ms
            if success:
                self._stats["daily"][today]["skill_successes"] += 1
            else:
                self._stats["daily"][today]["skill_failures"] += 1

            # Per-skill stats
            if skill_name not in self._stats["skills"]:
                self._stats["skills"][skill_name] = {
                    "executions": 0,
                    "successes": 0,
                    "failures": 0,
                    "duration_ms": 0,
                }
            self._stats["skills"][skill_name]["executions"] += 1
            self._stats["skills"][skill_name]["duration_ms"] += duration_ms
            if success:
                self._stats["skills"][skill_name]["successes"] += 1
            else:
                self._stats["skills"][skill_name]["failures"] += 1

            # Daily per-skill
            if skill_name not in self._stats["daily"][today]["skills_run"]:
                self._stats["daily"][today]["skills_run"][skill_name] = 0
            self._stats["daily"][today]["skills_run"][skill_name] += 1

            # Session stats
            self._stats["current_session"]["skill_executions"] += 1

            self._save_stats()

    # =========================================================================
    # Memory Tracking
    # =========================================================================

    def record_memory_read(self, key: str = "") -> None:
        """Record a memory read operation."""
        with self._stats_lock:
            self._stats = self._load_stats()
            today = self._ensure_today()
            self._stats["lifetime"]["memory_reads"] += 1
            self._stats["daily"][today]["memory_reads"] += 1
            self._stats["current_session"]["memory_ops"] += 1
            self._save_stats()

    def record_memory_write(self, key: str = "") -> None:
        """Record a memory write operation."""
        with self._stats_lock:
            self._stats = self._load_stats()
            today = self._ensure_today()
            self._stats["lifetime"]["memory_writes"] += 1
            self._stats["daily"][today]["memory_writes"] += 1
            self._stats["current_session"]["memory_ops"] += 1
            self._save_stats()

    # =========================================================================
    # Code Tracking
    # =========================================================================

    def record_lines_written(self, lines: int) -> None:
        """Record lines of code written."""
        with self._stats_lock:
            self._stats = self._load_stats()
            today = self._ensure_today()
            self._stats["lifetime"]["lines_written"] += lines
            self._stats["daily"][today]["lines_written"] += lines
            self._save_stats()

    # =========================================================================
    # Session Tracking
    # =========================================================================

    def start_session(self) -> None:
        """Start a new session."""
        with self._stats_lock:
            self._stats = self._load_stats()
            today = self._ensure_today()
            self._stats["lifetime"]["sessions"] += 1
            self._stats["daily"][today]["sessions"] += 1
            self._stats["current_session"] = {
                "started": datetime.now().isoformat(),
                "tool_calls": 0,
                "skill_executions": 0,
                "memory_ops": 0,
            }
            self._save_stats()

    # =========================================================================
    # Getters
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get all stats."""
        with self._stats_lock:
            self._ensure_today()
            return self._stats.copy()

    def get_today_stats(self) -> dict[str, Any]:
        """Get today's stats."""
        with self._stats_lock:
            today = self._ensure_today()
            return self._stats["daily"][today].copy()

    def get_lifetime_stats(self) -> dict[str, Any]:
        """Get lifetime stats."""
        with self._stats_lock:
            return self._stats["lifetime"].copy()

    def get_session_stats(self) -> dict[str, Any]:
        """Get current session stats."""
        with self._stats_lock:
            return self._stats["current_session"].copy()

    def get_top_tools(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get top tools by call count."""
        with self._stats_lock:
            tools = self._stats.get("tools", {})
            sorted_tools = sorted(
                tools.items(),
                key=lambda x: x[1].get("calls", 0),
                reverse=True,
            )
            return [(name, data["calls"]) for name, data in sorted_tools[:limit]]

    def get_top_skills(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get top skills by execution count."""
        with self._stats_lock:
            skills = self._stats.get("skills", {})
            sorted_skills = sorted(
                skills.items(),
                key=lambda x: x[1].get("executions", 0),
                reverse=True,
            )
            return [(name, data["executions"]) for name, data in sorted_skills[:limit]]

    def get_daily_trend(self, days: int = 7) -> list[dict[str, Any]]:
        """Get daily stats for the last N days."""
        with self._stats_lock:
            result = []
            for i in range(days - 1, -1, -1):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                if date in self._stats["daily"]:
                    result.append({"date": date, **self._stats["daily"][date]})
                else:
                    result.append(
                        {
                            "date": date,
                            "tool_calls": 0,
                            "skill_executions": 0,
                            "memory_reads": 0,
                            "memory_writes": 0,
                            "lines_written": 0,
                        }
                    )
            return result

    def get_summary(self) -> dict[str, Any]:
        """Get a summary suitable for display."""
        with self._stats_lock:
            today = self._ensure_today()
            lifetime = self._stats["lifetime"]
            today_stats = self._stats["daily"][today]
            session = self._stats["current_session"]

            return {
                "lifetime": {
                    "tool_calls": lifetime["tool_calls"],
                    "tool_success_rate": (
                        round(lifetime["tool_successes"] / lifetime["tool_calls"] * 100, 1)
                        if lifetime["tool_calls"] > 0
                        else 0
                    ),
                    "skill_executions": lifetime["skill_executions"],
                    "skill_success_rate": (
                        round(lifetime["skill_successes"] / lifetime["skill_executions"] * 100, 1)
                        if lifetime["skill_executions"] > 0
                        else 0
                    ),
                    "memory_ops": lifetime["memory_reads"] + lifetime["memory_writes"],
                    "lines_written": lifetime["lines_written"],
                    "sessions": lifetime["sessions"],
                },
                "today": {
                    "tool_calls": today_stats["tool_calls"],
                    "skill_executions": today_stats["skill_executions"],
                    "memory_ops": today_stats["memory_reads"] + today_stats["memory_writes"],
                    "lines_written": today_stats["lines_written"],
                },
                "session": {
                    "started": session["started"],
                    "tool_calls": session["tool_calls"],
                    "skill_executions": session["skill_executions"],
                    "memory_ops": session["memory_ops"],
                },
                "top_tools": self.get_top_tools(5),
                "top_skills": self.get_top_skills(5),
            }


# Global instance
_stats: AgentStats | None = None


def get_agent_stats() -> AgentStats:
    """Get the global agent stats instance."""
    global _stats
    if _stats is None:
        _stats = AgentStats()
    return _stats


# Convenience functions
def record_tool_call(tool_name: str, success: bool, duration_ms: int = 0, workspace_uri: str | None = None) -> None:
    """Record a tool call."""
    get_agent_stats().record_tool_call(tool_name, success, duration_ms, workspace_uri)


def record_skill_execution(
    skill_name: str,
    success: bool,
    duration_ms: int = 0,
    steps_completed: int = 0,
    total_steps: int = 0,
    workspace_uri: str | None = None,
) -> None:
    """Record a skill execution."""
    get_agent_stats().record_skill_execution(skill_name, success, duration_ms, steps_completed, total_steps)


def record_memory_read(key: str = "", workspace_uri: str | None = None) -> None:
    """Record a memory read."""
    get_agent_stats().record_memory_read(key)


def record_memory_write(key: str = "", workspace_uri: str | None = None) -> None:
    """Record a memory write."""
    get_agent_stats().record_memory_write(key)


def record_lines_written(lines: int, workspace_uri: str | None = None) -> None:
    """Record lines written."""
    get_agent_stats().record_lines_written(lines)


def get_workspace_stats(workspace_uri: str) -> dict:
    """Get stats for a specific workspace."""
    stats = get_agent_stats()
    with stats._stats_lock:
        return stats._ensure_workspace(workspace_uri).copy()


def start_session() -> None:
    """Start a new session."""
    get_agent_stats().start_session()
