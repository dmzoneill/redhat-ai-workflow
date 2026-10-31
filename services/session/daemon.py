"""
Session Daemon - Cursor Session State Manager

A standalone service that manages Cursor session state with real-time updates.
Designed to run as a systemd user service.

Features:
- Watches Cursor's database for session changes
- D-Bus IPC for external control and queries
- Full-text search of chat content
- Real-time state change notifications
- Periodic sync with workspace_states.json
- Systemd watchdog support

Usage:
    python -m services.session                # Run daemon
    python -m services.session --status       # Check if running
    python -m services.session --stop         # Stop running daemon
    python -m services.session --search "query"  # Search chats
    python -m services.session --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-session
    systemctl --user status bot-session
    systemctl --user stop bot-session

D-Bus:
    Service: com.aiworkflow.BotSession
    Path: /com/aiworkflow/BotSession

    Methods:
    - GetSessions() -> JSON list of sessions
    - SearchChats(query: str, limit: int) -> JSON search results
    - RefreshNow() -> Trigger immediate sync
    - GetState() -> Full workspace state JSON

    Signals:
    - StateChanged(change_type: str) - Emitted when sessions change
"""

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from server.config_manager import config as config_manager
from server.paths import CURSOR_WORKSPACE_STORAGE, SESSION_STATE_FILE
from server.workspace_state import WorkspaceRegistry
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon
from services.session import sync_work
from services.session.cursor_db import ActiveSessionScanner, search_chats, state_hash
from services.session.sync_work import EMPTY_RESULT, SessionTracker

logger = logging.getLogger(__name__)

# Errors one sync pass or handler can hit (file, database, registry and data errors).
SYNC_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
    sqlite3.Error,
)


@dataclass
class SyncIntervals:
    """Tiered sync intervals in seconds."""

    fast: float = 2.0  # Active session detection only (lightweight)
    recent: float = 10.0  # Full sync for the last N active sessions
    background: float = 120.0  # Incremental sync for all other sessions


@dataclass
class SyncStats:
    """Counters reported by get_service_stats and health_check."""

    sync_count: int = 0
    last_sync_time: float = 0
    search_count: int = 0
    last_state_hash: str = ""

    def record_sync(self) -> None:
        """Count a completed sync."""
        self.sync_count += 1
        self.last_sync_time = time.time()


def read_state_file() -> dict | None:
    """Contents of session_state.json, or None if it does not exist."""
    if not SESSION_STATE_FILE.exists():
        return None
    data: dict = json.loads(SESSION_STATE_FILE.read_text())
    return data


def configured_repo_paths() -> set[str]:
    """Resolved local paths of the repositories in config.json."""
    repos = config_manager.get("repositories", default={})
    return {str(Path(repo["path"]).resolve()) for repo in repos.values() if repo.get("path", "")}


class SessionDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main session daemon with D-Bus and sleep/wake support."""

    # BaseDaemon configuration
    name = "session"
    description = "Session Daemon - Cursor session state manager"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSession"
    object_path = "/com/aiworkflow/BotSession"
    interface_name = "com.aiworkflow.BotSession"

    def __init__(self, verbose: bool = False, enable_dbus: bool = True):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)

        self._stats = SyncStats()
        self._intervals = SyncIntervals()
        self._tracker = SessionTracker(max_recent=5, batch_size=10)
        self._scanner = ActiveSessionScanner(CURSOR_WORKSPACE_STORAGE)
        self._tasks: list[asyncio.Task] = []

        self.register_handler("search_chats", self._handle_search_chats)
        self.register_handler("get_sessions", self._handle_get_sessions)
        self.register_handler("refresh_now", self._handle_refresh_now)
        self.register_handler("get_state", self._handle_get_state)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("remove_workspace", self._handle_remove_workspace)

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return session-specific statistics."""
        return {
            "sync_count": self._stats.sync_count,
            "last_sync_time": self._stats.last_sync_time,
            "search_count": self._stats.search_count,
            "configured_workspaces": len(self._scanner.configured_paths),
            "sync_interval": self._intervals.background,
            "fast_sync_interval": self._intervals.fast,
            "recent_sync_interval": self._intervals.recent,
            "background_sync_interval": self._intervals.background,
            "recent_active_sessions": len(self._tracker.recent),
            "last_active_session": self._tracker.last_active,
        }

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()
        try:
            data = read_state_file()
        except (OSError, ValueError):
            service["session_count"] = 0
            service["workspace_count"] = 0
        else:
            if data is not None:
                service["session_count"] = data.get("session_count", 0)
                service["workspace_count"] = data.get("workspace_count", 0)
        return {**base, **service}

    async def health_check(self) -> dict:
        """Perform a health check on the session daemon."""
        now = time.time()
        self._last_health_check = now
        started = self.start_time or 0

        checks = {
            "running": self.is_running,
            "config_loaded": len(self._scanner.configured_paths) > 0,
            # Informational only, not required for health:
            "recent_sync": self._stats.last_sync_time > 0
            and (now - self._stats.last_sync_time) < self._intervals.background * 3,
            "uptime_ok": bool(started) and (now - started) > 5,
        }

        core_checks = ["running", "config_loaded"]
        healthy = all(checks.get(k, False) for k in core_checks)
        message = (
            "Session daemon is healthy"
            if healthy
            else f"Unhealthy: {[k for k in core_checks if not checks.get(k, False)]}"
        )
        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": now,
            "sync_count": self._stats.sync_count,
        }

    # ==================== D-Bus Method Handlers ====================

    async def _handle_search_chats(self, query: str, limit: int = 20) -> dict:
        """Search chat content across all configured workspaces."""
        self._stats.search_count += 1
        if not CURSOR_WORKSPACE_STORAGE.exists():
            return {"results": [], "query": query, "error": "Cursor storage not found"}
        try:
            results = await asyncio.to_thread(
                search_chats, CURSOR_WORKSPACE_STORAGE, query, self._scanner.configured_paths, limit
            )
        except SYNC_ERRORS as e:
            logger.error("Search error: %s", e)
            return {"results": [], "query": query, "error": str(e)}
        return {"results": results[:limit], "query": query, "total_found": len(results)}

    async def _handle_get_sessions(self) -> dict:
        """Get all sessions from session state."""
        try:
            data = await asyncio.to_thread(read_state_file)
        except (OSError, ValueError) as e:
            return {"sessions": [], "error": str(e)}
        if data is None:
            return {"sessions": [], "session_count": 0}
        return {
            "sessions": data.get("sessions", []),
            "session_count": data.get("session_count", 0),
            "updated_at": data.get("updated_at"),
        }

    async def _handle_refresh_now(self) -> dict:
        """Trigger immediate sync."""
        await self._do_sync()
        return {"success": True, "sync_count": self._stats.sync_count}

    async def _handle_get_state(self) -> dict:
        """Get full session state."""
        try:
            data = await asyncio.to_thread(read_state_file)
        except (OSError, ValueError) as e:
            return {"error": str(e)}
        return data if data is not None else {}

    async def _handle_write_state(self) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        await self._do_sync()
        return {"success": True, "file": str(SESSION_STATE_FILE)}

    async def _handle_remove_workspace(self, uri: str | None = None, **_kwargs) -> dict:
        """Remove a workspace from tracking.

        Args:
            uri: The workspace URI to remove

        Returns:
            dict with success status
        """
        if not uri:
            return {"success": False, "error": "uri required"}

        try:
            removed = await asyncio.to_thread(self._remove_workspace_work, uri)
            if not removed:
                return {"success": False, "error": f"Workspace {uri} not found"}
            await self._do_sync()
        except SYNC_ERRORS as e:
            logger.error("Failed to remove workspace %s: %s", uri, e)
            return {"success": False, "error": str(e)}

        logger.info("Removed workspace: %s", uri)
        return {"success": True, "message": f"Removed workspace: {uri}"}

    @staticmethod
    def _remove_workspace_work(uri: str) -> bool:
        WorkspaceRegistry.load_from_disk()
        if not WorkspaceRegistry.remove(uri):
            return False
        WorkspaceRegistry.save_to_disk()
        return True

    # ==================== Core Logic ====================

    def _load_configured_paths(self) -> None:
        """Load configured repository paths from config.json."""
        try:
            self._scanner.configured_paths = configured_repo_paths()
        except SYNC_ERRORS as e:
            logger.error("Failed to load config: %s", e)
            self._scanner.configured_paths = set()
            return
        logger.info("Loaded %d configured repository paths", len(self._scanner.configured_paths))

    async def _do_fast_sync(self) -> bool:
        """Fast sync: detect active session changes and session count changes.

        This is lightweight - just reads composer metadata, not chat content.
        A session count change (sessions added or deleted) triggers a full sync.

        Returns:
            True if active session changed or session count changed, False otherwise
        """
        try:
            active_sessions, session_count = await asyncio.to_thread(self._scanner.scan)
        except SYNC_ERRORS as e:
            logger.debug("Fast sync error: %s", e)
            return False

        changed = False
        last_count = self._tracker.last_session_count
        if last_count >= 0 and session_count != last_count:
            logger.info("Session count changed: %d -> %d, triggering full sync", last_count, session_count)
            await self._do_sync()
            changed = True
        self._tracker.last_session_count = session_count

        for session_id in active_sessions.values():
            if session_id and session_id != self._tracker.last_active:
                logger.debug("Active session changed: %s", session_id[:8])
                self._tracker.mark_active(session_id)
                changed = True
        return changed

    def _record_success(self) -> None:
        self._stats.record_sync()
        self.record_successful_operation()

    async def _do_recent_sync(self) -> dict:
        """Sync recent active sessions with full detail.

        Runs blocking I/O in a worker thread to keep the event loop
        responsive for watchdog pings.

        Returns:
            Sync result dict
        """
        if not self._tracker.recent:
            logger.debug("Recent sync: No recent sessions, skipping")
            return dict(EMPTY_RESULT)
        try:
            async with self._tracker.lock:
                sync_result = await asyncio.to_thread(sync_work.recent_sync, self._tracker)
        except SYNC_ERRORS as e:
            logger.exception("Recent sync error")
            self.record_failed_operation()
            return {"error": str(e)}
        self._record_success()
        logger.debug("Recent sync: %d sessions, %s", len(self._tracker.recent), sync_result)
        return sync_result

    async def _do_background_sync(self) -> dict:
        """Background sync: incremental sync of all other sessions, in batches.

        Returns:
            Sync result dict
        """
        try:
            async with self._tracker.lock:
                return await asyncio.to_thread(sync_work.background_sync, self._tracker)
        except SYNC_ERRORS as e:
            logger.exception("Background sync error")
            return {"error": str(e)}

    async def _do_initial_sync(self) -> None:
        """Initial lightweight sync - skips expensive content scanning."""
        try:
            session_count = await asyncio.to_thread(sync_work.initial_sync, self._scanner.configured_paths)
        except SYNC_ERRORS:
            logger.exception("Initial sync error")
            self.record_failed_operation()
            return
        self._record_success()
        logger.info("Initial sync complete: %d sessions", session_count)

    async def _do_sync(self) -> None:
        """Full sync - called on manual refresh or session count change."""
        try:
            async with self._tracker.lock:
                session_count, sync_result = await asyncio.to_thread(
                    sync_work.full_sync, self._scanner.configured_paths
                )
        except SYNC_ERRORS:
            logger.exception("Session sync error")
            self.record_failed_operation()
            return
        self._record_success()
        logger.debug("Full sync: %d sessions, %s", session_count, sync_result)

    async def _fast_sync_tick(self) -> None:
        if await self._do_fast_sync():
            logger.info("Active session changed, triggering recent sync...")
            await self._do_recent_sync()
            self.emit_event(
                "StateChanged",
                json.dumps({"type": "active_session_changed", "session_id": self._tracker.last_active}),
            )

    async def _fast_sync_loop(self) -> None:
        """Detect active session changes; trigger a recent sync when one changes."""
        logger.info("Starting fast sync loop (interval: %ss)", self._intervals.fast)
        while not self._shutdown_event.is_set():
            try:
                await self._fast_sync_tick()
                await asyncio.sleep(self._intervals.fast)
            except SYNC_ERRORS as e:
                logger.error("Fast sync loop error: %s", e)
                await asyncio.sleep(2)

    async def _periodic_loop(
        self, label: str, interval: float, job: Callable[[], Awaitable[object]], error_pause: float
    ) -> None:
        logger.info("Starting %s sync loop (interval: %ss)", label, interval)
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
                if self._shutdown_event.is_set():
                    break
                await job()
            except SYNC_ERRORS as e:
                logger.error("%s sync loop error: %s", label.capitalize(), e)
                await asyncio.sleep(error_pause)

    async def _recent_sync_loop(self) -> None:
        """Full-detail sync of the last N active sessions."""
        await self._periodic_loop("recent", self._intervals.recent, self._do_recent_sync, 5)

    async def _background_sync_loop(self) -> None:
        """Incremental sync of all sessions, in batches to avoid CPU spikes."""
        await self._periodic_loop("background", self._intervals.background, self._do_background_sync, 10)

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        logger.info("Session daemon starting...")
        self._load_configured_paths()

        logger.info("Running initial lightweight sync...")
        await self._do_initial_sync()
        self._stats.last_state_hash = await asyncio.to_thread(
            state_hash, CURSOR_WORKSPACE_STORAGE, self._scanner.configured_paths
        )

        if self.enable_dbus:
            await self.start_dbus()

        self.is_running = True

        self._tasks = [
            asyncio.create_task(self._fast_sync_loop()),
            asyncio.create_task(self._recent_sync_loop()),
            asyncio.create_task(self._background_sync_loop()),
        ]

        await self.start_sleep_monitor()

        logger.info(
            "Session daemon ready with tiered sync: fast=%ss, recent=%ss (top %d), background=%ss (batch %d)",
            self._intervals.fast,
            self._intervals.recent,
            self._tracker.max_recent,
            self._intervals.background,
            self._tracker.batch_size,
        )

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Session daemon shutting down...")

        await self.stop_sleep_monitor()

        pending = {task for task in self._tasks if not task.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending)

        if self.enable_dbus:
            await self.stop_dbus()

        self.is_running = False
        await super().shutdown()
        logger.info("Session daemon stopped")

    async def on_system_wake(self):
        """Handle system wake from sleep - refresh session state."""
        logger.info("System wake detected - triggering session refresh")
        await self._do_recent_sync()
        logger.info("Post-wake session refresh complete")


if __name__ == "__main__":
    SessionDaemon.main()
