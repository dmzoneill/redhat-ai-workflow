#!/usr/bin/env python3
"""
Memory Daemon - Centralized memory/state service.

A standalone service that owns and caches all memory files:
- memory/state/*.yaml - current_work, environments, knowledge
- memory/learned/*.yaml - patterns, tool_failures
- memory/sessions/*.yaml - session logs
- memory/knowledge/ - persona knowledge

All consumers (UI, MCP server, skills engine, tools) query this daemon
via D-Bus instead of reading files directly.

Features:
- In-memory caching with file watchers for invalidation
- Single source of truth for memory state
- D-Bus IPC for external queries
- Read/Write/Append operations
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.memory                # Run daemon
    python -m services.memory --status       # Check if running
    python -m services.memory --stop         # Stop running daemon
    python -m services.memory --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-memory
    systemctl --user status bot-memory
    systemctl --user stop bot-memory

D-Bus:
    Service: com.aiworkflow.Memory
    Path: /com/aiworkflow/Memory
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase

# Memory directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"

logger = logging.getLogger(__name__)


class MemoryDaemon(DaemonDBusBase, BaseDaemon):
    """Memory daemon with D-Bus support - owns all memory/state files."""

    # BaseDaemon configuration
    name = "memory"
    description = "Memory Daemon - Centralized memory/state service"

    # D-Bus configuration
    service_name = "com.aiworkflow.Memory"
    object_path = "/com/aiworkflow/Memory"
    interface_name = "com.aiworkflow.Memory"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)

        # Caches
        self._file_cache: dict[str, dict] = {}  # path -> {content, mtime}
        self._max_file_cache_size = 100  # Prevent unbounded memory growth
        self._health_cache: dict | None = None
        self._files_cache: dict | None = None

        # Cache timestamps
        self._health_loaded_at: datetime | None = None
        self._files_loaded_at: datetime | None = None

        # File watchers
        self._watchers: list = []

        # Register D-Bus handlers
        self.register_handler("get_health", self._handle_get_health)
        self.register_handler("get_files", self._handle_get_files)
        self.register_handler("get_current_work", self._handle_get_current_work)
        self.register_handler("get_environments", self._handle_get_environments)
        self.register_handler("get_patterns", self._handle_get_patterns)
        self.register_handler("get_learned_patterns", self._handle_get_learned_patterns)
        self.register_handler("get_tool_fixes", self._handle_get_tool_fixes)
        self.register_handler("get_session_logs", self._handle_get_session_logs)
        self.register_handler("get_memory_dir", self._handle_get_memory_dir)
        self.register_handler("read", self._handle_read)
        self.register_handler("write", self._handle_write)
        self.register_handler("append", self._handle_append)
        self.register_handler("get_state", self._handle_get_state)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return memory-specific statistics."""
        return {
            "cached_files": len(self._file_cache),
            "health_loaded_at": self._health_loaded_at.isoformat() if self._health_loaded_at else None,
            "files_loaded_at": self._files_loaded_at.isoformat() if self._files_loaded_at else None,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        stats = await self.get_service_stats()
        return {
            "status": "running" if self.is_running else "stopped",
            "memory_dir": str(MEMORY_DIR),
            "memory_dir_exists": MEMORY_DIR.exists(),
            **stats,
        }

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full daemon state for UI."""
        stats = await self.get_service_stats()
        return {
            "success": True,
            "state": {
                **stats,
                "running": True,
            },
        }

    async def _handle_get_health(self, **kwargs) -> dict:
        """Get memory health statistics."""
        try:
            health = self._calculate_health()
            return {"success": True, "health": health}
        except Exception as e:
            logger.error(f"Failed to get health: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_files(self, **kwargs) -> dict:
        """Get list of memory files by category."""
        try:
            files = self._get_files_list()
            return {"success": True, "files": files}
        except Exception as e:
            logger.error(f"Failed to get files: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_current_work(self, **kwargs) -> dict:
        """Get current work state."""
        try:
            content = self._read_yaml("state/current_work")
            if content:
                return {
                    "success": True,
                    "work": {
                        "activeIssue": content.get("active_issues", [{}])[0] if content.get("active_issues") else None,
                        "activeMR": content.get("open_mrs", [{}])[0] if content.get("open_mrs") else None,
                        "followUps": content.get("follow_ups", []),
                        "activeIssues": content.get("active_issues", []),
                        "openMRs": content.get("open_mrs", []),
                    },
                }
            return {"success": True, "work": {}}
        except Exception as e:
            logger.error(f"Failed to get current work: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_environments(self, **kwargs) -> dict:
        """Get environment statuses."""
        try:
            content = self._read_yaml("state/environments")
            if content:
                environments = []
                for env_name, env_data in content.items():
                    if isinstance(env_data, dict):
                        environments.append(
                            {
                                "name": env_name,
                                "status": env_data.get("status", "unknown"),
                                "lastChecked": env_data.get("last_checked", ""),
                                "namespace": env_data.get("namespace", ""),
                            }
                        )
                return {"success": True, "environments": environments}
            return {"success": True, "environments": []}
        except Exception as e:
            logger.error(f"Failed to get environments: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_patterns(self, **kwargs) -> dict:
        """Get learned patterns."""
        try:
            content = self._read_yaml("learned/patterns")
            if content:
                patterns = []
                for pattern_type, pattern_list in content.items():
                    if isinstance(pattern_list, list):
                        for p in pattern_list:
                            if isinstance(p, dict):
                                patterns.append(
                                    {
                                        "type": pattern_type,
                                        "pattern": p.get("pattern", p.get("job", "")),
                                        "count": p.get("count", 1),
                                        "lastUsed": p.get("last_seen", ""),
                                    }
                                )
                return {"success": True, "patterns": patterns}
            return {"success": True, "patterns": []}
        except Exception as e:
            logger.error(f"Failed to get patterns: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_learned_patterns(self, **kwargs) -> dict:
        """Get learned patterns in UI-friendly format."""
        try:
            content = self._read_yaml("learned/patterns")
            if content:
                patterns = []
                idx = 0
                # Process pattern categories that are useful for the UI
                pattern_categories = [
                    "error_patterns",
                    "auth_patterns",
                    "pipeline_patterns",
                    "bonfire_patterns",
                    "concur_patterns",
                ]
                for pattern_type in pattern_categories:
                    pattern_list = content.get(pattern_type, [])
                    if isinstance(pattern_list, list):
                        for p in pattern_list:
                            if isinstance(p, dict):
                                # Get usage stats if available
                                usage_stats = p.get("usage_stats", {})
                                patterns.append(
                                    {
                                        "id": f"{pattern_type}_{idx}",
                                        "pattern": p.get("pattern", ""),
                                        "context": pattern_type.replace("_", " ").title(),
                                        "learned_at": usage_stats.get("last_matched", p.get("last_seen", "")),
                                        "usage_count": usage_stats.get("times_matched", p.get("count", 1)),
                                        "meaning": p.get("meaning", ""),
                                        "fix": p.get("fix", ""),
                                    }
                                )
                                idx += 1
                return {"success": True, "patterns": patterns}
            return {"success": True, "patterns": []}
        except Exception as e:
            logger.error(f"Failed to get learned patterns: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_tool_fixes(self, **kwargs) -> dict:
        """Get tool fixes from tool_failures.yaml."""
        try:
            content = self._read_yaml("learned/tool_failures")
            fixes = []
            if content:
                # Get learned_fixes section
                learned_fixes = content.get("learned_fixes", [])
                for fix in learned_fixes:
                    if isinstance(fix, dict):
                        fixes.append(
                            {
                                "id": f"fix_{fix.get('tool', 'unknown')}_{len(fixes)}",
                                "tool_name": fix.get("tool", "unknown"),
                                "error_pattern": fix.get("error_pattern", ""),
                                "fix_description": fix.get("fix", ""),
                                "learned_at": fix.get("learned_at", ""),
                                "applied_count": 1 if fix.get("verified") else 0,
                                "root_cause": fix.get("root_cause", ""),
                                "verified": fix.get("verified", False),
                            }
                        )
            return {"success": True, "fixes": fixes}
        except Exception as e:
            logger.error(f"Failed to get tool fixes: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_session_logs(self, limit: int = 20, **kwargs) -> dict:
        """Get recent session logs."""
        try:
            logs = []
            sessions_dir = MEMORY_DIR / "sessions"
            if sessions_dir.exists():
                # Get recent session files
                session_files = sorted(sessions_dir.glob("*.yaml"), key=lambda f: f.stat().st_mtime, reverse=True)[
                    :limit
                ]

                for session_file in session_files:
                    try:
                        content = yaml.safe_load(session_file.read_text())
                        if content:
                            # Extract log entries from session - handle both 'logs' and 'entries' keys
                            session_logs = content.get("logs", content.get("entries", []))
                            session_date = content.get("date", session_file.stem)

                            for log in session_logs[-5:]:  # Last 5 from each session
                                if isinstance(log, dict):
                                    # Build timestamp from date + time if available
                                    timestamp = log.get("timestamp", "")
                                    if not timestamp and log.get("time"):
                                        timestamp = f"{session_date} {log.get('time')}"

                                    logs.append(
                                        {
                                            "timestamp": timestamp,
                                            "session_id": session_file.stem,
                                            "session_name": content.get("name", session_date),
                                            "action": log.get("action", log.get("type", "")),
                                            "details": log.get("details", log.get("message", "")),
                                        }
                                    )
                    except Exception as e:
                        logger.debug(f"Failed to read session {session_file}: {e}")

            # Sort by timestamp descending
            logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return {"success": True, "logs": logs[:limit]}
        except Exception as e:
            logger.error(f"Failed to get session logs: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_memory_dir(self, **kwargs) -> dict:
        """Get the memory directory path."""
        return {"success": True, "path": str(MEMORY_DIR)}

    async def _handle_read(self, path: str = None, **kwargs) -> dict:
        """Read a memory file."""
        if not path:
            return {"success": False, "error": "path required"}

        try:
            content = self._read_yaml(path)
            return {"success": True, "content": content}
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_write(self, path: str = None, content: Any = None, **kwargs) -> dict:
        """Write a memory file."""
        if not path:
            return {"success": False, "error": "path required"}

        try:
            self._write_yaml(path, content)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to write {path}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_append(self, path: str = None, key: str = None, value: Any = None, **kwargs) -> dict:
        """Append to a list in a memory file."""
        if not path or not key:
            return {"success": False, "error": "path and key required"}

        try:
            content = self._read_yaml(path) or {}
            if key not in content:
                content[key] = []
            if isinstance(content[key], list):
                # Parse value if it's a JSON string
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                content[key].append(value)
            self._write_yaml(path, content)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to append to {path}: {e}")
            return {"success": False, "error": str(e)}

    # ==================== File Operations ====================

    def _get_file_path(self, relative_path: str) -> Path:
        """Get absolute path for a relative memory path."""
        # Remove .yaml extension if present (we'll add it)
        if relative_path.endswith(".yaml"):
            relative_path = relative_path[:-5]
        return MEMORY_DIR / f"{relative_path}.yaml"

    def _read_yaml(self, relative_path: str) -> dict | None:
        """Read and cache a YAML file."""
        file_path = self._get_file_path(relative_path)

        # Check cache
        if relative_path in self._file_cache:
            cached = self._file_cache[relative_path]
            if file_path.exists():
                current_mtime = file_path.stat().st_mtime
                if cached["mtime"] == current_mtime:
                    return cached["content"]

        # Read file
        if not file_path.exists():
            return None

        try:
            content = yaml.safe_load(file_path.read_text())
            # Enforce cache size limit
            if len(self._file_cache) >= self._max_file_cache_size:
                # Remove oldest entry (first key in dict - Python 3.7+ maintains order)
                oldest_key = next(iter(self._file_cache))
                del self._file_cache[oldest_key]
            self._file_cache[relative_path] = {
                "content": content,
                "mtime": file_path.stat().st_mtime,
            }
            return content
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return None

    def _write_yaml(self, relative_path: str, content: Any):
        """Write a YAML file and update cache."""
        file_path = self._get_file_path(relative_path)

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(file_path, "w") as f:
            yaml.safe_dump(content, f, default_flow_style=False, allow_unicode=True)

        # Update cache
        self._file_cache[relative_path] = {
            "content": content,
            "mtime": file_path.stat().st_mtime,
        }

    def _calculate_health(self) -> dict:
        """Calculate memory health statistics."""
        total_size = 0
        session_logs = 0
        patterns = 0
        last_session = ""

        if MEMORY_DIR.exists():
            # Calculate total size
            for f in MEMORY_DIR.rglob("*.yaml"):
                try:
                    total_size += f.stat().st_size
                except Exception:
                    pass

            # Count session logs
            sessions_dir = MEMORY_DIR / "sessions"
            if sessions_dir.exists():
                session_files = list(sessions_dir.glob("*.yaml"))
                session_logs = len(session_files)
                if session_files:
                    # Get most recent session
                    session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    last_session = session_files[0].stem

            # Count patterns
            patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
            if patterns_file.exists():
                try:
                    content = yaml.safe_load(patterns_file.read_text())
                    if content:
                        for v in content.values():
                            if isinstance(v, list):
                                patterns += len(v)
                except Exception:
                    pass

        # Format size
        if total_size > 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"
        elif total_size > 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        else:
            size_str = f"{total_size} B"

        self._health_cache = {
            "totalSize": size_str,
            "totalSizeBytes": total_size,
            "sessionLogs": session_logs,
            "lastSession": last_session,
            "patterns": patterns,
        }
        self._health_loaded_at = datetime.now()
        return self._health_cache

    def _get_files_list(self) -> dict:
        """Get list of memory files by category."""
        result = {
            "state": [],
            "learned": [],
            "sessions": [],
            "knowledge": [],
        }

        if not MEMORY_DIR.exists():
            return result

        # State files
        state_dir = MEMORY_DIR / "state"
        if state_dir.exists():
            result["state"] = [f.stem for f in state_dir.glob("*.yaml")]

        # Learned files
        learned_dir = MEMORY_DIR / "learned"
        if learned_dir.exists():
            result["learned"] = [f.stem for f in learned_dir.glob("*.yaml")]

        # Session files (limited to recent)
        sessions_dir = MEMORY_DIR / "sessions"
        if sessions_dir.exists():
            session_files = sorted(sessions_dir.glob("*.yaml"), key=lambda f: f.stat().st_mtime, reverse=True)
            result["sessions"] = [f.stem for f in session_files[:20]]

        # Knowledge files
        knowledge_dir = MEMORY_DIR / "knowledge" / "personas"
        if knowledge_dir.exists():
            for persona_dir in knowledge_dir.iterdir():
                if persona_dir.is_dir():
                    for f in persona_dir.glob("*.yaml"):
                        result["knowledge"].append(
                            {
                                "persona": persona_dir.name,
                                "file": f.stem,
                            }
                        )

        self._files_cache = result
        self._files_loaded_at = datetime.now()
        return result

    # ==================== File Watching ====================

    async def _watch_directory(self, directory: Path):
        """Watch a directory for changes and invalidate cache."""
        try:
            from watchfiles import awatch

            logger.info(f"Starting file watcher for {directory}")
            async for changes in awatch(directory):
                logger.info(f"Detected changes in {directory}: {len(changes)} files")
                # Invalidate affected cache entries
                for _change_type, change_path in changes:
                    rel_path = Path(change_path).relative_to(MEMORY_DIR)
                    cache_key = str(rel_path).replace(".yaml", "")
                    if cache_key in self._file_cache:
                        del self._file_cache[cache_key]
                # Invalidate health/files cache
                self._health_cache = None
                self._files_cache = None
        except ImportError:
            logger.warning("watchfiles not installed - file watching disabled")
        except Exception as e:
            logger.error(f"File watcher error for {directory}: {e}")

    async def _start_file_watchers(self):
        """Start file watchers for memory directories."""
        try:
            if MEMORY_DIR.exists():
                import asyncio as _asyncio

                self._watchers.append(_asyncio.create_task(self._watch_directory(MEMORY_DIR)))
        except Exception as e:
            logger.warning(f"Failed to start file watchers: {e}")

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Memory daemon starting...")

        # Pre-load caches
        self._calculate_health()
        self._get_files_list()

        # Start file watchers
        await self._start_file_watchers()

        # Start D-Bus service if enabled
        if self.enable_dbus:
            try:
                await self.start_dbus()
                logger.info(f"D-Bus service started: {self.service_name}")
            except Exception as e:
                logger.error(f"Failed to start D-Bus: {e}")

        self.is_running = True
        logger.info("Memory daemon ready")

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Memory daemon shutting down...")

        # Cancel file watchers
        for watcher in self._watchers:
            watcher.cancel()

        # Stop D-Bus
        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Memory daemon stopped")

    async def health_check(self) -> dict:
        """Perform a health check on the memory daemon."""
        self._last_health_check = time.time()

        checks = {
            "running": self.is_running,
            "memory_dir_exists": MEMORY_DIR.exists(),
            "cache_populated": len(self._file_cache) > 0,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": "Memory daemon is healthy" if healthy else "Memory daemon has issues",
            "timestamp": self._last_health_check,
        }


if __name__ == "__main__":
    MemoryDaemon.main()
